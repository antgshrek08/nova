// Appearance and voice preferences, stored on the backend (/settings/app) so
// onboarding, Settings, the title bar and every window agree.
import { useCallback, useEffect, useState } from "react";
import { getAppSettings, updateAppSettings } from "../api.js";
import { DEFAULT_PALETTE, resolvePalette } from "./palettes.js";

// Automatic: whatever this device is set to (light or dark), like every other
// app on it. A device that can't say falls back to night from 7 pm to 7 am.
const DARK_QUERY = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
function nightNow() {
  if (DARK_QUERY && DARK_QUERY.media !== "not all") return DARK_QUERY.matches;
  const h = new Date().getHours();
  return h >= 19 || h < 7;
}

// The last settings this device saw, so the right look shows on the very first
// frame -- and when the engine can't be reached (a phone away from its computer).
const CACHE = "nova.settings.cache";
function cached() {
  try { return JSON.parse(localStorage.getItem(CACHE) || "{}") || {}; } catch { return {}; }
}
function remember(s) {
  try { localStorage.setItem(CACHE, JSON.stringify(s || {})); } catch { /* private window */ }
}

export default function usePrefs() {
  const [settings, setSettings] = useState(cached);
  const [loaded, setLoaded] = useState(false);
  const [clock, setClock] = useState(0);

  useEffect(() => {
    getAppSettings().then((s) => { if (s && typeof s === "object") { setSettings(s); remember(s); } }).catch(() => {}).finally(() => setLoaded(true));
    const t = setInterval(() => setClock((n) => n + 1), 60000);
    const follow = () => setClock((n) => n + 1);
    DARK_QUERY?.addEventListener?.("change", follow);
    return () => { clearInterval(t); DARK_QUERY?.removeEventListener?.("change", follow); };
  }, []);

  const save = useCallback(async (patch) => {
    setSettings((s) => { const next = { ...s, ...patch }; remember(next); return next; });
    try {
      const next = await updateAppSettings(patch);
      if (next && typeof next === "object") { setSettings(next); remember(next); }
    } catch (error) {
      console.warn("Could not save the setting", error);
    }
  }, []);

  const mode = ["day", "night", "auto"].includes(settings.appearance_mode) ? settings.appearance_mode : "auto";
  const paletteId = settings.color_palette || DEFAULT_PALETTE;
  const palette = resolvePalette(paletteId, settings.custom_palette);
  const dark = mode === "night" || (mode === "auto" && nightNow());
  void clock;
  // The phone's status bar and the browser chrome follow the look too.
  useEffect(() => {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", dark ? "#0E0F10" : "#ECE9E2");
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
  }, [dark]);

  return {
    loaded,
    settings,
    save,
    mode,
    dark,
    paletteId,
    palette,
    customColors: (settings.custom_palette || "#5FD3A0,#F0E08A,#1D4E6B").split(","),
    setMode: (m) => save({ appearance_mode: m }),
    setPalette: (id) => save({ color_palette: id }),
    setCustom: (colors) => save({ color_palette: "custom", custom_palette: colors.join(",") }),
  };
}
