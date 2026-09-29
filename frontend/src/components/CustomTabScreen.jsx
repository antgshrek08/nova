import React, { useState } from "react";
import { deleteCustomTab } from "../api.js";

export default function CustomTabScreen({ tab, onDeleted, onOpenChatWithPrompt }) {
  const [activeSubTab, setActiveSubTab] = useState("preview");

  if (!tab) {
    return (
      <div className="flex h-full items-center justify-center text-charcoal-500">
        No custom tab selected.
      </div>
    );
  }

  async function handleDelete() {
    if (window.confirm(`Delete custom tab "${tab.title}"?`)) {
      try {
        await deleteCustomTab(tab.id);
        if (onDeleted) onDeleted(tab.id);
      } catch (e) {
        alert("Failed to delete tab: " + e.message);
      }
    }
  }

  return (
    <div className="flex h-full flex-col bg-charcoal-950 text-charcoal-100 font-sans">
      {/* Tab Top Bar */}
      <div className="flex items-center justify-between border-b border-charcoal-800 bg-charcoal-900/60 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600/20 text-indigo-400 font-bold text-sm">
            ✨
          </div>
          <div>
            <h2 className="text-sm font-semibold text-white">{tab.title}</h2>
            <p className="text-xs text-charcoal-400">{tab.description || "Custom User Extensibility Module"}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => onOpenChatWithPrompt?.(`Nova, help me customize and improve the "${tab.title}" tab.`)}
            className="flex items-center gap-1.5 rounded bg-indigo-600/20 border border-indigo-500/30 px-2.5 py-1 text-xs text-indigo-300 hover:bg-indigo-600/30"
          >
            <span>💬 Edit with Nova</span>
          </button>
          <button
            onClick={handleDelete}
            className="rounded bg-rose-950/40 border border-rose-800/30 px-2.5 py-1 text-xs text-rose-300 hover:bg-rose-900/40"
          >
            Remove Tab
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-auto p-4">
        {tab.content_type === "widget" && tab.html_content ? (
          <div className="h-full w-full rounded-xl border border-charcoal-800 bg-charcoal-900/40 p-4 overflow-auto">
            <div
              className="prose prose-invert max-w-none"
              dangerouslySetInnerHTML={{ __html: tab.html_content }}
            />
          </div>
        ) : (
          <div className="flex h-full flex-col items-center justify-center text-center p-8">
            <div className="text-4xl mb-3">🧩</div>
            <h3 className="text-base font-semibold text-white">{tab.title} Extensibility Slot</h3>
            <p className="max-w-md text-xs text-charcoal-400 mt-1 mb-4">
              This custom tab is ready for your widgets, study decks, interactive formulas, or calculators.
            </p>
            <button
              onClick={() => onOpenChatWithPrompt?.(`Nova, generate an interactive widget for "${tab.title}".`)}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-500"
            >
              Ask Nova to Build Content for this Tab
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
