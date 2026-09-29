// Ctrl+K: jump anywhere or run a command by typing a few letters of it.
import { useEffect, useMemo, useRef, useState } from "react";
import Icon from "./icons.jsx";

/** Letters of the query in order, anywhere in the text; earlier and
 * word-start matches rank higher. */
function score(text, query) {
  const t = text.toLowerCase();
  const q = query.toLowerCase().trim();
  if (!q) return 1;
  const direct = t.indexOf(q);
  if (direct >= 0) return 1000 - direct - (direct > 0 && t[direct - 1] !== " " ? 50 : 0);
  let i = 0;
  let s = 0;
  for (const ch of q) {
    const at = t.indexOf(ch, i);
    if (at < 0) return 0;
    s += at === i ? 3 : 1;
    i = at + 1;
  }
  return s;
}

export default function Palette({ commands, onClose }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const results = useMemo(() => commands
    .map((c) => ({ ...c, s: score(`${c.label} ${c.group || ""} ${c.keywords || ""}`, query) }))
    .filter((c) => c.s > 0)
    .sort((a, b) => b.s - a.s || (a.order ?? 0) - (b.order ?? 0))
    .slice(0, 40), [commands, query]);

  useEffect(() => { setActive(0); }, [query]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const run = (c) => { onClose(); c.run(); };
  const onKeyDown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(results.length - 1, i + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(0, i - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); if (results[active]) run(results[active]); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  };

  return (
    <div className="p-scrim top" onPointerDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="p-palette" role="dialog" aria-modal="true" aria-label="Go to or run a command">
        <label className="p-palette-in">
          <Icon name="search" />
          <input ref={inputRef} value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={onKeyDown}
            placeholder="Go to a screen, a chat, or a setting…" role="combobox" aria-expanded="true"
            aria-controls="p-palette-list" aria-activedescendant={results[active] ? `p-pal-${active}` : undefined} />
          <kbd className="p-kbd">Esc</kbd>
        </label>
        <div className="p-palette-list" id="p-palette-list" role="listbox" ref={listRef}>
          {results.length === 0 && <div className="note" style={{ padding: "14px 16px" }}>Nothing matches.</div>}
          {results.map((c, i) => (
            <div key={c.id} id={`p-pal-${i}`} data-i={i} role="option" aria-selected={i === active}
              className="p-palette-row" onMouseMove={() => setActive(i)} onClick={() => run(c)}>
              <Icon name={c.icon || "arrow"} size={15} />
              <span className="l">{c.label}</span>
              {c.group && <span className="g">{c.group}</span>}
              {c.shortcut && <kbd className="p-kbd">{c.shortcut}</kbd>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
