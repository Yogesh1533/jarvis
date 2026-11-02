import type * as THREE from "three";
import { androidFace, orbFace, screenFace, sentinelFace, visorFace } from "./droids";
import { hologramFace } from "./hologram";
import type { Face, FaceId } from "./types";

export { FACES, type FaceId } from "./types";

export async function createFace(id: Exclude<FaceId, "orb">, renderer: THREE.WebGLRenderer): Promise<Face> {
  switch (id) {
    case "hologram": return hologramFace(renderer);
    case "android": return androidFace();
    case "visor": return visorFace();
    case "orbface": return orbFace();
    case "sentinel": return sentinelFace();
    default: return screenFace();
  }
}

let scan: Promise<boolean> | null = null;

/** Whether this Mac has a face scan for the hologram (data/face/hologram.json). */
export function hologramAvailable(): Promise<boolean> {
  scan ??= fetch("/api/face/hologram", { cache: "no-cache" }).then((r) => r.ok, () => false);
  return scan;
}
