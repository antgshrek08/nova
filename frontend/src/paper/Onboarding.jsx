// First run: everything a new user needs before Nova is useful -- who they
// are, how Nova looks, the AI models it thinks with, how much it may do on its
// own, its voice, their notes (Obsidian vaults found automatically), and what
// to connect. Choices are saved as they're made, so leaving early loses
// nothing. ?preview=onboarding shows it again without saving your profile,
// keys or vaults.
import { useEffect, useRef, useState } from "react";
import {
  BACKEND_URL, connectObsidianVault, detectObsidianVaults, selectDesktopFolder,
  textToSpeech, updateUserProfile,
} from "../api.js";
import { playTtsAudio, stopTtsAudio } from "../lib/ttsPlayback.js";
import Icon from "./icons.jsx";
import ModelGuide from "./ModelGuide.jsx";
import Reactor from "./Reactor.jsx";
import { ModeChoice, PaletteChoice } from "./SettingsViews.jsx";
import { STOP_KEY } from "./keys.js";
import SystemAccess from "./SystemAccess.jsx";

const truthy = (v) => v === true || v === "1" || v === 1;
const openLink = (url) => (window.electronAPI?.openLink ? window.electronAPI.openLink(url) : window.open(url, "_blank"));
const STEPS = ["You", "Look", "Models", "Permissions", "Voice", "Notes", "Connect"];

/* ---- models ---------------------------------------------------------------- */

function ModelsStep({ preview, onCount }) {
  return <div className="p-onbblock"><ModelGuide preview={preview} onChanged={onCount} compact /></div>;
}

/* ---- permissions ---------------------------------------------------------- */

const LEVELS = [
  ["readonly", "Read only", "Nova looks, searches and answers. It changes nothing on your computer or the web."],
  ["guarded", "Ask first", "Nova asks before anything that changes something. Recommended to start."],
  ["full", "Trusted", "Nova acts without asking each time. Payments, sending messages and submitting work still ask."],
];

function PermissionsStep({ prefs }) {
  const s = prefs.settings;
  const level = s.autonomy_level || "guarded";
  return (
    <div className="p-onbblock">
      <div className="p-modes p-onblevels" role="radiogroup" aria-label="How much Nova may do on its own">
        {LEVELS.map(([id, name, note]) => (
          <button key={id} role="radio" aria-checked={level === id} className="p-mode" aria-pressed={level === id} onClick={() => prefs.save({ autonomy_level: id })}>
            <span>{name}<small>{note}</small></span>
          </button>
        ))}
      </div>
      <div className="p-row" style={{ width: "min(560px, 100%)", textAlign: "left" }}>
        <span>When Nova uses the web<small>Show lets you watch it work; hidden keeps its browser out of your way</small></span>
        <div className="p-seg" role="group" aria-label="Nova's browser">
          <button aria-pressed={s.browser_visibility_mode === "visible"} onClick={() => prefs.save({ browser_visibility_mode: "visible" })}>Show it</button>
          <button aria-pressed={s.browser_visibility_mode !== "visible"} onClick={() => prefs.save({ browser_visibility_mode: "hidden" })}>Keep hidden</button>
        </div>
      </div>
      <div style={{ width: "min(560px, 100%)", textAlign: "left" }}><SystemAccess compact /></div>
      <p className="note">{`Stop Nova any time: press ${STOP_KEY}, or throw your mouse into a screen corner.`} Your chats, memory and keys stay on this computer.</p>
    </div>
  );
}

/* ---- voice ------------------------------------------------------------------ */

const VOICES = [["ava", "Ava", "warm"], ["andrew", "Andrew", "calm"], ["emma", "Emma", "bright"], ["default", "Ryan", "works offline"]];

function VoiceStep({ prefs }) {
  const s = prefs.settings;
  const [playing, setPlaying] = useState(null);
  const [loading, setLoading] = useState(null);
  const [voiceMsg, setVoiceMsg] = useState("");
  useEffect(() => () => stopTtsAudio(), []);
  async function play(id) {
    if (playing === id) { stopTtsAudio(); setPlaying(null); return; }
    stopTtsAudio();
    setVoiceMsg("");
    setLoading(id);
    try {
      const blob = await textToSpeech("Hi, I'm Nova. I'll keep track of your classes and handle the busywork.", id);
      setLoading(null);
      setPlaying(id);
      await playTtsAudio(blob, { onEnd: () => setPlaying((p) => (p === id ? null : p)) });
    } catch (e) {
      setLoading(null);
      setPlaying(null);
      setVoiceMsg(`That voice couldn't play: ${e.message}. Online voices need internet${offline ? "; Ryan works offline" : ""}.`);
    }
  }
  const [names, setNames] = useState(null);
  // The offline voice (Ryan, "default") is an optional download; the engine
  // lists it only when it's installed, and speaks Ava in its place otherwise.
  const offline = !names || "default" in names;
  const saved = s.tts_voice_id || "default";
  const current = saved === "default" && !offline ? "ava" : saved;
  useEffect(() => {
    fetch(`${BACKEND_URL}/tts/voices`).then((r) => r.json()).then((d) => setNames(Object.fromEntries((d.voices || []).map((v) => [v.id, v.name])))).catch(() => {});
  }, []);
  // A voice already chosen that isn't one of the suggestions stays listed first.
  const base = VOICES.filter(([id]) => id !== "default" || offline);
  const list = base.some(([id]) => id === current) ? base : [[current, ((names || {})[current] || "Your voice").split(" · ")[0], "your current voice"], ...base];
  return (
    <div className="p-onbblock">
      <div className="p-seg" role="group" aria-label="Speak replies">
        <button aria-pressed={truthy(s.voice_replies)} onClick={() => prefs.save({ voice_replies: true, speak_summary_only: true })}>Speak replies</button>
        <button aria-pressed={!truthy(s.voice_replies)} onClick={() => prefs.save({ voice_replies: false })}>Text only</button>
      </div>
      <div className="p-voices p-onbvoices" role="radiogroup" aria-label="Nova's voice">
        {list.map(([id, name, note]) => (
          <div key={id} className={`p-voice${current === id ? " on" : ""}`}>
            <button role="radio" aria-checked={current === id} className="pick" onClick={() => prefs.save({ tts_voice_id: id })}>
              <span className="dot" /><span className="n">{name} <span className="note">· {note}</span></span>
            </button>
            <button className="p-link" onClick={() => play(id)} disabled={loading === id} aria-label={playing === id ? `Stop ${name}` : `Play ${name}`} title={loading === id ? "Loading…" : playing === id ? "Stop" : "Play a sample"}>
              {loading === id ? <span className="p-spin" aria-hidden="true" /> : <Icon name={playing === id ? "stop" : "play"} size={14} />}
            </button>
          </div>
        ))}
      </div>
      {voiceMsg && <p className="err">{voiceMsg}</p>}
      <p className="note">Press play to hear each one. Ten more voices, and cloning your own, are in Settings, Voice.</p>
    </div>
  );
}

/* ---- notes (Obsidian, found automatically) ------------------------------ */

function NotesStep({ picked, setPicked, preview }) {
  const [found, setFound] = useState(null);
  const [extra, setExtra] = useState("");
  const [making, setMaking] = useState(false);
  const [made, setMade] = useState("");
  async function makeFolder() {
    if (preview) { setMade("In preview nothing is created."); return; }
    setMaking(true);
    try {
      const r = await fetch(`${BACKEND_URL}/obsidian/create`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).then((x) => x.json());
      setFound((f) => [{ name: r.name, path: r.path, notes: 1, is_open: false, source: "found", connected: true }, ...(f || [])]);
      setMade(`Made "${r.name}" in your Documents folder and connected it.`);
    } catch (e) { setMade(`Couldn't make it: ${e.message}`); } finally { setMaking(false); }
  }
  useEffect(() => {
    detectObsidianVaults().then((d) => {
      const list = (d.vaults || []).filter((v) => !v.nova_own);
      setFound(list);
      // Ticked to start: the vault open in Obsidian, or the only one.
      setPicked(new Set(list.filter((v) => v.connected || v.is_open || list.length === 1).map((v) => v.path)));
    }).catch(() => setFound([]));
  }, [setPicked]);
  const toggle = (path) => setPicked((s) => { const n = new Set(s); if (n.has(path)) n.delete(path); else n.add(path); return n; });
  return (
    <div className="p-onbblock">
      <details className="p-mg-help" open={found?.length === 0}>
        <summary>New to Obsidian?</summary>
        <ul>
          <li><b>Obsidian</b> is a free note-taking app. Your notes are plain files in a folder on your computer, called a <b>vault</b>.</li>
          <li>Nova reads your notes when it answers, so it knows what you already wrote, and it can write new notes for you: lecture notes, summaries, study guides.</li>
          <li>Don't use it yet? Press <b>Make a notes folder for me</b>. Later, install Obsidian and choose "Open folder as vault" to see your notes there.</li>
        </ul>
        <div className="p-acts">
          <button className="p-sm" onClick={() => openLink("https://obsidian.md/download")}><Icon name="open" />Get Obsidian (free)</button>
        </div>
      </details>
      {found === null && <div className="note">Looking for your Obsidian vaults…</div>}
      {found?.length > 0 && (
        <div className="p-onbvaults" role="group" aria-label="Obsidian vaults found">
          {found.map((v) => (
            <label key={v.path} className={`p-onbvault${picked.has(v.path) || v.connected ? " on" : ""}`}>
              <input type="checkbox" checked={picked.has(v.path) || v.connected} disabled={v.connected} onChange={() => toggle(v.path)} />
              <span><b>{v.name}</b><small>{v.notes >= 5000 ? "5,000+" : v.notes.toLocaleString()} notes · {v.is_open ? "open in Obsidian" : v.source === "found" ? "found on this computer" : "in Obsidian"}{v.connected ? " · already connected" : ""}</small><small className="mono">{v.path}</small></span>
            </label>
          ))}
        </div>
      )}
      {found?.length === 0 && <p className="note">No Obsidian vaults on this computer yet.</p>}
      {found && !found.some((v) => v.connected) && (
        found.length === 0
          ? <button className="p-sm dark" onClick={makeFolder} disabled={making}><Icon name="folder" />{making ? "Making it…" : "Make a notes folder for me"}</button>
          : <button className="p-link" onClick={makeFolder} disabled={making}>{making ? "Making it…" : "Or make a new notes folder"}</button>
      )}
      {made && <p className="note">{made}</p>}
      <div className="p-inline" style={{ width: "min(560px, 100%)" }}>
        <input className="p-input" value={extra} placeholder="Another vault folder" aria-label="Another vault folder" onChange={(e) => setExtra(e.target.value)}
          onBlur={() => { if (extra.trim()) { toggle(extra.trim()); } }} />
        <button className="p-sm" onClick={async () => { const p = await selectDesktopFolder().catch(() => null); const path = p?.path || p; if (path) { setExtra(path); setPicked((s) => new Set([...s, path])); } }}>Choose folder</button>
      </div>
    </div>
  );
}

/* ---- connect --------------------------------------------------------------- */

function ConnectStep({ models, prefs, onOpen }) {
  const [status, setStatus] = useState({});
  useEffect(() => {
    // Each status shows as soon as its own check answers; reading Google
    // calendars can take a few seconds and shouldn't hold the rest.
    const j = (path) => fetch(`${BACKEND_URL}${path}`).then((r) => r.json()).catch(() => ({}));
    const set = (patch) => setStatus((s) => ({ ...s, ...patch }));
    j("/canvas/status").then((c) => set({ canvas: Boolean(c?.canvas?.any_configured) }));
    j("/apple-calendar/status").then((a) => { if (a?.configured) set({ calendar: true }); });
    j("/calendar/sources").then((cal) => set({ calendar: Boolean(cal?.apple?.connected || cal?.google?.length || cal?.feeds?.length) }));
    j("/push/devices").then((d) => set({ phone: Array.isArray(d) && d.length > 0 }));
    j("/homework/sources").then((hw) => set({ homework: (hw?.sources || []).length }));
  }, []);
  const [open, setOpen] = useState(null);
  const rows = [
    ["Canvas", "cap", "Your courses and due dates", status.canvas, "Canvas",
      "Nova reads your classes, assignments and due dates from Canvas, reminds you before things are due, and can open and work on assignments.",
      "Your school's Canvas login. The easiest way is Canvas's calendar feed link: in Canvas open Calendar, then Calendar Feed, and copy it.", "About 2 minutes"],
    ["Other homework sites", "file", status.homework ? `${status.homework} added` : "Pearson, ALEKS, WebAssign, Lumen and more", Boolean(status.homework), "Homework platforms",
      "If a class uses Pearson MyLab, ALEKS, WebAssign, Lumen, McGraw Hill, Gradescope or your school's Moodle or Brightspace, Nova finds the assignments there too.",
      "Pick the site and sign in once in Nova's browser window. Nova keeps you signed in.", "About 1 minute per site"],
    ["Your calendars", "cal", "Apple, Google, Outlook or any calendar link", status.calendar, "Calendar",
      "Nova sees your classes and plans, finds free time, and puts study sessions before due dates.",
      "Apple: an app-specific password from appleid.apple.com. Google or Outlook: the calendar's private link from its settings. Settings shows where each one is.", "About 2 minutes"],
    ["Your phone", "phone", "Nova's free phone app and notifications", status.phone, "Phone access",
      "Talk to Nova from your phone and get notifications about due dates and finished work. It's free and needs no app store.",
      "The free Tailscale app on this computer and your phone, signed in to the same account. Settings walks you through it and shows a code to scan.", "About 5 minutes"],
  ];
  return (
    <div className="p-onbblock">
      <div className="p-onbconnect">
        {rows.map(([name, icon, desc, done, section, what, need, time]) => (
          <div key={name} className={`p-onbitem${open === name ? " open" : ""}`}>
            <button className={`p-onbrow${done ? " done" : ""}`} onClick={() => setOpen(open === name ? null : name)} aria-expanded={open === name}>
              <Icon name={icon} /><span><b>{name}</b><small>{desc}</small></span>
              <span className={`p-status ${done ? "tested" : "browse"}`}>{done ? "connected" : "how it works"}</span>
            </button>
            {open === name && (
              <div className="p-onbhelp">
                <p><b>What it does.</b> {what}</p>
                <p><b>What you need.</b> {need}</p>
                <p className="note">{time}. You can do it later in Settings, {section}.</p>
                <div className="p-acts"><button className="p-sm dark" onClick={() => onOpen(section)}>{done ? "Open its settings" : "Set it up now"}</button></div>
              </div>
            )}
          </div>
        ))}
      </div>
      {window.electronAPI?.setLaunchAtLogin && (
        <div className="p-row" style={{ width: "min(520px, 100%)", textAlign: "left" }}>
          <span>Start Nova when I sign in to Windows<small>So reminders and notifications reach you</small></span>
          <button className="p-switch" role="switch" aria-checked={truthy(prefs.settings.launch_at_login)} aria-label="Start Nova when I sign in"
            onClick={() => { const v = !truthy(prefs.settings.launch_at_login); prefs.save({ launch_at_login: v }); window.electronAPI.setLaunchAtLogin(v, prefs.settings.miniplayer_at_login !== false); }} />
        </div>
      )}
      {models?.count != null && models.count >= 4 && <p className="note">You have {models.count} models ready, so Workspace is unlocked: your models working as one team.</p>}
    </div>
  );
}

/* ---- the flow -------------------------------------------------------------- */

const COPY = [
  ["Welcome to Nova", "Nova learns how you work and handles the busywork: classes, homework, code, and your computer. Start with a little about you."],
  ["Make Nova yours", "Pick day or night, and Nova's colors. You can change both any time in Settings."],
  ["Nova's models", "Nova thinks with AI models: some run on this computer, some online. Here's every way to add one and what this computer already has."],
  ["What Nova may do", "Nova can work in apps and on the web for you. Choose how much it does before checking with you."],
  ["Nova's voice", "Nova can say a short version of each answer out loud, and the reactor moves with its voice."],
  ["Your notes", "Nova can read your notes and write new ones for you. Tick the vaults it found, or let it make a notes folder."],
  ["Connect your things", "Each one makes Nova more useful. Tap one to see what it does and what you need. Set it up now, or any time in Settings."],
];

export default function OnboardingView({ prefs, onDone, preview = false, models }) {
  const [step, setStep] = useState(0);
  const [profile, setProfile] = useState({ name: "", school: "", major: "" });
  const [vaults, setVaults] = useState(() => new Set());
  const [modelCount, setModelCount] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const top = useRef(null);
  useEffect(() => { top.current?.scrollIntoView?.({ block: "start" }); }, [step]);

  // Look, voice and permission choices apply as they're made (in preview too,
  // so they visibly work); the profile, keys and vaults save only for real.
  const safePrefs = prefs;

  async function finish(section) {
    const next = typeof section === "string" ? section : undefined;
    if (preview) { onDone(next); return; }
    setBusy(true);
    setError("");
    try {
      await updateUserProfile({ name: profile.name.trim() || "Student", school: profile.school.trim(), major: profile.major.trim(), onboarding_completed: 1 });
      for (const path of vaults) {
        const name = path.split(/[\\/]/).filter(Boolean).pop() || "Vault";
        await connectObsidianVault(name, path).catch(() => {});
      }
      onDone(next);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const field = (key, label, placeholder) => (
    <label className="p-onbfield">
      <span className="note">{label}</span>
      <input className="p-input" value={profile[key]} placeholder={placeholder}
        onChange={(e) => setProfile((p) => ({ ...p, [key]: e.target.value }))}
        onKeyDown={(e) => { if (e.key === "Enter") setStep((n) => Math.min(STEPS.length - 1, n + 1)); }} />
    </label>
  );
  const needsModel = step === 2 && modelCount === 0;

  return (
    <section className="p-onb" aria-label="Welcome to Nova">
      <div className="inner" ref={top}>
        <Reactor palette={prefs.palette} dark={prefs.dark} />
        <div className="p-onbdots" aria-hidden="true">{STEPS.map((name, i) => <i key={name} className={i === step ? "on" : i < step ? "past" : ""} />)}</div>
        <div className="stepn">Step {step + 1} of {STEPS.length} · {STEPS[step]}{preview ? " · preview" : ""}</div>
        <h2>{COPY[step][0]}</h2>
        <p>{COPY[step][1]}</p>
        {step === 0 && (<>
          {field("name", "What should Nova call you?", "Your name")}
          {field("school", "School", "Your school")}
          {field("major", "Major or focus", "What you study")}
        </>)}
        {step === 1 && (<><ModeChoice prefs={safePrefs} /><PaletteChoice prefs={safePrefs} withCustomInputs /></>)}
        {step === 2 && <ModelsStep preview={preview} onCount={setModelCount} />}
        {step === 3 && <PermissionsStep prefs={safePrefs} />}
        {step === 4 && <VoiceStep prefs={safePrefs} />}
        {step === 5 && <NotesStep picked={vaults} setPicked={setVaults} preview={preview} />}
        {step === 6 && <ConnectStep models={models} prefs={safePrefs} onOpen={(section) => finish(section)} />}
        {error && <p className="err">{error}</p>}
        <div className="p-acts">
          {step > 0 && <button className="p-sm" onClick={() => setStep(step - 1)}>Back</button>}
          {step < STEPS.length - 1
            ? <button className="p-btn" onClick={() => setStep(step + 1)}>{needsModel ? "Continue without a model" : "Continue"}</button>
            : <button className="p-btn" onClick={() => finish()} disabled={busy}>{busy ? "Saving…" : "Start using Nova"}</button>}
        </div>
        {step < STEPS.length - 1 && <button className="p-link" onClick={() => setStep(STEPS.length - 1)}>Skip ahead</button>}
      </div>
    </section>
  );
}
