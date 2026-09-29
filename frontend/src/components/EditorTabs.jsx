import { useEffect, useRef, useState } from "react";

function fileName(path) {
  return path.split("/").pop() || path;
}

/** Open-file tabs (task: "Main editor with open-file tabs and breadcrumbs").
 * Task: "Open-file tabs should use an overflow menu ... Keep all content
 * and controls accessible; merely clipping overflow is insufficient" -- a
 * ResizeObserver on the strip measures which tabs actually fit and moves
 * the rest into a real "N more" dropdown listing every overflowed tab by
 * name, rather than letting `overflow-x` clip them out of reach (which is
 * exactly the global no-horizontal-scrollbar rule this app now holds
 * everywhere). Dirty dot mirrors the old editor's "unsaved changes"
 * indicator; a close button asks its caller (CodeTab) to confirm when the
 * file is actually dirty, never a silent close of real unsaved edits. */
export default function EditorTabs({ openPaths, activePath, isDirty, onSelect, onClose }) {
  const containerRef = useRef(null);
  const [visibleCount, setVisibleCount] = useState(openPaths.length);
  const [overflowOpen, setOverflowOpen] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const TAB_ESTIMATE_WIDTH = 160;
    const MORE_BUTTON_WIDTH = 64;

    function recompute() {
      const available = container.clientWidth;
      const fitsAll = Math.floor(available / TAB_ESTIMATE_WIDTH);
      if (fitsAll >= openPaths.length) {
        setVisibleCount(openPaths.length);
      } else {
        const fitsWithMore = Math.max(1, Math.floor((available - MORE_BUTTON_WIDTH) / TAB_ESTIMATE_WIDTH));
        setVisibleCount(Math.min(fitsWithMore, openPaths.length));
      }
    }
    recompute();
    const observer = new ResizeObserver(recompute);
    observer.observe(container);
    return () => observer.disconnect();
  }, [openPaths.length]);

  // Always keep the active tab actually visible, even if it'd otherwise
  // fall past the fitted count -- swap it in for the last visible slot
  // rather than hiding the one tab the user is looking at.
  const activeIndex = openPaths.indexOf(activePath);
  let visible = openPaths.slice(0, visibleCount);
  let overflowed = openPaths.slice(visibleCount);
  if (activeIndex >= visibleCount && activeIndex !== -1) {
    overflowed = openPaths.filter((p, i) => i >= visibleCount && p !== activePath);
    visible = [...openPaths.slice(0, visibleCount - 1), activePath];
  }

  if (openPaths.length === 0) {
    return <div className="h-9 shrink-0 border-b border-charcoal-700 bg-charcoal-900" />;
  }

  return (
    <div ref={containerRef} className="flex h-9 min-w-0 shrink-0 items-stretch border-b border-charcoal-700 bg-charcoal-900">
      <div className="flex min-w-0 flex-1 items-stretch overflow-hidden">
        {visible.map((path) => (
          <Tab
            key={path}
            path={path}
            active={path === activePath}
            dirty={isDirty(path)}
            onSelect={() => onSelect(path)}
            onClose={() => onClose(path)}
          />
        ))}
      </div>
      {overflowed.length > 0 && (
        <div className="relative shrink-0">
          <button
            onClick={() => setOverflowOpen((v) => !v)}
            className="flex h-full items-center gap-1 border-l border-charcoal-700 px-2.5 text-[11px] font-medium text-charcoal-400 hover:bg-charcoal-800 hover:text-charcoal-200"
            title={`${overflowed.length} more open file${overflowed.length === 1 ? "" : "s"}`}
          >
            +{overflowed.length} <span aria-hidden>▾</span>
          </button>
          {overflowOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setOverflowOpen(false)} />
              <div className="absolute right-0 top-full z-20 max-h-80 w-64 overflow-y-auto rounded-b-md border border-charcoal-600 bg-charcoal-850 py-1 shadow-xl">
                {overflowed.map((path) => (
                  <button
                    key={path}
                    onClick={() => {
                      onSelect(path);
                      setOverflowOpen(false);
                    }}
                    className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-xs text-charcoal-200 hover:bg-charcoal-800"
                    title={path}
                  >
                    {isDirty(path) && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />}
                    <span className="truncate">{fileName(path)}</span>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Tab({ path, active, dirty, onSelect, onClose }) {
  return (
    <div
      onClick={onSelect}
      title={path}
      className={`group flex min-w-0 max-w-[180px] shrink-0 cursor-pointer items-center gap-1.5 border-r border-charcoal-800 px-3 text-xs transition-colors ${
        active ? "bg-charcoal-950 text-charcoal-100" : "text-charcoal-400 hover:bg-charcoal-850 hover:text-charcoal-200"
      }`}
    >
      <span className="min-w-0 flex-1 truncate">{fileName(path)}</span>
      {dirty ? (
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" title="Unsaved changes" />
      ) : (
        <span className="h-1.5 w-1.5 shrink-0" />
      )}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
        className="shrink-0 rounded px-0.5 text-charcoal-600 opacity-0 hover:bg-charcoal-700 hover:text-charcoal-200 group-hover:opacity-100"
        title="Close"
      >
        ×
      </button>
    </div>
  );
}
