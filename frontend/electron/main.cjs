const { app, BrowserWindow, ipcMain, Menu, screen, globalShortcut, dialog, powerMonitor, Tray, nativeImage, shell } = require("electron");
const path = require("node:path");
const fs = require("node:fs");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");
let desktopLocked = false;
app.whenReady().then(() => {
  desktopLocked = powerMonitor.getSystemIdleState(1) === "locked";
  powerMonitor.on("lock-screen", () => { desktopLocked = true; });
  powerMonitor.on("unlock-screen", () => { desktopLocked = false; });
});
ipcMain.handle("get-desktop-activity", () => ({
  idleMs: powerMonitor.getSystemIdleTime() * 1000,
  locked: desktopLocked || powerMonitor.getSystemIdleState(1) === "locked",
  busy: Boolean(voiceAudioOwner && !voiceAudioOwner.isDestroyed()),
}));

// No File/Edit/View/Window/Help bar -- this app has no menu-driven features
// (no Open/Save/Print, no multi-window/tab management Electron's defaults
// assume), so the default template is just dead chrome. Must run before
// createWindow() -- applies globally to every window, not per-window.
Menu.setApplicationMenu(null);

const isDev = process.env.NODE_ENV === "development";
// The test copy of Nova (npm run start:test, or the "Nova (test)" shortcut):
// a whole second Nova with its own port, data folder and window storage, so
// onboarding, the tour and everything else can be tried as a brand-new user
// without touching the real one. NOVA_PORT / NOVA_DATA_DIR move either on their own.
const TEST = process.env.NOVA_TEST === "1" || process.argv.includes("--nova-test");
const PORT = Number(process.env.NOVA_PORT || (TEST ? 8010 : 8000));
const DATA_DIR = process.env.NOVA_DATA_DIR || path.join(app.getPath("home"), TEST ? ".ai-council-test" : ".ai-council");
if (TEST) {
  app.setName("Nova (test)");
  app.setPath("userData", path.join(app.getPath("appData"), "nova-test"));
}
const BACKEND = `http://127.0.0.1:${PORT}`;
// What the windows add to their address: which engine to talk to, and the test badge.
const PAGE_QUERY = [PORT !== 8000 ? `backend=${encodeURIComponent(BACKEND)}` : "", TEST ? "test=1" : ""].filter(Boolean).join("&");
const withQuery = (extra) => [extra, PAGE_QUERY].filter(Boolean).join("&");
const BACKEND_HEALTH_URL = `${BACKEND}/health`;

const isWindows = process.platform === "win32";
const isMac = process.platform === "darwin";
// Windows only shows a notification (and names it "Nova" in Action Center)
// for an app with an identity; this matches the installer's appId.
if (isWindows) app.setAppUserModelId("com.nova.desktop");
const isLinux = process.platform === "linux";

// Packaged: bundled under resources/backend (see package.json's build.extraResources).
// Dev: the real backend/ directory at the repo root, two levels up from here.
const backendDir = app.isPackaged
  ? path.join(process.resourcesPath, "backend")
  : path.join(__dirname, "..", "..", "backend");

function resolvePythonExe() {
  // The installers ship their own Python at backend/python
  // (frontend/build/prepare_python.py); a source checkout uses backend/.venv.
  const bundled = path.join(backendDir, "python", isWindows ? "python.exe" : path.join("bin", "python3"));
  if (fs.existsSync(bundled)) return bundled;
  const candidates = isWindows
    ? [
        path.join(backendDir, ".venv", "Scripts", "python.exe"),
        path.join(backendDir, "venv", "Scripts", "python.exe"),
        "python.exe",
        "python",
      ]
    : [
        path.join(backendDir, ".venv", "bin", "python3"),
        path.join(backendDir, ".venv", "bin", "python"),
        path.join(backendDir, "venv", "bin", "python3"),
        path.join(backendDir, "venv", "bin", "python"),
        "/usr/bin/python3",
        "/usr/local/bin/python3",
        "python3",
        "python",
      ];
  for (const c of candidates) {
    if (path.isAbsolute(c) && fs.existsSync(c)) {
      return c;
    }
  }
  return candidates[0];
}
const pythonExe = resolvePythonExe();

function backendRevision() {
  const directory = path.join(backendDir, "app");
  const digest = crypto.createHash("sha256");
  for (const name of fs.readdirSync(directory).filter(name => name.endsWith(".py")).sort()) {
    digest.update(name);
    digest.update(fs.readFileSync(path.join(directory, name)));
  }
  return digest.digest("hex").slice(0, 16);
}
const expectedBackendRevision = backendRevision();

// public/ ships as part of the Vite build (copied straight into dist/, see
// package.json's build.files), so it's present in both dev (served from
// source) and packaged (built into dist/) runs.
const iconFileName = isWindows ? "icon.ico" : "icon.png";
const iconPath = app.isPackaged
  ? path.join(__dirname, "..", "dist", iconFileName)
  : path.join(__dirname, "..", "public", iconFileName);

let backendProcess = null;
let weStartedBackend = false;

// Google Workspace MCP (task: "wire it in" -- these were manually launched
// via a shell during setup; this makes Electron own their lifecycle the
// same way it already owns the Python backend's, so they survive an app
// restart without a human re-running anything). Two independent instances,
// one per connected Google account (personal/school -- see
// backend/app/mcp_manager.py's server rows "Google Workspace (Personal)"/
// "(School)"), each with its own port and its own on-disk credential
// store so the two accounts' tokens never collide. Real, saved sign-in
// tokens already live in these exact directories -- do not change them,
// that would orphan the completed Google sign-ins.
const WORKSPACE_MCP_ACCOUNTS = [
  { role: "personal", port: 8101, credentialsDirName: "workspace-mcp-personal" },
  { role: "school", port: 8102, credentialsDirName: "workspace-mcp-school" },
];

function resolveWorkspaceMcpExe() {
  const bundled = path.join(backendDir, "python", isWindows ? path.join("Scripts", "workspace-mcp.exe") : path.join("bin", "workspace-mcp"));
  if (fs.existsSync(bundled)) return bundled;
  const candidates = isWindows
    ? [
        path.join(backendDir, ".venv", "Scripts", "workspace-mcp.exe"),
        path.join(backendDir, "venv", "Scripts", "workspace-mcp.exe"),
        "workspace-mcp.exe",
      ]
    : [
        path.join(backendDir, ".venv", "bin", "workspace-mcp"),
        path.join(backendDir, "venv", "bin", "workspace-mcp"),
        "workspace-mcp",
      ];
  for (const c of candidates) {
    if (path.isAbsolute(c) && fs.existsSync(c)) {
      return c;
    }
  }
  return candidates[0];
}
const workspaceMcpExe = resolveWorkspaceMcpExe();
// google_workspace_mcp needs GOOGLE_OAUTH_CLIENT_ID/SECRET, which live in
// the same shared ~/.ai-council/.env every other API key in this app uses
// (see backend/app/config.py) -- read directly here rather than duplicating
// them into Electron's own config, so there's exactly one place they're
// ever stored on disk.
const appEnvPath = path.join(DATA_DIR, ".env");
function readAppEnvFile() {
  const values = {};
  let text;
  try {
    text = fs.readFileSync(appEnvPath, "utf-8");
  } catch {
    return values;
  }
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    values[key] = value;
  }
  return values;
}

const workspaceMcpProcesses = {}; // role -> { process, weStarted }

async function isWorkspaceMcpHealthy(port) {
  try {
    // No dedicated /health route -- any response (even a 4xx from a bare
    // GET with no MCP protocol headers) means something real is listening
    // on this port; only a connection failure means it isn't up.
    await fetch(`http://127.0.0.1:${port}/mcp`, { signal: AbortSignal.timeout(1000) });
    return true;
  } catch {
    return false;
  }
}

async function waitForWorkspaceMcp(port, maxAttempts = 40, intervalMs = 500) {
  for (let i = 0; i < maxAttempts; i++) {
    if (await isWorkspaceMcpHealthy(port)) return true;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return false;
}

function startWorkspaceMcpProcess(role, port, credentialsDirName, clientId, clientSecret) {
  const logPath = path.join(app.getPath("userData"), `workspace-mcp-${role}.log`);
  const logStream = fs.createWriteStream(logPath, { flags: "a" });
  logStream.write(`\n--- starting workspace-mcp (${role}) ${new Date().toISOString()} ---\n`);

  const credentialsDir = path.join(DATA_DIR, credentialsDirName);
  fs.mkdirSync(credentialsDir, { recursive: true });

  const proc = spawn(
    workspaceMcpExe,
    ["--single-user", "--transport", "streamable-http", "--tools", "gmail", "calendar"],
    {
      cwd: backendDir,
      windowsHide: true,
      env: {
        ...process.env,
        WORKSPACE_MCP_PORT: String(port),
        GOOGLE_OAUTH_REDIRECT_URI: `http://localhost:${port}/oauth2callback`,
        WORKSPACE_MCP_CREDENTIALS_DIR: credentialsDir,
        GOOGLE_OAUTH_CLIENT_ID: clientId,
        GOOGLE_OAUTH_CLIENT_SECRET: clientSecret,
        OAUTHLIB_INSECURE_TRANSPORT: "1",
      },
    }
  );
  workspaceMcpProcesses[role] = { process: proc, weStarted: true };

  proc.stdout.on("data", (chunk) => logStream.write(chunk));
  proc.stderr.on("data", (chunk) => logStream.write(chunk));
  proc.on("exit", (code) => {
    logStream.write(`--- workspace-mcp (${role}) exited with code ${code} ---\n`);
  });
}

async function startWorkspaceMcpIfConfigured() {
  if (TEST) return; // their ports belong to the real Nova
  const env = readAppEnvFile();
  const clientId = env.GOOGLE_OAUTH_CLIENT_ID;
  const clientSecret = env.GOOGLE_OAUTH_CLIENT_SECRET;
  // No-op, not an error, for anyone who hasn't set up Google OAuth at all --
  // Gmail/Calendar are optional, the rest of the app must not depend on them.
  if (!clientId || !clientSecret) return;

  for (const { role, port, credentialsDirName } of WORKSPACE_MCP_ACCOUNTS) {
    const alreadyRunning = await isWorkspaceMcpHealthy(port);
    if (alreadyRunning) continue;
    startWorkspaceMcpProcess(role, port, credentialsDirName, clientId, clientSecret);
    await waitForWorkspaceMcp(port);
  }
}

function stopWorkspaceMcpProcesses() {
  for (const entry of Object.values(workspaceMcpProcesses)) {
    if (entry.weStarted && entry.process && !entry.process.killed) {
      entry.process.kill();
    }
  }
}

// "Launch at login" (Settings > General). openAtLogin is meaningless for a
// bare `electron .` dev run (there's no installed exe to point the OS at),
// but is otherwise a real registration -- Electron writes an actual Windows
// Registry Run-key entry (via Squirrel-aware startup arg) or scheduled-task
// equivalent depending on platform. `path` is only set for packaged builds;
// omitting it in dev leaves Electron to use its own dev executable, which is
// harmless (just not meaningful) rather than wrong.
// Linux has no login-item API: every desktop starts what's in
// ~/.config/autostart (the XDG autostart spec), so Nova goes there.
const linuxAutostart = path.join(app.getPath("home"), ".config", "autostart", "nova.desktop");

function linuxLaunchAtLogin(enabled, miniplayerOnly) {
  if (!enabled) {
    fs.rmSync(linuxAutostart, { force: true });
    return;
  }
  const exe = process.env.APPIMAGE || process.execPath;
  const parts = [exe, ...(app.isPackaged ? [] : [app.getAppPath()]), ...(miniplayerOnly ? ["--nova-miniplayer-only"] : [])];
  const exec = parts.map((p) => (/[\s"]/.test(p) ? `"${p.replace(/"/g, '\\"')}"` : p)).join(" ");
  fs.mkdirSync(path.dirname(linuxAutostart), { recursive: true });
  fs.writeFileSync(linuxAutostart, `[Desktop Entry]
Type=Application
Name=Nova
Exec=${exec}
X-GNOME-Autostart-enabled=true
`);
}

function launchesAtLogin() {
  return isLinux ? fs.existsSync(linuxAutostart) : app.getLoginItemSettings().openAtLogin;
}

function applyLaunchAtLogin(enabled, miniplayerOnly = true) {
  if (TEST) return; // the test copy never starts itself
  if (isLinux) {
    linuxLaunchAtLogin(enabled, miniplayerOnly);
    return;
  }
  app.setLoginItemSettings({
    openAtLogin: enabled,
    // Booting straight to the pet rather than the full window is the point of
    // launching at login: the pet is the always-there face of Nova, and a
    // full window seizing the screen at every boot is why people switch this
    // off again. The switch is read back on startup below.
    args: miniplayerOnly ? ["--nova-miniplayer-only"] : [],
    ...(app.isPackaged ? { path: process.execPath } : {}),
  });
}

ipcMain.handle("set-launch-at-login", (_event, enabled, miniplayerOnly) => {
  applyLaunchAtLogin(Boolean(enabled), miniplayerOnly !== false);
  return launchesAtLogin();
});

// Whether the backend should listen beyond this machine. Stored in the same
// .env every other Nova setting lives in, and read here at spawn time because
// the bind address is fixed for the life of the process -- changing it takes
// a restart, which the Settings copy says.
function phoneAccessEnabled() {
  try {
    const text = fs.readFileSync(appEnvPath, "utf-8");
    return /^NOVA_PHONE_ACCESS\s*=\s*["']?1["']?\s*$/m.test(text);
  } catch {
    return false;
  }
}

async function isBackendHealthy() {
  try {
    const res = await fetch(BACKEND_HEALTH_URL, { signal: AbortSignal.timeout(1000) });
    if (!res.ok) return false;
    const health = await res.json();
    return health.app === "nova" && health.protocol === 1;
  } catch {
    return false;
  }
}

async function waitForBackend(maxAttempts = 60, intervalMs = 500) {
  for (let i = 0; i < maxAttempts; i++) {
    if (await isBackendHealthy()) return true;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return false;
}

function startBackendProcess() {
  const logPath = path.join(app.getPath("userData"), "backend.log");
  const logStream = fs.createWriteStream(logPath, { flags: "a" });
  logStream.write(`\n--- starting backend ${new Date().toISOString()} ---\n`);
  logStream.write(`python: ${pythonExe}\ncwd: ${backendDir}\n`);

  // 127.0.0.1 unless the user has turned phone access on. Binding wider is
  // what makes Nova reachable from another device, and it is also what makes
  // the token in backend/app/access.py load-bearing rather than theoretical --
  // so it is a deliberate choice, off by default, and read from the file the
  // setting is written to rather than assumed.
  const host = !TEST && phoneAccessEnabled() ? "0.0.0.0" : "127.0.0.1";
  backendProcess = spawn(pythonExe, ["-m", "uvicorn", "app.main:app", "--host", host, "--port", String(PORT)], {
    cwd: backendDir,
    windowsHide: true,
    env: { ...process.env, NOVA_DATA_DIR: DATA_DIR, ...(TEST ? { NOVA_TEST: "1" } : {}) },
  });
  weStartedBackend = true;

  backendProcess.stdout.on("data", (chunk) => logStream.write(chunk));
  backendProcess.stderr.on("data", (chunk) => logStream.write(chunk));
  backendProcess.on("exit", (code) => {
    logStream.write(`--- backend exited with code ${code} ---\n`);
  });
}

function stopBackendProcess() {
  if (weStartedBackend && backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
}

let mainWindow = null;
let miniplayerWindow = null;
let tray = null;
// True when Nova was started to be the pet and nothing else (login item, or
// --nova-miniplayer-only). It changes one thing: closing the last window must
// not quit, because there is no main window to go back to and the tray is the
// only way back in.
let miniplayerOnlyLaunch = false;

/** The tray icon. Without it, a Nova running as just the pet is unreachable:
 * close the pet and there is no window, no taskbar button and no way to get
 * the app back short of killing it in Task Manager. */
function createTray() {
  if (tray) return tray;
  const trayIconName = isWindows ? "tray.ico" : "tray.png";
  let trayIconPath = path.join(__dirname, trayIconName);
  if (!fs.existsSync(trayIconPath)) {
    trayIconPath = iconPath;
  }
  const icon = nativeImage.createFromPath(trayIconPath);
  tray = new Tray(icon.isEmpty() ? nativeImage.createEmpty() : icon);
  tray.setToolTip("N.O.V.A.");
  refreshTrayMenu();
  tray.on("double-click", () => showMainWindow());
  return tray;
}

function refreshTrayMenu() {
  if (!tray) return;
  const petUp = Boolean(miniplayerWindow && !miniplayerWindow.isDestroyed());
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Open N.O.V.A.", click: () => showMainWindow() },
    {
      label: petUp ? "Hide the pet" : "Show the pet",
      click: () => {
        if (petUp) miniplayerWindow.close();
        else createMiniplayerWindow();
        refreshTrayMenu();
      },
    },
    { type: "separator" },
    // Explicitly labelled: with the tray present, closing every window no
    // longer quits, so there has to be an obvious way to actually stop Nova.
    { label: "Quit N.O.V.A.", click: () => { quitting = true; app.quit(); } },
  ]));
}

/** Focus the main window, creating it if this launch never made one. */
function showMainWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
    return mainWindow;
  }
  return createWindow();
}

// Set by the tray's Quit and by before-quit, so window-all-closed can tell a
// deliberate quit from the user simply closing a window.
let quitting = false;
// Set when opening the miniplayer minimized the app, so closing the
// miniplayer knows to bring it back (and only then).
let mainHiddenForMiniplayer = false;
let miniplayerHitRects = null;
let desktopPetWindow = null;
let microphoneOwner = null;
let voiceAudioOwner = null;
async function yieldWakeMicrophone() {
  if (!microphoneOwner?.background || microphoneOwner.sender.isDestroyed()) return;
  microphoneOwner.sender.send("yield-microphone");
  for (let i = 0; i < 50 && microphoneOwner?.background; i++) await new Promise(resolve => setTimeout(resolve, 20));
}
ipcMain.handle("claim-microphone", async (event, token, background = false) => {
  if (typeof token !== "string" || token.length > 100) return false;
  // The compact window owns wake listening while open; the main app resumes
  // automatically after it closes. Never interrupt an active recording.
  if (background && miniplayerWindow && !miniplayerWindow.isDestroyed()) {
    if (event.sender !== miniplayerWindow.webContents) return false;
    if (microphoneOwner?.background && microphoneOwner.sender !== event.sender) await yieldWakeMicrophone();
  }
  if (background && voiceAudioOwner && !voiceAudioOwner.isDestroyed()) return false;
  if (!background) await yieldWakeMicrophone();
  if (microphoneOwner && !microphoneOwner.sender.isDestroyed()) return false;
  microphoneOwner = { sender: event.sender, token, background };
  if (!background) {
    voiceAudioOwner = null;
    for (const window of BrowserWindow.getAllWindows()) if (window.webContents !== event.sender) window.webContents.send("stop-voice-audio");
  }
  return true;
});
ipcMain.on("release-microphone", (event, token) => {
  if (microphoneOwner?.sender === event.sender && microphoneOwner.token === token) microphoneOwner = null;
});
ipcMain.on("release-voice-audio", (event) => { if (voiceAudioOwner === event.sender) voiceAudioOwner = null; });
ipcMain.on("silence-voice", () => {
  voiceAudioOwner = null;
  for (const window of BrowserWindow.getAllWindows()) if (!window.isDestroyed()) window.webContents.send("stop-voice-audio");
});
ipcMain.handle("claim-voice-audio", async (event) => {
  await yieldWakeMicrophone();
  if (microphoneOwner && !microphoneOwner.sender.isDestroyed()) return false;
  voiceAudioOwner = event.sender;
  for (const window of BrowserWindow.getAllWindows()) {
    if (window.webContents !== event.sender) window.webContents.send("stop-voice-audio");
  }
  return true;
});
/** Links and sign-in pages never open as a bare app window. They go to a tab
 * in Nova's browser when Settings > Browser says so (the backend decides and
 * opens it), otherwise to the user's default browser. */
async function openLink(url) {
  // macOS: the Privacy & Security panes Nova asks the user to switch it on in.
  if (process.platform === "darwin" && /^x-apple\.systempreferences:com\.apple\.preference\.security\?Privacy_[A-Za-z]+$/.test(url)) {
    shell.openExternal(url);
    return;
  }
  let target;
  try { target = new URL(url); } catch { return; }
  if (!["http:", "https:", "mailto:"].includes(target.protocol)) return;
  if (target.protocol !== "mailto:") {
    try {
      const res = await fetch(`${BACKEND}/browser/open-link`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
        signal: AbortSignal.timeout(8000),
      });
      if (res.ok && (await res.json()).handled) return;
    } catch { /* backend busy or down: the user's browser still works */ }
  }
  shell.openExternal(url);
}

function isAppUrl(url) {
  return url.startsWith("file:") || url.startsWith("http://localhost:5173") || url.startsWith("devtools:");
}

app.on("web-contents-created", (_event, contents) => {
  contents.setWindowOpenHandler(({ url }) => {
    if (url && !isAppUrl(url) && url !== "about:blank") openLink(url);
    return { action: "deny" };
  });
  // A plain link clicked without target=_blank would otherwise replace Nova
  // itself with the web page.
  contents.on("will-navigate", (event, url) => {
    if (isAppUrl(url)) return;
    event.preventDefault();
    openLink(url);
  });
});
ipcMain.handle("open-link", (_event, url) => openLink(String(url || "")));
// A notification clicked: bring the app forward, leave the miniplayer alone.
ipcMain.handle("show-main-window", () => { showMainWindow(); });

const hasInstanceLock = app.requestSingleInstanceLock();
// "Start over" (test copy only, and only when no other test copy is open):
// forget its data and its pages' saved state, so onboarding and the tour run
// as for a brand-new user. Never touches the real Nova's folders.
if (TEST && hasInstanceLock && process.argv.includes("--fresh")) {
  const pageState = ["Local Storage", "IndexedDB", "Session Storage", "Service Worker"].map((d) => path.join(app.getPath("userData"), d));
  for (const dir of [DATA_DIR, ...pageState]) {
    if (dir.includes("test")) {
      try { fs.rmSync(dir, { recursive: true, force: true }); } catch { /* in use: left as it is */ }
    }
  }
}
if (!hasInstanceLock) app.quit();
app.on("second-instance", (_event, argv) => {
  // Launching Nova again while it is already running means "show me Nova".
  // This used to only raise an existing main window, which was fine when
  // there always was one -- after a pet-only launch there is none, and
  // double-clicking the shortcut would have silently done nothing.
  // A second copy asking only for the pet gets the pet, not the full window.
  if (argv.includes("--nova-miniplayer-only")) {
    createMiniplayerWindow();
    refreshTrayMenu();
    return;
  }
  showMainWindow();
});

function createWindow() {
  const win = new BrowserWindow({
    width: 1100,
    height: 760,
    title: TEST ? "Nova (test)" : "N.O.V.A.",
    titleBarStyle: isMac ? "hiddenInset" : "hidden",
    ...(isMac ? { trafficLightPosition: { x: 16, y: 17 } } : {}),
    icon: iconPath,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow = win;
  win.on("closed", () => {
    if (mainWindow === win) mainWindow = null;
  });
  // Bringing the app back from the taskbar while the miniplayer is up is
  // switching back to the full app: the miniplayer steps aside.
  win.on("restore", () => {
    if (mainHiddenForMiniplayer && miniplayerWindow && !miniplayerWindow.isDestroyed()) {
      mainHiddenForMiniplayer = false;
      miniplayerWindow.close();
    }
  });

  if (isDev) {
    win.loadURL("http://localhost:5173");
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"), PAGE_QUERY ? { search: PAGE_QUERY } : undefined);
  }
  return win;
}

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  } else {
    showMainWindow();
  }
});

// Window controls IPC for custom titlebar
ipcMain.handle("minimize-window", (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (win) win.minimize();
});
ipcMain.handle("maximize-window", (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (win) {
    if (win.isMaximized()) win.unmaximize();
    else win.maximize();
  }
});
ipcMain.handle("close-window", (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (win) win.close();
});
ipcMain.handle("is-window-maximized", (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  return win ? win.isMaximized() : false;
});
ipcMain.handle("set-always-on-top", (event, flag) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (win) win.setAlwaysOnTop(Boolean(flag));
});

// Small always-on-top companion window (Spotify/Apple Music-style mini
// player) -- mascot + Full Screen/Speak buttons only, no chat box (see
// src/components/NovaReactorWindow.jsx, loaded via the same index.html with
// ?miniplayer=1 so this doesn't need its own Vite build target).
// skipTaskbar since it's a utility window, not a second app window; no
// frame since the whole point is a small borderless widget.
const miniplayerPositionPath = () =>
  path.join(app.getPath("userData"), "miniplayer-position.json");

const MINIPLAYER_MARGIN = 24;

/** Bottom-right of a display's work area.
 *
 * The pet always opens in a corner rather than wherever it was last dragged.
 * Restoring an exact position sounds friendlier and is not: the window gets
 * nudged around in use, so "where you left it" drifts into "somewhere in the
 * middle of the screen", and a companion that wanders is worse than one that
 * has a home. workArea, so it sits above the taskbar rather than under it.
 */
function bottomRightOf(display, width, height) {
  const { workArea: a } = display;
  return {
    x: Math.round(a.x + a.width - width - MINIPLAYER_MARGIN),
    y: Math.round(a.y + a.height - height - MINIPLAYER_MARGIN),
  };
}

/** The display the pet was last on, if it still exists.
 *
 * The *screen* is remembered; the position on it is not. Moving the pet to the
 * second monitor should stick, because that is a deliberate choice about where
 * it lives. Checked against the current displays rather than trusted -- a
 * monitor that was there yesterday may be unplugged today, and restoring to a
 * display that no longer exists would leave an invisible window with no way to
 * find it.
 */
function savedMiniplayerDisplay() {
  let saved;
  try {
    saved = JSON.parse(fs.readFileSync(miniplayerPositionPath(), "utf8"));
  } catch {
    return null;
  }
  if (saved?.displayId === undefined) return null;
  return screen.getAllDisplays().find(d => d.id === saved.displayId) || null;
}

function readMiniplayerPrefs() {
  try { return JSON.parse(fs.readFileSync(miniplayerPositionPath(), "utf8")) || {}; } catch { return {}; }
}

function writeMiniplayerPrefs(patch) {
  try {
    fs.writeFileSync(miniplayerPositionPath(), JSON.stringify({ ...readMiniplayerPrefs(), ...patch }));
  } catch { /* not worth surfacing */ }
}

/** Pinned: floats above other windows and stays off the taskbar, like a
 * widget. Unpinned: an ordinary window -- other windows can cover it, and it
 * gets a taskbar button and Alt+Tab entry so it can always be brought back. */
function miniplayerPinned() {
  return readMiniplayerPrefs().pinned !== false;
}

function applyMiniplayerPin(win, pinned) {
  if (!win || win.isDestroyed()) return;
  win.setAlwaysOnTop(pinned);
  win.setSkipTaskbar(pinned);
}

function rememberMiniplayerPosition(win) {
  if (!win || win.isDestroyed()) return;
  try {
    const displayId = screen.getDisplayMatching(win.getBounds()).id;
    writeMiniplayerPrefs({ displayId });
  } catch {
    // Not worth surfacing: the pet still works, it just opens on the primary
    // display next time instead of the one it was moved to.
  }
}

function createMiniplayerWindow() {
  if (miniplayerWindow && !miniplayerWindow.isDestroyed()) {
    miniplayerWindow.show();
    miniplayerWindow.focus();
    return miniplayerWindow;
  }
  const WIDTH = 260;
  // No panel any more -- the page paints nothing but the character, its status
  // line and the controls (see NovaReactorWindow's render). The window is sized
  // to that content rather than to a card: the 400x330 character box at 260px
  // wide is ~215px tall, plus the status line and the control cluster.
  // Everything outside the character is transparent, so extra height is not
  // spare room -- it is an invisible dead zone that still eats clicks meant for
  // whatever is behind it.
  // 330 was sized when both control rows waited for hover. With type/talk now
  // always up and the secondary row fading in beneath it, the stack ran past
  // the bottom edge and the rows collided with the status line.
  const HEIGHT = 376;
  // Always the bottom-right corner -- of the screen it was last moved to, or
  // the primary one. Out of the way of whatever is being worked on, and clear
  // of the top-left corner most apps put their own toolbars in.
  const home = savedMiniplayerDisplay() || screen.getPrimaryDisplay();
  const corner = bottomRightOf(home, WIDTH, HEIGHT);
  const win = new BrowserWindow({
    width: WIDTH,
    height: HEIGHT,
    x: corner.x,
    y: corner.y,
    transparent: true,
    // The OS window must not draw a background behind the page -- the page is
    // transparent now, and any window background would show as a visible panel.
    hasShadow: false,
    title: TEST ? "Nova (test)" : "N.O.V.A.",
    icon: iconPath,
    alwaysOnTop: miniplayerPinned(),
    frame: false,
    resizable: false,
    skipTaskbar: miniplayerPinned(),
    // Real bug found live: a new BrowserWindow shows immediately by
    // default, which can paint a frame or two of unstyled/mid-layout HTML
    // before the stylesheet finishes loading -- reported as the mascot
    // rendering as "a vertical triangle" on open. show:false + the
    // ready-to-show handler below (standard Electron pattern) holds the
    // window hidden until the page has actually finished painting, so the
    // very first thing shown is the real, fully-styled circle.
    show: false,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  // Starts click-through so the space around the pet never steals a click from
  // the app behind it; the renderer switches it off while the pointer is over
  // the character or a control (see NovaReactorWindow).
  win.setIgnoreMouseEvents(true, { forward: true });
  startMiniplayerHitTesting(win);
  win.once("ready-to-show", () => win.show());
  miniplayerWindow = win;
  // "moved" fires once per drag on Windows, not per pixel, so writing the file
  // here is cheap. Saved on close too, since a window moved and then closed
  // quickly can be destroyed before the event lands.
  win.on("moved", () => rememberMiniplayerPosition(win));
  win.on("close", () => rememberMiniplayerPosition(win));
  win.on("closed", () => {
    if (miniplayerWindow === win) miniplayerWindow = null;
    miniplayerHitRects = null;
    // The tray's Show/Hide label describes the pet's current state, so it has
    // to follow the pet closing itself, not just the tray closing it.
    refreshTrayMenu();
    // Opening the miniplayer tucked the app away; closing it brings it back.
    if (mainHiddenForMiniplayer && !quitting) {
      mainHiddenForMiniplayer = false;
      if (mainWindow && !mainWindow.isDestroyed()) {
        if (mainWindow.isMinimized()) mainWindow.restore();
        mainWindow.show();
        mainWindow.focus();
      }
    }
  });

  const url = isDev ? "http://localhost:5173/?nova-reactor=1" : null;
  if (isDev) {
    win.loadURL(url);
  } else {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"), { search: withQuery("nova-reactor=1") });
  }
  return win;
}

// Code tab milestone: "Opening an existing project through the native
// folder picker" -- a real OS dialog, not a fake in-app one, since only the
// main process can show a native file/folder chooser. Returns the chosen
// absolute path (or null if the user cancelled) for the renderer to POST to
// the backend's /code/workspace-root. No sandboxing applied here -- the
// user choosing a folder through their own OS's dialog is the actual
// safety boundary (same reasoning as any real IDE's "Open Folder").
ipcMain.handle("choose-project-folder", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openDirectory", "createDirectory"],
    title: "Open Project Folder",
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

// The user switching to the miniplayer: the full app gets out of the way
// (minimized, not closed) and comes back when the miniplayer closes.
ipcMain.handle("open-miniplayer", () => {
  createMiniplayerWindow();
  if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isMinimized()) {
    mainHiddenForMiniplayer = true;
    mainWindow.minimize();
  }
});

// The solid parts of the miniplayer (its card, in window coordinates), as
// measured by the page. Everything else stays click-through. Without this the
// fixed zones below missed the card's header, so its X never got the click.
ipcMain.on("miniplayer-hit-rects", (event, rects) => {
  if (!miniplayerWindow || miniplayerWindow.isDestroyed() || event.sender !== miniplayerWindow.webContents) return;
  if (!Array.isArray(rects)) return;
  miniplayerHitRects = rects.slice(0, 8).filter(r => r && [r.x, r.y, r.w, r.h].every(Number.isFinite))
    .map(r => ({ x: r.x, y: r.y, w: r.w, h: r.h }));
});

ipcMain.handle("get-miniplayer-pinned", () => miniplayerPinned());
ipcMain.handle("set-miniplayer-pinned", (_event, flag) => {
  const pinned = Boolean(flag);
  writeMiniplayerPrefs({ pinned });
  applyMiniplayerPin(miniplayerWindow, pinned);
  return pinned;
});

/** Which display the pet is on, and how many there are to cycle through. */
ipcMain.handle("miniplayer-displays", () => {
  const displays = screen.getAllDisplays();
  if (!miniplayerWindow || miniplayerWindow.isDestroyed()) {
    return { count: displays.length, index: 0 };
  }
  const current = screen.getDisplayMatching(miniplayerWindow.getBounds());
  return {
    count: displays.length,
    index: Math.max(0, displays.findIndex(d => d.id === current.id)),
  };
});

/** Send the pet to the bottom-right corner of the next display.
 *
 * The corner, not the equivalent spot on the new screen: the corner is where
 * the pet lives, and landing it anywhere else would mean the button sometimes
 * parks it in the middle of a monitor.
 */
ipcMain.handle("miniplayer-next-display", () => {
  if (!miniplayerWindow || miniplayerWindow.isDestroyed()) return null;
  const displays = screen.getAllDisplays();
  if (displays.length < 2) return null;

  const bounds = miniplayerWindow.getBounds();
  const from = screen.getDisplayMatching(bounds);
  const nextIndex = (displays.findIndex(d => d.id === from.id) + 1) % displays.length;
  const next = displays[nextIndex];

  const corner = bottomRightOf(next, bounds.width, bounds.height);
  miniplayerWindow.setPosition(corner.x, corner.y);
  rememberMiniplayerPosition(miniplayerWindow);
  return { index: nextIndex, count: displays.length };
});

// How often to ask where the cursor is. 60ms is well inside the time it takes
// to move a mouse onto a target and press, and costs nothing measurable.
const MINIPLAYER_HIT_POLL_MS = 60;

/** Which parts of the pet's window are solid enough to take a click.
 *
 * Window-relative, and deliberately generous around the character rather than
 * pixel-accurate: the aim is that the large empty regions -- the side margins
 * and the band between the character and the controls -- stop stealing clicks,
 * not that every transparent pixel of the sprite does.
 */
function miniplayerHitZones(width, height) {
  const CHARACTER_W = 150;              // the figure, not its 260px canvas
  return [
    { x: (width - CHARACTER_W) / 2, y: 0, w: CHARACTER_W, h: 232 },  // character
    { x: 0, y: height - 92, w: width, h: 92 },                        // control rows
  ];
}

/** Toggle click-through from the real cursor position.
 *
 * This cannot be driven from the renderer's mouseenter, which is the obvious
 * design and does not work: while a window is ignoring the mouse, Chromium
 * receives no move events for it either -- `forward: true` did not deliver them
 * for this transparent window -- so the page can never notice the pointer
 * arriving and ask for the mouse back. Measured directly: hovering the
 * character produced no hover state at all. Polling the cursor in the main
 * process has no such dependency.
 */
function startMiniplayerHitTesting(win) {
  // Starts true to match the setIgnoreMouseEvents(true) the window is created
  // with, so the first tick only calls through when the state actually differs.
  let ignoring = true;
  const timer = setInterval(() => {
    if (!win || win.isDestroyed()) return;
    const bounds = win.getBounds();
    const cursor = screen.getCursorScreenPoint();
    const x = cursor.x - bounds.x;
    const y = cursor.y - bounds.y;
    const zones = miniplayerHitRects || miniplayerHitZones(bounds.width, bounds.height);
    const solid = zones.some(z => x >= z.x && x <= z.x + z.w && y >= z.y && y <= z.y + z.h);
    if (ignoring === !solid) return;    // already in the right state
    ignoring = !solid;
    win.setIgnoreMouseEvents(ignoring, { forward: true });
  }, MINIPLAYER_HIT_POLL_MS);
  win.on("closed", () => clearInterval(timer));
}

ipcMain.handle("close-miniplayer", () => {
  if (miniplayerWindow && !miniplayerWindow.isDestroyed()) miniplayerWindow.close();
});

// The miniplayer's own "Full Screen" button -- brings the real app forward
// and dismisses the miniplayer, same as clicking back into a Spotify/Apple
// Music main window from their mini player.
ipcMain.handle("focus-main-window", () => {
  mainHiddenForMiniplayer = false;
  if (miniplayerWindow && !miniplayerWindow.isDestroyed()) miniplayerWindow.close();
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  } else {
    createWindow();
  }
});

// Desktop roaming character (character system phase 2, task: "let the
// character move around the actual desktop outside the miniplayer circle" --
// architecture referenced from TonyNa-code/desktop-pet: a transparent,
// frameless, always-on-top window sized to the screen's real work area
// (screen.getPrimaryDisplay().workArea already excludes the taskbar on
// Windows, which is what satisfies "avoids the taskbar" for free -- no
// manual taskbar-rect math needed), with the character positioned and
// animated via CSS/JS *inside* that one window rather than physically
// moving a tiny OS window around the screen (the latter is what real
// desktop-pet implementations avoid too -- moving a window via setBounds on
// every animation frame is expensive and visibly janky compared to a CSS
// transform).
//
// focusable:false so it can never steal focus/keyboard input from whatever
// app the user is actually using -- this window should be able to sit on
// top of everything and be looked at without ever being "in the way".
// Click-through is the default state (see set-desktop-pet-click-through
// below): forward:true means mouse events still reach the renderer for
// hover detection, they just don't get treated as a real click on this
// window's (invisible, transparent) content -- that's what lets clicks
// "pass through" to the desktop/whatever app is really underneath, except
// over the character itself, where the renderer flips this off.
function createDesktopPetWindow() {
  if (desktopPetWindow && !desktopPetWindow.isDestroyed()) {
    desktopPetWindow.show();
    return desktopPetWindow;
  }
  const { workArea } = screen.getPrimaryDisplay();
  const win = new BrowserWindow({
    x: workArea.x,
    y: workArea.y,
    width: workArea.width,
    height: workArea.height,
    title: TEST ? "Nova (test)" : "N.O.V.A.",
    icon: iconPath,
    transparent: true,
    frame: false,
    resizable: false,
    movable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    hasShadow: false,
    focusable: false,
    show: false,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.setIgnoreMouseEvents(true, { forward: true });
  win.once("ready-to-show", () => win.show());
  desktopPetWindow = win;
  win.on("closed", () => {
    if (desktopPetWindow === win) desktopPetWindow = null;
  });

  const url = isDev ? "http://localhost:5173/?pet=1" : null;
  if (isDev) {
    win.loadURL(url);
  } else {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"), { search: withQuery("pet=1") });
  }
  return win;
}

ipcMain.handle("open-desktop-pet", () => {
  // Backward-compatible callers now open the contained character surface.
  createMiniplayerWindow();
});

ipcMain.handle("close-desktop-pet", () => {
  if (desktopPetWindow && !desktopPetWindow.isDestroyed()) desktopPetWindow.close();
});

// Hover-driven click-through toggle (see createDesktopPetWindow's comment) --
// called from the renderer's onMouseEnter/onMouseLeave on the character
// element itself, many times over the window's lifetime, so this stays
// cheap and just no-ops if the window's gone.
ipcMain.handle("set-desktop-pet-click-through", (_event, ignore) => {
  if (desktopPetWindow && !desktopPetWindow.isDestroyed()) {
    desktopPetWindow.setIgnoreMouseEvents(Boolean(ignore), { forward: true });
  }
});

// Push-to-talk hotkey (task: "manual push-to-talk hotkey as a backup to
// wake-word... a reliable fallback that works regardless"). Real Electron
// API constraint worth being explicit about: globalShortcut only exposes a
// single fire-on-keydown callback per registration -- there is no
// accompanying keyup event for a *system-wide* hotkey without a native OS
// keyboard hook (an extra native-module dependency this deliberately
// avoids), so this is implemented as a TOGGLE (press once to start
// listening, press again to stop and send) rather than a literal
// press-and-hold. Practically equivalent for this feature's actual purpose
// -- a deterministic, wake-word-independent way to start a voice turn --
// just not literal "hold" semantics.
//
// Always targets the miniplayer specifically (opening it if it isn't
// already), not whichever window happens to be focused: the miniplayer's
// mic flow is a fully self-contained voice turn (record -> transcribe ->
// send -> speak) that doesn't depend on which conversation/tab the main
// window has open, so the hotkey behaves the same "just talk to it" way
// regardless of whatever else is on screen -- the same reliability
// property wake-word itself would have if it were live.
let currentPushToTalkAccelerator = null;

function triggerPushToTalk() {
  // Real bug found live: when the miniplayer isn't open yet, sending the
  // IPC message immediately after createMiniplayerWindow() races the
  // fresh renderer's own startup -- the window existed, but its React tree
  // (and the useEffect that subscribes to this event) hadn't mounted yet,
  // so the very first trigger silently went nowhere and the miniplayer
  // just sat there "Sleeping" instead of listening. did-finish-load fires
  // once that page has actually finished loading (main.jsx has run, so
  // the subscription is live) -- reusing an already-open window (the
  // common case) still sends immediately, no artificial delay.
  const alreadyOpen = miniplayerWindow && !miniplayerWindow.isDestroyed();
  const win = createMiniplayerWindow();
  if (alreadyOpen) {
    win.webContents.send("push-to-talk-triggered");
  } else {
    win.webContents.once("did-finish-load", () => {
      win.webContents.send("push-to-talk-triggered");
    });
  }
}

function registerPushToTalkHotkey(accelerator) {
  if (currentPushToTalkAccelerator) {
    globalShortcut.unregister(currentPushToTalkAccelerator);
    currentPushToTalkAccelerator = null;
  }
  if (!accelerator) return { success: true };
  const ok = globalShortcut.register(accelerator, triggerPushToTalk);
  if (!ok) {
    return { success: false, error: `"${accelerator}" is invalid or already in use by another app.` };
  }
  currentPushToTalkAccelerator = accelerator;
  return { success: true };
}

ipcMain.handle("register-push-to-talk-hotkey", (_event, accelerator) => {
  return registerPushToTalkHotkey(accelerator);
});

app.whenReady().then(async () => {
  if (!hasInstanceLock) return;
  // If a backend is already up (e.g. a dev instance started separately in a
  // terminal), don't spawn a second one on the same port -- just use it.
  const alreadyRunning = await isBackendHealthy();
  if (!alreadyRunning) {
    startBackendProcess();
    if (!await waitForBackend()) {
      dialog.showErrorBox("Nova could not start", `The backend did not become ready, or an older backend is using port ${PORT}. Restart Nova with scripts/Start-Nova.ps1. Details are in the backend.log file in Nova’s app data folder.`);
      app.quit();
      return;
    }
  }

  await startWorkspaceMcpIfConfigured();

  // Reconcile the OS-level registration with whatever's persisted in
  // Settings on every launch -- covers both a normal "user flipped the
  // toggle last session" case and the one-time gap from before this was
  // wired up at all (the setting could already be "on" in the DB from
  // before, with nothing ever actually registered for it).
  try {
    const res = await fetch(`${BACKEND}/settings/app`, { signal: AbortSignal.timeout(2000) });
    if (res.ok) {
      const settings = await res.json();
      applyLaunchAtLogin(
        Boolean(settings.launch_at_login),
        settings.miniplayer_at_login !== false,
      );
      if (settings.push_to_talk_hotkey) registerPushToTalkHotkey(settings.push_to_talk_hotkey);
    }
  } catch {
    // Non-fatal -- next settings save (or next launch) reconciles it.
  }

  // Started as the pet and nothing else -- from the login item, or by hand.
  // The backend is already running by this point (it is started above, the
  // same way it is for a normal launch), which is what lets the pet answer,
  // speak and run tools without the main window ever being opened.
  miniplayerOnlyLaunch =
    app.commandLine.hasSwitch("nova-miniplayer-only") ||
    process.argv.includes("--nova-miniplayer-only");

  if (miniplayerOnlyLaunch) {
    // The tray belongs to this launch shape specifically. A normal launch is
    // left exactly as it was: it has a main window and a taskbar button, and
    // adding a tray there would only raise the question of why closing the
    // window still quits.
    createTray();
    createMiniplayerWindow();
    refreshTrayMenu();
  } else {
    createWindow();
    if (app.commandLine.hasSwitch("nova-miniplayer")) createMiniplayerWindow();
  }

  // macOS and Linux: Nova's pointer overlay and the stop key (Windows' engine
  // draws and registers these itself).
  const pointerOverlay = require("./pointer-overlay.cjs");
  pointerOverlay.start(PORT);

  app.on("activate", () => {
    if (!BrowserWindow.getAllWindows().some((w) => !pointerOverlay.isOverlay(w))) showMainWindow();
  });
});

app.on("window-all-closed", () => {
  // Closing the pet must not take Nova down with it. In a miniplayer-only
  // launch there is no main window to fall back to, so quitting here would
  // mean the pet's own close button silently stops the backend, the wake
  // word and every scheduled job. The tray is how you quit, or come back.
  if (miniplayerOnlyLaunch && !quitting) {
    refreshTrayMenu();
    return;
  }
  stopBackendProcess();
  stopWorkspaceMcpProcesses();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  quitting = true;
  stopBackendProcess();
  stopWorkspaceMcpProcesses();
  globalShortcut.unregisterAll();
});
