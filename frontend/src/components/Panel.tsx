import { useState, type ReactNode } from "react";

/** `fold` makes a panel collapsible; the choice is remembered per panel. */
export function Panel(props: {
  title: string;
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  fold?: "open" | "closed";
}) {
  const key = "jarvis.fold." + props.title;
  const [open, setOpen] = useState(() => {
    try {
      const saved = localStorage.getItem(key);
      if (saved) return saved === "1";
    } catch {
      /* storage blocked: use the default */
    }
    return props.fold !== "closed";
  });
  const toggle = () => {
    setOpen(!open);
    try {
      localStorage.setItem(key, open ? "0" : "1");
    } catch {
      /* not remembered */
    }
  };
  return (
    <section className={"panel " + (props.className ?? "") + (props.fold && !open ? " folded" : "")} aria-label={props.title}>
      <header className="panel-head">
        {props.fold ? (
          <h2>
            <button className="fold-btn" onClick={toggle} aria-expanded={open}>
              {props.title}
              <svg className="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10l5 5 5-5" /></svg>
            </button>
          </h2>
        ) : (
          <h2>{props.title}</h2>
        )}
        {props.meta !== undefined && <span className="panel-meta">{props.meta}</span>}
        {props.actions && <div className="panel-actions">{props.actions}</div>}
      </header>
      {(!props.fold || open) && <div className="panel-body">{props.children}</div>}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

/** Shared loading / error / not-connected states for a panel's data. */
export function PanelStatus({ loading, error, what }: { loading: boolean; error?: string; what: string }) {
  if (loading) return <p className="empty">Loading {what}…</p>;
  if (error === "not_connected")
    return (
      <p className="empty">
        Connect Google to see your {what}: run <code>python -m jarvis setup-google</code>, then reload.
      </p>
    );
  if (error) return <p className="empty error-text">Couldn't load {what}. {error}</p>;
  return null;
}

export type IconName =
  | "close" | "check" | "plus" | "history" | "settings" | "expand" | "mic" | "mic-off" | "send"
  | "command" | "play" | "pause" | "next" | "prev" | "orb" | "full" | "volume" | "external" | "skills" | "search" | "calendar" | "tasks" | "sun";

export function Icon({ name }: { name: IconName }) {
  const paths: Record<string, ReactNode> = {
    close: <path d="M6 6l12 12M18 6L6 18" />,
    check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
    plus: <path d="M12 5v14M5 12h14" />,
    history: <><path d="M4 12a8 8 0 1 0 2.4-5.7" /><path d="M4 4v4h4M12 8v4l3 2" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" /></>,
    expand: <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />,
    mic: <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></>,
    "mic-off": <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M3 3l18 18" /></>,
    send: <path d="M4 12l16-8-6 16-2.5-6.5L4 12z" />,
    command: <path d="M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6z" />,
    play: <path d="M8 5.5v13l10.5-6.5L8 5.5z" />,
    pause: <path d="M8 5v14M16 5v14" />,
    next: <path d="M6 6l9 6-9 6V6zM18 5v14" />,
    prev: <path d="M18 6l-9 6 9 6V6zM6 5v14" />,
    orb: <><circle cx="12" cy="12" r="4" /><circle cx="12" cy="12" r="8.5" strokeDasharray="3 3" /></>,
    full: <><rect x="3.5" y="5" width="17" height="14" rx="2" /><path d="M3.5 9h17" /></>,
    volume: <path d="M4 9.5h3.5L12 6v12l-4.5-3.5H4v-5zM15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" />,
    skills: <><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" /><path d="M18.5 16l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z" /></>,
    search: <><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></>,
    calendar: <><rect x="4" y="5.5" width="16" height="14.5" rx="2" /><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4" /></>,
    tasks: <><rect x="4.5" y="4.5" width="15" height="15" rx="3" /><path d="M8.5 12.5l2.5 2.5 4.5-5" /></>,
    sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8" /></>,
    external: <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />,
  };
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      {paths[name]}
    </svg>
  );
}

/** Jarvis's mark: a small arc reactor. */
export function JarvisMark({ title }: { title?: string }) {
  return (
    <svg className="jarvis-mark" viewBox="0 0 64 64" role={title ? "img" : undefined} aria-hidden={title ? undefined : true} aria-label={title}>
      <circle cx="32" cy="32" r="20" fill="none" stroke="var(--holo)" strokeWidth="2.5" strokeDasharray="22 6" />
      <circle cx="32" cy="32" r="12" fill="none" stroke="var(--holo)" strokeOpacity=".55" strokeWidth="1.5" />
      <circle cx="32" cy="32" r="6" fill="var(--ice)" />
    </svg>
  );
}
