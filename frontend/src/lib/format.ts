import { useStore } from "./store";

export function clock(d: Date) {
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function longDate(d: Date) {
  return d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
}

/** "in 25 min", "now", "2 h ago" */
export function relative(target: Date, now = new Date()) {
  const mins = Math.round((target.getTime() - now.getTime()) / 60000);
  const abs = Math.abs(mins);
  if (abs < 1) return "now";
  const span = abs < 60 ? `${abs} min` : abs < 60 * 36 ? `${Math.round(abs / 60)} h` : `${Math.round(abs / 1440)} d`;
  return mins > 0 ? `in ${span}` : `${span} ago`;
}

export function dayLabel(d: Date, now = new Date()) {
  const a = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const b = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const diff = Math.round((a - b) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  return d.toLocaleDateString([], { weekday: "long" });
}

export function countdown(seconds: number) {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** SQLite "YYYY-MM-DD HH:MM" local time -> Date */
export function parseLocal(s: string) {
  return new Date(s.replace(" ", "T"));
}

const TOOL_LABELS: Record<string, string> = {
  gmail_search: "Searching mail",
  gmail_read: "Reading an email",
  gmail_create_draft: "Drafting an email",
  gmail_send_draft: "Sending email",
  calendar_list_events: "Checking your calendar",
  calendar_create_event: "Adding to your calendar",
  calendar_update_event: "Updating an event",
  calendar_delete_event: "Deleting an event",
  task_add: "Adding a task",
  task_list: "Checking tasks",
  task_complete: "Completing a task",
  task_delete: "Deleting a task",
  reminder_set: "Setting a reminder",
  reminder_list: "Checking reminders",
  reminder_cancel: "Cancelling a reminder",
  web_search: "Searching the web",
  web_read_page: "Reading a web page",
  news_headlines: "Pulling headlines",
  memory_save: "Remembering",
  memory_read: "Recalling",
  memory_delete: "Forgetting",
  weather_get: "Checking the weather",
  timer_set: "Starting a timer",
  timer_list: "Checking timers",
  timer_cancel: "Cancelling a timer",
  briefing_get: "Compiling your briefing",
  system_status: "Running diagnostics",
  mac_open_app: "Opening an app",
  mac_quit_app: "Quitting an app",
  mac_open_url: "Opening a page",
  mac_set_volume: "Adjusting volume",
  mac_media: "Controlling music",
  mac_now_playing: "Checking music",
  mac_notify: "Posting a notification",
  mac_screenshot: "Taking a screenshot",
  mac_clipboard_read: "Reading the clipboard",
  mac_clipboard_write: "Copying to clipboard",
  mac_list_shortcuts: "Listing Shortcuts",
  mac_run_shortcut: "Running a Shortcut",
  mac_run_applescript: "Running a script",
  files_search: "Searching files",
  files_read: "Reading a file",
  files_open: "Opening a file",
};

// When a Tavily key is set, web tools run on Tavily: say so in the trace.
const TAVILY_LABELS: Record<string, string> = {
  web_search: "Searching the web with Tavily",
  news_headlines: "Reading the news with Tavily",
  web_read_page: "Reading a page with Tavily",
  meeting_prep: "Preparing your meeting (calendar, email, Tavily)",
};

export function toolLabel(name: string) {
  if (useStore.getState().config?.tavily && TAVILY_LABELS[name]) return TAVILY_LABELS[name];
  return TOOL_LABELS[name] ?? name.replace(/_/g, " ");
}

export function toolDetail(args: Record<string, unknown>) {
  const v = Object.values(args).find((x) => typeof x === "string" || typeof x === "number");
  return v === undefined ? "" : String(v);
}
