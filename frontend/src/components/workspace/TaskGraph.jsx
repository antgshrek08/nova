import { useEffect, useState } from "react";
import { BACKEND_URL } from "../../api.js";

/** The dependency DAG for one workspace task.
 *
 * The constellation next door shows live team structure — which role is busy.
 * That is a different question from what actually blocks what, which is the
 * only view that answers "why hasn't this started yet."
 *
 * Laid out in dependency layers rather than with a force simulation: a plan is
 * a DAG with a direction, and reading order left-to-right carries that better
 * than a physics blob. Cycles cannot occur (the director builds a DAG) but a
 * malformed one would simply stop advancing, so the layering loop is bounded.
 */
const STATUS_STYLE = {
  done: "border-emerald-500/50 bg-emerald-500/10 text-emerald-200",
  running: "border-emerald-400 bg-emerald-400/10 text-emerald-100",
  queued: "border-charcoal-600 bg-charcoal-800/60 text-charcoal-300",
  blocked: "border-amber-500/40 bg-amber-500/10 text-amber-200",
  error: "border-rose-500/50 bg-rose-500/10 text-rose-200",
  partial: "border-amber-500/40 bg-amber-500/10 text-amber-200",
  cancelled: "border-charcoal-700 bg-charcoal-900 text-charcoal-500",
  interrupted: "border-charcoal-700 bg-charcoal-900 text-charcoal-500",
};

function layer(nodes, edges) {
  const incoming = new Map(nodes.map((n) => [n.id, []]));
  for (const edge of edges) {
    if (incoming.has(edge.to)) incoming.get(edge.to).push(edge.from);
  }
  const depth = new Map();
  let remaining = nodes.map((n) => n.id);
  for (let pass = 0; pass < nodes.length + 1 && remaining.length; pass++) {
    const ready = remaining.filter((id) =>
      incoming.get(id).every((dep) => depth.has(dep))
    );
    if (ready.length === 0) break;       // malformed graph: stop rather than loop
    for (const id of ready) {
      const deps = incoming.get(id);
      depth.set(id, deps.length ? Math.max(...deps.map((d) => depth.get(d))) + 1 : 0);
    }
    remaining = remaining.filter((id) => !depth.has(id));
  }
  for (const id of remaining) depth.set(id, 0);   // unreachable: show it anyway

  const columns = [];
  for (const node of nodes) {
    const index = depth.get(node.id) ?? 0;
    (columns[index] ||= []).push(node);
  }
  return columns.filter(Boolean);
}

export default function TaskGraph({ taskId }) {
  const [graph, setGraph] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!taskId) return;
    let disposed = false;
    const load = () =>
      fetch(`${BACKEND_URL}/workspace/tasks/${taskId}/graph`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`Failed (${r.status})`))))
        .then((data) => !disposed && (setGraph(data), setError("")))
        .catch((caught) => !disposed && setError(caught.message));
    load();
    // Cheap poll: a running plan changes status every few seconds and this is
    // one small query against a local SQLite file.
    const timer = setInterval(load, 4000);
    return () => { disposed = true; clearInterval(timer); };
  }, [taskId]);

  if (error) return <p role="alert" className="p-3 text-xs text-rose-300">{error}</p>;
  if (!graph) return <p className="p-3 text-xs text-charcoal-500">Loading plan…</p>;

  const subtasks = graph.nodes.filter((n) => !n.is_root);
  if (subtasks.length === 0) {
    return (
      <p className="p-3 text-xs leading-relaxed text-charcoal-500">
        This task ran directly — no subtasks were created, so there is no plan to show.
      </p>
    );
  }

  const columns = layer(subtasks, graph.edges);
  const blockedBy = new Map(subtasks.map((n) => [n.id, []]));
  for (const edge of graph.edges) {
    if (blockedBy.has(edge.to)) blockedBy.get(edge.to).push(edge.from);
  }
  const titleOf = new Map(graph.nodes.map((n) => [n.id, n.title]));

  return (
    <div className="h-full overflow-auto p-3">
      <div className="flex items-start gap-4">
        {columns.map((column, index) => (
          <div key={index} className="flex min-w-[190px] flex-col gap-2">
            <p className="text-[10px] uppercase tracking-wide text-charcoal-600">
              {index === 0 ? "Starts immediately" : `After step ${index}`}
            </p>
            {column.map((node) => (
              <div
                key={node.id}
                className={`rounded-lg border p-2 ${STATUS_STYLE[node.status] || STATUS_STYLE.queued}`}
              >
                <p className="text-[11px] font-medium leading-snug">{node.title}</p>
                <p className="mt-1 text-[10px] opacity-70">
                  {node.role || node.team || "task"} · {node.status}
                </p>
                {blockedBy.get(node.id)?.length > 0 && (
                  <p className="mt-1 truncate text-[10px] opacity-60"
                     title={blockedBy.get(node.id).map((id) => titleOf.get(id)).join(", ")}>
                    waits on: {blockedBy.get(node.id).map((id) => titleOf.get(id)).join(", ")}
                  </p>
                )}
                {node.status === "error" && node.error && (
                  <p className="mt-1 text-[10px] opacity-80">{String(node.error).slice(0, 120)}</p>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
