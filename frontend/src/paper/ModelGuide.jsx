// A beginner's guide to giving Nova models: every option, what it costs, its
// real status on this computer (app/model_catalog.py), and the steps to set
// it up right here -- paste a key and pick models, download a starter model,
// or copy an install command. Used by onboarding and Settings > Models.
import { useCallback, useEffect, useRef, useState } from "react";
import { BACKEND_URL, createCustomModel, discoverCustomModels, pullOllamaModel, saveSettings } from "../api.js";
import Icon from "./icons.jsx";
import OtherKey from "./OtherKey.jsx";

const openLink = (url) => (window.electronAPI?.openLink ? window.electronAPI.openLink(url) : window.open(url, "_blank"));
const STATE = {
  ready: ["tested", "ready"], running: ["experimental", "running, add its models"], installed: ["experimental", "installed, not running"],
  not_installed: ["browse", "not set up"], needs_key: ["browse", "not set up"],
};
// A few models to tick first when a service lists dozens.
const PREFER = /(llama-3\.3-70b|llama-3\.1-8b|gpt-4\.1-mini|gpt-4o-mini|gpt-4\.1$|claude-(sonnet|haiku)|deepseek-(chat|reasoner)|mistral-(small|large)-latest|grok-[34]|qwen|gemma)/i;

function KeySetup({ p, onDone, preview }) {
  const [key, setKey] = useState("");
  const [found, setFound] = useState(null);
  const [pick, setPick] = useState(() => new Set());
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const direct = p.setting; // OpenRouter and Gemini keys are Nova settings

  async function saveDirect(e) {
    e.preventDefault();
    if (preview) { setMsg("In preview nothing is saved."); return; }
    setBusy("save"); setMsg("");
    try { await saveSettings(p.setting === "openrouter" ? { openrouterApiKey: key.trim() } : { geminiApiKey: key.trim() }); setKey(""); setMsg("Saved. Nova can use these models now."); onDone(); }
    catch (err) { setMsg(err.message); } finally { setBusy(""); }
  }
  async function find(e) {
    e.preventDefault();
    setBusy("find"); setMsg(""); setFound(null);
    try {
      const ids = await discoverCustomModels(p.api_base, key.trim());
      setFound(ids);
      setPick(new Set(ids.filter((id) => PREFER.test(id)).slice(0, 3).concat(ids.length && !ids.some((id) => PREFER.test(id)) ? [ids[0]] : [])));
      if (!ids.length) setMsg("The key worked, but that service listed no models.");
    } catch (err) { setMsg(`That didn't work: ${err.message}`); } finally { setBusy(""); }
  }
  async function add() {
    if (preview) { setMsg("In preview nothing is saved."); return; }
    setBusy("add"); setMsg("");
    try {
      for (const id of pick) await createCustomModel({ name: `${p.name} · ${id.split("/").pop()}`, provider: "custom", modelId: id, category: "general_writing", apiBase: p.api_base, apiKey: key.trim() });
      setMsg(`Added ${pick.size} model${pick.size === 1 ? "" : "s"}.`);
      setKey(""); setFound(null); onDone();
    } catch (err) { setMsg(err.message); } finally { setBusy(""); }
  }

  return (
    <div className="p-mg-set">
      <form className="p-inline" onSubmit={direct ? saveDirect : find}>
        <input className="p-input" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder={`Paste your ${p.name} key`} aria-label={`${p.name} key`} />
        <button className="p-sm dark" disabled={!key.trim() || Boolean(busy)}>{busy === "save" ? "Saving…" : busy === "find" ? "Checking…" : direct ? "Save key" : "Check key"}</button>
      </form>
      {found?.length > 0 && (
        <>
          <div className="note">Pick the models to use. You can change this later in Settings, Models.</div>
          <div className="p-pick" role="listbox" aria-multiselectable="true" aria-label={`${p.name} models`}>
            {found.slice(0, 150).map((id) => (
              <button key={id} role="option" aria-selected={pick.has(id)} onClick={() => setPick((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; })}>
                <span className="mono">{id}</span>{pick.has(id) && <Icon name="check" size={14} />}
              </button>
            ))}
          </div>
          <div className="p-acts"><button className="p-sm dark" onClick={add} disabled={!pick.size || busy === "add"}>{busy === "add" ? "Adding…" : `Add ${pick.size} model${pick.size === 1 ? "" : "s"}`}</button></div>
        </>
      )}
      {msg && <p className="note">{msg}</p>}
    </div>
  );
}

function LocalSetup({ p, onDone, preview }) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(null);
  const [msg, setMsg] = useState("");
  async function starter() {
    if (preview) { setMsg("In preview nothing is downloaded."); return; }
    setBusy(true); setMsg(""); setProgress({ status: "starting…" });
    try {
      await pullOllamaModel({ name: "llama3.2:3b", category: "general_writing", displayName: "Llama 3.2 (3B)" }, (ev) => {
        if (ev.type === "progress") setProgress(ev);
        if (ev.type === "error") setMsg(ev.message);
      });
      setMsg("Downloaded. Nova can use it now, even offline."); onDone();
    } catch (err) { setMsg(err.message); } finally { setBusy(false); setProgress(null); }
  }
  async function addLmStudio() {
    setBusy(true); setMsg("");
    try {
      const ids = await discoverCustomModels(p.api_base, "");
      if (preview) { setMsg(`Found ${ids.length}. In preview nothing is added.`); return; }
      for (const id of ids.slice(0, 5)) await createCustomModel({ name: `LM Studio · ${id}`, provider: "custom", modelId: id, category: "general_writing", apiBase: p.api_base, apiKey: "" });
      setMsg(`Added ${Math.min(5, ids.length)} model${ids.length === 1 ? "" : "s"}.`); onDone();
    } catch (err) { setMsg(`LM Studio didn't answer: ${err.message}`); } finally { setBusy(false); }
  }
  return (
    <div className="p-mg-set">
      <div className="p-acts">
        {p.id === "ollama" && p.state !== "not_installed" && <button className="p-sm dark" onClick={starter} disabled={busy}>{busy ? "Downloading…" : "Download a starter model (2 GB)"}</button>}
        {p.id === "lmstudio" && p.state === "running" && <button className="p-sm dark" onClick={addLmStudio} disabled={busy}>{busy ? "Adding…" : "Add its models"}</button>}
      </div>
      {progress && <div className="note">{progress.status}{progress.total ? ` · ${Math.round((progress.completed / progress.total) * 100)}%` : ""}
        {progress.total ? <div className="p-bar"><i style={{ width: `${Math.min(100, (progress.completed / progress.total) * 100)}%` }} /></div> : null}</div>}
      {msg && <p className="note">{msg}</p>}
    </div>
  );
}

function AppSetup({ p }) {
  const [copied, setCopied] = useState(false);
  if (!p.command) return null;
  return (
    <div className="p-mg-cmd">
      <code>{p.command}</code>
      <button className="p-sm" onClick={() => navigator.clipboard.writeText(p.command).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); })}><Icon name="copy" />{copied ? "Copied" : "Copy"}</button>
    </div>
  );
}

export default function ModelGuide({ preview = false, onChanged, compact = false }) {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);
  // The callback is read through a ref so a parent passing a fresh function
  // each render doesn't make this reload forever.
  const changed = useRef(onChanged);
  changed.current = onChanged;
  const load = useCallback(() => fetch(`${BACKEND_URL}/models/providers`).then((r) => r.json()).then((d) => { setData(d); changed.current?.(d.ready_models); }).catch(() => setData({ providers: [], groups: {}, ready_models: 0 })), []);
  useEffect(() => { load(); }, [load]);
  if (!data) return <div className="note">Checking which models this computer has…</div>;
  const groups = Object.entries(data.groups || {});
  const ready = data.ready_models;

  return (
    <div className={`p-mg${compact ? " compact" : ""}`}>
      <div className={`p-mg-sum${ready ? " ok" : ""}`}>
        <b>{ready}</b>
        <span>{ready ? `model${ready === 1 ? "" : "s"} ready to use` : "No models yet. Nova needs at least one to answer."}</span>
        <button className="p-link" onClick={load}><Icon name="refresh" size={13} /> Check again</button>
      </div>
      <details className="p-mg-help" open={!ready}>
        <summary>Which should I pick?</summary>
        <ul>
          <li><b>Just starting:</b> get a free <b>OpenRouter</b> key. It takes about two minutes and gives Nova many free models.</li>
          <li><b>Want everything private and offline:</b> install <b>Ollama</b> and download a starter model. It needs a few GB of space.</li>
          <li><b>Already pay for ChatGPT or Claude:</b> set up <b>Codex</b> or <b>Claude Code</b> and Nova uses your subscription.</li>
          <li><b>More is better:</b> each one you add gives Nova another model to choose from. With four, Workspace unlocks and they work as a team.</li>
        </ul>
        <p className="note">A key is like a password for that service. Nova keeps it on this computer and never shows it again.</p>
      </details>
      {groups.map(([gid, gname]) => (
        <div key={gid} className="p-mg-group">
          <div className="muted">{gname}</div>
          {data.providers.filter((p) => p.group === gid).map((p) => {
            const [cls, label] = STATE[p.state] || STATE.needs_key;
            const isOpen = open === p.id;
            return (
              <div key={p.id} className={`p-mg-card${isOpen ? " open" : ""}`}>
                <button className="head" onClick={() => setOpen(isOpen ? null : p.id)} aria-expanded={isOpen}>
                  <span className="t"><b>{p.name}</b><small>{p.cost}</small></span>
                  <span className={`p-status ${cls}`}>{p.state === "ready" && p.count > 1 ? `${p.count} ready` : label}</span>
                  <svg className="car" viewBox="0 0 12 12" aria-hidden="true"><path d="M4 2l4 4-4 4" /></svg>
                </button>
                {isOpen && (
                  <div className="body">
                    <p>{p.about}</p>
                    {p.note && <p className="note">{p.note}</p>}
                    <ol>{p.steps.map((s) => <li key={s}>{s}</li>)}</ol>
                    <div className="p-acts">
                      <button className="p-sm" onClick={() => openLink(p.link)}><Icon name="open" />Open {new URL(p.link).hostname.replace(/^www\./, "")}</button>
                      {p.kind !== "key" && <button className="p-sm" onClick={load}><Icon name="refresh" />Check again</button>}
                    </div>
                    {p.kind === "key" && <KeySetup p={p} preview={preview} onDone={load} />}
                    {p.kind === "local" && <LocalSetup p={p} preview={preview} onDone={load} />}
                    {p.kind === "app" && <AppSetup p={p} />}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}
      <div className="p-mg-group">
        <div className="muted">Something else</div>
        <OtherKey preview={preview} onDone={load} />
      </div>
    </div>
  );
}
