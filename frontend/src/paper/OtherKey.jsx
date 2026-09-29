// "Any other service or key": a key by a name the user chooses (Jev, a
// provider Nova doesn't list, a school's AI gateway). The engine routes it
// (app/custom_keys.py): a known name goes where it belongs, an address that
// serves models lists them to pick from, anything else is kept by its name.
import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL, createCustomModel } from "../api.js";
import Icon from "./icons.jsx";

async function call(path, init) {
  const res = await fetch(`${BACKEND_URL}${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return body;
}

export default function OtherKey({ preview = false, onDone }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", key: "", api_base: "" });
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [models, setModels] = useState(null);
  const [pick, setPick] = useState(() => new Set());
  const [saved, setSaved] = useState([]);
  const loadSaved = useCallback(() => call("/keys/custom").then((d) => setSaved(d.keys || [])).catch(() => {}), []);
  useEffect(() => { loadSaved(); }, [loadSaved]);

  async function submit(e) {
    e.preventDefault();
    if (preview) { setMsg("In preview nothing is saved."); return; }
    setBusy("save"); setMsg(""); setModels(null);
    try {
      const r = await call("/keys/custom", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
      setMsg(r.note);
      if (r.kind === "models") {
        setModels({ base: r.api_base, ids: r.models });
        setPick(new Set(r.models.slice(0, 3)));
      } else {
        setForm({ name: "", key: "", api_base: "" });
        onDone?.();
      }
      loadSaved();
    } catch (err) { setMsg(err.message); } finally { setBusy(""); }
  }
  async function add() {
    setBusy("add");
    try {
      for (const id of pick) await createCustomModel({ name: `${form.name} · ${id.split("/").pop()}`, provider: "custom", modelId: id, category: "general_writing", apiBase: models.base, apiKey: form.key });
      setMsg(`Added ${pick.size} model${pick.size === 1 ? "" : "s"} from ${form.name}.`);
      setModels(null); setForm({ name: "", key: "", api_base: "" });
      onDone?.();
    } catch (err) { setMsg(err.message); } finally { setBusy(""); }
  }

  return (
    <div className={`p-mg-card${open ? " open" : ""}`}>
      <button className="head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="t"><b>Any other service or key</b><small>A key Nova doesn't list, by a name you choose (like Jev)</small></span>
        {saved.length > 0 && <span className="p-status tested">{saved.length} saved</span>}
        <svg className="car" viewBox="0 0 12 12" aria-hidden="true"><path d="M4 2l4 4-4 4" /></svg>
      </button>
      {open && (
        <div className="body">
          <p>Give it a name and paste the key. If it's for AI models, add the service's API address too, and Nova lists its models to pick from. Nova recognizes names like Jev, OpenAI or Groq and puts those keys where they belong.</p>
          <form className="p-mg-other" onSubmit={submit}>
            <input className="p-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Name, like Jev or Together" aria-label="Key name" />
            <input className="p-input" type="password" autoComplete="off" value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} placeholder="The key" aria-label="Key" />
            <input className="p-input" value={form.api_base} onChange={(e) => setForm({ ...form, api_base: e.target.value })} placeholder="API address, if it's for models (like https://api.together.xyz/v1)" aria-label="API address (optional)" />
            <div className="p-acts"><button className="p-sm dark" disabled={!form.name.trim() || !form.key.trim() || Boolean(busy)}>{busy === "save" ? "Checking…" : "Save key"}</button></div>
          </form>
          {models?.ids?.length > 0 && (
            <>
              <div className="p-pick" role="listbox" aria-multiselectable="true" aria-label="Models to add">
                {models.ids.slice(0, 150).map((id) => (
                  <button key={id} role="option" aria-selected={pick.has(id)} onClick={() => setPick((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; })}>
                    <span className="mono">{id}</span>{pick.has(id) && <Icon name="check" size={14} />}
                  </button>
                ))}
              </div>
              <div className="p-acts"><button className="p-sm dark" onClick={add} disabled={!pick.size || busy === "add"}>{busy === "add" ? "Adding…" : `Add ${pick.size} model${pick.size === 1 ? "" : "s"}`}</button></div>
            </>
          )}
          {msg && <p className="note">{msg}</p>}
          {saved.length > 0 && (
            <div className="p-mg-saved">
              <div className="note">Saved keys (only names are shown)</div>
              {saved.map((k) => (
                <div key={k.env} className="p-row" style={{ borderTop: 0, padding: "4px 0" }}>
                  <span>{k.name}<small className="mono">{k.env}</small></span>
                  <button className="p-link" aria-label={`Remove ${k.name}`} onClick={async () => { await call(`/keys/custom/${k.env}`, { method: "DELETE" }); loadSaved(); }}><Icon name="trash" size={14} /></button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
