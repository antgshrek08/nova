import { useCallback, useEffect, useRef } from "react";

const MIN_WIDTH = 300;
// Raised from 620: on a wide monitor the conversation is the thing being read,
// and the reactor stage beside it stays legible at any size, so there is no
// reason to stop the user giving the transcript half the window.
const MAX_WIDTH = 900;
const COLLAPSED_WIDTH = 44;
const STORAGE_KEY = "nova.transcriptPanel.width";

/** Default width for a first run: a share of the window rather than a flat
 * 320px. The fixed default was set against a small window and left the actual
 * conversation in a column narrower than the decorative reactor beside it on
 * any normal monitor -- messages wrapped every five or six words. A stored
 * width always wins; this only decides where a new install starts. */
function defaultWidth() {
  const available = typeof window === "undefined" ? 1280 : window.innerWidth;
  return Math.round(Math.min(560, Math.max(380, available * 0.38)));
}

export function loadTranscriptWidth() {
  const stored = Number(localStorage.getItem(STORAGE_KEY));
  return Number.isFinite(stored) && stored >= MIN_WIDTH && stored <= MAX_WIDTH ? stored : defaultWidth();
}

/** Resizable, collapsible right-hand transcript panel (task: "A resizable,
 * collapsible transcript panel on the RIGHT, containing messages, links,
 * attachments, and a typing input"). Purely a layout shell -- messages,
 * attachments, and the input row are ChatWindow's existing JSX, passed in
 * as children -- so none of that logic gets duplicated. Width persists
 * across sessions (localStorage) the same way collapsed state does, since a
 * user who narrows/widens or collapses this once almost certainly wants
 * that choice to stick on the next launch, not silently reset. */
export default function TranscriptPanel({ width, onWidthChange, collapsed, onToggleCollapsed, onNewChat, focusMode, onToggleFocusMode, children }) {
  const draggingRef = useRef(false);

  const handleDragMove = useCallback(
    (e) => {
      if (!draggingRef.current) return;
      const proposed = window.innerWidth - e.clientX;
      onWidthChange(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, proposed)));
    },
    [onWidthChange]
  );

  const handleDragEnd = useCallback(() => {
    draggingRef.current = false;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    window.removeEventListener("mousemove", handleDragMove);
    window.removeEventListener("mouseup", handleDragEnd);
  }, [handleDragMove]);

  function handleDragStart(e) {
    if (collapsed) return;
    // Real bug found live: without preventDefault, a fast drag across the
    // reactor stage's text ("N.O.V.A." / the state label) started a native
    // text-selection drag alongside the resize, which could even summon a
    // browser extension's selection popup mid-drag. userSelect: none on top
    // covers the parts of the drag path preventDefault's per-event timing
    // can miss.
    e.preventDefault();
    draggingRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", handleDragMove);
    window.addEventListener("mouseup", handleDragEnd);
  }

  useEffect(() => () => handleDragEnd(), [handleDragEnd]);

  return (
    <div
      // On a phone this is the whole screen, so the pixel width -- which
      // exists for the desktop drag handle -- must not apply. w-full wins
      // below sm:, and sm:w-[--panel-width] restores the dragged size above
      // it. Setting the width only through the custom property keeps one
      // source of truth rather than a style attribute fighting a class.
      className="relative flex h-full w-full shrink-0 flex-col border-l border-charcoal-700 bg-charcoal-850 transition-[width] duration-150 sm:w-[--panel-width]"
      style={{ "--panel-width": `${collapsed ? COLLAPSED_WIDTH : width}px` }}
    >
      {!collapsed && (
        <div
          onMouseDown={handleDragStart}
          title="Drag to resize"
          className="absolute left-0 top-0 z-10 h-full w-1.5 -translate-x-1/2 cursor-col-resize hover:bg-emerald-500/30"
        />
      )}

      <div className="flex shrink-0 items-center justify-between border-b border-charcoal-700 px-4 py-3">
        {!collapsed && <span className="text-sm font-medium text-charcoal-300">Transcript</span>}
        <div className="flex items-center gap-1">
          {/* Task: "Keep a clear New conversation action in Chat" -- History
              itself moved into Memory this pass, but starting a fresh chat
              is common enough (and different enough from "browse old ones")
              that it stays directly on the Chat screen. */}
          {!collapsed && onNewChat && (
            <button
              onClick={onNewChat}
              title="Start a new conversation"
              className="rounded-md px-2 py-1 text-xs font-medium text-charcoal-400 hover:bg-charcoal-800 hover:text-charcoal-200"
            >
              + New
            </button>
          )}
          {!collapsed && onToggleFocusMode && (
            <button
              onClick={onToggleFocusMode}
              title={focusMode ? "Switch to Split Stage View" : "Focus Mode (Dynamic Island)"}
              className="hidden sm:flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-charcoal-400 hover:bg-charcoal-800 hover:text-charcoal-200 transition-colors"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <path d="M9 3v18" />
              </svg>
              <span>{focusMode ? "Stage" : "Focus"}</span>
            </button>
          )}
          {/* Desktop-only. On a phone this panel is the entire screen, so
              collapsing it to a 44px vertical rail reading "Transcript"
              sideways leaves nowhere to go and nothing to read. */}
          <button
            onClick={onToggleCollapsed}
            title={collapsed ? "Expand transcript" : "Collapse transcript"}
            className={`hidden h-6 w-6 items-center justify-center rounded-md text-charcoal-400 hover:bg-charcoal-800 hover:text-charcoal-200 sm:flex ${
              collapsed ? "mx-auto" : ""
            }`}
          >
            <ChevronIcon flipped={!collapsed} />
          </button>
        </div>
      </div>

      {collapsed ? (
        <button
          onClick={onToggleCollapsed}
          title="Expand transcript"
          className="flex flex-1 items-center justify-center text-charcoal-500 hover:text-emerald-400"
        >
          <span className="rotate-90 whitespace-nowrap text-sm font-medium">Transcript</span>
        </button>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      )}
    </div>
  );
}

function ChevronIcon({ flipped }) {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      style={{ transform: flipped ? "rotate(180deg)" : "none" }}
    >
      <polyline points="9 6 15 12 9 18" />
    </svg>
  );
}
