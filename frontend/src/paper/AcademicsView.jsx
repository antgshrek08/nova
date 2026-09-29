import { useEffect, useMemo, useState } from "react";
import { listStudyNotes, runCanvasSync } from "../api.js";
import CalendarTab from "./CalendarTab.jsx";
import Guide, { GuideButton } from "./Guide.jsx";
import Reactor from "./Reactor.jsx";
import { useUi } from "./ui.jsx";
import { canvasAssignments, cancelQueue, discoverHomework, homeworkAssignments, homeworkSources, operatorResume, operatorStatus, queueItemLive, reconcileQueueItem, taskLive } from "./paperApi.js";

const DAY = 86400000;

function dueDate(a) {
  const d = a.due_at ? new Date(a.due_at) : null;
  return d && !Number.isNaN(d.getTime()) ? d : null;
}

function courseCode(name = "") {
  return name.split(/\s|\(/)[0] || name;
}

function assignmentId(url = "") {
  const m = url.match(/assignments?\/(\d+)|assignment_(\d+)/);
  return m ? m[1] || m[2] : null;
}

/** Status comes only from real records: an open queue item, a running
 * operator task, or Canvas's own submitted flag. */
function statusFor(a, queues, tasks) {
  const id = String(a.canvas_id || assignmentId(a.url) || "");
  for (const q of queues) {
    if (q.state === "cancelled") continue;
    const item = (q.items || []).find((i) => String(i.assignment?.id) === id);
    if (!item) continue;
    if (queueItemLive(q, item)) return { cls: "work", text: "Nova working" };
    if (item.state === "executing") return { cls: "you", text: "Check receipt" };
    if (item.state === "queued") return { cls: "q", text: "Queued" };
    if (item.state === "completed") return { cls: "ok", text: "Submitted, receipt checked" };
    if (item.state === "unknown") return { cls: "you", text: "Check receipt" };
    if (item.state === "auth_required") return { cls: "you", text: "Needs you" };
  }
  if (tasks.some((t) => taskLive(t) && assignmentId(t.url) === id)) return { cls: "work", text: "Nova working" };
  if (a.submitted) return { cls: "ok", text: "Submitted" };
  return null;
}

export default function AcademicsView({ palette, dark, onAsk }) {
  const ui = useUi();
  const [tab, setTab] = useState("week");
  const [assignments, setAssignments] = useState(null);
  const [op, setOp] = useState({ queues: [], tasks: [], drafts: [], topics: [], stopped: false });
  const [notes, setNotes] = useState(null);
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [sources, setSources] = useState([]);

  async function load() {
    try {
      const [data, status, other, srcs] = await Promise.all([
        canvasAssignments(), operatorStatus().catch(() => null),
        homeworkAssignments().catch(() => ({ assignments: [] })), homeworkSources().catch(() => ({ sources: [] })),
      ]);
      // Other platforms' work, in the same shape as Canvas's (homework_discovery).
      const found = (other.assignments || []).map((a) => ({
        ...a, course_name: a.platform, submitted: a.status === "done", external: true, canvas_id: `x-${a.id}`,
      }));
      setAssignments([...(data.assignments || []), ...found]);
      setSources(srcs.sources || []);
      if (status) setOp(status);
      setError("");
    } catch (e) {
      setError(e.message);
      setAssignments([]);
    }
  }

  useEffect(() => {
    load();
    const timer = setInterval(() => operatorStatus().then(setOp).catch(() => {}), 5000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => { if (tab === "notes" && notes === null) listStudyNotes().then((n) => setNotes(n || [])).catch(() => setNotes([])); }, [tab, notes]);

  const now = Date.now();
  const startToday = new Date(); startToday.setHours(0, 0, 0, 0);
  const { groups, overdue, courses, undated } = useMemo(() => {
    const list = (assignments || []).filter((a) => !a.submitted);
    const horizon = tab === "week" ? 7 : 45;
    const within = list.filter((a) => { const d = dueDate(a); return d && d >= startToday && d - startToday < horizon * DAY; })
      .sort((x, y) => dueDate(x) - dueDate(y));
    const byDay = new Map();
    within.forEach((a) => {
      const key = dueDate(a).toDateString();
      if (!byDay.has(key)) byDay.set(key, []);
      byDay.get(key).push(a);
    });
    const late = list.filter((a) => { const d = dueDate(a); return d && d < startToday && now - d < 14 * DAY; });
    const courseMap = new Map();
    (assignments || []).forEach((a) => {
      const c = a.course_name || "Course";
      const row = courseMap.get(c) || { name: c, open: 0 };
      if (!a.submitted && dueDate(a) && dueDate(a) >= startToday) row.open += 1;
      courseMap.set(c, row);
    });
    const undatedOther = list.filter((a) => a.external && !dueDate(a));
    return { undated: undatedOther, groups: [...byDay.entries()], overdue: late, courses: [...courseMap.values()].sort((a, b) => a.name.localeCompare(b.name)) };
  }, [assignments, tab]);

  const activeQueues = (op.queues || []).filter((q) => ["queued", "running", "waiting_for_user"].includes(q.state));
  const uncertain = (op.queues || []).flatMap((q) => (q.items || []).filter((i) => i.state === "unknown").map((i) => ({ q, i })));
  const drafts = (op.drafts || []).filter((d) => !["submitted", "cancelled"].includes(d.status));
  const needs = uncertain.length + drafts.length + (op.topics || []).length;
  const openCount = (assignments || []).filter((a) => !a.submitted && dueDate(a) && dueDate(a) >= startToday && dueDate(a) - startToday < 7 * DAY).length;

  async function sync() {
    setSyncing(true);
    try {
      await runCanvasSync();
      if (sources.length) {
        const r = await discoverHomework();
        const needs = (r.platforms || []).filter((x) => x.status === "needs_sign_in").map((x) => x.source);
        if (needs.length) ui.toast(`${needs.join(", ")} need${needs.length === 1 ? "s" : ""} you to sign in once. Settings, Homework platforms.`);
      }
      await load();
    } catch (e) { setError(e.message); } finally { setSyncing(false); }
  }

  const label = (d) => {
    const diff = Math.round((new Date(d).setHours(0, 0, 0, 0) - startToday) / DAY);
    if (diff === 0) return "Today";
    if (diff === 1) return "Tomorrow";
    return d.toLocaleDateString([], { weekday: "long" });
  };

  const Row = ({ a }) => {
    const s = statusFor(a, op.queues || [], op.tasks || []);
    const d = dueDate(a);
    return (
      <a className="p-asg" href={a.url} target="_blank" rel="noreferrer" title={a.url}
        onContextMenu={(e) => ui.openMenu(e, [
          { label: "Open assignment", icon: "open", onSelect: () => window.open(a.url, "_blank") },
          { label: "Copy link", icon: "copy", onSelect: () => navigator.clipboard.writeText(a.url).then(() => ui.toast("Link copied.")) },
          "-",
          onAsk && { label: "Ask Nova to do it", icon: "bolt", onSelect: () => onAsk("Do this assignment for me: " + (a.display_title || a.title) + " (" + a.url + ")") },
          onAsk && { label: "Ask Nova to explain it", icon: "chat", onSelect: () => onAsk("Walk me through this assignment: " + (a.display_title || a.title) + " (" + a.url + ")") },
        ], { title: a.display_title || a.title })}>
        <b>{a.display_title || a.title}</b>
        {s ? <span className={`p-tag ${s.cls}`}>{s.text}</span> : <span />}
        <span className="meta">{a.external ? a.platform : courseCode(a.course_name)} · {d ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }).toLowerCase() : a.due_text || "no due date shown"}</span>
      </a>
    );
  };

  return (
    <section className="p-page" aria-label="Academics">
      <div className="p-ph">
        <Reactor palette={palette} dark={dark} />
        <div><h1>Academics</h1><div className="sub">{assignments ? `${openCount} due this week · ${courses.length} courses${sources.length ? ` from Canvas and ${sources.length} other platform${sources.length === 1 ? "" : "s"}` : " from Canvas"}` : "Loading your courses…"}</div></div>
        <GuideButton id="academics" />
        <span className="sp" />
        <div className="p-tabs" role="group" aria-label="View">
          {[["week", "This week"], ["upcoming", "Upcoming"], ["calendar", "Calendar"], ["courses", "Courses"], ["notes", "Notes"]].map(([k, t]) => (
            <button key={k} aria-pressed={tab === k} onClick={() => setTab(k)}>{t}</button>
          ))}
        </div>
        <button className="p-sm" onClick={sync} disabled={syncing}>{syncing ? "Syncing…" : sources.length ? "Sync all" : "Sync Canvas"}</button>
      </div>
      <div className="scroll p-pg">
        <Guide id="academics" />
        {error && <p className="err">{error}</p>}
        <div className="p-two">
          <div className="p-card" style={{ padding: "6px 16px" }}>
            {tab === "calendar" ? <CalendarTab onAsk={onAsk} /> : tab === "courses" ? (
              courses.length ? courses.map((c) => (
                <div className="p-day" key={c.name}><div className="d">{courseCode(c.name)}<small>{c.name}</small></div>
                  <div className="muted">{c.open ? `${c.open} open assignment${c.open === 1 ? "" : "s"}` : "Nothing open"}</div></div>
              )) : <div className="p-empty"><div className="muted">No courses yet. Connect Canvas in Settings, then sync.</div></div>
            ) : tab === "notes" ? (
              notes === null ? <div className="p-empty muted">Loading notes…</div>
                : notes.length ? notes.map((n) => (
                  <div className="p-day" key={n.id}><div className="d">{n.title || "Note"}<small>{n.created_at?.slice(0, 10)}</small></div><div style={{ fontSize: 14, whiteSpace: "pre-wrap" }}>{(n.content || "").slice(0, 400)}</div></div>
                )) : <div className="p-empty"><div className="muted">No notes yet. Ask Nova to take notes from a reading or a photo.</div></div>
            ) : assignments === null ? (
              <div className="p-empty muted">Loading assignments…</div>
            ) : (
              <>
                {groups.length === 0 && <div className="p-day"><div className="d">Today<small>{new Date().toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}</small></div><div className="muted">Nothing due {tab === "week" ? "this week" : "soon"}.</div></div>}
                {groups.map(([key, items]) => {
                  const d = new Date(key);
                  return (
                    <div className="p-day" key={key}>
                      <div className="d">{label(d)}<small>{d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}</small></div>
                      <div>{items.map((a) => <Row key={a.canvas_id || a.url} a={a} />)}</div>
                    </div>
                  );
                })}
                {undated.length > 0 && (
                  <div className="p-day"><div className="d">No date<small>other platforms</small></div><div>{undated.map((a) => <Row key={a.canvas_id || a.url} a={a} />)}</div></div>
                )}
                {overdue.length > 0 && (
                  <div className="p-day"><div className="d">Past due<small>last two weeks</small></div><div>{overdue.map((a) => <Row key={a.canvas_id || a.url} a={a} />)}</div></div>
                )}
              </>
            )}
          </div>
          <div className="p-stack">
            {op.stopped && (
              <div className="p-card"><div className="head"><i>Nova is stopped</i><span>{op.record?.reason || ""}</span></div>
                <div className="note">Nothing will act on your behalf until you resume.</div>
                <div className="p-acts"><button className="p-sm dark" onClick={() => operatorResume().then(load)}>Resume</button></div></div>
            )}
            <div className="p-card"><div className="head"><i>Autopilot</i><span>{activeQueues.length ? activeQueues[0].state.replace(/_/g, " ") : "idle"}</span></div>
              {activeQueues.length === 0 ? <div className="note">No homework queue is running. Ask Nova in Chat to do an assignment, or queue several.</div> : null}
              {activeQueues.map((q) => (
                <div key={q.id} style={{ display: "grid", gap: 8 }}>
                  {(q.items || []).map((i) => (
                    <div className="p-step" key={i.id}>
                      <span className="t">{i.state === "executing" ? "now" : i.state === "completed" ? "done" : "next"}</span>
                      <span>{i.assignment?.title}</span>
                      <span className={`s${i.state === "completed" ? " ok" : i.state === "executing" ? " now" : ""}`}>{i.state.replace(/_/g, " ")}</span>
                    </div>
                  ))}
                  <div className="note">Submission authorized until {new Date(q.expires_at * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}.</div>
                  <div className="p-acts"><button className="p-sm" onClick={() => cancelQueue(q.id).then(load)}>Stop queue</button></div>
                </div>
              ))}
            </div>
            <div className="p-card"><div className="head"><i>Needs you</i><span>{needs}</span></div>
              {needs === 0 && <div className="note">Nothing is waiting on you.</div>}
              {drafts.map((d) => <div className="p-step" key={d.id}><span className="t">draft</span><span>{d.title || d.assignment_title || "Written assignment"}</span><span className="s">review in Chat</span></div>)}
              {(op.topics || []).map((t) => <div className="p-step" key={t.id}><span className="t">topic</span><span>{t.title || t.topic || "Essay topic"}</span><span className="s">approve in Chat</span></div>)}
              {uncertain.map(({ q, i }) => (
                <div className="p-step" key={i.id}><span className="t">check</span><span>{i.assignment?.title}: no receipt yet</span>
                  <button className="p-link" onClick={() => reconcileQueueItem(q.id, i.id).then(load).catch((e) => setError(e.message))}>Check receipt</button></div>
              ))}
            </div>
            <div className="p-card"><div className="head"><i>Courses</i><span>open now</span></div>
              {courses.length ? <div className="p-kv">{courses.map((c) => [<span key={`${c.name}a`}>{c.name}</span>, <span key={`${c.name}b`}>{c.open}</span>])}</div>
                : <div className="note">Connect Canvas in Settings to see your courses.</div>}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
