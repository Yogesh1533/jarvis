# Jarvis — Personal Voice Assistant

An always-on, wake-word voice assistant that runs on your own machine. Say
**"Hey Jarvis"**, ask for something, and it answers out loud — with real
access to your Gmail, Google Calendar, a local task list, spoken reminders,
web search, and a persistent memory it maintains about you.

- **Private by design** — the microphone is processed locally by
  [openWakeWord](https://github.com/dscripka/openWakeWord); no audio leaves
  your machine until the wake word fires. Speech-to-text runs locally too
  (Whisper, on the Mac's GPU) unless you opt into a cloud provider.
- **Safe by design** — sending email, editing meetings that have other
  attendees, and deleting anything require your **spoken confirmation**,
  enforced in code (the model physically cannot execute those actions
  without it — see [ARCHITECTURE.md](ARCHITECTURE.md)).
- **Yours to shape** — the assistant's personality lives in
  [config/jarvis-voice-assistant-system-prompt.md](config/jarvis-voice-assistant-system-prompt.md).
  Edit it freely; no code changes needed.

Brain: Claude Sonnet 5.5 by default, through your Claude plan, or NVIDIA
Nemotron open models on Nebius Token Factory (set `LLM_BACKEND` and
`LLM_MODEL` in `.env`). TTS is pluggable: Piper (local,
free, default, with a voice per mood), ElevenLabs, or OpenAI.

## Nebius x NVIDIA Global AI Hackathon: Personal AI track

Jarvis is a voice assistant that lives on your Mac and runs its reasoning
on NVIDIA Nemotron open models through Nebius Token Factory. Your voice,
your memories and the wake word stay on the machine. Personal details are
masked before any text goes to the cloud, and anything that sends,
deletes or edits a shared meeting needs your spoken yes, enforced in code.

What the hackathon build added (branch `hackathon/nebius`):

- **Nemotron as the brain.** `LLM_BACKEND=nebius` drives all 59 tools
  through Token Factory's OpenAI-compatible API.
- **A router across three model sizes.** Quick commands ("pause the
  music") go to Nemotron 3.5 Lightning, everyday requests to Nemotron 3
  Super 120B, and planning or "prep me" requests to Nemotron 3 Ultra 550B.
  Rules, not an extra model call, so routing adds no latency and the HUD
  can say why each model was picked.
- **A privacy vault.** Emails, phone numbers and card numbers are swapped
  for placeholders like `[EMAIL_1]` in everything sent to Nebius, then
  restored on the Mac just before a tool runs and before Jarvis speaks.
- **Meeting prep.** "Prep me for my 2pm" pulls the meeting, recent email
  with each attendee, what Jarvis remembers about them and a web look at
  their company in parallel. Nemotron Ultra turns it into an on-screen
  briefing card and a short spoken summary.
- **A Brain panel in the HUD** showing which model answered, why, how
  long it took, the tokens used and how many values were masked.
- **Screen reading** through Nemotron 3.5 Super VL, which describes a
  screenshot for the text models.
- **Tests and an eval.** 249 offline checks (including one where the model
  tries to approve its own email send) and a tool-calling eval over 27
  everyday voice requests (`tests/tool_eval.py`).

![Jarvis architecture: local senses on the Mac, a privacy vault, and Nemotron models on Nebius Token Factory](docs/jarvis-architecture.png)

Quick start on Nebius: set `LLM_BACKEND=nebius` and `NEBIUS_API_KEY` in
`.env`, run `python -m jarvis nebius-models --probe` to check model
access, then `python -m jarvis web` (see section 4b). Design details are
in [ARCHITECTURE.md](ARCHITECTURE.md#three-llm-backends).

Built by Yogesh Dhakal.

---

## 1. Requirements

- macOS or Windows laptop with a microphone (Raspberry Pi works too, but
  use a small Whisper model).
- Python 3.9+ for the API backend, 3.10+ for the subscription backend
  (tip: `uv venv --python 3.12 .venv` gets you a modern Python without
  touching the system one).
- Claude access: either a Claude subscription (Pro/Max) or an Anthropic
  API key with credits — see step 3. Everything else is free.

## 2. Install

```bash
cd jarvis
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` in any editor — the next sections tell you what to put in it.

## 3. Claude access — pick one backend

**Option A — your Claude subscription (no API credits; the default).**
`LLM_BACKEND=agent-sdk` in `.env`. This routes Jarvis through the Claude
Code CLI using your Claude Pro/Max login; usage counts against your plan.
Needs Python 3.10+ and the CLI:

```bash
curl -fsSL https://claude.ai/install.sh | bash   # installs ~/.local/bin/claude
~/.local/bin/claude                              # run once, choose "Log in
                                                 # with your Claude account"
```

**Option B — API key.** Set `LLM_BACKEND=api`, create a key at
<https://platform.claude.com> (Settings → API keys), put it in `.env` as
`ANTHROPIC_API_KEY=sk-ant-...`, and add API credits under Settings →
Billing (billed separately from a Claude subscription).

**Option C — NVIDIA Nemotron on Nebius Token Factory (open models).**
Create a key in the [Token Factory](https://tokenfactory.nebius.com)
console and set, in `.env`:

```bash
LLM_BACKEND=nebius
NEBIUS_API_KEY=...
```

Then see which NVIDIA models your key can use, and check they do tool
calling, and put the one you want in `NEBIUS_MODEL`:

```bash
python -m jarvis nebius-models --probe
```

The wake word, speech-to-text and memory recall still run on your Mac.
Only the conversation text and tool results (including email and calendar
content Jarvis reads for you) go to Nebius. The confirmation gate works
exactly the same on every backend.

## 4. First run — text mode (no audio needed)

```bash
python -m jarvis text
```

Type instead of talking; everything else (tools, memory, confirmations)
works identically. Try: *"add a task to buy milk tomorrow evening"*, then
*"what's on my task list?"*. Confirmations arrive as a `[CONFIRM] ... [yes/no]:`
prompt. This is the fastest way to test changes to the system prompt or tools.

## 4b. The HUD (recommended)

A full-screen, Iron Man–style interface over the same brain: an animated
reactor that orbits, spirals and pulses as Jarvis listens, thinks and
speaks, with live panels for your agenda, tasks, timers, reminders, inbox,
system vitals and memories.

Build the front-end once (needs Node 18+):

```bash
cd frontend && npm install && npm run build && cd ..
```

Then run it and open <http://127.0.0.1:8765> in Chrome, Edge or Safari:

```bash
python -m jarvis web
```

Click **Bring Jarvis online** (browsers need one click before a page may
use the mic and speakers) and allow microphone access. From then on:

- Say **"Hey Jarvis"**, then your request. The wake word, turn-taking and
  Whisper transcription all run in the Python server on this Mac; the
  browser only streams mic audio to it over localhost.
- **Take your time.** A pause doesn't end your turn: Jarvis transcribes
  what you've said so far and, if it sounds unfinished ("turn off the
  lights in the…"), keeps listening; "hold on" or "let me think" buys more
  time. You'll see what it's hearing live, with a bar showing how long it
  will wait. Choose Snappy, Balanced or Patient in settings, or just say
  "give me more time to think".
- **Talk over it** to interrupt, like with a person. When you start
  talking, Jarvis turns its voice down at once. If you said real words, it
  stops and listens. If it was just "mm-hmm", "yeah", or its own voice
  leaking into the mic, it carries on. Saying something while it's still
  thinking adds to your request. Replies start speaking after the first
  sentence, and Jarvis says a short "one moment" while slow tools run.
- **Conversations stay open**: after a reply, Jarvis keeps listening for
  about 20 seconds so you can carry on without the wake word. Say "that's
  all" or "thanks, Jarvis" to end early, or choose shorter conversations
  in settings. Settings also has wake word sensitivity and a microphone
  picker with a level meter. Jarvis follows headsets and USB mics as they
  come and go.
- **Moods**: Classic, Calm, Focused, Upbeat and Night each have their own
  voice, pace and style. Pick one from the top bar, or say "switch to calm
  mode". You can also pick any installed voice, or let Jarvis choose a
  mood from how you sound.
- Press **Space** / tap the reactor to talk without the wake word,
  **Esc** to interrupt, **/** to type, **⌘K** for the command palette
  (moods, voices, themes, settings, or type anything to ask).
- Jarvis can put **cards** on screen (lists, numbers, headlines) and
  control the interface by voice: "show my history", "switch to orb mode",
  "clear the cards", "mute the mic".
- Confirmations appear as an on-screen alert and are spoken; answer by
  voice, by typing yes/no, or with the buttons.
- **Now playing** follows whatever is playing on your Mac (YouTube Music,
  including its Chrome app, Spotify, Apple Music or a browser tab) live,
  with artwork, a progress bar you can drag to seek, ±15 s, play/pause,
  skip and volume. It reads macOS's media session through
  [`media-control`](https://github.com/ungive/media-control):
  `brew install media-control`. Without it, only Spotify and Music work.
  Conversation history (clock icon) survives restarts.

## 4c. The Mac app (⌘J from anywhere)

`desktop/` wraps the HUD in a small Electron app: no browser tab, no
"Bring Jarvis online" click, and it starts the Python server itself (or
uses one already running).

```bash
cd desktop && npm install && npm run pack
```

That builds `Jarvis.app`, installs it into `~/Applications` and signs it
for this Mac. Open it from Spotlight. Then:

- **⌘J** anywhere: Jarvis appears and listens (or stops talking).
- **⌘⇧J**: switch between the full interface and a small floating orb
  that stays on top of your other windows without taking focus.
- **Switch to another app** and the full interface shrinks to the orb by
  itself, so Jarvis stays in view while you work. Come back through the
  Dock, "Show Jarvis" or ⌘Tab and the full interface returns; clicking the
  orb itself doesn't expand it. Turn this off with "Orb when I switch to
  another app" in the menu-bar icon.
- Menu-bar icon: talk, show, orb/full, orb-on-switch, **Launch at login**, server log, quit.
  Closing the window keeps Jarvis listening in the menu bar.

The first launch asks for the microphone, and macOS may ask to let Jarvis
use files in iCloud Drive (where this project lives): allow both. ⌘J
replaces that shortcut in other apps (e.g. Chrome's Downloads) while Jarvis
runs. Server logs go to `~/Library/Logs/Jarvis/server.log`. For development,
`cd desktop && npm start` runs it without packaging.

Front-end development with hot reload: run `python -m jarvis web` and, in
another terminal, `cd frontend && npm run dev`, then open
<http://localhost:5173>.

> The project lives in iCloud Drive, so the virtualenv and `node_modules`
> are kept in `.venv.nosync` and `frontend/node_modules.nosync` (iCloud
> skips `.nosync` names) behind `.venv` / `node_modules` symlinks. Keep it
> that way: iCloud evicting packages makes Python hang on import.

## 5. Google — Gmail and Calendar (optional but recommended)

One-time setup, roughly 5 minutes:

1. Go to <https://console.cloud.google.com> and create a project (any name).
2. **APIs & Services → Library**: enable the **Gmail API** and the
   **Google Calendar API**.
3. **APIs & Services → OAuth consent screen**: choose **External**, fill in
   the app name and your email, and add **your own Gmail address as a test
   user**. (Test mode is fine forever for personal use.)
4. **APIs & Services → Credentials → Create credentials → OAuth client ID →
   Desktop app**. Download the JSON and save it as `credentials.json` in
   the project folder (or point `GOOGLE_CREDENTIALS_PATH` at it).
5. Run:

   ```bash
   python -m jarvis setup-google
   ```

   A browser opens; sign in and approve. The token is stored at
   `data/google_token.json` and refreshes itself from then on.

   If Google says "Access blocked … has not completed the Google
   verification process", your address isn't a test user yet. Add it under
   **Google Auth Platform → Audience → Test users**, then run the command again.

Once connected, Jarvis brings things up without being asked (Settings →
Heads-ups, or just say "warn me 10 minutes before meetings"):

- **Meeting alerts**: a spoken heads-up 5 minutes before each event on your
  calendar (5/10/15 minutes, or off). If you haven't touched the Mac in
  10 minutes, it only shows on screen.
- **Morning briefing**: from 7:00 (or a time you choose), the first time you
  sit down at your Mac before noon, Jarvis reads you the weather, your first
  meetings and the email that matters. Once a day.

## 6. Voice — pick your TTS

**Piper (default, free, local).** Download a voice once:

```bash
python -m piper.download_voices en_GB-alan-medium --data-dir data/voices
```

Then make sure `PIPER_VOICE` in `.env` points at the downloaded `.onnx`
file. Browse other voices at <https://rhasspy.github.io/piper-samples/>.

**ElevenLabs (best quality).** Create a key at <https://elevenlabs.io>
(Profile → API keys), then in `.env` set `TTS_PROVIDER=elevenlabs` and
`ELEVENLABS_API_KEY=...`. Pick a voice ID from their Voice Library if you
don't want the default.

**OpenAI.** Create a key at <https://platform.openai.com/api-keys>, then set
`TTS_PROVIDER=openai` and `OPENAI_API_KEY=...`.

**Speech to text.** On Apple Silicon Macs, Jarvis runs Whisper large-v3-turbo
on the GPU (`mlx-whisper`, in `requirements.txt`; the model downloads once,
about 1.6 GB). On spoken commands with room noise it got 10.5% of words
wrong versus 27% for the old `base.en` default, in about 0.4 s. Other Macs
use `faster-whisper` on the CPU. Put names Jarvis should expect (contacts,
artists, places) in `STT_VOCABULARY` in `.env`, comma-separated. For the
OpenAI Whisper API instead, set `STT_PROVIDER=openai` (uses the same
`OPENAI_API_KEY`).

## 7. Run it

```bash
python -m jarvis
```

First launch downloads the wake-word and Whisper models (a minute or two).
Then: say **"Hey Jarvis"**, wait for the chime, and speak. After it answers
it keeps listening for ~6 seconds so you can follow up without repeating the
wake word. All timings are tunable in `.env`.

macOS will ask for microphone permission for your terminal the first time —
allow it (System Settings → Privacy & Security → Microphone).

Things to try:

- "Good morning" → a spoken briefing: weather, agenda, mail, tasks.
- "Set a ten minute timer for the pasta."
- "What's playing?" / "Skip this song" / "Go back 15 seconds" / "Play Sajjan Raj Vaidya on YouTube Music."
- "What am I looking at?" / "Help me with this error." *(Jarvis looks at your screen)*
- "Summarize this page." *(uses the browser tab you're on)*
- "Make a note: ideas for the thesis intro…" / "What did I note about the landlord?"
- "Text Mum that I'm running late." *(asks you to confirm first)*
- "Open Safari and go to the BBC." / "Take a screenshot."
- "Find my resume and summarize it."
- "What's in the news about SpaceX?" / "Read this page: <url>"
- "Run my Good Night shortcut."

- "What's on my calendar this week?"
- "Search my email for anything from the university."
- "Draft a reply saying I'll be there." → "Okay, send it." *(asks you to confirm out loud)*
- "Remind me in 20 minutes to stretch."
- "Remember that my sister's birthday is March 3rd."

## 8. Run on startup (optional)

**macOS** — create `~/Library/LaunchAgents/com.yogesh.jarvis.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.yogesh.jarvis</string>
  <key>ProgramArguments</key><array>
    <string>/Users/yogesh/Developer/apps/jarvis/.venv/bin/python</string>
    <string>-m</string><string>jarvis</string><string>voice</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/yogesh/Developer/apps/jarvis</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/jarvis.log</string>
  <key>StandardErrorPath</key><string>/tmp/jarvis.err</string>
</dict></plist>
```

Load it with `launchctl load ~/Library/LaunchAgents/com.yogesh.jarvis.plist`.
Note: launchd-started processes need mic permission granted to the Python
binary; if it can't hear you, run it once from Terminal first.

**Windows** — Task Scheduler → Create Task → trigger *At log on* → action:
`C:\...\jarvis\.venv\Scripts\python.exe` with arguments `-m jarvis voice`
and *Start in* set to the project folder.

## 8b. Memory recall

Jarvis can find things you told it, or discussed, weeks ago by meaning, not
exact words ("what hotel did we pick for Lisbon?"). It uses a small local
embedding model (`fastembed`, about 64 MB, downloaded once to
`~/.cache/jarvis/models`); nothing is sent anywhere. The first launch builds
the index in the background, so give it a few seconds. Settings in `.env`:
`RECALL_INDEX_TURNS=0` stops indexing conversations, `RECALL_MIN_SCORE`
tunes how close a match must be, and `MEMORY_PRELOAD_CHARS` caps how much
memory goes into each session's prompt before it switches to an index.
Without `fastembed` installed, recall falls back to keyword search.

You can also switch Claude model (Sonnet, Opus, Haiku) from Settings in the
HUD, or by saying "use Opus" / "back to the default model".

## 9. Tests

```bash
python tests/smoke_test.py
```

Runs offline (fake model, fake Gmail): exercises tasks, reminders, memory,
turn-taking (pausing mid-thought, "let me think", barge-in pre-roll),
moods and voice-controlled settings, HUD cards, web search, and proves the
confirmation gate blocks unconfirmed sends — including a simulated model
that tries to set the confirmation flag itself.

## 9b. Tool-calling eval (Nebius)

```bash
python tests/tool_eval.py --limit 10   # quick check, ~100k tokens
python tests/tool_eval.py              # all 27 requests on auto routing, ~270k tokens
python tests/tool_eval.py --configs auto lightning super ultra   # full comparison, ~1M
```

27 everyday voice requests, each in a fresh conversation with the real
system prompt and every tool offered. Tools are stubbed, so nothing is
actually sent or changed. It scores whether the model picks the right tool
and how fast it decides (one request per case), and writes
`tests/tool_eval_results.md`. It uses real tokens and stops at `--budget`
(default 300k).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Wake word never triggers | Settings → Listening → Wake word: Sensitive (or lower `WAKE_THRESHOLD`); check mic permission. |
| Triggers on random speech | Wake word: Strict (or raise `WAKE_THRESHOLD`). |
| Cuts you off mid-sentence | Say "give me more time to think" (or Settings → Listening → Patient). |
| Jarvis interrupts itself | Its own voice is reaching the mic: use headphones, or turn off "Stop talking when I interrupt". |
| Jarvis doesn't hear you at all | Settings → Listening: check the microphone picker and that the level meter moves. The top bar says "Waiting for a microphone" when none is connected. |
| Now playing is empty for YouTube Music | `brew install media-control`, then restart Jarvis. |
| "What's on my screen" sees only the wallpaper | Allow Jarvis under System Settings → Privacy & Security → Screen Recording, then restart it. |
| App stuck on "Starting the Jarvis server" | Look for a macOS prompt about iCloud Drive access and allow it; check `~/Library/Logs/Jarvis/server.log`. |
| Jarvis mishears names or words | Add them to `STT_VOCABULARY` in `.env` (comma-separated), then restart. |
| Slow transcription | On Apple Silicon, check Settings shows the GPU model (`pip install mlx-whisper`). Elsewhere use `WHISPER_MODEL=tiny.en` or `STT_PROVIDER=openai`. |
| "piper CLI not found" | `pip install piper-tts` inside the venv, and download a voice (step 6). |
| Google tool errors | Re-run `python -m jarvis setup-google`. |
| Slow replies | Keep `LLM_EFFORT=low`; raise to `medium`/`high` for harder questions. |
| HUD says "Microphone blocked" | Allow the mic for `127.0.0.1` in the browser's site settings, then toggle the mic button. |
| Mac control asks for permission | macOS asks once per app the first time Jarvis controls Music/Spotify etc. (System Settings → Privacy & Security → Automation). Allow it for your terminal/Python. |
| "You've hit your monthly spend limit" | Your Claude plan's usage limit for that model; set `LLM_MODEL` to another model in `.env` or wait for the reset. |
