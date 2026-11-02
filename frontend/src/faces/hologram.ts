import * as THREE from "three";
import { disposeTree, sm } from "./helpers";
import type { Face, FaceEnv } from "./types";

/*
 * A wireframe head built from 478 face landmarks measured on the owner's own
 * photo (scripts/face_scan.py). The points are served from the gitignored
 * data/ folder, so the repo never holds them. Jaw and lips follow the voice,
 * the eyelids blink, and brows, smile and gaze follow the expression.
 */

interface Data {
  lm: number[][];
  tess: number[];
  cont: number[];
}

const LIDS: [number, number][] = [
  [159, 145], [158, 153], [160, 144], [161, 163], [157, 154],
  [386, 374], [385, 380], [387, 373], [388, 390], [384, 381],
];
const BROW = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46, 300, 293, 334, 296, 336, 285, 295, 282, 283, 276];
const CORNERS = [61, 291, 62, 292, 76, 306, 185, 409];

const LINE_VERT = /* glsl */ `
varying float vY; varying float vZ;
void main(){ vec4 w = modelMatrix * vec4(position, 1.0); vY = w.y; vZ = position.z; gl_Position = projectionMatrix * viewMatrix * w; }`;
const LINE_FRAG = /* glsl */ `
uniform vec3 uCol; uniform float uA, uT, uScan, uW; uniform vec2 uZr; varying float vY; varying float vZ;
void main(){
  float d = smoothstep(uZr.x, uZr.y, vZ);
  float a = uA * (0.3 + 0.8 * d);
  a += exp(-pow((vY - uScan) * uW, 2.0)) * 0.85 * uA;
  a *= 0.92 + 0.08 * sin(uT * 28.0 + vY * 60.0);
  gl_FragColor = vec4(uCol * a, a);
}`;
const POINT_VERT = /* glsl */ `
uniform float uSize; void main(){ gl_PointSize = uSize; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const POINT_FRAG = /* glsl */ `
uniform vec3 uCol; uniform float uA;
void main(){ float d = length(gl_PointCoord - 0.5); float a = smoothstep(0.5, 0.0, d) * uA; gl_FragColor = vec4(mix(uCol, vec3(1.0), 0.35 * a) * a, a); }`;

export async function hologramFace(renderer: THREE.WebGLRenderer): Promise<Face> {
  const res = await fetch("/api/face/hologram", { cache: "no-cache" });
  if (!res.ok) throw new Error("The hologram needs a face scan. Run scripts/face_scan.py on a front photo.");
  const D: Data = await res.json();
  const lm = D.lm, E = D.tess, K = D.cont, N = lm.length;
  const DPR = renderer.getPixelRatio();

  // ── landmarks → centred, roll- and pitch-corrected points ──────────
  const AR = 0.75, SC = 2.3; // photo aspect (3:4) and a convenient world scale
  const cx = lm[168][0], cy = lm[168][1];
  const ang = Math.atan2(lm[263][1] - lm[33][1], (lm[263][0] - lm[33][0]) * AR);
  const ca = Math.cos(ang), sa = Math.sin(ang);
  const base = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    const px = (lm[i][0] - cx) * AR, py = lm[i][1] - cy;
    base.set([(px * ca + py * sa) * SC, -(-px * sa + py * ca) * SC, -lm[i][2] * AR * SC], i * 3);
  }
  const bx = (k: number) => base[k * 3], by = (k: number) => base[k * 3 + 1], bz = (k: number) => base[k * 3 + 2];
  const pitch = 0.12 - Math.atan2(bz(10) - bz(152), by(10) - by(152));
  const cp = Math.cos(pitch), sp = Math.sin(pitch);
  for (let i = 0; i < N; i++) {
    const y0 = by(i), z0 = bz(i);
    base[i * 3 + 1] = y0 * cp - z0 * sp;
    base[i * 3 + 2] = y0 * sp + z0 * cp;
  }
  const H = Math.abs(by(10) - by(152));
  const xc = (bx(234) + bx(454)) / 2, Wt = Math.abs(bx(454) - bx(234)) / 2;
  let zmin = 1e9, zmax = -1e9;
  for (let i = 0; i < N; i++) { zmin = Math.min(zmin, bz(i)); zmax = Math.max(zmax, bz(i)); }

  // ── per-point deformation weights ──────────────────────────────────
  const gauss = (centres: number[], sigma: number) => {
    const w = new Float32Array(N);
    for (let p = 0; p < N; p++) {
      let m = 0;
      for (const c of centres) {
        const dx = bx(p) - bx(c), dy = by(p) - by(c);
        m = Math.max(m, Math.exp(-(dx * dx + dy * dy) / (2 * sigma * sigma)));
      }
      w[p] = m;
    }
    return w;
  };
  const mouthY = (by(13) + by(14)) / 2, mouthHalf = Math.abs(bx(291) - bx(61)) / 2;
  const jawW = new Float32Array(N), upW = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    const below = (mouthY - by(i)) / H, ax = Math.abs(bx(i) - xc) / Wt;
    jawW[i] = sm(-0.01, 0.07, below) * (1 - 0.8 * sm(0.45, 0.95, ax) * (1 - sm(0.25, 0.5, below)));
    upW[i] = below < 0 && -below < 0.1 ? (1 - sm(0, 0.09, -below)) * (1 - sm(0.8, 1.6, Math.abs(bx(i) - xc) / mouthHalf)) : 0;
  }
  const smileW = gauss(CORNERS, 0.09 * H);
  const browW = gauss(BROW, 0.07 * H);

  // ── scene objects ──────────────────────────────────────────────────
  const root = new THREE.Group();
  const pivot = new THREE.Group();
  root.add(pivot);
  const U = {
    uCol: { value: new THREE.Color() }, uT: { value: 0 }, uScan: { value: 0 },
    uW: { value: 1 / (0.1 * H) }, uZr: { value: new THREE.Vector2(zmin, zmax) },
  };
  const lineMat = (a: number) => new THREE.ShaderMaterial({
    uniforms: { uCol: U.uCol, uT: U.uT, uScan: U.uScan, uW: U.uW, uZr: U.uZr, uA: { value: a } },
    vertexShader: LINE_VERT, fragmentShader: LINE_FRAG,
    transparent: true, depthTest: false, blending: THREE.AdditiveBlending,
  });
  const pointMat = (size: number, a: number) => new THREE.ShaderMaterial({
    uniforms: { uCol: U.uCol, uSize: { value: size * DPR }, uA: { value: a } },
    vertexShader: POINT_VERT, fragmentShader: POINT_FRAG,
    transparent: true, depthTest: false, blending: THREE.AdditiveBlending,
  });
  const dynamic = (arr: Float32Array) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(arr, 3));
    return g;
  };
  const add = (o: THREE.Object3D, parent: THREE.Object3D = pivot) => { o.frustumCulled = false; parent.add(o); return o; };

  const pos = new Float32Array(base);
  const tessArr = new Float32Array(E.length * 3), contArr = new Float32Array(K.length * 3);
  const contGeo = dynamic(contArr), ptGeo = dynamic(pos);
  const tessGeo = dynamic(tessArr);
  add(new THREE.LineSegments(tessGeo, lineMat(0.34)));
  add(new THREE.LineSegments(contGeo, lineMat(1.0)));
  const contB = add(new THREE.LineSegments(contGeo, lineMat(0.7)));
  contB.position.set(0.0025 * H, 0.0025 * H, 0);
  add(new THREE.Points(ptGeo, pointMat(3.2, 0.8)));
  const eyeArr = new Float32Array(6), eyeGeo = dynamic(eyeArr);
  const eyeGlow = pointMat(50, 1), eyeCore = pointMat(16, 1);
  add(new THREE.Points(eyeGeo, eyeGlow));
  add(new THREE.Points(eyeGeo, eyeCore));

  // A faint neck so the head doesn't float, and a broken halo behind it.
  const neck: number[] = [];
  const yN = by(152) - 0.22 * H, zN = bz(234) - 0.35 * Wt;
  const ring = (y: number, rx: number, rz: number) => {
    for (let s = 0; s < 36; s++) {
      const a = -Math.PI / 2 + (Math.PI * s) / 36, b = -Math.PI / 2 + (Math.PI * (s + 1)) / 36;
      neck.push(xc + Math.sin(a) * rx, y, zN + Math.cos(a) * rz, xc + Math.sin(b) * rx, y, zN + Math.cos(b) * rz);
    }
  };
  for (let k = 0; k <= 2; k++) ring(yN - k * 0.27 * H, Wt * 0.52, Wt * 0.5);
  for (let j = -5; j <= 5; j++) {
    const t2 = (j / 5) * (Math.PI / 2) * 0.98;
    neck.push(xc + Math.sin(t2) * Wt * 0.52, yN, zN + Math.cos(t2) * Wt * 0.5, xc + Math.sin(t2) * Wt * 0.52, yN - 0.54 * H, zN + Math.cos(t2) * Wt * 0.5);
  }
  add(new THREE.LineSegments(dynamic(new Float32Array(neck)), lineMat(0.7)));
  const halo: number[] = [];
  const hc = [xc, by(10) - 0.2 * H, bz(168) - 0.6 * H], hr = 1.18 * H;
  for (let s = 0; s < 120; s++) {
    if ((s * 7) % 11 >= 8) continue;
    const t3 = (s / 120) * Math.PI * 2, t4 = ((s + 1) / 120) * Math.PI * 2;
    halo.push(hc[0] + Math.cos(t3) * hr, hc[1] + Math.sin(t3) * hr, hc[2], hc[0] + Math.cos(t4) * hr, hc[1] + Math.sin(t4) * hr, hc[2]);
  }
  add(new THREE.LineSegments(dynamic(new Float32Array(halo)), lineMat(0.8)), root);

  // Frame the head and neck.
  const yTop = by(10) + 0.6 * H, yBot = by(152) - 1.05 * H, yMid = (yTop + yBot) / 2;
  const dist = (yTop - yBot) / 2 / Math.tan((15 * Math.PI) / 180);

  let scan = 0;

  const update = (env: FaceEnv) => {
    const { e, t, dt, ptr } = env;
    const hy = e.hype;
    const open = e.amp * (0.85 + 0.3 * hy) * 0.2 * H;
    const smile = e.smile * (0.5 + 0.5 * Math.min(1, 0.6 + e.amp));
    const brow = e.brow + 0.12 * Math.sin(t * 1.3) * e.amp;
    for (let p = 0; p < N; p++) {
      let x = base[p * 3], y = base[p * 3 + 1], z = base[p * 3 + 2];
      const side = x > xc ? 1 : -1;
      y += -open * jawW[p] + open * 0.16 * upW[p];
      z += -open * 0.18 * jawW[p];
      y += smile * 0.05 * H * smileW[p];
      x += side * (smile * 0.03 * H - open * 0.12) * smileW[p];
      y += brow * 0.05 * H * browW[p];
      pos[p * 3] = x; pos[p * 3 + 1] = y; pos[p * 3 + 2] = z;
    }
    const op = Math.min(1.4, Math.max(0, (e.eye * e.blink) / 0.95));
    for (const [u, l] of LIDS) pos[u * 3 + 1] = base[l * 3 + 1] + (base[u * 3 + 1] - base[l * 3 + 1]) * op;
    for (let o = 0; o < E.length; o += 2) {
      const a = E[o] * 3, b = E[o + 1] * 3, q = o * 3;
      tessArr.set([pos[a], pos[a + 1], pos[a + 2], pos[b], pos[b + 1], pos[b + 2]], q);
    }
    for (let o = 0; o < K.length; o += 2) {
      const a = K[o] * 3, b = K[o + 1] * 3, q = o * 3;
      contArr.set([pos[a], pos[a + 1], pos[a + 2], pos[b], pos[b + 1], pos[b + 2]], q);
    }
    tessGeo.attributes.position.needsUpdate = true;
    contGeo.attributes.position.needsUpdate = true;
    ptGeo.attributes.position.needsUpdate = true;
    [468, 473].forEach((k, n) => {
      eyeArr[n * 3] = pos[k * 3] + e.lx * 0.012 * H;
      eyeArr[n * 3 + 1] = pos[k * 3 + 1] + e.ly * 0.01 * H;
      eyeArr[n * 3 + 2] = pos[k * 3 + 2] + 0.02 * H;
    });
    eyeGeo.attributes.position.needsUpdate = true;
    const vis = sm(0.12, 0.5, op), fl = 0.9 + 0.1 * Math.sin(t * 31) + 0.25 * hy * Math.sin(t * 57);
    eyeGlow.uniforms.uA.value = vis * fl * 0.9;
    eyeCore.uniforms.uA.value = vis;

    // Cursor parallax, idle drift, hype bob and the burst shake.
    const shake = Math.max(0, 1 - e.burst / 0.9);
    pivot.rotation.y = ptr.x * 0.45 + Math.sin(t * 0.4) * 0.05 + e.lx * 0.05;
    pivot.rotation.x = ptr.y * 0.2 + Math.sin(t * 0.5) * 0.025 - e.ly * 0.04;
    pivot.rotation.z = hy * 0.05 * Math.sin(t * 4.2);
    pivot.position.y = hy * 0.03 * H * Math.abs(Math.sin(t * 8.5)) + shake * 0.02 * H * Math.sin(t * 70);
    pivot.position.x = shake * 0.015 * H * Math.sin(t * 61);

    // A scan band sweeps up the face, faster while Jarvis is working.
    scan = (scan + dt * (env.mode === "thinking" ? 0.7 : 0.3)) % 1.25;
    U.uScan.value = yBot + (yTop - yBot) * (1.25 - scan) - 0.15 * (yTop - yBot);
    U.uT.value = t;
    U.uCol.value.copy(env.color);
  };

  return {
    root,
    camera: { fov: 30, pos: [xc, yMid, bz(168) + dist], look: [xc, yMid, 0] },
    bloom: 0.9,
    lit: false,
    update,
    dispose: () => disposeTree(root),
  };
}
