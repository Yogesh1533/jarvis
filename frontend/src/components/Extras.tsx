import { useEffect, useMemo, useRef, useState } from "react";
import { activate, ask, runHudAction, setLayout, setMic, setServer, toggleFullscreen } from "../lib/actions";
import { useStore, type HoloCard } from "../lib/store";
import { THEMES, type ThemeId } from "../lib/themes";
import { Icon } from "./Panel";

// ── Mood switch (top bar) ──────────────────────────────────────────
export function MoodSwitch() {
  const [open, setOpen] = useState(false);
  const mood = useStore((s) => s.server.mood);
  const auto = useStore((s) => s.server.auto_mood);
  const moods = useStore((s) => s.persona.moods);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", close);
    };
  }, [open]);

  const current = moods[mood];
  if (!current) return null;
  return (
    <div className="mood" ref={ref}>
      <button
        className={"mood-btn mood-" + mood}
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-haspopup="menu"
        title="Jarvis's mood and voice"
      >
        <i aria-hidden="true" />
        {current.label}
        {auto && <small>auto</small>}
      </button>
      {open && (
        <div className="mood-menu" role="menu">
          {Object.entries(moods).map(([id, m]) => (
            <button
              key={id}
              role="menuitemradio"
              aria-checked={id === mood}
              className={"mood-item mood-" + id + (id === mood ? " active" : "")}
              onClick={() => {
                setServer({ mood: id, voice: "" });
                setOpen(false);
              }}
            >
              <i aria-hidden="true" />
              <span>
                <b>{m.label}</b>
                <small>{m.blurb}</small>
              </span>
            </button>
          ))}
          <label className="mood-auto">
            <input type="checkbox" checked={auto} onChange={() => setServer({ auto_mood: !auto })} />
            Pick a mood from how I sound
          </label>
        </div>
      )}
    </div>
  );
}

// ── Live transcript while you talk ─────────────────────────────────
const VERDICT_TEXT: Record<string, string> = {
  speaking: "Listening",
  incomplete: "Take your time",
  hold: "Waiting for you",
  complete: "Got it",
  done: "Got it",
};

export function HearingLine() {
  const hearing = useStore((s) => s.hearing);
  const mode = useStore((s) => s.mode);
  if (!hearing || mode === "speaking" || mode === "idle") return null;
  const waiting = hearing.verdict === "incomplete" || hearing.verdict === "hold";
  return (
    <div className={"hearing v-" + hearing.verdict} aria-live="polite">
      {hearing.text && <p className="hearing-text">{hearing.text}</p>}
      <span className="hearing-state">
        <i aria-hidden="true" />
        {VERDICT_TEXT[hearing.verdict]}
      </span>
      {waiting && hearing.wait > 0 && (
        // Drains over the time Jarvis will keep waiting; speaking again resets it.
        <span className="patience" key={hearing.at} style={{ ["--wait" as string]: `${hearing.wait}s` }} aria-hidden="true" />
      )}
    </div>
  );
}

// ── Holographic cards (the hud_show_card tool) ─────────────────────
function openOrAsk(item: { title: string; url?: string | null }) {
  if (item.url) window.open(item.url, "_blank", "noopener");
  else ask(`Tell me more about ${item.title}.`);
}

function Card({ card }: { card: HoloCard }) {
  const drop = useStore((s) => s.dropCard);
  return (
    <article className={"holo holo--" + card.style} aria-label={card.title}>
      <header>
        <div>
          <h3>{card.title}</h3>
          {card.subtitle && <p>{card.subtitle}</p>}
        </div>
        <button className="ghost-x" onClick={() => drop(card.id)} aria-label="Dismiss card">
          <Icon name="close" />
        </button>
      </header>
      {card.style === "stats" ? (
        <dl className="holo-stats">
          {card.items.map((it, i) => (
            <div key={i}>
              <dd>{it.value ?? "–"}</dd>
              <dt>{it.title}</dt>
              {it.detail && <span>{it.detail}</span>}
            </div>
          ))}
        </dl>
      ) : card.style === "text" ? (
        <div className="holo-text">
          {card.items.map((it, i) => (
            <p key={i}>
              {it.title && <b>{it.title} </b>}
              {it.detail}
            </p>
          ))}
        </div>
      ) : (
        <ul className="holo-list">
          {card.items.map((it, i) => (
            <li key={i}>
              <button className="row-btn" onClick={() => openOrAsk(it)} title={it.url ? "Open link" : "Ask Jarvis about this"}>
                <span className="holo-item">
                  <span className="holo-title">{it.title}</span>
                  {it.detail && <span className="holo-detail">{it.detail}</span>}
                </span>
                {it.value && <span className="holo-value">{it.value}</span>}
                {it.url && <Icon name="external" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

export function HoloCards() {
  const cards = useStore((s) => s.cards);
  if (!cards.length) return null;
  return (
    <div className="holo-stack" aria-label="Cards from Jarvis">
      {cards.map((c) => (
        <Card key={c.id} card={c} />
      ))}
    </div>
  );
}

// ── Command palette (⌘K) ───────────────────────────────────────────
interface Command {
  id: string;
  label: string;
  group: string;
  hint?: string;
  run: () => void;
}

function useCommands(): Command[] {
  const server = useStore((s) => s.server);
  const persona = useStore((s) => s.persona);
  const local = useStore((s) => s.local);
  const layout = useStore((s) => s.layout);

  return useMemo(() => {
    const on = (b: boolean) => (b ? "on" : "off");
    const list: Command[] = [
      { id: "talk", group: "Jarvis", label: "Talk to Jarvis", hint: "Space", run: activate },
      { id: "brief", group: "Ask", label: "Brief me on my day", run: () => ask("Good morning. Brief me on my day.") },
      { id: "cal", group: "Ask", label: "What's on my calendar today?", run: () => ask("What's on my calendar today?") },
      { id: "mail", group: "Ask", label: "Anything important in my email?", run: () => ask("Anything important in my unread email?") },
      { id: "news", group: "Ask", label: "Top headlines", run: () => ask("What are today's top headlines? Show them as a card.") },
      { id: "weather", group: "Ask", label: "Weather this week", run: () => ask("What's the weather this week? Show it as a card.") },
      { id: "sys", group: "Ask", label: "How is my Mac doing?", run: () => ask("How is my Mac doing?") },
    ];
    Object.entries(persona.moods).forEach(([id, m]) =>
      list.push({ id: "mood-" + id, group: "Mood", label: `${m.label} mood`, hint: id === server.mood ? "current" : m.blurb, run: () => setServer({ mood: id, voice: "" }) }),
    );
    Object.entries(persona.voices).forEach(([id, label]) =>
      list.push({ id: "voice-" + id, group: "Voice", label: `Voice: ${label}`, hint: id === persona.voice ? "speaking now" : undefined, run: () => setServer({ voice: id }) }),
    );
    (["snappy", "balanced", "patient"] as const).forEach((p) =>
      list.push({ id: "pat-" + p, group: "Listening", label: `Patience: ${p[0].toUpperCase() + p.slice(1)}`, hint: p === server.patience ? "current" : undefined, run: () => setServer({ patience: p }) }),
    );
    (["low", "normal", "high"] as const).forEach((w) =>
      list.push({ id: "wake-" + w, group: "Listening", label: `Wake word sensitivity: ${w[0].toUpperCase() + w.slice(1)}`, hint: w === server.wake ? "current" : undefined, run: () => setServer({ wake: w }) }),
    );
    list.push({
      id: "conv", group: "Listening",
      label: server.conversation === "open" ? "Short conversations (stop listening sooner)" : "Longer conversations (keep listening after replies)",
      hint: `now ${server.conversation}`,
      run: () => setServer({ conversation: server.conversation === "open" ? "brief" : "open" }),
    });
    (["off", "5", "10", "15"] as const).forEach((m) =>
      list.push({ id: "meet-" + m, group: "Heads-ups", label: m === "off" ? "Meeting alerts: Off" : `Meeting alerts: ${m} minutes before`, hint: m === server.meeting_alerts ? "current" : undefined, run: () => setServer({ meeting_alerts: m }) }),
    );
    list.push({
      id: "briefing", group: "Heads-ups",
      label: server.briefing === "off" ? "Turn on the morning briefing" : "Turn off the morning briefing",
      hint: server.briefing === "off" ? undefined : `from ${server.briefing}`,
      run: () => setServer({ briefing: server.briefing === "off" ? "07:00" : "off" }),
    });
    (Object.keys(THEMES) as ThemeId[]).forEach((t) =>
      list.push({ id: "theme-" + t, group: "Theme", label: `Theme: ${THEMES[t].name}`, hint: t === server.theme ? "current" : undefined, run: () => setServer({ theme: t }) }),
    );
    list.push(
      { id: "mic", group: "Settings", label: `Microphone ${local.mic ? "off" : "on"}`, hint: `now ${on(local.mic)}`, run: () => setMic(!local.mic) },
      { id: "barge", group: "Settings", label: "Interrupt by talking", hint: on(server.barge_in), run: () => setServer({ barge_in: !server.barge_in }) },
      { id: "fill", group: "Settings", label: "“One moment” fillers", hint: on(server.fillers), run: () => setServer({ fillers: !server.fillers }) },
      { id: "speak", group: "Settings", label: "Speak typed replies", hint: on(server.speak), run: () => setServer({ speak: !server.speak }) },
      { id: "auto", group: "Settings", label: "Pick mood automatically", hint: on(server.auto_mood), run: () => setServer({ auto_mood: !server.auto_mood }) },
      { id: "hist", group: "Window", label: "Conversation history", run: () => runHudAction("open_history") },
      { id: "set", group: "Window", label: "Settings", run: () => runHudAction("open_settings") },
      { id: "cards", group: "Window", label: "Clear cards", run: () => runHudAction("clear_cards") },
      { id: "layout", group: "Window", label: layout === "orb" ? "Full interface" : "Orb mode", hint: "⌘⇧J in the app", run: () => setLayout(layout === "orb" ? "full" : "orb") },
      { id: "fs", group: "Window", label: "Full screen", run: toggleFullscreen },
    );
    return list;
  }, [server, persona, local, layout]);
}

export function CommandPalette() {
  const commands = useCommands();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);
  const close = () => useStore.getState().set({ palette: false });

  const results = useMemo(() => {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    const hits = terms.length
      ? commands.filter((c) => terms.every((t) => (c.label + " " + c.group).toLowerCase().includes(t)))
      : commands;
    if (!q.trim()) return hits;
    const askIt: Command = { id: "ask", group: "Ask", label: `Ask Jarvis: “${q.trim()}”`, hint: "Enter", run: () => ask(q.trim()) };
    return hits.length ? [...hits, askIt] : [askIt];
  }, [q, commands]);

  useEffect(() => setSel(0), [q]);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-i="${sel}"]`)?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  const run = (c: Command | undefined) => {
    if (!c) return;
    close();
    c.run();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(results.length - 1, s + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(0, s - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      run(results[sel]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  };

  let lastGroup = "";
  return (
    <div className="palette-scrim" onPointerDown={(e) => e.target === e.currentTarget && close()}>
      <div className="palette" role="dialog" aria-label="Commands">
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey}
          placeholder="Type a command, or anything to ask Jarvis"
          aria-label="Search commands"
          aria-controls="palette-list"
          aria-activedescendant={results[sel] ? "pc-" + results[sel].id : undefined}
          role="combobox"
          aria-expanded="true"
        />
        <ul id="palette-list" role="listbox" ref={listRef}>
          {results.map((c, i) => {
            const head = c.group !== lastGroup;
            lastGroup = c.group;
            return (
              <li key={c.id} role="presentation">
                {head && <span className="pc-group">{c.group}</span>}
                <button
                  id={"pc-" + c.id}
                  role="option"
                  aria-selected={i === sel}
                  data-i={i}
                  className={i === sel ? "sel" : ""}
                  onPointerMove={() => setSel(i)}
                  onClick={() => run(c)}
                >
                  <span>{c.label}</span>
                  {c.hint && <small>{c.hint}</small>}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

// ── Orb mode controls ──────────────────────────────────────────────
export function OrbBar({ onExpand }: { onExpand: () => void }) {
  const mic = useStore((s) => s.local.mic);
  const mood = useStore((s) => s.persona.moods[s.server.mood]?.label);
  return (
    <div className="orb-bar">
      <button className={"icon-btn" + (mic ? "" : " off")} onClick={() => setMic(!mic)} aria-label={mic ? "Turn microphone off" : "Turn microphone on"} title={mic ? "Mic on" : "Mic off"}>
        <Icon name={mic ? "mic" : "mic-off"} />
      </button>
      {mood && <span className="orb-mood">{mood}</span>}
      <button className="icon-btn" onClick={onExpand} aria-label="Open the full interface" title="Full interface (⌘⇧J)">
        <Icon name="full" />
      </button>
    </div>
  );
}
