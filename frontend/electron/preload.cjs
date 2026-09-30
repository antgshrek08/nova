const { contextBridge, ipcRenderer } = require("electron");

// The renderer talks to the FastAPI backend directly over
// http://localhost:8000 for everything except real OS-level integrations
// that only the main process can do -- "Launch at login" (Settings >
// General, needs app.setLoginItemSettings) and the miniplayer window
// (Settings > General "Open miniplayer" button, plus the miniplayer's own
// "Full Screen" button calling back the other way -- see
// electron/main.cjs's createMiniplayerWindow/ipcMain handlers).
contextBridge.exposeInMainWorld("electronAPI", {
  getDesktopActivity: () => ipcRenderer.invoke("get-desktop-activity"),
  claimMicrophone: (token, background) => ipcRenderer.invoke("claim-microphone", token, background),
  onYieldMicrophone: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("yield-microphone", listener);
    return () => ipcRenderer.removeListener("yield-microphone", listener);
  },
  releaseVoiceAudio: () => ipcRenderer.send("release-voice-audio"),
  // Stop Nova talking in every window (the main app and the miniplayer).
  silenceVoice: () => ipcRenderer.send("silence-voice"),
  releaseMicrophone: (token) => ipcRenderer.send("release-microphone", token),
  claimVoiceAudio: () => ipcRenderer.invoke("claim-voice-audio"),
  onStopVoiceAudio: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("stop-voice-audio", listener);
    return () => ipcRenderer.removeListener("stop-voice-audio", listener);
  },
  setLaunchAtLogin: (enabled, miniplayerOnly) =>
    ipcRenderer.invoke("set-launch-at-login", enabled, miniplayerOnly),
  chooseProjectFolder: () => ipcRenderer.invoke("choose-project-folder"),
  openMiniplayer: () => ipcRenderer.invoke("open-miniplayer"),
  closeMiniplayer: () => ipcRenderer.invoke("close-miniplayer"),
  // Returns { count, index } so the miniplayer can hide its own monitor
  // button when there is only one screen to be on.
  miniplayerDisplays: () => ipcRenderer.invoke("miniplayer-displays"),
  moveMiniplayerToNextDisplay: () => ipcRenderer.invoke("miniplayer-next-display"),
  focusMainWindow: () => ipcRenderer.invoke("focus-main-window"),
  openDesktopPet: () => ipcRenderer.invoke("open-desktop-pet"),
  closeDesktopPet: () => ipcRenderer.invoke("close-desktop-pet"),
  setDesktopPetClickThrough: (ignore) => ipcRenderer.invoke("set-desktop-pet-click-through", ignore),
  registerPushToTalkHotkey: (accelerator) => ipcRenderer.invoke("register-push-to-talk-hotkey", accelerator),
  // NovaReactorWindow.jsx subscribes to this to trigger its own mic toggle when
  // the global push-to-talk hotkey fires (see main.cjs's triggerPushToTalk).
  // Returns an unsubscribe function -- the listener must be removed on
  // unmount, not left to accumulate across HMR reloads in dev.
  onPushToTalkTriggered: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("push-to-talk-triggered", listener);
    return () => ipcRenderer.removeListener("push-to-talk-triggered", listener);
  },
  platform: process.platform,
  minimizeWindow: () => ipcRenderer.invoke("minimize-window"),
  maximizeWindow: () => ipcRenderer.invoke("maximize-window"),
  closeWindow: () => ipcRenderer.invoke("close-window"),
  isWindowMaximized: () => ipcRenderer.invoke("is-window-maximized"),
  setAlwaysOnTop: (flag) => ipcRenderer.invoke("set-always-on-top", flag),
  getMiniplayerPinned: () => ipcRenderer.invoke("get-miniplayer-pinned"),
  setMiniplayerPinned: (flag) => ipcRenderer.invoke("set-miniplayer-pinned", flag),
  setMiniplayerHitRects: (rects) => ipcRenderer.send("miniplayer-hit-rects", rects),
  openLink: (url) => ipcRenderer.invoke("open-link", url),
  showMainWindow: () => ipcRenderer.invoke("show-main-window"),
});
