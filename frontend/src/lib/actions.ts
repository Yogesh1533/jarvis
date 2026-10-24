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

let micBusy: Promise<void> = Promise.resolve();

/** Turn the mic on or off. Calls run one at a time. */
export function setMic(on: boolean): Promise<void> {
  micBusy = micBusy.then(() => applyMic(on)).catch(() => {});
  return micBusy;
}

async function applyMic(on: boolean) {
  const store = useStore.getState();
  if (!on) {
    audio.stopMic();
    store.setLocal({ mic: false });
    link.send({ type: "mic", on: false });
    return;
  }
  try {
    await audio.init();
    await audio.startMic((buf) => link.sendAudio(buf), store.local.micDevice, () => restartMic());
  } catch (e) {
    const name = (e as Error).name;
    link.send({ type: "mic", on: false });
    if (name === "NotAllowedError" || name === "SecurityError") {
      store.toast("error", "Microphone blocked. Allow mic access for Jarvis, then turn it on again.");
      store.setLocal({ mic: false });
    } else {
      // No mic plugged in right now: stay switched on and pick one up when it appears.
      store.toast("notice", "No microphone found. I'll start listening when one is connected.");
    }
    return;
  }
  store.setLocal({ mic: true });
  link.send({ type: "mic", on: true });
}

/** Reopen the mic (a device was unplugged or switched, or a new one chosen). */
export function restartMic() {
  if (!useStore.getState().local.mic) return Promise.resolve();
  audio.stopMic();
  return setMic(true);
}

export function chooseMic(deviceId: string) {
  useStore.getState().setLocal({ micDevice: deviceId });
  return restartMic();
}

// Headsets and USB mics come and go; follow them.
let deviceTimer: ReturnType<typeof setTimeout> | undefined;
navigator.mediaDevices?.addEventListener("devicechange", () => {
  clearTimeout(deviceTimer);
  deviceTimer = setTimeout(() => {
    const { local } = useStore.getState();
    if (!local.mic) return;
    // Restart when we have no mic, or when following the system default
    // (which may have just changed).
    if (!audio.micActive || !local.micDevice) restartMic();
  }, 600);
});

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
