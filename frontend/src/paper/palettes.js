// Nova's color palettes (docs/plans/2026-09-28-design-direction.md). The
// reactor keeps its form in every palette; only these colors change. `a` and
// `b` are the reactor's front colors, `back` its depth color, `ok` the color
// for checked results on day (`ok`) and night (`okn`) surfaces.
export const PALETTES = {
  grove: { name: "Grove", note: "Mint and sage", a: "#4FBF8B", b: "#A9D46F", back: "#1E5B45", ok: "#1F7A55", okn: "#7FD1A8" },
  fern: { name: "Fern", note: "Green and sea mist", a: "#3FA87A", b: "#7FBFD4", back: "#1B4F72", ok: "#2A7A5E", okn: "#74C9A3" },
  moss: { name: "Moss", note: "Olive and gold", a: "#9DBA5A", b: "#E8C66A", back: "#3E4A1C", ok: "#56741F", okn: "#B5CF7A" },
  dusk: { name: "Dusk", note: "Lilac and peach", a: "#B7A5EE", b: "#F2B28C", back: "#2A3BD1", ok: "#2A3BD1", okn: "#8E9BFF" },
  ember: { name: "Ember", note: "Coral and honey", a: "#F2A07B", b: "#F5D08A", back: "#8A2F4B", ok: "#A8452B", okn: "#F2A07B" },
  glacier: { name: "Glacier", note: "Ice and violet", a: "#9CC8F2", b: "#C9B8F5", back: "#26407A", ok: "#2B5DB8", okn: "#9CC8F2" },
};

export const DEFAULT_PALETTE = "grove";
const HEX = /^#[0-9a-f]{6}$/i;

/** The palette for a stored choice; "custom" reads three hex colors. */
export function resolvePalette(id, custom = "") {
  if (id === "custom") {
    const [a, b, back] = String(custom).split(",");
    if ([a, b, back].every((c) => HEX.test(c || ""))) {
      const [r, g, bl] = hexToRgb(back).map((v) => Math.round(v * 0.9));
      return { name: "Custom", note: "Your three colors", a, b, back, ok: rgbToHex([r, g, bl]), okn: a };
    }
    return PALETTES[DEFAULT_PALETTE];
  }
  return PALETTES[id] || PALETTES[DEFAULT_PALETTE];
}

export function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}

export function rgbToHex(rgb) {
  return `#${rgb.map((v) => Math.max(0, Math.min(255, v)).toString(16).padStart(2, "0")).join("")}`;
}
