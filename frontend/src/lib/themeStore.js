/**
 * Nova Theme & Accent Color Customization System
 * Allows persistent, universal theming across all screens, controls, and UI components.
 */

export const THEME_PRESETS = [
  { id: "azure", name: "Sapphire Azure", hex: "#3B82F6", border: "#60A5FA" },
  { id: "emerald", name: "Emerald Mint", hex: "#10B981", border: "#34D399" },
  { id: "violet", name: "Cosmic Violet", hex: "#8B5CF6", border: "#A78BFA" },
  { id: "amber", name: "Sunset Amber", hex: "#F59E0B", border: "#FBBF24" },
  { id: "coral", name: "Crimson Coral", hex: "#F43F5E", border: "#FB7185" },
  { id: "slate", name: "Platinum Slate", hex: "#94A3B8", border: "#CBD5E1" },
];

const DEFAULT_ACCENT = "#3B82F6";
const STORAGE_KEY = "nova.accentColor";

function hexToRgb(hex) {
  let c = hex.replace("#", "");
  if (c.length === 3) {
    c = c.split("").map((x) => x + x).join("");
  }
  const num = parseInt(c, 16);
  return {
    r: (num >> 16) & 255,
    g: (num >> 8) & 255,
    b: num & 255,
  };
}

export function getAccentColor() {
  try {
    return localStorage.getItem(STORAGE_KEY) || DEFAULT_ACCENT;
  } catch {
    return DEFAULT_ACCENT;
  }
}

export function applyAccentColor(hex) {
  if (!hex || typeof hex !== "string" || !hex.startsWith("#")) {
    hex = DEFAULT_ACCENT;
  }

  const { r, g, b } = hexToRgb(hex);
  const root = document.documentElement;

  root.style.setProperty("--accent", hex);
  root.style.setProperty("--accent-rgb", `${r}, ${g}, ${b}`);
  root.style.setProperty("--accent-subtle", `rgba(${r}, ${g}, ${b}, 0.12)`);
  root.style.setProperty("--accent-border", `rgba(${r}, ${g}, ${b}, 0.3)`);
  root.style.setProperty("--accent-hover", `rgba(${r}, ${g}, ${b}, 0.85)`);
  root.style.setProperty("--accent-glow", `rgba(${r}, ${g}, ${b}, 0.25)`);
  root.style.setProperty("--nova-accent", hex);
  root.style.setProperty("--nova-accent-strong", hex);

  try {
    localStorage.setItem(STORAGE_KEY, hex);
  } catch {
    // LocalStorage quota or disabled
  }

  window.dispatchEvent(new CustomEvent("nova:theme-changed", { detail: { hex } }));
}

export function initTheme() {
  const current = getAccentColor();
  applyAccentColor(current);
}
