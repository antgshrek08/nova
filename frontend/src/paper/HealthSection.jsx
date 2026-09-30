// Settings > Health: is Nova working properly, in plain words. A quick check
// (Nova's own files are intact, nothing has been going wrong), the problems
// it hit recently, and -- only on a copy of Nova's source that can use it --
// undoing the last change Nova made to its own code.
import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL } from "../api.js";
import Icon from "./icons.jsx";
import { agoText } from "./remote.js";
import { useUi } from "./ui.jsx";

async function call(path, init) {
  const res = await fetch(`${BACKEND_URL}${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return body;
}

export default function HealthSection() {
  const ui = useUi();
  const [status, setStatus] = useState(null);
  const [errors, setErrors] = useState([]);
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState(null);

  const load = useCallback(async () => {
    const [s, e] = await Promise.all([call("/sentinel/status").catch(() => null), call("/sentinel/errors?limit=20").catch(() => ({ errors: [] }))]);
    setStatus(s);
    setErrors(e.errors || []);
  }, []);
  useEffect(() => { load(); }, [load]);

  async function check() {
    setChecking(true);
    try { setResult(await call("/sentinel/diagnose?test_pattern=none", { method: "POST" })); await load(); }
    catch (e) { ui.toast(e.message, { error: true }); } finally { setChecking(false); }
  }
  async function clear() {
    try { await call("/sentinel/errors", { method: "DELETE" }); setErrors([]); ui.toast("Cleared."); } catch (e) { ui.toast(e.message, { error: true }); }
  }
  async function undo() {
    const yes = await ui.confirm({ title: "Undo Nova's last change to itself?", body: "Puts back the files Nova changed in its own code the last time it repaired itself.", confirm: "Undo it", danger: true });
    if (!yes) return;
    try {
      const r = await call("/sentinel/rollback", { method: "POST" });
      if (r.ok === false || r.error) throw new Error(r.error || "It couldn't be undone.");
      ui.toast("Undone.");
      load();
    } catch (e) { ui.toast(e.message, { error: true }); }
  }

  if (!status) return <div className="note">Checking…</div>;
  const intact = status.syntax?.valid !== false;
  const healthy = intact && errors.length === 0;
  return (
    <>
      <div className="p-sgroup">
        <div className="p-remote-card">
          <span className={`dot${healthy ? " on" : ""}`} style={healthy ? undefined : { background: "var(--clay)" }} />
          <div className="t">
            <b>{healthy ? "Nova is healthy" : !intact ? "Some of Nova's files are damaged" : `Nova hit ${errors.length} ${errors.length === 1 ? "problem" : "problems"} recently`}</b>
            <small>{healthy ? "Its files are intact and nothing has gone wrong lately." : !intact ? "Reinstalling Nova fixes this." : "Details below. Most fix themselves; tell Nova in chat if one keeps happening."}</small>
          </div>
          <button className="p-sm" disabled={checking} onClick={check}><Icon name="refresh" size={14} />{checking ? "Checking…" : "Check now"}</button>
        </div>
        {result && <p className="note">{result.healthy ? "Checked just now: all good." : "Checked just now: see the problems below."}</p>}
      </div>
      <div className="p-sgroup">
        <div className="p-shead"><h4>Recent problems</h4>{errors.length > 0 && <button className="p-link" onClick={clear}>Clear</button>}</div>
        {errors.length === 0 && <p className="d">None.</p>}
        {errors.map((e, i) => (
          <div className="p-row" key={i}>
            <span>{String(e.message || e.error || e.type || "Problem").slice(0, 160)}<small>{[e.where || e.source || e.path, e.timestamp && agoText(new Date(e.timestamp).getTime())].filter(Boolean).join(" · ")}</small></span>
          </div>
        ))}
      </div>
      {status.last_checkpoint && status.can_rollback && (
        <div className="p-sgroup">
          <div className="p-shead"><h4>Nova's self-repairs</h4></div>
          <p className="d">Nova can fix bugs in its own code, and keeps a way back each time.</p>
          <div className="p-acts"><button className="p-sm danger" onClick={undo}>Undo Nova's last change to itself</button></div>
        </div>
      )}
    </>
  );
}
