"""HUD server: the React/Three.js front-end (and the desktop app) over the
same Assistant core.

One WebSocket (/ws) carries everything live:

  client -> server   binary frames: 16 kHz mono int16 mic audio (always-on)
                     JSON: text, listen, summon, interrupt, playback_done,
                     confirm, mic, settings
  server -> client   JSON: hello, state, wake, hearing, transcript, tool,
                     reply/say + audio segments, filler, barge_in, confirm,
                     confirm_done, notify, notice, voice, settings, card, hud

Listening works like a modern voice assistant (see audio/turns.py): the
client streams mic audio; this server spots the wake word, tracks speech
with a neural detector, shows a live transcript while you talk, and judges
at each pause whether you've finished or are mid-thought. While Jarvis
speaks it keeps listening for you to talk over it (barge-in). Replies are
spoken sentence by sentence so the first words arrive quickly. Mic audio
is processed in memory on this machine and never stored.

The confirmation gate is unchanged: a gated tool blocks its turn in
web_confirm() until the user answers by voice, by typing, or by clicking.

Single-user by design (it's your Mac) and bound to 127.0.0.1.
"""
import asyncio
import base64
import itertools
import json
import queue
import random
import re
import threading
from collections import deque
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, hud_bridge, moods, settings, tools
from .assistant import Assistant
from .audio.turns import CHUNK, TurnDetector, judge
from .tools import history, reminders, timers
from .voice import is_affirmative

FRONTEND_DIST = config.ROOT / "frontend" / "dist"
# Talking over Jarvis: 6 of the last 8 chunks (~640 ms) sound like speech,
# one of them clearly. Per-chunk scores are jumpy, so no "N in a row".
BARGE_WINDOW, BARGE_NEEDED = 8, 6


class VoicePipeline:
    """Wake word, turn-taking and Whisper, fed by the client's mic stream.

    mode: "off"    ignore audio (mic off, or Jarvis is thinking)
          "sleep"  listen only for the wake word
          "record" capture one turn for `purpose` ("chat" or "confirm")
          "watch"  Jarvis is speaking; listen only for the user talking
                   over it (barge-in)
    """

    def __init__(self, hub):
        self.hub = hub
        self.frames = queue.Queue(maxsize=400)
        self.mode = "off"
        self.purpose = "chat"
        self.turn = None
        self.vad = None
        self.detector = None
        self.mic_on = False
        self.ready = False      # speech-to-text loaded
        self.wake_ok = False    # wake-word model loaded
        self.error = None
        self.recent = deque(maxlen=8)
        self.barge_probs = deque(maxlen=BARGE_WINDOW)
        self.heard = None       # last "hearing" verdict sent to the HUD
        self._buf = np.zeros(0, dtype=np.int16)
        self._lock = threading.Lock()
        self._stt_busy = False
        self._check_waiting = None

    # -- lifecycle -------------------------------------------------------
    def load(self):
        """Load models in the background so the server starts instantly."""
        try:
            from .audio import stt
            from .audio.turns import SpeechDetector

            stt.warm()
            self.vad = SpeechDetector()
            self.ready = True
        except Exception as exc:  # noqa: BLE001 — surface in the HUD instead
            self.error = "Speech-to-text unavailable: {}".format(exc)
        try:
            from .audio.wake import WakeWordDetector

            self.detector = WakeWordDetector()
            self.wake_ok = True
        except Exception as exc:  # noqa: BLE001
            self.error = (self.error + " " if self.error else "") + \
                "Wake word unavailable: {}".format(exc)
        threading.Thread(target=self._worker, daemon=True, name="hud-voice").start()
        if self.hub.state == "idle":
            self.sleep()
        self.hub.emit(self.status())

    def status(self):
        return {
            "type": "voice", "ready": self.ready, "wake": self.wake_ok,
            "mic": self.mic_on, "error": self.error,
            "wake_word": config.WAKE_WORD_MODEL.replace("_", " "),
        }

    # -- control (any thread) -------------------------------------------
    def set_mic(self, on):
        self.mic_on = bool(on)
        if not self.mic_on:
            self._set_mode("off")
        elif self.hub.state == "idle":
            self.sleep()
        self.hub.emit(self.status())

    def sleep(self):
        """Back to waiting for the wake word (if we can hear it)."""
        self._set_mode("sleep" if self.wake_ok and self.mic_on else "off")

    def pause(self):
        self._set_mode("off")

    def watch(self):
        """Jarvis started speaking: listen for the user talking over it."""
        ok = self.ready and self.mic_on and settings.get()["barge_in"]
        self._set_mode("watch" if ok else "off")

    def listen(self, timeout, purpose, preroll=None, speaking=False):
        """Capture one turn right now, no wake word needed."""
        if not self.ready:
            self.hub.notice(self.error or "Voice is still loading. One moment.")
            return False
        if not self.mic_on:
            self.hub.notice("The microphone is off. Turn it on to talk to me.")
            return False
        patience = "snappy" if purpose == "confirm" else settings.get()["patience"]
        with self._lock:
            self.turn = TurnDetector(
                timeout, patience, detector=self.vad, preroll=preroll, speaking=speaking
            )
            self.purpose = purpose
            self.mode = "record"
            self.heard = None
            self._drain()
        self.hub.set_state("confirm" if purpose == "confirm" else "listening")
        return True

    def recording(self):
        return self.mode == "record"

    def _set_mode(self, mode):
        with self._lock:
            self.mode = mode
            if mode != "record":
                self.turn = None
            self.barge_probs.clear()
            self.recent.clear()
            self._drain()

    def _drain(self):
        self._buf = np.zeros(0, dtype=np.int16)
        try:
            while True:
                self.frames.get_nowait()
        except queue.Empty:
            pass

    # -- audio path ------------------------------------------------------
    def feed(self, data):
        if self.mode == "off":
            return
        try:
            self.frames.put_nowait(data)
        except queue.Full:
            pass  # falling behind; dropping audio beats growing latency

    def _worker(self):
        while True:
            data = self.frames.get()
            with self._lock:
                if self.mode == "off":
                    continue
                self._buf = np.concatenate(
                    [self._buf, np.frombuffer(data, dtype=np.int16)]
                )
                chunks = []
                while len(self._buf) >= CHUNK:
                    chunks.append(self._buf[:CHUNK].copy())
                    self._buf = self._buf[CHUNK:]
            for chunk in chunks:
                try:
                    if self._process(chunk):
                        break
                except Exception as exc:  # noqa: BLE001 — never kill the audio thread
                    print("[hud] voice pipeline error: {}".format(exc))

    def _process(self, chunk):
        """Returns True when the mode changed and remaining chunks are stale."""
        mode = self.mode
        if mode == "sleep" and self.detector is not None:
            if self.detector.detect(chunk):
                self.detector.reset()
                self.hub.on_wake()
                return True
        elif mode == "watch" and self.vad is not None:
            self.recent.append(chunk)
            self.barge_probs.append(self.vad.prob(chunk))
            probs = self.barge_probs
            if sum(p >= 0.5 for p in probs) >= BARGE_NEEDED and max(probs) >= 0.85:
                preroll = list(self.recent)
                self.hub.on_barge_in(preroll)
                return True
        elif mode == "record" and self.turn is not None:
            turn = self.turn
            result = turn.feed(chunk)
            if result == "timeout":
                purpose = self.purpose
                self.pause()
                self.hub.on_listen_timeout(purpose)
                return True
            if result in ("check", "live"):
                self._partial(turn, check=result == "check")
            elif result == "wait" and self.heard != "speaking" and turn.started and turn.quiet_run == 0:
                self.heard = "speaking"
                self.hub.emit({"type": "hearing", "verdict": "speaking"})
            if result == "done":
                text, purpose = turn.final_text(), self.purpose
                audio = turn.audio()
                self.pause()
                self.hub.set_state("thinking")
                self.hub.emit({"type": "hearing", "verdict": "done"})
                if text is None:
                    text = self._transcribe(audio)
                self.hub.on_utterance(text, purpose)
                return True
        return False

    def _transcribe(self, audio):
        from .audio import stt

        try:
            return stt.transcribe(audio)
        except Exception as exc:  # noqa: BLE001
            self.hub.notice("I couldn't transcribe that: {}".format(exc))
            return ""

    def _partial(self, turn, check):
        """Transcribe the turn so far, off the audio thread. A "check" also
        decides whether the user sounds finished; "live" only updates the
        on-screen transcript and is skipped when Whisper is busy."""
        if self._stt_busy:
            if check:
                self._check_waiting = turn
            return
        self._stt_busy = True
        audio = turn.audio()

        def job():
            text = self._transcribe(audio)
            if self.turn is turn:
                if check:
                    kind = judge(text)
                    turn.verdict(kind, text)
                    self.heard = kind
                    self.hub.emit({
                        "type": "hearing", "text": text, "verdict": kind,
                        "wait": turn.wait_limit(), "silence": turn.silence,
                    })
                elif text:
                    self.hub.emit({"type": "hearing", "text": text, "verdict": "speaking"})
            self._stt_busy = False
            waiting, self._check_waiting = self._check_waiting, None
            if waiting is not None and waiting is self.turn and waiting.pending == "checking":
                self._partial(waiting, check=True)   # the check deferred while busy

        threading.Thread(target=job, daemon=True, name="hud-partial").start()


_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _speech_segments(text):
    """First sentence alone (so speech starts fast), then the rest."""
    parts = [p for p in _SENTENCE.split(_speakable(text)) if p.strip()]
    if len(parts) <= 1:
        return parts or [text]
    return [parts[0], " ".join(parts[1:])]


class Hub:
    """Shared state for all connected HUD windows and the single assistant."""

    def __init__(self):
        self.loop = None
        self.outbox = None
        self.clients = set()
        self.mic_owner = None               # the one window whose mic we listen to
        self.assistant = None
        self.turn_lock = threading.Lock()   # one turn at a time
        self.state = "idle"
        self.confirm = None                 # {"prompt", "event", "answer"}
        self.after_playback = None          # "followup" | "confirm" | "idle"
        self.playing_id = None
        self.turn_source = None
        self.filler_sent = False
        self.interrupted = False
        self._ids = itertools.count(1)
        self._filler_cache = {}
        self.voice = VoicePipeline(self)

    # -- outbound (thread-safe, ordered) ---------------------------------
    def emit(self, msg):
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.outbox.put_nowait, msg)

    async def sender(self):
        while True:
            msg = await self.outbox.get()
            targets = list(self.clients)
            # Speech plays in one window only: the one you're talking to.
            if msg.pop("_to", None) == "speaker" and self.mic_owner in self.clients:
                targets = [self.mic_owner]
            try:
                data = json.dumps(msg)
            except (TypeError, ValueError) as exc:
                print("[hud] dropped unserializable {} message: {}".format(msg.get("type"), exc))
                continue
            for ws in targets:
                try:
                    await ws.send_text(data)
                except Exception:  # noqa: BLE001 — a closed window
                    self.clients.discard(ws)

    def set_state(self, state):
        self.state = state
        self.emit({"type": "state", "state": state})

    def notice(self, text):
        self.emit({"type": "notice", "text": text})

    def settings_msg(self):
        return {
            "type": "settings",
            "settings": settings.get(),
            "moods": {k: {"label": m["label"], "blurb": m["blurb"]} for k, m in moods.MOODS.items()},
            "voices": moods.installed_voices(),
            "voice": moods.current()["voice"],
        }

    def hello(self):
        return {
            "type": "hello",
            "state": self.state,
            "confirm": self.confirm["prompt"] if self.confirm else None,
            "voice": self.voice.status(),
            "settings": self.settings_msg(),
            "config": {
                "backend": config.LLM_BACKEND,
                "model": config.LLM_MODEL,
                "tts": config.TTS_PROVIDER,
                "stt": config.STT_PROVIDER,
                "google": config.GOOGLE_TOKEN_PATH.exists(),
                "tools": len(tools.TOOL_SCHEMAS),
            },
        }

    # -- speech out ------------------------------------------------------
    def _synth(self, text):
        from .audio import tts

        raw, mime = tts.synthesize(text)
        return base64.b64encode(raw).decode("ascii"), mime

    def say(self, text, kind, then, speak=True, extra=None):
        """Send text to the clients and, if speaking, its audio sentence by
        sentence. `then` runs once the client reports playback finished."""
        uid = next(self._ids)
        msg = {"type": kind, "id": uid, "text": text, "speak": speak}
        msg.update(extra or {})
        if not speak:
            self.emit(msg)
            self._after(then)
            return
        self.playing_id = uid
        self.after_playback = then
        if then != "confirm":
            self.set_state("speaking")
        self.voice.watch()
        self.emit(msg)
        segments = _speech_segments(text)
        for seq, segment in enumerate(segments):
            if self.playing_id != uid:
                return   # interrupted; don't bother synthesizing the rest
            audio = mime = None
            try:
                audio, mime = self._synth(segment)
            except Exception as exc:  # noqa: BLE001 — the client's own voice takes over
                print("[hud] TTS failed, client voice will be used: {}".format(exc))
            self.emit({
                "type": "audio", "id": uid, "seq": seq, "last": seq == len(segments) - 1,
                "audio": audio, "mime": mime, "text": segment, "_to": "speaker",
            })

    def filler(self):
        """A short "one moment" while a voice request runs slow tools."""
        mood = moods.current()
        phrase = random.choice(mood["fillers"])
        key = (mood["voice"], mood["speed"], mood["volume"], phrase)
        try:
            if key not in self._filler_cache:
                self._filler_cache[key] = self._synth(phrase)
            audio, mime = self._filler_cache[key]
        except Exception:  # noqa: BLE001 — fillers are optional
            return
        self.emit({"type": "filler", "text": phrase, "audio": audio, "mime": mime, "_to": "speaker"})

    def playback_done(self, uid=None):
        if uid is not None and uid != self.playing_id:
            return   # a stale report from an utterance that was replaced
        then, self.after_playback = self.after_playback, None
        self.playing_id = None
        if then is not None:
            self._after(then)

    def _after(self, then):
        if then == "confirm":
            if self.confirm and self.voice.mic_on and self.voice.ready:
                self.voice.listen(config.RECORD_START_TIMEOUT, "confirm")
            else:
                self.voice.pause()
            return
        if self.turn_lock.locked() and then != "followup":
            self.voice.pause()
            return  # an announcement finished mid-turn; the turn owns state
        if then == "followup" and self.voice.mic_on and self.voice.ready:
            self.voice.listen(config.FOLLOWUP_WINDOW, "chat")
            return
        self.set_state("idle")
        self.voice.sleep()

    # -- turns -----------------------------------------------------------
    def submit(self, text, source, speak=True):
        if not self.turn_lock.acquire(blocking=False):
            self.notice("Still working on your last request.")
            return
        threading.Thread(
            target=self._turn, args=(text, source, speak), daemon=True, name="hud-turn"
        ).start()

    def _turn(self, text, source, speak):
        error = False
        try:
            self.voice.pause()
            self.after_playback = None
            self.playing_id = None
            self.turn_source = source
            self.filler_sent = False
            self.emit({"type": "transcript", "role": "user", "text": text, "source": source})
            _log("user", text)
            self.set_state("thinking")
            if self.assistant is None:
                self.assistant = Assistant(confirm=self.web_confirm)
            prompt = text
            if self.interrupted:
                prompt = "(I cut off your previous reply before you finished it.) " + text
                self.interrupted = False
            reply = self.assistant.chat(prompt)
        except Exception as exc:  # noqa: BLE001 — config/API errors go to the HUD
            reply = "Something went wrong: {}".format(exc)
            error = True
        finally:
            self.turn_source = None
            self.turn_lock.release()
        _log("jarvis", reply)
        self.say(
            reply, kind="reply",
            then="followup" if source == "voice" else "idle",
            speak=speak and not error, extra={"error": error},
        )

    def web_confirm(self, prompt):
        """Called mid-turn by a gated tool. Blocks until answered (or 2 min)."""
        event = threading.Event()
        self.confirm = {"prompt": prompt, "event": event, "answer": False}
        self.set_state("confirm")
        self.emit({"type": "confirm", "prompt": prompt})
        headline = prompt.split("\n")[0]
        self.say(
            headline + " Say yes to confirm, or anything else to cancel.",
            kind="say", then="confirm", speak=settings.get()["speak"] or self.turn_source == "voice",
        )
        event.wait(timeout=120)
        answer = self.confirm["answer"]
        self.confirm = None
        self.after_playback = None
        self.playing_id = None
        self.voice.pause()
        self.emit({"type": "confirm_done", "yes": answer, "prompt": prompt})
        self.set_state("thinking")
        return answer

    def answer_confirm(self, yes):
        pending = self.confirm
        if pending is not None:
            pending["answer"] = bool(yes)
            pending["event"].set()

    # -- voice events ----------------------------------------------------
    def on_wake(self):
        self.emit({"type": "wake"})
        self.voice.listen(config.RECORD_START_TIMEOUT, "confirm" if self.confirm else "chat")

    def on_barge_in(self, preroll):
        """The user started talking over Jarvis: stop and listen."""
        self.emit({"type": "barge_in"})
        self.playing_id = None
        self.after_playback = None
        if not self.confirm:
            self.interrupted = True
        self.voice.listen(
            config.RECORD_START_TIMEOUT, "confirm" if self.confirm else "chat",
            preroll=preroll, speaking=True,
        )

    def on_listen_timeout(self, purpose):
        if purpose == "confirm" and self.confirm:
            self.set_state("confirm")   # still answerable by click or wake word
            self.voice.sleep()
            return
        self.set_state("idle")
        self.voice.sleep()

    def on_utterance(self, text, purpose):
        text = (text or "").strip()
        if purpose == "confirm":
            if text:
                self.emit({"type": "transcript", "role": "user", "text": text, "source": "voice"})
            self.answer_confirm(is_affirmative(text))
            return
        if not text:
            self.set_state("idle")
            self.voice.sleep()
            return
        self.submit(text, source="voice", speak=True)

    # -- background events ----------------------------------------------
    def on_tool(self, phase, name, args, is_error):
        preview = {k: (v if len(str(v)) < 120 else str(v)[:117] + "…") for k, v in args.items()}
        self.emit({"type": "tool", "phase": phase, "name": name, "args": preview, "ok": not is_error})
        if (phase == "start" and self.turn_source == "voice" and not self.filler_sent
                and settings.get()["fillers"] and not name.startswith(("hud_", "voice_"))):
            self.filler_sent = True
            self.filler()

    def on_settings(self, _snapshot, _changes):
        self.emit(self.settings_msg())

    def to_hud(self, event):
        self.emit(event)
        return bool(self.clients)

    def announce(self, kind, text):
        """Reminders and timers: show on the HUD, and speak if Jarvis is free."""
        self.emit({"type": "notify", "kind": kind, "text": text})
        if not self.turn_lock.locked() and self.state in ("idle", "listening"):
            self.voice.pause()
            self.say(text, kind="say", then="idle", speak=True)

    # -- inbound ---------------------------------------------------------
    def interrupt(self):
        """Client stopped playback; listen instead of talking."""
        self.after_playback = None
        self.playing_id = None
        if self.confirm:
            self.voice.listen(config.RECORD_START_TIMEOUT, "confirm")
            return
        if self.state == "speaking":
            self.interrupted = True
        if not self.turn_lock.locked():
            if not self.voice.listen(config.RECORD_START_TIMEOUT, "chat"):
                self.set_state("idle")

    def handle(self, data):
        kind = data.get("type")
        if kind == "text":
            text = (data.get("text") or "").strip()
            if not text:
                return
            if self.confirm:   # typing "yes"/"no" answers a pending confirmation
                self.emit({"type": "transcript", "role": "user", "text": text, "source": "text"})
                self.answer_confirm(is_affirmative(text))
                return
            speak = data.get("speak")
            self.submit(text, source="text", speak=settings.get()["speak"] if speak is None else bool(speak))
        elif kind in ("listen", "summon"):
            if self.state == "speaking":
                self.emit({"type": "barge_in"})
                self.interrupt()
            elif self.voice.recording():
                self.voice.pause()
                self.on_listen_timeout(self.voice.purpose)
            elif self.confirm:
                self.voice.listen(config.RECORD_START_TIMEOUT, "confirm")
            elif self.turn_lock.locked():
                self.notice("Still working on your last request.")
            else:
                self.after_playback = None
                self.voice.listen(config.RECORD_START_TIMEOUT, "chat")
        elif kind == "interrupt":
            self.interrupt()
        elif kind == "playback_done":
            self.playback_done(data.get("id"))
        elif kind == "confirm":
            self.answer_confirm(data.get("yes"))
        elif kind == "mic":
            self.voice.set_mic(data.get("on"))
        elif kind == "settings":
            try:
                settings.update(**(data.get("changes") or {}))
            except ValueError as exc:
                self.notice(str(exc))
        elif kind == "speak":   # older clients
            try:
                settings.update(speak=bool(data.get("on", True)))
            except ValueError:
                pass


def _speakable(text):
    """Strip characters TTS engines read out literally."""
    return text.replace("*", "").replace("#", "").replace("`", "").strip()


def _log(role, text):
    try:
        history.add(role, text)
    except Exception as exc:  # noqa: BLE001 — never fail a turn over logging
        print("[hud] history log failed: {}".format(exc))


hub = Hub()


@asynccontextmanager
async def lifespan(_app):
    hub.loop = asyncio.get_running_loop()
    hub.outbox = asyncio.Queue()
    sender = asyncio.create_task(hub.sender())
    tools.add_listener(hub.on_tool)
    settings.add_listener(hub.on_settings)
    hud_bridge.attach(hub.to_hud)
    reminders.start_scheduler(lambda msg: hub.announce("reminder", "Reminder: " + msg))
    timers.set_notifier(lambda label: hub.announce("timer", "Your {} is done.".format(label)))
    threading.Thread(target=hub.voice.load, daemon=True, name="hud-voice-load").start()
    yield
    sender.cancel()


app = FastAPI(title="Jarvis", lifespan=lifespan)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    hub.clients.add(ws)
    await ws.send_text(json.dumps(hub.hello()))
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                # With the app and a browser tab both open, mixing two mics
                # would garble everything: only the latest to turn its mic on counts.
                if ws is hub.mic_owner:
                    hub.voice.feed(msg["bytes"])
            elif msg.get("text"):
                try:
                    data = json.loads(msg["text"])
                except ValueError:
                    continue
                if data.get("type") == "mic":
                    if data.get("on"):
                        hub.mic_owner = ws
                    elif ws is not hub.mic_owner:
                        continue   # another window muting itself; ours stays live
                hub.handle(data)
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)
        if ws is hub.mic_owner:
            hub.mic_owner = None
            hub.voice.set_mic(False)
        if not hub.clients:
            # Nobody is left to play audio or report playback finishing.
            hub.voice.set_mic(False)
            hub.after_playback = None
            hub.playing_id = None
            if not hub.turn_lock.locked() and hub.confirm is None:
                hub.set_state("idle")


# ── REST: media ──────────────────────────────────────────────────────
class MediaIn(BaseModel):
    action: str


class VolumeIn(BaseModel):
    level: int


@app.get("/api/media")
def api_media():
    from .tools import mac

    return _safe(lambda: {"now": mac.now_playing_data(), "volume": mac.get_volume()})


@app.post("/api/media")
def api_media_action(body: MediaIn):
    from .tools import mac

    return _safe(lambda: mac.media(body.action))


@app.post("/api/volume")
def api_volume(body: VolumeIn):
    from .tools import mac

    return _safe(lambda: mac.set_volume(body.level))


@app.get("/api/settings")
def api_settings():
    return hub.settings_msg()


# ── REST: panel data ─────────────────────────────────────────────────
def _google(fn):
    if not config.GOOGLE_TOKEN_PATH.exists():
        return {"error": "not_connected"}
    try:
        return {"data": fn()}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _safe(fn):
    try:
        return {"data": fn()}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@app.get("/api/agenda")
def api_agenda(days: int = 2):
    from .tools import gcal

    return _google(lambda: gcal.events_data(days))


@app.get("/api/mail")
def api_mail():
    from .tools import gmail

    return _google(gmail.unread_data)


@app.get("/api/weather")
def api_weather():
    from .tools import weather

    return _safe(weather.data)


@app.get("/api/system")
def api_system():
    from .tools import system

    return _safe(system.data)


@app.get("/api/tasks")
def api_tasks():
    from .tools import tasks

    return _safe(tasks.rows)


class TaskIn(BaseModel):
    title: str
    due: str = None


@app.post("/api/tasks")
def api_task_add(body: TaskIn):
    from .tools import tasks

    return _safe(lambda: tasks.add(body.title, due=body.due or None))


@app.post("/api/tasks/{task_id}/complete")
def api_task_complete(task_id: int):
    from .tools import tasks

    return _safe(lambda: tasks.complete(task_id))


# UI deletes are direct user actions (the HUD asks "are you sure" itself),
# so they pass _confirmed=True — the model never reaches these endpoints.
@app.delete("/api/tasks/{task_id}")
def api_task_delete(task_id: int):
    from .tools import tasks

    return _safe(lambda: tasks.delete(task_id, _confirmed=True))


@app.get("/api/reminders")
def api_reminders():
    return _safe(reminders.rows)


@app.delete("/api/reminders/{reminder_id}")
def api_reminder_delete(reminder_id: int):
    return _safe(lambda: reminders.cancel(reminder_id, _confirmed=True))


@app.get("/api/timers")
def api_timers():
    return _safe(timers.rows)


@app.delete("/api/timers/{timer_id}")
def api_timer_delete(timer_id: int):
    return _safe(lambda: timers.cancel(timer_id))


@app.get("/api/memories")
def api_memories():
    from .tools import memory

    return _safe(memory.items)


class MemoryIn(BaseModel):
    summary: str
    content: str


@app.put("/api/memories/{name}")
def api_memory_save(name: str, body: MemoryIn):
    from .tools import memory

    return _safe(lambda: memory.save(name, body.summary, body.content))


@app.delete("/api/memories/{name}")
def api_memory_delete(name: str):
    from .tools import memory

    return _safe(lambda: memory.delete(name, _confirmed=True))


@app.get("/api/history")
def api_history(limit: int = 80):
    return _safe(lambda: history.recent(limit))


@app.delete("/api/history")
def api_history_clear():
    return _safe(history.clear)


# ── Front-end ────────────────────────────────────────────────────────
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="hud")
else:
    @app.get("/", response_class=HTMLResponse)
    def index():
        return (
            "<body style='background:#02070d;color:#cdeeff;font:16px system-ui;"
            "padding:40px'><h1>Jarvis HUD isn't built yet</h1><p>Run "
            "<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>, "
            "then reload.</p></body>"
        )


def run(port=8765):
    import uvicorn

    print("Jarvis HUD on http://127.0.0.1:{}".format(port))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
