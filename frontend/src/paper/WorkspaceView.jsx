// Workspace: your models as a team. Unlocked once four models are ready.
// Everything here is real: roles are the backend's team roles (app/teams.py),
// a job goes to the director, which splits it into steps for those roles, and
// the board below reads the same task records Agents shows.
import { useCallback, useEffect, useMemo, useState } from "react";
import { cancelWorkspaceTask, createWorkspaceTask, getWorkspaceTask, listTeams, listWorkspaceTasks, retryWorkspaceTask, setMaxHeavyWorkers, setTeamRoleModel } from "../api.js";
import Icon from "./icons.jsx";
import Guide, { GuideButton } from "./Guide.jsx";
import Reactor from "./Reactor.jsx";
import { useUi } from "./ui.jsx";

const LIVE = ["pending", "queued", "running", "working", "in_progress", "waiting"];
const IDEAS = [
  ["Research and write", "Research the pros and cons of three topics for my term paper and write a one-page comparison"],
  ["Build a prototype", "Plan, build and review a small web page that tracks my assignments by due date"],
  ["Study plan", "Make a two-week study plan for my next calculus test from my Canvas assignments, with practice problems"],
  ["Review my code", "Review the project open in Studio for bugs and suggest the three most important fixes"],
];
const TEAM_NOTES = {
  director: "Splits your job into steps and hands each to the right role.",
  engineering: "Plans, writes, debugs and reviews code.",
  design: "Interfaces, frontend code, wording and accessibility.",
  research: "Finds sources, investigates and writes it up.",
  learning: "Tutoring, practice, and checking answers.",
  business: "Plans, strategy and business writing.",
  desktop: "Plans work on your computer and in the browser.",
  memory: "Keeps what Nova knows tidy and consistent.",
  quality: "Tests, performance and acceptance checks.",
  everyday: "Nova's daily routines: briefs, reminders, checks.",
};

function statusOf(t) {
  if (LIVE.includes(t.status)) return ["work", "Working"];
  if (t.status === "done") return ["ok", "Done"];
  if (t.status === "cancelled") return ["q", "Stopped"];
  if (t.status === "interrupted") return ["q", "Didn't finish"];
  if (t.status === "error") return ["you", "Hit a problem"];
  return ["q", t.status];
}

function ago(ts) {
  const d = new Date(ts?.includes("T") ? ts : `${String(ts).replace(" ", "T")}Z`);
  const s = (Date.now() - d) / 1000;
  if (Number.isNaN(s)) return "";
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function Job({ task, open, onToggle, onChanged }) {
  const ui = useUi();
  const [detail, setDetail] = useState(null);
  const live = LIVE.includes(task.status);
  const [cls, label] = statusOf(task);

  useEffect(() => {
    if (!open && !live) return undefined;
    let on = true;
    const get = () => getWorkspaceTask(task.id).then((d) => on && setDetail(d)).catch(() => {});
    get();
    const t = live ? setInterval(get, 3000) : null;
    return () => { on = false; if (t) clearInterval(t); };
  }, [task.id, open, live]);

  const steps = detail?.subtasks || [];
  const doneSteps = steps.filter((s) => s.status === "done").length;
  const stop = () => cancelWorkspaceTask(task.id).then(() => { ui.toast("Stopped."); onChanged(); }).catch((e) => ui.toast(e.message, { error: true }));
  const retry = async () => {
    try { await retryWorkspaceTask(task.id, false); ui.toast("Trying again."); onChanged(); }
    catch (e) {
      if (/confirm/i.test(e.message) && await ui.confirm({ title: "Run it again?", body: e.message, confirm: "Run again" })) {
        await retryWorkspaceTask(task.id, true).catch((err) => ui.toast(err.message, { error: true }));
        onChanged();
      } else ui.toast(e.message, { error: true });
    }
  };
  const menu = (e) => ui.openMenu(e, [
    { label: open ? "Hide steps" : "Show steps", onSelect: onToggle },
    task.result_summary && { label: "Copy result", icon: "copy", onSelect: () => navigator.clipboard.writeText(task.result_summary).then(() => ui.toast("Copied.")) },
    { label: "Copy the job", icon: "copy", onSelect: () => navigator.clipboard.writeText(task.title) },
    "-",
    live ? { label: "Stop", icon: "stop", danger: true, onSelect: stop } : { label: "Run again", icon: "refresh", onSelect: retry },
  ], { title: task.title });

  return (
    <div className={`p-job${open ? " open" : ""}`} onContextMenu={menu}>
      <button className="p-jobhead" onClick={onToggle} aria-expanded={open}>
        <span className={`p-dotst ${cls}`} />
        <span className="t"><b>{task.title}</b><small>{ago(task.created_at)}{steps.length ? ` · ${doneSteps} of ${steps.length} steps` : ""}</small></span>
        <span className={`p-tag ${cls}`}>{label}</span>
      </button>
      {live && steps.length > 0 && <div className="p-bar"><i style={{ width: `${(doneSteps / steps.length) * 100}%` }} /></div>}
      {open && (
        <div className="p-jobbody">
          {steps.length === 0 && <div className="note">{live ? "The director is planning the steps…" : "No separate steps were recorded."}</div>}
          {steps.map((s) => {
            const [c, l] = statusOf(s);
            return (
              <div className="p-jstep" key={s.id}>
                <span className={`p-dotst ${c}`} />
                <span className="r">{(s.role || "step").replace(/_/g, " ")}</span>
                <span className="x">{s.title}{s.model ? <small>{s.model}</small> : null}</span>
                <span className={`s ${c}`}>{l}</span>
              </div>
            );
          })}
          {task.result_summary && <div className="p-result">{task.result_summary}</div>}
          {task.error && <p className="err">{task.error}</p>}
          <div className="p-acts">
            {live ? <button className="p-sm" onClick={stop}><Icon name="stop" />Stop</button>
              : <button className="p-sm" onClick={retry}><Icon name="refresh" />Run again</button>}
            {task.result_summary && <button className="p-sm" onClick={() => navigator.clipboard.writeText(task.result_summary).then(() => ui.toast("Copied."))}><Icon name="copy" />Copy result</button>}
          </div>
        </div>
      )}
    </div>
  );
}

export default function WorkspaceView({ palette, dark, onWatch, onModels }) {
  const ui = useUi();
  const [data, setData] = useState(null);
  const [team, setTeam] = useState("director");
  const [task, setTask] = useState("");
  const [busy, setBusy] = useState(false);
  const [jobs, setJobs] = useState(null);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState("");

  const loadTeam = useCallback(() => listTeams().then(setData).catch((e) => setError(e.message)), []);
  const loadJobs = useCallback(() => listWorkspaceTasks().then((rows) => setJobs((Array.isArray(rows) ? rows : [])
    .filter((t) => t.parent_id == null && t.team !== "everyday"))).catch(() => setJobs([])), []);
  useEffect(() => {
    loadTeam();
    loadJobs();
    const t = setInterval(loadJobs, 5000);
    return () => clearInterval(t);
  }, [loadTeam, loadJobs]);

  const options = (data?.model_options || []).filter((o) => o.enabled);
  const teams = useMemo(() => [["director", "Director"], ...Object.entries(data?.teams || {})], [data]);
  const roles = (data?.roles || []).filter((r) => (team === "director" ? !r.team : r.team === team));
  const unready = (data?.roles || []).filter((r) => !r.available);
  const changed = (data?.roles || []).filter((r) => r.model_id !== r.default_model_id);
  const director = (data?.roles || []).find((r) => r.key === "director");
  const liveJobs = (jobs || []).filter((j) => LIVE.includes(j.status));

  async function assign(role, modelId) {
    setError("");
    setData((d) => ({ ...d, roles: d.roles.map((r) => (r.key === role.key ? { ...r, model_id: modelId, model_name: options.find((o) => o.id === modelId)?.name || modelId } : r)) }));
    try { await setTeamRoleModel(role.key, modelId); await loadTeam(); } catch (e) { setError(e.message); loadTeam(); }
  }
  async function resetAll() {
    const ok = await ui.confirm({ title: "Use the recommended models?", body: `${changed.length} role${changed.length === 1 ? "" : "s"} will go back to Nova's recommended model.`, confirm: "Reset" });
    if (!ok) return;
    for (const r of changed) await setTeamRoleModel(r.key, r.default_model_id).catch(() => {});
    await loadTeam();
    ui.toast("Every role is back on its recommended model.");
  }

  async function start(text = task) {
    const body = text.trim();
    if (!body) return;
    setBusy(true);
    setError("");
    try {
      const root = await createWorkspaceTask(body);
      setTask("");
      ui.toast("The team has it. Progress shows below.");
      await loadJobs();
      if (root?.id) setOpen(root.id);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const firstTime = jobs && jobs.length === 0;
  return (
    <section className="p-page" aria-label="Workspace">
      <div className="p-ph">
        <Reactor palette={palette} dark={dark} state={liveJobs.length ? "thinking" : "idle"} />
        <div><h1>Workspace</h1><div className="sub">Your models as one team. The director plans, the others research, build and check each other's work.</div></div>
        <GuideButton id="workspace" />
        <button className="p-sm" onClick={onWatch}><Icon name="nodes" />Open Agents</button>
      </div>
      <div className="scroll p-pg">
        <Guide id="workspace" />
        {error && <p className="err">{error}</p>}
        <div className="p-wsask">
          <textarea className="p-fieldarea" rows={3} value={task} onChange={(e) => setTask(e.target.value)} aria-label="A job for the team"
            placeholder="What should the team do? Describe the whole job; the director breaks it into steps."
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); start(); } }} />
          <div className="row">
            <div className="p-chips">{IDEAS.map(([name, text]) => <button key={name} className="p-chip" onClick={() => setTask(text)} title={text}>{name}</button>)}</div>
            <span className="note">Ctrl+Enter</span>
            <button className="p-btn" onClick={() => start()} disabled={busy || !task.trim()}>{busy ? "Starting…" : "Give it to the team"}</button>
          </div>
        </div>

        <div className="p-two">
          <div className="p-stack">
            {firstTime && (
              <div className="p-card">
                <div className="head"><i>Getting started</i><span /></div>
                <div className="p-check-list">
                  <div className="done"><Icon name="check" size={15} />{options.length} models are ready</div>
                  <div className={director?.available ? "done" : ""}><Icon name={director?.available ? "check" : "info"} size={15} />
                    The director uses {director?.model_name || "…"}{director && !director.available ? `: ${director.availability_reason}` : ""}</div>
                  <div><Icon name="arrow" size={15} />Give the team its first job above</div>
                </div>
              </div>
            )}
            <div className="p-card">
              <div className="head"><i>Jobs</i><span>{liveJobs.length ? `${liveJobs.length} working` : jobs ? `${jobs.length}` : ""}</span></div>
              {jobs === null && <div className="note">Loading…</div>}
              {jobs?.length === 0 && <div className="note">Nothing yet. Jobs you give the team appear here with every step.</div>}
              {(jobs || []).slice(0, 30).map((j) => (
                <Job key={j.id} task={j} open={open === j.id} onToggle={() => setOpen(open === j.id ? null : j.id)} onChanged={loadJobs} />
              ))}
            </div>
          </div>

          <div className="p-stack">
            <div className="p-card">
              <div className="head"><i>Your team</i>
                {changed.length > 0 ? <button className="p-link" onClick={resetAll}>Use recommended models</button> : <span>recommended models</span>}</div>
              <div className="p-teamtabs" role="tablist" aria-label="Teams">
                {teams.map(([key, name]) => (
                  <button key={key} role="tab" aria-selected={team === key} onClick={() => setTeam(key)}>{name}</button>
                ))}
              </div>
              <div className="note">{TEAM_NOTES[team] || ""}</div>
              {!data && <div className="note">Loading the team…</div>}
              <div className="p-roles">
                {roles.map((role) => (
                  <div className={`p-role${role.available ? "" : " warn"}`} key={role.key}>
                    <div className="top">
                      <b>{role.label}</b>
                      {role.writes_files && <span className="p-tag work" title="Can change files, following your Autonomy setting">writes files</span>}
                    </div>
                    <small>{role.tool_scope}</small>
                    <select className="p-sm" value={role.model_id || ""} onChange={(e) => assign(role, e.target.value)} aria-label={`Model for ${role.label}`}>
                      {!options.some((o) => o.id === role.model_id) && <option value={role.model_id}>{role.model_name || role.model_id}</option>}
                      {options.map((o) => <option key={o.id} value={o.id}>{o.name}{o.id === role.default_model_id ? " (recommended)" : ""}</option>)}
                    </select>
                    {!role.available && <div className="err">{role.availability_reason}</div>}
                  </div>
                ))}
              </div>
            </div>
            <div className="p-card"><div className="head"><i>How hard it works</i><span /></div>
              <div className="p-row" style={{ borderTop: 0 }}>
                <span>Big models at once<small>More finishes sooner but uses more of your computer</small></span>
                <div className="p-seg" role="group" aria-label="Big models at once">
                  {[1, 2, 3, 4].map((n) => <button key={n} aria-pressed={(data?.max_heavy_workers ?? 1) === n} onClick={() => setMaxHeavyWorkers(n).then(loadTeam)}>{n}</button>)}
                </div>
              </div>
            </div>
            {unready.length > 0 && (
              <div className="p-card"><div className="head"><i>Needs attention</i><span>{unready.length}</span></div>
                {unready.slice(0, 6).map((r) => <div className="note" key={r.key}>{r.label}: {r.availability_reason}</div>)}
                <div className="p-acts"><button className="p-sm" onClick={onModels}>Manage models</button></div>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
