// Before packaging: draw the app and menu-bar icons (no image tools needed)
// and record where the Jarvis project lives, so the packaged app can start
// its server from anywhere.
const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const DESKTOP = path.resolve(__dirname, "..");
const ASSETS = path.join(DESKTOP, "assets");

function png(size, pixel) {
  const raw = Buffer.alloc((size * 4 + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0; // filter: none
    for (let x = 0; x < size; x++) {
      const [r, g, b, a] = pixel((x + 0.5) / size, (y + 0.5) / size, size);
      const o = y * (size * 4 + 1) + 1 + x * 4;
      raw[o] = r;
      raw[o + 1] = g;
      raw[o + 2] = b;
      raw[o + 3] = a;
    }
  }
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(zlib.crc32(td) >>> 0);
    return Buffer.concat([len, td, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // RGBA
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", zlib.deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const clamp = (v) => Math.max(0, Math.min(1, v));
const band = (d, center, width, soft) => clamp(1 - (Math.abs(d - center) - width / 2) / soft);

// App icon: a dark rounded tile holding an arc-reactor ring.
function appPixel(u, v, size) {
  const aa = 1.5 / size;
  // rounded square (macOS-style inset of ~10%)
  const m = 0.1, rad = 0.18;
  const qx = Math.max(Math.abs(u - 0.5) - (0.5 - m - rad), 0);
  const qy = Math.max(Math.abs(v - 0.5) - (0.5 - m - rad), 0);
  const tile = clamp((rad - Math.hypot(qx, qy)) / aa);
  if (!tile) return [0, 0, 0, 0];
  const d = Math.hypot(u - 0.5, v - 0.5);
  const ang = Math.atan2(v - 0.5, u - 0.5);
  const ring = band(d, 0.25, 0.03, aa);
  const segments = band(d, 0.31, 0.025, aa) * (Math.cos(ang * 10) > 0.2 ? 1 : 0);
  const core = clamp(1 - d / 0.12);
  const glow = Math.exp(-((d - 0.25) ** 2) / 0.004) * 0.5;
  const light = Math.min(1, ring + segments * 0.8 + core ** 1.5 + glow);
  const base = [6, 14, 22];
  const holo = [79, 216, 255];
  const c = base.map((b, i) => Math.round(b + (holo[i] - b) * light + (255 - holo[i]) * core ** 3 * 0.8));
  return [...c, Math.round(255 * tile)];
}

// Menu-bar icon: a template image (black + alpha) of the same ring.
function trayPixel(u, v, size) {
  const aa = 1 / size;
  const d = Math.hypot(u - 0.5, v - 0.5);
  const a = Math.max(band(d, 0.36, 0.09, aa), clamp((0.12 - d) / aa));
  return [0, 0, 0, Math.round(255 * a)];
}

fs.mkdirSync(ASSETS, { recursive: true });
fs.writeFileSync(path.join(ASSETS, "trayTemplate.png"), png(18, trayPixel));
fs.writeFileSync(path.join(ASSETS, "trayTemplate@2x.png"), png(36, trayPixel));
fs.writeFileSync(path.join(ASSETS, "icon.png"), png(1024, appPixel));

const iconset = path.join(ASSETS, "icon.iconset");
fs.mkdirSync(iconset, { recursive: true });
for (const s of [16, 32, 128, 256, 512]) {
  fs.writeFileSync(path.join(iconset, `icon_${s}x${s}.png`), png(s, appPixel));
  fs.writeFileSync(path.join(iconset, `icon_${s}x${s}@2x.png`), png(s * 2, appPixel));
}
execFileSync("iconutil", ["-c", "icns", iconset, "-o", path.join(ASSETS, "icon.icns")]);
fs.rmSync(iconset, { recursive: true });

const pkgPath = path.join(DESKTOP, "package.json");
const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
pkg.jarvisRoot = path.resolve(DESKTOP, "..");
fs.writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + "\n");
console.log("Icons drawn; jarvisRoot =", pkg.jarvisRoot);
