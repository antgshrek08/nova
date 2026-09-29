import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import NovaReactorWindow from "./components/NovaReactorWindow.jsx";
import DesktopPet from "./components/DesktopPet.jsx";
import PaperApp from "./paper/PaperApp.jsx";
import "./index.css";
import { initTheme } from "./lib/themeStore.js";

initTheme();

// Dev-only automated layout check (task: "Add a development-only automated
// layout check ... Do not show that checker in the normal user interface")
// -- import.meta.env.DEV is a build-time constant, so Rollup drops this
// entire branch (and devLayoutCheck.js's module) from a production build.
if (import.meta.env.DEV) {
  import("./lib/devLayoutCheck.js").then(({ installDevLayoutCheck }) => installDevLayoutCheck());
}

// The miniplayer and desktop pet are each a separate, small/full-screen
// Electron BrowserWindow (see electron/main.cjs's createMiniplayerWindow /
// createDesktopPetWindow) pointed at this same dev server / built
// index.html, just with ?miniplayer=1 or ?pet=1 appended -- one Vite entry
// point serving three very different windows, instead of separate build
// targets to maintain.
const params = new URLSearchParams(window.location.search);
const isMiniplayer = params.get("miniplayer") === "1";
const isNovaReactor = params.get("nova-reactor") === "1";
const isPet = params.get("pet") === "1";

// index.html's <body> carries bg-charcoal-950 for every window this same HTML
// serves -- fine for the main app and miniplayer (both opaque), but the pet
// window is a real OS-transparent Electron BrowserWindow (see
// electron/main.cjs's createDesktopPetWindow), and a solid body background
// paints over that transparency from *inside* the page before anything ever
// reaches the OS compositor. Only the pet window needs this stripped -- the
// other two still want the real background.
if (isPet || isNovaReactor || isMiniplayer) {
  document.body.classList.remove("bg-charcoal-950", "text-charcoal-100");
  document.documentElement.style.background = "transparent";
  document.body.style.background = "transparent";
}

// The Paper interface (docs/plans/2026-09-28-design-direction.md) is the main
// window. The previous interface stays reachable while the rebuild finishes:
// ?ui=classic for one launch, or localStorage "nova.ui" = "classic" to keep it.
function prefersClassic() {
  if (params.get("ui") === "classic") return true;
  if (params.get("ui") === "paper") return false;
  try { return window.localStorage.getItem("nova.ui") === "classic"; } catch { return false; }
}

function Root() {
  if (isNovaReactor || isMiniplayer) return <NovaReactorWindow />;
  if (isPet) return <DesktopPet />;
  return prefersClassic() ? <App /> : <PaperApp />;
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
