// Install the built app into ~/Applications and ad-hoc sign it there, so
// macOS remembers its microphone permission (no Apple developer account
// needed for your own Mac). Signing happens outside iCloud Drive, which
// keeps re-adding Finder metadata that codesign rejects.
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const out = path.resolve(__dirname, "..", "out.nosync");
const dir = fs.readdirSync(out).find((d) => d.startsWith("mac"));
if (!dir) throw new Error("No mac build found in " + out);
const built = path.join(out, dir, "Jarvis.app");

const apps = path.join(os.homedir(), "Applications");
const target = path.join(apps, "Jarvis.app");
fs.mkdirSync(apps, { recursive: true });
fs.rmSync(target, { recursive: true, force: true });
execFileSync("ditto", [built, target]);
execFileSync("xattr", ["-cr", target]);
execFileSync("codesign", ["--force", "--deep", "--sign", "-", target], { stdio: "inherit" });
console.log("Installed and signed:", target);
