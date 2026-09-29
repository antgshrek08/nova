---
name: browser-testing
description: Prove a page works in a real browser — interactions, forms, breakpoints, console, accessibility — and report before fixing.
keywords: [playwright, browser test, e2e, end to end, test the page, responsive, breakpoint, console errors, accessibility, a11y, does it work, broken]
---

Testing a page means driving it, not reading its source. The output of a test
run is a pass/fail list, and nothing gets fixed in the same breath.

Cover five things, in this order:

1. **Every interactive element** — click it, and report anything that does
   nothing. A button wired to no handler looks identical to one that works.
2. **Every form, three ways** — empty, garbage, and valid. Most forms handle the
   third and fall over on the first two.
3. **Three widths — 375, 768, 1440** — reporting overflow, overlap, and text
   that becomes unreadable. Horizontal scroll on a phone is a bug, not a
   preference.
4. **The console** — every error, including the ones that do not visibly break
   anything yet.
5. **Reachability** — every image has alt text, every control can be reached and
   operated by keyboard.

Then stop. Report the list and fix nothing.

Fixing comes as a separate pass that touches only the failures, shows the diff,
and re-runs the same tests to produce a new list. When one pass both finds and
fixes, a small correction turns into a silent rewrite nobody reviewed.

Know the blind spot: a browser test driven by the accessibility tree checks
behaviour, not appearance. It will happily pass a page whose layout is visibly
broken. Visual problems need a visual pass. Reporting "all tests pass" about a
page that looks wrong is worse than saying nothing, because it sounds like
evidence.
