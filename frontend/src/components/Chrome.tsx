import { useEffect, useRef, useState } from "react";
import { activate, answerConfirm, ask, chooseMic, interrupt, setMic, setServer, toggleFullscreen } from "../lib/actions";
import { api } from "../lib/api";
import { audio } from "../lib/audio";
import { clock, longDate, toolDetail, toolLabel } from "../lib/format";
import { useStore } from "../lib/store";
import { THEMES, type ThemeId } from "../lib/themes";
import { MoodSwitch } from "./Extras";
import { Icon } from "./Panel";
import { WeatherReadout } from "./Panels";

// ── Boot ───────────────────────────────────────────────────────────
const BOOT_LINES = [
  "Initializing neural interface",
  "Linking to Claude core",
  "Calibrating audio array",
  "Loading tool systems",
  "All systems online",
];

export function Boot({ onDone, auto = false }: { onDone: () => void; auto?: boolean }) {
  const [phase, setPhase] = useState<"ready" | "running" | "out">("ready");
  const [shown, setShown] = useState(0);

  const start = async () => {
    setPhase("running");
    await audio.init();
    audio.sounds = useStore.getState().local.sounds;
    audio.sfx("boot");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const step = reduced ? 60 : 260;
    BOOT_LINES.forEach((_, i) => setTimeout(() => setShown(i + 1), step * (i + 1)));
    setTimeout(() => {
      setPhase("out");
      onDone();
    }, step * (BOOT_LINES.length + 1.5));
  };

  // The desktop app may start audio without a click, so it boots itself.
  useEffect(() => {
    if (auto) start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (phase === "ready" && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        start();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className={"boot boot-" + phase} aria-live="polite">
      {phase === "ready" && !auto ? (
        <div className="boot-card">
          <p className="boot-mark">J.A.R.V.I.S.</p>
          <p className="boot-sub">Just A Rather Very Intelligent System</p>
          <button className="boot-btn" onClick={start} autoFocus>
            Bring Jarvis online
          </button>
          <p className="boot-hint">Your browser needs one click before Jarvis can listen and speak.</p>
        </div>
      ) : (
        <ol className="boot-lines">
          {BOOT_LINES.slice(0, shown).map((l, i) => (
            <li key={l} className={i === BOOT_LINES.length - 1 ? "final" : ""}>
              {l}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ── Top bar ────────────────────────────────────────────────────────
export function TopBar() {
  const [now, setNow] = useState(new Date());
  const online = useStore((s) => s.online);
  const voice = useStore((s) => s.voice);
  const wantMic = useStore((s) => s.local.mic);
  const setDrawer = (d: "history" | "settings") =>
    useStore.getState().set({ drawer: useStore.getState().drawer === d ? null : d, palette: false });

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const status = !online
    ? "Reconnecting to the server"
    : !voice.mic
      ? wantMic ? "Waiting for a microphone" : "Microphone off"
      : !voice.ready
        ? "Loading voice"
        : voice.wake
          ? `Listening for “${voice.wake_word}”`
          : "Wake word unavailable, press Space to talk";

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">J.A.R.V.I.S.</span>
        <span className={"link-state " + (online && voice.mic && voice.ready ? "ok" : online ? "warn" : "down")}>
          <i aria-hidden="true" />
          {status}
        </span>
      </div>
      <div className="chrono">
        <time className="chrono-time" dateTime={now.toISOString()}>
          {clock(now)}
          <span className="chrono-sec">{String(now.getSeconds()).padStart(2, "0")}</span>
        </time>
        <span className="chrono-date">{longDate(now)}</span>
      </div>
      <div className="top-actions">
        <WeatherReadout />
        <MoodSwitch />
        <button className="icon-btn" onClick={() => useStore.getState().set({ palette: true, drawer: null })} aria-label="Command palette" title="Commands (⌘K)">
          <Icon name="command" />
        </button>
        <button className="icon-btn" onClick={() => setDrawer("history")} aria-label="Conversation history" title="Conversation history">
          <Icon name="history" />
        </button>
        <button className="icon-btn" onClick={() => setDrawer("settings")} aria-label="Settings" title="Settings">
          <Icon name="settings" />
        </button>
        <button className="icon-btn" onClick={toggleFullscreen} aria-label="Toggle full screen" title="Full screen">
          <Icon name="expand" />
        </button>
      </div>
    </header>
  );
}

// ── Status line, caption, tool trace ──────────────────────────────
export function StatusLine() {
  const mode = useStore((s) => s.mode);
  const voice = useStore((s) => s.voice);
  const text: Record<string, string> = {
    boot: "",
    idle: voice.mic && voice.wake ? `Say “${voice.wake_word}” or press Space` : "Press Space or tap the reactor to talk",
    listening: "Listening",
    thinking: "Working on it",
    speaking: "Speaking. Press Esc to interrupt",
    confirm: "Waiting for your go-ahead",
  };
  return (
    <p className={"status-line s-" + mode} aria-live="polite">
      {text[mode]}
    </p>
  );
}

export function Caption({ compact = false }: { compact?: boolean }) {
  const caption = useStore((s) => s.caption);
  const [shown, setShown] = useState("");
  useEffect(() => {
    if (!caption) return;
    if (caption.role === "user") {
      setShown(caption.text);
      return;
    }
    // Typewriter reveal, capped so long replies don't lag behind the voice.
    const full = caption.text;
    const perChar = Math.max(8, Math.min(32, 2600 / full.length));
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setShown(full.slice(0, i));
      if (i >= full.length) clearInterval(id);
    }, perChar);
    return () => clearInterval(id);
  }, [caption]);
  if (!caption) return null;
  return (
    <div className={"caption caption-" + caption.role + (compact ? " compact" : "")} key={caption.key}>
      <span className="caption-who">{caption.role === "user" ? "You" : "Jarvis"}</span>
      <p>{shown}</p>
    </div>
  );
}

export function ToolTrace() {
  const tools = useStore((s) => s.tools);
  const mode = useStore((s) => s.mode);
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((x) => x + 1), 1000);
    return () => clearInterval(id);
  }, []);
  const recent = tools.filter((t) => t.phase === "start" || Date.now() - t.at < (mode === "thinking" ? 60_000 : 8000)).slice(-4);
  if (!recent.length) return null;
  return (
    <ul className="tool-trace" aria-label="What Jarvis is doing">
      {recent.map((t) => (
        <li key={t.id} className={t.phase === "start" ? "run" : t.ok ? "ok" : "fail"}>
          <i aria-hidden="true" />
          <span className="tt-label">{toolLabel(t.name)}</span>
          <span className="tt-detail">{toolDetail(t.args)}</span>
        </li>
      ))}
    </ul>
  );
}

// ── Command bar ────────────────────────────────────────────────────
const QUICK = [
  { label: "Brief me", text: "Good morning. Brief me on my day." },
  { label: "Today's schedule", text: "What's on my calendar today?" },
  { label: "Unread mail", text: "Anything important in my unread email?" },
  { label: "Headlines", text: "What are today's top headlines?" },
];

export function CommandBar({ inputRef }: { inputRef: React.RefObject<HTMLInputElement> }) {
  const [text, setText] = useState("");
  const mic = useStore((s) => s.local.mic);
  const mode = useStore((s) => s.mode);
  const confirm = useStore((s) => s.confirm);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    setText("");
    ask(t);
  };

  return (
    <div className="command">
      <div className="quick" role="group" aria-label="Quick requests">
        {QUICK.map((q) => (
          <button key={q.label} className="chip" onClick={() => ask(q.text)} disabled={mode === "thinking"}>
            {q.label}
          </button>
        ))}
      </div>
      <form className="command-bar" onSubmit={submit}>
        <button
          type="button"
          className={"mic-btn " + (mic ? "on" : "off")}
          onClick={() => setMic(!mic)}
          aria-pressed={mic}
          aria-label={mic ? "Turn microphone off" : "Turn microphone on"}
          title={mic ? "Microphone on (always listening for the wake word)" : "Microphone off"}
        >
          <Icon name={mic ? "mic" : "mic-off"} />
        </button>
        <input
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={confirm ? "Type yes or no" : "Ask Jarvis anything"}
          aria-label="Message Jarvis"
          autoComplete="off"
        />
        <button type="submit" className="send-btn" aria-label="Send" disabled={!text.trim()}>
          <Icon name="send" />
        </button>
      </form>
      <p className="keys">
        <kbd>Space</kbd> talk <kbd>Esc</kbd> interrupt <kbd>/</kbd> type <kbd>⌘K</kbd> commands
      </p>
    </div>
  );
}

// ── Confirmation ───────────────────────────────────────────────────
export function ConfirmDialog() {
  const prompt = useStore((s) => s.confirm);
  const declineRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (prompt) declineRef.current?.focus();
  }, [prompt]);
  if (!prompt) return null;
  const [headline, ...rest] = prompt.split("\n");
  const detail = rest.join("\n").trim();
  return (
    <div className="confirm" role="alertdialog" aria-labelledby="confirm-title" aria-describedby="confirm-body">
      <p className="confirm-kicker">Jarvis needs your go-ahead</p>
      <h2 id="confirm-title">{headline}</h2>
      {detail && <pre id="confirm-body">{detail}</pre>}
      <div className="confirm-actions">
        <button className="btn-approve" onClick={() => answerConfirm(true)}>Approve</button>
        <button className="btn-decline" ref={declineRef} onClick={() => answerConfirm(false)}>Decline</button>
      </div>
      <p className="confirm-hint">Or say “yes” to approve. Anything else declines.</p>
    </div>
  );
}

// ── Toasts ─────────────────────────────────────────────────────────
export function Toasts() {
  const toasts = useStore((s) => s.toasts);
  const dismiss = useStore((s) => s.dismiss);
  return (
    <div className="toasts" aria-live="assertive">
      {toasts.map((t) => (
        <div key={t.id} className={"toast toast-" + t.kind} role="status">
          <span>{t.text}</span>
          <button className="ghost-x" onClick={() => dismiss(t.id)} aria-label="Dismiss">
            <Icon name="close" />
          </button>
        </div>
      ))}
    </div>
  );
}

// ── Drawers ────────────────────────────────────────────────────────
function Drawer({ title, children }: { title: string; children: React.ReactNode }) {
  const close = () => useStore.getState().set({ drawer: null });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <aside className="drawer" aria-label={title}>
      <header>
        <h2>{title}</h2>
        <button className="icon-btn" onClick={close} aria-label="Close">
          <Icon name="close" />
        </button>
      </header>
      <div className="drawer-body">{children}</div>
    </aside>
  );
}

interface HistoryRow {
  id: number;
  role: "user" | "jarvis";
  text: string;
  created_at: string;
}

export function HistoryDrawer() {
  const logLen = useStore((s) => s.log.length);
  const [rows, setRows] = useState<HistoryRow[] | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    api<HistoryRow[]>("/api/history?limit=200").then((r) => setRows(r.data ?? []));
  }, [logLen]);
  useEffect(() => endRef.current?.scrollIntoView(), [rows]);
  const clear = async () => {
    if (!window.confirm("Clear the saved conversation log? Jarvis's memories are not affected.")) return;
    await api("/api/history", { method: "DELETE" });
    setRows([]);
  };
  let lastDay = "";
  return (
    <Drawer title="Conversation">
      {rows && rows.length === 0 && <p className="empty">No conversation yet.</p>}
      <ol className="history">
        {rows?.map((r) => {
          const day = r.created_at.slice(0, 10);
          const show = day !== lastDay;
          lastDay = day;
          return (
            <li key={r.id} className={"h-" + r.role}>
              {show && <span className="h-day">{new Date(day).toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })}</span>}
              <span className="h-time">{r.created_at.slice(11, 16)}</span>
              <p>{r.text}</p>
            </li>
          );
        })}
      </ol>
      <div ref={endRef} />
      {rows && rows.length > 0 && (
        <button className="text-btn danger" onClick={clear}>Clear conversation log</button>
      )}
    </Drawer>
  );
}

const PATIENCE: { id: "snappy" | "balanced" | "patient"; label: string; note: string }[] = [
  { id: "snappy", label: "Snappy", note: "Replies the moment you stop" },
  { id: "balanced", label: "Balanced", note: "Waits through short pauses" },
  { id: "patient", label: "Patient", note: "Gives you time to think" },
];

const WAKE: { id: "low" | "normal" | "high"; label: string; note: string }[] = [
  { id: "low", label: "Strict", note: "Fewer false starts; say it clearly" },
  { id: "normal", label: "Normal", note: "A good balance for most rooms" },
  { id: "high", label: "Sensitive", note: "Hears you from across the room, sometimes wakes by mistake" },
];

const BRIEFING_TIMES = ["06:00", "06:30", "07:00", "07:30", "08:00", "08:30", "09:00", "09:30", "10:00"];

function timeOfDay(hhmm: string) {
  const [h, m] = hhmm.split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "am" : "pm"}`;
}

/** Which mic to use, with a live meter so you can see it hears you. */
function MicPicker() {
  const local = useStore((s) => s.local);
  const [mics, setMics] = useState<{ id: string; label: string }[]>([]);
  const meter = useRef<HTMLElement>(null);

  useEffect(() => {
    const load = () => audio.microphones().then(setMics).catch(() => setMics([]));
    load();
    navigator.mediaDevices?.addEventListener("devicechange", load);
    let raf = 0;
    const tick = () => {
      if (meter.current) meter.current.style.setProperty("--level", String(audio.level("mic")));
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => {
      cancelAnimationFrame(raf);
      navigator.mediaDevices?.removeEventListener("devicechange", load);
    };
  }, [local.mic]);

  return (
    <>
      <label className="select-row">
        <span>Microphone</span>
        <select value={local.micDevice} onChange={(e) => chooseMic(e.target.value)} disabled={!local.mic}>
          <option value="">System default{audio.micLabel && !local.micDevice ? ` (${audio.micLabel})` : ""}</option>
          {mics.map((m) => (
            <option key={m.id} value={m.id}>{m.label}</option>
          ))}
        </select>
      </label>
      {local.mic && (
        <div className="mic-meter" role="img" aria-label="Microphone level">
          <i ref={meter} />
        </div>
      )}
    </>
  );
}

export function SettingsDrawer() {
  const server = useStore((s) => s.server);
  const local = useStore((s) => s.local);
  const persona = useStore((s) => s.persona);
  const config = useStore((s) => s.config);
  const voice = useStore((s) => s.voice);

  const toggleSounds = () => {
    useStore.getState().setLocal({ sounds: !local.sounds });
    audio.sounds = !local.sounds;
  };

  return (
    <Drawer title="Settings">
      <fieldset className="setting">
        <legend>Mood</legend>
        <div className="mood-grid">
          {Object.entries(persona.moods).map(([id, m]) => (
            <button
              key={id}
              className={"mood-opt mood-" + id + (server.mood === id ? " active" : "")}
              aria-pressed={server.mood === id}
              onClick={() => setServer({ mood: id, voice: "" })}
            >
              <b>{m.label}</b>
              <span>{m.blurb}</span>
            </button>
          ))}
        </div>
        <Toggle label="Let Jarvis pick a mood from how you sound" on={server.auto_mood} onChange={() => setServer({ auto_mood: !server.auto_mood })} />
      </fieldset>

      <fieldset className="setting">
        <legend>Model</legend>
        <label className="select-row">
          <span>Model</span>
          <select value={server.model} onChange={(e) => setServer({ model: e.target.value })}>
            <option value="">{config?.backend === "nebius" ? "Automatic (picks per request)" : `Default (${persona.models[persona.default_model] || persona.default_model})`}</option>
            {Object.entries(persona.models).map(([id, label]) => (
              <option key={id} value={id}>{label}</option>
            ))}
          </select>
        </label>
        <p className="fine">{config?.backend === "nebius"
          ? "Automatic sends quick commands to Lightning, planning to Ultra and the rest to Super. Pick one to pin it."
          : "Takes effect from the next reply. Opus thinks deepest but uses more of your plan; Haiku is quickest."}</p>
      </fieldset>

      <fieldset className="setting">
        <legend>Voice</legend>
        <label className="select-row">
          <span>Speaking voice</span>
          <select value={server.voice} onChange={(e) => setServer({ voice: e.target.value })}>
            <option value="">Match the mood{persona.voices[persona.voice] && !server.voice ? ` (${persona.voices[persona.voice]})` : ""}</option>
            {Object.entries(persona.voices).map(([id, label]) => (
              <option key={id} value={id}>{label}</option>
            ))}
          </select>
        </label>
        <Toggle label="Speak typed replies out loud" on={server.speak} onChange={() => setServer({ speak: !server.speak })} />
        <Toggle label="Say “one moment” while working" on={server.fillers} onChange={() => setServer({ fillers: !server.fillers })} />
      </fieldset>

      <fieldset className="setting">
        <legend>Listening</legend>
        <div className="segmented" role="radiogroup" aria-label="How long Jarvis waits when you pause">
          {PATIENCE.map((p) => (
            <button key={p.id} role="radio" aria-checked={server.patience === p.id} className={server.patience === p.id ? "active" : ""} onClick={() => setServer({ patience: p.id })}>
              {p.label}
            </button>
          ))}
        </div>
        <p className="fine">{PATIENCE.find((p) => p.id === server.patience)?.note}. Unfinished sentences and “hold on” always buy extra time.</p>
        <Toggle label="Always listen for the wake word" on={local.mic} onChange={() => setMic(!local.mic)} />
        <MicPicker />
        <span className="setting-label">Wake word</span>
        <div className="segmented" role="radiogroup" aria-label="Wake word sensitivity">
          {WAKE.map((w) => (
            <button key={w.id} role="radio" aria-checked={server.wake === w.id} className={server.wake === w.id ? "active" : ""} onClick={() => setServer({ wake: w.id })}>
              {w.label}
            </button>
          ))}
        </div>
        <p className="fine">{WAKE.find((w) => w.id === server.wake)?.note}.</p>
        <Toggle label="Stop talking when I interrupt" on={server.barge_in} onChange={() => setServer({ barge_in: !server.barge_in })} />
        <Toggle
          label="Keep the conversation going after each reply"
          on={server.conversation === "open"}
          onChange={() => setServer({ conversation: server.conversation === "open" ? "brief" : "open" })}
        />
        <p className="fine">Say “that's all” or “thanks, Jarvis” to end a conversation early.</p>
      </fieldset>

      <fieldset className="setting">
        <legend>Heads-ups</legend>
        <label className="select-row">
          <span>Before meetings</span>
          <select value={server.meeting_alerts} onChange={(e) => setServer({ meeting_alerts: e.target.value as typeof server.meeting_alerts })}>
            <option value="off">Off</option>
            <option value="5">5 minutes</option>
            <option value="10">10 minutes</option>
            <option value="15">15 minutes</option>
          </select>
        </label>
        <label className="select-row">
          <span>Morning briefing</span>
          <select value={server.briefing} onChange={(e) => setServer({ briefing: e.target.value })}>
            <option value="off">Off</option>
            {[...new Set([...BRIEFING_TIMES, server.briefing])].filter((t) => t !== "off").sort().map((t) => (
              <option key={t} value={t}>From {timeOfDay(t)}</option>
            ))}
          </select>
        </label>
        <p className="fine">
          {config && !config.google ? "Meeting alerts need Google connected. " : ""}
          The briefing plays the first time you're at your Mac after that time, before noon: weather, your first meetings and important email.
        </p>
      </fieldset>

      <fieldset className="setting">
        <legend>Theme</legend>
        <div className="swatches">
          {(Object.keys(THEMES) as ThemeId[]).map((id) => (
            <button
              key={id}
              className={"swatch" + (server.theme === id ? " active" : "")}
              onClick={() => setServer({ theme: id })}
              aria-pressed={server.theme === id}
              style={{ ["--sw" as string]: THEMES[id].primary, ["--sw2" as string]: THEMES[id].accent }}
            >
              <i aria-hidden="true" />
              {THEMES[id].name}
            </button>
          ))}
        </div>
        <Toggle label="Interface sounds" on={local.sounds} onChange={toggleSounds} />
      </fieldset>

      {config && (
        <dl className="server-facts">
          <div><dt>Brain</dt><dd>{config.model} via {{ "agent-sdk": "your Claude subscription", nebius: "Nebius Token Factory" }[config.backend] ?? "the Anthropic API"}</dd></div>
          <div><dt>Voice engine</dt><dd>{config.tts}</dd></div>
          <div><dt>Speech to text</dt><dd>{{ mlx: "Whisper large-v3-turbo, on this Mac's GPU", local: "Whisper, on this Mac" }[config.stt] ?? config.stt}</dd></div>
          <div><dt>Wake word</dt><dd>{voice.wake ? `“${voice.wake_word}”, on this Mac` : voice.ready ? "Unavailable" : "Loading"}</dd></div>
          <div><dt>Google</dt><dd>{config.google ? "Connected" : <>Not connected. Run <code>python -m jarvis setup-google</code></>}</dd></div>
          <div><dt>Tools</dt><dd>{config.tools}</dd></div>
        </dl>
      )}
      {voice.error && <p className="empty error-text">{voice.error}</p>}
      <p className="fine">Everything here can also be changed by asking, for example “switch to calm mode” or “give me more time to think”.</p>
    </Drawer>
  );
}

function Toggle({ label, on, onChange }: { label: string; on: boolean; onChange: () => void }) {
  return (
    <label className="toggle">
      <span>{label}</span>
      <input type="checkbox" role="switch" checked={on} onChange={onChange} />
      <i aria-hidden="true" />
    </label>
  );
}

export function useHotkeys(inputRef: React.RefObject<HTMLInputElement>) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest("input, textarea, select, [contenteditable]");
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        const st = useStore.getState();
        if (st.mode !== "boot") st.set({ palette: !st.palette, drawer: null });
        return;
      }
      if (e.key === "Escape") {
        if (useStore.getState().palette) return; // the palette closes itself
        if (useStore.getState().mode === "speaking") interrupt();
        if (typing) (e.target as HTMLElement).blur();
        return;
      }
      if (typing || useStore.getState().mode === "boot") return;
      if (e.code === "Space" && !(e.target as HTMLElement)?.closest("button")) {
        e.preventDefault();
        activate();
      } else if (e.key === "/") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [inputRef]);
}

