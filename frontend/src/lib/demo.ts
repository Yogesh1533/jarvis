import { audio } from "./audio";
import { useStore, type DevTask, type Mode } from "./store";
import type { FaceId } from "../faces/types";

/*
 * A scripted showcase for filming: no server, no microphone, nothing saved.
 * It plays a short fake conversation on the real HUD (modes, captions,
 * cards, reactions), then tours the faces. Press Esc or click to stop.
 */

const FACES_TOUR: [FaceId, string][] = [
  ["hologram", "Hologram. Built from a scan of one very handsome face."],
  ["screen", "Screen droid. Friendly, slightly smug."],
  ["visor", "Visor. For when I mean business."],
  ["sentinel", "Sentinel. Please don't make me use this one."],
  ["orb", "And the classic orb, for the traditionalists."],
];

let stop: (() => void) | null = null;
export const demoRunning = () => stop !== null;

export function stopDemo() {
  stop?.();
}

export function startDemo() {
  if (stop) return;
  const s = useStore.getState;
  const saved = { face: s().local.face, mode: s().mode, cards: s().cards, caption: s().caption };
  const timers: number[] = [];
  let ended = false;

  const at = (ms: number, fn: () => void) => void timers.push(window.setTimeout(() => !ended && fn(), ms));
  const mode = (m: Mode) => s().setMode(m);
  const say = (role: "user" | "jarvis", text: string) => s().setCaption(role, text);
  const react = (kind: string) => s().set({ reaction: { kind, at: Date.now() } });
  const speak = (on: boolean) => (audio.demoVoice = on);

  const end = () => {
    if (ended) return;
    ended = true;
    timers.forEach(clearTimeout);
    speak(false);
    window.removeEventListener("keydown", onKey, true);
    window.removeEventListener("pointerdown", onClick, true);
    s().set({ cards: [], caption: saved.caption, drawer: null, demoDevtasks: null });
    s().setLocal({ face: saved.face });
    mode(saved.mode === "boot" ? "idle" : saved.mode);
    stop = null;
  };
  const onKey = (e: KeyboardEvent) => e.key === "Escape" && end();
  const onClick = () => end();
  window.addEventListener("keydown", onKey, true);
  // Ignore the click that started the demo (from the palette).
  setTimeout(() => !ended && window.addEventListener("pointerdown", onClick, true), 600);
  stop = end;

  s().set({ drawer: null, palette: false, cards: [] });
  if (saved.face === "orb") s().setLocal({ face: "hologram" });

  // Scene 1: ask for the day.
  at(800, () => { mode("listening"); say("user", "Hey Jarvis, what does my day look like?"); });
  at(3600, () => mode("thinking"));
  at(5200, () => {
    mode("speaking"); speak(true);
    say("jarvis", "Busy. Three meetings, one of which could have been an email, and a gap at four where you'll definitely do nothing.");
    s().addCard({
      title: "Today", subtitle: "Demo data", style: "list",
      items: [
        { title: "Design review", detail: "10:00 · Room 4", value: "10:00" },
        { title: "Investor call", detail: "13:30 · Zoom", value: "13:30" },
      ],
    });
    audio.sfx("blip");
  });
  at(8800, () => react("smirk"));
  at(11500, () => { speak(false); mode("idle"); });

  // Scene 2: a roast.
  at(12500, () => { mode("listening"); say("user", "Roast my morning."); });
  at(14500, () => mode("thinking"));
  at(15800, () => {
    mode("speaking"); speak(true);
    say("jarvis", "Three snoozes, cereal for dinner energy, and you opened the laptop before the kettle. Bold.");
    s().set({ cards: [] });
    s().addCard({
      title: "Vitals", subtitle: "Demo data", style: "stats",
      items: [
        { title: "Snoozes", value: "3" },
        { title: "Coffee", value: "2" },
        { title: "Meetings", value: "3" },
      ],
    });
    audio.sfx("blip");
  });
  at(18500, () => react("laugh"));
  at(21500, () => { speak(false); mode("idle"); s().set({ cards: [] }); });

  // Scene 2b: a coding agent works in the Agents panel (fake rows, no backend).
  const stamp = (offsetS: number) => {
    const d = new Date(Date.now() + offsetS * 1000);
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  };
  const started = stamp(0);
  const job = (state: "running" | "done", step: string, extra: Partial<DevTask> = {}): DevTask[] => [{
    id: 1, project: "demo-app", instruction: "Add a dark mode toggle to settings",
    branch: null, state, started_at: started, finished_at: null, last_step: step, summary: null, diffstat: null, ...extra,
  }];
  const steps = ["Reading the codebase", "Editing Settings.tsx", "Running tests"];
  at(12600, () => s().set({ demoDevtasks: job("running", "Starting up") }));
  steps.forEach((st, i) => at(14500 + i * 2200, () => s().set({ demoDevtasks: job("running", st) })));
  at(14500 + steps.length * 2200, () =>
    s().set({ demoDevtasks: job("done", "Done", { finished_at: stamp(0), branch: "jarvis/dark-mode-a1b2", diffstat: "3 files, +42 -7" }) }));

  // Scene 3: the face tour.
  FACES_TOUR.forEach(([face, line], i) => {
    const t = 22500 + i * 4200;
    at(t, () => { s().setLocal({ face }); mode("speaking"); speak(true); say("jarvis", line); if (i === 2) react("wow"); });
    at(t + 3600, () => { speak(false); mode("idle"); });
  });
  at(22500 + FACES_TOUR.length * 4200 + 600, end);
}
