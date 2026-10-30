import { useEffect, useMemo, useState } from "react";
import { ask, runHudAction, setServer } from "../lib/actions";
import { usePanelData } from "../lib/api";
import { relative } from "../lib/format";
import { useStore } from "../lib/store";
import { Drawer } from "./Chrome";
import { Icon, type IconName } from "./Panel";

/** True when nothing else wants the middle of the screen: no reply, card or question. */
export function useIsHome() {
  const mode = useStore((s) => s.mode);
  const caption = useStore((s) => s.caption);
  const cards = useStore((s) => s.cards.length);
  const confirm = useStore((s) => s.confirm);
  return mode === "idle" && !caption && cards === 0 && !confirm;
}

function useNow(ms = 30_000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

// ── Model switch ───────────────────────────────────────────────────
const RANK: Record<string, number> = { Lightning: 0, Super: 1, Ultra: 2 };

/** "Nemotron 3 Ultra 550B" -> "Ultra"; "Sonnet 5.5 · balanced" -> "Sonnet 5.5". */
function shortLabel(label: string) {
  const hit = label.match(/Lightning|Super|Ultra|Nano/);
  return hit ? hit[0] : label.split(" · ")[0];
}

export function ModelSwitch() {
  const model = useStore((s) => s.server.model);
  const models = useStore((s) => s.persona.models);
  const backend = useStore((s) => s.config?.backend);
  const last = useStore((s) => s.brain[s.brain.length - 1]);
  const options = useMemo(() => {
    const list = Object.entries(models)
      .map(([id, label]) => ({ id, label, short: shortLabel(label) }))
      .sort((a, b) => (RANK[a.short] ?? 9) - (RANK[b.short] ?? 9));
    return [{ id: "", label: backend === "nebius" ? "Automatic: picks a model per request" : "Default model", short: "Auto" }, ...list];
  }, [models, backend]);
  if (Object.keys(models).length < 2) return null;
  const answered = backend === "nebius" && !model && last ? shortLabel(models[last.model] ?? last.model) : "";
  return (
    <div className="model-switch" role="radiogroup" aria-label="Model">
      {options.map((o) => {
        const on = model === o.id;
        return (
          <button
            key={o.id}
            role="radio"
            aria-checked={on}
            className={on ? "on" : ""}
            title={o.label}
            onClick={() => setServer({ model: o.id })}
          >
            {o.short}
            {on && o.id === "" && answered && <small>{answered}</small>}
          </button>
        );
      })}
    </div>
  );
}

// ── Greeting and the day at a glance ───────────────────────────────
interface CalEvent { id: string; title: string; start: string; end: string; all_day: boolean; attendees: number }
interface Task { id: number; title: string; due: string | null }
interface Weather { temp: number; condition: string; days: { high: number; low: number }[] }

function greeting(d: Date) {
  const h = d.getHours();
  return h < 5 ? "Still up" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export function HomeBrief() {
  const now = useNow();
  const name = useStore((s) => s.config?.name);
  const agenda = usePanelData<CalEvent[]>("/api/agenda?days=2", "agenda", 5 * 60_000);
  const tasks = usePanelData<Task[]>("/api/tasks", "tasks");
  const weather = usePanelData<Weather>("/api/weather", "system");

  const upcoming = (agenda.data ?? []).filter((e) => !e.all_day && new Date(e.end) > now);
  const next = upcoming.find((e) => e.attendees > 0) ?? upcoming[0]; // a meeting beats "Wake Up"
  const open = tasks.data?.length;
  const w = weather.data;

  const bits: { icon: IconName; text: string; ask: string }[] = [];
  if (next) {
    const start = new Date(next.start);
    const live = start <= now;
    bits.push({
      icon: "calendar",
      text: live ? `${next.title}, happening now` : `${next.title}, ${relative(start, now)}`,
      ask: `Prep me for "${next.title}".`,
    });
  } else if (agenda.data) {
    bits.push({ icon: "calendar", text: "Nothing else on your calendar", ask: "What's on my calendar this week?" });
  }
  if (open !== undefined) {
    bits.push({
      icon: "tasks",
      text: open === 0 ? "No open tasks" : `${open} open task${open === 1 ? "" : "s"}`,
      ask: "What's on my task list?",
    });
  }
  if (w) bits.push({ icon: "sun", text: `${w.temp}° ${w.condition.toLowerCase()}`, ask: "What's the weather looking like?" });

  return (
    <section className="home-brief" aria-label="Today at a glance">
      <p className="home-kicker" lang="ne">नमस्ते</p>
      <h1>
        {greeting(now)}
        {name ? `, ${name}` : ""}
      </h1>
      {bits.length > 0 && (
        <ul>
          {bits.map((b) => (
            <li key={b.icon}>
              <button onClick={() => ask(b.ask)}>
                <Icon name={b.icon} />
                {b.text}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── Quick actions ──────────────────────────────────────────────────
const CHIPS = [
  { label: "Prep my next meeting", text: "Prep me for my next meeting." },
  { label: "Plan my day", text: "Plan my day around my calendar and tasks." },
  { label: "Brief me", text: "Good morning. Brief me on my day." },
  { label: "Unread mail", text: "Anything important in my unread email?" },
  { label: "Headlines", text: "What are today's top headlines?" },
];

export function QuickActions() {
  return (
    <div className="quick" role="group" aria-label="Quick requests">
      {CHIPS.map((c) => (
        <button key={c.label} className="chip" onClick={() => ask(c.text)}>
          {c.label}
        </button>
      ))}
    </div>
  );
}

// ── Skills ─────────────────────────────────────────────────────────
export interface Skill {
  name: string;
  description: string;
  starter: boolean;
  created: string;
  body: string;
}

const pretty = (slug: string) => {
  const s = slug.replace(/-/g, " ");
  return s[0].toUpperCase() + s.slice(1);
};

const runSkill = (s: Skill) => ask(`Run my ${s.name.replace(/-/g, " ")} skill.`);

export function SkillsShelf() {
  const res = usePanelData<Skill[]>("/api/skills", "skills");
  const skills = res.data ?? [];
  if (!skills.length) return null;
  const shown = skills.slice(0, 3);
  return (
    <section className="shelf" aria-label="Your skills">
      <ul>
        {shown.map((s) => (
          <li key={s.name}>
            <button className="skill-card" onClick={() => runSkill(s)} title={`Run: ${s.description}`}>
              <span className="skill-text">
                <span className="skill-name">{pretty(s.name)}</span>
                <span className="skill-desc">{s.description}</span>
              </span>
              <span className="skill-run" aria-hidden="true"><Icon name="play" /></span>
            </button>
          </li>
        ))}
        <li>
          <button className="skill-card more" onClick={() => runHudAction("open_skills")}>
            <span className="skill-text">
              <span className="skill-name">All skills</span>
              <span className="skill-desc">{skills.length} saved · teach a new one</span>
            </span>
          </button>
        </li>
      </ul>
    </section>
  );
}

export function SkillsDrawer() {
  const res = usePanelData<Skill[]>("/api/skills", "skills");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const skills = (res.data ?? []).filter((s) => (s.name + " " + s.description).toLowerCase().includes(q.toLowerCase()));
  const close = () => useStore.getState().set({ drawer: null });
  return (
    <Drawer title="Skills">
      <p className="skills-lede">
        A skill is a routine Jarvis can repeat. Do something once, then say <q>save that as my weekly report skill</q>.
        Jarvis sees each skill's name and description, and opens the steps only when it runs one.
      </p>
      <div className="skills-tools">
        <label className="skills-search">
          <Icon name="search" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search skills" aria-label="Search skills" />
        </label>
        <button
          className="chip"
          onClick={() => {
            close();
            ask("Save what we just did as a skill. Pick a short name and description.");
          }}
        >
          Save my last request
        </button>
      </div>
      {res.data && skills.length === 0 && <p className="empty">{q ? "No skill matches." : "No skills yet."}</p>}
      <ul className="skill-list">
        {skills.map((s) => (
          <li key={s.name} className={open === s.name ? "open" : ""}>
            <div className="skill-row">
              <button
                className="skill-toggle"
                aria-expanded={open === s.name}
                onClick={() => setOpen(open === s.name ? null : s.name)}
              >
                <span className="skill-name">{pretty(s.name)}</span>
                <span className={"badge" + (s.starter ? "" : " mine")}>{s.starter ? "Starter" : "Yours"}</span>
                <span className="skill-desc">{s.description}</span>
              </button>
              <button
                className="run-btn"
                aria-label={`Run ${pretty(s.name)}`}
                onClick={() => {
                  close();
                  runSkill(s);
                }}
              >
                <Icon name="play" />
                Run
              </button>
            </div>
            {open === s.name && <pre className="skill-body">{s.body}</pre>}
          </li>
        ))}
      </ul>
    </Drawer>
  );
}
