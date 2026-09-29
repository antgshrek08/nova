import { useState } from "react";
import { useFileChangeSets, revertChange, clearFileChangeSets } from "../lib/codeEditorStore.js";

const KIND_LABEL = { added: "Added", modified: "Modified", deleted: "Deleted" };
const KIND_TONE = {
  added: "text-emerald-400 bg-emerald-900/30",
  modified: "text-sky-400 bg-sky-900/30",
  deleted: "text-rose-400 bg-rose-900/30",
};

/** Change review (task: "Provide a change-review view for proposed edits").
 * Honesty note, matching code_files.py's own: by the time a change appears
 * here, claude -p / codex exec already wrote it to disk -- this reviews
 * what actually happened, it does not gate whether it happens. There is
 * deliberately no "Apply" button (nothing is pending) -- only "Revert",
 * which really does write the captured prior content back (task:
 * "Apply/reject actions only where backed by a real implementation"). */
export default function ChangeReviewPanel({ onOpenFile }) {
  const changeSets = useFileChangeSets();

  if (changeSets.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-8 text-center text-sm text-charcoal-500">
        No changes yet. When N.O.V.A. edits files for you, what changed shows up here.
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto p-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[11px] uppercase tracking-wide text-charcoal-500">Recent changes</p>
        <button onClick={clearFileChangeSets} className="text-[11px] text-charcoal-500 hover:text-charcoal-300">
          Clear
        </button>
      </div>
      <div className="space-y-3">
        {changeSets.map((set) => (
          <div key={set.id} className="rounded-lg border border-charcoal-700 bg-charcoal-850">
            <p className="border-b border-charcoal-700 px-3 py-1.5 text-[11px] text-charcoal-500">
              {new Date(set.timestamp).toLocaleTimeString()} — {set.changes.length} file{set.changes.length === 1 ? "" : "s"}
            </p>
            <div className="divide-y divide-charcoal-800">
              {set.changes.map((change) => (
                <FileChange key={change.path} change={change} onOpenFile={onOpenFile} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FileChange({ change, onOpenFile }) {
  const [expanded, setExpanded] = useState(false);
  const [reverting, setReverting] = useState(false);
  const [revertError, setRevertError] = useState("");
  const canRevert = change.kind !== "deleted" && change.before !== null && change.before !== undefined;

  async function handleRevert() {
    if (!window.confirm(`Revert ${change.path} to its content before this change? This overwrites the file now.`)) return;
    setReverting(true);
    setRevertError("");
    try {
      await revertChange(change.path, change.before);
    } catch (err) {
      setRevertError(err.message || "Couldn't revert this file.");
    } finally {
      setReverting(false);
    }
  }

  return (
    <div className="p-2.5">
      <div className="flex min-w-0 items-center justify-between gap-2">
        <button
          onClick={() => onOpenFile?.(change.path)}
          className="min-w-0 flex-1 truncate text-left font-mono text-xs text-charcoal-200 hover:text-emerald-300"
          title={change.path}
        >
          {change.path}
        </button>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${KIND_TONE[change.kind]}`}>
          {KIND_LABEL[change.kind]}
        </span>
      </div>
      <div className="mt-1.5 flex items-center gap-3 text-[11px]">
        {change.diff && (
          <button onClick={() => setExpanded((v) => !v)} className="text-charcoal-500 hover:text-charcoal-300">
            {expanded ? "Hide diff" : "Show diff"}
          </button>
        )}
        {canRevert && (
          <button onClick={handleRevert} disabled={reverting} className="text-charcoal-500 hover:text-amber-400 disabled:opacity-50">
            {reverting ? "Reverting…" : "Revert"}
          </button>
        )}
      </div>
      {revertError && <p className="mt-1 text-[11px] text-rose-400">{revertError}</p>}
      {expanded && change.diff && <DiffView diff={change.diff} />}
    </div>
  );
}

/** Readable wrapped diff (task: "Readable wrapped diffs") -- a real unified
 * diff computed server-side (Python's own difflib against genuine before/
 * after content), rendered here with per-line +/- coloring and word-wrap
 * instead of a horizontally-scrolling `<pre>` (global no-horizontal-
 * scrollbar rule applies to diffs too). */
function DiffView({ diff }) {
  const lines = diff.split("\n");
  return (
    <pre className="mt-2 max-h-64 overflow-y-auto overflow-x-hidden rounded-md bg-charcoal-950 p-2 font-mono text-[11px] leading-5">
      {lines.map((line, i) => {
        let tone = "text-charcoal-400";
        if (line.startsWith("+") && !line.startsWith("+++")) tone = "text-emerald-400";
        else if (line.startsWith("-") && !line.startsWith("---")) tone = "text-rose-400";
        else if (line.startsWith("@@")) tone = "text-sky-400";
        return (
          <div key={i} className={`whitespace-pre-wrap break-all ${tone}`}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}
