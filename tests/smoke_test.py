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
check("request carries fallback config", req["fallbacks"] == [{"model": config.LLM_FALLBACK_MODEL}]
      and req["betas"] == ["server-side-fallback-2026-06-01"])
check("system prompt loaded from config file", "Jarvis" in req["system"][0]["text"])
check("no thinking param sent (always-on for fable-5)", "thinking" not in req)

print("== affirmative parsing ==")
check("'Yes.' is affirmative", is_affirmative("Yes."))
check("'yeah go ahead' is affirmative", is_affirmative("yeah go ahead"))
check("'no' is not affirmative", not is_affirmative("no"))
check("'yesterday was fine' is not affirmative", not is_affirmative("yesterday was fine"))
check("empty is not affirmative", not is_affirmative(""))

print("== web search (live, needs network) ==")
try:
    from jarvis.tools import websearch

    result = websearch.search("Anthropic Claude", max_results=2)
    check("web search returns results", len(result) > 40)
except Exception as exc:  # noqa: BLE001
    print("  skipped - web search unavailable here: {}".format(exc))

print("\nALL {} CHECKS PASSED".format(len(PASS)))
