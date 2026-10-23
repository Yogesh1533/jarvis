// The Electron shell (desktop/preload.js) exposes window.jarvisDesktop.
// In a plain browser tab it's absent and everything degrades gracefully.
import type { Layout } from "./store";

export interface DesktopBridge {
  platform: string;
  layout: Layout; // the window's layout when the page loaded
  setLayout(layout: Layout): void;
  toggleFullscreen(): void;
  onSummon(fn: () => void): void;
  onLayout(fn: (layout: Layout) => void): void;
}

export const desktop: DesktopBridge | undefined = (window as unknown as { jarvisDesktop?: DesktopBridge }).jarvisDesktop;

/** Running inside the app (no click needed to start audio). */
export const isApp = !!desktop || new URLSearchParams(location.search).get("app") === "1";
