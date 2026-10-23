import { useEffect, useRef } from "react";
import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { audio } from "../lib/audio";
import { useStore, type Mode } from "../lib/store";
import { THEMES } from "../lib/themes";

/*
 * The reactor: a noise-displaced particle shell around a glowing core,
 * wrapped in tilted HUD rings that orbit at different speeds. Every state
 * has a target "pose" (colour, spin, turbulence, spiral, sonar) and the
 * scene eases toward it each frame, so transitions are always smooth.
 *
 *   idle       slow cyan breathing, rings drifting
 *   listening  rings speed up, sonar pulses, shell ripples with your voice
 *   thinking   accent-coloured spiral vortex, counter-rotating rings
 *   speaking   shell and core pulse with Jarvis's voice
 *   confirm    alert-coloured, slow heavy pulse
 */

const NOISE = /* glsl */ `
vec3 mod289(vec3 x){return x-floor(x*(1./289.))*289.;}
vec4 mod289(vec4 x){return x-floor(x*(1./289.))*289.;}
vec4 permute(vec4 x){return mod289(((x*34.)+1.)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1./6.,1./3.);const vec4 D=vec4(0.,.5,1.,2.);
  vec3 i=floor(v+dot(v,C.yyy));vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz);vec3 l=1.-g;vec3 i1=min(g.xyz,l.zxy);vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx;vec3 x2=x0-i2+C.yyy;vec3 x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.,i1.z,i2.z,1.))+i.y+vec4(0.,i1.y,i2.y,1.))+i.x+vec4(0.,i1.x,i2.x,1.));
  float n_=.142857142857;vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.*floor(p*ns.z*ns.z);vec4 x_=floor(j*ns.z);vec4 y_=floor(j-7.*x_);
  vec4 x=x_*ns.x+ns.yyyy;vec4 y=y_*ns.x+ns.yyyy;vec4 h=1.-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy);vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.+1.;vec4 s1=floor(b1)*2.+1.;vec4 sh=-step(h,vec4(0.));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x);vec3 p1=vec3(a0.zw,h.y);vec3 p2=vec3(a1.xy,h.z);vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
  vec4 m=max(.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.);m=m*m;
  return 42.*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}`;

const SHELL_VERT = /* glsl */ `
${NOISE}
attribute float aSeed;
uniform float uTime, uAmp, uLevel, uScatter, uSize, uPixelRatio;
varying float vGlow;
void main(){
  vec3 dir = normalize(position);
  float n = snoise(dir * 1.7 + vec3(0., uTime * .32, uTime * .11));
  float ripple = snoise(dir * 3.4 + uTime * 1.6) * uLevel * .42;
  float r = 1. + n * uAmp + ripple + uScatter * aSeed * aSeed * 1.8;
  vec4 mv = modelViewMatrix * vec4(dir * r, 1.);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = uSize * uPixelRatio * (.55 + aSeed * .9) / -mv.z;
  vGlow = smoothstep(-.5, .7, n) * .7 + .3;
}`;

const SHELL_FRAG = /* glsl */ `
uniform vec3 uColor, uDeep;
uniform float uIntensity;
varying float vGlow;
void main(){
  float d = length(gl_PointCoord - .5);
  float a = smoothstep(.5, .05, d);
  vec3 c = mix(uDeep, uColor, vGlow);
  gl_FragColor = vec4(c * uIntensity * a * .5, a * uIntensity);
}`;

const SPIRAL_VERT = /* glsl */ `
attribute float aSeed;
uniform float uSize, uPixelRatio, uTime;
varying float vSeed;
void main(){
  vec4 mv = modelViewMatrix * vec4(position, 1.);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = uSize * uPixelRatio * (.4 + aSeed) / -mv.z * (.8 + .4 * sin(uTime * 4. + aSeed * 40.));
  vSeed = aSeed;
}`;

const SPIRAL_FRAG = /* glsl */ `
uniform vec3 uColor;
uniform float uOpacity;
varying float vSeed;
void main(){
  float d = length(gl_PointCoord - .5);
  float a = smoothstep(.5, 0., d) * uOpacity;
  gl_FragColor = vec4(uColor * a, a);
}`;

interface Pose {
  spin: number;
  amp: number;
  scatter: number;
  spiral: number;
  sonar: number;
  intensity: number;
  core: number;
  colorKey: "primary" | "accent" | "alert" | "speak";
}

const POSES: Record<Mode, Pose> = {
  boot: { spin: 0.05, amp: 0.02, scatter: 0.6, spiral: 0, sonar: 0, intensity: 0, core: 0, colorKey: "primary" },
  idle: { spin: 0.14, amp: 0.07, scatter: 0, spiral: 0, sonar: 0, intensity: 0.85, core: 0.9, colorKey: "primary" },
  listening: { spin: 0.55, amp: 0.09, scatter: 0, spiral: 0, sonar: 1, intensity: 1.05, core: 1.1, colorKey: "primary" },
  thinking: { spin: 1.7, amp: 0.13, scatter: 0.1, spiral: 1, sonar: 0, intensity: 1.05, core: 1.25, colorKey: "accent" },
  speaking: { spin: 0.4, amp: 0.05, scatter: 0, spiral: 0, sonar: 0, intensity: 1.15, core: 1.15, colorKey: "speak" },
  confirm: { spin: 0.22, amp: 0.1, scatter: 0, spiral: 0.25, sonar: 0.5, intensity: 1, core: 1, colorKey: "alert" },
};

function glowTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 256;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.18, "rgba(255,255,255,.75)");
  grad.addColorStop(0.45, "rgba(255,255,255,.18)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 256, 256);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function additive(color: THREE.Color, opacity = 1) {
  return new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
}

/** A ring made of arcs: [startDeg, lengthDeg] pairs. */
function arcRing(radius: number, width: number, arcs: [number, number][], mat: THREE.Material) {
  const g = new THREE.Group();
  for (const [start, len] of arcs) {
    const geo = new THREE.RingGeometry(radius - width / 2, radius + width / 2, 96, 1,
      THREE.MathUtils.degToRad(start), THREE.MathUtils.degToRad(len));
    g.add(new THREE.Mesh(geo, mat));
  }
  return g;
}

function tickRing(radius: number, count: number, len: number, mat: THREE.LineBasicMaterial, every = 0) {
  const pts: number[] = [];
  for (let i = 0; i < count; i++) {
    const a = (i / count) * Math.PI * 2;
    const l = every && i % every === 0 ? len * 2.2 : len;
    pts.push(Math.cos(a) * radius, Math.sin(a) * radius, 0,
      Math.cos(a) * (radius + l), Math.sin(a) * (radius + l), 0);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  return new THREE.LineSegments(geo, mat);
}

export function Reactor({ onActivate }: { onActivate: () => void }) {
  const mount = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = mount.current!;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    const pr = Math.min(window.devicePixelRatio, 2);
    renderer.setPixelRatio(pr);
    renderer.setClearColor(0x000000, 0);
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    camera.position.set(0, 0, 8.4);

    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.8, 0.55, 0.12);
    composer.addPass(bloom);
    composer.addPass(new OutputPass());

    // Live colours, eased toward the target each frame.
    const cur = { color: new THREE.Color("#4fd8ff"), deep: new THREE.Color("#1b6a85") };
    const target = { color: new THREE.Color(), deep: new THREE.Color() };
    const white = new THREE.Color("#e8fbff");

    const root = new THREE.Group();
    scene.add(root);

    // ── particle shell ──────────────────────────────────────────────
    const N = 5200;
    const pos = new Float32Array(N * 3);
    const seed = new Float32Array(N);
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const th = golden * i;
      pos.set([Math.cos(th) * r, y, Math.sin(th) * r], i * 3);
      seed[i] = Math.random();
    }
    const shellGeo = new THREE.BufferGeometry();
    shellGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    shellGeo.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
    const shellU = {
      uTime: { value: 0 }, uAmp: { value: 0.07 }, uLevel: { value: 0 }, uScatter: { value: 0.6 },
      uSize: { value: 26 }, uPixelRatio: { value: pr }, uIntensity: { value: 0 },
      uColor: { value: cur.color }, uDeep: { value: cur.deep },
    };
    const shell = new THREE.Points(shellGeo, new THREE.ShaderMaterial({
      uniforms: shellU, vertexShader: SHELL_VERT, fragmentShader: SHELL_FRAG,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    }));
    root.add(shell);

    // ── core glow ───────────────────────────────────────────────────
    const tex = glowTexture();
    const coreMat = new THREE.SpriteMaterial({ map: tex, color: cur.color, blending: THREE.AdditiveBlending, transparent: true, depthWrite: false });
    const core = new THREE.Sprite(coreMat);
    root.add(core);
    const hotMat = new THREE.SpriteMaterial({ map: tex, color: white, blending: THREE.AdditiveBlending, transparent: true, depthWrite: false });
    const hot = new THREE.Sprite(hotMat);
    root.add(hot);

    // ── rings ───────────────────────────────────────────────────────
    const ringMat = additive(cur.color, 0.85);
    const ringMatDim = additive(cur.color, 0.35);
    const tickMat = new THREE.LineBasicMaterial({ color: cur.color, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false });

    const orbitA = new THREE.Group();
    orbitA.rotation.set(1.18, 0.2, 0);
    const ringA = arcRing(1.42, 0.022, [[0, 96], [126, 84], [236, 104]], ringMat);
    orbitA.add(ringA);

    const orbitB = new THREE.Group();
    orbitB.rotation.set(-0.95, 0.5, 0.3);
    const ringB = tickRing(1.66, 120, 0.05, tickMat, 10);
    orbitB.add(ringB);

    const orbitC = new THREE.Group();
    orbitC.rotation.set(1.48, -0.35, 0);
    const ringC = arcRing(1.92, 0.01, [[10, 150], [200, 120]], ringMatDim);
    orbitC.add(ringC);

    // The outer HUD dial faces the camera.
    const dial = new THREE.Group();
    const dialTicks = tickRing(2.32, 180, 0.04, tickMat, 15);
    const dialArcs = arcRing(2.5, 0.014, [[20, 50], [100, 18], [150, 70], [262, 40], [318, 26]], ringMat);
    const dialInner = arcRing(2.2, 0.006, [[0, 360]], ringMatDim);
    dial.add(dialTicks, dialArcs, dialInner);

    root.add(orbitA, orbitB, orbitC, dial);

    // Orbiters: bright beads riding the tilted rings.
    const beadMat = new THREE.SpriteMaterial({ map: tex, color: white, blending: THREE.AdditiveBlending, transparent: true, depthWrite: false });
    const beads: { sprite: THREE.Sprite; ring: THREE.Object3D; r: number; speed: number; phase: number }[] = [];
    ([[ringA, 1.42, 1.0, 0], [ringA, 1.42, 1.0, Math.PI], [ringC, 1.92, -0.7, 1.3]] as const).forEach(
      ([ring, r, speed, phase]) => {
        const s = new THREE.Sprite(beadMat);
        s.scale.setScalar(0.16);
        ring.add(s);
        beads.push({ sprite: s, ring, r, speed, phase });
      },
    );

    // ── thinking spiral ─────────────────────────────────────────────
    const S = 2600;
    const sp = new Float32Array(S * 3);
    const ss = new Float32Array(S);
    for (let i = 0; i < S; i++) {
      const arm = i % 3;
      const t = Math.random();
      const r = 0.25 + t * 2.1;
      const a = arm * ((Math.PI * 2) / 3) + t * 5.2 + (Math.random() - 0.5) * 0.35 * (1 - t * 0.5);
      sp.set([Math.cos(a) * r, (Math.random() - 0.5) * 0.12 * (1 - t), Math.sin(a) * r], i * 3);
      ss[i] = Math.random();
    }
    const spiralGeo = new THREE.BufferGeometry();
    spiralGeo.setAttribute("position", new THREE.BufferAttribute(sp, 3));
    spiralGeo.setAttribute("aSeed", new THREE.BufferAttribute(ss, 1));
    const spiralU = {
      uSize: { value: 24 }, uPixelRatio: { value: pr }, uTime: { value: 0 },
      uColor: { value: new THREE.Color("#ffb23f") }, uOpacity: { value: 0 },
    };
    const spiral = new THREE.Points(spiralGeo, new THREE.ShaderMaterial({
      uniforms: spiralU, vertexShader: SPIRAL_VERT, fragmentShader: SPIRAL_FRAG,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    }));
    const spiralTilt = new THREE.Group();
    spiralTilt.rotation.set(0.42, 0, 0.12);
    spiralTilt.add(spiral);
    root.add(spiralTilt);

    // ── sonar pulses (listening / confirm) ──────────────────────────
    const sonarMats: THREE.MeshBasicMaterial[] = [];
    const sonars: THREE.Mesh[] = [];
    for (let i = 0; i < 3; i++) {
      const m = additive(cur.color, 0);
      sonarMats.push(m);
      const mesh = new THREE.Mesh(new THREE.RingGeometry(0.995, 1.0, 128), m);
      sonars.push(mesh);
      root.add(mesh);
    }

    // ── background dust ─────────────────────────────────────────────
    const D = 700;
    const dp = new Float32Array(D * 3);
    for (let i = 0; i < D; i++) {
      const r = 4 + Math.random() * 9;
      const u = Math.random() * Math.PI * 2;
      const v = Math.acos(2 * Math.random() - 1);
      dp.set([r * Math.sin(v) * Math.cos(u), r * Math.sin(v) * Math.sin(u), r * Math.cos(v) - 4], i * 3);
    }
    const dustGeo = new THREE.BufferGeometry();
    dustGeo.setAttribute("position", new THREE.BufferAttribute(dp, 3));
    const dustMat = new THREE.PointsMaterial({ color: cur.deep, size: 0.03, transparent: true, opacity: 0.7, blending: THREE.AdditiveBlending, depthWrite: false });
    const dust = new THREE.Points(dustGeo, dustMat);
    scene.add(dust);

    // ── layout & input ──────────────────────────────────────────────
    const resize = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      renderer.setSize(w, h);
      composer.setSize(w, h);
      bloom.resolution.set(w, h);
      camera.aspect = w / h;
      // Keep the whole dial in frame on tall/narrow screens.
      camera.position.z = w / h < 1 ? 8.4 / Math.max(w / h, 0.55) : 8.4;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    const mouse = { x: 0, y: 0 };
    const onMove = (e: PointerEvent) => {
      mouse.x = e.clientX / window.innerWidth - 0.5;
      mouse.y = e.clientY / window.innerHeight - 0.5;
    };
    window.addEventListener("pointermove", onMove);

    // ── animation ───────────────────────────────────────────────────
    const live: Omit<Pose, "colorKey"> & { level: number } = { ...POSES.boot, level: 0 };
    const clock = new THREE.Clock();
    let raf = 0;
    let spinAngle = 0;
    const motion = reduced ? 0.25 : 1;

    const frame = () => {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(clock.getDelta(), 0.05);
      const t = clock.elapsedTime;
      const { mode, server } = useStore.getState();
      const theme = THEMES[server.theme] ?? THEMES.arc;
      const pose = POSES[mode];

      // Targets
      const colorHex =
        pose.colorKey === "accent" ? theme.accent : pose.colorKey === "alert" ? theme.alert : theme.primary;
      target.color.set(colorHex);
      if (pose.colorKey === "speak") target.color.lerp(white, 0.28);
      target.deep.set(theme.deep);

      const k = 1 - Math.exp(-dt * 3.2);
      cur.color.lerp(target.color, k);
      cur.deep.lerp(target.deep, k);
      for (const key of ["spin", "amp", "scatter", "spiral", "sonar", "intensity", "core"] as const) {
        live[key] += (pose[key] - live[key]) * (key === "intensity" && mode !== "boot" ? k * 0.6 : k);
      }
      const rawLevel =
        mode === "listening" ? audio.level("mic") : mode === "speaking" ? audio.level("out") : 0;
      live.level += (rawLevel - live.level) * (1 - Math.exp(-dt * 14));

      // Shell
      shellU.uTime.value = t * motion;
      shellU.uAmp.value = live.amp;
      shellU.uLevel.value = live.level;
      shellU.uScatter.value = live.scatter;
      const breathe = mode === "confirm" ? 0.12 * Math.sin(t * 2.6) : 0.04 * Math.sin(t * 1.3);
      shellU.uIntensity.value = live.intensity * (1 + breathe);

      // Core
      const coreScale = (0.9 + live.level * 1.1 + breathe) * live.core;
      core.scale.setScalar(1.25 * coreScale);
      coreMat.color.copy(cur.color);
      coreMat.opacity = 0.7 * Math.min(1, live.intensity);
      hot.scale.setScalar(0.38 * coreScale);
      hotMat.opacity = 0.85 * Math.min(1, live.intensity);

      // Rings: each orbit turns about its own axis at its own pace.
      spinAngle += dt * live.spin * motion;
      ringA.rotation.z = spinAngle * 1.0;
      ringB.rotation.z = -spinAngle * 0.6;
      ringC.rotation.z = spinAngle * 0.8;
      orbitA.rotation.y = 0.2 + Math.sin(t * 0.21) * 0.25;
      orbitB.rotation.x = -0.95 + Math.sin(t * 0.17) * 0.2;
      orbitC.rotation.y = -0.35 + spinAngle * 0.15;
      dialTicks.rotation.z = -spinAngle * 0.18;
      dialArcs.rotation.z = spinAngle * 0.3;
      const dialScale = 1 + live.level * 0.05 + live.sonar * 0.015 * Math.sin(t * 5);
      dial.scale.setScalar(dialScale);

      ringMat.color.copy(cur.color);
      ringMatDim.color.copy(cur.color);
      tickMat.color.copy(cur.color);
      ringMat.opacity = 0.85 * Math.min(1, live.intensity);
      ringMatDim.opacity = 0.35 * Math.min(1, live.intensity);
      tickMat.opacity = 0.5 * Math.min(1, live.intensity);

      for (const b of beads) {
        const a = b.phase + spinAngle * b.speed * 2.2;
        b.sprite.position.set(Math.cos(a) * b.r, Math.sin(a) * b.r, 0);
      }
      beadMat.opacity = Math.min(1, live.intensity);

      // Spiral
      spiralU.uTime.value = t;
      spiralU.uOpacity.value = live.spiral * 0.9;
      spiralU.uColor.value.copy(cur.color);
      spiral.rotation.y = -t * 1.6 * motion;
      spiral.visible = live.spiral > 0.01;
      shell.rotation.y += dt * live.spin * 0.25 * motion;

      // Sonar: three staggered rings expanding outward.
      sonars.forEach((s, i) => {
        const p = (t * (mode === "confirm" ? 0.35 : 0.6) + i / 3) % 1;
        s.scale.setScalar(1.15 + p * 1.5);
        sonarMats[i].color.copy(cur.color);
        sonarMats[i].opacity = live.sonar * (1 - p) * 0.55;
      });

      dust.rotation.y = t * 0.01;
      dustMat.color.copy(cur.deep);

      bloom.strength = 0.75 + live.level * 0.55;

      // Gentle parallax
      root.rotation.y += (mouse.x * 0.35 - root.rotation.y) * 0.04;
      root.rotation.x += (mouse.y * 0.25 - root.rotation.x) * 0.04;

      composer.render();
    };
    frame();

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("pointermove", onMove);
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        m.geometry?.dispose();
        const mat = m.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
        else mat?.dispose();
      });
      tex.dispose();
      composer.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, []);

  const mode = useStore((s) => s.mode);
  const label =
    mode === "speaking" ? "Stop Jarvis speaking" : mode === "listening" ? "Stop listening" : "Talk to Jarvis";

  return (
    <div className="reactor" ref={mount}>
      <button className="reactor-hit" aria-label={label} title={label} onClick={onActivate} />
    </div>
  );
}
