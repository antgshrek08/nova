// Settings > Calendar: every calendar Nova can read (Apple, Google, and any
// calendar by its private link), where Nova adds events, and study planning.
import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL } from "../api.js";
import Icon from "./icons.jsx";
import { Row } from "./SettingsSections.jsx";
import { useUi } from "./ui.jsx";

async function call(path, init) {
  const res = await fetch(`${BACKEND_URL}${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return body;
}

function Section({ title, desc, children, aside }) {
  return (
    <div className="p-sgroup">
      <div className="p-shead"><h4>{title}</h4>{aside}</div>
      {desc && <p className="d">{desc}</p>}
      {children}
    </div>
  );
}

const HOW = [
  ["Google Calendar", "On a computer: calendar.google.com, Settings, click the calendar on the left, then copy \"Secret address in iCal format\". For adding events too, connect Google under Connectors."],
  ["Outlook / Microsoft 365", "outlook.com or Outlook on the web: Settings, Calendar, Shared calendars, Publish a calendar, then copy the ICS link."],
  ["iCloud", "Or connect Apple Calendar above for adding events. For read only: in the Calendar app, share the calendar publicly and copy the link."],
  ["School or team calendars", "Look for Subscribe, iCal, ICS or webcal on the calendar's page and copy that link."],
];

export function CalendarSources({ prefs }) {
  const ui = useUi();
  const [src, setSrc] = useState(null);
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState("");
  const [how, setHow] = useState(false);
  const load = useCallback(() => call("/calendar/sources").then(setSrc).catch((e) => setSrc({ error: e.message, apple: {}, google: [], feeds: [] })), []);
  useEffect(() => { load(); }, [load]);

  async function add(e) {
    e.preventDefault();
    setBusy("add");
    try {
      const f = await call("/calendar/feeds", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: url.trim(), name: name.trim() }) });
      setUrl(""); setName("");
      ui.toast(`Added "${f.name}". Its events now show in Academics, Calendar.`);
      load();
    } catch (err) { ui.toast(err.message, { error: true }); } finally { setBusy(""); }
  }
  const remove = (f) => ui.undoable({
    message: `Removed "${f.name}".`,
    apply: () => setSrc((s) => ({ ...s, feeds: s.feeds.filter((x) => x.id !== f.id) })),
    revert: load,
    commit: () => call(`/calendar/feeds/${f.id}`, { method: "DELETE" }),
  });

  const writable = [
    ...((src?.apple?.calendars || []).filter((c) => c.writable).map((c) => ({ ...c, label: `${c.name} (Apple)` }))),
    ...((src?.google || []).flatMap((a) => a.calendars.map((c) => ({ ...c, label: `${c.name} (${a.label})` })))),
  ];
  const s = prefs.settings;

  async function planWeek() {
    setBusy("plan");
    try {
      const r = await call("/calendar/study-week", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      ui.toast(`Planned ${r.planned.length} study session${r.planned.length === 1 ? "" : "s"}${r.skipped?.length ? `; ${r.skipped.length} skipped` : ""}.`);
    } catch (err) { ui.toast(err.message, { error: true }); } finally { setBusy(""); }
  }

  return (
    <>
      <Section title="Your calendars" desc="Nova reads all of these together: in Academics, Calendar, when it finds you free time, and when it plans study sessions.">
        {src === null && <div className="note">Checking your calendars…</div>}
        {src && (
          <>
            <Row label="Apple (iCloud)" desc={src.apple.connected ? `${src.apple.calendars.map((c) => c.name).join(", ") || "Connected"} · read and write` : "Connect it above"}>
              <span className={`p-status ${src.apple.connected ? "tested" : "browse"}`}>{src.apple.connected ? "connected" : "not connected"}</span>
            </Row>
            {src.google.length > 0 ? src.google.map((a) => (
              <Row key={a.email} label={a.label} desc={a.error ? `Couldn't read it: ${a.error}` : `${a.calendars.map((c) => c.name).join(", ")} · read and write`}>
                <span className={`p-status ${a.error ? "unsupported" : "tested"}`}>{a.error ? "problem" : "connected"}</span>
              </Row>
            )) : (
              <Row label="Google" desc="Add it by its private link below (read only), or connect the Google Workspace connector under Connectors to add events too.">
                <span className="p-status browse">not connected</span>
              </Row>
            )}
            {(src.feeds || []).map((f) => (
              <Row key={f.id} label={f.name} desc="Calendar link · read only">
                <button className="p-link" onClick={() => remove(f)} aria-label={`Remove ${f.name}`} title="Remove"><Icon name="trash" size={14} /></button>
                <span className="p-status tested">linked</span>
              </Row>
            ))}
          </>
        )}
      </Section>

      <Section title="Add any calendar by its link" desc="Google, Outlook, Microsoft 365, Yahoo, your school's calendar: almost every calendar has a private or published link. Nova reads it; nothing is changed there."
        aside={<button className="p-link" onClick={() => setHow((h) => !h)}>{how ? "Hide how" : "Where do I find the link?"}</button>}>
        {how && (
          <div className="p-howto">
            {HOW.map(([t, d]) => <div key={t}><b>{t}</b><span>{d}</span></div>)}
          </div>
        )}
        <form className="p-grid2" onSubmit={add}>
          <input className="p-input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https:// or webcal:// calendar link" aria-label="Calendar link" type="password" autoComplete="off" />
          <input className="p-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name (optional)" aria-label="Calendar name" />
          <div className="p-acts"><button className="p-sm dark" disabled={busy === "add" || !url.trim()}>{busy === "add" ? "Checking…" : "Add calendar"}</button>
            <span className="note">The link is kept on this computer. Treat a private link like a password.</span></div>
        </form>
      </Section>

      {writable.length > 0 && (
        <Section title="How Nova uses your calendar">
          <Row label="Nova adds events to" desc="Study sessions and anything you ask Nova to schedule">
            <select className="p-sm" value={s.calendar_default_url || ""} onChange={(e) => prefs.save({ calendar_default_url: e.target.value })} aria-label="Calendar for Nova's events">
              <option value="">{writable[0] ? `${writable[0].label} (first one)` : "Choose…"}</option>
              {writable.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
          </Row>
          <Row label="Remind me before events Nova adds" desc="Apple calendars; Google uses its own default">
            <select className="p-sm" value={String(s.calendar_reminder_minutes ?? 30)} onChange={(e) => prefs.save({ calendar_reminder_minutes: Number(e.target.value) })} aria-label="Reminder">
              {[[0, "No reminder"], [10, "10 minutes"], [30, "30 minutes"], [60, "1 hour"], [120, "2 hours"], [1440, "1 day"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Row>
          <Row label="Study sessions" desc="How long, and the time Nova tries first on the day before something's due">
            <select className="p-sm" value={String(s.study_block_minutes ?? 60)} onChange={(e) => prefs.save({ study_block_minutes: Number(e.target.value) })} aria-label="Study length">
              {[30, 45, 60, 90, 120].map((m) => <option key={m} value={m}>{m} min</option>)}
            </select>
            <select className="p-sm" value={String(s.study_block_hour ?? 19)} onChange={(e) => prefs.save({ study_block_hour: Number(e.target.value) })} aria-label="Study time">
              {Array.from({ length: 17 }, (_, i) => i + 6).map((h) => <option key={h} value={h}>{new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric" })}</option>)}
            </select>
          </Row>
          <Row label="Plan this week" desc="A study session before every assignment due in the next 7 days, in free time across all your calendars">
            <button className="p-sm dark" onClick={planWeek} disabled={busy === "plan"}>{busy === "plan" ? "Planning…" : "Plan study time"}</button>
          </Row>
        </Section>
      )}
    </>
  );
}
