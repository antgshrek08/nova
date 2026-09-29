import { useEffect, useRef, useState } from "react";

/** Breadcrumbs above the active file (task: "Main editor with open-file
 * tabs and breadcrumbs" / "breadcrumbs should collapse"). A long path in a
 * narrow window is exactly the horizontal-overflow risk the no-scrollbar
 * rule calls out -- rather than truncating (losing the folder names
 * entirely) or scrolling (a horizontal scrollbar), the middle segments
 * collapse into a single "…" that opens a real dropdown listing every
 * hidden segment, so the full path stays genuinely reachable, not just
 * visually implied. */
export default function Breadcrumbs({ path, workspaceName }) {
  const containerRef = useRef(null);
  const [collapsed, setCollapsed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const segments = path ? path.split("/") : [];

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    function check() {
      setCollapsed(el.scrollWidth > el.clientWidth + 1);
    }
    check();
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  if (!path) {
    return <div className="h-7 shrink-0 border-b border-charcoal-800 bg-charcoal-900/50" />;
  }

  // Always show the workspace root, the file itself, and its immediate
  // parent folder; collapse everything else in between (if anything) into
  // one dropdown -- keeps the common case (a shallow path) fully visible
  // with no collapsing at all.
  const hiddenMiddle = collapsed && segments.length > 3 ? segments.slice(0, segments.length - 2) : null;
  const visibleTail = hiddenMiddle ? segments.slice(segments.length - 2) : segments;

  return (
    <div ref={containerRef} className="flex h-7 min-w-0 shrink-0 items-center gap-1 overflow-hidden border-b border-charcoal-800 bg-charcoal-900/50 px-3 text-[11px] text-charcoal-500">
      <span className="shrink-0 font-medium text-charcoal-400">{workspaceName}</span>
      <span className="shrink-0 text-charcoal-700">/</span>
      {hiddenMiddle && (
        <>
          <div className="relative shrink-0">
            <button onClick={() => setMenuOpen((v) => !v)} className="rounded px-1 hover:bg-charcoal-800 hover:text-charcoal-200">
              …
            </button>
            {menuOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                <div className="absolute left-0 top-full z-20 max-h-72 w-64 overflow-y-auto rounded-b-md border border-charcoal-600 bg-charcoal-850 py-1 text-xs shadow-xl">
                  {hiddenMiddle.map((seg, i) => (
                    <div key={i} className="truncate px-3 py-1 text-charcoal-300" style={{ paddingLeft: `${12 + i * 10}px` }}>
                      {seg}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
          <span className="shrink-0 text-charcoal-700">/</span>
        </>
      )}
      {visibleTail.map((seg, i) => (
        <span key={i} className="flex min-w-0 shrink items-center gap-1">
          <span className={`truncate ${i === visibleTail.length - 1 ? "text-charcoal-300" : ""}`}>{seg}</span>
          {i < visibleTail.length - 1 && <span className="shrink-0 text-charcoal-700">/</span>}
        </span>
      ))}
    </div>
  );
}
