// Agents: jobs Nova does on its own. What's working now, the agents you set
// up (and when they run), what didn't finish (resume it), and -- only if you
// want them -- what finished. Backend: app/crew.py. Updates every few seconds.
import { useCallback, useEffect, useState } from "react";
import { listModels } from "../api.js";
import Guide, { GuideButton } from "./Guide.jsx";
import Icon from "./icons.jsx";
import Reactor from "./Reactor.jsx";
import { crewCreate, crewDelete, crewDismiss, crewOverview, crewResume, crewStart, crewStop, crewUpdate, operatorResume, operatorStatus, operatorStop } from "./paperApi.js";
import { agoText, recall, remember, requireLive, useSession } from "./remote.js";
import { Seg, Switch } from "./SettingsSections.jsx";
import { Overlay, useUi } from "./ui.jsx";

const REFRESH_MS = 3000;
const SHOW_FINISHED = "nova.agents.showFinished";
const STATE = {
  working: ["Working", "var(--clay)"],
  scheduled: ["Scheduled", "var(--ok)"],
  ready: ["Ready", "var(--tx3)"],
  paused: ["Paused", "var(--ln)"],
};
const WHEN = [["none", "When I start it"], ["once", "Once"], ["daily", "Daily"], ["weekdays", "Weekdays"], ["weekly", "Weekly"], ["hourly", "Every few hours"]];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function since(ts) {
  if (!ts) return "";
  return agoText(ts * 1000);
}

function nextText(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const today = new Date();
  const tomorrow = new Date(Date.now() + 86400000);
  const t = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }).toLowerCase();
  if (d.toDateString() === today.toDateString()) return `next today ${t}`;
  if (d.toDateString() === tomorrow.toDateString()) return `next tomorrow ${t}`;
  return `next ${d.toLocaleDateString([], { weekday: "short" })} ${t}`;
}

function stored(key) {
  try { return localStorage.getItem(key) === "1"; } catch { return false; }
}

export default function AgentsView({ palette, dark, onOpenConversation }) {
  const ui = useUi();
  const session = useSession();
  const [showFinished, setShowFinished] = useState(() => stored(SHOW_FINISHED));
  const [data, setData] = useState(() => recall("agents")?.data || null);
  const [offlineAt, setOfflineAt] = useState(null);
  const [op, setOp] = useState({ stopped: false });
  const [editing, setEditing] = useState(null); // {} for new, agent for edit
  const [open, setOpen] = useState(null); // agent id
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    try {
      const [view, status] = await Promise.all([crewOverview(showFinished), operatorStatus().catch(() => null)]);
      setData(view);
      setOfflineAt(null);
      remember("agents", view);
      if (status) setOp(status);
    } catch {
      const snap = recall("agents");
      if (snap) { setData((d) => d || snap.data); setOfflineAt(snap.at); }
      else setData((d) => d || { agents: [], working: [], unfinished: [], finished: [], finished_count: 0 });
    }
  }, [showFinished]);

  useEffect(() => {
    load();
    const tick = () => { if (!document.hidden) load(); };
    const t = setInterval(tick, REFRESH_MS);
    document.addEventListener("visibilitychange", tick);
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", tick); };
  }, [load]);

  const act = (label, fn, ok) => requireLive(async () => {
    setBusy(label);
    try { await fn(); if (ok) ui.toast(ok); await load(); } catch (e) { ui.toast(e.message, { error: true }); } finally { setBusy(""); }
  }, "Starting or changing agents");

  const toggleFinished = () => {
    const next = !showFinished;
    setShowFinished(next);
    try { localStorage.setItem(SHOW_FINISHED, next ? "1" : "0"); } catch { /* ignore */ }
  };

  const agents = data?.agents || [];
  const working = data?.working || [];
  const unfinished = data?.unfinished || [];
  const finished = data?.finished || [];
  const openAgent = agents.find((a) => a.id === open);
  const empty = data && !agents.length && !working.length && !unfinished.length;

  return (
    <section className="p-page" aria-label="Agents">
      <div className="p-ph">
        <Reactor palette={palette} dark={dark} />
        <div><h1>Agents</h1><div className="sub">Jobs Nova does on its own{working.length ? ` · ${working.length} working now` : ""}</div></div>
        <GuideButton id="agents" />
        <span className="sp" />
        <button className="p-sm dark" data-tour="new-agent" onClick={() => requireLive(() => setEditing({}), "Setting up an agent")}><Icon name="plus" size={14} />New agent</button>
        {working.length > 0 && !op.stopped && <button className="p-sm" onClick={() => act("stopall", operatorStop, "Stopped everything.")}>Stop all</button>}
        {op.stopped && <button className="p-sm" onClick={() => act("resumeall", operatorResume, "Nova can act again.")}>Let Nova act again</button>}
      </div>
      <div className="scroll p-pg">
        <Guide id="agents" />
        {offlineAt && <p className="note p-offline"><Icon name="info" size={14} /> Your computer's Nova isn't reachable. This is from {agoText(offlineAt)}.</p>}
        {op.stopped && <p className="note">Nova is stopped: {op.record?.reason || "stopped by you"}. Nothing runs until you let it act again.</p>}
        {data === null && <div className="muted">Loading…</div>}

        {empty && (
          <div className="p-agents-empty">
            <b>No agents yet</b>
            <p>An agent is a job Nova does by itself, once or on a schedule. Try one of these, or ask Nova in Chat.</p>
            <div className="p-chips">
              {[["Morning brief", "Every weekday at 7:30, tell me what's due this week and what's on my calendar today.", { kind: "weekdays", time: "07:30" }],
                ["Weekly review", "Every Sunday evening, sum up what I finished this week and what's coming next week.", { kind: "weekly", day: 6, time: "18:00" }],
                ["Tech digest", "Once a day, find the three most useful AI and tech stories and write two lines on each.", { kind: "daily", time: "12:00" }]].map(([name, task, schedule]) => (
                <button key={name} className="p-chip" onClick={() => requireLive(() => setEditing({ name, task, schedule, model: "auto" }), "Setting up an agent")}>{name}</button>
              ))}
            </div>
          </div>
        )}

        {working.length > 0 && (
          <div className="p-agsec">
            <h3>Working now</h3>
            {working.map((r) => (
              <div className="p-agrow live" key={r.id}>
                <span className="dot pulse" />
                <div className="t"><b>{r.agent_name}</b><small>{r.kind === "browser" ? `In the browser · ${r.summary}` : r.kind === "team" ? "Team task" : (r.model_label || r.model || "Picking a model…")} · started {since(r.started_at)}</small></div>
                {r.kind !== "browser" && <button className="p-sm" disabled={busy === r.id} onClick={() => act(r.id, () => crewStop(r.id), "Stopped.")}>Stop</button>}
              </div>
            ))}
          </div>
        )}

        {unfinished.length > 0 && (
          <div className="p-agsec">
            <h3>Didn't finish</h3>
            {unfinished.map((r) => (
              <div className="p-agrow" key={r.id}>
                <span className="dot" style={{ background: "var(--clay)", opacity: 0.55 }} />
                <div className="t"><b>{r.agent_name}</b><small>{r.error || "Stopped part-way"} · {since(r.finished_at || r.started_at)}</small></div>
                <button className="p-sm dark" disabled={busy === r.id} onClick={() => act(r.id, () => crewResume(r.id), "Picking up where it stopped.")}>Resume</button>
                <button className="p-ib plain" aria-label="Dismiss" title="Dismiss" onClick={() => act(`x${r.id}`, () => crewDismiss(r.id))}><Icon name="x" size={14} /></button>
              </div>
            ))}
          </div>
        )}

        {agents.length > 0 && (
          <div className="p-agsec">
            <h3>Your agents</h3>
            {agents.map((a) => {
              const [label, color] = STATE[a.state] || STATE.ready;
              return (
                <button className="p-agrow btn" key={a.id} onClick={() => setOpen(a.id)} aria-label={`${a.name}, ${label}`}>
                  <span className={`dot${a.state === "working" ? " pulse" : ""}`} style={{ background: color }} />
                  <div className="t"><b>{a.name}</b><small>{a.about}</small></div>
                  <div className="when"><span>{a.when}</span><small>{a.state === "scheduled" ? nextText(a.next_run_at) : label}</small></div>
                  <Icon name="chev" size={14} />
                </button>
              );
            })}
          </div>
        )}

        {data && (data.finished_count > 0 || showFinished) && (
          <div className="p-agsec">
            <div className="p-aghead"><h3>Finished</h3><span className="sp" /><span className="note">Show</span><Switch on={showFinished} onChange={toggleFinished} label="Show finished runs" /></div>
            {showFinished && finished.map((r) => (
              <button className="p-agrow btn" key={r.id} onClick={() => r.conversation_id && onOpenConversation?.(r.conversation_id)}>
                <span className="dot" style={{ background: "var(--ok)" }} />
                <div className="t"><b>{r.agent_name}</b><small>{r.summary || "Done"} · {since(r.finished_at || r.started_at)}</small></div>
              </button>
            ))}
            {!showFinished && <p className="note">{data.finished_count} finished {data.finished_count === 1 ? "run" : "runs"} hidden.</p>}
          </div>
        )}
      </div>

      {openAgent && (
        <AgentSheet agent={openAgent} runs={[...working, ...unfinished, ...finished].filter((r) => r.agent_id === openAgent.id)} busy={busy}
          onClose={() => setOpen(null)}
          onStart={() => act(openAgent.id, () => crewStart(openAgent.id), `${openAgent.name} started.`)}
          onPause={() => act(`p${openAgent.id}`, () => crewUpdate(openAgent.id, { enabled: !openAgent.enabled }), openAgent.enabled ? "Paused." : "Back on its schedule.")}
          onEdit={() => requireLive(() => { setEditing(openAgent); setOpen(null); }, "Editing agents")}
          onDelete={() => requireLive(async () => {
            const yes = await ui.confirm({ title: `Delete ${openAgent.name}?`, body: "It stops running. Its past runs stay in your chats.", confirm: "Delete", danger: true });
            if (!yes) return;
            setOpen(null);
            act(`d${openAgent.id}`, () => crewDelete(openAgent.id), "Deleted.");
          }, "Deleting agents")}
          onOpenConversation={onOpenConversation} live={session.live} />
      )}
      {editing && <AgentEditor initial={editing} onClose={() => setEditing(null)} onSaved={(msg) => { setEditing(null); ui.toast(msg); load(); }} />}
    </section>
  );
}

function AgentSheet({ agent, runs, busy, onClose, onStart, onPause, onEdit, onDelete, onOpenConversation, live }) {
  const [label, color] = STATE[agent.state] || STATE.ready;
  const working = agent.state === "working";
  return (
    <Overlay>
    <div className="p-scrim p-sheet-scrim" onPointerDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <section className="p-sheet" role="dialog" aria-modal="true" aria-label={agent.name}>
        <div className="p-sheet-hd">
          <span className={`dot${working ? " pulse" : ""}`} style={{ background: color }} />
          <div className="t"><b>{agent.name}</b><small>{label} · {agent.when}{agent.state === "scheduled" ? ` · ${nextText(agent.next_run_at)}` : ""}</small></div>
          <button className="p-ib plain" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
        </div>
        <p className="p-sheet-task">{agent.task}</p>
        <div className="p-kv"><span>Model</span><span>{agent.model === "auto" ? "Auto: the cheapest model that does it well" : agent.model}</span>
          <span>Made by</span><span>{agent.created_by === "chat" ? "Nova, from a chat" : "You"}</span></div>
        <div className="p-acts wrap">
          <button className="p-sm dark" disabled={working || busy === agent.id} onClick={onStart}><Icon name="play" size={13} />{agent.last_run_at ? "Start again" : "Start now"}</button>
          {agent.schedule?.kind !== "none" && <button className="p-sm" onClick={onPause}>{agent.enabled ? "Pause schedule" : "Turn schedule on"}</button>}
          <button className="p-sm" onClick={onEdit}><Icon name="edit" size={13} />Edit</button>
          <button className="p-sm danger" onClick={onDelete}><Icon name="trash" size={13} />Delete</button>
        </div>
        {!live && <p className="note">Starting and changing agents needs Nova open on your computer.</p>}
        {runs.length > 0 && (
          <div className="p-sheet-runs">
            <div className="muted">Recent runs</div>
            {runs.slice(0, 6).map((r) => (
              <button key={r.id} className="p-agrow btn small" onClick={() => r.conversation_id && onOpenConversation?.(r.conversation_id)}>
                <span className={`dot${r.status === "working" ? " pulse" : ""}`} style={{ background: r.status === "done" ? "var(--ok)" : "var(--clay)" }} />
                <div className="t"><b>{r.status === "done" ? "Finished" : r.status === "working" ? "Working" : "Didn't finish"}</b><small>{r.summary || r.error || ""} · {since(r.finished_at || r.started_at)}</small></div>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
    </Overlay>
  );
}

function AgentEditor({ initial, onClose, onSaved }) {
  const isNew = !initial.id;
  const [name, setName] = useState(initial.name || "");
  const [task, setTask] = useState(initial.task || "");
  const [kind, setKind] = useState(initial.schedule?.kind || "none");
  const [time, setTime] = useState(initial.schedule?.time || "08:00");
  const [day, setDay] = useState(initial.schedule?.day ?? 0);
  const [hours, setHours] = useState(initial.schedule?.every_hours || 3);
  const [at, setAt] = useState(() => {
    const t = initial.schedule?.at ? new Date(initial.schedule.at * 1000) : new Date(Date.now() + 3600000);
    return new Date(t.getTime() - t.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  });
  const [model, setModel] = useState(initial.model || "auto");
  const [startNow, setStartNow] = useState(false);
  const [models, setModels] = useState([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => { listModels().then((m) => setModels((Array.isArray(m) ? m : []).filter((x) => x.enabled !== false))).catch(() => {}); }, []);

  async function save(e) {
    e.preventDefault();
    const schedule = { kind, time, day: Number(day), every_hours: Number(hours), at: kind === "once" ? new Date(at).toISOString() : undefined };
    setSaving(true);
    setError("");
    try {
      if (isNew) await crewCreate({ name, task, schedule, model, start_now: startNow });
      else await crewUpdate(initial.id, { name, task, schedule, model });
      onSaved(isNew ? `${name || "Agent"} is set up.` : "Saved.");
    } catch (err) { setError(err.message); } finally { setSaving(false); }
  }

  return (
    <Overlay>
    <div className="p-scrim p-sheet-scrim" onPointerDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <form className="p-sheet" role="dialog" aria-modal="true" aria-label={isNew ? "New agent" : "Edit agent"} onSubmit={save}>
        <div className="p-sheet-hd"><div className="t"><b>{isNew ? "New agent" : "Edit agent"}</b><small>A job Nova does on its own</small></div>
          <button type="button" className="p-ib plain" onClick={onClose} aria-label="Close"><Icon name="x" /></button></div>
        <label className="p-field"><span>Name</span><input className="p-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Morning brief" maxLength={60} /></label>
        <label className="p-field"><span>What should it do?</span>
          <textarea className="p-input" rows={4} value={task} onChange={(e) => setTask(e.target.value)} required
            placeholder="Every morning, tell me what's due this week and what's on my calendar today." /></label>
        <div className="p-field"><span>When</span>
          <div className="p-chips">{WHEN.map(([id, label]) => <button type="button" key={id} className="p-chip" aria-pressed={kind === id} onClick={() => setKind(id)}>{label}</button>)}</div>
          {["daily", "weekdays", "weekly"].includes(kind) && (
            <div className="p-inline">
              {kind === "weekly" && <select className="p-input" value={day} onChange={(e) => setDay(e.target.value)} aria-label="Day">{DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</select>}
              <input className="p-input" type="time" value={time} onChange={(e) => setTime(e.target.value)} aria-label="Time" />
            </div>
          )}
          {kind === "hourly" && <div className="p-inline"><span>Every</span><input className="p-input" type="number" min={1} max={168} value={hours} onChange={(e) => setHours(e.target.value)} aria-label="Hours" /><span>hours</span></div>}
          {kind === "once" && <div className="p-inline"><input className="p-input" type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} aria-label="When" /></div>}
        </div>
        <label className="p-field"><span>Model</span>
          <select className="p-input" value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="auto">Auto: the cheapest model that does it well</option>
            <option value="claude_cli:haiku">Claude Haiku (fast)</option>
            <option value="claude_cli:sonnet">Claude Sonnet</option>
            <option value="claude_cli:opus">Claude Opus (slowest, strongest)</option>
            {models.filter((m) => !String(m.id).startsWith("claude_cli")).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select></label>
        {isNew && <Seg value={startNow ? "y" : "n"} onChange={(v) => setStartNow(v === "y")} label="Start now" options={[["n", "Just save it"], ["y", "Save and start now"]]} />}
        {error && <p className="err">{error}</p>}
        <div className="p-acts"><button type="button" className="p-sm" onClick={onClose}>Cancel</button>
          <button className="p-sm dark" disabled={saving || !task.trim()}>{saving ? "Saving…" : isNew ? "Set it up" : "Save"}</button></div>
        {isNew && <p className="note">Or just ask Nova in Chat: "every weekday at 8, summarize my assignments".</p>}
      </form>
    </div>
    </Overlay>
  );
}
