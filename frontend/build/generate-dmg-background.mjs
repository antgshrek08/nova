// The Mac disk image's window: Nova on the left, Applications on the right,
// an arrow between them, and the one thing a first-time Mac user needs to
// know. Run with: node build/generate-dmg-background.mjs
// Writes build/background.png (540x380) and build/background@2x.png.
// Icon positions must match "dmg.contents" in package.json (and the Intel
// disk image settings in .github/workflows/release.yml).
import sharp from "sharp";

const W = 540;
const H = 380;
const FONT = "'Segoe UI', 'Helvetica Neue', Arial, sans-serif";

function svg(scale) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W * scale}" height="${H * scale}" viewBox="0 0 ${W} ${H}">
  <defs>
    <radialGradient id="glow" cx="50%" cy="46%" r="65%">
      <stop offset="0" stop-color="#15303a"/>
      <stop offset="1" stop-color="#0b1220"/>
    </radialGradient>
    <linearGradient id="arrow" gradientUnits="userSpaceOnUse" x1="212" y1="0" x2="318" y2="0">
      <stop offset="0" stop-color="#34d399" stop-opacity="0.35"/>
      <stop offset="1" stop-color="#2dd4bf"/>
    </linearGradient>
  </defs>
  <rect width="${W}" height="${H}" fill="url(#glow)"/>
  <text x="${W / 2}" y="58" text-anchor="middle" font-family="${FONT}" font-size="21" font-weight="600" fill="#f1f5f9">Drag Nova into Applications</text>
  <text x="${W / 2}" y="84" text-anchor="middle" font-family="${FONT}" font-size="12.5" fill="#94a3b8">Then open it from Applications or Launchpad.</text>
  <path d="M 212 196 L 318 196" stroke="url(#arrow)" stroke-width="5" stroke-linecap="round" fill="none"/>
  <path d="M 306 182 L 324 196 L 306 210" stroke="#2dd4bf" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
  <rect x="40" y="306" width="${W - 80}" height="50" rx="12" fill="#ffffff" fill-opacity="0.05" stroke="#ffffff" stroke-opacity="0.08"/>
  <text x="${W / 2}" y="327" text-anchor="middle" font-family="${FONT}" font-size="11.5" fill="#cbd5e1">First time opening it? If your Mac asks, click Done, then choose</text>
  <text x="${W / 2}" y="344" text-anchor="middle" font-family="${FONT}" font-size="11.5" fill="#cbd5e1">System Settings › Privacy &amp; Security › Open Anyway. Only once.</text>
</svg>`;
}

await sharp(Buffer.from(svg(1))).png().toFile(new URL("./background.png", import.meta.url).pathname.replace(/^\/(\w:)/, "$1"));
await sharp(Buffer.from(svg(2))).png().toFile(new URL("./background@2x.png", import.meta.url).pathname.replace(/^\/(\w:)/, "$1"));
console.log("wrote build/background.png and build/background@2x.png");
