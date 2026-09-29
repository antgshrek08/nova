import { useMemo, useState } from "react";
import { useTasks } from "../../lib/workspaceStore.js";
import TaskRow from "./TaskRow.jsx";
import TaskDetailPanel from "./TaskDetailPanel.jsx";

const ATTENTION_STATUSES = new Set(["error", "partial", "blocked", "interrupted"]);
const DONE_STATUSES = new Set(["done", "cancelled"]);

function matchesSearch(task, query) {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    task.title.toLowerCase().includes(q) ||
    (task.team || "").toLowerCase().includes(q) ||
    (task.role || "").toLowerCase().includes(q) ||
    (task.model || "").toLowerCase().includes(q)
  );
}

/** Task: "A small Tasks tab/drawer provides history and detailed task
 * controls" -- the old task-dashboard's Active/Attention/Queued/Completed
 * grouping and detail panel, demoted from Workspace's default screen into a
 * slide-over reachable by its own tab, so the graph canvas + reactor stays
 * the thing Workspace opens into. New requests enter through normal Chat;
 * this drawer contains history, details, cancellation, and retry only. */
export default function TasksDrawer({ open, onClose }) {
  const { tasks, loaded } = useTasks();
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [showCompleted, setShowCompleted] = useState(false);

  const topLevel = useMemo(
    () => tasks.filter((t) => t.parent_id == null && matchesSearch(t, query)),
    [tasks, query]
  );
  const active = topLevel.filter((t) => t.status === "running");
  const queued = topLevel.filter((t) => t.status === "queued");
  const attention = topLevel.filter((t) => ATTENTION_STATUSES.has(t.status));
  const completed = topLevel.filter((t) => DONE_STATUSES.has(t.status));


  return (
    <>
      <div
        aria-hidden="true"
        onClick={onClose}
        className={`absolute inset-0 z-20 bg-charcoal-950/40 transition-opacity ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />
      <div
        className={`absolute inset-y-0 left-0 z-30 flex w-full max-w-md min-w-0 flex-col border-r border-charcoal-800 bg-charcoal-950 shadow-2xl transition-transform duration-200 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex shrink-0 items-center gap-2 border-b border-charcoal-800 px-4 py-2.5">
          <h2 className="font-mono text-[13px] font-semibold tracking-wide text-charcoal-200">Tasks</h2>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter…"
            className="ml-auto min-w-0 max-w-[9rem] flex-1 rounded-md bg-charcoal-900 px-2.5 py-1.5 text-[12px] text-charcoal-200 placeholder:text-charcoal-600 ring-1 ring-charcoal-800 focus:outline-none focus:ring-emerald-600"
          />
          <button onClick={onClose} className="shrink-0 text-charcoal-500 hover:text-charcoal-200">✕</button>
        </div>


        <div className="flex min-h-0 flex-1 min-w-0">
          <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
            {!loaded && <p className="px-4 py-6 text-center text-sm text-charcoal-500">Loading tasks…</p>}
            {loaded && topLevel.length === 0 && (
              <p className="px-4 py-6 text-center text-sm text-charcoal-500">
                No tasks yet. Ask Nova for multi-step work in Chat.
              </p>
            )}
            {active.length > 0 && (
              <Section title="Active" count={active.length}>
                {active.map((t) => (
                  <TaskRow key={t.id} task={t} selected={t.id === selectedId} onSelect={setSelectedId} />
                ))}
              </Section>
            )}
            {attention.length > 0 && (
              <Section title="Needs attention" count={attention.length} accent="text-amber-400">
                {attention.map((t) => (
                  <TaskRow key={t.id} task={t} selected={t.id === selectedId} onSelect={setSelectedId} />
                ))}
              </Section>
            )}
            {queued.length > 0 && (
              <Section title="Queued" count={queued.length}>
                {queued.map((t) => (
                  <TaskRow key={t.id} task={t} selected={t.id === selectedId} onSelect={setSelectedId} />
                ))}
              </Section>
            )}
            {completed.length > 0 && (
              <Section
                title="Completed"
                count={completed.length}
                collapsed={!showCompleted}
                onToggle={() => setShowCompleted((v) => !v)}
              >
                {showCompleted &&
                  completed.map((t) => (
                    <TaskRow key={t.id} task={t} selected={t.id === selectedId} onSelect={setSelectedId} />
                  ))}
              </Section>
            )}
          </div>

          {selectedId != null && (
            <div className="min-h-0 w-[280px] shrink-0 border-l border-charcoal-800 bg-charcoal-900">
              <TaskDetailPanel taskId={selectedId} onClose={() => setSelectedId(null)} onOpenTask={setSelectedId} />
            </div>
          )}
        </div>
      </div>
    </>
  );
}

export function useAttentionCount() {
  const { tasks } = useTasks();
  return tasks.filter((t) => t.parent_id == null && ATTENTION_STATUSES.has(t.status)).length;
}

function Section({ title, count, children, accent, collapsed, onToggle }) {
  return (
    <div>
      <button
        onClick={onToggle}
        className={`flex w-full items-center gap-2 px-4 pb-1.5 pt-3 text-[10.5px] font-semibold uppercase tracking-wide ${
          accent || "text-charcoal-500"
        } ${onToggle ? "hover:text-charcoal-300" : ""}`}
      >
        {onToggle && <span className="text-charcoal-600">{collapsed ? "▸" : "▾"}</span>}
        <span>{title}</span>
        <span className="text-charcoal-600">({count})</span>
      </button>
      {!collapsed && <div>{children}</div>}
    </div>
  );
}
