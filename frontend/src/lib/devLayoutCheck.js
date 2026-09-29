/** Dev-only automated layout check (task: "Add a development-only automated
 * layout check that reports any element whose right edge exceeds the
 * viewport or whose scroll width exceeds its client width. Do not show that
 * checker in the normal user interface"). Console-only, never rendered --
 * import.meta.env.DEV is a compile-time constant, so this whole module and
 * its call site in main.jsx are dropped by Rollup's tree-shaking in a
 * production build (confirmed the same way ReactorDevHarness's removal was
 * confirmed: grepping dist/assets/*.js for this file's own strings after a
 * real `npm run build`).
 *
 * Intentional exception (task: "only the code text editor, if needed"):
 * an element opts out by carrying `data-allow-horizontal-scroll` -- used by
 * CodeEditor.jsx's own code surface, which needs real horizontal scrolling
 * for long lines and is explicitly not a violation of the no-horizontal-
 * scroll rule.
 */

function isExemptFromHorizontalScrollCheck(el) {
  return Boolean(el.closest?.("[data-allow-horizontal-scroll]"));
}

/** An element whose own box extends past the viewport is only a REAL
 * problem (a visible horizontal scrollbar, or the document literally
 * growing wider) if nothing between it and the page actually clips that
 * overflow away first. A common, correct pattern this app uses (e.g.
 * WorkspaceTab's pannable/zoomable ModelNetwork canvas) is a large
 * absolutely-positioned surface inside an `overflow-hidden` viewport --
 * `getBoundingClientRect()` still reports that surface's full,
 * un-clipped box, which would otherwise show up here as a false
 * "violation" despite there being zero real overflow (confirmed by
 * checking `document.documentElement.scrollWidth` directly, which this
 * function's callers should trust as the ground truth over any single
 * element's rect). This walks up the ancestor chain and returns true the
 * moment it finds an `overflow-x: hidden|clip` container that itself does
 * NOT overflow the viewport -- i.e. a container that is genuinely doing
 * its job of clipping. */
function isClippedByAnAncestor(el, viewportWidth) {
  let node = el.parentElement;
  while (node && node !== document.body) {
    const style = window.getComputedStyle(node);
    if (style.overflowX === "hidden" || style.overflowX === "clip" || style.overflow === "hidden") {
      const rect = node.getBoundingClientRect();
      if (rect.right - viewportWidth <= 1 && rect.left >= -1) return true;
    }
    node = node.parentElement;
  }
  return false;
}

export function checkLayoutOverflow({ log = true } = {}) {
  const viewportWidth = window.innerWidth;
  const violations = [];
  const all = document.querySelectorAll("body *");
  for (const el of all) {
    if (isExemptFromHorizontalScrollCheck(el)) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue; // not rendered (display:none, detached, etc.)
    const rawRightEdgeOverflow = rect.right - viewportWidth;
    const rightEdgeOverflow = rawRightEdgeOverflow > 1 && isClippedByAnAncestor(el, viewportWidth) ? 0 : rawRightEdgeOverflow;
    // scrollWidth > clientWidth is completely normal (and intended) for any
    // `overflow: hidden` truncation -- e.g. Tailwind's `truncate` -- since
    // that's clipped content, not a scrollable/visible overflow. Only flag
    // it when the element's own overflow-x would actually let that extra
    // width become a real horizontal scrollbar or pannable region.
    const overflowX = window.getComputedStyle(el).overflowX;
    const scrollOverflow = overflowX === "auto" || overflowX === "scroll" ? el.scrollWidth - el.clientWidth : 0;
    if (rightEdgeOverflow > 1 || scrollOverflow > 1) {
      violations.push({
        element: el,
        selector: describe(el),
        rightEdgeOverflowPx: Math.round(rightEdgeOverflow),
        scrollOverflowPx: Math.round(scrollOverflow),
      });
    }
  }
  // Ground truth (task: "reports any element whose right edge exceeds the
  // viewport or whose scroll width exceeds its client width" -- this is the
  // document-level version of that same check, and the one that actually
  // determines whether a real horizontal scrollbar exists).
  const documentOverflowPx = document.documentElement.scrollWidth - document.documentElement.clientWidth;
  if (log) {
    if (violations.length === 0 && documentOverflowPx <= 1) {
      // eslint-disable-next-line no-console
      console.log(`[layout-check] no horizontal overflow at ${viewportWidth}px viewport width.`);
    } else {
      // eslint-disable-next-line no-console
      console.warn(
        `[layout-check] documentOverflowPx=${documentOverflowPx}, ${violations.length} element-level violation(s) at ${viewportWidth}px:`,
        violations
      );
    }
  }
  return violations;
}

function describe(el) {
  const id = el.id ? `#${el.id}` : "";
  const cls = typeof el.className === "string" && el.className ? `.${el.className.trim().split(/\s+/).slice(0, 3).join(".")}` : "";
  return `${el.tagName.toLowerCase()}${id}${cls}`;
}

/** Wires the checker to run automatically (debounced) on resize, plus once
 * shortly after initial mount, and exposes `window.__checkLayoutOverflow`
 * for a manual check from the devtools console at any window size during
 * testing. Call once from main.jsx, DEV-only. */
export function installDevLayoutCheck() {
  window.__checkLayoutOverflow = checkLayoutOverflow;
  let timer = null;
  const scheduled = () => {
    clearTimeout(timer);
    timer = setTimeout(() => checkLayoutOverflow(), 400);
  };
  window.addEventListener("resize", scheduled);
  setTimeout(() => checkLayoutOverflow(), 1500);
}
