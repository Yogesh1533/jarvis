import type * as THREE from "three";
import type { Mode } from "../lib/store";

/** Which face fills the stage. "orb" is the original particle reactor. */
export type FaceId = "orb" | "hologram" | "android" | "screen" | "visor" | "orbface" | "sentinel";

export const FACES: { id: FaceId; name: string; blurb: string }[] = [
  { id: "orb", name: "Orb", blurb: "The particle reactor" },
  { id: "hologram", name: "Hologram", blurb: "A wireframe built from your own face" },
  { id: "screen", name: "Screen droid", blurb: "Chrome head, glowing eyes, voice equalizer" },
  { id: "android", name: "Android", blurb: "Crimson face, gold cowl, forehead gem" },
  { id: "visor", name: "Visor", blurb: "White helmet with one light bar" },
  { id: "orbface", name: "Orb face", blurb: "The orb with a face drawn in light" },
  { id: "sentinel", name: "Sentinel", blurb: "Faceted gunmetal head with a vented mouth" },
];

/** Everything a face can express, eased each frame by `Expression`. */
export interface Expr {
  eye: number; // eye openness, 1 = normal
  brow: number; // -1 frown .. 1 raised
  tilt: number; // brow angle, + stern
  smile: number; // -1 .. 1
  lx: number; // gaze, -1 left .. 1 right
  ly: number; // gaze, -1 down .. 1 up
  hype: number; // 0 .. 1
  amp: number; // mouth opening from the real voice, 0 .. 1
  wide: number; // mouth width wobble around 1
  blink: number; // 1 open .. 0 shut
  burst: number; // seconds since Hype was switched on
}

export interface FaceEnv {
  t: number;
  dt: number;
  color: THREE.Color; // theme/mode colour, already eased
  deep: THREE.Color;
  mode: Mode;
  e: Expr;
  ptr: { x: number; y: number }; // eased pointer, -1 .. 1
}

export interface Face {
  root: THREE.Object3D;
  camera: { fov: number; pos: [number, number, number]; look: [number, number, number] };
  /** Base bloom strength; the stage adds the voice level on top. */
  bloom: number;
  /** True when the face uses lit PBR materials and wants the studio environment map. */
  lit: boolean;
  update(env: FaceEnv): void;
  dispose(): void;
}
