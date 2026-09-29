// Nova's interface, Paper and Light (docs/plans/2026-09-28-design-direction.md).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BACKEND_URL, deleteConversation, deleteCustomTab, getCustomTabs, getUserProfile, listConversations, renameConversation, setConversationPinned } from "../api.js";
import AcademicsView from "./AcademicsView.jsx";
import AgentsView from "./AgentsView.jsx";
import ChatView from "./ChatView.jsx";
import Icon from "./icons.jsx";
import MemoryView from "./MemoryView.jsx";
import Notifications from "./Notifications.jsx";
import Palette from "./Palette.jsx";
import Reactor from "./Reactor.jsx";
import OnboardingView from "./Onboarding.jsx";
import { SETTINGS_SECTIONS, SettingsView } from "./SettingsViews.jsx";
import StudioView from "./StudioView.jsx";
import WorkspaceView from "./WorkspaceView.jsx";
import { useModelCount, WORKSPACE_MIN_MODELS } from "./models.js";
import { AddTabView, UserTabView } from "./TabsViews.jsx";
import { sendMessage, setPrefill } from "./chatStore.js";
import { operatorStop } from "./paperApi.js";
import { UiProvider, useListKeys, useSelection, useUi } from "./ui.jsx";
import usePrefs from "./usePrefs.js";
import "./paper.css";
import { IS_MAC, STOP_KEY, keys } from "./keys.js";
import { useDismissed } from "./dismissals.js";

const SECTIONS = [
  ["chat", "Chat", "chat"],
  ["academics", "Academics", "cap"],
  ["studio", "Studio", "code"],
  ["agents", "Agents", "nodes"],
  ["memory", "Memory", "brain"],
];

const electron = typeof window !== "undefined" ? window.electronAPI : null;

function stored(key, fallback) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function store(key, value) {
  try { localStorage.setItem(key, value); } catch { /* private window */ }
}

/** A readable name for a conversation: its title, or its first words. */
function titleOf(c) {
  if (!c) return "New conversation";
  if (c.title && c.title !== "New conversation") return c.title;
  const plain = (c.preview || "").replace(/[*_`#>]+/g, "").replace(/\s+/g, " ").trim();
  return plain ? plain.slice(0, 60) : "New conversation";
}

const SHORTCUTS = [
  ["Search and go anywhere", keys("Ctrl+K")],
  ["New chat", keys("Ctrl+N")],
  ["Chat, Academics, Studio, Agents, Memory", keys("Ctrl+1 … 5")],
  ["Settings", keys("Ctrl+,")],
  ["Show or hide the sidebar", keys("Ctrl+B")],
  ["Day or night", keys("Ctrl+Shift+L")],
  ["Stop everything Nova is doing", STOP_KEY],
  ["Expand the chat / close a menu", "Esc"],
  ["Rename the selected chat", "F2"],
  ["Select several", keys("Ctrl+click, Shift+click")],
  ["Select all in a list", keys("Ctrl+A")],
  ["Delete the selection", "Delete"],
  ["Search in a list", "/"],
  ["This list", keys("Ctrl+/")],
];

function ShortcutSheet({ onClose }) {
  const ref = useRef(null);
  useEffect(() => { ref.current?.querySelector("button")?.focus(); }, []);
  return (
    <div className="p-scrim" onPointerDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
      <div ref={ref} className="p-dialog" role="dialog" aria-modal="true" aria-labelledby="p-keys-t">
        <h2 id="p-keys-t">Keyboard shortcuts</h2>
        <div className="p-keys">{SHORTCUTS.map(([what, keys]) => [<span key={what}>{what}</span>, <kbd key={`${what}k`}>{keys}</kbd>])}</div>
        <div className="p-acts"><button className="p-sm dark" onClick={onClose}>Done</button></div>
      </div>
    </div>
  );
}

/** Past chats in the sidebar: click to open, Ctrl/Shift+click to select
 * several, right-click for Rename / Pin / Delete, F2 to rename. */
function History({ conversations, setConversations, current, running, onOpen, onDeleted }) {
  const ui = useUi();
  const ids = useMemo(() => conversations.map((c) => c.id), [conversations]);
  const sel = useSelection(ids);
  const [renaming, setRenaming] = useState(null);
  const [name, setName] = useState("");
  const ref = useRef(null);

  const remove = useCallback((which) => {
    const gone = new Set(which);
    const removed = conversations.filter((c) => gone.has(c.id));
    if (!removed.length) return;
    ui.undoable({
      message: removed.length === 1 ? `Deleted "${titleOf(removed[0]).slice(0, 40)}".` : `Deleted ${removed.length} chats.`,
      apply: () => { setConversations((all) => all.filter((c) => !gone.has(c.id))); sel.clear(); if (gone.has(current)) onDeleted(); },
      revert: () => setConversations((all) => [...all, ...removed].sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))),
      commit: async () => { for (const c of removed) await deleteConversation(c.id); },
    });
  }, [conversations, current, onDeleted, sel, setConversations, ui]);
  useListKeys(ref, sel, { onDelete: remove });

  const startRename = (c) => { setRenaming(c.id); setName(titleOf(c)); };
  const commitRename = async (c) => {
    const title = name.trim();
    setRenaming(null);
    if (!title || title === titleOf(c)) return;
    setConversations((all) => all.map((x) => (x.id === c.id ? { ...x, title } : x)));
    try { await renameConversation(c.id, title); } catch (e) { ui.toast(`Couldn't rename: ${e.message}`, { error: true }); }
  };
  const pin = async (c) => {
    const pinned = !Number(c.pinned);
    setConversations((all) => all.map((x) => (x.id === c.id ? { ...x, pinned: pinned ? 1 : 0 } : x)));
    try { await setConversationPinned(c.id, pinned); } catch (e) { ui.toast(e.message, { error: true }); }
  };

  const menu = (e, c) => {
    const which = sel.forMenu(c.id);
    const many = which.length > 1;
    ui.openMenu(e, many ? [
      { label: `Delete ${which.length} chats`, icon: "trash", shortcut: "Del", danger: true, onSelect: () => remove(which) },
      { label: "Select all", shortcut: keys("Ctrl+A"), onSelect: sel.all },
      { label: "Select none", shortcut: "Esc", onSelect: sel.clear },
    ] : [
      { label: "Open", icon: "chat", onSelect: () => { sel.clear(); onOpen(c.id); } },
      { label: "Rename", icon: "edit", shortcut: "F2", onSelect: () => startRename(c) },
      { label: Number(c.pinned) ? "Unpin" : "Pin to top", icon: "pin", onSelect: () => pin(c) },
      { label: "Copy title", icon: "copy", onSelect: () => navigator.clipboard.writeText(titleOf(c)) },
      "-",
      { label: "Delete", icon: "trash", shortcut: "Del", danger: true, onSelect: () => remove([c.id]) },
    ], { title: many ? `${which.length} selected` : titleOf(c) });
  };

  const ordered = useMemo(() => [...conversations].sort((a, b) => Number(b.pinned || 0) - Number(a.pinned || 0)), [conversations]);

  return (
    <div className="hist" ref={ref} role="listbox" aria-label="Earlier chats" aria-multiselectable="true">
      {ordered.slice(0, 60).map((c) => (
        <div key={c.id} role="option" tabIndex={0} aria-selected={sel.has(c.id)}
          className={`p-item${sel.has(c.id) ? " p-sel" : ""}`} aria-current={current === c.id ? "page" : undefined} title={titleOf(c)}
          onClick={(e) => { if (renaming === c.id) return; if (!sel.rowClick(c.id, e)) onOpen(c.id); }}
          onContextMenu={(e) => menu(e, c)}
          onDoubleClick={() => startRename(c)}
          onKeyDown={(e) => {
            if (e.target !== e.currentTarget) return;
            if (e.key === "Enter") onOpen(c.id);
            if (e.key === "F2") { e.preventDefault(); startRename(c); }
            if (e.key === " ") { e.preventDefault(); sel.toggle(c.id, e); }
            if (e.key === "ArrowDown") { e.preventDefault(); e.currentTarget.nextElementSibling?.focus(); }
            if (e.key === "ArrowUp") { e.preventDefault(); e.currentTarget.previousElementSibling?.focus(); }
          }}>
          {Number(c.pinned) ? <Icon name="pin" size={12} /> : null}
          {renaming === c.id
            ? <input className="p-rename" value={name} autoFocus onChange={(e) => setName(e.target.value)} aria-label="Chat name"
                onFocus={(e) => e.target.select()} onBlur={() => commitRename(c)}
                onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Enter") commitRename(c); if (e.key === "Escape") setRenaming(null); }} />
            : <span className="t">{titleOf(c)}</span>}
          {running.has(c.id) && <span className="run" title="Nova is working on this" />}
        </div>
      ))}
    </div>
  );
}

function Shell({ prefs, models }) {
  const ui = useUi();
  const [view, setView] = useState(() => { const v = stored("nova.paper.view", "chat"); return v === "settings" ? "chat" : v; });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [userTab, setUserTab] = useState(null);
  const [settingsSection, setSettingsSection] = useState("Appearance");
  const [conversationId, setConversationId] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [tabs, setTabs] = useState([]);
  const [expanded, setExpanded] = useState(false);
  const [collapsed, setCollapsed] = useState(() => stored("nova.paper.collapsed", "0") === "1");
  const [onboarding, setOnboarding] = useState(false);
  const [palette, setPalette] = useState(false);
  const [keysOpen, setKeysOpen] = useState(false);
  const [running, setRunning] = useState(() => new Set());
  const [offline, setOffline] = useState(false);
  const [drawer, setDrawer] = useState(false);
  // "Workspace unlocked" appears once, the first time four models are ready
  // (?preview=unlock shows it again for a look).
  // "Later" and "Open Workspace" both mean it has been seen: never again.
  const [unlockDismissed, dismissUnlock] = useDismissed("workspace.unlock");
  const unlockPreview = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("preview") === "unlock";
  const [unlockClosed, setUnlockClosed] = useState(false);
  const unlockShown = !unlockClosed && (unlockPreview || (models.unlocked && unlockDismissed === false));
  const closeUnlock = (open) => { if (!unlockPreview) dismissUnlock(); setUnlockClosed(true); if (open) go("workspace"); };

  const refreshConversations = useCallback(() => {
    listConversations({ tab: "chat" }).then((rows) => setConversations(Array.isArray(rows) ? rows : [])).catch(() => {});
  }, []);
  const refreshTabs = useCallback(() => {
    getCustomTabs().then((rows) => setTabs(Array.isArray(rows) ? rows : [])).catch(() => {});
  }, []);

  useEffect(() => {
    refreshConversations();
    refreshTabs();
    // ?preview=onboarding shows the welcome again without saving anything.
    if (new URLSearchParams(window.location.search).get("preview") === "onboarding") setOnboarding("preview");
    else getUserProfile().then((p) => { if (p && Number(p.onboarding_completed) === 0) setOnboarding(true); }).catch(() => {});
    // Nova can add a tab or retitle a chat during any turn.
    const t = setInterval(() => { refreshConversations(); refreshTabs(); }, 8000);
    return () => clearInterval(t);
  }, [refreshConversations, refreshTabs]);

  // Which chats have a turn running (a dot in the sidebar), and whether the
  // backend is answering at all (a banner when it isn't).
  useEffect(() => {
    let misses = 0;
    const poll = async () => {
      try {
        const res = await fetch(`${BACKEND_URL}/chat/running`, { signal: AbortSignal.timeout(4000) });
        const data = await res.json();
        setRunning(new Set((data.running || []).map((r) => r.conversation_id)));
        misses = 0;
        setOffline(false);
      } catch {
        misses += 1;
        if (misses >= 2) setOffline(true);
      }
    };
    poll();
    const t = setInterval(poll, 4000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => { if (view !== "usertab") store("nova.paper.view", view); }, [view]);
  useEffect(() => { store("nova.paper.collapsed", collapsed ? "1" : "0"); }, [collapsed]);

  const go = useCallback((next, tab = null) => {
    setView(next);
    setUserTab(tab);
    setDrawer(false);
    if (next !== "chat") setExpanded(false);
  }, []);
  const newChat = useCallback(() => { go("chat"); setConversationId(null); }, [go]);
  const openSettings = useCallback((section) => { if (section) setSettingsSection(section); setSettingsOpen(true); }, []);

  // Where a notification leads: "chat:12", "workspace", "academics",
  // "settings:Section".
  const openNotice = useCallback((n) => {
    const view = n?.view || "";
    if (view.startsWith("chat:")) { go("chat"); setConversationId(Number(view.slice(5))); }
    else if (view.startsWith("settings:")) openSettings(view.slice(9));
    else if (["workspace", "academics", "agents", "studio", "memory"].includes(view)) go(view);
  }, [go, openSettings]);

  const draftForNova = useCallback((text) => {
    setPrefill(text);
    setConversationId(null);
    go("chat");
  }, [go]);

  const askNova = async (text) => {
    go("chat");
    setConversationId(null);
    await sendMessage(null, text, [], { onCreated: (id) => { setConversationId(id); refreshConversations(); } });
  };

  // "Ask Nova about this" from a right-click: open a fresh chat with it.
  useEffect(() => {
    const onPrefill = () => { setConversationId(null); go("chat"); };
    window.addEventListener("nova-prefill", onPrefill);
    return () => window.removeEventListener("nova-prefill", onPrefill);
  }, [go]);

  // Global keyboard shortcuts.
  useEffect(() => {
    const onKey = (e) => {
      const mod = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      if (mod && k === "k") { e.preventDefault(); setPalette((p) => !p); }
      else if (mod && !e.shiftKey && k === "n") { e.preventDefault(); newChat(); }
      else if (mod && k === ",") { e.preventDefault(); setSettingsOpen((o) => !o); }
      else if (mod && k === "b") { e.preventDefault(); setCollapsed((c) => !c); }
      else if (mod && e.shiftKey && k === "l") { e.preventDefault(); prefs.setMode(prefs.dark ? "day" : "night"); }
      else if (mod && (k === "/" || k === "?")) { e.preventDefault(); setKeysOpen(true); }
      else if (mod && !e.shiftKey && !e.altKey && /^[1-5]$/.test(e.key)) { e.preventDefault(); go(SECTIONS[Number(e.key) - 1][0]); }
      else if (e.key === "Escape" && !document.querySelector(".p-menu, .p-scrim")) setExpanded(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, newChat, openSettings, prefs]);

  useEffect(() => {
    // The page behind the app follows day and night too.
    document.documentElement.style.background = prefs.dark ? "#0D0E12" : "#F6F4F0";
  }, [prefs.dark]);

  const conversation = conversations.find((c) => c.id === conversationId);
  const activeTab = tabs.find((t) => t.id === userTab);
  const crumb = onboarding ? "Welcome to Nova"
    : view === "chat" ? `Chat · ${conversationId == null ? "New conversation" : titleOf(conversation)}`
    : view === "usertab" ? activeTab?.title || "Your tab"
    : view === "addtab" ? "Add a tab"
    : view === "workspace" ? "Workspace"
    : SECTIONS.find(([k]) => k === view)?.[1] || "Nova";
  useEffect(() => { document.title = `${crumb} · Nova`; }, [crumb]);

  const removeTab = (t) => ui.undoable({
    message: `Removed the "${t.title}" tab.`,
    apply: () => { setTabs((all) => all.filter((x) => x.id !== t.id)); if (userTab === t.id) go("addtab"); },
    revert: () => setTabs((all) => [...all, t]),
    commit: () => deleteCustomTab(t.id),
  });
  const tabMenu = (e, t) => ui.openMenu(e, [
    { label: "Open", icon: "tab", onSelect: () => go("usertab", t.id) },
    { label: "Ask Nova to change it", icon: "chat", onSelect: () => draftForNova(`Change my "${t.title}" tab: `) },
    "-",
    { label: "Remove tab", icon: "trash", danger: true, onSelect: () => removeTab(t) },
  ], { title: t.title });

  const commands = useMemo(() => [
    ...SECTIONS.map(([k, label, icon], i) => ({ id: `go-${k}`, label, icon, group: "Go to", shortcut: `Ctrl+${i + 1}`, order: i, run: () => go(k) })),
    ...(models.unlocked ? [{ id: "go-workspace", label: "Workspace", icon: "team", group: "Go to", run: () => go("workspace") }] : []),
    { id: "new-chat", label: "New chat", icon: "plus", group: "Action", shortcut: keys("Ctrl+N"), run: newChat },
    { id: "add-tab", label: "Add a tab", icon: "plus", group: "Action", run: () => go("addtab") },
    { id: "theme", label: prefs.dark ? "Switch to day" : "Switch to night", icon: prefs.dark ? "sun" : "moon", group: "Action", shortcut: keys("Ctrl+Shift+L"), run: () => prefs.setMode(prefs.dark ? "day" : "night") },
    { id: "sidebar", label: collapsed ? "Show the sidebar" : "Hide the sidebar", icon: "side", group: "Action", shortcut: keys("Ctrl+B"), run: () => setCollapsed((c) => !c) },
    ...(electron?.openMiniplayer ? [{ id: "mini", label: "Open the miniplayer", icon: "pip", group: "Action", run: () => electron.openMiniplayer() }] : []),
    { id: "stop", label: "Stop everything Nova is doing", icon: "stop", group: "Action", keywords: "halt emergency", run: () => operatorStop().then(() => ui.toast("Nova is stopped. Resume from Agents.")) },
    { id: "keys", label: "Keyboard shortcuts", icon: "keys", group: "Help", shortcut: keys("Ctrl+/"), run: () => setKeysOpen(true) },
    ...SETTINGS_SECTIONS.map(([name, icon]) => ({ id: `set-${name}`, label: name, icon, group: "Settings", run: () => openSettings(name) })),
    ...tabs.map((t) => ({ id: `tab-${t.id}`, label: t.title, icon: "tab", group: "Your tab", run: () => go("usertab", t.id) })),
    ...conversations.slice(0, 200).map((c) => ({ id: `c-${c.id}`, label: titleOf(c), icon: "chat", group: "Chat", order: 100, keywords: c.preview, run: () => { go("chat"); setConversationId(c.id); } })),
  ], [collapsed, conversations, go, models.unlocked, newChat, openSettings, prefs, tabs, ui]);

  const style = useMemo(() => ({
    "--pa": prefs.palette.a, "--pb": prefs.palette.b, "--okd": prefs.palette.ok, "--okn": prefs.palette.okn,
  }), [prefs.palette]);

  return (
    <div className={`paper${prefs.dark ? " night" : ""}${expanded ? " expanded" : ""}${onboarding ? " onboarding" : ""}${collapsed ? " collapsed" : ""}${drawer ? " drawer" : ""}`} style={style}>
      <header className={`p-title${electron?.platform === "darwin" ? " mac" : ""}`}>
        <div className="l"><Reactor palette={prefs.palette} dark={prefs.dark} /><b>Nova</b></div>
        <div className="mid">
          <button className="p-searchbtn" onClick={() => setPalette(true)} aria-label={keys("Search and go anywhere (Ctrl+K)")}>
            <Icon name="search" size={13} /><span>{crumb}</span><kbd className="p-kbd">{IS_MAC ? "⌘K" : "Ctrl K"}</kbd>
          </button>
        </div>
        <div className="r">
          <Notifications enabledDesktop={prefs.settings.notify_desktop !== false} onOpen={openNotice} />
          <div className="p-tog" role="group" aria-label="Day or night">
            <button aria-pressed={!prefs.dark} aria-label="Day" title={keys("Day (Ctrl+Shift+L)")} onClick={() => prefs.setMode("day")}><Icon name="sun" /></button>
            <button aria-pressed={prefs.dark} aria-label="Night" title={keys("Night (Ctrl+Shift+L)")} onClick={() => prefs.setMode("night")}><Icon name="moon" /></button>
          </div>
          {electron?.minimizeWindow && electron?.platform !== "darwin" && <>
            <button className="p-wc" aria-label="Minimize" title="Minimize" onClick={() => electron.minimizeWindow()}><Icon name="min" /></button>
            <button className="p-wc" aria-label="Maximize" title="Maximize" onClick={() => electron.maximizeWindow()}><Icon name="max" size={14} /></button>
            <button className="p-wc close" aria-label="Close" title="Close" onClick={() => electron.closeWindow()}><Icon name="x" /></button>
          </>}
        </div>
      </header>
      <div className="p-body">
        <nav className="p-nav" aria-label="Nova">
          {SECTIONS.map(([key, label, icon], i) => (
            <button key={key} className="p-item" aria-label={label} title={`${label} (Ctrl+${i + 1})`} aria-current={view === key ? "page" : undefined} onClick={() => go(key)}>
              <Icon name={icon} /><span className="t">{label}</span>
            </button>
          ))}
          {models.unlocked && (
            <button className="p-item" aria-label="Workspace" title="Workspace" aria-current={view === "workspace" ? "page" : undefined} onClick={() => go("workspace")}>
              <Icon name="team" /><span className="t">Workspace</span>
            </button>
          )}
          <div className="grp">Your tabs</div>
          {tabs.length === 0 && <div className="empty">Nothing yet. Tell Nova what you'd like here.</div>}
          {tabs.map((t) => (
            <button key={t.id} className="p-item" aria-label={t.title} title={t.title} aria-current={view === "usertab" && userTab === t.id ? "page" : undefined}
              onClick={() => go("usertab", t.id)} onContextMenu={(e) => tabMenu(e, t)}>
              <Icon name="tab" /><span className="t">{t.title}</span>
            </button>
          ))}
          <button className="p-item" aria-label="Add tab" title="Add tab" aria-current={view === "addtab" ? "page" : undefined} onClick={() => go("addtab")}><Icon name="plus" /><span className="t">Add tab</span></button>
          <div className="p-navtools">
            <div className="grp">Earlier</div>
            <button className="p-link" onClick={newChat} aria-label="New chat" title={keys("New chat (Ctrl+N)")}><Icon name="plus" size={15} /></button>
            <button className="p-link" onClick={() => setCollapsed(true)} aria-label="Hide the sidebar" title={keys("Hide the sidebar (Ctrl+B)")}><Icon name="side" size={15} /></button>
          </div>
          <History conversations={conversations} setConversations={setConversations} current={view === "chat" ? conversationId : null}
            running={running} onOpen={(id) => { go("chat"); setConversationId(id); }} onDeleted={() => setConversationId(null)} />
          <button className="p-item p-phoneonly" onClick={() => { setDrawer(false); openSettings(); }}><Icon name="gear" /><span className="t">Settings</span></button>
          <div className="bottom">
            {collapsed && <button className="p-item" aria-label="Show the sidebar" title={keys("Show the sidebar (Ctrl+B)")} onClick={() => setCollapsed(false)}><Icon name="side" /><span className="t">Sidebar</span></button>}
            <button className="p-item" aria-label="Miniplayer" onClick={() => electron?.openMiniplayer?.()} disabled={!electron?.openMiniplayer} title={electron?.openMiniplayer ? "Open the miniplayer" : "The miniplayer is part of the desktop app"}>
              <Icon name="pip" /><span className="t">Miniplayer</span>
            </button>
            <button className="p-item" aria-label="Settings" title={keys("Settings (Ctrl+,)")} aria-current={settingsOpen ? "page" : undefined} aria-haspopup="dialog" onClick={() => openSettings()}><Icon name="gear" /><span className="t">Settings</span></button>
          </div>
        </nav>
        {drawer && <div className="p-drawerscrim" onClick={() => setDrawer(false)} />}
        <main className="p-main">
          {offline && <div className="p-banner" role="alert"><i />Nova's engine isn't responding. Reconnecting…</div>}
          {onboarding ? <OnboardingView prefs={prefs} preview={onboarding === "preview"} models={models}
              onDone={(section) => { setOnboarding(false); if (section) openSettings(section); }} />
            : view === "chat" ? (
              <ChatView
                conversationId={conversationId}
                onConversation={(id) => { setConversationId(id); refreshConversations(); }}
                title={conversationId == null ? "New conversation" : titleOf(conversation)}
                palette={prefs.palette}
                dark={prefs.dark}
                expanded={expanded}
                onToggleExpand={() => setExpanded((x) => !x)}
                onNewChat={newChat}
                voiceId={prefs.settings.tts_voice_id}
              />
            )
            : view === "academics" ? <AcademicsView palette={prefs.palette} dark={prefs.dark} onAsk={draftForNova} />
            : view === "studio" ? <StudioView palette={prefs.palette} dark={prefs.dark} />
            : view === "agents" ? <AgentsView palette={prefs.palette} dark={prefs.dark} />
            : view === "memory" ? <MemoryView palette={prefs.palette} dark={prefs.dark} />
            : view === "workspace" ? <WorkspaceView palette={prefs.palette} dark={prefs.dark} onWatch={() => go("agents")} onModels={() => openSettings("Models")} />
            : view === "addtab" ? <AddTabView palette={prefs.palette} dark={prefs.dark} onAsk={askNova} models={models} minModels={WORKSPACE_MIN_MODELS} onModels={() => openSettings("Models")} />
            : view === "usertab" ? (
              <UserTabView tab={activeTab} palette={prefs.palette} dark={prefs.dark} onAsk={draftForNova} onRemove={removeTab} />
            )
            : <ChatView conversationId={conversationId} onConversation={(id) => { setConversationId(id); refreshConversations(); }}
                title={conversationId == null ? "New conversation" : titleOf(conversation)} palette={prefs.palette} dark={prefs.dark}
                expanded={expanded} onToggleExpand={() => setExpanded((x) => !x)} onNewChat={newChat} voiceId={prefs.settings.tts_voice_id} />}
        </main>
      </div>
      <nav className="p-tabbar" aria-label="Nova">
        {[["chat", "Chat", "chat"], ["academics", "Academics", "cap"], ["agents", "Agents", "nodes"], ["memory", "Memory", "brain"]].map(([k, l, i]) => (
          <button key={k} aria-current={view === k && !drawer ? "page" : undefined} onClick={() => go(k)}><Icon name={i} /><span>{l}</span></button>
        ))}
        <button aria-expanded={drawer} onClick={() => setDrawer((d) => !d)}><Icon name="side" /><span>Menu</span></button>
      </nav>
      {settingsOpen && (
        <SettingsView prefs={prefs} section={settingsSection} onSection={setSettingsSection} onModelsChanged={models.refresh}
          onClose={() => setSettingsOpen(false)} />
      )}
      {unlockShown && (
        <div className="p-scrim" style={{ zIndex: 60 }} onPointerDown={(e) => { if (e.target === e.currentTarget) closeUnlock(false); }}
          onKeyDown={(e) => { if (e.key === "Escape") closeUnlock(false); }}>
          <div className="p-dialog p-unlock" role="dialog" aria-modal="true" aria-labelledby="p-unlock-t">
            <div className="p-unlock-r"><Reactor palette={prefs.palette} dark={prefs.dark} state="thinking" /></div>
            <h2 id="p-unlock-t">Workspace unlocked</h2>
            <p>You have {models.count ?? 4} models ready, so they can now work as one team. A director plans your job and hands each step to the model best at it: research, building, checking.</p>
            <div className="p-acts">
              <button className="p-sm" onClick={() => closeUnlock(false)}>Later</button>
              <button className="p-sm dark" autoFocus onClick={() => closeUnlock(true)}>Open Workspace</button>
            </div>
          </div>
        </div>
      )}
      {palette && <Palette commands={commands} onClose={() => setPalette(false)} />}
      {keysOpen && <ShortcutSheet onClose={() => setKeysOpen(false)} />}
    </div>
  );
}

export default function PaperApp() {
  const prefs = usePrefs();
  const models = useModelCount();
  const askRef = useRef(null);
  const layerStyle = useMemo(() => ({
    "--pa": prefs.palette.a, "--pb": prefs.palette.b, "--okd": prefs.palette.ok, "--okn": prefs.palette.okn,
  }), [prefs.palette]);
  return (
    <UiProvider askNova={(text) => askRef.current?.(text)} layerClass={prefs.dark ? "night" : ""} layerStyle={layerStyle}>
      <ShellWithAsk prefs={prefs} models={models} askRef={askRef} />
    </UiProvider>
  );
}

function ShellWithAsk({ askRef, ...props }) {
  // "Ask Nova about this" on selected text: start a chat with it quoted.
  askRef.current = (text) => {
    setPrefill(`About this:\n> ${text.replace(/\n/g, "\n> ")}\n\n`);
    window.dispatchEvent(new CustomEvent("nova-prefill"));
  };
  return <Shell {...props} />;
}
