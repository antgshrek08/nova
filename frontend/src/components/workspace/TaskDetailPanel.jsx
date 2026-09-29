import { useEffect, useState } from "react";
import TaskGraph from "./TaskGraph.jsx";
import { getWorkspaceTask, cancelWorkspaceTask, retryWorkspaceTask } from "../../api.js";
import { useTaskListVersion } from "../../lib/workspaceStore.js";
import TaskRow from "./TaskRow.jsx";

const ACTIVITY_LABEL = {
  created: "Created",
  planned: "Planned",
  started: "Started",
  files_changed: "Files changed",
  done: "Done",
  error: "Error",
  blocked: "Blocked",
  cancelled: "Cancelled",
  retried: "Retried",
  interrupted: "Interrupted",
  synthesized: "Synthesized",
};

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** Task: "Selecting a task opens a resizable details panel with subtasks,
 * dependencies, activity, outputs, and applicable controls." Refetches the
 * full detail (subtasks/dependencies/activity, none of which the list-shaped
 * live task store carries) whenever the store's version signal changes --
 * cheap enough for a desktop app's own task volume, and simpler/more
 * correct than trying to keep a second, richer shape in sync over the
 * socket too. */
export default function TaskDetailPanel({ taskId, onClose, onOpenTask }) {
  const [task, setTask] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retryConfirm, setRetryConfirm] = useState(null);
  const version = useTaskListVersion();

  useEffect(() => {
    let cancelled = false;
    getWorkspaceTask(taskId)
      .then((t) => !cancelled && setTask(t))
      .catch((err) => !cancelled && setError(err.message || "Couldn't load this task."));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `version` is a
    // deliberate refetch trigger, not data this effect reads directly.
  }, [taskId, version]);

  async function handleCancel() {
    setBusy(true);
    try {
      await cancelWorkspaceTask(taskId);
    } catch (err) {
      setError(err.message || "Couldn't cancel this task.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRetry(confirm = false) {
    setBusy(true);
    setError("");
    try {
      const result = await retryWorkspaceTask(taskId, confirm);
      if (result.requires_confirmation) {
        setRetryConfirm(result.reason);
      } else {
        setRetryConfirm(null);
      }
    } catch (err) {
      setError(err.message || "Couldn't retry this task.");
    } finally {
      setBusy(false);
    }
  }

  if (error && !task) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
        <p className="text-sm text-rose-400">{error}</p>
        <button onClick={onClose} className="text-xs text-charcoal-400 hover:text-charcoal-200">Close</button>
      </div>
    );
  }
  if (!task) {
    return <div className="flex h-full items-center justify-center text-sm text-charcoal-500">Loading…</div>;
  }

  const canCancel = task.status === "running" || task.status === "queued" || task.status === "blocked";
  const canRetry = ["error", "partial", "cancelled", "interrupted"].includes(task.status);
  const isRunning = task.status === "running";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-start justify-between gap-2 border-b border-charcoal-800 px-4 py-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-charcoal-200">{task.title}</p>
          <p className="mt-0.5 text-[11px] text-charcoal-500">
            {task.team
              ? `${task.team} · ${task.role}`
              : task.subtasks.length > 0
                ? `Delegated to ${task.subtasks.length} subtask${task.subtasks.length > 1 ? "s" : ""}`
                : "Direct answer"}{" "}
            · {task.status}
            {task.model && <> · <span className="font-mono">{task.model}</span></>}
          </p>
        </div>
        <button onClick={onClose} className="shrink-0 text-charcoal-500 hover:text-charcoal-200">✕</button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {task.description && task.description !== task.title && (
          <div className="mb-4">
            <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-charcoal-500">Request</p>
            <p className="whitespace-pre-wrap text-[13px] text-charcoal-300">{task.description}</p>
          </div>
        )}

        {(task.result_summary || task.error) && (
          <div className="mb-4">
            <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-charcoal-500">
              {task.error ? "Error" : "Output"}
            </p>
            <p className={`whitespace-pre-wrap text-[13px] ${task.error ? "text-rose-300" : "text-charcoal-300"}`}>
              {task.error || task.result_summary}
            </p>
          </div>
        )}

        {task.artifacts.length > 0 && (
          <div className="mb-4">
            <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-charcoal-500">
              Files changed
            </p>
            <ul className="space-y-1">
              {task.artifacts.map((a) => (
                <li key={a.path} className="flex items-center gap-2 font-mono text-[12px] text-charcoal-300">
                  <span
                    className={`rounded px-1 text-[10px] ${
                      a.kind === "added" ? "bg-emerald-500/15 text-emerald-300" :
                      a.kind === "deleted" ? "bg-rose-500/15 text-rose-300" : "bg-sky-500/15 text-sky-300"
                    }`}
                  >
                    {a.kind}
                  </span>
                  <span className="truncate">{a.path}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {task.dependencies.length > 0 && (
          <div className="mb-4">
            <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-charcoal-500">
              Depends on
            </p>
            <p className="text-[12px] text-charcoal-400">
              {task.dependencies.length} task{task.dependencies.length > 1 ? "s" : ""} must finish first.
            </p>
          </div>
        )}

        {task.subtasks.length > 0 && (
          <div className="mb-4">
            <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-charcoal-500">
              Subtasks ({task.subtasks.length})
            </p>
            <div className="-mx-1 divide-y divide-charcoal-800/60 rounded-md ring-1 ring-charcoal-800">
              {task.subtasks.map((sub) => (
                <TaskRow key={sub.id} task={sub} selected={false} onSelect={onOpenTask} />
              ))}
            </div>
          </div>
        )}

        {/* The plan's real shape: which subtasks exist and what blocks what.
            Only shown for a task that actually delegated -- a direct run has
            no dependencies to draw. */}
        <div>
          <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-charcoal-500">Plan</p>
          <div className="rounded-lg border border-charcoal-800 bg-charcoal-900/40">
            <TaskGraph taskId={task.id} />
          </div>
        </div>

        {task.activity.length > 0 && (
          <div>
            <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-charcoal-500">Activity</p>
            <ul className="space-y-1.5">
              {task.activity.map((a) => (
                <li key={a.id} className="flex gap-2 text-[12px]">
                  <span className="shrink-0 font-mono text-charcoal-600">{formatTime(a.created_at)}</span>
                  <span className="shrink-0 text-charcoal-400">{ACTIVITY_LABEL[a.kind] || a.kind}</span>
                  <span className="min-w-0 flex-1 text-charcoal-300">{a.message}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-charcoal-800 px-4 py-2.5">
        {retryConfirm && (
          <div className="mb-2 rounded-md bg-amber-950/40 px-2.5 py-2 text-[11.5px] text-amber-300">
            <p>{retryConfirm}</p>
            <div className="mt-1.5 flex gap-2">
              <button onClick={() => handleRetry(true)} className="rounded bg-amber-600 px-2 py-1 text-[11px] font-medium text-white hover:bg-amber-500">
                Retry anyway
              </button>
              <button onClick={() => setRetryConfirm(null)} className="rounded px-2 py-1 text-[11px] text-charcoal-400 hover:text-charcoal-200">
                Cancel
              </button>
            </div>
          </div>
        )}
        {error && <p className="mb-2 text-[11.5px] text-rose-400">{error}</p>}
        <div className="flex items-center gap-2">
          {canCancel && (
            <button
              onClick={handleCancel}
              disabled={busy}
              className="rounded-md px-2.5 py-1.5 text-[11.5px] font-medium text-charcoal-300 ring-1 ring-charcoal-600 hover:bg-charcoal-800 disabled:opacity-50"
              title={isRunning ? "Cancel reaches the running operation directly." : "Cancel before it starts."}
            >
              Cancel
            </button>
          )}
          {canRetry && (
            <button
              onClick={() => handleRetry(false)}
              disabled={busy}
              className="rounded-md px-2.5 py-1.5 text-[11.5px] font-medium text-charcoal-300 ring-1 ring-charcoal-600 hover:bg-charcoal-800 disabled:opacity-50"
            >
              Retry
            </button>
          )}
          {!canCancel && !canRetry && (
            <span className="text-[11.5px] text-charcoal-600">No actions available for a {task.status} task.</span>
          )}
        </div>
      </div>
    </div>
  );
}
