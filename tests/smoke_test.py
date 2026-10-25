"""Offline smoke test: tools, reminders, memory, and — critically — proof
that the confirmation gate blocks unconfirmed dangerous actions even when
the model tries to smuggle the confirmation flag in.

Run:  python tests/smoke_test.py
"""
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import config  # noqa: E402

# Sandbox all state into a temp dir before importing the tools.
_tmp = Path(tempfile.mkdtemp(prefix="jarvis-test-"))
config.DB_PATH = _tmp / "jarvis.db"
config.MEMORY_DIR = _tmp / "memory"
config.REMINDER_POLL_SECONDS = 0.2

from jarvis import tools  # noqa: E402
from jarvis.tools import gmail, memory, reminders, tasks  # noqa: E402
from jarvis.assistant import Assistant  # noqa: E402
from jarvis.voice import is_affirmative  # noqa: E402

PASS = []


def check(name, cond):
    assert cond, "FAILED: {}".format(name)
    PASS.append(name)
    print("  ok - {}".format(name))


print("== tasks ==")
tasks.add("buy milk", due="2026-07-10 18:00")
tasks.add("finish report")
check("task_list shows both", "buy milk" in tasks.list_tasks() and "finish report" in tasks.list_tasks())
tasks.complete(2)
check("task_complete hides done task", "finish report" not in tasks.list_tasks())

print("== confirmation gate: task_delete ==")
out, err = tools.execute("task_delete", {"task_id": 1}, confirm=lambda p: False)
check("declined delete returns DECLINED message", out == tools.DECLINED_MESSAGE and not err)
check("task survives declined delete", "buy milk" in tasks.list_tasks())
asked = []
out, err = tools.execute("task_delete", {"task_id": 1}, confirm=lambda p: asked.append(p) or True)
check("confirm callback received a prompt", asked and "buy milk" in asked[0])
check("confirmed delete removes task", "buy milk" not in tasks.list_tasks())

print("== confirmation gate: model cannot self-confirm ==")
tasks.add("sneaky target")
row_id = 3
asked = []
out, err = tools.execute(
    "task_delete", {"task_id": row_id, "_confirmed": True}, confirm=lambda p: asked.append(p) or False
)
check("_confirmed from model is stripped (still asks)", len(asked) == 1)
check("injection did not delete the task", "sneaky target" in tasks.list_tasks())

print("== reminders ==")
reminders.set_reminder("stand up", "2020-01-01 00:00")  # already due
fired = []
reminders.start_scheduler(lambda msg: fired.append(msg))
time.sleep(1.0)
check("due reminder fired via scheduler", fired == ["stand up"])
reminders.set_reminder("future thing", "2099-01-01 09:00")
check("reminder_list shows pending", "future thing" in reminders.list_reminders())
out, err = tools.execute("reminder_cancel", {"reminder_id": 2}, confirm=lambda p: True)
check("confirmed cancel removes reminder", "future thing" not in reminders.list_reminders())
try:
    reminders.set_reminder("bad", "tomorrow-ish")
    check("invalid due_at rejected", False)
except ValueError:
    check("invalid due_at rejected", True)

print("== memory ==")
memory.save("favorite-editor", "Prefers VS Code", "Yogesh uses VS Code with the vim plugin.")
check("memory_read returns content", "vim plugin" in memory.read("favorite-editor"))
check("load_all includes memory", "favorite-editor" in memory.load_all())
try:
    memory.save("../evil", "x", "y")
    check("path traversal name rejected", False)
except ValueError:
    check("path traversal name rejected", True)
out, err = tools.execute("memory_delete", {"name": "favorite-editor"}, confirm=lambda p: False)
check("declined memory delete keeps file", "vim plugin" in memory.read("favorite-editor"))

print("== confirmation gate: gmail send (fake service) ==")
sent = []


class FakeDrafts:
    def get(self, userId, id, format):
        return SimpleNamespace(execute=lambda: {
            "message": {"payload": {"headers": [
                {"name": "To", "value": "alice@example.com"},
                {"name": "Subject", "value": "Hello"},
            ]}}
        })

    def send(self, userId, body):
        return SimpleNamespace(execute=lambda: sent.append(body["id"]))


class FakeUsers:
    def drafts(self):
        return FakeDrafts()


gmail._service = lambda: SimpleNamespace(users=lambda: FakeUsers())

out, err = tools.execute("gmail_send_draft", {"draft_id": "d1"}, confirm=lambda p: False)
check("unconfirmed send is blocked", sent == [] and out == tools.DECLINED_MESSAGE)
out, err = tools.execute(
    "gmail_send_draft", {"draft_id": "d1", "_confirmed": True}, confirm=lambda p: False
)
check("send with injected _confirmed is still blocked", sent == [])
prompts = []
out, err = tools.execute("gmail_send_draft", {"draft_id": "d1"}, confirm=lambda p: prompts.append(p) or True)
check("confirmation prompt names recipient", "alice@example.com" in prompts[0])
check("confirmed send goes through", sent == ["d1"])

print("== assistant loop (scripted fake model) ==")


class FakeResponse:
    def __init__(self, blocks, stop_reason="end_turn"):
        self.content = blocks
        self.stop_reason = stop_reason


def text_block(t):
    return SimpleNamespace(type="text", text=t)


def tool_block(name, args, id="tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=args, id=id)


class FakeClient:
    """Scripted model: first asks to send the draft (self-confirming!), then wraps up."""

    def __init__(self):
        self.calls = []
        self.script = [
            FakeResponse([
                text_block("Sending it now."),
                tool_block("gmail_send_draft", {"draft_id": "d1", "_confirmed": True}),
            ], stop_reason="tool_use"),
            FakeResponse([text_block("Understood, I won't send it.")]),
        ]
        self.beta = SimpleNamespace(
            messages=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.script.pop(0)


sent.clear()
fake = FakeClient()
assistant = Assistant(confirm=lambda p: False, client=fake)
reply = assistant.chat("send my draft to alice")
check("assistant relays the declined outcome", reply == "Understood, I won't send it.")
check("no email sent through the full loop", sent == [])
check("tool_result fed back to model", any(
    isinstance(m.get("content"), list)
    and isinstance(m["content"][0], dict)
    and m["content"][0].get("type") == "tool_result"
    and tools.DECLINED_MESSAGE in m["content"][0]["content"]
    for m in fake.calls[1]["messages"]
))
req = fake.calls[0]
check("request uses configured model", req["model"] == config.LLM_MODEL)
check("request carries fallback config", req["fallbacks"] == "default"
      and req["betas"] == ["server-side-fallback-2026-07-01"])
check("system prompt loaded from config file", "Jarvis" in req["system"][0]["text"])
check("no thinking param sent (adaptive by default)", "thinking" not in req)

print("== affirmative parsing ==")
check("'Yes.' is affirmative", is_affirmative("Yes."))
check("'yeah go ahead' is affirmative", is_affirmative("yeah go ahead"))
check("'no' is not affirmative", not is_affirmative("no"))
check("'yesterday was fine' is not affirmative", not is_affirmative("yesterday was fine"))
check("empty is not affirmative", not is_affirmative(""))

print("== tool events for the HUD ==")
events = []
tools.add_listener(lambda phase, name, args, is_error: events.append((phase, name)))
tools.execute("task_list", {}, confirm=lambda p: False)
check("listener sees start then end", events[-2:] == [("start", "task_list"), ("end", "task_list")])

print("== mac control gates (osascript stubbed) ==")
from jarvis.tools import mac  # noqa: E402

ran = []
mac._run = lambda cmd, input_text=None, timeout=20: ran.append(cmd) or ""
script_args = {"script": 'tell application "Finder" to empty trash', "purpose": "empty the trash"}
out, err = tools.execute("mac_run_applescript", dict(script_args, _confirmed=True), confirm=lambda p: False)
check("applescript blocked without confirmation (even self-confirmed)", ran == [] and out == tools.DECLINED_MESSAGE)
prompts = []
tools.execute("mac_run_applescript", script_args, confirm=lambda p: prompts.append(p) or True)
check("applescript confirmation shows the script", "empty trash" in prompts[0] and len(ran) == 1)
ran.clear()
tools.execute("mac_quit_app", {"name": "Safari"}, confirm=lambda p: False)
check("quitting an app needs confirmation", ran == [])
evil = 'x" & (do shell script "rm -rf ~") & "'
mac.notify(evil, title="t")
check("user strings reach osascript as argv, never as script source",
      ran[-1][-1] == evil and not any("rm -rf" in part for part in ran[-1][:-2]))
try:
    mac.open_url("file:///etc/passwd")
    check("non-http URLs rejected", False)
except ValueError:
    check("non-http URLs rejected", True)

print("== files are confined to FILES_ROOTS ==")
from jarvis.tools import files  # noqa: E402

config.FILES_ROOTS = [_tmp.resolve()]
(_tmp / "notes.md").write_text("launch codes: 0000", encoding="utf-8")
check("reads a file inside the root", "launch codes" in files.read(str(_tmp / "notes.md")))
for outside in ("/etc/hosts", str(_tmp / ".." / "outside.txt")):
    try:
        files.read(outside)
        check("rejects {}".format(outside), False)
    except PermissionError:
        check("rejects path outside root ({})".format(Path(outside).name), True)

print("== timers ==")
from jarvis.tools import timers  # noqa: E402

done = []
timers.set_notifier(done.append)
timers.set_timer(1, "tea")
check("timer listed while running", "tea" in timers.list_timers())
time.sleep(1.4)
check("timer fires its notifier", done == ["tea"] and timers.rows() == [])

print("== turn-taking: pausing mid-thought ==")
import numpy as np  # noqa: E402
from jarvis.audio import turns  # noqa: E402
from jarvis.audio.turns import TurnDetector, judge  # noqa: E402

check("dangling word is incomplete", judge("Turn off the lights in the") == "incomplete")
check("trailing comma is incomplete", judge("Set a timer for ten minutes,") == "incomplete")
check("'let me think' asks for time", judge("Remind me to, um, let me think") == "hold")
check("trailing 'um' asks for time", judge("What about um") == "hold")
check("a full request is complete", judge("What's the weather tomorrow?") == "complete")
check("a short answer is complete", judge("Yes.") == "complete")
check("a lone word is incomplete", judge("Weather") == "incomplete")


class FakeVAD:
    """Speech probability from the chunk itself: loud = speech."""

    def prob(self, chunk):
        return 0.95 if chunk.any() else 0.0


quiet = np.zeros(turns.CHUNK, dtype=np.int16)
loud = (np.ones(turns.CHUNK) * 4000).astype(np.int16)
per_s = int(1 / turns.CHUNK_S)


def run(td, chunks, verdict=None):
    """Feed chunks; answer a "check" with `verdict`. Returns (result, seconds of trailing silence)."""
    silent = 0
    for c in chunks:
        r = td.feed(c)
        silent = silent + 1 if not c.any() else 0
        if r == "check" and verdict:
            td.verdict(verdict, "some text")
        if r in ("done", "timeout"):
            return r, silent * turns.CHUNK_S
    return "wait", silent * turns.CHUNK_S


td = TurnDetector(start_timeout=0.4, detector=FakeVAD())
check("silence before speaking times out", run(td, [quiet] * 10)[0] == "timeout")

td = TurnDetector(start_timeout=2, patience="balanced", detector=FakeVAD())
r, after = run(td, [loud] * 10 + [quiet] * 30, verdict="complete")
check("complete sentence ends quickly (<1 s of silence)", r == "done" and after < 1.0)

td = TurnDetector(start_timeout=2, patience="balanced", detector=FakeVAD())
r, after = run(td, [loud] * 10 + [quiet] * (3 * per_s), verdict="incomplete")
check("mid-thought pause of 3 s does not end the turn", r == "wait")
r, after = run(td, [loud] * 5 + [quiet] * (2 * per_s), verdict="complete")
check("carrying on after the pause, then finishing, ends it", r == "done")
check("both halves are in the utterance", len(td.audio()) >= 15 * turns.CHUNK)

td = TurnDetector(start_timeout=2, patience="balanced", detector=FakeVAD())
r, _ = run(td, [loud] * 10 + [quiet] * (10 * per_s), verdict="hold")
check("'let me think' waits well past the usual limit", r == "wait")

td = TurnDetector(start_timeout=2, patience="snappy", detector=FakeVAD())
r, after = run(td, [loud] * 10 + [quiet] * (5 * per_s), verdict="incomplete")
check("snappy patience gives up sooner", r == "done" and after <= 2.2)

td = TurnDetector(start_timeout=2, detector=FakeVAD(), preroll=[loud] * 3, speaking=True)
check("barge-in pre-roll keeps the first words", len(td.audio()) == 3 * turns.CHUNK)

print("== settings, moods and voice control ==")
from jarvis import hud_bridge, moods, settings  # noqa: E402
from jarvis.assistant import stamp  # noqa: E402

NO = lambda prompt: False  # noqa: E731 — none of these tools should ask

changes = []
settings.add_listener(lambda snap, ch: changes.append(ch))
check("defaults load", settings.get()["mood"] == "classic")
try:
    settings.update(patience="forever")
    check("invalid patience rejected", False)
except ValueError:
    check("invalid patience rejected", True)
try:
    settings.update(colour="red")
    check("unknown setting rejected", False)
except ValueError:
    check("unknown setting rejected", True)
out, err = tools.execute("voice_set_mood", {"mood": "calm"}, confirm=NO)
check("voice_set_mood changes the mood", not err and settings.get()["mood"] == "calm")
check("listeners hear about it", {"mood": "calm"} in [{k: v for k, v in c.items() if k == "mood"} for c in changes])
check("calm mood slows the voice", moods.current()["speed"] < 1.0)
check("mood style reaches the model", "calm" in stamp("hello").lower())
out, err = tools.execute("assistant_set_preference", {"setting": "patience", "value": "patient"}, confirm=NO)
check("patience is voice-controllable", not err and settings.get()["patience"] == "patient")
out, err = tools.execute("assistant_set_preference", {"setting": "barge_in", "value": "off"}, confirm=NO)
check("'off' turns a toggle off", settings.get()["barge_in"] is False)

hud_bridge.attach(None)
out, _ = tools.execute("hud_show_card", {"title": "Mars", "items": [{"title": "Moons", "value": "2"}]}, confirm=NO)
check("cards degrade gracefully with no HUD open", "isn't open" in out)
sent_events = []
hud_bridge.attach(lambda e: sent_events.append(e) or True)
tools.execute("hud_show_card", {"title": "Links", "items": [
    {"title": "ok", "url": "https://example.com"},
    {"title": "bad", "url": "javascript:alert(1)"},
]}, confirm=NO)
urls = [i["url"] for i in sent_events[-1]["items"]]
check("card links must be http(s)", urls == ["https://example.com", None])
tools.execute("hud_control", {"action": "orb_mode"}, confirm=NO)
check("hud_control reaches the HUD", sent_events[-1] == {"type": "hud", "action": "orb_mode"})
tools.execute("hud_control", {"action": "set_theme", "value": "mark"}, confirm=NO)
check("theme can be set by voice", settings.get()["theme"] == "mark")
hud_bridge.attach(None)
settings.update(**settings.DEFAULTS)

print("== HUD confirmation flow ==")
import threading  # noqa: E402
from jarvis import web  # noqa: E402

hub = web.Hub()
hub._synth = lambda text: (None, None)   # no TTS in tests
answers = []
t = threading.Thread(target=lambda: answers.append(hub.web_confirm("Delete task 9?")))
t.start()
time.sleep(0.2)
check("pending confirmation is exposed to the HUD", hub.confirm and hub.confirm["prompt"] == "Delete task 9?")
hub.handle({"type": "text", "text": "no thanks"})
t.join(2)
check("typing 'no' declines", answers == [False] and hub.confirm is None)
t = threading.Thread(target=lambda: answers.append(hub.web_confirm("Send it?")))
t.start()
time.sleep(0.2)
hub.handle({"type": "confirm", "yes": True})
t.join(2)
check("clicking approve confirms", answers == [False, True])

print("== talking over Jarvis, and ending a conversation ==")
from jarvis.audio.turns import ends_conversation, interruption  # noqa: E402

check("'mm-hmm' over Jarvis is ignored", interruption("Mm-hmm.") == "ignore")
check("'yeah, right' is ignored", interruption("Yeah, right.") == "ignore")
check("a real question interrupts", interruption("Wait, what about Rome?") == "barge")
check("'stop' always interrupts", interruption("Stop.") == "barge")
check("a lone word (often a misheard 'mm-hmm') doesn't", interruption("Amen.") == "ignore")
check("...but counts as an addition while thinking", interruption("Rome", min_words=1) == "barge")
check("Whisper's silence hallucination is ignored", interruption("Thank you.") == "ignore")
spoken = "The forecast for tomorrow is sunny with a high of twenty four degrees"
check("Jarvis's own echo is ignored", interruption("sunny with a high of twenty four", spoken) == "ignore")
check("'thanks, that's all' ends the conversation", ends_conversation("Thanks, that's all."))
check("'goodbye Jarvis' ends it", ends_conversation("Goodbye"))
check("a request that starts with thanks doesn't", not ends_conversation("Thanks for the weather, now play music"))
settings.update(wake="high", conversation="brief")
check("wake sensitivity lowers the threshold", settings.wake_threshold() < config.WAKE_THRESHOLD)
check("brief conversations use the short window", settings.followup_window() == config.FOLLOWUP_WINDOW)
settings.update(wake="normal", conversation="open")
check("open conversations listen longer", settings.followup_window() > config.FOLLOWUP_WINDOW)

sent, real_emit, real_synth = [], hub.emit, hub._synth
hub.emit = sent.append


def _cut_off_while_synthesizing(text):
    if "rest" in text:
        hub.playing_id = None   # the user talked over the first sentence
    return None, None


hub._synth = _cut_off_while_synthesizing
hub.say("First sentence. And the rest of the answer.", "reply", "idle")
check("a reply cut off mid-synthesis doesn't play its rest",
      [m["seq"] for m in sent if m.get("type") == "audio"] == [0])
hub.emit, hub._synth = real_emit, real_synth

hub.turn_active = True
hub.additions = []
hub.on_addition("and check Rome too")
check("speech while thinking is queued for the turn", hub.additions == ["and check Rome too"])
check("queued additions are taken once", hub._take_additions() == "and check Rome too" and hub._take_additions() == "")
check("taking an empty queue ends the turn's window", hub.turn_active is False)

from jarvis.audio.turns import CHUNK, SpeechDetector  # noqa: E402

vad = SpeechDetector()
if vad.session is None:
    print("  skipped - speech model unavailable here")
else:
    quiet = max(vad.prob(np.zeros(CHUNK, dtype=np.int16)) for _ in range(10))
    check("streaming speech detector stays low on silence", quiet < 0.2)

    # "Wait, stop..." recorded over Jarvis's voice, after echo cancellation.
    # After a long quiet stretch (what the mic sounds like while Jarvis
    # talks) the detector must still notice it quickly.
    talkover = np.fromfile(Path(__file__).parent / "fixtures" / "talkover_aec.pcm", dtype=np.int16)
    vad = SpeechDetector()
    for _ in range(int(600 / 0.08)):   # ten minutes of silence
        vad.prob(np.zeros(CHUNK, dtype=np.int16))
    probs = [vad.prob(talkover[i:i + CHUNK]) for i in range(0, 25 * CHUNK, CHUNK)]
    heard = sum(p >= 0.6 for p in probs) / len(probs)
    check("speech over Jarvis is heard after a long quiet stretch ({:.0%})".format(heard), heard >= 0.3)

print("== speech to text ==")
from jarvis.audio import stt  # noqa: E402

config.STT_VOCABULARY = "Sajjan Raj Vaidya, Bupa"
check("the vocabulary primes Whisper", stt.prompt() == "Jarvis, Sajjan Raj Vaidya, Bupa.")
real_choice, config.STT_PROVIDER = config.STT_PROVIDER, "auto"
stt._provider = None
real_machine, stt.platform.machine = stt.platform.machine, lambda: "x86_64"
check("auto uses the CPU model off Apple Silicon", stt.provider() == "local")
stt.platform.machine, stt._provider = real_machine, None
if stt.provider() == "mlx" and vad.session is not None:
    heard = stt.transcribe(talkover).lower()
    check("the GPU model hears 'stop' through Jarvis's voice ({!r})".format(heard), "stop" in heard)
config.STT_PROVIDER, stt._provider = real_choice, None

print("== meeting alerts and the morning briefing ==")
from datetime import datetime, timedelta, timezone  # noqa: E402

from jarvis import proactive  # noqa: E402

now = datetime(2026, 10, 26, 9, 55, tzinfo=timezone.utc)
standup = {"id": "e1", "title": "Standup", "start": now + timedelta(minutes=5), "link": "https://meet"}
check("meeting alert wording", proactive.alert_text(standup, now) == "Heads up: Standup starts in 5 minutes, on Google Meet.")
check("a location is named", proactive.alert_text(
    {"title": "Dentist", "start": now + timedelta(minutes=1), "location": "12 King St, Sydney"}, now
) == "Heads up: Dentist starts in 1 minute, at 12 King St.")

said = []
fake_hub = type("H", (), {"announce": lambda self, kind, text, speak=True: said.append(text)})()
watcher = proactive.Proactive(fake_hub)
watcher.fetched = time.time()   # don't call Google
later = {"id": "e2", "title": "Review", "start": datetime.now(timezone.utc) + timedelta(minutes=40)}
soon = {"id": "e3", "title": "Sync", "start": datetime.now(timezone.utc) + timedelta(minutes=4)}
begun = {"id": "e4", "title": "Started", "start": datetime.now(timezone.utc) - timedelta(minutes=1)}
watcher.events = [later, soon, begun]
watcher._meetings(5)
watcher._meetings(5)
check("alerts only for meetings within the lead time, once", len(said) == 1 and "Sync" in said[0])
spoken_too = []
fake_hub.announce = lambda kind, text, speak=True: spoken_too.append(speak)
real_idle, proactive.idle_seconds = proactive.idle_seconds, lambda: 3600
watcher.alerted.clear()
watcher._meetings(5)
proactive.idle_seconds = real_idle
check("alerts aren't spoken to an empty room", spoken_too == [False])

morning = datetime(2026, 10, 26, 8, 15)
check("briefing plays once you're at the Mac after its time",
      proactive.briefing_due(morning, "07:00", None, idle=5))
check("...not before its time", not proactive.briefing_due(morning, "08:30", None, idle=5))
check("...not while you're away", not proactive.briefing_due(morning, "07:00", None, idle=900))
check("...not twice in a day", not proactive.briefing_due(morning, "07:00", "2026-10-26", idle=5))
check("...not in the afternoon", not proactive.briefing_due(morning.replace(hour=15), "07:00", None, idle=5))
check("...not when off", not proactive.briefing_due(morning, "off", None, idle=5))

check("briefing times are normalised", settings.update(briefing="7:30")["briefing"] == "07:30")
check("'10 minutes' sets the alert lead", settings.update(meeting_alerts="10 minutes")["meeting_alerts"] == "10")
try:
    settings.update(briefing="25:00")
    check("impossible briefing times are refused", False)
except ValueError:
    check("impossible briefing times are refused", True)
settings.update(briefing="07:00", meeting_alerts="5")

started = []
hub.clients = set()
check("no briefing without a window to hear it", hub.brief("x") is False)
hub.clients = {object()}
hub.state = "idle"
real_submit, hub.submit = hub.submit, lambda text, source, speak=True, last=False: started.append(source)
check("the briefing starts a turn of Jarvis's own", hub.brief("x") is True and started == ["auto"])
hub.submit, hub.clients = real_submit, set()

print("== media, screen images and messages ==")
from jarvis.tools import media  # noqa: E402

state = media._parse({
    "title": "Suna Kaanchi", "artist": "Sajjan Raj Vaidya", "playing": True, "playbackRate": 1,
    "bundleIdentifier": "com.google.Chrome.app.cinhimbnkkaeohfgghhklpknlkffjgod",
    "durationMicros": 287_000_000, "elapsedTimeMicros": 44_000_000, "timestampEpochMicros": 1_000_000,
})
check("YouTube Music's Chrome app is named", state["app"] == "YouTube Music")
check("track times are in seconds", state["duration"] == 287 and state["elapsed"] == 44)
check("an empty media session means nothing playing", media._parse({}) is None)
try:
    media.control("rewind")
    check("unknown media actions are refused", False)
except ValueError:
    check("unknown media actions are refused", True)

real_handlers = tools._handlers
tools._handlers = lambda: {"screen_look": lambda: tools.ToolImage("a screen", "AAAA", "image/png")}
out, err = tools.execute("screen_look", {}, confirm=lambda p: True)
tools._handlers = real_handlers
check("screenshots reach the model as images", isinstance(out, tools.ToolImage) and out.data == "AAAA" and not err)

prompts = []
out, err = tools.execute(
    "message_send", {"to": "+61 400 000 000", "text": "running late", "_confirmed": True},
    confirm=lambda p: prompts.append(p) or False,
)
check("messages need confirmation (even with a smuggled flag)", out == tools.DECLINED_MESSAGE and len(prompts) == 1)
check("the confirmation shows the recipient and text", "+61 400 000 000" in prompts[0] and "running late" in prompts[0])

print("== web search (live, needs network) ==")
try:
    from jarvis.tools import websearch

    result = websearch.search("Anthropic Claude", max_results=2)
    check("web search returns results", len(result) > 40)
except Exception as exc:  # noqa: BLE001
    print("  skipped - web search unavailable here: {}".format(exc))

print("\nALL {} CHECKS PASSED".format(len(PASS)))
