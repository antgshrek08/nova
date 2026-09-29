import { useEffect, useState } from "react";
import { loadCustomMascots, mascotFor, mascotUrl } from "../../lib/mascots.js";

/** One model's mascot, bobbing while it works.
 *
 * Animation is a two-frame background-position swap on a sprite strip, not a
 * CSS transform: these are 16px pixel-art figures upscaled with
 * image-rendering: pixelated, and transforming them resamples the pixels into
 * mush at exactly the moment they are meant to look crisp.
 *
 * Motion is spent deliberately. Only a working mascot animates; idle ones hold
 * frame one and dim. Nothing animates while the tab is hidden, and nothing
 * animates for a viewer who has asked for reduced motion -- Workspace already
 * runs the reactor and the constellation canvas, and this is the third thing
 * competing for the same frame budget.
 */
const FRAME_MS = 420;

export default function Mascot({
  /** A mascot name directly, for callers that already know which one they want
   * (Settings listing the set) rather than resolving from a model. */
  name: explicitName,
  provider,
  model,
  size = 40,
  working = false,
  dimmed = false,
  title,
}) {
  const [custom, setCustom] = useState({});
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    let disposed = false;
    const sync = () => loadCustomMascots().then(({ found }) => !disposed && setCustom({ ...found }));
    sync();
    // Settings fires this after an upload. Without it, a mascot already on
    // screen keeps the old art until the component happens to remount, so
    // replacing Claude's picture appears to do nothing in Workspace.
    window.addEventListener("nova:mascots-updated", sync);
    return () => { disposed = true; window.removeEventListener("nova:mascots-updated", sync); };
  }, []);

  useEffect(() => {
    if (!working) { setFrame(0); return undefined; }
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return undefined;

    let timer = 0;
    const tick = () => {
      // document.hidden rather than a visibilitychange listener alone: a tab
      // backgrounded mid-interval would otherwise keep ticking until the next
      // event fires.
      if (!document.hidden) setFrame((f) => (f === 0 ? 1 : 0));
      timer = setTimeout(tick, FRAME_MS);
    };
    timer = setTimeout(tick, FRAME_MS);
    return () => clearTimeout(timer);
  }, [working]);

  const name = explicitName || mascotFor({ provider, model }) || (model ? String(model).split("/").pop() : "nova");
  const url = name ? mascotUrl(name, custom) : null;

  if (!url) {
    // Deterministic hash from name
    let h = 0;
    const str = String(name || provider || "agent");
    for (let i = 0; i < str.length; i++) h = (Math.imul(31, h) + str.charCodeAt(i)) | 0;
    h = Math.abs(h);

    const palettes = [
      { body: "#38bdf8", dark: "#0284c7", eye: "#ffffff", glow: "#7dd3fc" }, // Cyan
      { body: "#a78bfa", dark: "#7c3aed", eye: "#ffffff", glow: "#c4b5fd" }, // Purple
      { body: "#34d399", dark: "#059669", eye: "#ffffff", glow: "#6ee7b7" }, // Emerald
      { body: "#fb923c", dark: "#ea580c", eye: "#ffffff", glow: "#fdba74" }, // Orange
      { body: "#f472b6", dark: "#db2777", eye: "#ffffff", glow: "#f9a8d4" }, // Pink
      { body: "#38d9a9", dark: "#0ca678", eye: "#ffffff", glow: "#63e6be" }, // Mint
    ];
    const p = palettes[h % palettes.length];
    const isBlinking = working && frame === 1;
    const bob = working && frame === 1 ? -1 : 0;

    return (
      <svg
        role="img"
        aria-label={title || `${name} mascot`}
        title={title || name}
        width={size}
        height={size}
        viewBox="0 0 16 16"
        style={{
          display: "inline-block",
          imageRendering: "pixelated",
          shapeRendering: "crispEdges",
          opacity: dimmed ? 0.38 : 1,
          filter: dimmed ? "saturate(0.55)" : "none",
          transform: `translateY(${bob}px)`,
          transition: "transform 180ms ease, opacity 240ms ease",
        }}
      >
        {/* Antenna */}
        <rect x="7" y="1" width="2" height="2" fill={working ? p.glow : p.dark} />
        <rect x="6" y="0" width="4" height="1" fill={working ? "#fef08a" : p.body} />

        {/* Head Shell */}
        <rect x="3" y="3" width="10" height="8" rx="1" fill={p.body} />
        <rect x="4" y="4" width="8" height="6" fill="#0f172a" />

        {/* Eyes (Blinking on animation frame) */}
        {!isBlinking ? (
          <>
            <rect x="5" y="6" width="2" height="2" fill={p.glow} />
            <rect x="9" y="6" width="2" height="2" fill={p.glow} />
          </>
        ) : (
          <>
            <rect x="5" y="7" width="2" height="1" fill={p.dark} />
            <rect x="9" y="7" width="2" height="1" fill={p.dark} />
          </>
        )}

        {/* Cheeks / Accents */}
        <rect x="4" y="8" width="1" height="1" fill={p.dark} opacity="0.8" />
        <rect x="11" y="8" width="1" height="1" fill={p.dark} opacity="0.8" />

        {/* Body / Pedestal */}
        <rect x="5" y="11" width="6" height="3" fill={p.dark} />
        <rect x="6" y="14" width="4" height="1" fill={p.body} />
        <rect x="7" y="12" width="2" height="1" fill={working ? p.glow : "#475569"} />
      </svg>
    );
  }

  return (
    <span
      role="img"
      aria-label={title || `${name} mascot`}
      title={title || name}
      style={{
        display: "inline-block",
        width: size,
        height: size,
        backgroundImage: `url(${url})`,
        // The strip is two frames wide, so the element shows one frame at a
        // time and slides by its own width.
        backgroundSize: `${size * 2}px ${size}px`,
        backgroundPosition: `${-frame * size}px 0`,
        backgroundRepeat: "no-repeat",
        imageRendering: "pixelated",
        opacity: dimmed ? 0.38 : 1,
        filter: dimmed ? "saturate(0.55)" : "none",
        transition: "opacity 240ms ease, filter 240ms ease",
      }}
    />
  );
}
