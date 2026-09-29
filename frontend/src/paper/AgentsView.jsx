import { useEffect, useState } from "react";
import { cancelWorkspaceTask, getWorkspaceTask, listWorkspaceTasks, retryWorkspaceTask } from "../api.js";
import Guide, { GuideButton } from "./Guide.jsx";
import Reactor from "./Reactor.jsx";
import { operatorResume, operatorStatus, operatorStop, taskLive, taskUnfinished } from "./paperApi.js";

const GROUPS = [
  ["Running", (t) => ["working", "running", "in_progress"].includes(t.status)],
  ["Waiting", (t) => ["queued", "pending", "blocked", "waiting"].includes(t.status)],
  ["Finished", (t) => ["done", "completed"].includes(t.status)],
  ["Stopped or failed", (t) => ["error", "failed", "cancelled"].includes(t.status)],
];

function color(status) {
  if (["working", "running", "in_progress"].includes(status)) return "var(--clay)";
  if (["done", "completed"].includes(status)) return "var(--ok)";
  if (["error", "failed", "cancelled"].includes(status)) return "var(--danger)";
  return "var(--ln)";
}

function ago(ts) {
  if (!ts) return "";
  const d = new Date(String(ts).includes("T") ? ts : `${String(ts).replace(" ", "T")}Z`);
  const mins = Math.round((Date.now() - d) / 60000);
  if (Number.isNaN(mins)) return "";
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 1440) return `${Math.round(mins / 60)} h ago`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export default function AgentsView({ palette, dark }) {
  const [tasks, setTasks] = useState(null);
  const [op, setOp] = useState({ stopped: false, tasks: [] });
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    try {
      const [list, status] = await Promise.all([listWorkspaceTasks(), operatorStatus().catch(() => null)]);
      setTasks((list || []).filter((t) => !t.parent_id));
      if (status) setOp(status);
    } catch (e) {
      setError(e.message);
      setTasks([]);
    }
  }
  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t); }, []);
  useEffect(() => {
    if (selected == null) { setDetail(null); return undefined; }
    let live = true;
    const get = () => getWorkspaceTask(selected).then((d) => live && setDetail(d)).catch(() => {});
    get();
    const t = setInterval(get, 4000);
    return () => { live = false; clearInterval(t); };
  }, [selected]);

  const task = detail?.task || detail;
  const subtasks = detail?.subtasks || detail?.children || [];
  const browserRuns = (op.tasks || []).filter(taskLive);
  const unfinished = (op.tasks || []).filter(taskUnfinished).slice(0, 5);

  return (
    <section className="p-page" aria-label="Agents">
      <div className="p-ph">
        <Reactor palette={palette} dark={dark} />
        <div><h1>Agents</h1><div className="sub">What Nova is doing, step by step</div></div>
        <GuideButton id="agents" />
        <span className="sp" />
        {op.stopped
          ? <button className="p-sm dark" onClick={() => operatorResume().then(load)}>Resume Nova</button>
          : <button className="p-sm" onClick={() => operatorStop().then(load)}>Stop everything</button>}
      </div>
      <div className="scroll p-pg">
        <Guide id="agents" />
        {error && <p className="err">{error}</p>}
        {op.stopped && <p className="note">Nova is stopped: {op.record?.reason || "stopped by you"}. Nothing acts on your behalf until you resume.</p>}
        <div className="p-two">
          <div className="p-stack">
            {tasks === null && <div className="muted">Loading…</div>}
            {browserRuns.length > 0 && (
              <div style={{ display: "grid", gap: 8 }}>
                <div className="muted">In the browser</div>
                {browserRuns.map((r) => (
                  <div className="p-run" key={r.id}><span className="dot" style={{ background: "var(--clay)" }} /><b>{r.workflow || "Browser task"}</b><span className="r">{r.steps?.length || 0} steps</span><span className="meta">{r.url}</span></div>
                ))}
              </div>
            )}
            {unfinished.length > 0 && (
              <div style={{ display: "grid", gap: 8 }}>
                <div className="muted">Didn't finish</div>
                {unfinished.map((r) => (
                  <div className="p-run" key={r.id}><span className="dot" style={{ background: "var(--danger)" }} /><b>{r.workflow || "Browser task"}</b><span className="r">{ago(new Date(r.created_at * 1000).toISOString())}</span><span className="meta">{r.summary || "Stopped without a result"} · {r.url}</span></div>
                ))}
              </div>
            )}
            {tasks && tasks.length === 0 && browserRuns.length === 0 && (
              <div className="p-empty"><div className="muted">Nothing running. Tasks you give Nova appear here with every step.</div></div>
            )}
            {tasks && GROUPS.map(([name, test]) => {
              const rows = tasks.filter(test);
              if (!rows.length) return null;
              return (
                <div key={name} style={{ display: "grid", gap: 8 }}>
                  <div className="muted">{name}</div>
                  {rows.slice(0, name === "Finished" ? 12 : 50).map((t) => (
                    <button className="p-run" key={t.id} aria-pressed={selected === t.id} onClick={() => setSelected(t.id)}>
                      <span className="dot" style={{ background: color(t.status) }} />
                      <b>{t.title || t.description?.slice(0, 60) || `Task ${t.id}`}</b>
                      <span className="r">{ago(t.updated_at || t.created_at)}</span>
                      <span className="meta">{[t.team, t.model || t.provider].filter(Boolean).join(" · ") || t.status}</span>
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
          <div className="p-card">
            {!task ? <div className="note">Select a task to see what it did.</div> : (
              <>
                <div className="head"><i>{task.title || `Task ${task.id}`}</i><span>{task.status}</span></div>
                {task.description && <div style={{ fontSize: 14, color: "var(--tx2)" }}>{task.description}</div>}
                {subtasks.length > 0 && (
                  <div style={{ display: "grid", gap: 6 }}>
                    {subtasks.map((s) => (
                      <div className="p-step" key={s.id}><span className="t">{s.role || "step"}</span><span>{s.title || s.description}</span><span className={`s${["done", "completed"].includes(s.status) ? " ok" : ["working", "running"].includes(s.status) ? " now" : ""}`}>{s.status}</span></div>
                    ))}
                  </div>
                )}
                {task.result_summary && <div className="p-result">{task.result_summary}</div>}
                {task.error && <div className="err">{task.error}</div>}
                <div className="p-kv"><span>Model</span><span>{task.model || task.provider || "automatic"}</span><span>Team</span><span>{task.team || "none"}</span></div>
                <div className="p-acts">
                  {["working", "running", "queued", "pending"].includes(task.status) && <button className="p-sm" onClick={() => cancelWorkspaceTask(task.id).then(load)}>Stop</button>}
                  {["error", "failed", "cancelled"].includes(task.status) && <button className="p-sm" onClick={() => retryWorkspaceTask(task.id).then(load).catch((e) => setError(e.message))}>Try again</button>}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
