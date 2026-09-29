import { useEffect, useRef } from "react";
// Inlined with ?raw on purpose, despite making this a ~867KB chunk.
//
// Tried and reverted: importing it as ?url and fetching at runtime shrinks the
// chunk to 5KB and caches the HTML separately -- but the packaged app loads
// through `win.loadFile(...)`, i.e. a file:// origin, and Chromium blocks
// fetch() (and XHR) against file:// with webSecurity on. That would have
// traded a working miniplayer for a smaller bundle in precisely the
// environment that cannot be tested from the dev server. The chunk is
// lazy-loaded, so the cost is paid only when the miniplayer is opened.
//
// If this is worth revisiting: point the iframe's src at the asset instead of
// fetching it (an iframe may load file:// from a file:// parent) and apply the
// adaptations to the loaded document rather than to the source string.
import referenceHtml from "../../../Nova-Miniplayer.html?raw";
import { subscribeTtsPlayback } from "../lib/ttsPlayback.js";
import { transparentSprite } from "../lib/transparentSprite.js";

// The reference remains byte-for-byte unchanged. Only its page wrapper is
// adapted to the existing Electron surface; artwork and behavior run intact.
//
// Each adaptation is an exact-substring rewrite of the reference's own source.
// String.replace() returns the input untouched when the needle is absent, so
// before this guard existed a single edit to Nova-Miniplayer.html would have
// silently dropped the transparency patches -- the character would render on
// an opaque white card inside a transparent window, with nothing logged and
// nothing to point at. docs/miniplayer-character-integration.md pins the
// reference to one SHA-256 precisely because these rewrites depend on it, so
// a miss is a real integration break and is reported as one.
const ADAPTATIONS = [
  {
    label: "page wrapper styles",
    find: "</head>",
    // `color-scheme: dark` is load-bearing, not cosmetic. A srcdoc iframe
    // defaults to the light color scheme, and Chromium paints an OPAQUE WHITE
    // base canvas behind a light-scheme frame -- so `background: transparent`
    // on html/body was being honoured (computed style confirmed it) while the
    // frame still rendered as a white card inside the dark panel. Confirmed
    // live by toggling this one property: with it, the panel shows through;
    // without it, white returns regardless of every background rule below.
    replace: `<style>
:root{color-scheme:dark}
html,body{margin:0!important;padding:0!important;min-height:0!important;display:block!important;background:transparent!important;overflow:hidden}
#nova-character-v2{width:100%!important}.nova-window{border:0!important;border-radius:0!important;background:transparent!important;box-shadow:none!important}.nova-bar{display:none!important}.nova-touch,.nova-canvas{background:transparent!important}
</style></head>`,
  },
  {
    label: "transparent canvas (drop white fill)",
    find: "ctx.fillStyle='#fff';ctx.fillRect(0,0,400,330);",
    replace: "ctx.clearRect(0,0,400,330);",
  },
  {
    label: "drop standalone-page ground line",
    find: "ctx.strokeStyle='#dce5df';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(17,307);ctx.lineTo(383,307);ctx.stroke();",
    replace: "",
  },
  {
    label: "drop standalone-page right gutter",
    find: "ctx.fillStyle='#edf3ef';ctx.fillRect(382,0,18,330);ctx.fillStyle='#cadbcf';ctx.fillRect(382,0,2,330);",
    replace: "",
  },
  {
    label: "inject transparentSprite helper",
    find: "const root=document.getElementById",
    replace: `const transparentSprite=${transparentSprite.toString()};\nconst root=document.getElementById`,
  },
  {
    label: "route sprite loads through transparentSprite",
    find: "img.onload=resolve;",
    replace: "img.onload=()=>{try{images[name]=transparentSprite(img);resolve();}catch(error){reject(error);}};",
  },
];

const documentHtml = ADAPTATIONS.reduce((html, { label, find, replace }) => {
  if (!html.includes(find)) {
    const message =
      `Nova-Miniplayer.html no longer contains the anchor for "${label}". ` +
      `The compact character will render incorrectly (most visibly, on an opaque ` +
      `background). Re-check the adaptation against the current reference file.`;
    if (import.meta.env.DEV) throw new Error(message);
    // In a packaged build, a degraded character still beats a dead window.
    console.error(message);
    return html;
  }
  return html.replace(find, replace);
}, referenceHtml);

export default function MiniplayerCharacter({ activity = "idle" }) {
  const frameRef = useRef(null);
  const activityRef = useRef(activity);
  const cleanupRef = useRef(() => {});
  activityRef.current = activity;

  function connect() {
    cleanupRef.current();
    const root = frameRef.current?.contentDocument?.getElementById("nova-character-v2");
    if (!root) return;
    let disposed = false, attached = null, activePlayback = null, lastExpression = null;
    const synchronize = () => {
      const character = root.novaCharacter;
      if (!character?.getState().ready || disposed) return;
      const nextAudio = activePlayback?.audio || null;
      if (attached !== nextAudio) {
        character.detachSpeech();
        attached = nextAudio;
        if (attached) character.attachSpeech(attached, { analyser: activePlayback.analyser, cues: activePlayback.cues || [] });
      }
      const expression = ["listening", "thinking"].includes(activityRef.current) ? "focused" : "neutral";
      if (expression !== lastExpression) { lastExpression = expression; character.setExpression(expression); }
    };
    const unsubscribe = subscribeTtsPlayback(value => { activePlayback = value; synchronize(); });
    const onReady = event => { if (event.detail.ready && !disposed) synchronize(); };
    root.addEventListener("nova:state", onReady);
    let pending = false;
    const update = async () => {
      if (pending || disposed) return;
      pending = true;
      try {
        const desktop = await window.electronAPI?.getDesktopActivity?.();
        if (disposed) return;
        if (desktop) root.novaCharacter?.updateDesktopState({ ...desktop, busy: desktop.busy || activityRef.current !== "idle" });
        synchronize();
      } catch { /* The reference expires stale reports and uses page activity. */ }
      finally { pending = false; }
    };
    update();
    const timer = setInterval(update, 1000);
    cleanupRef.current = () => {
      disposed = true;
      clearInterval(timer);
      unsubscribe();
      root.removeEventListener("nova:state", onReady);
      root.novaCharacter?.destroy();
    };
  }
  useEffect(() => () => cleanupRef.current(), []);
  // pointerEvents:none because this is a picture, not a control: the character
  // lives in an iframe, and an iframe swallows every click into its own
  // document, so the parent never sees them. That silently broke "clicking the
  // character marks finished work as read" -- the click was landing inside the
  // frame and going nowhere. Nothing in here is interactive, so letting clicks
  // pass through costs nothing.
  return <iframe ref={frameRef} onLoad={connect} title="Nova animated character" srcDoc={documentHtml}
    className="block w-full border-0"
    style={{ aspectRatio: "400 / 330", WebkitAppRegion: "no-drag", pointerEvents: "none" }} />;
}
