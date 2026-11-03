// The only bridge between the HUD page and the app: a few narrow calls.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jarvisDesktop", {
  platform: process.platform,
  layout: ipcRenderer.sendSync("get-layout"),
  setLayout: (layout) => ipcRenderer.send("set-layout", layout === "orb" ? "orb" : "full"),
  toggleFullscreen: () => ipcRenderer.send("toggle-fullscreen"),
  onSummon: (fn) => ipcRenderer.on("summon", () => fn()),
  dragWindow: (on) => ipcRenderer.send("drag-window", !!on),
  onCursor: (fn) => ipcRenderer.on("cursor", (_e, p) => fn(p)),
  onLayout: (fn) => ipcRenderer.on("layout", (_e, layout) => fn(layout)),
});
