// Studio, rebuilt in Paper: explorer on the left, editor tabs in the middle,
// Nova's code chat on the right, and a bottom panel for changes, terminal,
// git, preview and shipping. Open files live in lib/codeEditorStore.js, so
// unsaved edits survive leaving Studio and coming back.
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BACKEND_URL, createCodeFile, createConversation, getCodeWorkspaceRoot, listCodeTree, listConversations,
  renameConversation, resetCodeWorkspaceRoot, setCodeWorkspaceRoot,
} from "../api.js";
import ChangeReviewPanel from "../components/ChangeReviewPanel.jsx";
import CodeEditor from "../components/CodeEditor.jsx";
import ErrorBoundary from "../components/ErrorBoundary.jsx";
import {
  addFileChangeSet, closeAllFiles, closeFile, openFile, saveFile, setActiveFile, useFileChangeSets, useOpenFiles,
} from "../lib/codeEditorStore.js";
import CodeChat from "./CodeChat.jsx";
import Guide, { GuideButton } from "./Guide.jsx";
import Icon from "./icons.jsx";
import Reactor from "./Reactor.jsx";
import { useUi } from "./ui.jsx";
import "./studio.css";
import { keys } from "./keys.js";

const IdeTools = lazy(() => import("../components/IdeTools.jsx"));
const LivePreviewPanel = lazy(() => import("../components/ide/LivePreviewPanel.jsx"));

const PANELS = [["changes", "Changes", "check"], ["terminal", "Terminal", "term"], ["git", "Git", "branch"], ["preview", "Preview", "globe"], ["ship", "Ship", "rocket"]];

function stored(key, fallback) {
  try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch { return fallback; }
}
function store(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private window */ }
}

async function code(path, body) {
  const res = await fetch(`${BACKEND_URL}/code/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data;
}

const base = (p) => p.split("/").pop();
const dir = (p) => (p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : "");

/* ---- drag to resize ---------------------------------------------------- */

function useDrag(onMove) {
  return useCallback((e) => {
    e.preventDefault();
    const move = (ev) => onMove(ev);
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); document.body.style.cursor = ""; };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }, [onMove]);
}

/* ---- explorer ----------------------------------------------------------- */

function Tree({ path = "", depth = 0, refresh, selected, onOpen, onMenu, expanded, setExpanded }) {
  const [rows, setRows] = useState(null);
  useEffect(() => { listCodeTree(path).then(setRows).catch(() => setRows([])); }, [path, refresh]);
  if (rows === null) return depth === 0 ? <div className="note" style={{ padding: "8px 12px" }}>Loading…</div> : null;
  if (!rows.length && depth === 0) return <div className="note" style={{ padding: "8px 12px" }}>This folder is empty.</div>;
  return rows.map((e) => {
    const open = expanded.has(e.path);
    return (
      <div key={e.path} role="none">
        <button role="treeitem" aria-expanded={e.is_dir ? open : undefined} aria-selected={!e.is_dir && selected === e.path}
          className={`p-node${!e.is_dir && selected === e.path ? " on" : ""}`} style={{ paddingLeft: 10 + depth * 14 }} title={e.path}
          data-path={e.path} data-dir={e.is_dir ? "1" : ""}
          onClick={() => (e.is_dir ? setExpanded(e.path, !open) : onOpen(e.path))}
          onContextMenu={(ev) => onMenu(ev, e)}>
          <span className="car">{e.is_dir ? <svg viewBox="0 0 12 12" style={{ transform: open ? "rotate(90deg)" : "none" }}><path d="M4 2l4 4-4 4" /></svg> : null}</span>
          <Icon name={e.is_dir ? "folder" : "file"} size={14} />
          <span className="n">{e.name}</span>
        </button>
        {e.is_dir && open && <Tree path={e.path} depth={depth + 1} refresh={refresh} selected={selected} onOpen={onOpen} onMenu={onMenu} expanded={expanded} setExpanded={setExpanded} />}
      </div>
    );
  });
}

function Explorer({ root, refresh, bump, activePath, onAsk, onRootChanged, dirty }) {
  const ui = useUi();
  const [expanded, setExp] = useState(() => new Set(stored("nova.studio.expanded", [])));
  const [draft, setDraft] = useState(null); // {kind: "file"|"folder"|"rename", at, value}
  const uploadRef = useRef(null);
  const setExpanded = useCallback((p, on) => setExp((s) => { const n = new Set(s); if (on) n.add(p); else n.delete(p); store("nova.studio.expanded", [...n]); return n; }), []);

  async function submit() {
    const d = draft;
    setDraft(null);
    const value = d?.value.trim().replace(/\\/g, "/").replace(/^\/+/, "");
    if (!value) return;
    try {
      if (d.kind === "file") { await createCodeFile(value); bump(); await openFile(value); }
      else if (d.kind === "folder") { await code("folder", { path: value }); bump(); setExpanded(value, true); }
      else if (d.kind === "rename" && value !== d.at) {
        if (dirty) throw new Error("Save or close files with unsaved changes before renaming.");
        await code("rename", { path: d.at, new_path: value });
        closeAllFiles();
        bump();
      }
    } catch (e) { ui.toast(e.message, { error: true }); }
  }
  async function importFiles(files) {
    if (!files?.length) return;
    const body = new FormData();
    for (const f of files) body.append("files", f);
    try {
      const res = await fetch(`${BACKEND_URL}/code/import`, { method: "POST", body });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Import failed");
      bump();
      ui.toast(`Imported ${data.paths?.length || files.length} file${files.length === 1 ? "" : "s"}.`);
    } catch (e) { ui.toast(e.message, { error: true }); }
  }

  const menu = (e, entry) => {
    const folder = entry ? (entry.is_dir ? entry.path : dir(entry.path)) : "";
    const pre = folder ? `${folder}/` : "";
    ui.openMenu(e, [
      entry && !entry.is_dir && { label: "Open", icon: "file", onSelect: () => openFile(entry.path) },
      { label: "New file…", icon: "plus", onSelect: () => { if (folder) setExpanded(folder, true); setDraft({ kind: "file", value: pre }); } },
      { label: "New folder…", icon: "folder", onSelect: () => setDraft({ kind: "folder", value: pre }) },
      entry && { label: "Rename…", icon: "edit", shortcut: "F2", onSelect: () => setDraft({ kind: "rename", at: entry.path, value: entry.path }) },
      "-",
      entry && { label: "Copy path", icon: "copy", onSelect: () => navigator.clipboard.writeText(entry.path) },
      entry && root?.path && { label: "Copy full path", onSelect: () => navigator.clipboard.writeText(`${root.path}/${entry.path}`.replace(/\//g, "\\")) },
      entry && !entry.is_dir && { label: "Ask Nova about this file", icon: "chat", onSelect: () => onAsk(`Look at ${entry.path} and `) },
      !entry && { label: "Import files…", onSelect: () => uploadRef.current?.click() },
      !entry && { label: "Collapse all", onSelect: () => { setExp(new Set()); store("nova.studio.expanded", []); } },
    ], { title: entry ? entry.path : root?.name });
  };

  const onKeyDown = (e) => {
    const items = [...e.currentTarget.querySelectorAll(".p-node")];
    const i = items.indexOf(document.activeElement);
    if (i < 0) return;
    const node = items[i];
    if (e.key === "ArrowDown") { e.preventDefault(); items[i + 1]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[i - 1]?.focus(); }
    else if (e.key === "ArrowRight" && node.dataset.dir) { e.preventDefault(); setExpanded(node.dataset.path, true); }
    else if (e.key === "ArrowLeft" && node.dataset.dir) { e.preventDefault(); setExpanded(node.dataset.path, false); }
    else if (e.key === "F2") { e.preventDefault(); setDraft({ kind: "rename", at: node.dataset.path, value: node.dataset.path }); }
  };

  return (
    <aside className="p-explorer" aria-label="Files"
      onDragOver={(e) => { if (e.dataTransfer?.types?.includes("Files")) e.preventDefault(); }}
      onDrop={(e) => { if (e.dataTransfer?.files?.length) { e.preventDefault(); importFiles(e.dataTransfer.files); } }}>
      <div className="p-exhead">
        <button className="p-projbtn" title={root?.path} onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          onRootChanged.menu({ preventDefault() {}, stopPropagation() {}, clientX: r.left + 8, clientY: r.bottom + 4, currentTarget: e.currentTarget, target: e.currentTarget });
        }}>
          <b>{root?.name || "Project"}</b><Icon name="down" size={12} />
        </button>
        <button className="p-link" title="New file" aria-label="New file" onClick={() => setDraft({ kind: "file", value: "" })}><Icon name="plus" size={15} /></button>
        <button className="p-link" title="Refresh" aria-label="Refresh files" onClick={bump}><Icon name="refresh" size={14} /></button>
      </div>
      {draft && (
        <form className="p-exdraft" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <label className="note">{draft.kind === "rename" ? `Rename ${base(draft.at)} to` : draft.kind === "folder" ? "New folder" : "New file"}</label>
          <input className="p-input mono" autoFocus value={draft.value} onChange={(e) => setDraft({ ...draft, value: e.target.value })}
            onKeyDown={(e) => { if (e.key === "Escape") setDraft(null); }} onBlur={() => setTimeout(() => setDraft(null), 150)}
            placeholder={draft.kind === "folder" ? "src/components" : "src/app.js"} aria-label="Path" />
        </form>
      )}
      <div className="p-tree scroll" role="tree" aria-label={root?.name || "Project files"} onKeyDown={onKeyDown}
        onContextMenu={(e) => { if (!e.defaultPrevented) menu(e, null); }}>
        {root && <Tree refresh={`${refresh}:${root.path}`} selected={activePath} onOpen={openFile} onMenu={menu} expanded={expanded} setExpanded={setExpanded} />}
      </div>
      <input ref={uploadRef} type="file" multiple hidden onChange={(e) => { importFiles(e.target.files); e.target.value = ""; }} />
    </aside>
  );
}

/* ---- editor tabs --------------------------------------------------------- */

function Tabs({ openPaths, activePath, isDirty, onClose }) {
  const ui = useUi();
  const ref = useRef(null);
  // Keep the active tab in view by scrolling the strip only (scrollIntoView
  // would also scroll every scrollable ancestor).
  useEffect(() => {
    const strip = ref.current;
    const tab = strip?.querySelector('[aria-selected="true"]');
    if (!tab) return;
    if (tab.offsetLeft < strip.scrollLeft) strip.scrollLeft = tab.offsetLeft;
    else if (tab.offsetLeft + tab.offsetWidth > strip.scrollLeft + strip.clientWidth) strip.scrollLeft = tab.offsetLeft + tab.offsetWidth - strip.clientWidth;
  }, [activePath]);
  if (!openPaths.length) return <div className="p-etabs empty" />;
  return (
    <div className="p-etabs" role="tablist" aria-label="Open files" ref={ref}>
      {openPaths.map((p) => (
        <div key={p} role="tab" aria-selected={p === activePath} tabIndex={p === activePath ? 0 : -1} className="p-etab" title={p}
          onClick={() => setActiveFile(p)}
          onAuxClick={(e) => { if (e.button === 1) onClose(p); }}
          onContextMenu={(e) => ui.openMenu(e, [
            { label: "Close", shortcut: keys("Ctrl+W"), onSelect: () => onClose(p) },
            { label: "Close others", onSelect: () => openPaths.filter((x) => x !== p).forEach(onClose) },
            { label: "Close all", onSelect: () => [...openPaths].forEach(onClose) },
            "-",
            { label: "Copy path", icon: "copy", onSelect: () => navigator.clipboard.writeText(p) },
          ], { title: p })}>
          <span className="n">{base(p)}</span>
          {isDirty(p) && <span className="dirty" title="Unsaved changes" />}
          <button className="x" aria-label={`Close ${base(p)}`} onClick={(e) => { e.stopPropagation(); onClose(p); }}><Icon name="x" size={12} /></button>
        </div>
      ))}
    </div>
  );
}

/* ---- Studio ------------------------------------------------------------- */

export default function StudioView({ palette, dark }) {
  const ui = useUi();
  const { openPaths, activePath, getEntry, isDirty, dirtyPaths } = useOpenFiles();
  const changeSets = useFileChangeSets();
  const [root, setRoot] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const bump = useCallback(() => setRefresh((n) => n + 1), []);
  const [chats, setChats] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [panel, setPanel] = useState(() => stored("nova.studio.panel", "changes"));
  const [panelOpen, setPanelOpen] = useState(() => stored("nova.studio.panelOpen", false));
  const [panelH, setPanelH] = useState(() => stored("nova.studio.panelH", 260));
  const phone = typeof window !== "undefined" && window.matchMedia("(max-width: 640px)").matches;
  const [chatOpen, setChatOpen] = useState(() => !phone && stored("nova.studio.chatOpen", true));
  const [chatW, setChatW] = useState(() => stored("nova.studio.chatW", 380));
  const [explorerOpen, setExplorerOpen] = useState(() => !phone && stored("nova.studio.explorer", true));
  const [split, setSplit] = useState(false);
  const [prefill, setPrefill] = useState("");
  const [savingAll, setSavingAll] = useState(false);
  const centerRef = useRef(null);
  const bodyRef = useRef(null);

  useEffect(() => { getCodeWorkspaceRoot().then(setRoot).catch((e) => ui.toast(e.message, { error: true })); }, [ui]);
  const loadChats = useCallback(() => listConversations({ tab: "code" }).then((rows) => {
    const list = Array.isArray(rows) ? rows : [];
    setChats(list);
    setConversationId((id) => id ?? list[0]?.id ?? null);
  }).catch(() => {}), []);
  useEffect(() => { loadChats(); }, [loadChats]);
  useEffect(() => { store("nova.studio.panel", panel); }, [panel]);
  useEffect(() => { store("nova.studio.panelOpen", panelOpen); }, [panelOpen]);
  // A phone starts with both side panels closed; that shouldn't become the
  // desktop's remembered layout.
  useEffect(() => { if (!phone) store("nova.studio.chatOpen", chatOpen); }, [chatOpen, phone]);
  useEffect(() => { if (!phone) store("nova.studio.explorer", explorerOpen); }, [explorerOpen, phone]);
  // On a phone the file list covers the editor; opening a file shows it.
  useEffect(() => { if (phone && activePath) setExplorerOpen(false); }, [phone, activePath]);

  const dragPanel = useDrag(useCallback((ev) => {
    const r = centerRef.current?.getBoundingClientRect();
    if (!r) return;
    const h = Math.min(r.height - 120, Math.max(120, r.bottom - ev.clientY));
    document.body.style.cursor = "row-resize";
    setPanelH(h);
    store("nova.studio.panelH", h);
  }, []));
  const dragChat = useDrag(useCallback((ev) => {
    const r = bodyRef.current?.getBoundingClientRect();
    if (!r) return;
    const w = Math.min(r.width * 0.6, Math.max(280, r.right - ev.clientX));
    document.body.style.cursor = "col-resize";
    setChatW(w);
    store("nova.studio.chatW", w);
  }, []));

  const closeTab = useCallback(async (p) => {
    if (isDirty(p)) {
      const ok = await ui.confirm({ title: `Close ${base(p)}?`, body: "It has unsaved changes. Closing it throws them away.", confirm: "Close without saving", danger: true });
      if (!ok) return;
    }
    closeFile(p);
  }, [isDirty, ui]);

  async function saveAll() {
    setSavingAll(true);
    try { for (const p of dirtyPaths) await saveFile(p); bump(); ui.toast("Saved."); } finally { setSavingAll(false); }
  }

  async function newChat() {
    const created = await createConversation({ tab: "code", title: "New code chat" });
    setConversationId(created.id);
    loadChats();
  }

  // Studio's own shortcuts: save, close tab, toggle panel / chat / explorer.
  useEffect(() => {
    const onKey = (e) => {
      const mod = e.ctrlKey || e.metaKey;
      if (!mod) return;
      const k = e.key.toLowerCase();
      if (k === "s" && e.shiftKey) { e.preventDefault(); saveAll(); }
      else if (k === "s") { e.preventDefault(); if (activePath) saveFile(activePath).then(bump); }
      else if (k === "w" && activePath) { e.preventDefault(); closeTab(activePath); }
      else if (k === "j" || k === "`") { e.preventDefault(); setPanelOpen((o) => !o); }
      else if (k === "l" && !e.shiftKey) { e.preventDefault(); setChatOpen((o) => !o); }
      else if (k === "e" && e.shiftKey) { e.preventDefault(); setExplorerOpen((o) => !o); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }); // re-bound each render so it sees the current file

  const confirmSwitch = async () => (dirtyPaths.length === 0 || ui.confirm({
    title: "Switch projects?", body: `${dirtyPaths.length} open file${dirtyPaths.length === 1 ? " has" : "s have"} unsaved changes. Switching closes them without saving.`, confirm: "Switch anyway", danger: true,
  }));
  const switchTo = async (fn) => {
    if (!(await confirmSwitch())) return;
    try { const r = await fn(); if (r) { setRoot(r); closeAllFiles(); bump(); } } catch (e) { ui.toast(e.message, { error: true }); }
  };
  const projectMenu = {
    menu: (e) => ui.openMenu(e, [
      { label: "Open a folder…", icon: "folder", onSelect: () => switchTo(async () => {
        const picked = window.electronAPI?.chooseProjectFolder ? await window.electronAPI.chooseProjectFolder() : window.prompt("Full path to a project folder:");
        return picked ? setCodeWorkspaceRoot(picked) : null;
      }) },
      { label: "Open Nova's own source", icon: "code", onSelect: () => switchTo(async () => {
        const res = await fetch(`${BACKEND_URL}/code/nova-source`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Nova's source isn't available");
        return data;
      }) },
      !root?.is_default && { label: "Back to the sandbox", onSelect: () => switchTo(resetCodeWorkspaceRoot) },
      "-",
      root?.path && { label: "Copy project path", icon: "copy", onSelect: () => navigator.clipboard.writeText(root.path) },
    ], { title: root?.path }),
  };

  const entry = activePath ? getEntry(activePath) : null;
  const currentChat = chats.find((c) => c.id === conversationId);
  const pendingChanges = changeSets.length;
  const crumbs = useMemo(() => (activePath ? activePath.split("/") : []), [activePath]);

  return (
    <section className="p-studio2" aria-label="Studio">
      <div className="p-sbar">
        <Reactor palette={palette} dark={dark} />
        <b>Studio</b>
        <GuideButton id="studio" />
        <button className="p-link" onClick={() => setExplorerOpen((o) => !o)} aria-pressed={explorerOpen} title={keys("Files (Ctrl+Shift+E)")}><Icon name="side" size={15} /></button>
        <nav className="p-crumbs" aria-label="File path">
          <span>{root?.name || "Project"}</span>
          {crumbs.map((c, i) => <span key={`${c}${i}`}><Icon name="arrow" size={10} />{c}</span>)}
        </nav>
        <span style={{ flex: 1 }} />
        {dirtyPaths.length > 0 && <button className="p-sm dark" onClick={saveAll} disabled={savingAll} title={keys("Save all (Ctrl+Shift+S)")}>{savingAll ? "Saving…" : `Save all (${dirtyPaths.length})`}</button>}
        <button className="p-sm" aria-pressed={split} onClick={() => setSplit((s) => !s)} title="Show the running app beside the code"><Icon name="globe" />Live preview</button>
        <button className="p-sm" aria-pressed={panelOpen} onClick={() => setPanelOpen((o) => !o)} title={keys("Terminal and tools (Ctrl+J)")}><Icon name="term" />Panel</button>
        <button className="p-sm" aria-pressed={chatOpen} onClick={() => setChatOpen((o) => !o)} title={keys("Nova (Ctrl+L)")}><Icon name="chat" />Nova</button>
      </div>
      <div className="p-sbody" ref={bodyRef} style={{ gridTemplateColumns: `${explorerOpen ? "minmax(170px, min(240px, 24%)) " : ""}minmax(0, 1fr)${chatOpen ? ` 6px minmax(260px, min(${chatW}px, 42%))` : ""}` }}>
        {explorerOpen && <Explorer root={root} refresh={refresh} bump={bump} activePath={activePath} dirty={dirtyPaths.length > 0}
          onAsk={(t) => { setChatOpen(true); setPrefill(t); }} onRootChanged={projectMenu} />}
        <div className="p-center" ref={centerRef} style={{ gridTemplateRows: `auto minmax(0, 1fr)${panelOpen ? ` 6px ${panelH}px` : ""}` }}>
          <Tabs openPaths={openPaths} activePath={activePath} isDirty={isDirty} onClose={closeTab} />
          <div className={`p-editor${split ? " split" : ""}`}>
            <div className="p-studio-host">
              {activePath ? (
                <ErrorBoundary><CodeEditor path={activePath} entry={entry} projectKey={root?.path ?? ""} /></ErrorBoundary>
              ) : (
                <div className="p-studio-empty">
                  <Guide id="studio" />
                  <Reactor palette={palette} dark={dark} />
                  <div className="muted">Open a file from the left, or ask Nova to build something.</div>
                  <div className="p-keys" style={{ maxWidth: 360 }}>
                    <span>Save</span><kbd>{keys("Ctrl+S")}</kbd><span>Close file</span><kbd>{keys("Ctrl+W")}</kbd>
                    <span>Terminal and tools</span><kbd>{keys("Ctrl+J")}</kbd><span>Nova</span><kbd>{keys("Ctrl+L")}</kbd><span>Files</span><kbd>{keys("Ctrl+Shift+E")}</kbd>
                  </div>
                </div>
              )}
            </div>
            {split && <div className="p-studio-host"><Suspense fallback={null}><LivePreviewPanel onClose={() => setSplit(false)} /></Suspense></div>}
          </div>
          {panelOpen && <div className="p-hsplit" onPointerDown={dragPanel} role="separator" aria-orientation="horizontal" aria-label="Resize the panel" />}
          {panelOpen && (
            <div className="p-bpanel">
              <div className="p-btabs" role="tablist" aria-label="Tools">
                {PANELS.map(([id, label, icon]) => (
                  <button key={id} role="tab" aria-selected={panel === id} onClick={() => setPanel(id)}>
                    <Icon name={icon} size={14} />{label}{id === "changes" && pendingChanges > 0 && <span className="badge">{pendingChanges}</span>}
                  </button>
                ))}
                <span style={{ flex: 1 }} />
                <button className="p-link" onClick={() => setPanelOpen(false)} aria-label="Close the panel" title={keys("Close (Ctrl+J)")}><Icon name="x" size={14} /></button>
              </div>
              <div className="p-studio-host p-bbody">
                {panel === "changes" && <ChangeReviewPanel onOpenFile={openFile} />}
                <Suspense fallback={null}><IdeTools view={panel} workspace={root?.path} /></Suspense>
              </div>
            </div>
          )}
        </div>
        {chatOpen && <div className="p-vsplit" onPointerDown={dragChat} role="separator" aria-orientation="vertical" aria-label="Resize Nova's panel" />}
        {chatOpen && (
          <aside className="p-codechat" aria-label="Nova">
            <div className="p-cchead">
              <select className="p-sm" value={conversationId ?? ""} onChange={(e) => setConversationId(Number(e.target.value))} aria-label="Code chat"
                onContextMenu={(e) => currentChat && ui.openMenu(e, [{ label: "Rename chat", icon: "edit", onSelect: async () => {
                  const t = window.prompt("Name this code chat", currentChat.title);
                  if (t?.trim()) { await renameConversation(currentChat.id, t.trim()); loadChats(); }
                } }])}>
                {!chats.length && <option value="">No code chats yet</option>}
                {chats.map((c) => <option key={c.id} value={c.id}>{c.title || `Code chat ${c.id}`}</option>)}
              </select>
              <button className="p-link" onClick={newChat} title="New code chat" aria-label="New code chat"><Icon name="plus" size={15} /></button>
            </div>
            <CodeChat conversationId={conversationId} activePath={activePath} prefill={prefill} onPrefillUsed={() => setPrefill("")}
              onNeedConversation={async () => { const c = await createConversation({ tab: "code", title: "New code chat" }); setConversationId(c.id); loadChats(); return c.id; }}
              onFileChanges={(id, changes) => { addFileChangeSet(id, changes); bump(); if (changes?.length) { setPanelOpen(true); setPanel("changes"); } }}
              onResponseDone={loadChats} />
          </aside>
        )}
      </div>
    </section>
  );
}
