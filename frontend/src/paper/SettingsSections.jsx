// Settings sections in the Paper interface. Every control here talks to the
// same backend endpoints the old settings window used; nothing is simulated.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  BACKEND_URL, addFileRoot, createAcpAgent, createCustomModel, createMcpServer, createSkill, createTtsVoice,
  connectAcpAgent, deleteAcpAgent, deleteCustomModel, deleteMcpServer, deleteSecret, deleteSkill, deleteTtsVoice,
  disconnectAppleCalendar, discoverCustomModels, getAppleCalendarStatus, getCanvasStatus, getCapabilities,
  getRoutingOverrides, getSettings, getSpendBreakdown, getTypeSafeStatus, listAcpAgents, listAppleCalendars,
  listFileRoots, listMcpServers, listModels, listRoutingCategories, listSecrets, listSkills, listTtsVoices,
  pullOllamaModel, putSecret, removeFileRoot, runCanvasSync, saveAppleCalendarCredentials, saveCanvasCredentials,
  saveCanvasFeed, saveCanvasSettings, saveSettings, saveTypeSafeKey, searchOpenRouterModels, setRoutingOverride,
  textToSpeech, toggleAcpAgent, toggleMcpServer, toggleModel,
} from "../api.js";
import { playTtsAudio, stopTtsAudio } from "../lib/ttsPlayback.js";
import Icon from "./icons.jsx";
import { readyModels, WORKSPACE_MIN_MODELS } from "./models.js";
import { addHomeworkSource, discoverHomework, homeworkSources, removeHomeworkSource, signInHomeworkSource } from "./paperApi.js";
import { useUi } from "./ui.jsx";
import { IS_WINDOWS } from "./keys.js";

/* ---- building blocks -------------------------------------------------- */

export function Switch({ on, onChange, label }) {
  return <button className="p-switch" role="switch" aria-checked={Boolean(on)} aria-label={label} onClick={() => onChange(!on)} />;
}

export function Row({ label, desc, children, top }) {
  return (
    <div className={`p-row${top ? " top" : ""}`}>
      <span>{label}{desc && <small>{desc}</small>}</span>
      <div className="ctl">{children}</div>
    </div>
  );
}

export function Seg({ value, options, onChange, label }) {
  return (
    <div className="p-seg" role="group" aria-label={label}>
      {options.map(([id, name]) => <button key={id} aria-pressed={value === id} onClick={() => onChange(id)}>{name}</button>)}
    </div>
  );
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

const truthy = (v) => v === true || v === "1" || v === 1;
const money = (n) => (n < 0.01 ? "under $0.01" : `$${n.toFixed(2)}`);

/* ---- Models, keys and adding models ----------------------------------- */

const CATEGORIES = ["general_writing", "reasoning_math", "agentic_planning", "frontend_ui_code", "multilingual", "long_context", "quick_simple", "vision_multimodal", "design_review", "homework"];
const API_PRESETS = [
  ["OpenAI", "https://api.openai.com/v1"], ["Anthropic", "https://api.anthropic.com/v1"],
  ["Gemini", "https://generativelanguage.googleapis.com/v1beta/openai"], ["Groq", "https://api.groq.com/openai/v1"],
  ["DeepSeek", "https://api.deepseek.com/v1"], ["Mistral", "https://api.mistral.ai/v1"], ["Cerebras", "https://api.cerebras.ai/v1"],
  ["xAI", "https://api.x.ai/v1"], ["NVIDIA NIM", "https://integrate.api.nvidia.com/v1"], ["Hugging Face", "https://router.huggingface.co/v1"],
  ["GitHub Models", "https://models.github.ai/inference"], ["Custom", ""],
];
const LOCAL_PRESETS = [["Ollama", "http://localhost:11434/v1"], ["LM Studio", "http://localhost:1234/v1"], ["vLLM", "http://localhost:8000/v1"], ["FreeLLMAPI", "http://localhost:3001/v1"]];

function KeyField({ label, desc, configured, placeholder, onSave, verify }) {
  const ui = useUi();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function save() {
    setBusy(true); setErr("");
    try { await onSave(value.trim()); setValue(""); ui.toast(`${label} saved${verify ? " and checked" : ""}.`); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <div className="p-keyrow">
      <div className="t"><b>{label}</b><span className={`p-status ${configured ? "tested" : "unsupported"}`}>{configured ? "saved" : "not set"}</span></div>
      {desc && <small>{desc}</small>}
      <form className="p-inline" onSubmit={(e) => { e.preventDefault(); if (value.trim()) save(); }}>
        <input className="p-input" type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)}
          placeholder={configured ? "•••••••• saved. Paste a new key to replace it" : placeholder} aria-label={`${label} key`} />
        <button className="p-sm dark" disabled={busy || !value.trim()}>{busy ? "Checking…" : "Save"}</button>
      </form>
      {err && <p className="err">{err}</p>}
    </div>
  );
}

function AddModel({ onAdded }) {
  const ui = useUi();
  const [kind, setKind] = useState("openrouter");
  const [form, setForm] = useState({ name: "", modelId: "", category: "general_writing", apiBase: "", apiKey: "" });
  const [query, setQuery] = useState("");
  const [orModels, setOrModels] = useState([]);
  const [found, setFound] = useState(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [pull, setPull] = useState({ name: "", status: null });
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  useEffect(() => {
    if (kind !== "openrouter") return undefined;
    const t = setTimeout(() => searchOpenRouterModels(query).then((r) => setOrModels(Array.isArray(r) ? r : [])).catch(() => setOrModels([])), 250);
    return () => clearTimeout(t);
  }, [kind, query]);

  async function add() {
    setBusy("add"); setErr("");
    try {
      await createCustomModel(kind === "openrouter"
        ? { name: form.name.trim() || form.modelId.trim(), provider: "openrouter", modelId: form.modelId.trim(), category: form.category }
        : { name: form.name.trim() || form.modelId.trim(), provider: "custom", modelId: form.modelId.trim(), category: form.category, apiBase: form.apiBase.trim(), apiKey: form.apiKey.trim() });
      ui.toast(`Added ${form.name.trim() || form.modelId.trim()}.`);
      set({ name: "", modelId: "" });
      onAdded();
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  }
  async function discover() {
    setBusy("find"); setErr(""); setFound(null);
    try { const ids = await discoverCustomModels(form.apiBase.trim(), form.apiKey.trim()); setFound(ids); if (!ids.length) setErr("That address answered but listed no models."); }
    catch (e) { setErr(e.message); } finally { setBusy(""); }
  }
  async function pullOllama() {
    setBusy("pull"); setErr(""); setPull((p) => ({ ...p, status: { status: "starting…" } }));
    try {
      await pullOllamaModel({ name: pull.name.trim(), category: form.category, displayName: form.name.trim() || pull.name.trim() }, (ev) => {
        if (ev.type === "progress") setPull((p) => ({ ...p, status: ev }));
        if (ev.type === "error") setErr(ev.message);
      });
      ui.toast(`Downloaded ${pull.name.trim()}.`);
      setPull({ name: "", status: null });
      onAdded();
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  }

  const canAdd = form.modelId.trim() && (kind === "openrouter" || form.apiBase.trim());
  return (
    <div className="p-card flat">
      <div className="head"><i>Add a model</i><span /></div>
      <Seg value={kind} onChange={(k) => { setKind(k); setFound(null); setErr(""); }} label="Kind of model"
        options={[["openrouter", "OpenRouter"], ["api", "API key"], ["local", "On this computer"]]} />
      {kind === "openrouter" && (
        <>
          <label className="p-pill wide"><Icon name="search" /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search OpenRouter's free models: qwen, deepseek, llama…" aria-label="Search OpenRouter models" /></label>
          <div className="p-pick" role="listbox" aria-label="OpenRouter models">
            {orModels.slice(0, 60).map((m) => (
              <button key={m.id} role="option" aria-selected={form.modelId === m.id} onClick={() => set({ modelId: m.id, name: form.name || m.name })}>
                <span>{m.name}</span><small>{m.id}</small>
              </button>
            ))}
            {!orModels.length && <div className="note">No matching free models right now.</div>}
          </div>
        </>
      )}
      {kind === "api" && (
        <>
          <div className="p-chips">{API_PRESETS.map(([n, base]) => (
            <button key={n} className="p-chip" aria-pressed={form.apiBase === base && (base || n === "Custom")} onClick={() => { set({ apiBase: base, name: form.name || (base ? n : "") }); setFound(null); }}>{n}</button>
          ))}</div>
          <input className="p-input" value={form.apiBase} onChange={(e) => { set({ apiBase: e.target.value }); setFound(null); }} placeholder="API address, like https://api.openai.com/v1" aria-label="API address" />
          <input className="p-input" type="password" autoComplete="off" value={form.apiKey} onChange={(e) => set({ apiKey: e.target.value })} placeholder="API key" aria-label="API key" />
        </>
      )}
      {kind === "local" && (
        <>
          <div className="p-inline">
            <input className="p-input" value={pull.name} onChange={(e) => setPull((p) => ({ ...p, name: e.target.value }))} placeholder="Download from Ollama: llama3.2, qwen3:8b, mistral…" aria-label="Ollama model to download" />
            <button className="p-sm dark" onClick={pullOllama} disabled={busy === "pull" || !pull.name.trim()}>{busy === "pull" ? "Downloading…" : "Download and add"}</button>
          </div>
          {pull.status && (
            <div className="note">{pull.status.status}{pull.status.total ? ` · ${Math.round((pull.status.completed / pull.status.total) * 100)}%` : ""}
              {pull.status.total ? <div className="p-bar"><i style={{ width: `${Math.min(100, (pull.status.completed / pull.status.total) * 100)}%` }} /></div> : null}</div>
          )}
          <div className="muted" style={{ fontSize: 13 }}>Or connect a local server</div>
          <div className="p-chips">{LOCAL_PRESETS.map(([n, base]) => (
            <button key={n} className="p-chip" aria-pressed={form.apiBase === base} onClick={() => { set({ apiBase: base, name: form.name || n }); setFound(null); }}>{n}</button>
          ))}</div>
          <input className="p-input" value={form.apiBase} onChange={(e) => { set({ apiBase: e.target.value }); setFound(null); }} placeholder="Local address, like http://localhost:11434/v1" aria-label="Local server address" />
        </>
      )}
      {kind !== "openrouter" && (
        <>
          <div className="p-inline">
            <button className="p-sm" onClick={discover} disabled={busy === "find" || !form.apiBase.trim()}>{busy === "find" ? "Looking…" : "Find its models"}</button>
            {found && <span className="note">{found.length} found</span>}
          </div>
          {found?.length > 0 && (
            <div className="p-pick" role="listbox" aria-label="Models at that address">
              {found.slice(0, 120).map((id) => <button key={id} role="option" aria-selected={form.modelId === id} onClick={() => set({ modelId: id })}><span className="mono">{id}</span></button>)}
            </div>
          )}
        </>
      )}
      <div className="p-grid2">
        <input className="p-input" value={form.modelId} onChange={(e) => set({ modelId: e.target.value })} placeholder="Model id" aria-label="Model id" />
        <input className="p-input" value={form.name} onChange={(e) => set({ name: e.target.value })} placeholder="Name (optional)" aria-label="Display name" />
      </div>
      <Row label="Best at" desc="Which kind of request Nova should send it">
        <select className="p-sm" value={form.category} onChange={(e) => set({ category: e.target.value })} aria-label="Best at">
          {CATEGORIES.map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
        </select>
      </Row>
      {err && <p className="err">{err}</p>}
      <div className="p-acts"><button className="p-sm dark" onClick={add} disabled={busy === "add" || !canAdd}>{busy === "add" ? "Adding…" : "Add model"}</button></div>
    </div>
  );
}

export function ModelsSection({ prefs, onChanged }) {
  const ui = useUi();
  const [models, setModels] = useState(null);
  const [ready, setReady] = useState(null);
  const [keys, setKeys] = useState({});
  const [jev, setJev] = useState(null);
  const [filter, setFilter] = useState("");
  const [all, setAll] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const list = await listModels();
      setModels(Array.isArray(list) ? list : []);
      setReady((await readyModels()).length);
    } catch (e) { setError(e.message); setModels([]); }
  }, []);
  useEffect(() => {
    load();
    getSettings().then(setKeys).catch(() => {});
    getTypeSafeStatus().then(setJev).catch(() => setJev(null));
  }, [load]);

  async function toggle(m) {
    setModels((list) => list.map((x) => (x.id === m.id ? { ...x, enabled: !m.enabled } : x)));
    try { await toggleModel(m.id, !m.enabled); await load(); onChanged?.(); } catch (e) { setError(e.message); load(); }
  }
  const remove = (m) => ui.undoable({
    message: `Removed ${m.name}.`,
    apply: () => setModels((list) => list.filter((x) => x.id !== m.id)),
    revert: () => load(),
    commit: async () => { await deleteCustomModel(m.id.slice("custom:".length)); onChanged?.(); },
  });

  const q = filter.trim().toLowerCase();
  const shown = (models || []).filter((m) => (all || m.enabled || m.id.startsWith("custom:") || m.provider !== "openrouter")
    && (!q || `${m.name} ${m.id} ${m.provider}`.toLowerCase().includes(q)));
  const groups = new Map();
  shown.forEach((m) => {
    const g = m.provider === "ollama" || m.id?.startsWith("ollama:") || m.provider === "hermes" ? "On this computer"
      : m.id.startsWith("custom:") ? "Added by you" : ["claude", "codex", "antigravity", "gemini_cli", "opencode"].includes(m.provider) ? "Signed-in apps" : "Cloud";
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(m);
  });

  return (
    <>
      <Section title="Models" desc={ready == null ? "Counting your models…" : ready >= WORKSPACE_MIN_MODELS
        ? `${ready} models are ready, so Workspace is unlocked.`
        : `${ready} of ${WORKSPACE_MIN_MODELS} models ready. Workspace unlocks at ${WORKSPACE_MIN_MODELS}.`}
        aside={<label className="p-pill"><Icon name="search" /><input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter models" aria-label="Filter models" /></label>}>
        <Row label="Main model" desc="Automatic picks the best model for each request">
          <select className="p-sm" value={prefs.settings.primary_model || ""} onChange={(e) => prefs.save({ primary_model: e.target.value })} aria-label="Main model">
            <option value="">Automatic</option>
            {(models || []).filter((m) => m.enabled).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </Row>
        <Row label="Prefer models on this computer" desc="Try a local model first when one fits">
          <Switch on={truthy(prefs.settings.prefer_local)} label="Prefer local models" onChange={(v) => prefs.save({ prefer_local: v })} />
        </Row>
        <Row label="Show every OpenRouter model" desc="Off shows only the ones you use">
          <Switch on={all} label="Show every OpenRouter model" onChange={setAll} />
        </Row>
        {error && <p className="err">{error}</p>}
        {models === null && <div className="note">Loading models…</div>}
        {[...groups.entries()].map(([name, rows]) => (
          <div key={name} className="p-mgroup">
            <div className="muted">{name}</div>
            {rows.map((m) => (
              <div className="p-row" key={m.id}
                onContextMenu={(e) => ui.openMenu(e, [
                  m.toggleable !== false && { label: m.enabled ? "Turn off" : "Turn on", onSelect: () => toggle(m) },
                  { label: "Copy model id", icon: "copy", onSelect: () => navigator.clipboard.writeText(m.id) },
                  m.id.startsWith("custom:") && "-",
                  m.id.startsWith("custom:") && { label: "Remove", icon: "trash", danger: true, onSelect: () => remove(m) },
                ], { title: m.name })}>
                <span>{m.name}<small>{m.availability_reason || m.category?.replace(/_/g, " ") || m.provider}</small></span>
                <div className="ctl">
                  {m.id.startsWith("custom:") && <button className="p-link" onClick={() => remove(m)} aria-label={`Remove ${m.name}`} title="Remove"><Icon name="trash" size={14} /></button>}
                  {m.toggleable === false
                    ? <span className="p-status browse">{m.enabled ? "always on" : "unavailable"}</span>
                    : <Switch on={m.enabled} label={`Use ${m.name}`} onChange={() => toggle(m)} />}
                </div>
              </div>
            ))}
          </div>
        ))}
      </Section>
      <Section title="API keys" desc="Kept on this computer in Nova's settings file, never shown again after saving.">
        <KeyField label="OpenRouter" desc="Hundreds of models, many free. openrouter.ai, Keys" configured={keys.openrouter_configured} placeholder="sk-or-…"
          onSave={async (k) => setKeys(await saveSettings({ openrouterApiKey: k }))} />
        <KeyField label="Google Gemini" desc="aistudio.google.com, Get API key" configured={keys.gemini_configured} placeholder="AIza…"
          onSave={async (k) => setKeys(await saveSettings({ geminiApiKey: k }))} />
        <KeyField label="TypeSafe (Jev)" verify desc="Sharpens how Nova decides which model answers. When Jev is unsure, Nova uses its built-in rules." configured={jev?.configured} placeholder="TypeSafe key"
          onSave={async (k) => setJev(await saveTypeSafeKey(k))} />
      </Section>
      <AddModel onAdded={() => { load(); onChanged?.(); }} />
    </>
  );
}

export function RoutingSection() {
  const [cats, setCats] = useState([]);
  const [over, setOver] = useState({});
  const [models, setModels] = useState([]);
  const [busy, setBusy] = useState(null);
  useEffect(() => {
    listRoutingCategories().then(setCats).catch(() => {});
    getRoutingOverrides().then(setOver).catch(() => {});
    listModels().then((m) => setModels((m || []).filter((x) => x.enabled))).catch(() => {});
  }, []);
  async function pick(cat, id) {
    setBusy(cat);
    try { setOver(await setRoutingOverride(cat, id || null)); } finally { setBusy(null); }
  }
  return (
    <Section title="Routing" desc="Nova picks a model for each kind of request. Pin one here to always use it for that kind; Automatic keeps Nova's own choice.">
      {cats.map((c) => (
        <Row key={c} label={c.replace(/_/g, " ").replace(/^\w/, (x) => x.toUpperCase())}>
          <select className="p-sm" value={over[c] || ""} disabled={busy === c} onChange={(e) => pick(c, e.target.value)} aria-label={`Model for ${c}`}>
            <option value="">Automatic</option>
            {models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </Row>
      ))}
      {!cats.length && <div className="note">Loading…</div>}
    </Section>
  );
}

/* ---- Autonomy --------------------------------------------------------- */

const LEVELS = [
  ["readonly", "Read only", "Nova reads, searches and answers, but changes nothing on your computer or the web."],
  ["guarded", "Ask first", "Nova asks before each action that changes something."],
  ["full", "Trusted", "Nova acts without asking each time. Payments, sending messages and essay submissions still ask."],
];
const SPEEDS = [[0, "Instant"], [0.25, "Quick"], [0.45, "Normal"], [0.9, "Easy to follow"]];

export function AutonomySection({ prefs }) {
  const s = prefs.settings;
  const level = s.autonomy_level || "guarded";
  const [caps, setCaps] = useState(null);
  const [showTools, setShowTools] = useState(false);
  useEffect(() => { getCapabilities().then(setCaps).catch(() => setCaps(null)); }, []);
  const speed = typeof s.desktop_click_seconds === "number" ? s.desktop_click_seconds : 0.45;
  return (
    <>
      <Section title="Autonomy" desc={IS_WINDOWS ? "How much Nova may do on its own. Stop always works: Ctrl+Alt+Esc, the Agents screen, or throw your mouse into a screen corner." : "How much Nova may do on its own. Stop always works from the Agents screen."}>
        <div className="p-modes" role="group" aria-label="Autonomy">
          {LEVELS.map(([id, name, note]) => (
            <button key={id} className="p-mode" aria-pressed={level === id} onClick={() => prefs.save({ autonomy_level: id })}>
              <span>{name}<small>{note}</small></span>
            </button>
          ))}
        </div>
        <Row label="Let Nova use tools" desc="Off makes Nova a plain chat: it can talk about your files but not open or change them">
          <Switch on={s.agent_tools_enabled !== false} label="Let Nova use tools" onChange={(v) => prefs.save({ agent_tools_enabled: v })} />
        </Row>
      </Section>
      <Section title="Nova's cursor" desc="With its own pointer, Nova clicks through apps without moving your mouse, so you can keep working or gaming. It never clicks into a fullscreen game.">
        <Row label="Pointer">
          <Seg value={s.desktop_pointer || "own"} onChange={(v) => prefs.save({ desktop_pointer: v })} label="Pointer" options={[["own", "Nova's own"], ["real", "Move my mouse"]]} />
        </Row>
        {(s.desktop_pointer || "own") === "own" && (
          <Row label="When an app only listens to your real mouse" desc={(s.desktop_borrow_mouse || "ask") === "never" ? "Nova says it couldn't click and never touches your mouse." : "Nova asks first; your mouse jumps there, clicks, and comes straight back."}>
            <Seg value={s.desktop_borrow_mouse === "never" ? "never" : "ask"} onChange={(v) => prefs.save({ desktop_borrow_mouse: v })} label="Borrow the mouse" options={[["ask", "Ask me"], ["never", "Never"]]} />
          </Row>
        )}
        <Row label="How fast it moves">
          <Seg value={SPEEDS.reduce((best, [v]) => (Math.abs(v - speed) < Math.abs(best - speed) ? v : best), 0.45)} onChange={(v) => prefs.save({ desktop_click_seconds: v })} label="Pointer speed"
            options={SPEEDS} />
        </Row>
        <Row label="Mark the spot before clicking" desc="A ring shows where the click lands; clicks pass through it">
          <Switch on={s.desktop_click_marker !== false} label="Mark the spot before clicking" onChange={(v) => prefs.save({ desktop_click_marker: v })} />
        </Row>
      </Section>
      {caps && (
        <Section title="Tools" desc={`${caps.tools.length} tools available now${caps.background_processes?.length ? ` · ${caps.background_processes.length} running in the background` : ""}. The ones that change something follow the level above.`}
          aside={<button className="p-link" onClick={() => setShowTools((x) => !x)}>{showTools ? "Hide" : "Show all"}</button>}>
          {showTools && <div className="p-chips">{caps.tools.map((t) => <span key={t.name} className={`p-chip static${t.mutating ? " warn" : ""}`} title={t.description}>{t.name}</span>)}</div>}
        </Section>
      )}
    </>
  );
}

/* ---- Voice ------------------------------------------------------------ */

export function VoiceSection({ prefs }) {
  const ui = useUi();
  const s = prefs.settings;
  const [voices, setVoices] = useState(null);
  const [playing, setPlaying] = useState(null);
  const [clone, setClone] = useState({ name: "", file: null });
  const [busy, setBusy] = useState(false);
  const [hotkey, setHotkey] = useState(s.push_to_talk_hotkey || "");
  const [hotErr, setHotErr] = useState("");
  const fileRef = useRef(null);
  const load = () => listTtsVoices().then(setVoices).catch(() => setVoices([]));
  useEffect(() => { load(); return () => stopTtsAudio(); }, []);
  useEffect(() => { setHotkey(s.push_to_talk_hotkey || ""); }, [s.push_to_talk_hotkey]);

  const current = s.tts_voice_id || "default";
  async function preview(v) {
    if (playing === v.id) { stopTtsAudio(); setPlaying(null); return; }
    setPlaying(v.id);
    try {
      const blob = await textToSpeech(`Hi, I'm Nova. This is the ${v.name.split(" · ")[0]} voice.`, v.id);
      await playTtsAudio(blob, { onEnd: () => setPlaying((p) => (p === v.id ? null : p)) });
    } catch (e) { setPlaying(null); ui.toast(`Couldn't play it: ${e.message}`, { error: true }); }
  }
  async function addClone() {
    setBusy(true);
    try {
      const created = await createTtsVoice(clone.name.trim(), clone.file);
      setClone({ name: "", file: null });
      if (fileRef.current) fileRef.current.value = "";
      await load();
      prefs.save({ tts_voice_id: String(created.id) });
      ui.toast("Voice cloned and selected.");
    } catch (e) { ui.toast(e.message, { error: true }); } finally { setBusy(false); }
  }
  const removeClone = (v) => ui.undoable({
    message: `Deleted the voice "${v.name}".`,
    apply: () => { setVoices((all) => all.filter((x) => x.id !== v.id)); if (current === v.id) prefs.save({ tts_voice_id: "default" }); },
    revert: load,
    commit: () => deleteTtsVoice(v.id),
  });
  async function applyHotkey() {
    setHotErr("");
    const result = await window.electronAPI?.registerPushToTalkHotkey?.(hotkey.trim());
    if (result && !result.success) { setHotErr(result.error || "Couldn't use that shortcut."); return; }
    prefs.save({ push_to_talk_hotkey: hotkey.trim() });
    ui.toast("Push-to-talk shortcut set.");
  }

  const groups = [["online", "Natural voices", "Need an internet connection. If it drops, Nova uses the offline voice when it's installed."], ["offline", "Offline voices", "Run on this computer."], ["cloned", "Your cloned voices", "Made from a clip you gave Nova. Slower to speak."]];
  return (
    <>
      <Section title="Voice">
        <Row label="Speak Nova's replies" desc="Nova says each answer out loud, and the reactor moves with its voice">
          <Switch on={truthy(s.voice_replies)} label="Speak Nova's replies" onChange={(v) => prefs.save({ voice_replies: v })} />
        </Row>
        <Row label="Short spoken summaries" desc="Speak one sentence instead of reading the whole reply">
          <Switch on={truthy(s.speak_summary_only)} label="Short spoken summaries" onChange={(v) => prefs.save({ speak_summary_only: v })} />
        </Row>
        <Row label="Stop talking when I type">
          <Switch on={truthy(s.duck_on_type)} label="Stop talking when I type" onChange={(v) => prefs.save({ duck_on_type: v })} />
        </Row>
        <Row label="Push-to-talk shortcut" desc="Works anywhere in Windows. Like Alt+Shift+Space">
          <form className="p-inline" onSubmit={(e) => { e.preventDefault(); applyHotkey(); }}>
            <input className="p-input mono" value={hotkey} onChange={(e) => setHotkey(e.target.value)} placeholder="Alt+Shift+Space" aria-label="Push-to-talk shortcut" style={{ width: 170 }} />
            <button className="p-sm" disabled={!hotkey.trim() || hotkey.trim() === s.push_to_talk_hotkey}>Set</button>
          </form>
        </Row>
        {hotErr && <p className="err">{hotErr}</p>}
      </Section>
      <Section title="Nova's voice" desc="Pick one and press play to hear it.">
        {voices === null && <div className="note">Loading voices…</div>}
        {groups.map(([kind, name, note]) => {
          const rows = (voices || []).filter((v) => (v.kind === "builtin" ? "offline" : v.kind) === kind);
          if (!rows.length) return null;
          return (
            <div key={kind} className="p-mgroup">
              <div className="muted">{name}<span className="note"> · {note}</span></div>
              <div className="p-voices" role="radiogroup" aria-label={name}>
                {rows.map((v) => (
                  <div key={v.id} className={`p-voice${current === v.id ? " on" : ""}`}
                    onContextMenu={(e) => ui.openMenu(e, [
                      { label: "Use this voice", icon: "check", onSelect: () => prefs.save({ tts_voice_id: v.id }) },
                      { label: playing === v.id ? "Stop" : "Play a sample", icon: "play", onSelect: () => preview(v) },
                      v.kind === "cloned" && "-",
                      v.kind === "cloned" && { label: "Delete voice", icon: "trash", danger: true, onSelect: () => removeClone(v) },
                    ], { title: v.name })}>
                    <button role="radio" aria-checked={current === v.id} className="pick" onClick={() => prefs.save({ tts_voice_id: v.id })}>
                      <span className="dot" /><span className="n">{v.name}</span>
                    </button>
                    <button className="p-link" onClick={() => preview(v)} aria-label={playing === v.id ? `Stop ${v.name}` : `Play ${v.name}`} title={playing === v.id ? "Stop" : "Play a sample"}>
                      <Icon name={playing === v.id ? "stop" : "play"} size={14} />
                    </button>
                    {v.kind === "cloned" && <button className="p-link" onClick={() => removeClone(v)} aria-label={`Delete ${v.name}`} title="Delete"><Icon name="trash" size={14} /></button>}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </Section>
      <Section title="Clone a voice" desc="A clean clip of one person speaking, over 5 seconds, works best. Only use a voice you have permission to use.">
        <div className="p-grid2">
          <input className="p-input" value={clone.name} onChange={(e) => setClone((c) => ({ ...c, name: e.target.value }))} placeholder="Name for the voice" aria-label="Voice name" />
          <input ref={fileRef} className="p-input" type="file" accept="audio/*" onChange={(e) => setClone((c) => ({ ...c, file: e.target.files?.[0] || null }))} aria-label="Voice clip" />
        </div>
        <div className="p-acts"><button className="p-sm dark" onClick={addClone} disabled={busy || !clone.name.trim() || !clone.file}>{busy ? "Cloning…" : "Clone voice"}</button></div>
      </Section>
    </>
  );
}

/* ---- Canvas ----------------------------------------------------------- */

export function CanvasSection() {
  const ui = useUi();
  const [status, setStatus] = useState(null);
  const [mode, setMode] = useState("feed");
  const [feed, setFeed] = useState("");
  const [base, setBase] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [calendars, setCalendars] = useState([]);
  const load = () => getCanvasStatus().then((d) => { setStatus(d); if (d.canvas?.base_url) setBase(d.canvas.base_url); if (d.canvas?.source === "api") setMode("token"); }).catch((e) => setError(e.message));
  useEffect(() => { load(); listAppleCalendars().then(setCalendars).catch(() => setCalendars([])); }, []);

  async function save() {
    setError(""); setBusy("connect");
    try {
      if (mode === "feed") await saveCanvasFeed(feed.trim());
      else await saveCanvasCredentials(base.trim(), token.trim());
      setFeed(""); setToken("");
      await runCanvasSync().catch(() => {});
      await load();
      ui.toast("Canvas connected and synced.");
    } catch (e) { setError(e.message); } finally { setBusy(""); }
  }
  async function sync() {
    setBusy("sync");
    try { const r = await runCanvasSync(); await load(); ui.toast(`Synced ${r.seen} assignments: ${r.new?.length || 0} new.`); }
    catch (e) { setError(e.message); } finally { setBusy(""); }
  }
  async function patch(p) { try { setStatus(await saveCanvasSettings(p)); } catch (e) { setError(e.message); } }

  const c = status?.canvas || {};
  const connected = Boolean(c.any_configured || c.configured || c.feed?.configured);
  const where = c.feed?.feed_host || c.base_url || "";
  return (
    <>
      <Section title="Canvas" desc="Nova reads your courses and assignments from Canvas. Homework itself opens in Nova's browser, signed in as you.">
        {status && (
          <Row label="Status" desc={connected ? `${where || "Connected"}${c.source === "feed" ? " · calendar feed" : c.token_set ? " · access token" : ""}${status.last_run ? ` · last synced ${status.last_run}` : ""}` : "Not connected"}>
            <span className={`p-status ${connected ? "tested" : "unsupported"}`}>{connected ? "connected" : "not connected"}</span>
            {connected && <button className="p-sm" onClick={sync} disabled={busy === "sync"}>{busy === "sync" ? "Syncing…" : "Sync now"}</button>}
          </Row>
        )}
        <Seg value={mode} onChange={setMode} label="How to connect" options={[["feed", "Calendar feed"], ["token", "Access token"]]} />
        {mode === "feed" ? (
          <div className="p-stack tight">
            <p className="note">In Canvas, open Calendar, then Calendar Feed, and copy the link. Works even when your school blocks access tokens. Treat it like a password.</p>
            <input className="p-input" type="password" value={feed} onChange={(e) => setFeed(e.target.value)} placeholder={c.feed?.configured ? `•••••••• saved (${c.feed.feed_host})` : "https://school.instructure.com/feeds/calendars/…"} aria-label="Canvas calendar feed link" />
          </div>
        ) : (
          <div className="p-stack tight">
            <p className="note">Better when your school allows it: Nova also sees what you've already submitted. Canvas, Account, Settings, New access token.</p>
            <input className="p-input" value={base} onChange={(e) => setBase(e.target.value)} placeholder="https://school.instructure.com" aria-label="Canvas address" />
            <input className="p-input" type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder={c.token_set ? "•••••••• saved" : "Access token"} aria-label="Canvas access token" />
          </div>
        )}
        <div className="p-acts"><button className="p-sm dark" onClick={save} disabled={busy === "connect" || (mode === "feed" ? !feed.trim() : !(base.trim() && token.trim()))}>{busy === "connect" ? "Checking…" : connected ? "Reconnect" : "Connect"}</button></div>
        {error && <p className="err">{error}</p>}
      </Section>
      {status && (
        <Section title="Syncing and reminders">
          <Row label="Nightly sync" desc="If the computer is asleep then, Nova syncs when it wakes">
            <Switch on={status.enabled} label="Nightly sync" onChange={(v) => patch({ enabled: v })} />
          </Row>
          <Row label="Sync at"><input className="p-input" type="time" value={status.time || "02:00"} onChange={(e) => patch({ syncTime: e.target.value })} aria-label="Sync time" /></Row>
          <Row label="Hide work overdue by more than" desc="Days. 0 keeps everything">
            <input className="p-input" type="number" min={0} max={365} value={status.stale_days ?? 14} onChange={(e) => patch({ staleDays: Number(e.target.value) })} style={{ width: 80 }} aria-label="Days" />
          </Row>
          <Row label="Reminders before each due date" top>
            <div className="p-chips">
              {[72, 48, 24, 12, 6, 3, 1].map((h) => {
                const on = (status.reminder_hours || []).includes(h);
                return <button key={h} className="p-chip" aria-pressed={on} onClick={() => patch({ reminderHours: on ? status.reminder_hours.filter((x) => x !== h) : [...(status.reminder_hours || []), h] })}>{h}h</button>;
              })}
            </div>
          </Row>
          <Row label="Add assignments to Apple Calendar" desc={calendars.length ? "Updated after every sync, so they show on your iPhone" : "Connect Apple Calendar first, under Calendar"}>
            <Switch on={Boolean(status.push_to_apple)} label="Add assignments to Apple Calendar" onChange={(v) => patch({ pushToApple: v })} />
          </Row>
          {status.push_to_apple && calendars.length > 0 && (
            <Row label="Which calendar">
              <select className="p-sm" value={status.push_calendar || ""} onChange={(e) => patch({ pushCalendar: e.target.value })} aria-label="Apple calendar">
                <option value="">Choose…</option>
                {calendars.filter((x) => !x.read_only).map((x) => <option key={x.url} value={x.url}>{x.name}</option>)}
              </select>
            </Row>
          )}
          {status.calendar_path && (
            <Row label="Calendar file" desc="Subscribe to it in Outlook or Google Calendar">
              <button className="p-sm" onClick={() => navigator.clipboard.writeText(status.calendar_path).then(() => ui.toast("Path copied."))}><Icon name="copy" />Copy path</button>
            </Row>
          )}
        </Section>
      )}
    </>
  );
}

/* ---- Homework platforms ----------------------------------------------- */

const STATUS = { tested: "Tested", experimental: "Experimental", browse: "Open and read", unsupported: "Not supported" };

const LMS = ["blackboard", "brightspace", "moodle"];

function YourPlatforms({ platforms }) {
  const ui = useUi();
  const [sources, setSources] = useState(null);
  const [pick, setPick] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState("");
  const load = () => homeworkSources().then((d) => setSources(d.sources || [])).catch(() => setSources([]));
  useEffect(() => { load(); }, []);
  const choices = (platforms || []).filter((p) => p.id !== "canvas" && p.status !== "unsupported" && p.kind !== "live");
  const needsUrl = LMS.includes(pick);

  async function add() {
    setBusy("add");
    try {
      const src = await addHomeworkSource(pick || null, url.trim() || null);
      setPick(""); setUrl("");
      await load();
      ui.toast(`Added ${src.name}. Sign in once, then Nova reads it on its own.`);
    } catch (e) { ui.toast(e.message, { error: true }); } finally { setBusy(""); }
  }
  async function find(id) {
    setBusy(id || "all");
    try {
      const r = await discoverHomework(id);
      await load();
      const found = (r.platforms || []).reduce((n, x) => n + (x.found || 0), 0);
      ui.toast(found ? `Found ${found} assignment${found === 1 ? "" : "s"}. They're in Academics.` : "Nothing new found. Check each platform's note below.");
    } catch (e) { ui.toast(e.message, { error: true }); } finally { setBusy(""); }
  }
  async function signIn(src) {
    try { await signInHomeworkSource(src.id); await load(); ui.toast(`${src.name} is open in Nova's browser. Sign in there, then press Find now.`); }
    catch (e) { ui.toast(e.message, { error: true }); }
  }
  const remove = (src) => ui.undoable({
    message: `Removed ${src.name} and what Nova found there.`,
    apply: () => setSources((all) => all.filter((x) => x.id !== src.id)),
    revert: load,
    commit: () => removeHomeworkSource(src.id),
  });
  const STATE = { ok: ["tested", "reading"], needs_sign_in: ["experimental", "sign in needed"], signing_in: ["experimental", "signing in"], error: ["unsupported", "couldn't read"], new: ["browse", "not read yet"] };

  return (
    <Section title="Your platforms" desc="Add each place your professors post work. Sign in once in Nova's browser; after that Nova reads them every night with Canvas, and whenever you press Sync in Academics. Reading only: nothing is opened, answered or submitted until you ask."
      aside={sources?.length ? <button className="p-sm" onClick={() => find()} disabled={Boolean(busy)}><Icon name="refresh" />{busy === "all" ? "Reading…" : "Find assignments now"}</button> : null}>
      {sources?.length === 0 && <p className="note">None yet. Canvas is already covered.</p>}
      {(sources || []).map((src) => {
        const [cls, text] = STATE[src.last_status] || STATE.new;
        return (
          <div key={src.id} className="p-conn" onContextMenu={(e) => ui.openMenu(e, [
            { label: "Sign in", icon: "key", onSelect: () => signIn(src) },
            { label: "Find now", icon: "refresh", onSelect: () => find(src.id) },
            { label: "Copy address", icon: "copy", onSelect: () => navigator.clipboard.writeText(src.url) },
            "-", { label: "Remove", icon: "trash", danger: true, onSelect: () => remove(src) },
          ], { title: src.name })}>
            <Row label={src.name} desc={[src.last_note, src.url].filter(Boolean).join(" · ")}>
              <span className={`p-status ${cls}`}>{text}{src.last_status === "ok" ? ` · ${src.count}` : ""}</span>
              {src.last_status !== "ok" && <button className="p-sm dark" onClick={() => signIn(src)}>Sign in</button>}
              <button className="p-sm" onClick={() => find(src.id)} disabled={Boolean(busy)}>{busy === src.id ? "Reading…" : "Find now"}</button>
              <button className="p-link" onClick={() => remove(src)} aria-label={`Remove ${src.name}`} title="Remove"><Icon name="trash" size={14} /></button>
            </Row>
          </div>
        );
      })}
      <div className="p-grid2" style={{ marginTop: 10 }}>
        <select className="p-input" value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Platform">
          <option value="">Choose a platform…</option>
          {choices.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <input className="p-input" value={url} onChange={(e) => setUrl(e.target.value)} aria-label="Platform address"
          placeholder={needsUrl ? "Your school's address, like https://moodle.school.edu" : "Address (optional): your class's page if it has its own"} />
        <div className="p-acts"><button className="p-sm dark" onClick={add} disabled={busy === "add" || (!pick && !url.trim()) || (needsUrl && !url.trim())}>{busy === "add" ? "Adding…" : "Add platform"}</button></div>
      </div>
    </Section>
  );
}

export function PlatformsSection() {
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState("");
  useEffect(() => {
    fetch(`${BACKEND_URL}/homework/platforms`).then((r) => r.json()).then((d) => setRows(d.platforms || [])).catch(() => setRows([]));
  }, []);
  const shown = (rows || []).filter((p) => !q.trim() || `${p.name} ${p.vendor || ""}`.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <>
      <YourPlatforms platforms={rows} />
      <Section title="What Nova can do on each" desc="Tested means it has worked end to end on a real assignment. Experimental platforms are recognized and handled, and Nova reports exactly what it sees until they're proven. Proctored tests, lockdown browsers and live sessions always stop Nova."
        aside={<label className="p-pill"><Icon name="search" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a platform" aria-label="Find a platform" /></label>}>
        {rows === null && <div className="note">Loading…</div>}
        {shown.map((p) => (
          <Row key={p.id} label={p.name} desc={[p.vendor, p.handles?.join(", "), p.notes].filter(Boolean).join(" · ")}>
            <span className={`p-status ${p.status}`}>{STATUS[p.status] || p.status}</span>
          </Row>
        ))}
      </Section>
    </>
  );
}

/* ---- Connectors (MCP) -------------------------------------------------- */

const MCP_PRESETS = [
  { name: "Sequential Thinking", command: "npx", args: "-y @modelcontextprotocol/server-sequential-thinking", hint: "Step-by-step reasoning. No key needed" },
  { name: "Context7", command: "npx", args: "-y @upstash/context7-mcp", hint: "Current library docs. Free key at context7.com" },
  { name: "Brave Search", command: "npx", args: "-y @brave/brave-search-mcp-server --transport stdio", hint: "Web search. Free key at brave.com/search/api" },
  { name: "Memory", command: "npx", args: "-y @modelcontextprotocol/server-memory", hint: "A knowledge graph Nova can write to" },
  { name: "Filesystem", command: "npx", args: "-y @modelcontextprotocol/server-filesystem .", hint: "Read project files" },
  { name: "Vercel", url: "https://mcp.vercel.com", hint: "Deployments and logs. Sign in on first use" },
  { name: "Hugging Face", url: "https://huggingface.co/mcp", hint: "Models, datasets, Spaces" },
  { name: "Replit", url: "https://replit-mcp.com/server/mcp", hint: "Build and publish Repls. Sign in on first use" },
  { name: "Lovable", url: "https://mcp.lovable.dev", hint: "Lovable projects. Sign in on first use" },
  { name: "Figma (desktop)", url: "http://127.0.0.1:3845/mcp", hint: "Needs the Figma desktop app with Dev Mode" },
];

export function ConnectorsSection() {
  const ui = useUi();
  const [servers, setServers] = useState(null);
  const [open, setOpen] = useState(null);
  const [form, setForm] = useState({ name: "", command: "", args: "", url: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const load = () => listMcpServers().then((s) => setServers(Array.isArray(s) ? s : [])).catch(() => setServers([]));
  useEffect(() => { load(); }, []);

  async function add() {
    setBusy(true); setErr("");
    try {
      const url = form.url.trim();
      await createMcpServer(url ? { name: form.name.trim(), transport: "http", url }
        : { name: form.name.trim(), command: form.command.trim(), args: form.args.trim() ? form.args.trim().split(/\s+/) : [] });
      setForm({ name: "", command: "", args: "", url: "" });
      await load();
      ui.toast("Connector added.");
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  const remove = (s) => ui.undoable({
    message: `Removed ${s.name}.`,
    apply: () => setServers((all) => all.filter((x) => x.id !== s.id)),
    revert: load,
    commit: () => deleteMcpServer(s.id),
  });
  async function toggle(s) { setServers((all) => all.map((x) => (x.id === s.id ? { ...x, enabled: !s.enabled } : x))); await toggleMcpServer(s.id, !s.enabled); load(); }

  return (
    <>
      <Section title="Connectors" desc="Give Nova more tools with MCP servers, the same kind Claude Desktop uses. When one's tools fit a request, Nova calls them for real.">
        {servers === null && <div className="note">Loading…</div>}
        {servers?.length === 0 && <div className="note">No connectors yet.</div>}
        {(servers || []).map((s) => (
          <div key={s.id} className="p-conn" onContextMenu={(e) => ui.openMenu(e, [
            { label: s.enabled ? "Turn off" : "Turn on", onSelect: () => toggle(s) },
            { label: open === s.id ? "Hide tools" : "Show tools", onSelect: () => setOpen(open === s.id ? null : s.id) },
            "-",
            { label: "Remove", icon: "trash", danger: true, onSelect: () => remove(s) },
          ], { title: s.name })}>
            <div className="p-row" style={{ borderTop: 0 }}>
              <span><i className={`p-led ${!s.enabled ? "off" : s.connected ? "ok" : "bad"}`} />{s.name}
                <small>{!s.enabled ? "off" : s.connected ? `${s.tools.length} tool${s.tools.length === 1 ? "" : "s"}` : s.needs_auth ? "needs you to sign in" : "can't reach it"}{" · "}{s.url || `${s.command} ${(s.args || []).join(" ")}`}</small></span>
              <div className="ctl">
                {s.tools?.length > 0 && <button className="p-link" onClick={() => setOpen(open === s.id ? null : s.id)}>{open === s.id ? "Hide" : "Tools"}</button>}
                <button className="p-link" onClick={() => remove(s)} aria-label={`Remove ${s.name}`} title="Remove"><Icon name="trash" size={14} /></button>
                <Switch on={s.enabled} label={`Use ${s.name}`} onChange={() => toggle(s)} />
              </div>
            </div>
            {s.error && <p className="err">{s.error}</p>}
            {open === s.id && <div className="p-chips">{s.tools.map((t) => <span key={t.name} className="p-chip static" title={t.description}>{t.name}</span>)}</div>}
          </div>
        ))}
      </Section>
      <div className="p-card flat">
        <div className="head"><i>Add a connector</i><span /></div>
        <div className="p-chips">{MCP_PRESETS.map((p) => (
          <button key={p.name} className="p-chip" title={p.hint} onClick={() => setForm({ name: p.name, command: p.command || "", args: p.args || "", url: p.url || "" })}>+ {p.name}</button>
        ))}</div>
        <div className="p-grid2">
          <input className="p-input" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="Name" aria-label="Connector name" />
          <input className="p-input" value={form.url} onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))} placeholder="Web address, for a remote server" aria-label="Remote server address" />
          <input className="p-input mono" value={form.command} disabled={Boolean(form.url.trim())} onChange={(e) => setForm((f) => ({ ...f, command: e.target.value }))} placeholder="Or a command: npx, python" aria-label="Command" />
          <input className="p-input mono" value={form.args} disabled={Boolean(form.url.trim())} onChange={(e) => setForm((f) => ({ ...f, args: e.target.value }))} placeholder="Arguments" aria-label="Arguments" />
        </div>
        {err && <p className="err">{err}</p>}
        <div className="p-acts"><button className="p-sm dark" onClick={add} disabled={busy || !form.name.trim() || (!form.command.trim() && !form.url.trim())}>{busy ? "Connecting…" : "Add connector"}</button></div>
      </div>
    </>
  );
}

/* ---- Skills ------------------------------------------------------------ */

export function SkillsSection() {
  const ui = useUi();
  const [skills, setSkills] = useState(null);
  const [models, setModels] = useState([]);
  const [open, setOpen] = useState(null);
  const [q, setQ] = useState("");
  const [form, setForm] = useState({ name: "", description: "", keywords: "", body: "", preferredModelId: "" });
  const [busy, setBusy] = useState(false);
  const load = () => listSkills().then((s) => setSkills(Array.isArray(s) ? s : [])).catch(() => setSkills([]));
  useEffect(() => { load(); listModels().then((m) => setModels((m || []).filter((x) => x.enabled))).catch(() => {}); }, []);
  async function add() {
    setBusy(true);
    try {
      await createSkill({ ...form, name: form.name.trim(), keywords: form.keywords.split(",").map((k) => k.trim()).filter(Boolean), preferredModelId: form.preferredModelId || null });
      setForm({ name: "", description: "", keywords: "", body: "", preferredModelId: "" });
      await load();
      ui.toast("Skill added.");
    } catch (e) { ui.toast(e.message, { error: true }); } finally { setBusy(false); }
  }
  const remove = (s) => ui.undoable({ message: `Removed the ${s.name} skill.`, apply: () => setSkills((all) => all.filter((x) => x.name !== s.name)), revert: load, commit: () => deleteSkill(s.name) });
  const shown = (skills || []).filter((s) => !q.trim() || `${s.name} ${s.description} ${(s.keywords || []).join(" ")}`.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <>
      <Section title="Skills" desc="Know-how Nova pulls in only when your message matches a skill's keywords, like how a homework site works."
        aside={<label className="p-pill"><Icon name="search" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a skill" aria-label="Find a skill" /></label>}>
        {skills === null && <div className="note">Loading…</div>}
        {shown.map((s) => (
          <div key={s.name} className="p-conn" onContextMenu={(e) => ui.openMenu(e, [
            { label: open === s.name ? "Hide details" : "Show details", onSelect: () => setOpen(open === s.name ? null : s.name) },
            "-", { label: "Remove", icon: "trash", danger: true, onSelect: () => remove(s) },
          ], { title: s.name })}>
            <Row label={s.name} desc={s.description}>
              <button className="p-link" onClick={() => setOpen(open === s.name ? null : s.name)}>{open === s.name ? "Hide" : "Details"}</button>
              <button className="p-link" onClick={() => remove(s)} aria-label={`Remove ${s.name}`} title="Remove"><Icon name="trash" size={14} /></button>
            </Row>
            {open === s.name && (
              <div className="p-skillbody">
                {s.keywords?.length > 0 && <div className="note">Keywords: {s.keywords.join(", ")}</div>}
                {s.preferred_model_id && <div className="note">Prefers {s.preferred_model_id}</div>}
                <pre>{s.body}</pre>
              </div>
            )}
          </div>
        ))}
      </Section>
      <div className="p-card flat">
        <div className="head"><i>Teach Nova a skill</i><span /></div>
        <div className="p-grid2">
          <input className="p-input" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="Name, like lab-reports" aria-label="Skill name" />
          <input className="p-input" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} placeholder="What it's for" aria-label="Description" />
        </div>
        <input className="p-input" value={form.keywords} onChange={(e) => setForm((f) => ({ ...f, keywords: e.target.value }))} placeholder="Keywords that bring it in, separated by commas" aria-label="Keywords" />
        <textarea className="p-fieldarea" rows={5} value={form.body} onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))} placeholder="What Nova should do when this skill applies…" aria-label="Instructions" />
        <Row label="Preferred model">
          <select className="p-sm" value={form.preferredModelId} onChange={(e) => setForm((f) => ({ ...f, preferredModelId: e.target.value }))} aria-label="Preferred model">
            <option value="">None, route normally</option>
            {models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </Row>
        <div className="p-acts"><button className="p-sm dark" onClick={add} disabled={busy || !form.name.trim() || !form.body.trim()}>{busy ? "Adding…" : "Add skill"}</button></div>
      </div>
    </>
  );
}

/* ---- Coding agents (ACP) ---------------------------------------------- */

export function AgentsSection() {
  const ui = useUi();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(null);
  const load = () => listAcpAgents().then(setData).catch((e) => ui.toast(e.message, { error: true }));
  useEffect(() => { load(); }, []);
  const agents = data?.agents || [];
  return (
    <Section title="Coding agents" desc="Outside agents Nova can hand a whole coding job to, like Claude Code or Gemini CLI. Your Autonomy setting still applies to what they do.">
      {data === null && <div className="note">Loading…</div>}
      {agents.map((a) => (
        <div key={a.id} className="p-conn">
          <div className="p-row" style={{ borderTop: 0 }}>
            <span><i className={`p-led ${a.status?.connected ? "ok" : a.status?.installed ? "off" : "bad"}`} />{a.name}
              <small>{a.status?.connected ? "connected" : a.status?.installed ? "not connected" : "not installed"} · {a.command}</small></span>
            <div className="ctl">
              <button className="p-sm" disabled={busy === a.id} onClick={async () => { setBusy(a.id); try { await connectAcpAgent(a.id); } catch (e) { ui.toast(e.message, { error: true }); } setBusy(null); load(); }}>{busy === a.id ? "Connecting…" : a.status?.connected ? "Reconnect" : "Connect"}</button>
              <button className="p-link" aria-label={`Remove ${a.name}`} title="Remove" onClick={() => ui.undoable({ message: `Removed ${a.name}.`, apply: () => setData((d) => ({ ...d, agents: d.agents.filter((x) => x.id !== a.id) })), revert: load, commit: () => deleteAcpAgent(a.id) })}><Icon name="trash" size={14} /></button>
              <Switch on={a.enabled} label={`Use ${a.name}`} onChange={async (v) => { await toggleAcpAgent(a.id, v); load(); }} />
            </div>
          </div>
        </div>
      ))}
      {(data?.suggested || []).length > 0 && <div className="muted" style={{ marginTop: 10 }}>Add one</div>}
      <div className="p-chips">
        {(data?.suggested || []).map((p) => {
          const added = agents.some((a) => a.name === p.name);
          return <button key={p.name} className="p-chip" disabled={added} title={p.note} onClick={async () => { await createAcpAgent({ name: p.name, command: p.command, args: p.args || [] }); load(); }}>{added ? `${p.name} ✓` : `+ ${p.name}`}</button>;
        })}
      </div>
    </Section>
  );
}

/* ---- Passwords (secrets) ---------------------------------------------- */

export function SecretsSection() {
  const ui = useUi();
  const [data, setData] = useState(null);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const load = () => listSecrets().then(setData).catch((e) => ui.toast(e.message, { error: true }));
  useEffect(() => { load(); }, []);
  async function add() {
    try { await putSecret(name.trim(), value); setName(""); setValue(""); await load(); ui.toast("Saved. Nova can use it by name."); }
    catch (e) { ui.toast(e.message, { error: true }); }
  }
  return (
    <Section title="Passwords" desc="Save a password here and Nova can type it into a sign-in page by name. The value goes straight to the keyboard: it never reaches a model, the chat, or memory.">
      {data && <p className="note">Stored in {data.backend}.</p>}
      {(data?.names || []).map((n) => (
        <Row key={n} label={<span className="mono" style={{ fontSize: 13, color: "var(--tx)" }}>{n}</span>} desc="•••••••• not readable from here">
          <button className="p-sm danger" onClick={async () => { const ok = await ui.confirm({ title: `Delete "${n}"?`, body: "Nova won't be able to sign in with it anymore. This can't be undone.", confirm: "Delete", danger: true }); if (ok) { await deleteSecret(n); load(); } }}>Delete</button>
        </Row>
      ))}
      <form className="p-grid2" onSubmit={(e) => { e.preventDefault(); if (name.trim() && value) add(); }} style={{ marginTop: 10 }}>
        <input className="p-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name Nova will use, like school-login" aria-label="Password name" autoComplete="off" />
        <input className="p-input" type="password" value={value} onChange={(e) => setValue(e.target.value)} placeholder="The password" aria-label="Password" autoComplete="new-password" />
        <div className="p-acts"><button className="p-sm dark" disabled={!name.trim() || !value}>Save password</button></div>
      </form>
      <p className="note">Then ask Nova something like "sign in to the school portal with school-login".</p>
    </Section>
  );
}

/* ---- Apple Calendar ---------------------------------------------------- */

export function CalendarSection() {
  const ui = useUi();
  const [apple, setApple] = useState(null);
  const [id, setId] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => getAppleCalendarStatus().then((d) => { setApple(d); if (d.apple_id) setId(d.apple_id); }).catch(() => setApple({}));
  useEffect(() => { load(); }, []);
  async function connect() {
    setBusy(true);
    try { const r = await saveAppleCalendarCredentials(id.trim(), pw.trim()); setPw(""); setApple(r); ui.toast(`Connected: ${(r.calendars || []).length} calendars.`); }
    catch (e) { ui.toast(e.message, { error: true }); } finally { setBusy(false); }
  }
  return (
    <Section title="Apple Calendar" desc="Nova can read your iCloud calendar and add events, and they show up on your iPhone and Mac. Adding or deleting events follows your Autonomy setting.">
      <Row label="Status"><span className={`p-status ${apple?.configured ? "tested" : "unsupported"}`}>{apple?.configured ? "connected" : "not connected"}</span></Row>
      <div className="p-grid2">
        <input className="p-input" value={id} onChange={(e) => setId(e.target.value)} placeholder="Apple ID, like you@icloud.com" aria-label="Apple ID" />
        <input className="p-input mono" type="password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder={apple?.password_set ? "•••••••• saved" : "App-specific password"} aria-label="App-specific password" />
      </div>
      <p className="note">Not your Apple password: make an app-specific one at appleid.apple.com, Sign-In and Security. Stored in {apple?.stored_in || "Windows' credential vault"}.</p>
      <div className="p-acts">
        <button className="p-sm dark" onClick={connect} disabled={busy || !id.trim() || (!pw.trim() && !apple?.password_set)}>{busy ? "Checking…" : apple?.configured ? "Reconnect" : "Connect"}</button>
        {apple?.configured && <button className="p-sm" onClick={async () => { setApple(await disconnectAppleCalendar()); ui.toast("Disconnected. The password was deleted."); }}>Disconnect</button>}
      </div>
    </Section>
  );
}

/* ---- Files ------------------------------------------------------------- */

export function FilesSection() {
  const ui = useUi();
  const [roots, setRoots] = useState(null);
  useEffect(() => { listFileRoots().then((d) => setRoots(d.roots)).catch((e) => { setRoots([]); ui.toast(e.message, { error: true }); }); }, [ui]);
  async function grant() {
    const picked = window.electronAPI?.chooseProjectFolder ? await window.electronAPI.chooseProjectFolder() : window.prompt("Full path to the folder:");
    if (!picked) return;
    try { setRoots((await addFileRoot(picked)).roots); ui.toast("Folder added."); } catch (e) { ui.toast(e.message, { error: true }); }
  }
  return (
    <Section title="Folders Nova can read" desc="Grant the folders you want Nova working in, not your whole drive. What it reads can go to whichever model answers. Passwords and keys (.env, .ssh, private keys) are never read.">
      {roots?.length === 0 && <div className="note">No folders yet. The project open in Studio is always readable.</div>}
      {(roots || []).map((r) => (
        <Row key={r.path} label={<span className="mono" style={{ fontSize: 12, color: "var(--tx)" }}>{r.path}</span>}>
          {r.is_workspace ? <span className="p-status browse">open project</span>
            : <button className="p-sm" onClick={async () => { try { setRoots((await removeFileRoot(r.path)).roots); } catch (e) { ui.toast(e.message, { error: true }); } }}>Remove</button>}
        </Row>
      ))}
      <div className="p-acts" style={{ marginTop: 10 }}><button className="p-sm dark" onClick={grant}><Icon name="folder" />Add a folder…</button></div>
    </Section>
  );
}

/* ---- About and usage --------------------------------------------------- */

export function AboutSection() {
  const [usage, setUsage] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { getSpendBreakdown(30).then(setUsage).catch((e) => setErr(e.message)); }, []);
  const groups = [["metered", "Paid per use"], ["subscription", "Subscriptions"], ["local", "On this computer"]];
  return (
    <>
      <Section title="Usage, last 30 days" desc="Money actually spent, apart from flat-rate subscriptions and free local models.">
        {err && <p className="note">{err}</p>}
        {usage && (
          <>
            <Row label="Actually spent"><b>{money(usage.real_spend_usd)}</b></Row>
            {groups.map(([k, label]) => usage[k]?.calls ? (
              <Row key={k} label={label} desc={(usage[k].providers || []).map((p) => `${p.provider} ${p.calls}`).join(" · ")}>
                <span className="mono">{usage[k].calls} calls · {k === "metered" ? money(usage[k].cost_usd) : `${usage[k].tokens.toLocaleString()} tokens`}</span>
              </Row>
            ) : null)}
          </>
        )}
      </Section>
      <Section title="About Nova">
        <div className="p-kv">
          <span>Version</span><span>0.1.0</span>
          <span>Interface build</span><span>{typeof __NOVA_BUILD_ID__ !== "undefined" ? __NOVA_BUILD_ID__ : "development"}</span>
          <span>Engine</span><span>this computer, port 8000</span>
          <span>Your data</span><span>~/.ai-council</span>
        </div>
      </Section>
    </>
  );
}
