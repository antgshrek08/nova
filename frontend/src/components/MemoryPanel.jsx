import { useEffect, useState } from "react";
import { searchMemory, listMemory, updateMemory, deleteMemory } from "../api.js";
import ConversationSidebar from "./ConversationSidebar.jsx";

function MemoryRow({ entry, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(entry.content);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await updateMemory(entry.id, draft);
      setEditing(false);
      onChanged();
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm("Forget this memory? This can't be undone.")) return;
    await deleteMemory(entry.id);
    onChanged();
  }

  return (
    <div className="rounded-md bg-slate-800/60 p-2 text-xs">
      <div className="mb-1 flex items-center justify-between text-slate-500">
        <span>
          {entry.role} · {entry.category || "uncategorized"} · conversation #{entry.conversation_id}
          {entry.distance != null && ` · distance ${entry.distance.toFixed(2)}`}
        </span>
        <div className="flex gap-2">
          <button onClick={() => setEditing((e) => !e)} className="hover:text-slate-200">
            {editing ? "Cancel" : "Edit"}
          </button>
          <button onClick={handleDelete} className="hover:text-red-400">
            Forget
          </button>
        </div>
      </div>
      {editing ? (
        <div className="space-y-1">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            className="w-full resize-none rounded-md bg-slate-900 px-2 py-1 text-slate-100 outline-none ring-1 ring-slate-700 focus:ring-indigo-500"
          />
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-md bg-indigo-600 px-2 py-1 text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      ) : (
        <p className="whitespace-pre-wrap text-slate-200">{entry.content}</p>
      )}
    </div>
  );
}

/** "Remembered Facts" -- the panel's original search+browse view, unchanged
 * functionally, just no longer the only thing this modal does (see
 * MemoryPanel below). */
function RememberedFacts() {
  const [query, setQuery] = useState("");
  const [entries, setEntries] = useState([]);
  const [mode, setMode] = useState("browse"); // "browse" | "search"
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      if (mode === "search" && query.trim()) {
        setEntries(await searchMemory(query.trim(), 15));
      } else {
        setEntries(await listMemory(50));
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSearch(e) {
    e.preventDefault();
    if (!query.trim()) {
      setMode("browse");
      await refresh();
      return;
    }
    setMode("search");
    setLoading(true);
    try {
      setEntries(await searchMemory(query.trim(), 15));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col p-4">
      <form onSubmit={handleSearch} className="mb-3 flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search everything remembered across conversations…"
          className="flex-1 rounded-md bg-slate-800 px-3 py-1.5 text-sm text-slate-100 outline-none ring-1 ring-slate-700 focus:ring-indigo-500"
        />
        <button
          type="submit"
          className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
        >
          Search
        </button>
      </form>

      <p className="mb-2 text-xs text-slate-500">
        {mode === "search" ? `Search results for "${query}"` : "Most recently remembered"}
      </p>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
        {loading && <p className="text-center text-xs text-slate-500">Loading…</p>}
        {!loading && entries.length === 0 && (
          <p className="text-center text-xs text-slate-600">Nothing here yet.</p>
        )}
        {entries.map((entry) => (
          <MemoryRow key={entry.id} entry={entry} onChanged={refresh} />
        ))}
      </div>
    </div>
  );
}

/** History (task: "Move conversation browsing into the existing Memory
 * destination... Add History and Remembered Facts sections") -- a thin
 * Chat/Code toggle in front of the existing ConversationSidebar, reused
 * as-is so listing, pinning, scheduling, deleting, and Projects management
 * all keep working exactly like they did in the removed header drawer.
 * Selecting a conversation hands (tab, id) up to App.jsx, which switches to
 * the right screen and closes this panel -- "Opening a conversation returns
 * to the correct Chat or Code context." */
function History({ activeConversationIds, refreshKey, onOpenConversation, onManageProjects }) {
  const [tab, setTab] = useState("chat");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 gap-1 border-b border-slate-800 p-3">
        {[
          { id: "chat", label: "Chat" },
          { id: "code", label: "Code" },
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
              tab === t.id ? "bg-indigo-600 text-white" : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        <ConversationSidebar
          tab={tab}
          activeId={activeConversationIds?.[tab] ?? null}
          onSelect={(id) => onOpenConversation(tab, id)}
          refreshKey={refreshKey}
          onManageProjects={onManageProjects}
        />
      </div>
    </div>
  );
}

const SECTIONS = [
  { id: "history", label: "History" },
  { id: "facts", label: "Remembered Facts" },
];

export default function MemoryPanel({ open, onClose, activeConversationIds, conversationListRefreshKey, onOpenConversation, onManageProjects }) {
  const [section, setSection] = useState("history");

  if (!open) return null;

  function handleOpenConversation(tab, id) {
    onOpenConversation?.(tab, id);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="flex h-[80vh] w-full max-w-3xl overflow-hidden rounded-xl bg-slate-900 shadow-xl">
        <div className="flex w-40 shrink-0 flex-col border-r border-slate-800 py-4">
          <h2 className="mb-3 px-4 text-sm font-semibold text-slate-100">Memory</h2>
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              onClick={() => setSection(s.id)}
              className={`px-4 py-2 text-left text-sm transition-colors ${
                section === s.id ? "bg-slate-800 text-slate-100" : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>

        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex shrink-0 items-center justify-between border-b border-slate-800 px-4 py-3">
            <h3 className="text-sm font-semibold text-slate-100">{SECTIONS.find((s) => s.id === section)?.label}</h3>
            <button className="text-sm text-slate-400 hover:text-slate-200" onClick={onClose}>
              Close
            </button>
          </div>

          {section === "history" ? (
            <History
              activeConversationIds={activeConversationIds}
              refreshKey={conversationListRefreshKey}
              onOpenConversation={handleOpenConversation}
              onManageProjects={onManageProjects}
            />
          ) : (
            <RememberedFacts />
          )}
        </div>
      </div>
    </div>
  );
}
