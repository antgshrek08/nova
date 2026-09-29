import { useEffect, useState } from "react";
import { connectAgentSocket } from "../lib/agentSocket.js";

const STATUS_META = {
  queued: { dot: "bg-amber-400", card: "border-amber-500/30", label: "Queued" },
  working: { dot: "bg-indigo-400", card: "border-indigo-500/40", label: "Working" },
  done: { dot: "bg-emerald-500", card: "border-slate-800", label: "Done" },
  error: { dot: "bg-red-500", card: "border-red-500/30", label: "Error" },
};

function relativeTime(seconds) {
  if (seconds < 1) return "just now";
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m ${s}s`;
}

function AgentCard({ job, now }) {
  const [expanded, setExpanded] = useState(false);
  const meta = STATUS_META[job.status] || STATUS_META.queued;
  const elapsed = now - job.created_at;
  const isActive = job.status === "queued" || job.status === "working";
  const preview = job.output.length > 220 ? "…" + job.output.slice(-220) : job.output;

  return (
    <div
      className={`rounded-xl border bg-slate-900/60 p-3 shadow-lg transition-colors ${meta.card} ${
        job.status === "working" ? "shadow-indigo-900/30" : ""
      }`}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="relative flex h-2.5 w-2.5 shrink-0">
            {job.status === "working" && (
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-75" />
            )}
            <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${meta.dot}`} />
          </span>
          <span className="truncate text-sm font-medium text-slate-100">
            {job.label || job.provider || "Routing…"}
          </span>
        </div>
        <span className="shrink-0 text-[11px] text-slate-500">{relativeTime(elapsed)}</span>
      </div>

      <div className="mb-2 flex flex-wrap gap-1.5">
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
            isActive ? "bg-indigo-950 text-indigo-300" : "bg-slate-800 text-slate-400"
          }`}
        >
          {meta.label}
        </span>
        {job.category && (
          <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] font-medium text-slate-400">
            {job.category}
          </span>
        )}
        {job.model && (
          <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] font-medium text-slate-400">
            {job.model}
          </span>
        )}
      </div>

      {job.status === "error" ? (
        <p className="rounded-lg bg-red-950/40 p-2 text-xs text-red-300">{job.error}</p>
      ) : (
        <pre
          className={`whitespace-pre-wrap break-words rounded-lg bg-black/30 p-2 font-mono text-xs text-slate-300 ${
            expanded ? "max-h-80 overflow-y-auto" : "max-h-24 overflow-hidden"
          }`}
        >
          {(expanded ? job.output : preview) || "…"}
        </pre>
      )}

      {job.output.length > 220 && (
        <button
          onClick={() => setExpanded((e) => !e)}
          className="mt-1.5 text-[11px] text-slate-500 hover:text-slate-300"
        >
          {expanded ? "Collapse" : "Expand raw output"}
        </button>
      )}
    </div>
  );
}

export default function AgentWorkspace() {
  const [jobs, setJobs] = useState({});
  const [order, setOrder] = useState([]);
  const [now, setNow] = useState(Date.now() / 1000);

  useEffect(() => connectAgentSocket((msg) => {
    if (msg.type === "snapshot") {
      const map = {};
      const ord = [];
      for (const job of msg.jobs) {
        map[job.id] = job;
        ord.push(job.id);
      }
      setJobs(map);
      setOrder(ord);
    } else if (msg.type === "job") {
      setJobs((prev) => ({ ...prev, [msg.job.id]: msg.job }));
      setOrder((prev) => (prev.includes(msg.job.id) ? prev : [...prev, msg.job.id]));
    }
  }), []);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);

  const allJobs = order.map((id) => jobs[id]).filter(Boolean).reverse();
  const active = allJobs.filter((j) => j.status === "queued" || j.status === "working");
  const recent = allJobs.filter((j) => j.status === "done" || j.status === "error");

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="mb-4 flex items-center gap-2">
        <span className="relative flex h-2.5 w-2.5">
          {active.length > 0 && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-75" />
          )}
          <span
            className={`relative inline-flex h-2.5 w-2.5 rounded-full ${
              active.length > 0 ? "bg-indigo-500" : "bg-slate-700"
            }`}
          />
        </span>
        <h2 className="text-sm font-semibold text-slate-200">
          {active.length} active · {recent.length} recent
        </h2>
      </div>

      {active.length > 0 && (
        <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {active.map((job) => (
            <AgentCard key={job.id} job={job} now={now} />
          ))}
        </div>
      )}

      {recent.length > 0 && (
        <>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Recent</h3>
          <div className="grid grid-cols-1 gap-3 opacity-80 sm:grid-cols-2 xl:grid-cols-3">
            {recent.map((job) => (
              <AgentCard key={job.id} job={job} now={now} />
            ))}
          </div>
        </>
      )}

      {allJobs.length === 0 && (
        <p className="mt-10 text-center text-sm text-slate-500">
          No agent activity yet — send a message in any tab to see it appear here live.
        </p>
      )}
    </div>
  );
}
