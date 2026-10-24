import { useEffect, useState, useCallback } from "react";
import { useStore, type Panel } from "./store";

export interface ApiResult<T> {
  data?: T;
  error?: string;
}

export async function api<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const r = await fetch(path, {
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    });
    return (await r.json()) as ApiResult<T>;
  } catch (e) {
    return { error: "Can't reach the Jarvis server." };
  }
}

/** Fetch a panel's data, refetching when the panel is bumped or on an interval. */
export function usePanelData<T>(path: string, panel: Panel, intervalMs = 0) {
  const tick = useStore((s) => s.refresh[panel]);
  const [state, setState] = useState<ApiResult<T> & { loading: boolean }>({ loading: true });

  const load = useCallback(async () => {
    const res = await api<T>(path);
    setState({ ...res, loading: false });
  }, [path]);

  useEffect(() => {
    load();
  }, [load, tick]);

  useEffect(() => {
    if (!intervalMs) return;
    const id = setInterval(load, intervalMs);
    return () => clearInterval(id);
  }, [load, intervalMs]);

  return { ...state, reload: load };
}

/** Which HUD panels a tool touches, so they refresh when it runs. */
export function panelsForTool(name: string): Panel[] {
  if (name.startsWith("task_")) return ["tasks"];
  if (name.startsWith("reminder_")) return ["reminders"];
  if (name.startsWith("timer_")) return ["timers"];
  if (name.startsWith("memory_")) return ["memory"];
  if (name.startsWith("calendar_")) return ["agenda"];
  if (name.startsWith("gmail_")) return ["mail"];
  if (name === "mac_set_volume") return ["system", "media"];
  if (name === "mac_media" || name === "mac_now_playing" || name === "mac_open_app" || name === "music_search_youtube") return ["media"];
  return [];
}
