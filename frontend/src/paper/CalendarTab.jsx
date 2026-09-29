// Academics > Calendar: one agenda over the user's iCloud events and every
// due date (app/calendar_hub.py), with study planning and quick events.
import { useCallback, useEffect, useMemo, useState } from "react";
import { BACKEND_URL } from "../api.js";
import Icon from "./icons.jsx";
import { useUi } from "./ui.jsx";

async function call(path, init) {
  const res = await fetch(`${BACKEND_URL}${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return body;
}
const post = (path, body) => call(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

const time = (d) => d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }).toLowerCase();
const dayKey = (d) => d.toDateString();

export default function CalendarTab({ onAsk }) {
  const ui = useUi();
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [free, setFree] = useState([]);
  const [cals, setCals] = useState([]);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState(() => {
    const d = new Date(Date.now() + 3600e3);
    d.setMinutes(0, 0, 0);
    const iso = new Date(d - d.getTimezoneOffset() * 60e3).toISOString().slice(0, 16);
    return { title: "", start: iso, minutes: 60, calendar: "" };
  });
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    call(`/calendar/agenda?days=${days}`).then(setData).catch((e) => setData({ items: [], note: e.message }));
    call(`/calendar/free?days=${days}&minutes=60`).then((d) => setFree(d.free || [])).catch(() => setFree([]));
  }, [days]);
  useEffect(() => { load(); }, [load]);
  // Every calendar Nova can add to: Apple's and each connected Google account's.
  useEffect(() => {
    call("/calendar/sources").then((src) => setCals([
      ...(src.apple?.calendars || []).filter((c) => c.writable).map((c) => ({ url: c.id, name: `${c.name} (Apple)` })),
      ...(src.google || []).flatMap((a) => a.calendars.map((c) => ({ url: c.id, name: `${c.name} (Google)` }))),
    ])).catch(() => {});
  }, []);

  const byDay = useMemo(() => {
    const map = new Map();
    const start = new Date(); start.setHours(0, 0, 0, 0);
    for (let i = 0; i < days; i += 1) map.set(dayKey(new Date(start.getTime() + i * 864e5)), []);
    (data?.items || []).forEach((it) => {
      const d = new Date(it.start);
      if (!Number.isNaN(d.getTime()) && map.has(dayKey(d))) map.get(dayKey(d)).push({ ...it, d });
    });
    return [...map.entries()];
  }, [data, days]);
  const freeByDay = useMemo(() => {
    const map = new Map();
    free.forEach((f) => { const s = new Date(f.start); const k = dayKey(s); if (!map.has(k)) map.set(k, []); map.get(k).push([s, new Date(f.end)]); });
    return map;
  }, [free]);

  async function plan(it) {
    setBusy(it.title);
    try {
      const r = await post("/calendar/study", { title: it.title, due_at: it.start, url: it.url });
      ui.toast(`Study session planned for ${new Date(r.start).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}.`);
      load();
    } catch (e) { ui.toast(e.message, { error: true }); } finally { setBusy(""); }
  }
  async function planAll() {
    setBusy("all");
    try {
      const r = await post("/calendar/study-week", { days });
      ui.toast(`Planned ${r.planned.length} study session${r.planned.length === 1 ? "" : "s"}${r.skipped.length ? `, ${r.skipped.length} skipped` : ""}.`);
      load();
    } catch (e) { ui.toast(e.message, { error: true }); } finally { setBusy(""); }
  }
  async function addEvent(e) {
    e.preventDefault();
    const calendar = form.calendar || cals[0]?.url;
    if (!calendar || !form.title.trim()) return;
    setBusy("add");
    try {
      const start = new Date(form.start);
      const end = new Date(start.getTime() + Number(form.minutes) * 60e3);
      await post("/calendar/events", { calendar, title: form.title.trim(), start: start.toISOString(), end: end.toISOString() });
      setForm((f) => ({ ...f, title: "" }));
      setAdding(false);
      ui.toast("Added to your calendar.");
      load();
    } catch (err) { ui.toast(err.message, { error: true }); } finally { setBusy(""); }
  }
  async function remove(it) {
    const ok = await ui.confirm({ title: `Delete "${it.title}"?`, body: `It will be removed from your ${it.source} calendar on every device.`, confirm: "Delete", danger: true });
    if (!ok) return;
    try { await call(`/apple-calendar/events?event_url=${encodeURIComponent(it.href)}`, { method: "DELETE" }); ui.toast("Deleted."); load(); }
    catch (e) { ui.toast(e.message, { error: true }); }
  }

  const menu = (e, it) => ui.openMenu(e, it.kind === "due" ? [
    { label: "Plan study time", icon: "cal", onSelect: () => plan(it) },
    it.url && { label: "Open assignment", icon: "open", onSelect: () => window.open(it.url, "_blank") },
    onAsk && { label: "Ask Nova to help", icon: "chat", onSelect: () => onAsk(`Help me with ${it.title}, due ${new Date(it.start).toLocaleString()}${it.url ? ` (${it.url})` : ""}`) },
  ] : [
    { label: "Copy", icon: "copy", onSelect: () => navigator.clipboard.writeText(`${it.title}, ${new Date(it.start).toLocaleString()}`) },
    it.href && "-",
    it.href && { label: "Delete event", icon: "trash", danger: true, onSelect: () => remove(it) },
  ], { title: it.title });

  const label = (k) => {
    const d = new Date(k); const t = new Date(); t.setHours(0, 0, 0, 0);
    const diff = Math.round((d - t) / 864e5);
    return diff === 0 ? "Today" : diff === 1 ? "Tomorrow" : d.toLocaleDateString([], { weekday: "long" });
  };

  return (
    <div className="p-caltab">
      <div className="p-calbar">
        <div className="p-seg" role="group" aria-label="How far ahead">
          {[[7, "Week"], [14, "Two weeks"], [30, "Month"]].map(([n, l]) => <button key={n} aria-pressed={days === n} onClick={() => setDays(n)}>{l}</button>)}
        </div>
        <span style={{ flex: 1 }} />
        {data?.can_write && <button className="p-sm" onClick={() => setAdding((a) => !a)}><Icon name="plus" />New event</button>}
        {data?.can_write && <button className="p-sm dark" onClick={planAll} disabled={busy === "all"}><Icon name="cal" />{busy === "all" ? "Planning…" : "Plan study time"}</button>}
      </div>
      {adding && (
        <form className="p-calnew" onSubmit={addEvent}>
          <input className="p-input" autoFocus value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="What is it?" aria-label="Event title" />
          <input className="p-input" type="datetime-local" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} aria-label="Starts" />
          <select className="p-input" value={form.minutes} onChange={(e) => setForm({ ...form, minutes: e.target.value })} aria-label="Length">
            {[15, 30, 45, 60, 90, 120, 180].map((m) => <option key={m} value={m}>{m < 60 ? `${m} min` : `${m / 60} h`}</option>)}
          </select>
          <select className="p-input" value={form.calendar} onChange={(e) => setForm({ ...form, calendar: e.target.value })} aria-label="Calendar">
            {cals.map((c) => <option key={c.url} value={c.url}>{c.name}</option>)}
          </select>
          <button className="p-sm dark" disabled={busy === "add" || !form.title.trim()}>{busy === "add" ? "Adding…" : "Add"}</button>
        </form>
      )}
      {data?.note && <p className="note">{data.note}</p>}
      {data === null && <div className="p-empty muted">Loading your calendar…</div>}
      {data && byDay.map(([k, items]) => {
        const d = new Date(k);
        const open = freeByDay.get(k) || [];
        return (
          <div className="p-day" key={k}>
            <div className="d">{label(k)}<small>{d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}</small></div>
            <div className="p-calitems">
              {items.length === 0 && <div className="note">Nothing scheduled.</div>}
              {items.map((it, i) => (
                <div key={`${it.uid || it.url || it.title}${i}`} className={`p-calitem ${it.kind}`} tabIndex={0} onContextMenu={(e) => menu(e, it)}>
                  <span className="tm">{it.all_day ? "all day" : time(it.d)}{it.end && !it.all_day ? `–${time(new Date(it.end))}` : ""}</span>
                  <span className="tt"><b>{it.kind === "due" ? `Due: ${it.title}` : it.title}</b><small>{[it.source, it.where].filter(Boolean).join(" · ")}</small></span>
                  {it.kind === "due" && data.can_write && (
                    <button className="p-link" onClick={() => plan(it)} disabled={busy === it.title} title="Put a study session before it in your calendar">{busy === it.title ? "Planning…" : "Plan study"}</button>
                  )}
                </div>
              ))}
              {open.length > 0 && <div className="p-free">Free {open.slice(0, 3).map(([s, e]) => `${time(s)}–${time(e)}`).join(", ")}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
