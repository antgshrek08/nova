import { useEffect, useState } from "react";
import NovaLogo from "../NovaLogo.jsx";

export default function TitleBar({ onOpenSettings, onOpenOnboarding }) {
  const [isMaximized, setIsMaximized] = useState(false);
  const [alwaysOnTop, setAlwaysOnTop] = useState(false);

  useEffect(() => {
    if (window.electronAPI?.isWindowMaximized) {
      window.electronAPI.isWindowMaximized().then(setIsMaximized).catch(() => {});
    }
  }, []);

  function handleMinimize() {
    window.electronAPI?.minimizeWindow?.();
  }

  function handleMaximize() {
    window.electronAPI?.maximizeWindow?.();
    setIsMaximized(!isMaximized);
  }

  function handleClose() {
    window.electronAPI?.closeWindow?.();
  }

  function toggleAlwaysOnTop() {
    const next = !alwaysOnTop;
    setAlwaysOnTop(next);
    window.electronAPI?.setAlwaysOnTop?.(next);
  }

  // Only render if electronAPI exists (or in web dev mode, render mock title bar)
  const isElectron = Boolean(window.electronAPI);
  const platform = window.electronAPI?.platform || (typeof navigator !== "undefined" && /Mac/i.test(navigator.userAgent) ? "darwin" : "win32");
  const isMac = platform === "darwin";

  return (
    <header
      className={`flex h-9 w-full select-none items-center justify-between border-b border-charcoal-800/80 bg-charcoal-950/95 ${isMac ? "pl-20 pr-3" : "px-3"} backdrop-blur-md z-50 text-[12px] text-charcoal-300`}
      style={{ WebkitAppRegion: "drag" }}
    >
      {/* Left: App Logo & Brand */}
      <div className="flex items-center gap-2" style={{ WebkitAppRegion: "no-drag" }}>
        <NovaLogo size={18} animate={false} />
        <span className="font-semibold tracking-wide text-zinc-100 text-[12.5px]">
          Nova
        </span>
        <span className="rounded-full bg-blue-500/10 px-2 py-0.2 text-[10px] font-medium text-blue-400 border border-blue-500/20">
          v2.0
        </span>
      </div>

      {/* Center: Workspace Status */}
      <div className="flex items-center gap-2 text-[11px]">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        <span className="text-zinc-300 font-medium">Academic Workspace</span>
        <span className="text-zinc-600">·</span>
        <span className="text-zinc-500">Canvas Sync Active</span>
      </div>

      {/* Right: Window Controls */}
      <div className="flex items-center gap-1" style={{ WebkitAppRegion: "no-drag" }}>
        {/* Guide / Onboarding shortcut */}
        {onOpenOnboarding && (
          <button
            onClick={onOpenOnboarding}
            title="Setup & Onboarding Wizard"
            className="rounded px-2 py-1 text-[11px] text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 transition-colors"
          >
            Setup Guide
          </button>
        )}

        {/* Pin Always on Top Toggle */}
        {isElectron && (
          <button
            onClick={toggleAlwaysOnTop}
            title={alwaysOnTop ? "Unpin window (normal layering)" : "Pin window always on top"}
            className={`rounded p-1.5 transition-colors ${
              alwaysOnTop
                ? "bg-emerald-500/20 text-emerald-300"
                : "text-charcoal-400 hover:bg-charcoal-800 hover:text-charcoal-200"
            }`}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="17" x2="12" y2="22"></line>
              <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"></path>
            </svg>
          </button>
        )}

        {/* Window controls (Windows and Linux) */}
        {!isMac && (
          <>
            {/* Minimize */}
            <button
              onClick={handleMinimize}
              title="Minimize"
              className="flex h-6 w-8 items-center justify-center rounded text-charcoal-400 hover:bg-charcoal-800 hover:text-charcoal-100 transition-colors"
            >
              <svg width="10" height="2" viewBox="0 0 10 2" fill="currentColor">
                <rect width="10" height="2" rx="1" />
              </svg>
            </button>

            {/* Maximize / Restore */}
            <button
              onClick={handleMaximize}
              title={isMaximized ? "Restore" : "Maximize"}
              className="flex h-6 w-8 items-center justify-center rounded text-charcoal-400 hover:bg-charcoal-800 hover:text-charcoal-100 transition-colors"
            >
              {isMaximized ? (
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <rect x="2.5" y="0.5" width="7" height="7" rx="1" />
                  <path d="M0.5 3.5V9.5H6.5" />
                </svg>
              ) : (
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <rect x="0.5" y="0.5" width="9" height="9" rx="1" />
                </svg>
              )}
            </button>

            {/* Close */}
            <button
              onClick={handleClose}
              title="Close"
              className="flex h-6 w-8 items-center justify-center rounded text-charcoal-400 hover:bg-rose-600 hover:text-white transition-colors"
            >
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <line x1="1" y1="1" x2="9" y2="9" />
                <line x1="9" y1="1" x2="1" y2="9" />
              </svg>
            </button>
          </>
        )}
      </div>
    </header>
  );
}
