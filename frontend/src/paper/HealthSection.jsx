// Settings > Health: is Nova working properly, in plain words. A quick check
// (Nova's own files are intact, nothing has been going wrong), bugs Nova found
// in its own code and fixing them (app/self_heal.py), whether it may fix them
// without asking, the problems it hit recently, and undoing its last fix.
import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL } from "../api.js";
import Icon from "./icons.jsx";
import { agoText } from "./remote.js";
import { Seg } from "./SettingsSections.jsx";
import { useUi } from "./ui.jsx";

async function call(path, init) {
  const res = await fetch(`${BACKEND_URL}${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return body;
}

export default function HealthSection({ prefs }) {
  const ui = useUi();
  const [status, setStatus] = useState(null);
  const [errors, setErrors] = useState([]);
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState(null);
  const [fixing, setFixing] = useState(null);

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
  async function fix(bug) {
    setFixing(bug.sig);
    try {
      const r = await call(`/sentinel/bugs/${bug.sig}/fix`, { method: "POST" });
      if (!r.ok) throw new Error(r.error || "Nova couldn't fix it.");
      ui.toast(r.message || "Fixed.");
    } catch (e) { ui.toast(e.message, { error: true }); } finally { setFixing(null); load(); }
  }
  async function dismiss(bug) {
    try { await call(`/sentinel/bugs/${bug.sig}`, { method: "DELETE" }); load(); } catch (e) { ui.toast(e.message, { error: true }); }
  }
  async function restart() {
    try {
      await call("/sentinel/restart", { method: "POST" });
      ui.toast("Restarting Nova's engine…");
      setTimeout(load, 6000);
    } catch (e) { ui.toast(e.message, { error: true }); }
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
  const bugs = status.bugs || [];
  const open = bugs.filter((b) => b.status !== "fixed");
  const fixedWaiting = bugs.some((b) => b.status === "fixed" && b.fixed_at * 1000 > Date.now() - 86400000);
  const healthy = intact && errors.length === 0 && open.length === 0;
  const mode = prefs?.settings?.self_repair || "ask";
  return (
    <>
      <div className="p-sgroup">
        <div className="p-remote-card">
          <span className={`dot${healthy ? " on" : ""}`} style={healthy ? undefined : { background: "var(--clay)" }} />
          <div className="t">
            <b>{healthy ? "Nova is healthy" : !intact ? "Some of Nova's files are damaged" : open.length ? `Nova found ${open.length} ${open.length === 1 ? "bug" : "bugs"} in its own code` : `Nova hit ${errors.length} ${errors.length === 1 ? "problem" : "problems"} recently`}</b>
            <small>{healthy ? "Its files are intact and nothing has gone wrong lately." : !intact ? "Reinstalling Nova fixes this." : open.length ? "Nova can fix it and check the fix itself. See below." : "Details below. Most fix themselves; tell Nova in chat if one keeps happening."}</small>
          </div>
          <button className="p-sm" disabled={checking} onClick={check}><Icon name="refresh" size={14} />{checking ? "Checking…" : "Check now"}</button>
        </div>
        {result && <p className="note">{result.healthy ? "Checked just now: all good." : "Checked just now: see the problems below."}</p>}
      </div>
      <div className="p-sgroup">
        <div className="p-shead"><h4>Bugs in Nova's own code</h4></div>
        <p className="d">When something goes wrong because of a mistake in Nova's code, Nova can fix it: a coding model writes the smallest change, and it's kept only if all of Nova's checks still pass.</p>
        {open.length === 0 && <p className="note">None found.</p>}
        {bugs.map((b) => (
          <div className="p-row" key={b.sig}>
            <span>{String(b.message || b.type).slice(0, 160)}
              <small>{[`${String(b.file || "").split("/").pop()}, line ${b.line}`, b.count > 1 && `${b.count} times`, b.status === "fixed" ? "Fixed" : b.last_result].filter(Boolean).join(" · ")}</small>
            </span>
            <div className="ctl">
              {b.status === "fixed" ? <span className="p-status tested">Fixed</span> : <>
                {status.can_repair && <button className="p-sm" disabled={!!fixing} onClick={() => fix(b)}>{fixing === b.sig || b.status === "fixing" ? "Fixing…" : "Fix it"}</button>}
                <button className="p-ib plain" aria-label="Dismiss" onClick={() => dismiss(b)}><Icon name="x" size={15} /></button>
              </>}
            </div>
          </div>
        ))}
        {fixedWaiting && status.can_restart && (
          <div className="p-acts"><button className="p-sm dark" onClick={restart}><Icon name="refresh" size={14} />Restart Nova's engine to use the fix</button></div>
        )}
        {!status.can_repair && <p className="note">This copy of Nova can't change its own files. Updating Nova gets fixes instead.</p>}
        {prefs && (
          <div className="p-row">
            <span>Fixing its own bugs<small>{mode === "auto" ? "Nova fixes them as soon as it finds them and tells you." : mode === "off" ? "Nova only lists them here." : "Nova tells you and waits for you to press Fix it."}</small></span>
            <div className="ctl"><Seg value={mode} onChange={(v) => prefs.save({ self_repair: v })} label="Fixing its own bugs" options={[["ask", "Ask me"], ["auto", "Automatically"], ["off", "Off"]]} /></div>
          </div>
        )}
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
