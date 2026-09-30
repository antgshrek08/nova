// Settings > School profile: where you study, and your courses -- the ones
// Nova found on Canvas and your homework sites, plus any you add yourself
// (a class with no website, say). Nova uses these to sort your work and to
// know which class a question is about.
import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL, getUserProfile, updateUserProfile } from "../api.js";
import Icon from "./icons.jsx";
import { useUi } from "./ui.jsx";

async function call(path, init) {
  const res = await fetch(`${BACKEND_URL}${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return body;
}

export default function SchoolProfile() {
  const ui = useUi();
  const [profile, setProfile] = useState(null);
  const [found, setFound] = useState([]);
  const [mine, setMine] = useState([]);
  const [form, setForm] = useState({ code: "", name: "", instructor: "", schedule: "" });
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    getUserProfile().then(setProfile).catch(() => setProfile({}));
    call("/courses").then((rows) => setMine(Array.isArray(rows) ? rows : [])).catch(() => setMine([]));
    try {
      const [canvas, other] = await Promise.all([
        call("/canvas/assignments").catch(() => ({ assignments: [] })),
        call("/homework/assignments").catch(() => ({ assignments: [] })),
      ]);
      const counts = new Map();
      for (const a of canvas.assignments || []) if (a.course_name) counts.set(a.course_name, { name: a.course_name, where: "Canvas", n: (counts.get(a.course_name)?.n || 0) + 1 });
      for (const a of other.assignments || []) if (a.platform) counts.set(a.platform, { name: a.platform, where: "Homework site", n: (counts.get(a.platform)?.n || 0) + 1 });
      setFound([...counts.values()].sort((x, y) => x.name.localeCompare(y.name)));
    } catch { setFound([]); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async (key, value) => {
    if ((profile?.[key] || "") === value) return;
    try { setProfile(await updateUserProfile({ [key]: value })); ui.toast("Saved."); } catch (e) { ui.toast(e.message, { error: true }); }
  };
  const field = (key, label, placeholder) => (
    <div className="p-row">
      <span>{label}</span>
      <div className="ctl">
        <input className="p-input" key={`${key}-${profile ? "l" : "w"}`} defaultValue={profile?.[key] || ""} placeholder={placeholder} aria-label={label}
          onBlur={(e) => save(key, e.target.value.trim())} onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
      </div>
    </div>
  );

  async function add(e) {
    e.preventDefault();
    if (!form.name.trim() && !form.code.trim()) return;
    try {
      await call("/courses", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: form.code.trim() || form.name.trim().slice(0, 12), name: form.name.trim() || form.code.trim(), instructor: form.instructor.trim(), schedule: form.schedule.trim() }) });
      setForm({ code: "", name: "", instructor: "", schedule: "" });
      setAdding(false);
      ui.toast("Course added.");
      load();
    } catch (err) { ui.toast(err.message, { error: true }); }
  }

  async function remove(c) {
    const yes = await ui.confirm({ title: `Remove ${c.code || c.name}?`, body: "Only from this list. Nothing on Canvas or your homework sites changes.", confirm: "Remove", danger: true });
    if (!yes) return;
    try { await call(`/courses/${c.id}`, { method: "DELETE" }); load(); } catch (err) { ui.toast(err.message, { error: true }); }
  }

  return (
    <>
      <div className="p-sgroup">
        <div className="p-shead"><h4>Your school</h4></div>
        <p className="d">Helps Nova answer at the right level and find your school's sites.</p>
        {field("school", "School", "Your school")}
        {field("major", "Major or focus", "What you study")}
        {field("graduation_year", "Graduating", "Year, like 2028")}
      </div>
      <div className="p-sgroup">
        <div className="p-shead"><h4>Your courses</h4></div>
        <p className="d">Nova finds these on Canvas and your homework sites. Add any others, like a class with no website.</p>
        {found.length === 0 && mine.length === 0 && <p className="note">None yet. Connect Canvas or a homework site, or add a course here.</p>}
        {found.map((c) => (
          <div className="p-row" key={`f-${c.where}-${c.name}`}>
            <span>{c.name}<small>{c.where} · {c.n} {c.n === 1 ? "assignment" : "assignments"}</small></span>
            <div className="ctl"><span className="p-status tested">Found</span></div>
          </div>
        ))}
        {mine.map((c) => (
          <div className="p-row" key={`m-${c.id}`}>
            <span>{c.code && c.name && c.code !== c.name ? `${c.code} · ${c.name}` : c.name || c.code}<small>{[c.instructor, c.schedule].filter(Boolean).join(" · ") || "Added by you"}</small></span>
            <div className="ctl"><button className="p-ib plain" aria-label={`Remove ${c.name}`} onClick={() => remove(c)}><Icon name="trash" size={15} /></button></div>
          </div>
        ))}
        {adding ? (
          <form className="p-course-form" onSubmit={add}>
            <input className="p-input" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="Code, like MAC2311" aria-label="Course code" />
            <input className="p-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Name, like Calculus 1" aria-label="Course name" />
            <input className="p-input" value={form.instructor} onChange={(e) => setForm({ ...form, instructor: e.target.value })} placeholder="Instructor (optional)" aria-label="Instructor" />
            <input className="p-input" value={form.schedule} onChange={(e) => setForm({ ...form, schedule: e.target.value })} placeholder="When it meets (optional)" aria-label="When it meets" />
            <div className="p-acts"><button type="button" className="p-sm" onClick={() => setAdding(false)}>Cancel</button><button className="p-sm dark">Add course</button></div>
          </form>
        ) : (
          <div className="p-acts"><button className="p-sm" onClick={() => setAdding(true)}><Icon name="plus" size={14} />Add a course</button></div>
        )}
      </div>
    </>
  );
}
