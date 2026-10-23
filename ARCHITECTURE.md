# Architecture

```
                        ┌─────────────────────────────────────────────┐
 mic ──► wake.py        │  assistant.py — the brain                   │
        (openWakeWord,  │                                             │
         always local)  │  claude-fable-5 via Anthropic API           │
            │ wake word │  (server-side fallback to claude-opus-4-8   │
            ▼           │   if a request is safety-declined)          │
        recorder.py     │                                             │
        (energy-based   │  system prompt = config/*.md  +  memory/*.md│
         endpointing)   │  loaded fresh each session, prompt-cached   │
            │ int16 PCM │                                             │
            ▼           │        ┌── tool loop ──────────────┐        │
        stt.py ────────►│ text ─►│ tools/__init__.py dispatch │       │
        (faster-whisper │        │  + CONFIRMATION GATE       │       │
         local, or      │        └──────────┬────────────────┘        │
         OpenAI API)    └───────────────────┼─────────────────────────┘
                                            │
            ┌────────────┬──────────┬───────┴────┬────────────┬───────────┐
            ▼            ▼          ▼            ▼            ▼           ▼
         gmail.py     gcal.py   tasks.py   reminders.py  websearch.py memory.py
         (Gmail API)  (GCal API)(SQLite)   (SQLite +     (DuckDuckGo) (markdown
                                            bg thread)                 files)
                                            │ due → spoken notification
        tts.py ◄── reply text               ▼
        (piper local / elevenlabs / openai) speaker
```

Three front-ends drive the same brain: `voice.py` (wake word → record →
transcribe → chat → speak → follow-up window), `text.py` (a REPL), and
`web.py` (a FastAPI localhost chat page; the confirmation gate surfaces as
a browser dialog via a short-poll `/poll` + `/confirm` round-trip while the
`/chat` request blocks mid-turn).
`assistant.py` and everything below it is audio-free, which is what makes
the text mode and the offline test suite possible.

## Components

| Piece | File(s) | Notes |
|---|---|---|
| Config | `jarvis/config.py`, `.env` | All keys, paths, and timings. Nothing sensitive in code. |
| Wake word | `audio/wake.py` | openWakeWord `hey_jarvis` model, ONNX runtime, 80 ms frames at 16 kHz. Runs continuously; nothing is recorded or sent anywhere until it fires. |
| Recording | `audio/recorder.py` | RMS energy endpointing: waits for speech, stops after `SILENCE_DURATION` of quiet. |
| STT | `audio/stt.py` | `faster-whisper` locally (default) or OpenAI Whisper API (`STT_PROVIDER=openai`). |
| Brain | `jarvis/assistant.py` | Multi-turn conversation, manual tool loop, prompt caching (`cache_control` on the system block), refusal handling with server-side model fallback. |
| Tools | `jarvis/tools/*` | Schemas + dispatcher in `tools/__init__.py`; one module per capability. |
| TTS | `audio/tts.py` | Piper (local subprocess), ElevenLabs, or OpenAI — selected by `TTS_PROVIDER`. |
| Reminders | `tools/reminders.py` | SQLite table + daemon thread; due reminders are spoken (voice mode) or printed (text mode). |
| Memory | `tools/memory.py` | One markdown file per fact in `memory/`, first line is the summary. All memories are appended to the system prompt at session start; the model writes new ones through `memory_save`. |

## The confirmation gate (enforced in code, not in the prompt)

The system prompt *tells* the model that sending email, editing shared
meetings, and deleting things need approval — but prompts are suggestions.
The enforcement lives in `jarvis/tools/__init__.py`:

1. Dangerous handlers (e.g. `gmail.send_draft`, `gcal.delete_event`,
   `tasks.delete`) take a keyword-only-by-convention `_confirmed=False`
   parameter and raise `ConfirmationRequired(prompt)` unless it's `True`.
   For calendar updates the check is dynamic: it only trips when the event
   actually has other attendees.
2. The dispatcher catches the exception, asks the **user** via a `confirm`
   callback — spoken question + yes/no answer in voice mode, keyboard
   prompt in text mode — and only re-invokes the handler with
   `_confirmed=True` if the user approved *in that same turn*. The flag is
   never persisted; the next dangerous call starts from zero.
3. The model cannot self-approve: every model-supplied argument starting
   with `_` is stripped before dispatch, so a tool call like
   `{"draft_id": "d1", "_confirmed": true}` still triggers the question.
   `tests/smoke_test.py` proves exactly this scenario end-to-end.

If the user declines, the tool returns a "user declined, do not retry"
result to the model, which reports back and moves on.

## Two LLM backends

`LLM_BACKEND` in `.env` selects how the brain reaches Claude:

- **`agent-sdk`** — `jarvis/agent_backend.py` drives the Claude Code CLI
  through the Claude Agent SDK, authenticating with the user's Claude
  subscription login (no API credits). Jarvis's 19 tools are registered as
  an in-process MCP server; every call still flows through
  `tools.execute`, so the confirmation gate applies unchanged. Claude
  Code's own built-in tools (Bash, file access, web) are explicitly
  disallowed. The SDK is async, so the backend runs a private event loop
  on a daemon thread behind the same synchronous `chat()` interface.
- **`api`** — the original path in `assistant.py`: the Anthropic SDK,
  pay-per-token, with the notes below.

## Anthropic API usage notes (`LLM_BACKEND=api`)

- Model `claude-fable-5`; reasoning is always on for this model, depth is
  tuned with `output_config.effort` (default `low` for snappy voice
  replies — configurable).
- `betas=["server-side-fallback-2026-06-01"]` + `fallbacks=[{"model":
  "claude-opus-4-8"}]`: if Fable's safety classifiers decline a benign
  request, the same call is transparently served by Opus instead of
  failing.
- The system prompt (personality + memories) is byte-stable for the whole
  session and marked with `cache_control: ephemeral`, so repeated turns
  read it from the prompt cache. The current timestamp is injected into
  each *user* message instead of the system prompt for the same reason.

## Data on disk

```
.env                  secrets and settings (git-ignored)
config/…prompt.md     editable personality + permission tiers
memory/*.md           one fact per file (git-ignored)
data/jarvis.db        tasks + reminders (SQLite, git-ignored)
data/google_token.json OAuth refresh token (git-ignored)
data/voices/*.onnx    Piper voice models
```
