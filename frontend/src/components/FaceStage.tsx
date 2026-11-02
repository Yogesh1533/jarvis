import { useEffect, useRef } from "react";
import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { Expression } from "../faces/expression";
import { createFace, type FaceId } from "../faces";
import { studioEnvironment } from "../faces/helpers";
import type { Face } from "../faces/types";
import { audio } from "../lib/audio";
import { useStore } from "../lib/store";
import { THEMES } from "../lib/themes";

/*
 * Hosts one of the robot or hologram faces in the same slot as the Reactor.
 * The face can be swapped from Settings without rebuilding the renderer.
 * It reads the assistant's mode, the persona mood and the live voice level,
 * so Jarvis's mouth moves with the audio actually coming out of the speaker.
 */
export function FaceStage({ onActivate }: { onActivate: () => void }) {
  const mount = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = mount.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(27, 1, 0.1, 100);
    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.5, 0.55, 0.12);
    composer.addPass(bloom);
    composer.addPass(new OutputPass());

    const cur = { color: new THREE.Color("#4fd8ff"), deep: new THREE.Color("#1b6a85") };
    const target = { color: new THREE.Color(), deep: new THREE.Color() };
    const white = new THREE.Color("#e8fbff");
    const expr = new Expression();
    let studio: THREE.Texture | null = null;
    let face: Face | null = null;
    let wanted = 0;

    const layout = () => {
      const w = el.clientWidth, h = el.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h);
      composer.setSize(w, h);
      bloom.resolution.set(w, h);
      camera.aspect = w / h;
      if (face) {
        const c = face.camera;
        // Keep the head in frame on narrow screens, and inside the band the
        // home screen leaves between the greeting and the actions.
        const css = getComputedStyle(document.documentElement);
        const top = parseFloat(css.getPropertyValue("--stage-top")) || 0;
        const bottom = parseFloat(css.getPropertyValue("--stage-bottom")) || 0;
        const free = Math.max(0.5, (h - top - bottom) / h);
        const k = (w / h < 1 ? 1 / Math.max(w / h, 0.55) : 1) / free;
        camera.fov = c.fov;
        camera.position.set(
          c.look[0] + (c.pos[0] - c.look[0]) * k,
          c.look[1] + (c.pos[1] - c.look[1]) * k,
          c.look[2] + (c.pos[2] - c.look[2]) * k,
        );
        camera.lookAt(c.look[0], c.look[1], c.look[2]);
        camera.setViewOffset(w, h, 0, -(top - bottom) / 2, w, h);
      }
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(layout);
    ro.observe(el);

    const load = async (id: FaceId) => {
      if (id === "orb") return;
      const n = ++wanted;
      try {
        const next = await createFace(id, renderer);
        if (n !== wanted) {
          next.dispose();
          return;
        }
        if (face) {
          scene.remove(face.root);
          face.dispose();
        }
        face = next;
        scene.add(next.root);
        if (next.lit) studio ??= studioEnvironment(renderer);
        scene.environment = next.lit ? studio : null;
        layout();
      } catch (err) {
        if (n !== wanted) return;
        const s = useStore.getState();
        s.toast("error", err instanceof Error ? err.message : "That face would not load");
        s.setLocal({ face: "orb" });
      }
    };
    void load(useStore.getState().local.face);
    const unsub = useStore.subscribe((s, prev) => {
      if (s.local.face !== prev.local.face) void load(s.local.face);
    });

    const mouse = { x: 0, y: 0 };
    const ptr = { x: 0, y: 0 };
    const onMove = (e: PointerEvent) => {
      mouse.x = (e.clientX / window.innerWidth - 0.5) * 2;
      mouse.y = (e.clientY / window.innerHeight - 0.5) * 2;
    };
    window.addEventListener("pointermove", onMove);

    const clock = new THREE.Clock();
    let raf = 0;
    const frame = () => {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(clock.getDelta(), 0.05);
      const t = clock.elapsedTime;
      if (!face) return;
      const { mode, server } = useStore.getState();
      const theme = THEMES[server.theme] ?? THEMES.arc;

      target.color.set(mode === "thinking" ? theme.accent : mode === "confirm" ? theme.alert : theme.primary);
      if (mode === "speaking") target.color.lerp(white, 0.28);
      if (server.mood === "hype" && mode !== "confirm") target.color.set("#ff3d9a");
      target.deep.set(theme.deep);
      const k = 1 - Math.exp(-dt * 3.2);
      cur.color.lerp(target.color, k);
      cur.deep.lerp(target.deep, k);

      const out = mode === "speaking" ? audio.level("out") : 0;
      const mic = mode === "listening" ? audio.level("mic") : 0;
      expr.update(dt, mode, server.mood, out, mic);
      ptr.x += (mouse.x - ptr.x) * 0.08;
      ptr.y += (mouse.y - ptr.y) * 0.08;

      face.update({ t, dt, color: cur.color, deep: cur.deep, mode, e: expr.v, ptr });
      bloom.strength = face.bloom + expr.v.amp * 0.35;
      composer.render();
    };
    frame();

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      unsub();
      window.removeEventListener("pointermove", onMove);
      face?.dispose();
      studio?.dispose();
      composer.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, []);

  const mode = useStore((s) => s.mode);
  const label =
    mode === "speaking" ? "Stop Jarvis speaking" : mode === "listening" ? "Stop listening" : "Talk to Jarvis";

  return (
    <div className="reactor face-stage" ref={mount}>
      <button className="reactor-hit" aria-label={label} title={label} onClick={onActivate} />
    </div>
  );
}
