import { useEffect, useRef, useState } from "react";
import { activate, runHudAction, setLayout, setMic, summon } from "./lib/actions";
import { panelsForTool } from "./lib/api";
import { audio } from "./lib/audio";
import { desktop, isApp } from "./lib/desktop";
import { link, type ServerMsg } from "./lib/link";
import { useStore, type Mode } from "./lib/store";
import { Reactor } from "./components/Reactor";
import {
  Boot, Caption, CommandBar, ConfirmDialog, HistoryDrawer, SettingsDrawer,
  StatusLine, Toasts, ToolTrace, TopBar, useHotkeys,
} from "./components/Chrome";
import { CommandPalette, HearingLine, HoloCards, OrbBar } from "./components/Extras";
import {
  AgendaPanel, MailPanel, MediaPanel, MemoryPanel, SystemPanel, TasksPanel, TimersPanel,
} from "./components/Panels";

// The server owns the state machine; until the boot sequence finishes we
// only remember its latest state.
let booted = false;
let serverMode: Mode = "idle";

function applyMode(m: Mode) {
  serverMode = m;
  if (booted) useStore.getState().setMode(m);
  // The live transcript belongs to one turn; fade it once the turn is over.
  if (m !== "listening" && m !== "confirm") {
    const at = useStore.getState().hearing?.at;
    setTimeout(() => {
      if (useStore.getState().hearing?.at === at) useStore.getState().set({ hearing: null });
    }, m === "thinking" ? 2500 : 600);
  }
}

audio.onDone((id) => link.send({ type: "playback_done", id }));

function applySettings(msg: ServerMsg) {
  useStore.getState().set({
    server: msg.settings,
    persona: { moods: msg.moods, voices: msg.voices, voice: msg.voice, models: msg.models || {}, default_model: msg.default_model || "" },
  });
}

function handle(msg: ServerMsg) {
  const s = useStore.getState();
  switch (msg.type) {
    case "hello":
      s.set({ config: msg.config, voice: msg.voice, confirm: msg.confirm });
      applySettings(msg.settings);
      applyMode(msg.state);
      // Another window may have left the server mid-playback; release it.
      if (msg.state === "speaking" && !audio.speaking) link.send({ type: "playback_done" });
      if (audio.micActive) link.send({ type: "mic", on: true });
      break;
    case "state":
      applyMode(msg.state);
      break;
    case "settings":
      applySettings(msg);
      break;
    case "voice": {
      const { ready, wake, mic, error, wake_word } = msg;
      s.set({ voice: { ready, wake, mic, error, wake_word } });
      break;
    }
    case "wake":
      audio.sfx("wake");
      s.set({ hearing: null });
      break;
    case "hearing":
      s.set({
        hearing: {
          text: msg.text ?? s.hearing?.text ?? "",
          verdict: msg.verdict,
          wait: msg.wait ?? s.hearing?.wait ?? 0,
          at: Date.now(),
        },
      });
      break;
    case "barge_in":
      audio.stop();
      break;
    case "media":
      s.set({ media: msg.now });
      break;
    case "duck":
      audio.duck(true);
      break;
    case "unduck":
      audio.duck(false);
      break;
    case "transcript":
      s.setCaption("user", msg.text);
      s.addLog("user", msg.text);
      break;
    case "tool":
      s.addTool({ name: msg.name, args: msg.args, phase: msg.phase, ok: msg.ok });
      if (msg.phase === "end") {
        const panels = panelsForTool(msg.name);
        if (panels.length) s.bump(...panels);
      }
      break;
    case "reply":
      s.setCaption("jarvis", msg.text);
      s.addLog("jarvis", msg.text, msg.error);
      if (msg.error) s.toast("error", msg.text);
      break;
    case "say":
      s.setCaption("jarvis", msg.text);
      break;
    case "audio":
      // Sent only to the window that owns the mic (or every window if none does).
      if (booted) audio.push(msg.id, msg.seq, msg.audio, msg.text, msg.last);
      else if (msg.last) link.send({ type: "playback_done", id: msg.id });
      break;
    case "filler":
      if (booted && msg.audio) audio.filler(msg.audio);
      break;
    case "card":
      s.addCard({ title: msg.title, subtitle: msg.subtitle, style: msg.style, items: msg.items });
      audio.sfx("blip");
      break;
    case "hud":
      runHudAction(msg.action);
      break;
    case "confirm":
      s.set({ confirm: msg.prompt });
      audio.sfx("alert");
      break;
    case "confirm_done":
      s.set({ confirm: null });
      s.addLog("note", (msg.yes ? "Approved: " : "Declined: ") + String(msg.prompt).split("\n")[0]);
      break;
    case "notify":
      audio.sfx("notify");
      s.toast(msg.kind, msg.text);
      s.bump("reminders", "timers");
      break;
    case "notice":
      s.toast("notice", msg.text);
      break;
  }
}

export default function App() {
  const [ready, setReady] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const theme = useStore((s) => s.server.theme);
  const layout = useStore((s) => s.layout);
  const drawer = useStore((s) => s.drawer);
  const palette = useStore((s) => s.palette);
  useHotkeys(inputRef);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    document.documentElement.dataset.layout = layout;
    document.documentElement.classList.toggle("app", isApp);
  }, [layout]);

  useEffect(() => {
    const offStatus = link.onStatus((online) => {
      useStore.getState().set({ online });
      if (!online && booted) useStore.getState().setMode("idle");
    });
    const off = link.on(handle);
    link.connect();
    desktop?.onSummon(() => summon());
    desktop?.onLayout((l) => useStore.getState().set({ layout: l, drawer: null, palette: false }));
    return () => {
      off();
      offStatus();
    };
  }, []);

  const onBooted = () => {
    booted = true;
    setReady(true);
    useStore.getState().setMode(serverMode);
    if (useStore.getState().local.mic) setMic(true);
  };

  if (layout === "orb") {
    return (
      <div className={"hud orb" + (ready ? " ready" : "")}>
        <Reactor onActivate={activate} />
        <div className="orb-text">
          <HearingLine />
          <Caption compact />
        </div>
        <OrbBar onExpand={() => setLayout("full")} />
        <Toasts />
        {!ready && <Boot onDone={onBooted} auto={isApp} />}
      </div>
    );
  }

  return (
    <div className={"hud" + (ready ? " ready" : "")}>
      <div className="backdrop" aria-hidden="true" />
      <Reactor onActivate={activate} />
      <TopBar />
      <main className="deck">
        <div className="col col-left">
          <AgendaPanel />
          <TasksPanel />
          <TimersPanel />
        </div>
        <div className="center">
          <HoloCards />
          <StatusLine />
          <HearingLine />
          <ToolTrace />
          <Caption />
          <ConfirmDialog />
        </div>
        <div className="col col-right">
          <MediaPanel />
          <MailPanel />
          <SystemPanel />
          <MemoryPanel />
        </div>
      </main>
      <CommandBar inputRef={inputRef} />
      <Toasts />
      {drawer === "history" && <HistoryDrawer />}
      {drawer === "settings" && <SettingsDrawer />}
      {palette && <CommandPalette />}
      {!ready && <Boot onDone={onBooted} auto={isApp} />}
    </div>
  );
}
