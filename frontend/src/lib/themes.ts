// Each theme sets the CSS custom properties (see styles.css) and the
// reactor's colours. `accent` is the "thinking" colour, `alert` is used
// while Jarvis waits for your go-ahead.
export type ThemeId = "arc" | "mark" | "vibranium";

export interface Theme {
  id: ThemeId;
  name: string;
  primary: string;
  deep: string;
  accent: string;
  alert: string;
}

export const THEMES: Record<ThemeId, Theme> = {
  arc: {
    id: "arc",
    name: "Arc reactor",
    primary: "#4fd8ff",
    deep: "#1b6a85",
    accent: "#ffb23f",
    alert: "#ff4d5e",
  },
  mark: {
    id: "mark",
    name: "Mark III",
    primary: "#ff5a3c",
    deep: "#7a1a10",
    accent: "#ffd45a",
    alert: "#6fe3ff",
  },
  vibranium: {
    id: "vibranium",
    name: "Vibranium",
    primary: "#a68bff",
    deep: "#3b2a7a",
    accent: "#6ff0d0",
    alert: "#ff4d7a",
  },
};
