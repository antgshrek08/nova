import { useState } from "react";
import GraphView from "./GraphView.jsx";
import HistoryView from "./HistoryView.jsx";
import FactsView from "./FactsView.jsx";
import SettingsView from "./SettingsView.jsx";

const SECTIONS = [
  { id: "graph", label: "Graph" },
  { id: "history", label: "History" },
  { id: "facts", label: "Facts" },
  // "Options", not "Settings": the rail already has a Settings destination,
  // and having both on screen made it ambiguous which one held what.
  { id: "settings", label: "Options" },
];

/** Memory as a full application destination (Milestone 2), not a modal --
 * an Obsidian-inspired "second brain": spacious dark charcoal canvas,
 * restrained emerald accents, Graph/History/Facts as peer views behind one
 * small internal nav. Reached from NavRail's Memory destination, same as
 * Chat/Code/Workspace (see App.jsx). */
export default function MemoryScreen({ activeConversationIds, conversationListRefreshKey, onOpenConversation, onManageProjects }) {
  const [section, setSection] = useState("graph");

  return (
    <div className="flex h-full min-h-0 min-w-0">
      <nav className="flex w-44 shrink-0 flex-col border-r border-charcoal-700 bg-charcoal-900 py-4">
        <h2 className="mb-3 px-4 text-sm font-semibold tracking-wide text-charcoal-100">Memory</h2>
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            onClick={() => setSection(s.id)}
            className={`px-4 py-2 text-left text-sm transition-colors ${
              section === s.id
                ? "bg-emerald-500/10 text-emerald-400"
                : "text-charcoal-400 hover:bg-charcoal-800 hover:text-charcoal-200"
            }`}
          >
            {s.label}
          </button>
        ))}
      </nav>

      <div className="min-h-0 min-w-0 flex-1">
        {section === "graph" && <GraphView onOpenConversation={onOpenConversation} />}
        {section === "history" && (
          <HistoryView
            activeConversationIds={activeConversationIds}
            refreshKey={conversationListRefreshKey}
            onOpenConversation={onOpenConversation}
            onManageProjects={onManageProjects}
          />
        )}
        {section === "facts" && <FactsView />}
        {section === "settings" && <SettingsView />}
      </div>
    </div>
  );
}
