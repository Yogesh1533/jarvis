import { audio } from "./audio";
import { desktop } from "./desktop";
import { link } from "./link";
import { useStore, type Layout, type ServerSettings } from "./store";

/** Send a typed request (or a quick action) to Jarvis. */
export function ask(text: string) {
  if (audio.speaking) audio.stop();
  link.send({ type: "text", text });
}

/** Stop Jarvis talking and start listening instead (barge-in). */
export function interrupt() {
  audio.stop();
  link.send({ type: "interrupt" });
}

/** The reactor button / Space key / ⌘J: talk, stop listening, or interrupt. */
export function activate() {
  const { mode } = useStore.getState();
  if (mode === "speaking") interrupt();
  else link.send({ type: "listen" });
}

/** ⌘J from anywhere on the Mac: start listening right away (or cut Jarvis off). */
export function summon() {
  const { mode } = useStore.getState();
  if (mode === "speaking") interrupt();
  else if (mode !== "listening") link.send({ type: "summon" });
}

export function answerConfirm(yes: boolean) {
  audio.stop();
  link.send({ type: "confirm", yes });
}

/** Change a server-side setting (mood, voice, patience…). Every window updates. */
export function setServer(changes: Partial<ServerSettings>) {
  const s = useStore.getState();
  s.set({ server: { ...s.server, ...changes } }); // optimistic; the server echoes back
  link.send({ type: "settings", changes });
}

export function setLayout(layout: Layout) {
  useStore.getState().set({ layout, drawer: null, palette: false });
  desktop?.setLayout(layout);
}

export function toggleFullscreen() {
  // Pages may only go full screen from a click; the app window can any time.
  if (desktop) desktop.toggleFullscreen();
  else if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen?.();
}

export async function setMic(on: boolean) {
  const store = useStore.getState();
  if (on) {
    try {
      await audio.init();
      await audio.startMic((buf) => link.sendAudio(buf));
    } catch {
      store.toast("error", "Microphone blocked. Allow mic access for Jarvis, then turn it on again.");
      store.setLocal({ mic: false });
      link.send({ type: "mic", on: false });
      return;
    }
  } else {
    audio.stopMic();
  }
  store.setLocal({ mic: on });
  link.send({ type: "mic", on });
}

/** Interface actions Jarvis can trigger by voice (the hud_control tool). */
export function runHudAction(action: string) {
  const s = useStore.getState();
  switch (action) {
    case "open_history":
      s.set({ drawer: "history", palette: false });
      break;
    case "open_settings":
      s.set({ drawer: "settings", palette: false });
      break;
    case "open_palette":
      s.set({ palette: true, drawer: null });
      break;
    case "close_panels":
      s.set({ drawer: null, palette: false });
      break;
    case "clear_cards":
      s.set({ cards: [] });
      break;
    case "orb_mode":
      setLayout("orb");
      break;
    case "full_mode":
      setLayout("full");
      break;
    case "toggle_fullscreen":
      toggleFullscreen();
      break;
    case "mute_mic":
      setMic(false);
      break;
  }
}
