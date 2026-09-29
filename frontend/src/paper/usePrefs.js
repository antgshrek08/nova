// Appearance and voice preferences, stored on the backend (/settings/app) so
// onboarding, Settings, the title bar and every window agree.
import { useCallback, useEffect, useState } from "react";
import { getAppSettings, updateAppSettings } from "../api.js";
import { DEFAULT_PALETTE, resolvePalette } from "./palettes.js";

// Automatic: night from 7 pm to 7 am local time.
function nightNow() {
  const h = new Date().getHours();
  return h >= 19 || h < 7;
}

export default function usePrefs() {
  const [settings, setSettings] = useState({});
  const [loaded, setLoaded] = useState(false);
  const [clock, setClock] = useState(0);

  useEffect(() => {
    getAppSettings().then((s) => setSettings(s || {})).catch(() => {}).finally(() => setLoaded(true));
    const t = setInterval(() => setClock((n) => n + 1), 60000);
    return () => clearInterval(t);
  }, []);

  const save = useCallback(async (patch) => {
    setSettings((s) => ({ ...s, ...patch }));
    try {
      const next = await updateAppSettings(patch);
      if (next && typeof next === "object") setSettings(next);
    } catch (error) {
      console.warn("Could not save the setting", error);
    }
  }, []);

  const mode = ["day", "night", "auto"].includes(settings.appearance_mode) ? settings.appearance_mode : "auto";
  const paletteId = settings.color_palette || DEFAULT_PALETTE;
  const palette = resolvePalette(paletteId, settings.custom_palette);
  const dark = mode === "night" || (mode === "auto" && nightNow());
  void clock;

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
