import * as THREE from "three";
import { aim, disposeTree, gs, lights, liveCanvas, neck, sm } from "./helpers";
import type { Face, FaceEnv } from "./types";

/*
 * Five robot heads that share one contract: build a root, then every frame
 * read the eased expression (eyes, brows, smile, gaze, hype) and the real voice
 * level (`e.amp`) and move the face to match.
 */

// Pulled back and lifted so the head clears the caption and prompt below it.
const CAMERA: Face["camera"] = { fov: 27, pos: [0, -0.05, 7.6], look: [0, -0.3, 0] };

function finish(root: THREE.Group, update: (env: FaceEnv) => void, bloom: number): Face {
  return { root, camera: CAMERA, bloom, lit: true, update, dispose: () => disposeTree(root) };
}

/* ───────────── android: a human-shaped head with a crimson face and gold cowl ───────────── */

const HX = 0.76, HY = 1.05, HZ = 0.86;
const taper = (y: number) => (y < -0.2 ? Math.min(0.3, (-0.2 - y) * 0.36) : 0);
function feat(x: number, y: number) {
  const ax = Math.abs(x);
  return (
    0.05 * gs(ax, y, 0.25, 0.36, 0.3, 0.05) - 0.085 * gs(ax, y, 0.3, 0.17, 0.13, 0.085) +
    0.1 * gs(x, y, 0, 0.05, 0.045, 0.2) + 0.15 * gs(x, y, 0, -0.2, 0.075, 0.06) + 0.06 * gs(ax, y, 0.115, -0.19, 0.05, 0.05) -
    0.03 * gs(x, y, 0, -0.28, 0.1, 0.03) + 0.075 * gs(x, y, 0, -0.405, 0.15, 0.03) + 0.07 * gs(x, y, 0, -0.545, 0.14, 0.035) -
    0.055 * gs(x, y, 0, -0.47, 0.19, 0.012) + 0.08 * gs(x, y, 0, -0.8, 0.14, 0.1) + 0.05 * gs(ax, y, 0.4, -0.02, 0.14, 0.12) -
    0.03 * gs(ax, y, 0.4, -0.38, 0.13, 0.15) + 0.03 * gs(x, y, 0, 0.65, 0.4, 0.25)
  );
}
const tc = new THREE.Color();
const cGold = new THREE.Color(0.66, 0.48, 0.18);
const cDeep = new THREE.Color(0.38, 0.05, 0.09);
function paint(x: number, y: number, uz: number) {
  const front = uz > 0 ? 1 : 0;
  const lip = Math.max(gs(x, y, 0, -0.405, 0.12, 0.026), gs(x, y, 0, -0.545, 0.11, 0.03)) * front;
  const sock = gs(Math.abs(x), y, 0.3, 0.17, 0.14, 0.09) * front;
  const groove = gs(x, y, 0, -0.47, 0.2, 0.012) * front;
  return tc.setRGB(0.62, 0.1, 0.14).lerp(cGold, sm(0.5, 0.64, y)).lerp(cDeep, lip * 0.55 + sock * 0.35 + groove * 0.4);
}

function makeHead(dirs: ArrayLike<number>, k: number) {
  const n = dirs.length / 3;
  const base = new Float32Array(n * 3), col = new Float32Array(n * 3), pos = new Float32Array(n * 3);
  const jawI: number[] = [], jawW: number[] = [], upI: number[] = [], upW: number[] = [];
  const coI: number[] = [], coW: number[] = [], coS: number[] = [];
  const surf = (x: number, y: number) => {
    const sx = HX * (1 - taper(y));
    const v = 1 - (x / sx) * (x / sx) - (y / HY) * (y / HY);
    return HZ * Math.sqrt(Math.max(0.01, v)) + k * feat(x, y);
  };
  for (let i = 0; i < n; i++) {
    const ux = -dirs[i * 3 + 2], uy = dirs[i * 3 + 1], uz = dirs[i * 3]; // the seam goes to the back of the head
    const x = ux * HX * (1 - taper(uy * HY)), y = uy * HY;
    let z = uz * HZ;
    if (uz > 0) z += k * feat(x, y) * sm(0, 0.3, uz);
    base.set([x, y, z], i * 3);
    const c = paint(x, y, uz);
    col.set([c.r, c.g, c.b], i * 3);
    if (uz > 0.1) {
      const wj = sm(-0.42, -0.64, y) * (1 - sm(0.42, 0.66, Math.abs(x)));
      if (wj > 0.001) { jawI.push(i); jawW.push(wj); }
      const wu = gs(x, y, 0, -0.41, 0.2, 0.035);
      if (wu > 0.03) { upI.push(i); upW.push(wu); }
      const wc = gs(Math.abs(x), y, 0.17, -0.47, 0.1, 0.06);
      if (wc > 0.03) { coI.push(i); coW.push(wc); coS.push(x < 0 ? -1 : 1); }
    }
  }
  pos.set(base);
  return {
    pos, col, surf,
    apply(a: number, w: number, smile: number) {
      pos.set(base);
      for (let j = 0; j < jawI.length; j++) { const i3 = jawI[j] * 3; pos[i3 + 1] -= a * 0.2 * jawW[j]; pos[i3 + 2] -= a * 0.035 * jawW[j]; }
      for (let j = 0; j < upI.length; j++) pos[upI[j] * 3 + 1] += a * 0.018 * upW[j];
      for (let j = 0; j < coI.length; j++) { const i3 = coI[j] * 3; pos[i3] += (w - 1) * 0.05 * coW[j] * coS[j]; pos[i3 + 1] += smile * 0.055 * coW[j]; }
    },
  };
}

export function androidFace(): Face {
  const root = new THREE.Group();
  const g = new THREE.Group();
  root.add(g);
  const sphere = new THREE.SphereGeometry(1, 96, 72);
  const head = makeHead(sphere.attributes.position.array, 0.8);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(head.pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(head.col, 3));
  geo.setIndex(sphere.index);
  geo.computeVertexNormals();
  sphere.dispose();
  g.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.4, metalness: 0.25, envMapIntensity: 0.9 })));
  const collar = neck(g, -1.35);
  const gy = 0.72, gz = head.surf(0, gy);
  const gem = new THREE.Mesh(new THREE.SphereGeometry(0.07, 20, 16), new THREE.MeshBasicMaterial({ color: 0xffe27a }));
  gem.scale.z = 0.7;
  gem.position.set(0, gy, gz + 0.03);
  const gemRing = new THREE.Mesh(new THREE.RingGeometry(0.07, 0.085, 32), new THREE.MeshBasicMaterial({ color: 0x3a0a0f }));
  gemRing.position.set(0, gy, gz + 0.02);
  g.add(gem, gemRing);

  const eyes = ([-1, 1] as const).map((s) => {
    const ex = 0.3 * s, ey = 0.17;
    const eroot = new THREE.Group();
    eroot.position.set(ex, ey, head.surf(ex, ey) - 0.045);
    g.add(eroot);
    const look = new THREE.Group();
    eroot.add(look);
    look.add(new THREE.Mesh(new THREE.SphereGeometry(0.105, 24, 16), new THREE.MeshStandardMaterial({ color: 0xe6f0ff, roughness: 0.3 })));
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.04, 0.056, 28), new THREE.MeshBasicMaterial({ color: 0x6fd8ff }));
    const pupil = new THREE.Mesh(new THREE.CircleGeometry(0.03, 20), new THREE.MeshBasicMaterial({ color: 0x03060c }));
    ring.position.z = 0.0975;
    pupil.position.z = 0.0985;
    look.add(ring, pupil);
    const lidMat = new THREE.MeshStandardMaterial({ color: 0x9a1f2a, roughness: 0.4, metalness: 0.2 });
    const up = new THREE.Mesh(new THREE.SphereGeometry(0.118, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2), lidMat);
    const lo = new THREE.Mesh(new THREE.SphereGeometry(0.118, 24, 12, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2), lidMat);
    eroot.add(up, lo);
    return { look, ring, up, lo };
  });
  const brows = ([-1, 1] as const).map((s) => {
    const m = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 10), new THREE.MeshStandardMaterial({ color: 0x4a0a12, roughness: 0.5 }));
    m.scale.set(0.16, 0.018, 0.03);
    g.add(m);
    return { m, s };
  });
  const mouth = new THREE.Mesh(new THREE.CircleGeometry(1, 32), new THREE.MeshBasicMaterial({ color: 0x14030a }));
  g.add(mouth);
  const rim = lights(root, 0x6fd8ff);

  return finish(root, (env) => {
    const { e, t, color } = env;
    aim(g, env);
    head.apply(e.amp, e.wide, e.smile);
    geo.attributes.position.needsUpdate = true;
    geo.computeVertexNormals();
    const ev = Math.min(1.15, Math.max(0, e.eye * e.blink));
    for (const eye of eyes) {
      eye.look.rotation.set(-e.ly * 0.35, e.lx * 0.4, 0);
      (eye.ring.material as THREE.MeshBasicMaterial).color.copy(color);
      eye.up.rotation.x = -0.5 + (1 - ev) * 1.95;
      eye.lo.rotation.x = 0.35 - (1 - Math.min(1, ev)) * 1.8;
    }
    for (const b of brows) {
      const x = b.s * 0.3, y = 0.36 + e.brow * 0.07;
      b.m.position.set(x, y, head.surf(x, y) + 0.012);
      b.m.rotation.z = -b.s * e.tilt * 0.45 + b.s * e.brow * 0.08;
    }
    const top = -0.462 + e.amp * 0.02, bot = -0.468 - e.amp * 0.1 * (0.8 + 0.2 * Math.sin(t * 24));
    mouth.scale.set(0.09 + 0.06 * e.wide, Math.max(0.003, (top - bot) / 2), 1);
    mouth.position.set(0, (top + bot) / 2, head.surf(0, -0.47) + 0.045);
    (gem.material as THREE.MeshBasicMaterial).color.setHex(0xffe27a).lerp(color, 0.35 + 0.15 * Math.sin(t * 2));
    (collar.material as THREE.MeshBasicMaterial).color.copy(color);
    rim.color.copy(color);
  }, 0.2);
}

/* ───────────── screen droid: a chrome head with a glass screen for a face ───────────── */

export function screenFace(): Face {
  const root = new THREE.Group();
  const g = new THREE.Group();
  root.add(g);
  const hs = new THREE.Vector3(0.9, 1.06, 0.84);
  const head = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 48), new THREE.MeshStandardMaterial({ color: 0x38335a, metalness: 0.85, roughness: 0.25, envMapIntensity: 1.3 }));
  head.scale.copy(hs);
  g.add(head);
  const { cv, cx, tex } = liveCanvas(512, 512);
  const screen = new THREE.Mesh(
    new THREE.SphereGeometry(1.012, 48, 32, Math.PI / 2 - 0.78, 1.56, Math.PI / 2 - 0.66, 1.32),
    new THREE.MeshBasicMaterial({ map: tex }),
  );
  screen.scale.copy(hs);
  g.add(screen);
  const rings = ([-1, 1] as const).map((s) => {
    const r = new THREE.Mesh(new THREE.TorusGeometry(0.2, 0.025, 10, 40), new THREE.MeshBasicMaterial({ color: 0x6fd8ff }));
    r.rotation.y = Math.PI / 2;
    r.position.set(s * 0.96, 0, -0.02);
    const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 0.1, 28), new THREE.MeshStandardMaterial({ color: 0x241f40, metalness: 0.9, roughness: 0.3 }));
    cap.rotation.z = Math.PI / 2;
    cap.position.set(s * 0.92, 0, -0.02);
    g.add(r, cap);
    return r;
  });
  const collar = neck(g, -1.35);
  const rim = lights(root, 0x6fd8ff);
  const W = cv.width;

  const draw = (env: FaceEnv) => {
    const { e, t } = env;
    const col = `#${env.color.getHexString()}`;
    const hy = e.hype, x = cx;
    x.shadowBlur = 0;
    x.globalAlpha = 1;
    x.fillStyle = "#02030a";
    x.fillRect(0, 0, W, W);
    const gr = x.createRadialGradient(256, 230, 20, 256, 230, 330);
    gr.addColorStop(0, "rgba(40,50,90,0.45)");
    gr.addColorStop(1, "rgba(0,0,0,0)");
    x.fillStyle = gr;
    x.fillRect(0, 0, W, W);
    x.shadowColor = col; x.shadowBlur = 28; x.strokeStyle = col; x.fillStyle = col; x.lineCap = "round"; x.lineJoin = "round";
    const ev = Math.min(1.25, Math.max(0.06, e.eye * e.blink));
    const happy = e.smile > 0.5 && hy < 0.5;
    const shx = hy * 5 * Math.sin(t * 47), shy = hy * 4 * Math.sin(t * 39 + 1);
    for (const s of [-1, 1]) {
      const cx0 = 256 + s * (112 + hy * 10) + e.lx * 26 + shx, cy0 = 190 - e.ly * 22 + shy;
      x.save();
      x.translate(cx0, cy0);
      x.rotate(-s * e.tilt * 0.35);
      if (hy > 0.5) {
        const pr = 1 + 0.12 * Math.sin(t * 14);
        x.beginPath(); x.ellipse(0, 0, 54 * pr, 66 * ev * pr, 0, 0, Math.PI * 2); x.fill();
        x.shadowBlur = 0; x.fillStyle = "#fff";
        x.beginPath(); x.ellipse(-8 * s, -6, 20, 26 * ev, 0, 0, Math.PI * 2); x.fill();
        x.fillStyle = col; x.shadowBlur = 28;
      } else if (happy) {
        x.lineWidth = 22; x.beginPath(); x.arc(0, 18, 44, Math.PI * 1.08, Math.PI * 1.92); x.stroke();
      } else {
        x.beginPath(); x.ellipse(0, 0, 44, 56 * ev, 0, 0, Math.PI * 2); x.fill();
      }
      x.restore();
      x.lineWidth = 12;
      x.beginPath();
      const by = 110 - e.brow * 30 + (e.tilt > 0 ? e.tilt * 12 : 0);
      x.moveTo(cx0 - 48, by + s * e.tilt * 12);
      x.lineTo(cx0 + 48, by - s * e.tilt * 12);
      x.stroke();
    }
    // The mouth is a voice equalizer that curves into a smile.
    const n = 17, bw = 15, gap = 9, total = n * bw + (n - 1) * gap, x0 = 256 - total / 2;
    for (let i = 0; i < n; i++) {
      const u = (i / (n - 1)) * 2 - 1, bell = 1 - u * u;
      let h = 8 + e.amp * bell * 120 * (0.65 + 0.35 * Math.sin(t * 22 + i * 1.9));
      const cy2 = 360 - e.smile * u * u * (40 + hy * 36);
      if (hy > 0.3) h += hy * 26 * bell;
      x.fillRect(x0 + i * (bw + gap), cy2 - h / 2, bw, h);
    }
    if (hy > 0.3) {
      for (let q = 0; q < 6; q++) {
        const ph = t * 3 + q * 1.7, sz = 6 + 8 * Math.abs(Math.sin(ph));
        const px = 256 + Math.cos(q * 1.05 + 0.4) * (205 + 12 * Math.sin(ph)), py = 170 + Math.sin(q * 1.05 + 0.4) * 120;
        x.save(); x.translate(px, py); x.rotate(ph); x.globalAlpha = hy * (0.4 + 0.6 * Math.abs(Math.sin(ph)));
        x.fillRect(-sz, -2, sz * 2, 4); x.fillRect(-2, -sz, 4, sz * 2); x.restore();
      }
      x.globalAlpha = hy * 0.18;
      for (let yy = (t * 120) % 24; yy < W; yy += 24) x.fillRect(0, yy, W, 3);
      x.globalAlpha = 1;
    }
    // A flash and a catchphrase the moment Hype is switched on.
    const bt = e.burst;
    if (bt >= 0 && bt < 1.1) {
      x.shadowBlur = 0;
      x.fillStyle = `rgba(255,255,255,${0.85 * Math.max(0, 1 - bt / 0.35)})`;
      x.fillRect(0, 0, W, W);
      if (bt > 0.05) {
        x.globalAlpha = Math.min(1, (1.1 - bt) * 2.5); x.fillStyle = "#fff"; x.shadowColor = col; x.shadowBlur = 24;
        x.font = `900 ${Math.round(66 + 22 * Math.max(0, 1 - bt * 3))}px Impact, 'Arial Black', sans-serif`;
        x.textAlign = "center"; x.fillText("LET'S GOOO", 256, 290); x.globalAlpha = 1;
      }
    }
    x.shadowBlur = 0;
    tex.needsUpdate = true;
  };

  return finish(root, (env) => {
    aim(g, env);
    g.position.y += Math.max(0, 0.6 - env.e.burst) * 0.02 * Math.sin(env.t * 70); // shake on the hype burst
    draw(env);
    for (const r of rings) (r.material as THREE.MeshBasicMaterial).color.copy(env.color);
    (collar.material as THREE.MeshBasicMaterial).color.copy(env.color);
    rim.color.copy(env.color);
  }, 0.4);
}

/* ───────────── visor: a white helmet with one light bar behind a dark visor ───────────── */

export function visorFace(): Face {
  const root = new THREE.Group();
  const g = new THREE.Group();
  root.add(g);
  const hs = new THREE.Vector3(0.9, 1.06, 0.84);
  const head = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 48), new THREE.MeshStandardMaterial({ color: 0xdfe4f6, metalness: 0.5, roughness: 0.2, envMapIntensity: 1.1 }));
  head.scale.copy(hs);
  g.add(head);
  const { cv, cx, tex } = liveCanvas(512, 224);
  const vis = new THREE.Mesh(
    new THREE.SphereGeometry(1.012, 56, 20, Math.PI / 2 - 0.85, 1.7, Math.PI / 2 - 0.4, 0.6),
    new THREE.MeshBasicMaterial({ map: tex }),
  );
  vis.scale.copy(hs);
  g.add(vis);
  const caps = ([-1, 1] as const).map((s) => {
    const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.24, 0.24, 0.1, 28), new THREE.MeshStandardMaterial({ color: 0xaab2cc, metalness: 0.8, roughness: 0.25 }));
    cap.rotation.z = Math.PI / 2;
    cap.position.set(s * 0.92, 0, -0.02);
    const r = new THREE.Mesh(new THREE.TorusGeometry(0.14, 0.014, 8, 36), new THREE.MeshBasicMaterial({ color: 0x6fd8ff }));
    r.rotation.y = Math.PI / 2;
    r.position.set(s * 0.975, 0, -0.02);
    g.add(cap, r);
    return r;
  });
  const collar = neck(g, -1.35);
  const rim = lights(root, 0x6fd8ff);

  return finish(root, (env) => {
    const { e, t } = env;
    aim(g, env);
    const W = cv.width, H = cv.height, x = cx, col = `#${env.color.getHexString()}`;
    x.shadowBlur = 0;
    const gr = x.createLinearGradient(0, 0, 0, H);
    gr.addColorStop(0, "#04050d");
    gr.addColorStop(1, "#0c0f20");
    x.fillStyle = gr;
    x.fillRect(0, 0, W, H);
    x.shadowColor = col; x.shadowBlur = 28; x.strokeStyle = col; x.lineCap = "round"; x.lineJoin = "round";
    x.lineWidth = Math.max(3, (10 + 22 * Math.min(1.15, e.eye * e.blink)) * 0.6);
    x.beginPath();
    for (let i = 0; i <= 80; i++) {
      const u = (i / 80) * 2 - 1, px = W / 2 + u * 190 + e.lx * 34;
      const y = 112 - e.ly * 24 - e.smile * u * u * 52 + e.tilt * (1 - Math.abs(u)) * 16 + Math.sin(u * 15 + t * 18) * e.amp * 38 * (1 - u * u);
      if (i === 0) x.moveTo(px, y); else x.lineTo(px, y);
    }
    x.stroke();
    x.shadowBlur = 0;
    tex.needsUpdate = true;
    for (const r of caps) (r.material as THREE.MeshBasicMaterial).color.copy(env.color);
    (collar.material as THREE.MeshBasicMaterial).color.copy(env.color);
    rim.color.copy(env.color);
  }, 0.12);
}

/* ───────────── orb face: the orb with a face drawn in light ───────────── */

export function orbFace(): Face {
  const root = new THREE.Group();
  const g = new THREE.Group();
  root.add(g);
  const shellMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { col: { value: new THREE.Color(0x6fd8ff) } },
    vertexShader: "varying vec3 n; varying vec3 v; void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0); n = normalize(normalMatrix*normal); v = normalize(-mv.xyz); gl_Position = projectionMatrix*mv; }",
    fragmentShader: "uniform vec3 col; varying vec3 n; varying vec3 v; void main(){ float f = pow(1.0 - max(dot(n,v),0.0), 2.4); gl_FragColor = vec4(col, f*0.9 + 0.05); }",
  });
  g.add(new THREE.Mesh(new THREE.SphereGeometry(1.1, 64, 48), shellMat));
  const N = 2600, pa = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    const y = 1 - Math.random() * 2, r = Math.sqrt(1 - y * y), th = Math.random() * Math.PI * 2, rad = 0.55 + Math.random() * 0.4;
    pa.set([Math.cos(th) * r * rad, y * rad, Math.sin(th) * r * rad], i * 3);
  }
  const pg = new THREE.BufferGeometry();
  pg.setAttribute("position", new THREE.BufferAttribute(pa, 3));
  const pts = new THREE.Points(pg, new THREE.PointsMaterial({ color: 0x6fd8ff, size: 0.016, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false }));
  g.add(pts);
  const { cv, cx, tex } = liveCanvas(512, 512);
  g.add(new THREE.Mesh(
    new THREE.SphereGeometry(1.02, 48, 36, Math.PI / 2 - 0.8, 1.6, Math.PI / 2 - 0.7, 1.4),
    new THREE.MeshBasicMaterial({ map: tex, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }),
  ));
  const rings = [0, 1].map((k) => {
    const r = new THREE.Mesh(new THREE.TorusGeometry(1.32 + k * 0.1, 0.008, 6, 96), new THREE.MeshBasicMaterial({ color: 0x6fd8ff, transparent: true, opacity: 0.55 }));
    r.rotation.x = 1.2 - k * 0.5;
    r.rotation.y = k * 0.6;
    g.add(r);
    return r;
  });

  return {
    root, camera: CAMERA, bloom: 0.85, lit: false,
    update(env) {
      const { e, t, color } = env;
      aim(g, env);
      const x = cx, col = `#${color.getHexString()}`, W = cv.width;
      x.clearRect(0, 0, W, W);
      x.shadowColor = col; x.shadowBlur = 26; x.strokeStyle = col; x.fillStyle = col; x.lineCap = "round"; x.lineJoin = "round";
      const ev = Math.min(1.15, Math.max(0.06, e.eye * e.blink)), happy = e.smile > 0.5;
      for (const s of [-1, 1]) {
        x.save();
        x.translate(256 + s * 108 + e.lx * 22, 205 - e.ly * 18);
        x.rotate(-s * e.tilt * 0.3);
        x.lineWidth = 11;
        x.beginPath();
        if (happy) x.arc(0, 14, 40, Math.PI * 1.08, Math.PI * 1.92);
        else x.ellipse(0, 0, 40, 40 * ev, 0, 0, Math.PI * 2);
        x.stroke();
        if (!happy) { x.beginPath(); x.ellipse(e.lx * 8, -e.ly * 6, 13, 13 * ev, 0, 0, Math.PI * 2); x.fill(); }
        x.restore();
      }
      // The mouth is a lens that opens with the voice and curves into a smile.
      const mw = 70 + 26 * e.wide, gap = 3 + e.amp * 52 * (0.8 + 0.2 * Math.sin(t * 24)), my = 345, sm2 = e.smile * 42;
      x.lineWidth = 9;
      x.beginPath();
      x.moveTo(256 - mw, my - sm2);
      x.quadraticCurveTo(256, my - gap / 2 + sm2 * 0.9, 256 + mw, my - sm2);
      x.quadraticCurveTo(256, my + gap / 2 + sm2 * 0.9, 256 - mw, my - sm2);
      x.stroke();
      x.shadowBlur = 0;
      tex.needsUpdate = true;
      shellMat.uniforms.col.value.copy(color);
      (pts.material as THREE.PointsMaterial).color.copy(color);
      pts.rotation.y = t * 0.12;
      pts.rotation.x = Math.sin(t * 0.3) * 0.15;
      rings.forEach((r, k) => {
        (r.material as THREE.MeshBasicMaterial).color.copy(color);
        r.rotation.z = t * (0.25 + k * 0.15) * (k ? -1 : 1);
      });
    },
    dispose: () => disposeTree(root),
  };
}

/* ───────────── sentinel: a faceted gunmetal head with slit eyes and a vented mouth ───────────── */

const zF = (x: number, y: number) => 0.86 * Math.sqrt(Math.max(0.02, 1 - (x / 0.82) * (x / 0.82) - (y / 1.12) * (y / 1.12)));

export function sentinelFace(): Face {
  const root = new THREE.Group();
  const g = new THREE.Group();
  root.add(g);
  const head = new THREE.Mesh(new THREE.IcosahedronGeometry(1, 2), new THREE.MeshStandardMaterial({ color: 0x59607c, metalness: 0.85, roughness: 0.32, flatShading: true, envMapIntensity: 1.3 }));
  head.scale.set(0.82, 1.12, 0.86);
  g.add(head);
  const slits = ([-1, 1] as const).map((s) => {
    const sh = new THREE.Shape();
    sh.moveTo(-0.17 * s, 0.045); sh.lineTo(0.17 * s, -0.01); sh.lineTo(0.17 * s, -0.05); sh.lineTo(-0.17 * s, -0.005); sh.closePath();
    const m = new THREE.Mesh(new THREE.ShapeGeometry(sh), new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide }));
    const halo = new THREE.Mesh(new THREE.ShapeGeometry(sh), new THREE.MeshBasicMaterial({ color: 0x6fd8ff, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
    const brow = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.05, 0.08), new THREE.MeshStandardMaterial({ color: 0x2a2e42, metalness: 0.9, roughness: 0.3 }));
    g.add(m, halo, brow);
    return { m, halo, brow, s };
  });
  const plate = new THREE.Mesh(new THREE.BoxGeometry(0.62, 0.26, 0.05), new THREE.MeshStandardMaterial({ color: 0x14172a, metalness: 0.9, roughness: 0.4 }));
  plate.position.set(0, -0.5, zF(0, -0.5) + 0.03);
  g.add(plate);
  const bars = Array.from({ length: 11 }, () => {
    const bar = new THREE.Mesh(new THREE.BoxGeometry(0.03, 1, 0.03), new THREE.MeshBasicMaterial({ color: 0x6fd8ff }));
    g.add(bar);
    return bar;
  });
  const ridge = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.36, 0.07), new THREE.MeshStandardMaterial({ color: 0x2a2e42, metalness: 0.9, roughness: 0.3 }));
  ridge.position.set(0, -0.02, zF(0, -0.02) + 0.04);
  const ant = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.4, 8), new THREE.MeshStandardMaterial({ color: 0x8a90ac, metalness: 0.9, roughness: 0.3 }));
  ant.position.set(0.28, 1.28, 0);
  ant.rotation.z = -0.2;
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.035, 12, 10), new THREE.MeshBasicMaterial({ color: 0x6fd8ff }));
  tip.position.set(0.32, 1.48, 0);
  g.add(ridge, ant, tip);
  const ears = ([-1, 1] as const).map((s) => {
    const c2 = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.1, 6), new THREE.MeshStandardMaterial({ color: 0x2a2e42, metalness: 0.9, roughness: 0.3 }));
    c2.rotation.z = Math.PI / 2;
    c2.position.set(s * 0.82, 0.05, -0.02);
    const r = new THREE.Mesh(new THREE.TorusGeometry(0.11, 0.012, 8, 6), new THREE.MeshBasicMaterial({ color: 0x6fd8ff }));
    r.rotation.y = Math.PI / 2;
    r.position.set(s * 0.875, 0.05, -0.02);
    g.add(c2, r);
    return r;
  });
  const collar = neck(g, -1.4);
  const rim = lights(root, 0x6fd8ff);
  const ec = new THREE.Color();

  return finish(root, (env) => {
    const { e, t, color } = env;
    aim(g, env);
    const ev = Math.min(1.2, Math.max(0.05, (0.35 + e.eye * 0.8) * e.blink));
    ec.set(0xffffff).lerp(color, 0.4);
    for (const sl of slits) {
      const x = sl.s * 0.3 + e.lx * 0.02, y = 0.22 + e.ly * 0.02, z = zF(x, y) + 0.05;
      const rz = -sl.s * e.tilt * 0.35 + sl.s * e.brow * 0.12;
      sl.m.position.set(x, y, z); sl.halo.position.set(x, y, z - 0.004);
      sl.m.rotation.z = rz; sl.halo.rotation.z = rz;
      sl.m.scale.set(1, ev, 1); sl.halo.scale.set(1.25, ev * 2.2, 1);
      (sl.m.material as THREE.MeshBasicMaterial).color.copy(ec);
      (sl.halo.material as THREE.MeshBasicMaterial).color.copy(color);
      const by = 0.4 + e.brow * 0.07;
      sl.brow.position.set(x, by, zF(x, by) + 0.05);
      sl.brow.rotation.z = -sl.s * e.tilt * 0.45 + sl.s * e.brow * 0.1;
    }
    bars.forEach((bar, i) => {
      const u = (i / 10) * 2 - 1;
      const h = 0.03 + e.amp * (1 - u * u) * 0.2 * (0.7 + 0.3 * Math.sin(t * 22 + i * 1.7));
      bar.scale.y = h;
      bar.position.set(u * 0.26, -0.5 - e.smile * u * u * 0.03, zF(u * 0.26, -0.5) + 0.065);
      (bar.material as THREE.MeshBasicMaterial).color.copy(color);
    });
    (tip.material as THREE.MeshBasicMaterial).color.copy(color);
    tip.scale.setScalar(0.8 + 0.3 * Math.sin(t * 3));
    for (const r of ears) (r.material as THREE.MeshBasicMaterial).color.copy(color);
    (collar.material as THREE.MeshBasicMaterial).color.copy(color);
    rim.color.copy(color);
  }, 0.4);
}
