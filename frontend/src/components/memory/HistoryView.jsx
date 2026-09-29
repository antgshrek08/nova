import { useEffect, useMemo, useState } from "react";
import { listConversations, setConversationPinned, deleteConversation } from "../../api.js";

const TABS = [
  { id: "chat", label: "Chat" },
  { id: "code", label: "Code" },
];

const GENERIC_TITLE = "New conversation";

function timeAgo(iso) {
  const then = new Date(iso.replace(" ", "T") + "Z").getTime();
  const seconds = Math.max(0, (Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function dayBucket(iso) {
  const d = new Date(iso.replace(" ", "T") + "Z");
  const now = new Date();
  const startOfDay = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const diffDays = Math.round((startOfDay(now) - startOfDay(d)) / 86400000);
  if (diffDays <= 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return "This week";
  if (diffDays < 30) return "This month";
  return "Older";
}

const BUCKET_ORDER = ["Pinned", "Today", "Yesterday", "This week", "This month", "Older"];

function excerpt(text, length = 72) {
  if (!text) return "";
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length <= length ? flat : flat.slice(0, length - 1) + "…";
}

/** One History row (task: "readable titles, a short preview, and a
 * timestamp" / "Preserve user-written titles; use a source-derived preview
 * when a title is simply 'New conversation'"). `preview` is a real excerpt
 * of the conversation's own most recent message (see db.py's
 * list_conversations -- a correlated subquery, not a second round trip per
 * row), not invented summary text. */
function Row({ conv, active, onSelect, onTogglePin, onDelete }) {
  const hasRealTitle = conv.title && conv.title.trim() && conv.title !== GENERIC_TITLE;
  const primary = hasRealTitle ? conv.title : excerpt(conv.preview) || GENERIC_TITLE;
  const secondary = hasRealTitle ? excerpt(conv.preview) : null;

  return (
    <div
      onClick={() => onSelect(conv.id)}
      className={`group mx-1 mb-1 flex min-w-0 cursor-pointer flex-col gap-0.5 rounded-lg px-3 py-2 ${
        active ? "bg-charcoal-800 ring-1 ring-emerald-600/40" : "hover:bg-charcoal-800"
      }`}
    >
      <div className="flex min-w-0 items-center justify-between gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-charcoal-100">{primary}</span>
        <span className="flex shrink-0 items-center gap-2">
          <span className="whitespace-nowrap text-[10.5px] text-charcoal-500">{timeAgo(conv.updated_at)}</span>
          <span
            className={`flex items-center gap-1 transition-opacity ${
              conv.pinned ? "opacity-100" : "opacity-0 group-hover:opacity-100"
            }`}
          >
            <button
              onClick={(e) => {
                e.stopPropagation();
                onTogglePin(conv);
              }}
              title={conv.pinned ? "Unpin" : "Pin"}
              className={conv.pinned ? "text-emerald-400" : "text-charcoal-500 hover:text-charcoal-200"}
            >
              <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor">
                <path d="M9.828.722a.5.5 0 0 1 .354.146l4.95 4.95a.5.5 0 0 1 0 .707c-.48.48-1.072.588-1.503.588-.177 0-.335-.018-.46-.039l-3.134 3.134a5.927 5.927 0 0 1 .16 1.013c.046.702-.032 1.687-.72 2.375a.5.5 0 0 1-.707 0l-2.829-2.828-3.182 3.182c-.195.195-1.219.902-1.414.707-.195-.195.512-1.22.707-1.414l3.182-3.182-2.828-2.829a.5.5 0 0 1 0-.707c.688-.688 1.673-.767 2.375-.72a5.922 5.922 0 0 1 1.013.16l3.134-3.133a2.772 2.772 0 0 1-.04-.461c0-.43.108-1.022.589-1.503a.5.5 0 0 1 .353-.146z" />
              </svg>
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete(conv.id);
              }}
              title="Delete"
              className="text-charcoal-500 hover:text-rose-400"
            >
              ✕
            </button>
          </span>
        </span>
      </div>
      {secondary && <p className="truncate text-xs text-charcoal-500">{secondary}</p>}
    </div>
  );
}

/** History (task: "History must retain conversation search and reopening in
 * the correct Chat/Code context"). Refinement pass adds a real search field,
 * date-grouped rows with readable titles/preview/timestamp, and keeps
 * pin/delete management working -- reopening still hands (tab, id) up to
 * MemoryScreen -> App.jsx exactly as before. */
export default function HistoryView({ activeConversationIds, refreshKey, onOpenConversation, onManageProjects }) {
  const [tab, setTab] = useState("chat");
  const [conversations, setConversations] = useState([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    try {
      setConversations(await listConversations({ tab }));
      setError("");
    } catch (err) {
      setError(err.message || "Couldn't reach N.O.V.A.");
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, refreshKey]);

  async function handleTogglePin(conv) {
    await setConversationPinned(conv.id, !conv.pinned);
    await refresh();
  }

  async function handleDelete(id) {
    if (!window.confirm("Delete this conversation?")) return;
    await deleteConversation(id);
    await refresh();
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter(
      (c) => (c.title || "").toLowerCase().includes(q) || (c.preview || "").toLowerCase().includes(q)
    );
  }, [conversations, query]);

  const grouped = useMemo(() => {
    const buckets = {};
    for (const c of filtered) {
      const key = c.pinned ? "Pinned" : dayBucket(c.updated_at);
      (buckets[key] ||= []).push(c);
    }
    return BUCKET_ORDER.filter((k) => buckets[k]?.length).map((k) => [k, buckets[k]]);
  }, [filtered]);

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-charcoal-700 px-5 py-3">
        <div className="flex gap-1.5">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors ${
                tab === t.id
                  ? "bg-emerald-600 text-white"
                  : "text-charcoal-400 ring-1 ring-charcoal-600 hover:bg-charcoal-800 hover:text-charcoal-200"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search conversations…"
          className="min-w-0 flex-1 rounded-lg bg-charcoal-850 px-3 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-600 focus:ring-emerald-500"
        />
        {tab === "chat" && (
          <button onClick={onManageProjects} className="shrink-0 text-xs text-charcoal-500 hover:text-charcoal-300">
            Manage projects
          </button>
        )}
      </div>

      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden py-2">
        {error && <p className="px-4 py-6 text-center text-xs text-rose-400">Couldn't reach N.O.V.A.: {error}</p>}
        {!error && filtered.length === 0 && (
          <p className="px-4 py-6 text-center text-xs text-charcoal-600">
            {query.trim() ? "No conversations match that search." : "No conversations yet."}
          </p>
        )}
        {!error &&
          grouped.map(([label, items]) => (
            <div key={label} className="mb-3">
              <p className="mb-1 px-4 text-[10px] font-semibold uppercase tracking-wide text-charcoal-500">{label}</p>
              {items.map((c) => (
                <Row
                  key={c.id}
                  conv={c}
                  active={activeConversationIds?.[tab] === c.id}
                  onSelect={(id) => onOpenConversation(tab, id)}
                  onTogglePin={handleTogglePin}
                  onDelete={handleDelete}
                />
              ))}
            </div>
          ))}
      </div>
    </div>
  );
}
