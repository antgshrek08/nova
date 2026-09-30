import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { agoText, recall, remember } from "./remote.js";
import { BACKEND_URL, listObsidianVaults } from "../api.js";
import Icon from "./icons.jsx";
import Guide, { GuideButton } from "./Guide.jsx";
import Reactor from "./Reactor.jsx";
import { hexToRgb } from "./palettes.js";
import { Checkbox, SelectionBar, useListKeys, useSelection, useUi } from "./ui.jsx";
import { IS_TOUCH, keys } from "./keys.js";

const CATEGORY = { fact: "About you", preference: "Preferences", schedule: "Courses and schedule", project: "Projects", person: "People" };

async function call(path, init) {
  const res = await fetch(`${BACKEND_URL}${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
  return body;
}

function Graph({ facts, palette, dark }) {
  const ref = useRef(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas.getContext("2d");
    const dpr = Math.max(2, Math.min(window.devicePixelRatio || 1, 3));
    const { w, h } = size;
    if (!w || !h) return;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const subjects = [...new Set(facts.map((f) => f.subject))].slice(0, 10);
    const cx = w / 2, cy = h / 2;
    const pts = subjects.map((s, i) => {
      const a = (i / Math.max(1, subjects.length)) * Math.PI * 2 - Math.PI / 2;
      const r = Math.min(w, h) * 0.36;
      return [s, cx + Math.cos(a) * Math.min(r * 1.1, w / 2 - 70), cy + Math.sin(a) * r];
    });
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = dark ? "rgba(236,233,228,.16)" : "rgba(20,20,20,.12)";
    pts.forEach(([, x, y]) => { ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y); ctx.stroke(); });
    const [a, b] = [hexToRgb(palette.a), hexToRgb(palette.b)];
    ctx.font = "12px 'Geist Variable', sans-serif";
    pts.forEach(([s, x, y], i) => {
      ctx.fillStyle = `rgb(${(i % 2 ? b : a).join(",")})`;
      ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = dark ? "#A7A29C" : "#5E5A55";
      const max = Math.max(40, (x < cx ? x : w - x) - 14);
      let label = s;
      while (label.length > 3 && ctx.measureText(label).width > max) label = `${label.slice(0, -2)}…`;
      ctx.fillText(label, x + (x < cx ? -ctx.measureText(label).width - 9 : 9), y + 4);
    });
    ctx.fillStyle = `rgb(${a.join(",")})`;
    ctx.beginPath(); ctx.arc(cx, cy, 10, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = dark ? "#ECE9E4" : "#141414";
    ctx.fillText("You", cx + 14, cy + 4);
  }, [facts, palette, dark, size]);
  return <canvas ref={ref} className="p-graph" aria-label="How what Nova knows connects" />;
}

export default function MemoryView({ palette, dark }) {
  const ui = useUi();
  const [facts, setFacts] = useState(null);
  const [vaults, setVaults] = useState([]);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const listRef = useRef(null);
  const searchRef = useRef(null);

  const [offlineAt, setOfflineAt] = useState(null);
  async function load() {
    try {
      const data = await call("/knowledge?limit=500");
      setFacts(data.knowledge || []);
      setOfflineAt(null);
      remember("memory", data.knowledge || []);
    } catch (e) {
      const snap = recall("memory");
      if (snap) { setFacts(snap.data || []); setOfflineAt(snap.at); }
      else { setError(e.message); setFacts([]); }
    }
  }
  useEffect(() => { load(); listObsidianVaults().then((v) => setVaults(v?.vaults || v || [])).catch(() => {}); }, []);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (facts || []).filter((f) => !q || f.statement.toLowerCase().includes(q) || f.subject.toLowerCase().includes(q));
  }, [facts, query]);
  const groups = useMemo(() => {
    const map = new Map();
    shown.forEach((f) => {
      const g = CATEGORY[f.category] || "Other things Nova learned";
      if (!map.has(g)) map.set(g, []);
      map.get(g).push(f);
    });
    return [...map.entries()];
  }, [shown]);
  // Selection follows what's on screen, in on-screen order (for Shift ranges).
  const order = useMemo(() => groups.flatMap(([, rows]) => rows.map((f) => f.id)), [groups]);
  const sel = useSelection(order);

  /** Forget now, with Undo; the deletes are sent when the toast goes away. */
  const forget = useCallback((ids) => {
    const gone = new Set(ids);
    const removed = (facts || []).filter((f) => gone.has(f.id));
    if (!removed.length) return;
    ui.undoable({
      message: removed.length === 1 ? "Nova forgot that." : `Nova forgot ${removed.length} things.`,
      apply: () => { setFacts((all) => all.filter((f) => !gone.has(f.id))); sel.clear(); },
      revert: () => setFacts((all) => [...removed, ...all.filter((f) => !gone.has(f.id))]
        .sort((a, b) => String(b.last_seen_at || b.created_at).localeCompare(String(a.last_seen_at || a.created_at)))),
      commit: async () => { for (const f of removed) await call(`/knowledge/${f.id}`, { method: "DELETE" }); },
    });
  }, [facts, sel, ui]);

  useListKeys(listRef, sel, { onDelete: forget });

  // "/" jumps to search, like most apps with a list.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName)) { e.preventDefault(); searchRef.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const startEdit = (f) => { setEditing(f.id); setDraft(f.statement); };

  async function save(f) {
    if (!draft.trim() || draft.trim() === f.statement) { setEditing(null); return; }
    try {
      const row = await call(`/knowledge/${f.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ statement: draft.trim() }) });
      setFacts((all) => all.map((x) => (x.id === f.id ? row : x)));
      setEditing(null);
      ui.toast("Saved. Nova will use the corrected version.");
    } catch (e) { setError(e.message); }
  }

  const copy = (ids) => {
    const text = (facts || []).filter((f) => ids.includes(f.id)).map((f) => f.statement).join("\n");
    navigator.clipboard.writeText(text).then(() => ui.toast(ids.length === 1 ? "Copied." : `Copied ${ids.length} things.`));
  };

  const menuFor = (e, f) => {
    const ids = sel.forMenu(f.id);
    const many = ids.length > 1;
    ui.openMenu(e, [
      !many && { label: "Edit", icon: "edit", shortcut: "Enter", onSelect: () => startEdit(f) },
      { label: many ? `Copy ${ids.length}` : "Copy", icon: "copy", onSelect: () => copy(ids) },
      "-",
      { label: "Select all", shortcut: keys("Ctrl+A"), onSelect: sel.all },
      { label: "Select none", shortcut: "Esc", onSelect: sel.clear },
      "-",
      { label: many ? `Forget ${ids.length}` : "Forget", icon: "trash", shortcut: "Del", danger: true, onSelect: () => forget(ids) },
    ], { title: many ? `${ids.length} selected` : f.subject });
  };

  return (
    <section className="p-page" aria-label="Memory">
      <div className="p-ph">
        <Reactor palette={palette} dark={dark} />
        <div><h1>Memory</h1><div className="sub">What Nova has learned about you and uses in every chat. Correct it, or make it forget.</div></div>
        <GuideButton id="memory" />
        <span className="sp" />
        <label className="p-pill"><Icon name="search" /><input ref={searchRef} value={query} onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") { setQuery(""); e.currentTarget.blur(); } }}
          placeholder="Search what Nova knows" aria-label="Search what Nova knows" /><kbd className="p-kbd">/</kbd></label>
      </div>
      <div className="scroll p-pg">
        <Guide id="memory" />
        {offlineAt && <p className="note p-offline"><Icon name="info" size={14} /> Your computer's Nova isn't reachable. This is from {agoText(offlineAt)}.</p>}
        {error && <p className="err">{error}</p>}
        <div className="p-two">
          <div className="p-stack" ref={listRef}>
            {facts === null && <div className="muted">Loading…</div>}
            {facts && facts.length === 0 && <div className="p-empty"><div className="muted">Nova hasn't learned anything yet. It picks things up from your chats, and they appear here.</div></div>}
            {facts && facts.length > 0 && shown.length === 0 && <div className="p-empty"><div className="muted">Nothing matches "{query}".</div></div>}
            {shown.length > 0 && (
              <SelectionBar sel={sel} total={order.length} noun="memory" nouns="memories">
                <button className="p-sm" disabled={!sel.count} onClick={() => copy([...sel.selected])}><Icon name="copy" />Copy</button>
                <button className="p-sm danger" disabled={!sel.count} onClick={() => forget([...sel.selected])}
                  title="Forget the selected memories (Delete)"><Icon name="trash" />{sel.count ? `Forget ${sel.count}` : "Forget"}</button>
              </SelectionBar>
            )}
            {groups.map(([name, rows]) => {
              const ids = rows.map((f) => f.id);
              const picked = ids.filter((id) => sel.has(id)).length;
              return (
                <div className="p-card" key={name}>
                  <div className="head">
                    <span className="p-grouphead">
                      <Checkbox checked={picked === ids.length} mixed={picked > 0 && picked < ids.length} label={`Select all in ${name}`}
                        onChange={() => (picked === ids.length
                          ? sel.set([...sel.selected].filter((id) => !ids.includes(id)))
                          : sel.set([...sel.selected, ...ids]))} />
                      <i>{name}</i>
                    </span>
                    <span>{rows.length}</span>
                  </div>
                  {rows.map((f) => (
                    <div className={`p-fact${sel.has(f.id) ? " p-sel" : ""}`} key={f.id} tabIndex={0} aria-selected={sel.has(f.id)}
                      onClick={(e) => sel.rowClick(f.id, e)} onContextMenu={(e) => menuFor(e, f)}
                      onKeyDown={(e) => {
                        if (e.target !== e.currentTarget) return;
                        if (e.key === " ") { e.preventDefault(); sel.toggle(f.id, e); }
                        if (e.key === "Enter") { e.preventDefault(); startEdit(f); }
                      }}>
                      <Checkbox checked={sel.has(f.id)} label="Select" onChange={(e) => sel.toggle(f.id, e)} />
                      {editing === f.id
                        ? <textarea rows={2} value={draft} autoFocus onChange={(e) => setDraft(e.target.value)} aria-label="Corrected statement"
                            onKeyDown={(e) => {
                              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); save(f); }
                              if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setEditing(null); }
                            }} />
                        : <span onDoubleClick={() => startEdit(f)}>{f.statement}</span>}
                      <span className="x">
                        {editing === f.id ? (
                          <><button className="p-link" onClick={() => save(f)}>Save</button><button className="p-link" onClick={() => setEditing(null)}>Cancel</button></>
                        ) : (
                          <><button className="p-link" onClick={() => startEdit(f)}>Edit</button><button className="p-link" onClick={() => forget([f.id])}>Forget</button></>
                        )}
                      </span>
                      <small>{f.status === "confirmed" ? "you said" : "Nova inferred"} · {f.subject} · {String(f.last_seen_at || f.created_at).slice(0, 10)}</small>
                    </div>
                  ))}
                </div>
              );
            })}
            {shown.length > 0 && <p className="note">{IS_TOUCH ? "Tap the boxes to select several. Press and hold a memory for more." : `${keys("Shift+click selects a range, Ctrl+A selects everything,")} Delete forgets, Esc clears. Right-click for more.`}</p>}
          </div>
          <div className="p-stack">
            {facts && facts.length > 0 && <Graph facts={shown} palette={palette} dark={dark} />}
            <div className="p-card"><div className="head"><i>Connected</i><span /></div>
              <div className="p-kv">
                <span>Obsidian</span><span>{vaults.length ? `${vaults.length} vault${vaults.length === 1 ? "" : "s"} linked` : "not linked"}</span>
                <span>Learned from chats</span><span>{facts ? facts.length : "…"}</span>
                <span>Where it's kept</span><span>on this computer</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
