"""Web front-end: a minimal chat UI over the same Assistant core.

Single-user by design (it's your laptop). The confirmation gate works over
HTTP the same way it does over voice: when a gated tool fires mid-turn, the
/chat request blocks, the browser (which polls /poll while waiting) shows a
confirm dialog, and POST /confirm releases the turn with the user's answer.
"""
import threading

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .assistant import Assistant
from .tools import reminders

app = FastAPI(title="Jarvis")

_assistant = None
_chat_lock = threading.Lock()   # one turn at a time
_state_lock = threading.Lock()
_pending = {"prompt": None, "event": None, "answer": False}
_notifications = []


def web_confirm(prompt):
    """Block the in-flight turn until the browser answers (or 120s passes)."""
    event = threading.Event()
    with _state_lock:
        _pending["prompt"] = prompt
        _pending["event"] = event
        _pending["answer"] = False
    event.wait(timeout=120)
    with _state_lock:
        _pending["prompt"] = None
        _pending["event"] = None
        return _pending["answer"]


def _get_assistant():
    global _assistant
    if _assistant is None:
        _assistant = Assistant(confirm=web_confirm)
        reminders.start_scheduler(
            lambda msg: _notifications.append("Reminder: " + msg)
        )
    return _assistant


class ChatIn(BaseModel):
    message: str


class ConfirmIn(BaseModel):
    yes: bool


@app.post("/chat")
def chat(body: ChatIn):
    text = body.message.strip()
    if not text:
        return {"reply": ""}
    with _chat_lock:
        try:
            return {"reply": _get_assistant().chat(text)}
        except Exception as exc:  # noqa: BLE001 — surface config/API errors in the UI
            return {"reply": "Something went wrong: {}".format(exc), "error": True}


@app.get("/poll")
def poll():
    with _state_lock:
        prompt = _pending["prompt"]
    drained, _notifications[:] = _notifications[:], []
    return {"confirm": prompt, "notifications": drained}


@app.post("/confirm")
def confirm(body: ConfirmIn):
    with _state_lock:
        if _pending["event"] is None:
            return {"ok": False}
        _pending["answer"] = body.yes
        _pending["event"].set()
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index():
    return _PAGE


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jarvis</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; }
  body {
    font-family: -apple-system, "Segoe UI", sans-serif;
    background: #101418; color: #dde3ea;
    display: flex; flex-direction: column; height: 100vh;
  }
  header {
    padding: 14px 20px; border-bottom: 1px solid #232a33;
    display: flex; align-items: baseline; gap: 10px;
  }
  header h1 { font-size: 17px; font-weight: 600; letter-spacing: .04em; }
  header span { font-size: 12px; color: #6b7683; }
  #log { flex: 1; overflow-y: auto; padding: 20px; display: flex;
         flex-direction: column; gap: 10px; }
  .msg { max-width: 72%; padding: 10px 14px; border-radius: 14px;
         line-height: 1.45; white-space: pre-wrap; font-size: 14.5px; }
  .you    { align-self: flex-end; background: #2b5cab; border-bottom-right-radius: 4px; }
  .jarvis { align-self: flex-start; background: #1c232b; border-bottom-left-radius: 4px; }
  .note   { align-self: center; background: none; color: #8fa1b3;
            font-size: 12.5px; font-style: italic; }
  .error  { background: #3a1f24; color: #f0b9b9; }
  form { display: flex; gap: 10px; padding: 14px 20px 18px;
         border-top: 1px solid #232a33; }
  input {
    flex: 1; padding: 11px 14px; font-size: 15px; color: inherit;
    background: #1a2027; border: 1px solid #2c343e; border-radius: 10px;
    outline: none;
  }
  input:focus { border-color: #3d6bb0; }
  button {
    padding: 11px 20px; font-size: 15px; border: 0; border-radius: 10px;
    background: #2b5cab; color: #fff; cursor: pointer;
  }
  button:disabled { opacity: .45; cursor: default; }
</style>
</head>
<body>
<header><h1>JARVIS</h1><span>web console — same brain as voice mode</span></header>
<div id="log">
  <div class="msg jarvis">Good evening. Type below — I have the same tools and
memory as voice mode, and I'll still ask before sending or deleting anything.</div>
</div>
<form id="f">
  <input id="box" autocomplete="off" placeholder="Message Jarvis…" autofocus>
  <button id="send">Send</button>
</form>
<script>
const log = document.getElementById("log");
const box = document.getElementById("box");
const send = document.getElementById("send");
let polling = null;

function add(cls, text) {
  const d = document.createElement("div");
  d.className = "msg " + cls;
  d.textContent = text;
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
  return d;
}

async function pollOnce() {
  try {
    const r = await (await fetch("/poll")).json();
    for (const n of r.notifications) add("note", n);
    if (r.confirm) {
      const yes = window.confirm(r.confirm);
      add("note", (yes ? "Confirmed: " : "Declined: ") + r.confirm);
      await fetch("/confirm", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({yes})});
    }
  } catch (e) { /* server restarting; keep polling */ }
}

document.getElementById("f").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const text = box.value.trim();
  if (!text) return;
  add("you", text);
  box.value = ""; box.disabled = true; send.disabled = true;
  const thinking = add("note", "thinking…");
  polling = setInterval(pollOnce, 600);
  try {
    const resp = await fetch("/chat", {method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message: text})});
    const data = await resp.json();
    thinking.remove();
    add(data.error ? "jarvis error" : "jarvis", data.reply);
  } catch (e) {
    thinking.remove();
    add("jarvis error", "Request failed: " + e);
  } finally {
    clearInterval(polling);
    await pollOnce();               // catch any trailing notifications
    box.disabled = false; send.disabled = false; box.focus();
  }
});
setInterval(pollOnce, 4000);        // reminders can fire while idle
</script>
</body>
</html>
"""


def run(port=8765):
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port)
