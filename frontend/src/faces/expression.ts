import type { Mode } from "../lib/store";
import type { Expr } from "./types";

type Target = Pick<Expr, "eye" | "brow" | "tilt" | "smile" | "lx" | "ly" | "hype">;

/** What each state of the assistant looks like. */
const MODE: Record<Mode, Target> = {
  boot: { eye: 0.12, brow: 0, tilt: 0, smile: 0, lx: 0, ly: 0, hype: 0 },
  idle: { eye: 0.95, brow: 0, tilt: 0, smile: 0.06, lx: 0, ly: 0, hype: 0 },
  listening: { eye: 1.12, brow: 0.4, tilt: 0, smile: 0.12, lx: 0, ly: 0.1, hype: 0 },
  thinking: { eye: 0.9, brow: 0.5, tilt: -0.15, smile: 0, lx: -0.8, ly: 0.7, hype: 0 },
  speaking: { eye: 1.0, brow: 0.12, tilt: 0, smile: 0.25, lx: 0, ly: 0, hype: 0 },
  confirm: { eye: 0.85, brow: -0.7, tilt: 0.55, smile: -0.1, lx: 0, ly: 0, hype: 0 },
};

/** The persona mood (Settings, or "switch to calm mode") nudges the expression. */
const MOOD: Record<string, Partial<Target>> = {
  calm: { eye: -0.2, brow: -0.15, smile: 0.12, ly: -0.1 },
  focused: { eye: -0.3, brow: -0.5, tilt: 0.4, smile: -0.1 },
  upbeat: { eye: 0.15, brow: 0.4, smile: 0.6 },
  night: { eye: -0.35, brow: -0.2, smile: 0.05 },
  hype: { eye: 0.3, brow: 0.9, smile: 0.95, hype: 1 },
  friend: { eye: 0.05, brow: 0.15, smile: 0.3 },
  sarcastic: { eye: -0.3, brow: -0.35, tilt: 0.3, smile: 0.15 },
  roast: { eye: -0.15, brow: -0.2, tilt: 0.45, smile: 0.5 },
};

/** Quick reactions (the hud_react tool): peak offsets, eased in and out. */
const REACT: Record<string, Partial<Target> & { wiggle?: number }> = {
  laugh: { smile: 0.9, eye: -0.5, brow: 0.3, wiggle: 0.18 },
  groan: { eye: -0.5, brow: -0.8, smile: -0.4, ly: -0.5 },
  smirk: { smile: 0.5, tilt: 0.5, brow: -0.3, eye: -0.2 },
  wow: { eye: 0.5, brow: 1, smile: 0.1, ly: 0.2 },
  facepalm: { eye: -0.6, brow: -0.9, smile: -0.3, tilt: -0.6, ly: -0.8 },
  wink: { smile: 0.6, tilt: 0.3, eye: -0.4 },
};
const REACT_SECS = 1.5;

const KEYS = ["eye", "brow", "tilt", "smile", "lx", "ly", "hype"] as const;

/** Turns (mode, mood, voice level) into smooth facial parameters, blinks included. */
export class Expression {
  v: Expr = { eye: 0.12, brow: 0, tilt: 0, smile: 0, lx: 0, ly: 0, hype: 0, amp: 0, wide: 1, blink: 1, burst: 99 };
  private t = 0;
  private nextBlink = 2.5;
  private blinkT = -1;
  private lastMood = "";
  private reacting: { kind: string; t: number } | null = null;

  react(kind: string) {
    if (REACT[kind]) this.reacting = { kind, t: 0 };
  }

  update(dt: number, mode: Mode, mood: string, out: number, mic: number) {
    const v = this.v;
    this.t += dt;
    const target: Target = { ...MODE[mode] };
    const nudge = MOOD[mood];
    if (nudge && mode !== "boot") for (const k of KEYS) target[k] += nudge[k] ?? 0;
    if (mode === "listening") {
      target.eye += mic * 0.25;
      target.brow += mic * 0.3;
    }
    if (this.reacting) {
      const r = this.reacting;
      r.t += dt;
      const u = r.t / REACT_SECS;
      if (u >= 1) this.reacting = null;
      else {
        const env = Math.sin(Math.min(1, u * 1.6) * Math.PI / 2) * (1 - Math.max(0, u - 0.6) / 0.4);
        const o = REACT[r.kind];
        for (const key of KEYS) target[key] += (o[key] ?? 0) * env;
        if (o.wiggle) target.tilt += Math.sin(r.t * 18) * o.wiggle * env;
        if (r.kind === "wink" && u > 0.15 && u < 0.35) target.eye -= 0.7;
      }
    }
    const k = 1 - Math.exp(-dt * 7);
    for (const key of KEYS) v[key] += (target[key] - v[key]) * k;

    if (mood === "hype" && this.lastMood !== "hype") v.burst = 0;
    else v.burst += dt;
    this.lastMood = mood;

    // Only Jarvis's own voice moves the mouth.
    const want = mode === "speaking" ? Math.min(1, out * 1.25) : 0;
    v.amp += (want - v.amp) * (1 - Math.exp(-dt * (want > v.amp ? 40 : 16)));
    v.wide += (0.75 + 0.5 * Math.sin(this.t * 6.3) - v.wide) * 0.2;

    if (this.blinkT < 0 && this.t > this.nextBlink) this.blinkT = 0;
    if (this.blinkT >= 0) {
      this.blinkT += dt;
      const u = this.blinkT / 0.17;
      v.blink = u < 1 ? 1 - Math.sin(u * Math.PI) : 1;
      if (u >= 1) {
        this.blinkT = -1;
        this.nextBlink = this.t + 2.2 + Math.random() * 3;
      }
    } else v.blink = 1;
  }
}
