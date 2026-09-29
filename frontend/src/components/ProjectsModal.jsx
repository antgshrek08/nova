import { useState } from "react";
import ProjectList from "./ProjectList.jsx";
import ProjectPanel from "./ProjectPanel.jsx";

/** N.O.V.A.'s redesign folds Projects into a sidebar section rather than a
 * standalone tab -- this modal is where the real Phase 2 project management
 * (instructions, files) still lives, reached via the sidebar's "Manage"
 * link. Reuses ProjectList/ProjectPanel as-is. */
export default function ProjectsModal({ open, onClose, onOpenConversation }) {
  const [projectId, setProjectId] = useState(null);

  if (!open) return null;

  function handleOpenConversation(id) {
    onOpenConversation?.(id);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="flex h-[70vh] w-full max-w-lg flex-col rounded-xl bg-charcoal-900 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-charcoal-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-charcoal-100">Projects</h2>
          <button onClick={onClose} className="text-charcoal-400 hover:text-charcoal-200">
            ✕
          </button>
        </div>
        {projectId == null ? (
          <ProjectList onSelect={setProjectId} />
        ) : (
          <ProjectPanel
            projectId={projectId}
            onBack={() => setProjectId(null)}
            onOpenConversation={handleOpenConversation}
          />
        )}
      </div>
    </div>
  );
}
