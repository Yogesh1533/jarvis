import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { audio } from "../lib/audio";
import { useStore, type Mode } from "../lib/store";

/*
 * The cinematic layer: a framed viewport, a rotating identity ring, a halo
 * behind the face and six small readouts. Every number is live: the audio
 * bars follow the real mic and speaker levels, the latency is a measured
 * round trip to this server, CPU and memory come from /api/system.
 */

const MODE_WORD: Record<Mode, string> = {
  boot: "BOOTING",
  idle: "STANDBY",
  listening: "LISTENING",
  thinking: "PROCESSING",
  speaking: "TRANSMITTING",
  confirm: "AWAITING YOU",
};

const up = (s: string) => s.replace(/[_-]+/g, " ").toUpperCase();
const short = (id: string) => (id.split("/").pop() ?? id).replace(/[_-]+/g, " ").toUpperCase();

interface Sys { cpu: number }

function Box({ title, rows, live, level, side }: {
  title: string;
  rows: [string, string][];
  live?: "out" | "mic" | "mode";
  level?: number; // 0..1, the steady bar
  side: "l" | "r";
}) {
  return (
    <div className={"tele-box " + side + (live ? " has-live" : "")}>
      <b>{title}</b>
      {rows.map(([k, v]) => (
        <p key={k}><span>{k}</span> · {v}</p>
      ))}
      <div className="tele-bar"><i style={{ width: `${Math.round(Math.min(1, Math.max(0, level ?? 0)) * 100)}%` }} /></div>
      <div className="tele-bar live"><i data-live={live ?? "none"} /></div>
    </div>
  );
}

export function HudFrame() {
  return (
    <div className="hud-frame" aria-hidden="true">
      <i className="sweep" />
      <i className="c tl" /><i className="c tr" /><i className="c bl" /><i className="c br" />
    </div>
  );
}

function IdentRing({ mode }: { mode: Mode }) {
  const ticks = Array.from({ length: 36 }, (_, i) => i);
  return (
    <svg className={"ident m-" + mode} viewBox="-100 -100 200 200" aria-hidden="true">
      <circle className="r1" r="94" />
      <g className="spin-a">
        <circle className="r2" r="86" />
        {ticks.map((i) => (
          <line key={i} className={i % 9 === 0 ? "big" : ""} x1="0" y1={i % 9 === 0 ? -94 : -91} x2="0" y2="-86" transform={`rotate(${i * 10})`} />
        ))}
      </g>
      <circle className="r3" r="68" />
      <text textAnchor="middle" dominantBaseline="central" y="1">J.A.R.V.I.S.</text>
    </svg>
  );
}

function Halo() {
  return (
    <svg className="halo" viewBox="-100 -100 200 200" aria-hidden="true">
      <circle r="92" />
      <g className="spin-b"><circle r="84" strokeDasharray="1 9" strokeWidth="1.4" /></g>
    </svg>
  );
}

export function Telemetry() {
  const root = useRef<HTMLDivElement>(null);
  const mode = useStore((s) => s.mode);
  const online = useStore((s) => s.online);
  const config = useStore((s) => s.config);
  const voice = useStore((s) => s.voice);
  const persona = useStore((s) => s.persona);
  const mood = useStore((s) => s.server.mood);
  const face = useStore((s) => s.local.face);
  const [ms, setMs] = useState<number | null>(null);

  // Round trip to the server, and the vitals that ride along.
  useEffect(() => {
    let dead = false;
    const poll = async () => {
      const t0 = performance.now();
      const res = await api<Sys>("/api/system");
      if (dead) return;
      setMs(res.data ? Math.round(performance.now() - t0) : null);
    };
    void poll();
    const id = setInterval(poll, 2500);
    return () => {
      dead = true;
      clearInterval(id);
    };
  }, []);

  // Live bars follow the real audio levels. Writing the DOM directly keeps
  // this off React's render path.
  useEffect(() => {
    let raf = 0;
    const els = root.current!.querySelectorAll<HTMLElement>("[data-live]");
    const cur = new WeakMap<HTMLElement, number>();
    const frame = () => {
      raf = requestAnimationFrame(frame);
      const m = useStore.getState().mode;
      for (const el of els) {
        const kind = el.dataset.live;
        const target =
          kind === "out" ? audio.level("out") * 1.6
          : kind === "mic" ? audio.level("mic") * 1.6
          : kind === "mode" ? (m === "idle" ? 0.12 : m === "thinking" ? 0.55 + 0.4 * Math.sin(performance.now() / 160) ** 2 : 0.8)
          : 0;
        const v = (cur.get(el) ?? 0) + (Math.min(1, target) - (cur.get(el) ?? 0)) * 0.25;
        cur.set(el, v);
        el.style.width = `${(v * 100).toFixed(1)}%`;
      }
    };
    frame();
    return () => cancelAnimationFrame(raf);
  }, []);

  const voiceName = persona.voices[persona.voice] ?? persona.voice ?? "default";

  return (
    <div className={"tele m-" + mode + (face === "orb" ? " orb" : "")} ref={root} aria-hidden="true">
      <Halo />
      <IdentRing mode={mode} />
      <div className="tele-col left">
        <Box side="l" title="VOICE" live="out" level={0.78}
          rows={[["PROFILE", up(voiceName)], ["ENGINE", up(config?.tts ?? "--")]]} />
        <Box side="l" title="WAKE" live="mic" level={voice.wake ? 0.9 : 0.1}
          rows={[["WORD", up(voice.wake_word ?? "--")], ["MIC", voice.mic ? "LISTENING" : "OFF"]]} />
      </div>
      <div className="tele-col right">
        <Box side="r" title="LINK" level={ms === null ? 0 : 1 - Math.min(1, ms / 400)}
          rows={[[up(config?.backend ?? "brain"), online ? "ONLINE" : "OFFLINE"], ["MODEL", short(config?.model ?? "--")], ["LATENCY", ms === null ? "--" : `${ms} MS`]]} />
        <Box side="r" title="MOOD" live="mode" level={0.7}
          rows={[["STATE", MODE_WORD[mode]], ["PERSONA", up(mood)]]} />
      </div>
    </div>
  );
}
