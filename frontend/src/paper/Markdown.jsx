// Renders Nova's replies: paragraphs, headings, lists, quotes, code, links,
// bold and italic, and math ($...$ and $$...$$ through KaTeX). Everything is
// built as React elements from the text; only KaTeX's own output is inserted
// as HTML, with KaTeX's trust setting off.
import { Fragment, memo, useState } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";

function renderMath(tex, display, key) {
  try {
    const html = katex.renderToString(tex, { displayMode: display, throwOnError: false, trust: false, strict: "ignore" });
    return <span key={key} dangerouslySetInnerHTML={{ __html: html }} />;
  } catch {
    return <code key={key}>{tex}</code>;
  }
}

const INLINE = /(\$\$[^$]+\$\$|\$[^$\n]+\$|\\\(.+?\\\)|`[^`]+`|\*\*[^*]+\*\*|\*[^*\n]+\*|_[^_\n]+_|\[[^\]]+\]\((?:https?:\/\/|mailto:)[^)\s]+\))/g;

function inline(text, keyBase = "") {
  const out = [];
  let last = 0;
  let i = 0;
  for (const match of text.matchAll(INLINE)) {
    const [tok] = match;
    if (match.index > last) out.push(text.slice(last, match.index));
    const key = `${keyBase}-${i++}`;
    if (tok.startsWith("$$")) out.push(renderMath(tok.slice(2, -2), true, key));
    else if (tok.startsWith("$")) out.push(renderMath(tok.slice(1, -1), false, key));
    else if (tok.startsWith("\\(")) out.push(renderMath(tok.slice(2, -2), false, key));
    else if (tok.startsWith("`")) out.push(<code key={key}>{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("**")) out.push(<strong key={key}>{inline(tok.slice(2, -2), key)}</strong>);
    else if (tok.startsWith("[")) {
      const m = tok.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      out.push(<a key={key} href={m[2]} target="_blank" rel="noreferrer">{m[1]}</a>);
    } else out.push(<em key={key}>{inline(tok.slice(1, -1), key)}</em>);
    last = match.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** A table row's cells; a | inside $math$ (|x|) or escaped (\\|) isn't a divider. */
function splitRow(row) {
  const cells = [];
  let cell = "";
  let math = false;
  for (let i = 0; i < row.length; i += 1) {
    const ch = row[i];
    if (ch === "\\" && row[i + 1] === "|") { cell += "|"; i += 1; continue; }
    if (ch === "$") math = !math;
    if (ch === "|" && !math) { cells.push(cell.trim()); cell = ""; continue; }
    cell += ch;
  }
  cells.push(cell.trim());
  return cells;
}

function blocks(src) {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^```(\w*)/);
    if (fence) {
      const body = [];
      i += 1;
      while (i < lines.length && !lines[i].startsWith("```")) body.push(lines[i++]);
      i += 1;
      out.push({ type: "code", text: body.join("\n") });
      continue;
    }
    // Display math: $$ ... $$ or \[ ... \], on one line or across several.
    const oneLine = line.match(/^\s*(?:\$\$(.+)\$\$|\\\[(.+)\\\])\s*$/);
    if (oneLine) { out.push({ type: "math", text: oneLine[1] ?? oneLine[2] }); i += 1; continue; }
    const opens = line.match(/^\s*(\$\$|\\\[)(.*)$/);
    if (opens) {
      const close = opens[1] === "$$" ? "$$" : "\\]";
      const body = [opens[2]];
      i += 1;
      while (i < lines.length && !lines[i].includes(close)) body.push(lines[i++]);
      if (i < lines.length) body.push(lines[i].slice(0, lines[i].indexOf(close)));
      i += 1;
      out.push({ type: "math", text: body.join("\n").trim() });
      continue;
    }
    // Tables: a header row, a |---| row, then rows.
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) && lines[i + 1].includes("-")) {
      const cells = (l) => splitRow(l.trim().replace(/^\||\|$/g, ""));
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push({ type: "table", head, rows });
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) { out.push({ type: `h${Math.min(heading[1].length, 4)}`, text: heading[2] }); i += 1; continue; }
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items = [];
      while (i < lines.length && (/^\s*[-*]\s+/.test(lines[i]) || /^\s*\d+[.)]\s+/.test(lines[i]))) {
        items.push(lines[i].replace(/^\s*(?:[-*]|\d+[.)])\s+/, ""));
        i += 1;
      }
      out.push({ type: ordered ? "ol" : "ul", items });
      continue;
    }
    if (/^>\s?/.test(line)) {
      const body = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) body.push(lines[i++].replace(/^>\s?/, ""));
      out.push({ type: "quote", text: body.join(" ") });
      continue;
    }
    if (!line.trim()) { i += 1; continue; }
    const para = [line]; // always take this line, so the reader never stands still
    i += 1;
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|>|\s*[-*]\s|\s*\d+[.)]\s|\s*\$\$|\s*\\\[|\s*\|.*\|\s*$)/.test(lines[i])) para.push(lines[i++]);
    out.push({ type: "p", text: para.join("\n") });
  }
  return out;
}

function CopyCode({ text }) {
  const [done, setDone] = useState(false);
  return (
    <button className="p-copycode" aria-label="Copy code" onClick={() => navigator.clipboard.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1400); })}>
      {done ? "Copied" : "Copy"}
    </button>
  );
}

function Markdown({ text }) {
  return (
    <>
      {blocks(text || "").map((b, n) => {
        const k = `b${n}`;
        if (b.type === "code") return <pre key={k}><CopyCode text={b.text} /><code>{b.text}</code></pre>;
        if (b.type === "math") return <Fragment key={k}>{renderMath(b.text, true, k)}</Fragment>;
        if (b.type === "ul" || b.type === "ol") {
          const List = b.type;
          return <List key={k}>{b.items.map((item, j) => <li key={j}>{inline(item, `${k}${j}`)}</li>)}</List>;
        }
        if (b.type === "quote") return <blockquote key={k}>{inline(b.text, k)}</blockquote>;
        if (b.type === "table") {
          return (
            <div key={k} className="p-mdtable">
              <table>
                <thead><tr>{b.head.map((c, j) => <th key={j}>{inline(c, `${k}h${j}`)}</th>)}</tr></thead>
                <tbody>{b.rows.map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `${k}r${ri}c${j}`)}</td>)}</tr>)}</tbody>
              </table>
            </div>
          );
        }
        if (b.type === "p") return <p key={k}>{b.text.split("\n").map((l, j) => <Fragment key={j}>{j > 0 && <br />}{inline(l, `${k}${j}`)}</Fragment>)}</p>;
        const H = b.type;
        return <H key={k}>{inline(b.text, k)}</H>;
      })}
    </>
  );
}

export { blocks };
export default memo(Markdown);
