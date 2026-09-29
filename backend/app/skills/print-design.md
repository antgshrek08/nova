---
name: print-design
description: Print-ready flyers, CVs, posters and cards built in HTML/CSS and exported to PDF from Chrome, instead of Canva
keywords: [flyer, poster, print ready, print-ready, pdf export, a5, a4, a6, business card, leaflet, brochure, cv in html, resume in html, instead of canva, canva, print css, page size, save as pdf, bleed, crop marks, booklet]
---

Design documents as HTML/CSS and export them from Chrome. The page becomes exact, versionable, diffable, and free — no subscription, no watermark, no export cap.

Approach adapted from TeeBo Studio's writeup (teebostudio.fr/blog/html-css-cv-flyer-canva). The `@page` trick is theirs; the specifics below are the parts a browser actually requires, which that article does not cover.

## The skeleton

```css
@page { size: A5; margin: 0; }          /* A5 148×210mm. Also: A4, A6, Letter, "A4 landscape" */

html, body { margin: 0; padding: 0; }

.page {
  width: 148mm;
  height: 210mm;                        /* exact page height, not min-height */
  overflow: hidden;                     /* a 1mm overflow silently becomes a blank second page */
  box-sizing: border-box;
  padding: 12mm;                        /* your safe margin — keep text inside it */
  position: relative;
}

.page + .page { break-before: page; }   /* multi-page: one .page per sheet */
```

Use **mm and pt throughout**, never px. Browsers map px to print at 96dpi, so the numbers stop meaning anything physical and nothing lines up with what a printer expects.

## The line everyone forgets

```css
* { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
```

Without it Chrome drops background colours and images when printing, and a dark flyer comes out as black text on white paper. This is the single most common reason "it looked right in the browser."

The user must also tick **Background graphics** in Chrome's print dialog — the CSS alone is not enough.

## Screen vs print

Design against the real page on screen, then strip the screen-only chrome:

```css
@media screen {
  body { background: #333; padding: 20mm; }     /* desk around the page */
  .page { box-shadow: 0 0 10mm rgba(0,0,0,.5); margin: 0 auto 10mm; }
}
@media print {
  .page { box-shadow: none; margin: 0; }
  .no-print { display: none !important; }
}
```

## Exporting

Ctrl/Cmd+P → Destination **Save as PDF** → Margins **None** → **Background graphics** on. Chrome only; Firefox and Safari handle `@page size` less reliably.

If a stray blank page appears, something is one hair over the page height — usually a trailing `<br>`, a margin collapsing out of the last element, or `height: 100%` on a body with padding.

## For a commercial printer

- **Bleed**: make the page 3mm larger on each side and push background art to the edge of that. A5 with bleed is `@page { size: 154mm 216mm; }`, with your 148×210 trim area centred. Ask the printer whether they want crop marks; browsers cannot generate them, so draw them as absolutely positioned elements or let the printer add them.
- **Colour**: browsers are sRGB only and cannot output CMYK. Say this plainly to the user — saturated screen colours, especially bright blues and greens, will shift when converted. For anything commercially printed, warn them to expect a proof.
- **Images**: 300dpi at final physical size. A photo placed 60mm wide needs ~700px. Screenshots and web images will look soft.
- **Fonts**: embed with `@font-face` pointing at a local file, or base64 the woff2 into the CSS so the file is self-contained. A Google Fonts `<link>` fails if the machine is offline at print time, and silently falls back.

## Typesetting a CV

```css
h2 { break-after: avoid; }              /* no heading stranded at a page foot */
.entry { break-inside: avoid; }         /* a job doesn't split across pages */
p { orphans: 2; widows: 2; }
```

Two variants from one file is worth doing — a dark version for screen and colour printing, a light version that does not drain a laser cartridge. Drive it from a class on `<body>` and one set of custom properties, not two stylesheets.

## Working with the user

Build the whole thing as one self-contained HTML file with the CSS inline — it emails, it versions, and it opens anywhere.

Use Nova's browser tools to actually open the file and screenshot it rather than asking the user whether it looks right. Check the page count before handing it over; an accidental second page is the most common defect and it is invisible in the editor.

Ask for the real content first — the actual name, the actual services, the actual phone number. Never ship a design full of lorem ipsum or invented details unless the user explicitly asks for a template.
