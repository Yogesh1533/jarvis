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
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, hud_bridge, moods, settings, tools
from .assistant import Assistant
from .audio.turns import CHUNK, TurnDetector, ends_conversation, interruption, judge
from .tools import history, media, reminders, timers
from .voice import is_affirmative

FRONTEND_DIST = config.ROOT / "frontend" / "dist"
# Someone starts talking: 3 of the last 5 chunks (~240 ms) scored as speech,
# enough to catch a quick "stop".
ONSET_WINDOW, ONSET_NEEDED, ONSET_PROB = 5, 3, 0.6
SPEECH_MIN = 8          # chunks (~640 ms) of actual speech before checking the words;
                        # anything shorter is a "mm-hmm" unless it's "stop"/"wait"/"no"
VERIFY_STEP = 8         # ...and again this much later if it was only "um"
VERIFY_LIMIT = 40       # give up on a probe that's still just noise (~3 s)
COOLDOWN = 12           # chunks to ignore after a false alarm (~1 s)


class VoicePipeline:
    """Wake word, turn-taking and Whisper, fed by the client's mic stream.

    mode: "off"    ignore audio (mic off)
          "sleep"  listen only for the wake word
          "record" capture one turn for `purpose` ("chat" or "confirm")
          "watch"  Jarvis is speaking or thinking: notice the user talking.
                   While speaking, a burst of speech ducks Jarvis's voice
                   and the words decide: a real interruption stops it and
                   becomes the next turn; "mm-hmm" or Jarvis's own echo
                   un-ducks it. While thinking, what the user says is
                   queued as an addition to their request.
    """

    def __init__(self, hub):
        self.hub = hub
        self.frames = queue.Queue(maxsize=400)
        self.mode = "off"
        self.purpose = "chat"
        self.watch_for = None   # "speaking" | "thinking" in watch mode
        self.turn = None
        self.probe = None       # provisional turn while watching
        self.probe_state = None # None | "verifying" | "done-pending"
        self.probe_done = False # the user has stopped talking
        self.probe_speech = 0   # chunks of the probe that were speech
        self.verify_at = SPEECH_MIN
        self.vad = None
        self.detector = None
        self.mic_on = False
        self.ready = False      # speech-to-text loaded
        self.wake_ok = False    # wake-word model loaded
        self.error = None
        self.recent = deque(maxlen=6)
        self.onset = deque(maxlen=ONSET_WINDOW)
        self.cooldown = 0
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

    def watch(self, what):
        """Jarvis is speaking or thinking: keep an ear out for the user.
        None just stops listening (e.g. a typed request)."""
        ok = what is not None and self.ready and self.mic_on and (what == "thinking" or settings.get()["barge_in"])
        with self._lock:
            if ok and what == "speaking" and self.mode == "watch" and self.probe is not None \
                    and self.watch_for == "thinking":
                # The reply is starting while the user is still adding to
                # their request: keep what they're saying, and treat it
                # as talking over the reply.
                self.watch_for = "speaking"
                self.probe_state = None
                self.probe_done = False
                self.verify_at = SPEECH_MIN
                self.hub.emit({"type": "duck"})
                return
        self._set_mode("watch" if ok else "off", watch_for=what)

    def listen(self, timeout, purpose, preroll=None, speaking=False, turn=None):
        """Capture one turn right now, no wake word needed. `turn` adopts a
        capture already in progress (a confirmed interruption)."""
        if not self.ready:
            self.hub.notice(self.error or "Voice is still loading. One moment.")
            return False
        if not self.mic_on:
            self.hub.notice("The microphone is off. Turn it on to talk to me.")
            return False
        patience = "snappy" if purpose == "confirm" else settings.get()["patience"]
        if turn is None and self.mode == "watch" and self.probe is not None:
            turn = self.probe   # they started talking as Jarvis finished
        if turn is not None:
            turn.pending = None  # judge its next pause for real
        with self._lock:
            self.turn = turn or TurnDetector(
                timeout, patience, detector=self.vad, preroll=preroll, speaking=speaking
            )
            self.purpose = purpose
            self.mode = "record"
            self.probe = None
            self.probe_state = None
            self.heard = "speaking" if turn else None
            if turn is None:
                self._drain()
        self.hub.set_state("confirm" if purpose == "confirm" else "listening")
        return True

    def recording(self):
        return self.mode == "record"

    def _set_mode(self, mode, watch_for=None):
        with self._lock:
            self.mode = mode
            self.watch_for = watch_for if mode == "watch" else None
            if mode != "record":
                self.turn = None
            self.probe = None
            self.probe_state = None
            self.onset.clear()
            self.recent.clear()
            self.cooldown = 0
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
            if self.vad is not None:
                self.vad.prob(chunk)  # keep the detector's state in step
            if self.detector.detect(chunk):
                self.detector.reset()
                self.hub.on_wake()
                return True
        elif mode == "watch" and self.vad is not None:
            return self._watch(chunk)
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
                self._finish(turn, self.purpose)
                return True
        return False

    def _finish(self, turn, purpose):
        text, audio = turn.final_text(), turn.audio()
        self.pause()
        self.hub.set_state("thinking")
        self.hub.emit({"type": "hearing", "verdict": "done"})
        if text is None:
            text = self._transcribe(audio)
        self.hub.on_utterance(text, purpose)

    # -- watching while Jarvis speaks or thinks ---------------------------
    def _watch(self, chunk):
        if self.probe is not None:
            return self._feed_probe(chunk)
        self.recent.append(chunk)
        p = self.vad.prob(chunk)
        if self.cooldown:
            self.cooldown -= 1
            return False
        self.onset.append(p)
        if sum(x >= ONSET_PROB for x in self.onset) < ONSET_NEEDED:
            return False
        # Someone's talking. Start capturing (with what came just before).
        patience = settings.get()["patience"]
        self.probe = TurnDetector(
            config.RECORD_START_TIMEOUT, patience, detector=self.vad,
            preroll=list(self.recent), speaking=True,
        )
        self.probe_state = None
        self.probe_done = False
        self.probe_speech = sum(x >= ONSET_PROB for x in self.onset)
        self.verify_at = SPEECH_MIN
        if self.watch_for == "speaking":
            self.hub.emit({"type": "duck"})
        else:
            self.hub.emit({"type": "hearing", "verdict": "speaking"})
        return False

    def _feed_probe(self, chunk):
        probe = self.probe
        result = probe.feed(chunk)
        if self.vad._last >= 0.5:
            self.probe_speech += 1
        if result == "check":
            # Answer the probe's pause checks without Whisper. Over Jarvis's
            # voice, keep capturing until the words are judged; while it
            # thinks, a pause ends the addition.
            probe.verdict("incomplete" if self.watch_for == "speaking" else "complete", "")
        if self.watch_for == "speaking":
            short = self.probe_speech < SPEECH_MIN
            if result == "done" and not self.probe_done:
                self.probe_done = True
                if self.probe_state == "verifying":
                    self.probe_state = "done-pending"
                elif self.probe_state is None:
                    self._verify(probe, short)
            elif result == "check" and short and self.probe_state is None:
                self.probe_done = True   # a brief burst, then quiet: judge it now
                self._verify(probe, short=True)
            elif self.probe_state is None and not self.probe_done and self.probe_speech >= self.verify_at:
                self._verify(probe)
            return False
        # Thinking: the user is adding to (or changing) their request.
        if result == "done":
            audio = probe.audio()
            self._reset_watch()
            threading.Thread(
                target=self._queue_addition, args=(audio,), daemon=True, name="hud-addition"
            ).start()
            return True
        return False

    def _reset_watch(self, cooldown=0):
        self.probe = None
        self.probe_state = None
        self.onset.clear()
        self.recent.clear()
        self.cooldown = cooldown

    def _verify(self, probe, short=False):
        """Were those real words from the user, or echo / "mm-hmm"? A
        `short` burst only counts if it's "stop", "wait", "no"..."""
        self.probe_state = "verifying"
        audio = probe.audio()
        spoken = self.hub.speaking_text

        def job():
            text = self._transcribe(audio)
            if self.probe is not probe:
                return  # superseded (Jarvis finished, or a new mode)
            kind = interruption(text, spoken, min_words=99 if short else 2)
            if self.hub.confirm and is_affirmative(text):
                kind = "barge"   # "yes" over the confirmation question
            if kind == "ignore":
                if not self.probe_done and len(probe.recorded) < VERIFY_LIMIT:
                    # Maybe just a slow start ("um... actually"): stay ducked
                    # and look again once there's more to go on.
                    self.verify_at = self.probe_speech + VERIFY_STEP
                    self.probe_state = None
                    return
                self._reset_watch(cooldown=COOLDOWN)
                self.hub.emit({"type": "unduck"})
                return
            done = self.probe_state == "done-pending"
            self.probe = None
            self.probe_state = None
            self.hub.on_barge_in(probe, finished=done)

        threading.Thread(target=job, daemon=True, name="hud-verify").start()

    def _queue_addition(self, audio):
        text = self._transcribe(audio)
        if interruption(text, self.hub.speaking_text, min_words=1) == "barge":
            self.hub.on_addition(text)
        else:
            self.hub.emit({"type": "hearing", "verdict": "done"})

    # -- transcription ---------------------------------------------------
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
        self.speaking_text = ""             # what Jarvis is saying (to spot its echo)
        self.turn_active = False
        self.additions = []                 # said while Jarvis was thinking
        self._additions_lock = threading.Lock()
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
        self.speaking_text = text
        if then != "confirm":
            self.set_state("speaking")
        self.voice.watch("speaking")
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
            if self.playing_id != uid:
                return   # interrupted while synthesizing: don't play the rest
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
        self.speaking_text = phrase
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
            self.voice.watch("thinking")
            return  # an announcement finished mid-turn; the turn owns state
        if then == "followup" and self.voice.mic_on and self.voice.ready:
            self.voice.listen(settings.followup_window(), "chat")
            return
        self.set_state("idle")
        self.voice.sleep()

    # -- turns -----------------------------------------------------------
    def submit(self, text, source, speak=True, last=False):
        """Run one request. `last`: the user signed off ("thanks, that's
        all"), so don't keep listening after the reply."""
        if not self.turn_lock.acquire(blocking=False):
            self.notice("Still working on your last request.")
            return
        with self._additions_lock:
            self.turn_active = True
            self.additions = []
        threading.Thread(
            target=self._turn, args=(text, source, speak, last), daemon=True, name="hud-turn"
        ).start()

    def _take_additions(self):
        """What the user said while we were thinking; ends the turn's
        listening window once nothing is left."""
        with self._additions_lock:
            extra, self.additions = self.additions, []
            if not extra:
                self.turn_active = False
            return " ".join(extra)

    def _turn(self, text, source, speak, last=False):
        error = False
        try:
            self.voice.watch("thinking" if source == "voice" else None)
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
            # They kept talking while we worked: answer that too. The reply
            # so far goes on screen; only the last one is spoken.
            while True:
                extra = self._take_additions()
                if not extra:
                    break
                _log("jarvis", reply)
                self.emit({"type": "reply", "id": next(self._ids), "text": reply, "speak": False})
                _log("user", extra)
                last = ends_conversation(extra)
                reply = self.assistant.chat(
                    "(I added this while you were answering; your previous answer was "
                    "shown on screen but not read out.) " + extra
                )
        except Exception as exc:  # noqa: BLE001 — config/API errors go to the HUD
            reply = "Something went wrong: {}".format(exc)
            error = True
        finally:
            with self._additions_lock:
                self.turn_active = False
                self.additions = []
            self.turn_source = None
            self.turn_lock.release()
        _log("jarvis", reply)
        self.say(
            reply, kind="reply",
            then="followup" if source == "voice" and not last else "idle",
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
        self.voice.watch("thinking" if self.turn_source == "voice" else None)
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

    def on_barge_in(self, probe, finished=False):
        """The user talked over Jarvis with real words: stop talking, and
        carry on capturing what they're saying (already in `probe`)."""
        self.emit({"type": "barge_in"})
        self.playing_id = None
        self.after_playback = None
        purpose = "confirm" if self.confirm else "chat"
        if not self.confirm:
            self.interrupted = True
        if finished:   # they'd already stopped talking
            self.voice.pause()
            self.set_state("thinking")
            self.emit({"type": "hearing", "verdict": "done"})
            self.on_utterance(self.voice._transcribe(probe.audio()), purpose)
            return
        if not self.voice.listen(config.RECORD_START_TIMEOUT, purpose, turn=probe):
            self.set_state("idle")

    def on_addition(self, text):
        """Something said while Jarvis was thinking."""
        with self._additions_lock:
            queued = self.turn_active
            if queued:
                self.additions.append(text)
        self.emit({"type": "hearing", "verdict": "done"})
        if queued:
            self.emit({"type": "transcript", "role": "user", "text": text, "source": "voice"})
        else:   # the turn just ended; make it the next one
            self.submit(text, source="voice", speak=True, last=ends_conversation(text))

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
        self.submit(text, source="voice", speak=True, last=ends_conversation(text))

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
    # Now playing (YouTube Music, Spotify...) pushed live to every window.
    media.watcher.start(lambda now: hub.emit({"type": "media", "now": now}))
    yield
    media.watcher.stop()
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
    position: float | None = None


class VolumeIn(BaseModel):
    level: int


@app.get("/api/media")
def api_media():
    from .tools import mac

    return _safe(lambda: {
        "now": media.current(), "volume": mac.get_volume(),
        "live": media.watcher.running, "seek": media.binary() is not None,
    })


@app.post("/api/media")
def api_media_action(body: MediaIn):
    return _safe(lambda: media.control(body.action, body.position))


@app.get("/api/media/art")
def api_media_art():
    art = media.watcher.art
    if art is None:
        return Response(status_code=404)
    return Response(art[0], media_type=art[1], headers={"Cache-Control": "max-age=86400"})


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
