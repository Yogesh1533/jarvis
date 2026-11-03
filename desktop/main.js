// Jarvis for the Mac: one window that is either the full HUD or a small
// floating orb, a menu-bar icon, and a global ⌘J to talk from anywhere.
const {
  app, BrowserWindow, Menu, Notification, Tray, globalShortcut, ipcMain,
  nativeImage, screen, session, shell, systemPreferences,
} = require("electron");
const fs = require("fs");
const path = require("path");
const pkg = require("./package.json");
const { Server, URL_BASE } = require("./server");

const ROOT =
  process.env.JARVIS_ROOT ||
  (app.isPackaged ? pkg.jarvisRoot : path.resolve(__dirname, ".."));
const SUMMON = "CommandOrControl+J";
const TOGGLE = "CommandOrControl+Shift+J";
const ORB = { width: 280, height: 340 };
const STATE_FILE = path.join(app.getPath("userData"), "window.json");

// Jarvis speaks without a click first, and keeps listening in the background.
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");


let win = null;
let tray = null;
let layout = "full";
let quitting = false;
// Switching to another app shrinks the full HUD to the orb (setting, default on).
let autoOrb = loadState().autoOrb !== false;
let autoOrbed = false; // the orb is showing because we collapsed it, not because you chose it
let blurTimer = null;
let armedAt = 0; // ignore focus changes while the app is still starting up
const server = new Server(ROOT);

// ── Remembered window state ───────────────────────────────────────
function loadState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
  } catch {
    return {};
  }
}
function saveState(patch) {
  const next = { ...loadState(), ...patch };
  try {
    fs.writeFileSync(STATE_FILE, JSON.stringify(next));
  } catch {
    /* not worth failing over */
  }
}

// ── Window ─────────────────────────────────────────────────────────
function hudUrl() {
  return `${URL_BASE}/?app=1${layout === "orb" ? "&mode=orb" : ""}`;
}

function isLocal(url) {
  return typeof url === "string" && url.startsWith(URL_BASE);
}

function createWindow() {
  const state = loadState();
  layout = state.layout === "orb" ? "orb" : "full";
  const full = state.full || { width: 1440, height: 900 };

  win = new BrowserWindow({
    ...full,
    minWidth: 220,
    minHeight: 260,
    show: false,
    transparent: true,
    backgroundColor: "#00000000",
    titleBarStyle: "hiddenInset",
    acceptFirstMouse: true, // the floating orb is never focused: its first click must count
    title: "Jarvis",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
      backgroundThrottling: false, // keep the mic stream alive when hidden
    },
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    if (!isLocal(url) && !url.startsWith("file://")) {
      e.preventDefault();
      if (/^https?:\/\//.test(url)) shell.openExternal(url);
    }
  });
  // The server restarting drops the page; come back when it does.
  win.webContents.on("did-fail-load", (_e, _code, _desc, url) => {
    if (isLocal(url)) setTimeout(() => win && win.loadURL(hudUrl()), 2000);
  });

  // Leaving Jarvis for another app or window: show the orb instead.
  win.on("blur", () => {
    clearTimeout(blurTimer);
    if (!autoOrb || layout !== "full" || !win.isVisible() || win.isMinimized()) return;
    if (Date.now() < armedAt) return;
    // Wait a beat: a menu or dialog briefly takes focus and hands it back.
    blurTimer = setTimeout(() => {
      if (!win || layout !== "full" || BrowserWindow.getFocusedWindow()) return;
      applyLayout("orb", { auto: true });
      win.showInactive();
    }, 300);
  });
  win.on("focus", () => clearTimeout(blurTimer));

  win.on("close", (e) => {
    if (!quitting) {
      e.preventDefault(); // keep listening from the menu bar
      win.hide();
    }
  });
  const remember = () => layout === "full" && !win.isSimpleFullScreen() && saveState({ full: win.getBounds() });
  win.on("resized", remember);
  win.on("moved", remember);

  applyLayout(layout, { notify: false, initial: true });
  win.loadFile(path.join(__dirname, "loading.html"), { query: { status: "Starting Jarvis" } });
  win.once("ready-to-show", () => {
    if (layout !== "orb") return win.show();
    win.showInactive();
    // Showing a hidden window puts back the position it was created at; set the orb's again.
    win.setBounds(orbBounds(), false);
  });
}

/** Keep the orb fully on a screen: macOS slides a half-off-screen window back when
 * it's clicked, which moves it out from under the second click of a double click. */
function onScreen(b) {
  const wa = screen.getDisplayMatching(b).workArea;
  return {
    ...b,
    x: Math.round(Math.min(Math.max(b.x, wa.x), wa.x + wa.width - b.width)),
    y: Math.round(Math.min(Math.max(b.y, wa.y), wa.y + wa.height - b.height)),
  };
}

function orbBounds() {
  const area = screen.getPrimaryDisplay().workArea;
  const saved = loadState().orb;
  if (saved) return onScreen({ ...saved, ...ORB });
  return { x: area.x + area.width - ORB.width - 24, y: area.y + area.height - ORB.height - 24, ...ORB };
}

function applyLayout(next, { notify = true, initial = false, auto = false } = {}) {
  if (!win) return;
  if (!initial && layout === "full") saveState({ full: win.getBounds() });
  if (!initial && layout === "orb") saveState({ orb: win.getBounds() });
  layout = next;
  autoOrbed = auto && next === "orb";
  // An automatic orb isn't remembered as your choice: relaunching opens the full HUD.
  saveState({ layout: autoOrbed ? "full" : layout });
  if (win.isSimpleFullScreen()) win.setSimpleFullScreen(false);
  if (layout === "orb") {
    win.setWindowButtonVisibility(false);
    win.setResizable(false);
    win.setAlwaysOnTop(true, "floating");
    // skipTransformProcessType keeps the app a normal one: without it macOS
    // turns it into an accessory app and the Dock icon disappears.
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true, skipTransformProcessType: true });
    // Not animated at startup: the window is still hidden, and the half-finished
    // animation would resume (sliding the orb across the screen) on the first click.
    win.setBounds(orbBounds(), !initial);
  } else {
    win.setWindowButtonVisibility(true);
    win.setResizable(true);
    win.setAlwaysOnTop(false);
    win.setVisibleOnAllWorkspaces(false, { skipTransformProcessType: true });
    win.setBounds(loadState().full || { width: 1440, height: 900 }, !initial);
    if (initial) win.center();
  }
  if (notify) win.webContents.send("layout", layout);
  refreshTray();
}

function show({ focus = true } = {}) {
  if (!win) return;
  if (layout === "orb" && !focus) win.showInactive();
  else {
    win.show();
    win.focus();
  }
}

/** Coming back to Jarvis (Dock icon, "Show Jarvis", switching to it) opens the
 * full HUD again, if the orb was only there because you left. */
function expandIfAutomatic() {
  if (!autoOrbed || layout !== "orb") return;
  applyLayout("full");
  show();
}

/** ⌘J: bring Jarvis up and start listening. The orb doesn't steal focus,
 * so you can keep typing in whatever you were using. */
function summon() {
  show({ focus: layout === "full" });
  win.webContents.send("summon");
}

function toggleLayout() {
  applyLayout(layout === "orb" ? "full" : "orb");
  show({ focus: layout === "full" });
}

// ── Menu bar ───────────────────────────────────────────────────────
function refreshTray() {
  if (!tray) return;
  const login = app.getLoginItemSettings().openAtLogin;
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Talk to Jarvis", accelerator: SUMMON, click: summon },
      { label: "Show Jarvis", click: () => { expandIfAutomatic(); show(); } },
      { type: "separator" },
      { label: "Full interface", type: "radio", checked: layout === "full", click: () => { applyLayout("full"); show(); } },
      { label: "Floating orb", type: "radio", checked: layout === "orb", accelerator: TOGGLE, click: () => { applyLayout("orb"); show({ focus: false }); } },
      {
        label: "Orb when I switch to another app",
        type: "checkbox",
        checked: autoOrb,
        click: (item) => {
          autoOrb = item.checked;
          saveState({ autoOrb });
          refreshTray();
        },
      },
      { type: "separator" },
      {
        label: "Launch at login",
        type: "checkbox",
        checked: login,
        click: (item) => {
          app.setLoginItemSettings({ openAtLogin: item.checked });
          refreshTray();
        },
      },
      { label: "Open server log", click: () => shell.openPath(server.logFile) },
      { type: "separator" },
      { label: "Quit Jarvis", accelerator: "CommandOrControl+Q", click: () => app.quit() },
    ]),
  );
}

function createTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, "assets", "trayTemplate.png"));
  icon.setTemplateImage(true);
  tray = new Tray(icon);
  tray.setToolTip("Jarvis (⌘J to talk)");
  refreshTray();
}

// ── Permissions ────────────────────────────────────────────────────
function allowLocalMedia() {
  const allowed = new Set(["media", "audioCapture", "clipboard-sanitized-write", "fullscreen"]);
  session.defaultSession.setPermissionRequestHandler((wc, permission, cb, details) => {
    cb(allowed.has(permission) && isLocal(details.requestingUrl || wc.getURL()));
  });
  session.defaultSession.setPermissionCheckHandler((_wc, permission, origin) => {
    return allowed.has(permission) && isLocal(origin);
  });
}

function registerShortcuts() {
  const failed = [];
  if (!globalShortcut.register(SUMMON, summon)) failed.push("⌘J");
  if (!globalShortcut.register(TOGGLE, toggleLayout)) failed.push("⌘⇧J");
  if (failed.length && Notification.isSupported()) {
    new Notification({
      title: "Jarvis",
      body: `${failed.join(" and ")} is already used by another app, so that shortcut won't work.`,
    }).show();
  }
}

// ── Lifecycle ──────────────────────────────────────────────────────
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", summon);

  app.whenReady().then(async () => {
    if (process.platform === "darwin") app.dock?.show();
    allowLocalMedia();
    // Not awaited: the window shouldn't wait on the permission prompt.
    // The HUD turns the mic on (and explains if it's blocked) by itself.
    if (process.platform === "darwin") systemPreferences.askForMediaAccess("microphone").catch(() => {});
    createWindow();
    createTray();
    registerShortcuts();

    ipcMain.on("get-layout", (e) => {
      e.returnValue = layout;
    });
    ipcMain.on("set-layout", (_e, next) => {
      if (next !== layout) applyLayout(next, { notify: false });
    });
    // The orb is a small window, so it never sees the cursor elsewhere on screen.
    // While it floats, report where the cursor is (as a point inside the window,
    // pulled in from far away) so the face can follow it.
    let lastCursor = "";
    setInterval(() => {
      if (!win || win.isDestroyed() || layout !== "orb" || !win.isVisible()) return;
      const c = screen.getCursorScreenPoint();
      const b = win.getBounds();
      const REACH = 700;
      const nx = Math.max(-1, Math.min(1, (c.x - (b.x + b.width / 2)) / REACH));
      const ny = Math.max(-1, Math.min(1, (c.y - (b.y + b.height / 2)) / REACH));
      const key = nx.toFixed(2) + "," + ny.toFixed(2);
      if (key === lastCursor) return;
      lastCursor = key;
      win.webContents.send("cursor", {
        x: Math.round(b.width / 2 + (nx * b.width) / 2),
        y: Math.round(b.height / 2 + (ny * b.height) / 2),
      });
    }, 33);
    // Dragging the floating orb. A CSS drag region would swallow its clicks, so the
    // page tells us when a drag starts and ends and we follow the cursor meanwhile.
    let dragTimer = null;
    ipcMain.on("drag-window", (_e, on) => {
      clearInterval(dragTimer);
      dragTimer = null;
      if (!win || layout !== "orb") return;
      if (!on) {
        saveState({ orb: win.getBounds() });
        return;
      }
      const c0 = screen.getCursorScreenPoint();
      const b0 = win.getBounds();
      dragTimer = setInterval(() => {
        if (!win || win.isDestroyed()) return clearInterval(dragTimer);
        const c = screen.getCursorScreenPoint();
        win.setBounds(onScreen({ x: b0.x + c.x - c0.x, y: b0.y + c.y - c0.y, width: b0.width, height: b0.height }));
      }, 8);
    });
    ipcMain.on("toggle-fullscreen", () => {
      if (layout === "full") win.setSimpleFullScreen(!win.isSimpleFullScreen());
    });

    const status = (text) =>
      win && !isLocal(win.webContents.getURL()) &&
      win.loadFile(path.join(__dirname, "loading.html"), { query: { status: text } });
    try {
      await server.ensure(status);
      await win.loadURL(hudUrl());
      armedAt = Date.now() + 3000;
    } catch (err) {
      status(String(err.message || err));
    }
  });

  app.on("activate", () => {
    expandIfAutomatic();
    show();
  });
  // Switching back to Jarvis (⌘Tab, Mission Control) opens the HUD, but clicking
  // the orb itself, which also activates the app, must not.
  app.on("did-become-active", () => {
    if (!win || !autoOrbed || layout !== "orb") return;
    const p = screen.getCursorScreenPoint();
    const b = win.getBounds();
    const onOrb = p.x >= b.x && p.x <= b.x + b.width && p.y >= b.y && p.y <= b.y + b.height;
    if (!onOrb) expandIfAutomatic();
  });
  app.on("before-quit", () => {
    quitting = true;
  });
  app.on("will-quit", () => {
    globalShortcut.unregisterAll();
    server.stop();
  });
}
