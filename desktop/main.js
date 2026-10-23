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
  win.once("ready-to-show", () => (layout === "orb" ? win.showInactive() : win.show()));
}

function orbBounds() {
  const area = screen.getPrimaryDisplay().workArea;
  const saved = loadState().orb;
  if (saved) return { ...saved, ...ORB };
  return { x: area.x + area.width - ORB.width - 24, y: area.y + area.height - ORB.height - 24, ...ORB };
}

function applyLayout(next, { notify = true, initial = false } = {}) {
  if (!win) return;
  if (!initial && layout === "full") saveState({ full: win.getBounds() });
  if (!initial && layout === "orb") saveState({ orb: win.getBounds() });
  layout = next;
  saveState({ layout });
  if (win.isSimpleFullScreen()) win.setSimpleFullScreen(false);
  if (layout === "orb") {
    win.setWindowButtonVisibility(false);
    win.setResizable(false);
    win.setAlwaysOnTop(true, "floating");
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    win.setBounds(orbBounds(), true);
  } else {
    win.setWindowButtonVisibility(true);
    win.setResizable(true);
    win.setAlwaysOnTop(false);
    win.setVisibleOnAllWorkspaces(false);
    win.setBounds(loadState().full || { width: 1440, height: 900 }, true);
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
      { label: "Show Jarvis", click: () => show() },
      { type: "separator" },
      { label: "Full interface", type: "radio", checked: layout === "full", click: () => { applyLayout("full"); show(); } },
      { label: "Floating orb", type: "radio", checked: layout === "orb", accelerator: TOGGLE, click: () => { applyLayout("orb"); show({ focus: false }); } },
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
    ipcMain.on("toggle-fullscreen", () => {
      if (layout === "full") win.setSimpleFullScreen(!win.isSimpleFullScreen());
    });

    const status = (text) =>
      win && !isLocal(win.webContents.getURL()) &&
      win.loadFile(path.join(__dirname, "loading.html"), { query: { status: text } });
    try {
      await server.ensure(status);
      await win.loadURL(hudUrl());
    } catch (err) {
      status(String(err.message || err));
    }
  });

  app.on("activate", () => show());
  app.on("before-quit", () => {
    quitting = true;
  });
  app.on("will-quit", () => {
    globalShortcut.unregisterAll();
    server.stop();
  });
}
