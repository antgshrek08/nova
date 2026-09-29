import { useEffect, useState } from "react";
import {
  listConversations,
  createConversation,
  deleteConversation,
  setConversationPinned,
} from "../api.js";

function timeAgo(iso) {
  const then = new Date(iso.replace(" ", "T") + "Z").getTime();
  const seconds = Math.max(0, (Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function Item({ conv, active, onSelect, onTogglePin, onDelete, sub }) {
  return (
    <div
      onClick={() => onSelect(conv.id)}
      className={`group mx-2 mb-1 flex cursor-pointer flex-col rounded-md px-2 py-1.5 text-xs ${
        active ? "bg-slate-800 text-slate-100" : "text-slate-300 hover:bg-slate-800/60"
      }`}
    >
      <div className="flex items-center justify-between gap-1">
        <span className="truncate">{conv.title}</span>
        <span
          className={`flex shrink-0 items-center gap-1.5 transition-opacity ${
            conv.pinned ? "opacity-100" : "opacity-0 group-hover:opacity-100"
          }`}
        >
          <button
            onClick={(e) => {
              e.stopPropagation();
              onTogglePin(conv);
            }}
            title={conv.pinned ? "Unpin" : "Pin"}
            className={conv.pinned ? "text-indigo-400" : "text-slate-500 hover:text-slate-200"}
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
            className="text-slate-500 hover:text-red-400"
          >
            ✕
          </button>
        </span>
      </div>
      {sub && <span className="mt-0.5 font-mono text-[10.5px] text-slate-500">{sub}</span>}
    </div>
  );
}

function Section({ label, items, active, onSelect, onTogglePin, onDelete, subFor, extra }) {
  if (items.length === 0) return null;
  return (
    <div className="mb-3">
      <div className="mb-1 flex items-center justify-between px-2">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</span>
        {extra}
      </div>
      {items.map((c) => (
        <Item
          key={c.id}
          conv={c}
          active={active === c.id}
          onSelect={onSelect}
          onTogglePin={onTogglePin}
          onDelete={onDelete}
          sub={subFor?.(c)}
        />
      ))}
    </div>
  );
}

/** Chat/Code tab sidebar: New-chat button + Pinned/Scheduled/Projects/Recents
 * sections, scoped to `tab` -- Code's history never mixes with Chat's since
 * both query /conversations?tab=... independently. Buckets are mutually
 * exclusive by priority (pinned > scheduled > project > recent) so a
 * conversation never appears twice. */
export default function ConversationSidebar({ tab, activeId, onSelect, refreshKey, onManageProjects }) {
  const [conversations, setConversations] = useState([]);
  const [error, setError] = useState("");

  async function refresh() {
    try {
      setConversations(await listConversations({ tab }));
      setError("");
    } catch (err) {
      // Backend-outage task: an unreachable backend must not read as "no
      // conversations yet" -- those are different facts (see the same fix
      // in FactsView.jsx for Remembered Facts). Existing list is left in
      // place rather than cleared.
      setError(err.message || "Couldn't reach N.O.V.A.");
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, refreshKey]);

  async function handleNew() {
    const conv = await createConversation({ tab });
    await refresh();
    onSelect(conv.id);
  }

  async function handleTogglePin(conv) {
    await setConversationPinned(conv.id, !conv.pinned);
    await refresh();
  }

  async function handleDelete(id) {
    if (!window.confirm("Delete this conversation?")) return;
    await deleteConversation(id);
    await refresh();
    if (activeId === id) onSelect(null);
  }

  const pinned = conversations.filter((c) => c.pinned);
  const scheduled = conversations.filter((c) => !c.pinned && c.schedule_label);
  const projects = conversations.filter((c) => !c.pinned && !c.schedule_label && c.project_id != null);
  const recents = conversations.filter(
    (c) => !c.pinned && !c.schedule_label && c.project_id == null
  );

  return (
    <div className="flex flex-1 flex-col overflow-y-auto py-2">
      <button
        onClick={handleNew}
        className="mx-2 mb-3 rounded-md border border-dashed border-slate-700 px-2 py-1.5 text-xs font-medium text-slate-400 hover:border-slate-500 hover:text-slate-200"
      >
        + New {tab === "code" ? "code chat" : "chat"}
      </button>

      <Section label="Pinned" items={pinned} active={activeId} onSelect={onSelect} onTogglePin={handleTogglePin} onDelete={handleDelete} />
      <Section
        label="Scheduled"
        items={scheduled}
        active={activeId}
        onSelect={onSelect}
        onTogglePin={handleTogglePin}
        onDelete={handleDelete}
        subFor={(c) => c.schedule_label}
      />
      <Section
        label="Projects"
        items={projects}
        active={activeId}
        onSelect={onSelect}
        onTogglePin={handleTogglePin}
        onDelete={handleDelete}
        extra={
          <button onClick={onManageProjects} className="text-[10px] text-slate-500 hover:text-slate-300">
            Manage
          </button>
        }
      />
      <Section
        label="Recents"
        items={recents}
        active={activeId}
        onSelect={onSelect}
        onTogglePin={handleTogglePin}
        onDelete={handleDelete}
        subFor={(c) => timeAgo(c.updated_at)}
      />

      {error && <p className="px-2 py-4 text-center text-xs text-red-400">Couldn't reach N.O.V.A.: {error}</p>}
      {!error && conversations.length === 0 && (
        <p className="px-2 py-4 text-center text-xs text-slate-600">No conversations yet.</p>
      )}
    </div>
  );
}
