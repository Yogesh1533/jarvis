# Jarvis — Personal Voice Assistant

An always-on, wake-word voice assistant that runs on your own machine. Say
**"Hey Jarvis"**, ask for something, and it answers out loud — with real
access to your Gmail, Google Calendar, a local task list, spoken reminders,
web search, and a persistent memory it maintains about you.

- **Private by design** — the microphone is processed locally by
  [openWakeWord](https://github.com/dscripka/openWakeWord); no audio leaves
  your machine until the wake word fires. Speech-to-text runs locally too
  (faster-whisper) unless you opt into a cloud provider.
- **Safe by design** — sending email, editing meetings that have other
  attendees, and deleting anything require your **spoken confirmation**,
  enforced in code (the model physically cannot execute those actions
  without it — see [ARCHITECTURE.md](ARCHITECTURE.md)).
- **Yours to shape** — the assistant's personality lives in
  [config/jarvis-voice-assistant-system-prompt.md](config/jarvis-voice-assistant-system-prompt.md).
  Edit it freely; no code changes needed.

Brain: Anthropic's `claude-fable-5`. TTS is pluggable: Piper (local, free,
default), ElevenLabs, or OpenAI.

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

**Option A — your Claude subscription (no API credits).** Set
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

## 4. First run — text mode (no audio needed)

```bash
python -m jarvis text
```

Type instead of talking; everything else (tools, memory, confirmations)
works identically. Try: *"add a task to buy milk tomorrow evening"*, then
*"what's on my task list?"*. Confirmations arrive as a `[CONFIRM] ... [yes/no]:`
prompt. This is the fastest way to test changes to the system prompt or tools.

There's also a browser chat UI over the same brain:

```bash
python -m jarvis web        # then open http://127.0.0.1:8765
```

Confirmations appear as a browser dialog; reminders pop in as notices.

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

**Cloud speech-to-text (optional).** Local Whisper is the default. For the
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
    <string>/Users/yogesh/Documents/jarvis/.venv/bin/python</string>
    <string>-m</string><string>jarvis</string><string>voice</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/yogesh/Documents/jarvis</string>
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

## 9. Tests

```bash
python tests/smoke_test.py
```

Runs offline (fake model, fake Gmail): exercises tasks, reminders, memory,
web search, and proves the confirmation gate blocks unconfirmed sends —
including a simulated model that tries to set the confirmation flag itself.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Wake word never triggers | Lower `WAKE_THRESHOLD` (e.g. 0.4); check mic permission. |
| Triggers on random speech | Raise `WAKE_THRESHOLD` (e.g. 0.6). |
| Cuts you off mid-sentence | Raise `SILENCE_DURATION`. |
| Slow transcription | Use `WHISPER_MODEL=tiny.en`, or `STT_PROVIDER=openai`. |
| "piper CLI not found" | `pip install piper-tts` inside the venv, and download a voice (step 6). |
| Google tool errors | Re-run `python -m jarvis setup-google`. |
| Slow replies | Keep `LLM_EFFORT=low`; raise to `medium`/`high` for harder questions. |
