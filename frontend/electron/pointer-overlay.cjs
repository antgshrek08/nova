// Nova's pointer and stop key on macOS and Linux.
//
// On Windows the engine draws its own pointer window and registers the stop
// key (backend/app/nova_pointer.py). Here the desktop app does both, fed by the
// engine's /pointer/events stream, so the emerald "Nova" pointer, the click
// ring and the stop key look and work the same on every computer.
//
// One transparent, click-through, never-focused window per display, above
// everything including fullscreen apps. It only paints; it never takes a
// click or a key.
const { app, BrowserWindow, globalShortcut, screen } = require("electron");
const http = require("node:http");

const BACKEND = { host: "127.0.0.1", port: 8000 };
const HIDE_AFTER_MS = 4000;

const PAGE = `<!doctype html><meta charset="utf-8"><style>
html,body{margin:0;height:100%;overflow:hidden;background:transparent}
#p{position:absolute;left:0;top:0;display:none;pointer-events:none;will-change:transform}
.ring{position:absolute;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;
 border:3px solid rgb(52,211,153);box-shadow:0 0 0 2px rgba(255,255,255,.85);pointer-events:none;
 animation:r .55s ease-out forwards}
@keyframes r{from{transform:scale(.4);opacity:1}to{transform:scale(1.35);opacity:0}}
</style>
<svg id="p" width="92" height="40" viewBox="0 0 92 40">
 <polygon points="3.5,3.5 3.5,26.5 9.5,20.5 14,30.5 18,29 13.5,19.5 21.5,19.5" fill="rgba(0,0,0,.35)"/>
 <polygon points="2,2 2,25 8,19 12.5,29 16.5,27.5 12,18 20,18" fill="rgb(52,211,153)" stroke="#fff" stroke-width="1.2" stroke-linejoin="round"/>
 <rect x="22" y="20" width="42" height="16" rx="8" fill="rgb(52,211,153)"/>
 <text x="43" y="32" text-anchor="middle" font-family="-apple-system,Segoe UI,Ubuntu,sans-serif" font-size="11" font-weight="700" fill="#062018">Nova</text>
</svg>
<script>
const p = document.getElementById("p");
window.nova = (e) => {
  if (e.t === "move") { p.style.display = "block"; p.style.transform = "translate(" + e.x + "px," + e.y + "px)"; }
  else if (e.t === "hide") { p.style.display = "none"; }
  else if (e.t === "flash") {
    const r = document.createElement("div"); r.className = "ring";
    r.style.left = e.x + "px"; r.style.top = e.y + "px";
    document.body.appendChild(r); setTimeout(() => r.remove(), 700);
  }
};
</script>`;

const overlays = new Map(); // display id -> BrowserWindow
let hideTimer = null;
let current = null; // display id showing the pointer

function overlayFor(display) {
  let win = overlays.get(display.id);
  if (win && !win.isDestroyed()) return win;
  const { x, y, width, height } = display.bounds;
  win = new BrowserWindow({
    x, y, width, height, show: false, frame: false, transparent: true, resizable: false, movable: false,
    focusable: false, skipTaskbar: true, hasShadow: false, alwaysOnTop: true, fullscreenable: false,
    webPreferences: { sandbox: true, contextIsolation: true, backgroundThrottling: false },
  });
  win.__novaOverlay = true;
  win.setIgnoreMouseEvents(true);
  win.setAlwaysOnTop(true, "screen-saver");
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(PAGE));
  overlays.set(display.id, win);
  return win;
}

// The engine speaks in screen pixels (points on macOS, where Electron uses
// the same units). On Linux with display scaling, Electron uses scaled units.
function toDip(x, y) {
  if (process.platform === "linux" && screen.screenToDipPoint) return screen.screenToDipPoint({ x, y });
  return { x, y };
}

function send(win, event) {
  if (!win || win.isDestroyed()) return;
  win.webContents.executeJavaScript(`window.nova && window.nova(${JSON.stringify(event)})`).catch(() => {});
}

function hideAll() {
  for (const win of overlays.values()) {
    send(win, { t: "hide" });
    if (!win.isDestroyed()) win.hide();
  }
  current = null;
}

function handle(event) {
  if (event.t === "hide") return hideAll();
  const point = toDip(event.x, event.y);
  const display = screen.getDisplayNearestPoint(point);
  const win = overlayFor(display);
  if (current !== null && current !== display.id) {
    const old = overlays.get(current);
    send(old, { t: "hide" });
    if (old && !old.isDestroyed()) old.hide();
  }
  current = display.id;
  if (!win.isVisible()) win.showInactive();
  const local = { ...event, x: point.x - display.bounds.x, y: point.y - display.bounds.y };
  send(win, local);
  clearTimeout(hideTimer);
  hideTimer = setTimeout(hideAll, HIDE_AFTER_MS);
}

function listen() {
  const req = http.get({ ...BACKEND, path: "/pointer/events", headers: { Accept: "text/event-stream" } }, (res) => {
    if (res.statusCode !== 200) { res.resume(); setTimeout(listen, 3000); return; }
    res.setEncoding("utf8");
    let buffer = "";
    res.on("data", (chunk) => {
      buffer += chunk;
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const data = block.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("");
        if (data) { try { handle(JSON.parse(data)); } catch { /* malformed event */ } }
      }
    });
    res.on("end", () => setTimeout(listen, 1500));
    res.on("error", () => setTimeout(listen, 1500));
  });
  req.on("error", () => setTimeout(listen, 2000));
}

function post(path, body) {
  const data = JSON.stringify(body);
  const req = http.request({ ...BACKEND, path, method: "POST", headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) } });
  req.on("error", () => {});
  req.end(data);
}

// The stop key. macOS has no Alt key; the same keys are Control+Option+Esc.
// A desktop can already own the first choice (KDE uses Ctrl+Alt+Esc), so try
// the next and tell the engine which one worked, so Nova names the right one.
function registerStopKey() {
  const mac = process.platform === "darwin";
  const choices = [
    ["Control+Alt+Escape", mac ? "Control+Option+Esc" : "Ctrl+Alt+Esc"],
    ["Control+Alt+Shift+Escape", mac ? "Control+Option+Shift+Esc" : "Ctrl+Alt+Shift+Esc"],
  ];
  for (const [accelerator, label] of choices) {
    let ok = false;
    try { ok = globalShortcut.register(accelerator, () => post("/pointer/hotkey", { pressed: true, label })); } catch { ok = false; }
    if (ok) {
      const tell = (tries) => {
        const req = http.request({ ...BACKEND, path: "/pointer/hotkey", method: "POST", headers: { "Content-Type": "application/json" } }, (res) => res.resume());
        req.on("error", () => { if (tries > 0) setTimeout(() => tell(tries - 1), 3000); });
        req.end(JSON.stringify({ label }));
      };
      tell(40);
      return label;
    }
  }
  return null;
}

function destroyAll() {
  for (const win of overlays.values()) if (!win.isDestroyed()) win.destroy();
  overlays.clear();
}

// Overlays are windows too: without this they would keep Nova running after
// its last real window closes, and stop the Dock icon from reopening it.
function isOverlay(win) {
  return Boolean(win && win.__novaOverlay);
}

function start() {
  if (process.platform === "win32") return; // the engine does this natively there
  app.on("browser-window-created", (_event, win) => {
    if (isOverlay(win)) return;
    win.on("closed", () => {
      if (!BrowserWindow.getAllWindows().some((w) => !isOverlay(w) && !w.isDestroyed())) destroyAll();
    });
  });
  app.on("before-quit", destroyAll);
  registerStopKey();
  listen();
  screen.on("display-removed", (_e, display) => {
    const win = overlays.get(display.id);
    if (win && !win.isDestroyed()) win.destroy();
    overlays.delete(display.id);
  });
}

module.exports = { start, isOverlay };
