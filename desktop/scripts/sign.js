// Install the built app into ~/Applications and sign it there. macOS ties the
// microphone and Screen Recording permissions to the code signature: an
// ad-hoc signature changes with every build, so each rebuild would lose them
// and ask again. A stable certificate (JARVIS_SIGN_IDENTITY, or the first
// "Apple Development" one in your keychain) keeps them across rebuilds.
// Signing happens outside iCloud Drive, which keeps re-adding Finder metadata
// that codesign rejects.
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

function identity() {
  if (process.env.JARVIS_SIGN_IDENTITY) return process.env.JARVIS_SIGN_IDENTITY;
  try {
    const list = execFileSync("security", ["find-identity", "-v", "-p", "codesigning"], { encoding: "utf8" });
    const m = list.match(/"(Apple Development:[^"]+)"/);
    if (m) return m[1];
  } catch {
    /* no keychain access: fall back to ad-hoc */
  }
  return "-";
}
const id = identity();
execFileSync("codesign", ["--force", "--deep", "--sign", id, target], { stdio: "inherit" });
console.log("Installed and signed (" + (id === "-" ? "ad-hoc" : id) + "):", target);
