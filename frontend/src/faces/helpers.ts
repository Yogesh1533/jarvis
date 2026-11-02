import * as THREE from "three";
import type { FaceEnv } from "./types";

export const sm = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

/** 2D gaussian bump. */
export const gs = (x: number, y: number, cx: number, cy: number, sx: number, sy: number) => {
  const dx = (x - cx) / sx;
  const dy = (y - cy) / sy;
  return Math.exp(-(dx * dx + dy * dy) * 0.5);
};

/** A soft studio environment so brushed metal has something to reflect. */
export function studioEnvironment(renderer: THREE.WebGLRenderer): THREE.Texture {
  const env = new THREE.Scene();
  const sph = new THREE.Mesh(
    new THREE.SphereGeometry(10, 24, 16),
    new THREE.MeshBasicMaterial({ side: THREE.BackSide, vertexColors: true }),
  );
  const p = sph.geometry.attributes.position;
  const cols = new Float32Array(p.count * 3);
  const c = new THREE.Color();
  for (let i = 0; i < p.count; i++) {
    c.setHSL(0.68, 0.45, 0.06 + 0.2 * Math.max(0, p.getY(i) / 10 + 0.2));
    cols.set([c.r, c.g, c.b], i * 3);
  }
  sph.geometry.setAttribute("color", new THREE.BufferAttribute(cols, 3));
  env.add(sph);
  ([[-5, 5, 6, 0xffffff, 7], [6, 2, 5, 0x9ad8ff, 4], [0, 8, -4, 0xb59cff, 5]] as const).forEach(([x, y, z, hex, k]) => {
    const m = new THREE.Mesh(
      new THREE.PlaneGeometry(6, 3),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(hex).multiplyScalar(k), side: THREE.DoubleSide }),
    );
    m.position.set(x, y, z);
    m.lookAt(0, 0, 0);
    env.add(m);
  });
  const pm = new THREE.PMREMGenerator(renderer);
  const tex = pm.fromScene(env).texture;
  pm.dispose();
  env.traverse((o) => {
    const m = o as THREE.Mesh;
    m.geometry?.dispose();
    (m.material as THREE.Material | undefined)?.dispose();
  });
  return tex;
}

/** Key, fill and a coloured rim. Intensities are tuned for three's physical lights. */
export function lights(root: THREE.Object3D, rimColor: number) {
  root.add(new THREE.AmbientLight(0xb4a8f4, 0.55));
  const key = new THREE.DirectionalLight(0xffffff, 1.7);
  key.position.set(2.6, 2.8, 3.2);
  const fill = new THREE.DirectionalLight(0x8a7ad8, 0.6);
  fill.position.set(-3, 0.5, 2.5);
  const rim = new THREE.PointLight(rimColor, 14, 10, 2);
  rim.position.set(-2.5, 1.2, -2);
  root.add(key, fill, rim);
  return rim;
}

/** Cursor parallax, a slow idle drift and a hype bob. */
export function aim(group: THREE.Object3D, env: FaceEnv) {
  const { t, ptr, e } = env;
  group.rotation.y = ptr.x * 0.5 + Math.sin(t * 0.4) * 0.05 + e.lx * 0.1;
  group.rotation.x = ptr.y * 0.22 + Math.sin(t * 0.5) * 0.025 - e.ly * 0.07;
  group.rotation.z = e.hype * 0.05 * Math.sin(t * 4.2);
  group.position.y = Math.sin(t * 0.9) * 0.02 + e.hype * 0.05 * Math.abs(Math.sin(t * 8.5));
}

/** A neck with a glowing collar ring. Returns the ring so the caller can tint it. */
export function neck(parent: THREE.Object3D, y: number) {
  const ng = new THREE.CylinderGeometry(0.27, 0.34, 0.8, 32, 6, true);
  const np = ng.attributes.position;
  const nc = new Float32Array(np.count * 3);
  for (let i = 0; i < np.count; i++) {
    const f = sm(-0.4, 0.4, np.getY(i));
    nc.set([0.22 * f + 0.02, 0.2 * f + 0.02, 0.3 * f + 0.04], i * 3);
  }
  ng.setAttribute("color", new THREE.BufferAttribute(nc, 3));
  const m = new THREE.Mesh(ng, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.4, metalness: 0.7 }));
  m.position.set(0, y, -0.05);
  parent.add(m);
  const collar = new THREE.Mesh(new THREE.TorusGeometry(0.32, 0.014, 8, 48), new THREE.MeshBasicMaterial({ color: 0x6fd8ff }));
  collar.rotation.x = Math.PI / 2;
  collar.position.set(0, y + 0.23, -0.04);
  parent.add(collar);
  return collar;
}

/** A 2D canvas used as a live texture (screens, visors, drawn faces). */
export function liveCanvas(w: number, h: number) {
  const cv = document.createElement("canvas");
  cv.width = w;
  cv.height = h;
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  return { cv, cx: cv.getContext("2d")!, tex };
}

/** Free every geometry, material and texture under a root. */
export function disposeTree(root: THREE.Object3D) {
  root.traverse((o) => {
    const m = o as THREE.Mesh;
    m.geometry?.dispose();
    const mat = m.material as THREE.Material | THREE.Material[] | undefined;
    for (const x of Array.isArray(mat) ? mat : mat ? [mat] : []) {
      (x as THREE.MeshBasicMaterial).map?.dispose();
      x.dispose();
    }
  });
}
