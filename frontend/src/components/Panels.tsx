import { useEffect, useState } from "react";
import { api, usePanelData } from "../lib/api";
import { ask } from "../lib/actions";
import { countdown, dayLabel, parseLocal, relative } from "../lib/format";
import { useStore, type NowPlaying } from "../lib/store";
import { Empty, Icon, Panel, PanelStatus } from "./Panel";

function useNow(ms = 1000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

// ── Agenda ─────────────────────────────────────────────────────────
interface CalEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  location?: string;
  attendees: number;
}

export function AgendaPanel() {
  const res = usePanelData<CalEvent[]>("/api/agenda?days=2", "agenda", 5 * 60_000);
  const now = useNow(30_000);
  const events = (res.data ?? []).filter((e) => new Date(e.end) > now);
  let lastDay = "";
  return (
    <Panel title="Agenda" meta={res.data ? `${events.length} upcoming` : undefined}>
      <PanelStatus loading={res.loading} error={res.error} what="calendar" />
      {res.data && events.length === 0 && <Empty>Nothing scheduled for the next two days.</Empty>}
      <ol className="agenda">
        {events.map((e) => {
          const start = new Date(e.start);
          const day = dayLabel(start, now);
          const showDay = day !== lastDay;
          lastDay = day;
          const live = start <= now && new Date(e.end) > now;
          return (
            <li key={e.id} className={live ? "live" : ""}>
              {showDay && <span className="agenda-day">{day}</span>}
              <button className="row-btn" onClick={() => ask(`Tell me about my "${e.title}" event.`)}>
                <span className="agenda-time">
                  {e.all_day ? "All day" : start.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}
                </span>
                <span className="agenda-title">{e.title}</span>
                <span className="agenda-rel">{live ? "Happening now" : e.all_day ? "" : relative(start, now)}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}

// ── Tasks ──────────────────────────────────────────────────────────
interface Task {
  id: number;
  title: string;
  due: string | null;
  notes: string | null;
}

export function TasksPanel() {
  const res = usePanelData<Task[]>("/api/tasks", "tasks");
  const [draft, setDraft] = useState("");
  const tasks = res.data ?? [];

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    const title = draft.trim();
    if (!title) return;
    setDraft("");
    await api("/api/tasks", { method: "POST", body: JSON.stringify({ title }) });
    res.reload();
  };
  const complete = async (id: number) => {
    await api(`/api/tasks/${id}/complete`, { method: "POST" });
    res.reload();
  };
  const remove = async (t: Task) => {
    if (!window.confirm(`Delete the task "${t.title}"?`)) return;
    await api(`/api/tasks/${t.id}`, { method: "DELETE" });
    res.reload();
  };

  return (
    <Panel title="Tasks" meta={res.data ? `${tasks.length} open` : undefined}>
      <PanelStatus loading={res.loading} error={res.error} what="tasks" />
      {res.data && tasks.length === 0 && <Empty>No open tasks. Add one below or just ask.</Empty>}
      <ul className="tasks">
        {tasks.map((t) => (
          <li key={t.id}>
            <button className="check" aria-label={`Complete ${t.title}`} onClick={() => complete(t.id)}>
              <Icon name="check" />
            </button>
            <span className="task-title">
              {t.title}
              {t.due && <span className="task-due">{relative(parseLocal(t.due))}</span>}
            </span>
            <button className="ghost-x" aria-label={`Delete ${t.title}`} onClick={() => remove(t)}>
              <Icon name="close" />
            </button>
          </li>
        ))}
      </ul>
      <form className="inline-add" onSubmit={add}>
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Add a task" aria-label="New task" />
        <button type="submit" aria-label="Add task" disabled={!draft.trim()}>
          <Icon name="plus" />
        </button>
      </form>
    </Panel>
  );
}

// ── Timers & reminders ─────────────────────────────────────────────
interface Timer {
  id: number;
  label: string;
  seconds: number;
  ends_at: number;
}
interface Reminder {
  id: number;
  message: string;
  due_at: string;
}

export function TimersPanel() {
  const timers = usePanelData<Timer[]>("/api/timers", "timers", 15_000);
  const rems = usePanelData<Reminder[]>("/api/reminders", "reminders", 60_000);
  const now = useNow(250);
  const nowS = now.getTime() / 1000;
  const live = (timers.data ?? []).filter((t) => t.ends_at > nowS - 1);
  const reminders = rems.data ?? [];

  const cancelTimer = async (id: number) => {
    await api(`/api/timers/${id}`, { method: "DELETE" });
    timers.reload();
  };
  const cancelReminder = async (r: Reminder) => {
    if (!window.confirm(`Cancel the reminder "${r.message}"?`)) return;
    await api(`/api/reminders/${r.id}`, { method: "DELETE" });
    rems.reload();
  };

  return (
    <Panel title="Timers and reminders" meta={live.length + reminders.length || undefined}>
      {live.length === 0 && reminders.length === 0 && !rems.loading && (
        <Empty>Nothing pending. Try “set a ten minute timer for tea”.</Empty>
      )}
      {live.length > 0 && (
        <ul className="timers">
          {live.map((t) => {
            const left = Math.max(0, t.ends_at - nowS);
            const frac = t.seconds ? left / t.seconds : 0;
            const C = 2 * Math.PI * 17;
            return (
              <li key={t.id}>
                <svg viewBox="0 0 40 40" className="timer-ring" aria-hidden="true">
                  <circle cx="20" cy="20" r="17" className="track" />
                  <circle cx="20" cy="20" r="17" className="fill" strokeDasharray={C} strokeDashoffset={C * (1 - frac)} />
                </svg>
                <span className="timer-left">{countdown(left)}</span>
                <span className="timer-label">{t.label}</span>
                <button className="ghost-x" aria-label={`Cancel ${t.label}`} onClick={() => cancelTimer(t.id)}>
                  <Icon name="close" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {reminders.length > 0 && (
        <ul className="reminders">
          {reminders.map((r) => {
            const due = parseLocal(r.due_at);
            return (
              <li key={r.id}>
                <span className="rem-when">
                  {dayLabel(due, now)} {due.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}
                </span>
                <span className="rem-msg">{r.message}</span>
                <button className="ghost-x" aria-label={`Cancel reminder ${r.message}`} onClick={() => cancelReminder(r)}>
                  <Icon name="close" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

// ── Mail ───────────────────────────────────────────────────────────
interface Mail {
  count: number;
  items: { id: string; from: string; subject: string; snippet: string }[];
}

export function MailPanel() {
  const res = usePanelData<Mail>("/api/mail", "mail", 3 * 60_000);
  const items = res.data?.items ?? [];
  return (
    <Panel title="Inbox" meta={res.data ? `${res.data.count} unread` : undefined}>
      <PanelStatus loading={res.loading} error={res.error} what="inbox" />
      {res.data && items.length === 0 && <Empty>Inbox zero. Nothing unread.</Empty>}
      <ul className="mail">
        {items.map((m) => (
          <li key={m.id}>
            <button
              className="row-btn"
              title="Ask Jarvis to summarize this email"
              onClick={() => ask(`Summarize the email from ${m.from} with the subject "${m.subject}".`)}
            >
              <span className="mail-from">{m.from}</span>
              <span className="mail-subject">{m.subject}</span>
            </button>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// ── Media ──────────────────────────────────────────────────────────
interface Media {
  now: NowPlaying | null;
  volume: number | null;
  live?: boolean; // updates arrive over the socket as they happen
  seek?: boolean; // the player can seek and skip 15 s
}

function mmss(s: number) {
  const t = Math.max(0, Math.floor(s));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}

/** Where the track is up to, ticking along while it plays. */
function usePosition(now: NowPlaying | null) {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!now?.playing) return;
    const id = setInterval(() => tick((n) => n + 1), 500);
    return () => clearInterval(id);
  }, [now?.playing, now?.title]);
  if (!now || now.elapsed == null) return null;
  let at = now.elapsed;
  if (now.playing && now.at) at += (Date.now() / 1000 - now.at) * (now.rate || 1);
  return now.duration ? Math.min(at, now.duration) : at;
}

function Progress({ now, canSeek, onSeek }: { now: NowPlaying; canSeek: boolean; onSeek: (s: number) => void }) {
  const pos = usePosition(now);
  const [drag, setDrag] = useState<number | null>(null);
  if (pos === null || !now.duration) return null;
  const shown = drag ?? pos;
  const pct = `${(100 * shown) / now.duration}%`;
  const commit = (v: number) => {
    setDrag(null);
    onSeek(v);
  };
  return (
    <div className="progress">
      <span>{mmss(shown)}</span>
      <input
        type="range" min={0} max={Math.round(now.duration)} step={1} value={Math.round(shown)}
        disabled={!canSeek}
        aria-label="Position in track"
        style={{ ["--v" as string]: pct }}
        onChange={(e) => setDrag(Number(e.target.value))}
        onPointerUp={(e) => commit(Number((e.target as HTMLInputElement).value))}
        onKeyUp={(e) => commit(Number((e.target as HTMLInputElement).value))}
      />
      <span>{mmss(now.duration)}</span>
    </div>
  );
}

export function MediaPanel() {
  const res = usePanelData<Media>("/api/media", "media", 8000);
  const live = useStore((s) => s.media);
  const [vol, setVol] = useState<number | null>(null);
  // Live updates win once they've arrived; polling still covers volume.
  const now = live !== undefined && res.data?.live ? live : res.data?.now ?? null;
  const volume = vol ?? res.data?.volume ?? null;
  const canSeek = !!res.data?.seek;

  const control = async (action: string, position?: number) => {
    await api("/api/media", { method: "POST", body: JSON.stringify({ action, position }) });
    if (!res.data?.live) setTimeout(res.reload, 400);
  };
  const seek = (position: number) => {
    if (now) useStore.getState().set({ media: { ...now, elapsed: position, at: Date.now() / 1000 } });
    control("seek", position);
  };
  const commitVolume = async (level: number) => {
    await api("/api/volume", { method: "POST", body: JSON.stringify({ level }) });
    setVol(null);
    res.reload();
  };

  return (
    <Panel title="Now playing" meta={now?.app} className="media-panel">
      {res.loading && !res.data && <Empty>Checking what's playing…</Empty>}
      {res.data && !now && <Empty>Nothing playing. Start something in YouTube Music, or ask me to.</Empty>}
      {now && (
        <div className="track">
          {now.art ? (
            <img className="track-art" src={now.art} alt="" />
          ) : (
            <span className={"eq" + (now.playing ? " on" : "")} aria-hidden="true"><i /><i /><i /><i /></span>
          )}
          <div className="track-text">
            <span className="track-title" title={now.title}>{now.title}</span>
            <span className="track-artist">{[now.artist, now.album].filter(Boolean).join(" — ")}</span>
          </div>
        </div>
      )}
      {now && <Progress now={now} canSeek={canSeek} onSeek={seek} />}
      <div className="media-ctl">
        {canSeek && (
          <button className="icon-btn skip" onClick={() => control("back")} aria-label="Back 15 seconds" title="Back 15 seconds">−15</button>
        )}
        <button className="icon-btn" onClick={() => control("previous")} aria-label="Previous track" title="Previous"><Icon name="prev" /></button>
        <button className="icon-btn big" onClick={() => control("playpause")} aria-label={now?.playing ? "Pause" : "Play"} title={now?.playing ? "Pause" : "Play"}>
          <Icon name={now?.playing ? "pause" : "play"} />
        </button>
        <button className="icon-btn" onClick={() => control("next")} aria-label="Next track" title="Next"><Icon name="next" /></button>
        {canSeek && (
          <button className="icon-btn skip" onClick={() => control("forward")} aria-label="Forward 15 seconds" title="Forward 15 seconds">+15</button>
        )}
        {volume !== null && (
          <label className="vol" title={`Volume ${volume}%`}>
            <Icon name="volume" />
            <input
              type="range" min={0} max={100} step={1} value={volume}
              aria-label="Mac volume"
              style={{ ["--v" as string]: `${volume}%` }}
              onChange={(e) => setVol(Number(e.target.value))}
              onPointerUp={(e) => commitVolume(Number((e.target as HTMLInputElement).value))}
              onKeyUp={(e) => commitVolume(Number((e.target as HTMLInputElement).value))}
            />
          </label>
        )}
      </div>
    </Panel>
  );
}

// ── System ─────────────────────────────────────────────────────────
interface Sys {
  cpu: number;
  memory: number;
  disk: number;
  battery: number | null;
  charging: boolean | null;
  net_up_kbs: number;
  net_down_kbs: number;
  volume: number | null;
  uptime_hours: number;
  host: string;
}

function Gauge({ label, value, note }: { label: string; value: number; note?: string }) {
  // 270° arc gauge
  const r = 26;
  const C = 2 * Math.PI * r;
  const arc = C * 0.75;
  const v = Math.max(0, Math.min(100, value));
  const hot = v >= 85;
  return (
    <figure className={"gauge" + (hot ? " hot" : "")}>
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <circle cx="32" cy="32" r={r} className="track" strokeDasharray={`${arc} ${C}`} transform="rotate(135 32 32)" />
        <circle cx="32" cy="32" r={r} className="fill" strokeDasharray={`${(arc * v) / 100} ${C}`} transform="rotate(135 32 32)" />
      </svg>
      <span className="gauge-val">{Math.round(v)}<small>%</small></span>
      <figcaption>{label}{note ? <span> {note}</span> : null}</figcaption>
    </figure>
  );
}

function rate(kbs: number) {
  return kbs >= 1024 ? `${(kbs / 1024).toFixed(1)} MB/s` : `${Math.round(kbs)} KB/s`;
}

export function SystemPanel() {
  const res = usePanelData<Sys>("/api/system", "system", 3000);
  const d = res.data;
  return (
    <Panel title="Diagnostics" meta={d?.host}>
      <PanelStatus loading={res.loading && !d} error={d ? undefined : res.error} what="system status" />
      {d && (
        <>
          <div className="gauges">
            <Gauge label="CPU" value={d.cpu} />
            <Gauge label="Memory" value={d.memory} />
            {d.battery !== null ? (
              <Gauge label="Battery" value={d.battery} note={d.charging ? "charging" : undefined} />
            ) : (
              <Gauge label="Disk" value={d.disk} />
            )}
          </div>
          <dl className="sys-facts">
            <div><dt>Network</dt><dd>↓ {rate(d.net_down_kbs)} ↑ {rate(d.net_up_kbs)}</dd></div>
            {d.volume !== null && <div><dt>Volume</dt><dd>{d.volume}%</dd></div>}
            <div><dt>Uptime</dt><dd>{d.uptime_hours < 48 ? `${d.uptime_hours} h` : `${Math.round(d.uptime_hours / 24)} days`}</dd></div>
          </dl>
        </>
      )}
    </Panel>
  );
}

// ── Memory ─────────────────────────────────────────────────────────
interface Memory {
  name: string;
  summary: string;
  content: string;
}

export function MemoryPanel() {
  const res = usePanelData<Memory[]>("/api/memories", "memory");
  const [open, setOpen] = useState<string | null>(null);
  const [edit, setEdit] = useState<{ summary: string; content: string } | null>(null);
  const items = res.data ?? [];

  const save = async (name: string) => {
    if (!edit) return;
    await api(`/api/memories/${name}`, { method: "PUT", body: JSON.stringify(edit) });
    setEdit(null);
    res.reload();
  };
  const remove = async (m: Memory) => {
    if (!window.confirm(`Make Jarvis forget "${m.summary}"?`)) return;
    await api(`/api/memories/${m.name}`, { method: "DELETE" });
    setOpen(null);
    res.reload();
  };

  return (
    <Panel title="What Jarvis knows" meta={res.data ? items.length : undefined}>
      <PanelStatus loading={res.loading} error={res.error} what="memories" />
      {res.data && items.length === 0 && (
        <Empty>Nothing yet. Tell Jarvis something worth keeping, like “remember my sister’s birthday is March 3rd”.</Empty>
      )}
      <ul className="memories">
        {items.map((m) => (
          <li key={m.name} className={open === m.name ? "open" : ""}>
            <button
              className="row-btn"
              aria-expanded={open === m.name}
              onClick={() => {
                setOpen(open === m.name ? null : m.name);
                setEdit(null);
              }}
            >
              {m.summary}
            </button>
            {open === m.name &&
              (edit ? (
                <div className="mem-edit">
                  <input value={edit.summary} onChange={(e) => setEdit({ ...edit, summary: e.target.value })} aria-label="Summary" />
                  <textarea rows={3} value={edit.content} onChange={(e) => setEdit({ ...edit, content: e.target.value })} aria-label="Details" />
                  <div className="mem-actions">
                    <button className="text-btn" onClick={() => save(m.name)}>Save</button>
                    <button className="text-btn quiet" onClick={() => setEdit(null)}>Cancel</button>
                  </div>
                </div>
              ) : (
                <div className="mem-detail">
                  <p>{m.content}</p>
                  <div className="mem-actions">
                    <button className="text-btn" onClick={() => setEdit({ summary: m.summary, content: m.content })}>Edit</button>
                    <button className="text-btn danger" onClick={() => remove(m)}>Forget</button>
                  </div>
                </div>
              ))}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// ── Weather (top bar) ──────────────────────────────────────────────
interface Weather {
  place: string;
  temp: number;
  condition: string;
  days: { high: number; low: number; rain_chance: number | null }[];
}

export function WeatherReadout() {
  const res = usePanelData<Weather>("/api/weather", "system", 0);
  const [data, setData] = useState<Weather | null>(null);
  useEffect(() => {
    if (res.data) setData(res.data);
  }, [res.data]);
  useEffect(() => {
    const id = setInterval(() => useStore.getState().bump("system"), 15 * 60_000);
    return () => clearInterval(id);
  }, []);
  if (!data) return null;
  const today = data.days[0];
  return (
    <button className="weather" onClick={() => ask("What's the weather looking like?")} title="Ask about the weather">
      <span className="weather-temp">{data.temp}°</span>
      <span className="weather-text">
        <span>{data.condition}</span>
        <span className="weather-sub">
          {data.place.split(",")[0]}
          {today ? `, ${today.low}° to ${today.high}°` : ""}
        </span>
      </span>
    </button>
  );
}
