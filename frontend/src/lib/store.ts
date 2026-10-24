import { create } from "zustand";
import { desktop } from "./desktop";
import type { ThemeId } from "./themes";

export type Mode = "boot" | "idle" | "listening" | "thinking" | "speaking" | "confirm";
export type Panel = "agenda" | "mail" | "tasks" | "reminders" | "timers" | "memory" | "system" | "media";
export type Layout = "full" | "orb";

export interface LogEntry {
  id: number;
  role: "user" | "jarvis" | "note";
  text: string;
  at: number;
  error?: boolean;
}

export interface ToolEvent {
  id: number;
  name: string;
  args: Record<string, unknown>;
  phase: "start" | "end";
  ok: boolean;
  at: number;
}

export interface Toast {
  id: number;
  kind: "reminder" | "timer" | "notice" | "error";
  text: string;
}

export interface VoiceStatus {
  ready: boolean;
  wake: boolean;
  mic: boolean;
  error: string | null;
  wake_word: string;
}

export interface ServerConfig {
  backend: string;
  model: string;
  tts: string;
  stt: string;
  google: boolean;
  tools: number;
}

/** Settings that live on the server, so voice commands and every window agree. */
export interface ServerSettings {
  theme: ThemeId;
  mood: string;
  voice: string;
  patience: "snappy" | "balanced" | "patient";
  barge_in: boolean;
  wake: "low" | "normal" | "high";
  conversation: "brief" | "open";
  fillers: boolean;
  speak: boolean;
  auto_mood: boolean;
}

export interface Persona {
  moods: Record<string, { label: string; blurb: string }>;
  voices: Record<string, string>;
  voice: string; // the voice actually in use
}

/** What's playing on the Mac (any app: YouTube Music, Spotify...). */
export interface NowPlaying {
  app: string | null;
  title: string;
  artist: string;
  album?: string;
  playing: boolean;
  rate?: number;
  duration?: number | null; // seconds
  elapsed?: number | null;  // seconds, as of `at`
  at?: number;              // epoch seconds
  art?: string | null;      // URL of the artwork
}

/** What Jarvis is hearing right now, while you talk. */
export interface Hearing {
  text: string;
  verdict: "speaking" | "incomplete" | "hold" | "complete" | "done";
  wait: number; // seconds of silence that will end your turn
  at: number;
}

export interface CardItem {
  title: string;
  detail?: string | null;
  value?: string | null;
  url?: string | null;
}

export interface HoloCard {
  id: number;
  title: string;
  subtitle?: string | null;
  style: "list" | "stats" | "text";
  items: CardItem[];
}

/** Settings that only concern this window. */
export interface LocalSettings {
  sounds: boolean;
  mic: boolean;
  micDevice: string; // "" = the system default
}

const LOCAL_KEY = "jarvis.local";
const LOCAL_DEFAULTS: LocalSettings = { sounds: true, mic: true, micDevice: "" };

function loadLocal(): LocalSettings {
  try {
    return { ...LOCAL_DEFAULTS, ...JSON.parse(localStorage.getItem(LOCAL_KEY) || "{}") };
  } catch {
    return LOCAL_DEFAULTS;
  }
}

const SERVER_DEFAULTS: ServerSettings = {
  theme: "arc", mood: "classic", voice: "", patience: "balanced",
  barge_in: true, wake: "normal", conversation: "open", fillers: true, speak: true, auto_mood: false,
};

let seq = 1;

interface State {
  mode: Mode;
  online: boolean;
  layout: Layout;
  voice: VoiceStatus;
  config: ServerConfig | null;
  caption: { role: "user" | "jarvis"; text: string; key: number } | null;
  hearing: Hearing | null;
  media: NowPlaying | null | undefined; // undefined: no live updates yet
  log: LogEntry[];
  tools: ToolEvent[];
  confirm: string | null;
  toasts: Toast[];
  cards: HoloCard[];
  local: LocalSettings;
  server: ServerSettings;
  persona: Persona;
  refresh: Record<Panel, number>;
  drawer: "history" | "settings" | null;
  palette: boolean;

  setMode: (m: Mode) => void;
  setCaption: (role: "user" | "jarvis", text: string) => void;
  addLog: (role: LogEntry["role"], text: string, error?: boolean) => void;
  addTool: (e: Omit<ToolEvent, "id" | "at">) => void;
  toast: (kind: Toast["kind"], text: string) => void;
  dismiss: (id: number) => void;
  addCard: (c: Omit<HoloCard, "id">) => void;
  dropCard: (id: number) => void;
  setLocal: (s: Partial<LocalSettings>) => void;
  bump: (...panels: Panel[]) => void;
  set: (s: Partial<State>) => void;
}

export const useStore = create<State>((set, get) => ({
  mode: "boot",
  online: false,
  layout: desktop?.layout ?? (new URLSearchParams(location.search).get("mode") === "orb" ? "orb" : "full"),
  voice: { ready: false, wake: false, mic: false, error: null, wake_word: "hey jarvis" },
  config: null,
  caption: null,
  hearing: null,
  media: undefined,
  log: [],
  tools: [],
  confirm: null,
  toasts: [],
  cards: [],
  local: loadLocal(),
  server: SERVER_DEFAULTS,
  persona: { moods: {}, voices: {}, voice: "" },
  refresh: { agenda: 0, mail: 0, tasks: 0, reminders: 0, timers: 0, memory: 0, system: 0, media: 0 },
  drawer: null,
  palette: false,

  setMode: (mode) => set({ mode }),
  setCaption: (role, text) => set({ caption: { role, text, key: seq++ } }),
  addLog: (role, text, error) =>
    set({ log: [...get().log.slice(-199), { id: seq++, role, text, at: Date.now(), error }] }),
  addTool: (e) => {
    const tools = get().tools;
    if (e.phase === "end") {
      // Update the matching in-flight entry rather than adding a line.
      const idx = [...tools].reverse().findIndex((t) => t.name === e.name && t.phase === "start");
      if (idx >= 0) {
        const i = tools.length - 1 - idx;
        const next = tools.slice();
        next[i] = { ...next[i], phase: "end", ok: e.ok };
        set({ tools: next });
        return;
      }
    }
    set({ tools: [...tools.slice(-5), { ...e, id: seq++, at: Date.now() }] });
  },
  toast: (kind, text) => {
    const id = seq++;
    set({ toasts: [...get().toasts.slice(-3), { id, kind, text }] });
    const ttl = kind === "reminder" || kind === "timer" ? 15000 : 6000;
    setTimeout(() => get().dismiss(id), ttl);
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
  addCard: (c) => set({ cards: [{ ...c, id: seq++ }, ...get().cards].slice(0, 3) }),
  dropCard: (id) => set({ cards: get().cards.filter((c) => c.id !== id) }),
  setLocal: (s) => {
    const local = { ...get().local, ...s };
    try {
      localStorage.setItem(LOCAL_KEY, JSON.stringify(local));
    } catch {
      /* private mode: settings just won't persist */
    }
    set({ local });
  },
  bump: (...panels) => {
    const refresh = { ...get().refresh };
    panels.forEach((p) => (refresh[p] += 1));
    set({ refresh });
  },
  set: (s) => set(s),
}));
