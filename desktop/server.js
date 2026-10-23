// Starts (and keeps alive) the Python Jarvis server, unless one is already
// running — e.g. you started `jarvis web` in a terminal. Only a server this
// app started is ever stopped by it.
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");

const PORT = 8765;
const URL_BASE = `http://127.0.0.1:${PORT}`;

function ping() {
  return new Promise((resolve) => {
    const req = http.get(`${URL_BASE}/api/settings`, { timeout: 1500 }, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

class Server {
  constructor(root) {
    this.root = root;
    this.child = null;
    this.stopping = false;
    this.restarts = 0;
    this.logDir = path.join(os.homedir(), "Library", "Logs", "Jarvis");
    this.logFile = path.join(this.logDir, "server.log");
  }

  python() {
    const py = path.join(this.root, ".venv", "bin", "python");
    if (!fs.existsSync(py)) {
      throw new Error(`No Python environment at ${py}. Set it up first (see README).`);
    }
    return py;
  }

  /** Resolves once the server answers; starts it if needed. */
  async ensure(onStatus = () => {}) {
    if (await ping()) {
      onStatus("Connected to the running Jarvis server");
      return;
    }
    this.start(onStatus);
    for (let i = 0; i < 240; i++) {
      // Models load in the background, so the port opens within seconds.
      if (await ping()) return;
      if (i === 20) {
        // The project lives in iCloud Drive: macOS holds the first file read
        // until you allow it, and that dialog can hide behind other windows.
        onStatus("Waiting for macOS: if it asks to let Jarvis use files in iCloud Drive, click Allow");
      }
      await new Promise((r) => setTimeout(r, 500));
    }
    throw new Error(`The Jarvis server didn't start. See ${this.logFile}`);
  }

  start(onStatus = () => {}) {
    fs.mkdirSync(this.logDir, { recursive: true });
    const log = fs.openSync(this.logFile, "a");
    onStatus("Starting the Jarvis server");
    this.child = spawn(this.python(), ["-m", "jarvis", "web"], {
      cwd: this.root,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      stdio: ["ignore", log, log],
    });
    this.child.on("exit", (code) => {
      this.child = null;
      fs.closeSync(log);
      if (this.stopping) return;
      // Crashed: try again with backoff, but don't spin forever.
      if (this.restarts++ < 5) {
        setTimeout(() => this.start(onStatus), 1500 * this.restarts);
      } else {
        onStatus(`The Jarvis server keeps stopping (exit ${code}). See ${this.logFile}`);
      }
    });
  }

  stop() {
    this.stopping = true;
    if (this.child) this.child.kill("SIGTERM");
  }
}

module.exports = { Server, URL_BASE, ping };
