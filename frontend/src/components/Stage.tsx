import { useStore } from "../lib/store";
import { FaceStage } from "./FaceStage";
import { Reactor } from "./Reactor";

/** The centrepiece: the orb, or one of the faces chosen in Settings. */
export function Stage({ onActivate }: { onActivate: () => void }) {
  const face = useStore((s) => s.local.face);
  return face === "orb" ? <Reactor onActivate={onActivate} /> : <FaceStage onActivate={onActivate} />;
}
