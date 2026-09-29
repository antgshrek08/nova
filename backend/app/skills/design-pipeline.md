---
name: design-pipeline
description: Design a site as a system first, then build it section by section and prove it works, instead of prompting "make it look better" repeatedly.
keywords: [design system, design.md, product.md, look better, redesign, site design, visual design, ui design, landing page, style guide, design tokens, type scale, spacing scale, figma]
---

The failure mode this exists to prevent: starting from "build me a site", then
steering with twenty rounds of "make it look nicer". Decide what good looks like
in writing first, and every later step has something to check itself against.

**1. Write the standard before building anything.**
Produce two files at the project root, and name them explicitly in later
requests — files sitting in a project are not read automatically.

- `PRODUCT.md` — what is being built and for whom.
- `DESIGN.md` — the visual system. Derive it rather than invent it: take two or
  three sites the user admires and extract, for each, the type scale and the
  ratio behind it, the spacing unit and how consistently it is applied, how many
  font weights and where each is used, how hierarchy is achieved without
  decoration, and what they deliberately do *not* do. Then synthesise the single
  system those sites agree on, adapted to this project's brand — not a copy of
  any one of them.

**2. If a real design exists, read it before coding.**
With a Figma file, report every distinct text style and its values, every
spacing value and which ones are inconsistent with the rest, every colour and
whether they resolve to a coherent palette, and anything that will not translate
directly to CSS. Then stop and confirm. Reading and immediately building means
discovering the misunderstanding after 800 lines exist.

**3. Build in sections, never the whole page.**
Hero, then nav, then the next block. Not caution — compounding. A broken spacing
scale caught in the hero fixes the page; caught at the end it is a rewrite.
Constrain each section: every spacing value from the scale in `DESIGN.md` and no
arbitrary pixels, at most two font weights, no animation on the first pass,
semantic HTML rather than nested divs.

**4. Audit deterministically before arguing about taste.**
Run the objective pass first and fix what it finds, because those findings are
not matters of opinion — repeated identical spacing that should be a scale,
decorative gradients standing in for hierarchy, three weights where two would
do, everything centred, one radius and one shadow stamped on every block. Only
then apply judgement about whether the result is any good.

**5. Make it prove it works.**
Test the built page rather than assuming: click every interactive element and
report anything that does nothing; submit every form three ways (empty, garbage,
valid); render at 375, 768 and 1440 and report overflow, overlap or unreadable
text; report every console error; check every image has alt text and every
control is reachable by keyboard. Produce a pass/fail list and **fix nothing
yet**.

**Never let one step both find a problem and fix it.** Report first, fix second,
then re-run the same checks and show the new list. Combining them is how a small
fix becomes a silent rewrite.

Behavioural testing and visual audit are different instruments: a test driven by
the accessibility tree can pass a page that is visibly broken. Neither replaces
the other.

Once set up, a section is four moves — build against `DESIGN.md`, audit and fix,
test and report, fix failures and re-test. If output drifts generic several
sections in, that is context dilution: start fresh and let `DESIGN.md` carry the
standard instead of the conversation.
