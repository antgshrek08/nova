import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { getUserProfile, updateUserProfile } from "../api.js";
import ErrorBoundary from "../components/ErrorBoundary.jsx";
import Icon from "./icons.jsx";
import Reactor from "./Reactor.jsx";
import { PALETTES, resolvePalette } from "./palettes.js";
import { browserSupport } from "./paperApi.js";
import {
  AboutSection, AgentsSection, AutonomySection, CalendarSection, CanvasSection, ConnectorsSection, FilesSection,
  ModelsSection, PlatformsSection, Row, RoutingSection, SecretsSection, Seg, SkillsSection, Switch, VoiceSection,
} from "./SettingsSections.jsx";
import { CalendarSources } from "./CalendarSettings.jsx";
import ModelGuide from "./ModelGuide.jsx";
import ObsidianSettings from "./ObsidianSettings.jsx";
import RemoteSettings from "./RemoteSettings.jsx";
import SchoolProfile from "./SchoolProfile.jsx";
import HealthSection from "./HealthSection.jsx";
import { IS_REMOTE } from "./remote.js";
import { NotificationsSection } from "./SettingsMore.jsx";
import { useUi } from "./ui.jsx";
import "./legacy.css";

// Panels that still use their original markup, restyled to Paper by legacy.css.
const NotificationsPanel = lazy(() => import("../components/settings/NotificationsPanel.jsx"));
const EmailPanel = lazy(() => import("../components/settings/EmailPanel.jsx"));
const AccountsPanel = lazy(() => import("../components/settings/AccountsPanel.jsx"));
const AccessPanel = lazy(() => import("../components/settings/AccessPanel.jsx"));

// The desktop app (Electron, loaded from a file) versus the phone app or a
// browser tab (served over http/https by Nova's engine).
const inDesktopApp = typeof window !== "undefined" && (Boolean(window.electronAPI) || window.location.protocol === "file:");

/** Every Settings section: [name, icon, group, search words]. */
export const SETTINGS_SECTIONS = [
  ["Appearance", "palette", "Nova", "day night colors theme dark light"],
  ["General", "user", "Nova", "profile name school startup login spending budget"],
  ["Voice", "voice", "Nova", "speech speak tts clone hotkey push to talk"],
  ["Autonomy", "shield", "Nova", "permissions cursor pointer mouse tools"],
  ["Browser", "globe", "Nova", "onyx chrome edge hidden visible links sign in"],
  ["Models", "bolt", "Models and tools", "api keys openrouter gemini typesafe jev ollama local"],
  ["Routing", "sliders", "Models and tools", "category model pick"],
  ["Connectors", "plug", "Models and tools", "mcp servers tools"],
  ["Skills", "box", "Models and tools", "know how instructions"],
  ["Coding agents", "code", "Models and tools", "acp claude code gemini cli"],
  ["Canvas", "cap", "School", "courses assignments sync feed token"],
  ["Homework platforms", "file", "School", "pearson aleks lumen webassign mylab"],
  ["School profile", "cap", "School", "classes schedule professor"],
  ["Sign-ins", "key", "Your accounts", "accounts logins sites"],
  ["Passwords", "shield", "Your accounts", "secrets vault"],
  ["Email", "mail", "Your accounts", "gmail outlook inbox"],
  ["Calendar", "cal", "Your accounts", "apple icloud"],
  ["Notifications", "bell", "Your accounts", "alerts push phone"],
  ["Remote", "phone", "Your accounts", "phone mobile remote device tailscale link token session"],
  ["Notes", "file", "Your accounts", "obsidian vault notes markdown"],
  ["Folders", "folder", "Your accounts", "files access"],
  ["Health", "refresh", "About", "sentinel errors diagnostics"],
  ["About", "info", "About", "usage spend version"],
];

export function ModeChoice({ prefs }) {
  const modes = [
    ["day", "Day", "Warm paper"],
    ["night", "Night", "Same Nova, night colors"],
    ["auto", "Automatic", "Matches your device's light or dark setting"],
  ];
  return (
    <div className="p-modes" role="group" aria-label="Day or night">
      {modes.map(([id, name, note]) => (
        <button key={id} className="p-mode" aria-pressed={prefs.mode === id} onClick={() => prefs.setMode(id)}>
          <div className={`p-pv ${id}`}><i /><b /></div>
          <span>{name}<small>{note}</small></span>
        </button>
      ))}
    </div>
  );
}

export function PaletteChoice({ prefs, withCustomInputs = false }) {
  const [c1, c2, c3] = prefs.customColors;
  const setCustom = (i, value) => {
    const next = [c1, c2, c3];
    next[i] = value;
    prefs.setCustom(next);
  };
  return (
    <>
      <div className="p-pals" role="group" aria-label="Nova's colors">
        {[...Object.entries(PALETTES), ["custom", resolvePalette("custom", prefs.customColors.join(","))]].map(([id, pal]) => (
          <button key={id} className="p-pal" aria-pressed={prefs.paletteId === id}
            onClick={() => (id === "custom" ? prefs.setCustom([c1, c2, c3]) : prefs.setPalette(id))}>
            <div className="sw"><Reactor palette={pal} dark={prefs.dark} state="idle" /></div>
            <span>{id === "custom" ? "Custom" : pal.name}<small>{id === "custom" ? "Your three colors" : pal.note}</small></span>
          </button>
        ))}
      </div>
      {withCustomInputs && prefs.paletteId === "custom" && (
        <div className="p-custom">
          <span>Your colors</span>
          <input type="color" value={c1} onChange={(e) => setCustom(0, e.target.value)} aria-label="First reactor color" />
          <input type="color" value={c2} onChange={(e) => setCustom(1, e.target.value)} aria-label="Second reactor color" />
          <input type="color" value={c3} onChange={(e) => setCustom(2, e.target.value)} aria-label="Depth color" />
          <span>two main colors, then the shadow color</span>
        </div>
      )}
    </>
  );
}

const truthy = (v) => v === true || v === "1" || v === 1;

function GeneralSection({ prefs }) {
  const ui = useUi();
  const s = prefs.settings;
  const [profile, setProfile] = useState(null);
  useEffect(() => { getUserProfile().then(setProfile).catch(() => setProfile({})); }, []);
  async function saveProfile(patch) {
    setProfile((p) => ({ ...p, ...patch }));
    try { await updateUserProfile(patch); } catch (e) { ui.toast(e.message, { error: true }); }
  }
  async function login(patch) {
    prefs.save(patch);
    const enabled = "launch_at_login" in patch ? patch.launch_at_login : truthy(s.launch_at_login);
    const petOnly = "miniplayer_at_login" in patch ? patch.miniplayer_at_login : s.miniplayer_at_login !== false;
    await window.electronAPI?.setLaunchAtLogin?.(enabled, petOnly);
  }
  const field = (key, label, placeholder) => (
    <Row label={label}>
      <input className="p-input" defaultValue={profile?.[key] || ""} key={`${key}-${profile ? "l" : "w"}`} placeholder={placeholder} aria-label={label}
        onBlur={(e) => { if (e.target.value.trim() !== (profile?.[key] || "")) saveProfile({ [key]: e.target.value.trim() }); }}
        onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} style={{ width: 260 }} />
    </Row>
  );
  return (
    <>
      <div className="p-sgroup">
        <div className="p-shead"><h4>You</h4></div>
        <p className="d">How Nova addresses you, and what it knows about your studies.</p>
        {field("name", "Name", "What Nova calls you")}
        {field("school", "School", "Your school")}
        {field("major", "Major or focus", "What you study")}
      </div>
      <div className="p-sgroup">
        <div className="p-shead"><h4>Your instructions for Nova</h4></div>
        <p className="d">Anything about how Nova should answer you: shorter replies, more examples, a language, a tone. Nova follows these in every chat.</p>
        <textarea className="p-input p-instructions" rows={4} maxLength={2000} key={`ci-${prefs.loaded ? "l" : "w"}`} defaultValue={s.custom_instructions || ""}
          placeholder="For example: Keep answers short. Explain math step by step. Call me Sam."
          aria-label="Your instructions for Nova"
          onBlur={(e) => { const v = e.target.value.trim(); if (v !== (s.custom_instructions || "")) { prefs.save({ custom_instructions: v }); ui.toast("Saved."); } }} />
      </div>
      <div className="p-sgroup">
        <div className="p-shead"><h4>Homework</h4></div>
        <Row label="How Nova helps with homework" desc="Solve answers outright and shows the working. Tutor walks you through it a step at a time.">
          <Seg value={s.homework_mode === "tutor" ? "tutor" : "solve"} onChange={(v) => prefs.save({ homework_mode: v })} label="Homework help" options={[["solve", "Solve"], ["tutor", "Tutor"]]} />
        </Row>
        <Row label="Double-check coding answers" desc="A second model reviews code answers. Slower and costs more.">
          <Switch on={truthy(s.handoff_review_enabled)} label="Double-check coding answers" onChange={(v) => prefs.save({ handoff_review_enabled: v })} />
        </Row>
      </div>
      <div className="p-sgroup">
        <div className="p-shead"><h4>Starting Nova</h4></div>
        <Row label="Start Nova when I sign in to Windows">
          <Switch on={truthy(s.launch_at_login)} label="Start Nova when I sign in" onChange={(v) => login({ launch_at_login: v })} />
        </Row>
        <Row label="Start as the miniplayer" desc="Opens just the miniplayer; everything keeps working in the background">
          <Switch on={s.miniplayer_at_login !== false} label="Start as the miniplayer" onChange={(v) => login({ miniplayer_at_login: v })} />
        </Row>
      </div>
      <div className="p-sgroup">
        <div className="p-shead"><h4>Spending</h4></div>
        <Row label="Daily limit for paid models" desc="US dollars. Subscriptions and local models don't count">
          <input className="p-input" type="number" step="0.5" min="0" defaultValue={s.spend_cap_usd ?? 1} key={`cap-${s.spend_cap_usd}`} aria-label="Daily limit"
            onBlur={(e) => prefs.save({ spend_cap_usd: parseFloat(e.target.value) || 0 })} style={{ width: 100 }} />
        </Row>
      </div>
    </>
  );
}

function BrowserSection({ prefs }) {
  const s = prefs.settings;
  const [browsers, setBrowsers] = useState(null);
  useEffect(() => { browserSupport().then(setBrowsers).catch(() => setBrowsers({ browsers: [] })); }, []);
  return (
    <div className="p-sgroup">
      <div className="p-shead"><h4>Browser</h4></div>
      <p className="d">Where Nova works on the web, and where links open.</p>
      <Row label="Show Nova's browser" desc="Visible uses your open Onyx window so you can watch. Hidden keeps Nova's own window out of your way.">
        <Seg value={s.browser_visibility_mode === "visible" ? "visible" : "hidden"} onChange={(v) => prefs.save({ browser_visibility_mode: v })} label="Browser visibility" options={[["visible", "Visible"], ["hidden", "Hidden"]]} />
      </Row>
      <Row label="Browser Nova drives" desc="Onyx uses Nova's own cursor; the others run a separate Nova profile">
        <select className="p-sm" value={s.browser_backend === "onyx" ? "onyx" : (s.preferred_browser || "chrome")} aria-label="Browser Nova drives"
          onChange={(e) => prefs.save(e.target.value === "onyx" ? { browser_backend: "onyx" } : { browser_backend: "edge", preferred_browser: e.target.value })}>
          {(browsers?.browsers || [{ id: "onyx", name: "Onyx", available: true }, { id: "chrome", name: "Google Chrome", available: true }]).map((b) => (
            <option key={b.id} value={b.id} disabled={!b.available}>{b.name}{b.available ? "" : " (not installed)"}</option>
          ))}
        </select>
      </Row>
      <Row label="Open links and sign-in pages in" desc={s.link_target === "nova" ? "A tab in your Onyx window, so a sign-in there is one Nova can use too. If Onyx isn't open, your usual browser." : "Your usual browser, the one Windows opens links in."}>
        <Seg value={s.link_target === "nova" ? "nova" : "system"} onChange={(v) => prefs.save({ link_target: v })} label="Where links open" options={[["system", "My browser"], ["nova", "Nova's browser"]]} />
      </Row>
    </div>
  );
}

function Legacy({ children }) {
  return (
    <div className="p-legacy">
      <ErrorBoundary><Suspense fallback={<div className="note">Loading…</div>}>{children}</Suspense></ErrorBoundary>
    </div>
  );
}

export function SettingsView({ prefs, section = "Appearance", onSection, onModelsChanged, onClose }) {
  const [query, setQuery] = useState("");
  const boxRef = useRef(null);
  const lastFocus = useRef(null);
  // A popup: Esc or a click outside closes it, focus stays inside while it's
  // open and goes back where it was afterwards.
  useEffect(() => {
    lastFocus.current = document.activeElement;
    boxRef.current?.querySelector(".p-setclose")?.focus();
    return () => lastFocus.current?.focus?.();
  }, []);
  const onKeyDown = (e) => {
    if (e.key === "Escape" && !document.querySelector(".p-menu, .p-dialog")) {
      if (e.target.tagName === "INPUT" && e.target.value && e.target.closest(".p-snav")) return;
      e.preventDefault(); e.stopPropagation(); onClose?.();
    }
    if (e.key === "Tab") {
      const f = [...boxRef.current.querySelectorAll('button:not([disabled]), input:not([disabled]), select, textarea, [tabindex="0"]')].filter((x) => x.offsetParent);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  };
  const current = SETTINGS_SECTIONS.some(([n]) => n === section) ? section : "Appearance";
  const q = query.trim().toLowerCase();
  const shown = useMemo(() => SETTINGS_SECTIONS.filter(([name, , group, words]) => !q || `${name} ${group} ${words}`.toLowerCase().includes(q)), [q]);
  const groups = useMemo(() => {
    const map = new Map();
    shown.forEach((row) => { if (!map.has(row[2])) map.set(row[2], []); map.get(row[2]).push(row); });
    return [...map.entries()];
  }, [shown]);

  // On a phone: the list of sections first; picking one opens it, "Settings" goes back.
  const navRef = useRef(null);
  const [opened, setOpened] = useState(Boolean(section && section !== "Appearance"));
  const pick = (name) => { setOpened(true); onSection(name); };
  return (
    <div className="p-scrim p-setscrim" onPointerDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}>
    <section className={`p-settings p-setmodal${opened ? " opened" : ""}`} role="dialog" aria-modal="true" aria-label="Settings" ref={boxRef} onKeyDown={onKeyDown}>
      <button className="p-setclose" onClick={onClose} aria-label="Close settings" title="Close (Esc)"><Icon name="x" /></button>
      <nav className="p-snav" aria-label="Settings sections" ref={navRef}>
        <h3>Settings</h3>
        <label className="p-pill"><Icon name="search" /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a setting" aria-label="Find a setting"
          onKeyDown={(e) => { if (e.key === "Enter" && shown[0]) pick(shown[0][0]); if (e.key === "Escape") setQuery(""); }} /></label>
        {groups.map(([group, rows]) => (
          <div key={group} className="p-sgrp">
            <div className="gl">{group}</div>
            {rows.map(([name, icon]) => (
              <button key={name} className="p-item" aria-current={current === name ? "page" : undefined} onClick={() => pick(name)}>
                <Icon name={icon} size={15} /><span className="t">{name}</span><Icon name="chev" size={14} />
              </button>
            ))}
          </div>
        ))}
        {!shown.length && <div className="note" style={{ padding: "6px 10px" }}>No setting matches.</div>}
      </nav>
      <div className="scroll" key={current}>
        <button className="p-setback" onClick={() => setOpened(false)}><Icon name="chev" size={15} />Settings</button>
        <div className="p-spanel">
          {current === "Appearance" && (
            <>
              <div className="p-sgroup"><div className="p-shead"><h4>Day or night</h4></div><p className="d">Only the colors change. You can also switch from the sun and moon in the title bar, or with Ctrl+Shift+L.</p><ModeChoice prefs={prefs} /></div>
              <div className="p-sgroup"><div className="p-shead"><h4>Nova's colors</h4></div><p className="d">The reactor keeps its shape and motion; only its colors change. Checked results and progress follow the same colors.</p><PaletteChoice prefs={prefs} withCustomInputs /></div>
            </>
          )}
          {current === "General" && <GeneralSection prefs={prefs} />}
          {current === "Voice" && <VoiceSection prefs={prefs} />}
          {current === "Autonomy" && <AutonomySection prefs={prefs} />}
          {current === "Browser" && <BrowserSection prefs={prefs} />}
          {current === "Models" && <><ModelsSection prefs={prefs} onChanged={onModelsChanged} /><div className="p-sgroup"><div className="p-shead"><h4>Add more models</h4></div><p className="d">Every way to give Nova a model, what it costs, and how to set it up.</p><ModelGuide onChanged={() => onModelsChanged?.()} /></div></>}
          {current === "Routing" && <RoutingSection />}
          {current === "Connectors" && <ConnectorsSection />}
          {current === "Skills" && <SkillsSection />}
          {current === "Coding agents" && <AgentsSection />}
          {current === "Canvas" && <CanvasSection />}
          {current === "Homework platforms" && <PlatformsSection />}
          {current === "School profile" && <SchoolProfile />}
          {current === "Sign-ins" && <Legacy><AccountsPanel /></Legacy>}
          {current === "Passwords" && <SecretsSection />}
          {current === "Email" && <Legacy><EmailPanel /></Legacy>}
          {current === "Calendar" && <><CalendarSection /><CalendarSources prefs={prefs} /></>}
          {current === "Notifications" && <>
            <NotificationsSection prefs={prefs} />
            {/* Push needs a service worker, which only a web page served over
                https (the phone app) can register. The desktop app is a local
                file and uses Windows notifications instead. */}
            {!inDesktopApp && <div className="p-sgroup"><div className="p-shead"><h4>This device</h4></div><Legacy><NotificationsPanel /></Legacy></div>}
          </>}
          {current === "Remote" && <><RemoteSettings />{!IS_REMOTE && <div className="p-sgroup"><div className="p-shead"><h4>Advanced</h4></div><Legacy><AccessPanel /></Legacy></div>}</>}
          {current === "Notes" && <ObsidianSettings />}
          {current === "Folders" && <FilesSection />}
          {current === "Health" && <HealthSection prefs={prefs} />}
          {current === "About" && <AboutSection />}
        </div>
      </div>
    </section>
    </div>
  );
}
