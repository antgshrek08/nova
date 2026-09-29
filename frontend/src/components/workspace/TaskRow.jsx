import { TEAM_LABEL } from "../../lib/teamRoster.js";
const STATUS_STYLE = {
  running: { dot: "bg-sky-400", text: "text-sky-300", label: "Running" },
  queued: { dot: "bg-charcoal-500", text: "text-charcoal-400", label: "Queued" },
  blocked: { dot: "bg-amber-400", text: "text-amber-300", label: "Blocked" },
  interrupted: { dot: "bg-amber-400", text: "text-amber-300", label: "Interrupted" },
  error: { dot: "bg-rose-400", text: "text-rose-300", label: "Failed" },
  partial: { dot: "bg-amber-400", text: "text-amber-300", label: "Partial" },
  cancelled: { dot: "bg-charcoal-600", text: "text-charcoal-500", label: "Cancelled" },
  done: { dot: "bg-emerald-400", text: "text-emerald-300", label: "Done" },
};


function elapsed(task) {
  const start = task.started_at || task.created_at;
  const end = task.completed_at || new Date().toISOString();
  const ms = new Date(end.endsWith("Z") ? end : end + "Z") - new Date(start.endsWith("Z") ? start : start + "Z");
  if (!Number.isFinite(ms) || ms < 0) return "";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

/** One task's row (task: "Readable task rows/cards showing task title,
 * assigned team, actual state, latest meaningful update, and elapsed
 * time") -- a row, not a card: no border-radius/shadow decoration, just a
 * left status-color bar and typographic hierarchy, so a list of many reads
 * as a real work queue rather than a grid of identical tiles. */
export default function TaskRow({ task, selected, onSelect }) {
  const style = STATUS_STYLE[task.status] || STATUS_STYLE.queued;
  // A root task with no team could still have been delegated (its
  // subtasks carry the team, not it) -- this flat list shape has no
  // subtask count to check (only the detail view's enriched response
  // does, where the equivalent label correctly says "Delegated to N
  // subtasks"), so this only ever asserts what it actually knows.
  const teamLabel = task.team ? TEAM_LABEL[task.team] || task.team : null;

  return (
    <button
      onClick={() => onSelect(task.id)}
      className={`flex w-full min-w-0 items-center gap-3 border-l-2 px-3 py-2.5 text-left transition-colors ${
        selected ? "border-emerald-400 bg-emerald-500/5" : "border-transparent hover:bg-charcoal-800/60"
      }`}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${style.dot}`} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] text-charcoal-200">{task.title}</p>
        <p className="mt-0.5 truncate text-[11px] text-charcoal-500">
          {[
            teamLabel && <span key="team" className="text-charcoal-400">{teamLabel}</span>,
            task.role && <span key="role">{task.role}</span>,
            task.error
              ? <span key="err" className="text-rose-400">{task.error.slice(0, 60)}</span>
              : task.result_summary && <span key="sum">{task.result_summary.slice(0, 60)}</span>,
          ]
            .filter(Boolean)
            .flatMap((seg, i) => (i === 0 ? [seg] : [<span key={`sep${i}`}> · </span>, seg]))}
        </p>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-0.5">
        <span className={`text-[11px] font-medium ${style.text}`}>{style.label}</span>
        <span className="font-mono text-[10.5px] text-charcoal-600">{elapsed(task)}</span>
      </div>
    </button>
  );
}
