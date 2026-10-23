# Architecture

```
                        ┌─────────────────────────────────────────────┐
 mic ──► wake.py        │  assistant.py — the brain                   │
        (openWakeWord,  │                                             │
         always local)  │  claude-fable-5 via Anthropic API           │
            │ wake word │  (server-side fallback to claude-opus-4-8   │
            ▼           │   if a request is safety-declined)          │
        recorder.py     │                                             │
        (turns.py: VAD  │  system prompt = config/*.md  +  memory/*.md│
         + semantic EoT)│  loaded fresh each session, prompt-cached   │
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
`web.py` + `frontend/` (the HUD, below).
`assistant.py` and everything below it is audio-free, which is what makes
the text mode and the offline test suite possible.

## The HUD (`web.py` + `frontend/`)

```
 browser (React + Three.js)                     web.py (FastAPI, 127.0.0.1)
 ─────────────────────────                      ───────────────────────────
 mic → AudioWorklet → 16 kHz int16 ──binary──►  VoicePipeline (mic owner only)
                                    /ws          sleep:  openWakeWord
                                                 record: TurnDetector + live
                                                         Whisper checks
                                                 watch:  barge-in while speaking
                                                 → Hub.submit()
 reactor / panels / live transcript ◄─JSON──    Hub: state, hearing, transcript,
 queues sentence audio, reports                      tool, reply/say + audio
   ──playback_done(id)──►                            segments, filler, card, hud,
 cards / palette / settings ◄─settings──             settings, confirm, notify
 panels ◄──────── REST /api/* ───────────────
```

- The server owns the state machine (`idle → listening → thinking →
  speaking`, plus `confirm`); the browser renders it. While Jarvis thinks,
  incoming audio is ignored. While it speaks, the pipeline only watches
  for the user talking over it (6 of 8 chunks scored as speech by the
  VAD, on echo-cancelled mic audio); then it stops playback, keeps the
  last ~640 ms as pre-roll and starts a new turn, and the next message
  tells the model it was cut off. After a spoken reply the browser
  reports playback finished (by utterance id) and the server opens the
  follow-up window, exactly like voice mode.
- Replies are synthesized sentence by sentence (first sentence alone,
  then the rest), so speech starts after one sentence of TTS. Audio and
  "one moment" fillers go only to the window that owns the mic, so with
  the app and a browser tab open Jarvis speaks once.
- Settings (`settings.py`, persisted to `data/settings.json`) live on the
  server: mood, voice, patience, barge-in, fillers, theme. The HUD and the
  model's tools (`voice_*`, `assistant_set_preference`) both change them,
  and every window is told. `moods.py` maps each mood to a Piper voice,
  pace and volume, plus a style note prefixed to each user message.
- Tools reach the HUD through `hud_bridge.py` (`hud_show_card`,
  `hud_control`) without importing the web server; with no HUD open they
  say so and the model answers aloud instead.
- The confirmation gate is unchanged: `Hub.web_confirm` blocks the turn
  until the user answers by voice, typing, or the on-screen buttons.
- Panel deletes (tasks, reminders, memories) are direct user clicks behind
  their own "are you sure", so those REST endpoints pass `_confirmed=True`;
  the model never reaches them.
- Reminders and timers are announced in the HUD and spoken when Jarvis is
  free. Conversation turns are logged to the `conversation` table.

## Turn-taking (`audio/turns.py`)

Modelled on how ChatGPT's voice mode avoids cutting people off (OpenAI's
documented "semantic VAD"): silence alone doesn't end a turn, meaning does.

1. Silero VAD (bundled with faster-whisper) scores every 80 ms chunk;
   speech starts after two chunks ≥ 0.5 (or one ≥ 0.85) and 320 ms of
   pre-roll is kept so the first syllable isn't clipped.
2. At the first pause of `base` seconds the audio so far is transcribed
   and `judge()` classifies it: **complete** (end after `base` of silence),
   **incomplete** (a dangling "and/the/to…", a trailing comma, a lone word:
   wait up to `limit`), or **hold** ("hold on", "let me think", "um":
   wait up to 15 s). Speaking again clears the verdict.
3. When the turn ends after a complete verdict, that transcript is reused,
   so there's no second Whisper pass.

| Patience | base | limit |
|---|---|---|
| snappy | 0.45 s | 2 s |
| balanced (default) | 0.7 s | 4 s |
| patient | 1.0 s | 8 s |

Confirmation answers always use snappy. Voice mode (`voice.py`) uses the
same detector through `recorder.record_utterance`.

## The Mac app (`desktop/`)

An Electron shell around the same HUD: `server.js` starts
`.venv/bin/python -m jarvis web` unless a server already answers (and
only ever stops one it started, restarting it on crashes); `main.js` owns
one transparent window that switches between the full HUD and a floating,
always-on-top orb, the menu-bar icon, launch-at-login, and the global
shortcuts (⌘J summon/listen, ⌘⇧J orb/full). `preload.js` exposes four
calls to the page as `window.jarvisDesktop`; the page needs no other
privileges. The microphone is granted only to the local server's origin.

## Components

| Piece | File(s) | Notes |
|---|---|---|
| Config | `jarvis/config.py`, `.env` | All keys, paths, and timings. Nothing sensitive in code. |
| Wake word | `audio/wake.py` | openWakeWord `hey_jarvis` model, ONNX runtime, 80 ms frames at 16 kHz. Runs continuously; nothing is recorded or sent anywhere until it fires. |
| Turn-taking | `audio/turns.py`, `audio/recorder.py` | Silero VAD + transcript-based end-of-turn (see above). |
| STT | `audio/stt.py` | `faster-whisper` locally (default) or OpenAI Whisper API (`STT_PROVIDER=openai`). |
| Brain | `jarvis/assistant.py` | Multi-turn conversation, manual tool loop, prompt caching (`cache_control` on the system block), refusal handling with server-side model fallback. |
| Tools | `jarvis/tools/*` | Schemas + dispatcher in `tools/__init__.py`; one module per capability. |
| TTS | `audio/tts.py` | Piper in-process (voices cached, ~50 ms per sentence once loaded; speed/volume from the mood), ElevenLabs, or OpenAI — selected by `TTS_PROVIDER`. |
| Settings, moods | `settings.py`, `moods.py`, `tools/persona.py` | Server-side settings shared by every window and changeable by voice. |
| HUD tools | `hud_bridge.py`, `tools/hud.py` | Cards and interface actions pushed to open HUD windows. |
| Reminders | `tools/reminders.py` | SQLite table + daemon thread; due reminders are spoken (voice mode) or printed (text mode). |
| Mac control | `tools/mac.py` | osascript with all user/model strings passed as argv (never spliced into script source); arbitrary AppleScript and quitting apps are confirmation-gated. |
| Files | `tools/files.py` | Spotlight search, read (text/PDF) and open, confined to `FILES_ROOTS`. |
| Weather, news, pages | `tools/weather.py`, `tools/websearch.py` | Open-Meteo (no key), DuckDuckGo news, readable-text page fetch. |
| Timers, briefing, vitals | `tools/timers.py`, `tools/briefing.py`, `tools/system.py` | In-memory timers; one-call daily briefing; psutil vitals for gauges. |
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
  subscription login (no API credits). Jarvis's tools are registered as
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
