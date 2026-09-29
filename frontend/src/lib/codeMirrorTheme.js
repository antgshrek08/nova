import { EditorView } from "@codemirror/view";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";

/** Code tab's own editor theme -- charcoal surfaces, restrained emerald
 * accents (design direction), built directly on CodeMirror's own theming
 * API rather than importing a mismatched pre-built theme (One Dark, etc.)
 * that wouldn't share this app's actual palette. Kept in its own module
 * since it's pure configuration, reused by every open tab's editor
 * instance. */
export const editorTheme = EditorView.theme(
  {
    "&": {
      color: "#e6ebe8", // charcoal-100
      backgroundColor: "#0a0b0c", // charcoal-950
      height: "100%",
      fontSize: "13px",
    },
    ".cm-content": {
      caretColor: "#34d399", // emerald-400
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
      padding: "8px 0",
    },
    ".cm-cursor, .cm-dropCursor": { borderLeftColor: "#34d399" },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
      backgroundColor: "rgba(16,185,129,0.25)",
    },
    ".cm-panels": { backgroundColor: "#131416", color: "#e6ebe8", borderColor: "#2b2e33" }, // charcoal-900 / charcoal-100 / charcoal-700
    ".cm-panels.cm-panels-top": { borderBottom: "1px solid #2b2e33" },
    ".cm-panels.cm-panels-bottom": { borderTop: "1px solid #2b2e33" },
    ".cm-searchMatch": { backgroundColor: "rgba(217,180,90,0.25)", outline: "1px solid rgba(217,180,90,0.4)" },
    ".cm-searchMatch.cm-searchMatch-selected": { backgroundColor: "rgba(16,185,129,0.35)" },
    ".cm-activeLine": { backgroundColor: "rgba(255,255,255,0.03)" },
    ".cm-activeLineGutter": { backgroundColor: "rgba(255,255,255,0.04)" },
    ".cm-gutters": {
      backgroundColor: "#0a0b0c",
      color: "#565b62", // charcoal-500
      border: "none",
      borderRight: "1px solid #202226", // charcoal-800
    },
    ".cm-lineNumbers .cm-gutterElement": { padding: "0 8px 0 12px" },
    ".cm-foldPlaceholder": { backgroundColor: "#202226", border: "none", color: "#8b9098" },
    ".cm-tooltip": { backgroundColor: "#191b1e", border: "1px solid #2b2e33", color: "#e6ebe8" },
    ".cm-tooltip-autocomplete ul li[aria-selected]": { backgroundColor: "rgba(16,185,129,0.2)" },
    "&.cm-editor.cm-focused": { outline: "none" },
  },
  { dark: true }
);

export const editorHighlightStyle = HighlightStyle.define([
  { tag: t.keyword, color: "var(--cm-keyword, #6ee7b7)" }, // emerald-300
  { tag: [t.name, t.deleted, t.character, t.macroName], color: "var(--cm-text, #e6ebe8)" },
  { tag: [t.function(t.variableName), t.labelName], color: "var(--cm-func, #7dd3fc)" }, // sky-300
  { tag: [t.color, t.constant(t.name), t.standard(t.name)], color: "var(--cm-const, #fbbf24)" }, // amber-400
  { tag: [t.definition(t.name), t.separator], color: "var(--cm-text, #e6ebe8)" },
  { tag: [t.typeName, t.className, t.number, t.changed, t.annotation, t.modifier, t.self, t.namespace], color: "var(--cm-const, #fbbf24)" },
  { tag: [t.operator, t.operatorKeyword, t.url, t.escape, t.regexp, t.link], color: "var(--cm-op, #b4b8bd)" },
  { tag: [t.meta, t.comment], color: "var(--cm-comment, #565b62)", fontStyle: "italic" },
  { tag: t.strong, fontWeight: "bold" },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: t.strikethrough, textDecoration: "line-through" },
  { tag: t.link, color: "var(--cm-func, #7dd3fc)", textDecoration: "underline" },
  { tag: t.heading, fontWeight: "bold", color: "var(--cm-keyword, #6ee7b7)" },
  { tag: [t.atom, t.bool, t.special(t.variableName)], color: "var(--cm-const, #fbbf24)" },
  { tag: [t.processingInstruction, t.string, t.inserted], color: "var(--cm-string, #a3e635)" }, // lime-400
  { tag: t.invalid, color: "var(--cm-invalid, #fb7185)" }, // rose-400
]);

export const editorSyntaxHighlighting = syntaxHighlighting(editorHighlightStyle);
