import { javascript } from "@codemirror/lang-javascript";
import { python } from "@codemirror/lang-python";
import { html } from "@codemirror/lang-html";
import { css } from "@codemirror/lang-css";
import { json } from "@codemirror/lang-json";
import { markdown } from "@codemirror/lang-markdown";
import { rust } from "@codemirror/lang-rust";
import { cpp } from "@codemirror/lang-cpp";

/** Editor foundation (task: "language-aware highlighting"). Extension-based
 * detection, same approach any editor without a real language server uses
 * for "which grammar" -- content sniffing would be overkill for a file
 * tree/tabs editor like this one. Returns a CodeMirror language extension,
 * or null for a plain-text file (still gets soft-wrapping/search/undo from
 * the base editor either way -- language support is additive, not
 * required). */
export function languageForPath(path) {
  const ext = (path.split(".").pop() || "").toLowerCase();
  switch (ext) {
    case "js":
    case "mjs":
    case "cjs":
      return javascript();
    case "jsx":
      return javascript({ jsx: true });
    case "ts":
      return javascript({ typescript: true });
    case "tsx":
      return javascript({ jsx: true, typescript: true });
    case "py":
    case "pyw":
      return python();
    case "html":
    case "htm":
      return html();
    case "css":
      return css();
    case "json":
      return json();
    case "md":
    case "markdown":
      return markdown();
    case "rs":
      return rust();
    case "c":
    case "h":
    case "cpp":
    case "cc":
    case "cxx":
    case "hpp":
      return cpp();
    default:
      return null;
  }
}
