import { useEffect, useState } from "react";
import { listConversations, createConversation, deleteConversation } from "../api.js";

export default function ConversationList({ tab, projectId = null, activeId, onSelect, refreshKey }) {
  const [conversations, setConversations] = useState([]);

  async function refresh() {
    const data = await listConversations({ tab, projectId });
    setConversations(data);
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, projectId, refreshKey]);

  async function handleNew() {
    const conv = await createConversation({ tab, projectId });
    await refresh();
    onSelect(conv.id);
  }

  async function handleDelete(e, id) {
    e.stopPropagation();
    if (!window.confirm("Delete this conversation?")) return;
    await deleteConversation(id);
    await refresh();
    if (activeId === id) onSelect(null);
  }

  return (
    <div className="flex flex-1 flex-col overflow-y-auto">
      <button
        onClick={handleNew}
        className="m-2 rounded-md border border-dashed border-slate-700 px-2 py-1.5 text-xs font-medium text-slate-400 hover:border-slate-500 hover:text-slate-200"
      >
        + New conversation
      </button>
      {conversations.map((c) => (
        <div
          key={c.id}
          onClick={() => onSelect(c.id)}
          className={`group mx-2 mb-1 flex cursor-pointer items-center justify-between rounded-md px-2 py-1.5 text-xs ${
            activeId === c.id ? "bg-slate-800 text-slate-100" : "text-slate-400 hover:bg-slate-800/60"
          }`}
        >
          <span className="truncate">{c.title}</span>
          <button
            onClick={(e) => handleDelete(e, c.id)}
            className="ml-2 shrink-0 text-slate-500 opacity-0 hover:text-red-400 group-hover:opacity-100"
          >
            ✕
          </button>
        </div>
      ))}
      {conversations.length === 0 && (
        <p className="px-2 py-4 text-center text-xs text-slate-600">No conversations yet.</p>
      )}
    </div>
  );
}
