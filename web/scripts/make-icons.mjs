#!/usr/bin/env node
// Generates the provider PWA icons (public/p/icon-*.png) with no dependencies: a primary
// green tile with the brand mark (a light leaf: three rounded corners and one tight one,
// as .brand-mark). Run: npm run icons
import { writeFileSync } from "node:fs";
import { deflateSync } from "node:zlib";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const out = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "p");
const GREEN = [0x1e, 0x4b, 0x38];
const CREAM = [0xf2, 0xf4, 0xee];
const GOLD = [0xf2, 0xb2, 0x33];

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
function crc32(buf) {
  let c = 0xffffffff;
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
function png(size, pixel) {
  const raw = Buffer.alloc((size * 4 + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0;
    for (let x = 0; x < size; x++) {
      const [r, g, b, a] = pixel(x + 0.5, y + 0.5);
      const i = y * (size * 4 + 1) + 1 + x * 4;
      raw[i] = r; raw[i + 1] = g; raw[i + 2] = b; raw[i + 3] = a;
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

// Inside a rounded rectangle with per-corner radii (tl, tr, br, bl)?
function inRounded(x, y, x0, y0, w, h, [tl, tr, br, bl]) {
  if (x < x0 || y < y0 || x > x0 + w || y > y0 + h) return false;
  const corner = (cx, cy, r) => (x - cx) ** 2 + (y - cy) ** 2 <= r * r;
  if (x < x0 + tl && y < y0 + tl) return corner(x0 + tl, y0 + tl, tl);
  if (x > x0 + w - tr && y < y0 + tr) return corner(x0 + w - tr, y0 + tr, tr);
  if (x > x0 + w - br && y > y0 + h - br) return corner(x0 + w - br, y0 + h - br, br);
  if (x < x0 + bl && y > y0 + h - bl) return corner(x0 + bl, y0 + h - bl, bl);
  return true;
}

function icon(size, { maskable }) {
  // Maskable icons keep the mark inside the central 80% safe zone and fill the square.
  const tileRadius = maskable ? 0 : size * 0.22;
  const mark = size * (maskable ? 0.42 : 0.56);
  const m0 = (size - mark) / 2;
  const r = mark / 2;
  return png(size, (x, y) => {
    if (!inRounded(x, y, 0, 0, size, size, [tileRadius, tileRadius, tileRadius, tileRadius])) return [0, 0, 0, 0];
    if (inRounded(x, y, m0, m0, mark, mark, [r, r, r, mark * 0.16])) {
      // A gold stem across the leaf.
      const stem = Math.abs((x - m0) - (mark - (y - m0))) < mark * 0.045 && x > m0 + mark * 0.2 && x < m0 + mark * 0.8;
      return [...(stem ? GOLD : CREAM), 255];
    }
    return [...GREEN, 255];
  });
}

writeFileSync(join(out, "icon-192.png"), icon(192, { maskable: false }));
writeFileSync(join(out, "icon-512.png"), icon(512, { maskable: false }));
writeFileSync(join(out, "icon-maskable-512.png"), icon(512, { maskable: true }));
console.log("Wrote public/p/icon-192.png, icon-512.png, icon-maskable-512.png");
