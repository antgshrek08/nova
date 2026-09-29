// One-off generator for the N.O.V.A. terminal wordmark app icon.
// Run with: node build/generate-icons.mjs
// Produces build/icon.svg, build/icon.png (1024 master) and build/icon.ico
// (multi-resolution, with a simplified small-size mark for the sizes where
// the full 8-glyph wordmark would be unreadable).
import sharp from "sharp";
import pngToIco from "png-to-ico";
import fs from "node:fs/promises";

const BG = "#020617"; // slate-950, matches the app shell background
const TEXT = "#f1f5f9"; // slate-100
const ACCENT = "#818cf8"; // indigo-400, matches the app's accent color
const FONT = "Consolas, 'Cascadia Mono', 'Courier New', monospace";
const CANVAS = 1024;
const RADIUS = Math.round(CANVAS * 0.22);

async function measure(svgFragment, w, h) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}">${svgFragment}</svg>`;
  const { data, info } = await sharp(Buffer.from(svg))
    .trim({ threshold: 10 })
    .toBuffer({ resolveWithObject: true });
  // sharp reports trimOffsetLeft/Top as a NEGATIVE offset (the position the
  // untrimmed canvas's origin would be at, relative to the trimmed image) --
  // negate to get the actual ink top-left position in source coordinates.
  return { width: info.width, height: info.height, left: -(info.trimOffsetLeft ?? 0), top: -(info.trimOffsetTop ?? 0), buf: data };
}

// Measures a piece of left-aligned text so its exact rendered ink box (font
// metrics vary by renderer/font-resolution, so this is measured empirically
// rather than estimated) is known before laying out the full composition.
async function measureText(text, fontSize, letterSpacing, weight = 700) {
  const probe = 4000;
  const y = probe / 2;
  const frag = `<text x="0" y="${y}" font-family="${FONT}" font-size="${fontSize}" font-weight="${weight}" letter-spacing="${letterSpacing}" fill="#fff">${text}</text>`;
  const m = await measure(frag, probe, probe);
  return { width: m.width, height: m.height, top: m.top, baselineOffsetFromTop: y - m.top };
}

function roundedSquareBg(size, radius) {
  return `<rect width="${size}" height="${size}" rx="${radius}" ry="${radius}" fill="${BG}"/>`;
}

async function buildFullWordmarkSvg(size) {
  const fontSize = size * 0.135;
  const letterSpacing = size * 0.02;
  const text = "N.O.V.A.";
  const tm = await measureText(text, fontSize, letterSpacing);

  const cursorGap = fontSize * 0.28;
  const cursorWidth = fontSize * 0.42;
  const cursorHeight = tm.height;
  const cursorRadius = cursorWidth * 0.15;

  const totalWidth = tm.width + cursorGap + cursorWidth;
  const startX = (size - totalWidth) / 2;
  const inkTop = (size - tm.height) / 2;
  const baselineY = inkTop + tm.baselineOffsetFromTop;
  const cursorX = startX + tm.width + cursorGap;

  const radius = Math.round(size * 0.22);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  ${roundedSquareBg(size, radius)}
  <text x="${startX}" y="${baselineY}" font-family="${FONT}" font-size="${fontSize}" font-weight="700" letter-spacing="${letterSpacing}" fill="${TEXT}">${text}</text>
  <rect x="${cursorX}" y="${inkTop}" width="${cursorWidth}" height="${cursorHeight}" rx="${cursorRadius}" fill="${ACCENT}"/>
</svg>`;
}

// Small-size mark: the full 8-glyph wordmark is unreadable under ~80px, so
// small ICO layers get a simplified "N" + cursor-block monogram in the same
// color language instead of a shrunk, mushy version of the full wordmark.
async function buildSmallMarkSvg(size) {
  const fontSize = size * 0.64;
  const text = "N";
  const tm = await measureText(text, fontSize, 0);

  const cursorGap = fontSize * 0.16;
  const cursorWidth = fontSize * 0.32;
  const cursorHeight = tm.height;
  const cursorRadius = Math.max(1, cursorWidth * 0.15);

  const totalWidth = tm.width + cursorGap + cursorWidth;
  const startX = (size - totalWidth) / 2;
  const inkTop = (size - tm.height) / 2;
  const baselineY = inkTop + tm.baselineOffsetFromTop;
  const cursorX = startX + tm.width + cursorGap;

  const radius = Math.round(size * 0.22);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  ${roundedSquareBg(size, radius)}
  <text x="${startX}" y="${baselineY}" font-family="${FONT}" font-size="${fontSize}" font-weight="700" fill="${TEXT}">${text}</text>
  <rect x="${cursorX}" y="${inkTop}" width="${cursorWidth}" height="${cursorHeight}" rx="${cursorRadius}" fill="${ACCENT}"/>
</svg>`;
}

async function main() {
  // 1. Full wordmark: source SVG + 1024 PNG master.
  const fullSvg1024 = await buildFullWordmarkSvg(CANVAS);
  await fs.writeFile("build/icon.svg", fullSvg1024);
  await sharp(Buffer.from(fullSvg1024)).png().toFile("build/icon.png");

  // 2. ICO layers.
  //    - Large layers (>=128) render the full wordmark natively at that size.
  //    - Small layers (<128) render the simplified N + cursor monogram
  //      natively at that size (not downscaled -- keeps stroke weight crisp
  //      instead of thinning out).
  const smallSizes = [16, 20, 24, 32, 40, 48, 64];
  const largeSizes = [128, 256];

  const pngBuffers = [];
  for (const s of smallSizes) {
    const svg = await buildSmallMarkSvg(s);
    pngBuffers.push(await sharp(Buffer.from(svg)).png().toBuffer());
  }
  for (const s of largeSizes) {
    const svg = await buildFullWordmarkSvg(s);
    pngBuffers.push(await sharp(Buffer.from(svg)).png().toBuffer());
  }

  const ico = await pngToIco(pngBuffers);
  await fs.writeFile("build/icon.ico", ico);

  // 3. Standalone previews at real taskbar-relevant sizes, for visual
  //    verification without having to actually pin the app to a taskbar.
  await fs.mkdir("build/preview", { recursive: true });
  for (const s of [16, 20, 24, 32, 48, 64]) {
    const svg = await buildSmallMarkSvg(s);
    await sharp(Buffer.from(svg)).png().toFile(`build/preview/mark-${s}.png`);
  }

  console.log("done");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
