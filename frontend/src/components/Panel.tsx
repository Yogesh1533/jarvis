import type { ReactNode } from "react";

export function Panel(props: {
  title: string;
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={"panel " + (props.className ?? "")} aria-label={props.title}>
      <header className="panel-head">
        <h2>{props.title}</h2>
        {props.meta !== undefined && <span className="panel-meta">{props.meta}</span>}
        {props.actions && <div className="panel-actions">{props.actions}</div>}
      </header>
      <div className="panel-body">{props.children}</div>
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
  | "command" | "play" | "pause" | "next" | "prev" | "orb" | "full" | "volume" | "external";

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
    external: <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />,
  };
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      {paths[name]}
    </svg>
  );
}
