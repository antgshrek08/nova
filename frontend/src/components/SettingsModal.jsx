import { useCallback, useEffect, useRef, useState } from "react";
import TeamsView from "./workspace/TeamsView.jsx";
import NotificationsPanel from "./settings/NotificationsPanel.jsx";
import EmailPanel from "./settings/EmailPanel.jsx";
import AccountsPanel from "./settings/AccountsPanel.jsx";
import AccessPanel from "./settings/AccessPanel.jsx";
import SentinelPanel from "./settings/SentinelPanel.jsx";
import AcademicsPanel from "./settings/AcademicsPanel.jsx";
import Mascot from "./workspace/Mascot.jsx";
import { MASCOT_NAMES, refreshCustomMascots } from "../lib/mascots.js";
import { THEME_PRESETS, getAccentColor, applyAccentColor } from "../lib/themeStore.js";
import { getSpendBreakdown } from "../api.js";
import {
  listSecrets,
  putSecret,
  deleteSecret,
  getCanvasStatus,
  saveCanvasCredentials,
  saveCanvasFeed,
  saveTypeSafeKey,
  saveCanvasSettings,
  runCanvasSync,
  listAcpAgents,
  createAcpAgent,
  deleteAcpAgent,
  toggleAcpAgent as toggleAcpAgentApi,
  connectAcpAgent,
  getCapabilities,
  getSettings,
  saveSettings,
  getAppSettings,
  updateAppSettings,
  listModels,
  toggleModel,
  getWorkspaceStats,
  searchOpenRouterModels,
  createCustomModel,
  disconnectAppleCalendar,
  discoverCustomModels,
  getAppleCalendarStatus,
  getTypeSafeStatus,
  uploadMascot,
  deleteMascot,
  revealMascotDirectory,
  listAppleCalendars,
  saveAppleCalendarCredentials,
  deleteCustomModel,
  pullOllamaModel,
  listMcpServers,
  createMcpServer,
  deleteMcpServer,
  toggleMcpServer,
  listTtsVoices,
  createTtsVoice,
  deleteTtsVoice,
  textToSpeech,
  listRoutingCategories,
  listFileRoots,
  addFileRoot,
  removeFileRoot,
  getRoutingOverrides,
  setRoutingOverride,
  listSkills,
  createSkill,
  deleteSkill,
} from "../api.js";
import { providerMeta, modelDisplayName } from "../lib/providers.js";
import { playTtsAudio } from "../lib/ttsPlayback.js";

// Grouped by the question you came here to answer, not by which subsystem
// owns the setting. Seventeen items in one flat list meant scanning all of
// them every time, and the labels do not help: "Routing", "Teams" and
// "Agents" are three different things and read as near-synonyms.
//
// The order runs from what changes often to what changes once. Canvas and
// notifications get touched during a term; MCP and Teams get set up and left
// alone.
const SECTION_GROUPS = [
  ["Preferences", ["General", "Models", "Academics", "Voice"]],
];

const SECTIONS = SECTION_GROUPS.flatMap(([, items]) => items);

// Settings > Autonomy. Ordered least- to most-capable so the row the user
// lands on reads as a scale, and described by what actually changes on screen
// rather than by policy language.
// How long the pointer takes to reach what it is about to click. Named for
// what you see rather than the number, since the number only means anything
// once you've watched it.
const CLICK_SPEEDS = [
  { id: "off", label: "Instant", seconds: 0 },
  { id: "quick", label: "Quick", seconds: 0.25 },
  { id: "normal", label: "Normal", seconds: 0.45 },
  { id: "slow", label: "Easy to follow", seconds: 0.9 },
];

// Match the backend's desktop_pointer / desktop_borrow_mouse settings
// (app/desktop.py). There is deliberately no "borrow without asking".
const POINTER_MODES = [
  { id: "own", label: "Nova's own pointer" },
  { id: "real", label: "Move my mouse" },
];

const BORROW_POLICIES = [
  { id: "ask", label: "Ask me first" },
  { id: "never", label: "Never" },
];

// Matches the backend's browser_backend setting (app/browser_control.py).
const BROWSER_BACKENDS = [
  { id: "onyx", label: "Onyx, with Nova's cursor" },
  { id: "edge", label: "Nova's Edge window" },
];

const AUTONOMY_LEVELS = [
  {
    id: "readonly",
    label: "Read-only",
    summary: "Look, don't touch",
    detail:
      "Nova can read files, search, take screenshots and list what's running. Anything that writes a file, runs a command or drives the mouse is refused.",
  },
  {
    id: "guarded",
    label: "Ask first",
    summary: "Approve each change",
    detail:
      "Nova works freely until it needs to change something — then an approval card appears in chat and nothing happens until you answer it.",
  },
  {
    id: "full",
    label: "Full",
    summary: "Just do it",
    detail:
      "Nova runs commands, edits files, opens apps and drives the browser without stopping to ask. It still won't type into a password or payment window, and it still checks with you before spending money or sending anything under your name.",
  },
];

// Every routing.py CATEGORY_CHAINS key except "coding" (deliberately
// CLI-only per spec -- no free-first attempt) and "image_generation"
// (needs a diffusion pipeline, not a text-completion model).
const ASSIGNABLE_CATEGORIES = [
  "general_writing",
  "reasoning_math",
  "agentic_planning",
  "frontend_ui_code",
  "multilingual",
  "long_context",
  "quick_simple",
  "vision_multimodal",
  "design_review",
];

// Curated shortcuts for Add Model > Custom -- each is a real company's own
// official, publicly-documented free-tier API with an OpenAI-compatible
// endpoint, vetted by hand (not auto-imported from a list) against two
// external "free LLM API" roundups. Deliberately excludes: proxy/aggregator
// products that ride on other providers' models through their own account
// system rather than being a direct model host (Kilo Code, Cline -- both
// are coding-assistant tools, not model providers); anything running on
// decentralized/community compute rather than a single accountable
// company's infra (Chutes.ai); and several smaller/newer names (LLM7.io,
// OpenCode Zen, Glhf.chat, Agnes AI, Aion Labs) neither list gave enough
// independent corroboration for -- absence here isn't a claim they're
// illegitimate, just that they didn't clear the bar for a pre-filled
// shortcut. Base URLs are current as of when this was written; a provider
// can always still be added manually below if a path has since moved.
const CUSTOM_PROVIDER_PRESETS = [
  { name: "Groq", apiBase: "https://api.groq.com/openai/v1" },
  { name: "Cerebras", apiBase: "https://api.cerebras.ai/v1" },
  { name: "Cloudflare Workers AI", apiBase: "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1" },
  { name: "Hugging Face", apiBase: "https://router.huggingface.co/v1" },
  { name: "Mistral AI", apiBase: "https://api.mistral.ai/v1" },
  { name: "Cohere", apiBase: "https://api.cohere.ai/compatibility/v1" },
  { name: "NVIDIA NIM", apiBase: "https://integrate.api.nvidia.com/v1" },
  { name: "DeepSeek", apiBase: "https://api.deepseek.com/v1" },
  { name: "xAI (Grok)", apiBase: "https://api.x.ai/v1" },
  { name: "GitHub Models", apiBase: "https://models.github.ai/inference" },
  { name: "SambaNova", apiBase: "https://api.sambanova.ai/v1" },
  { name: "Alibaba Cloud (Qwen)", apiBase: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1" },
  { name: "Nebius AI Studio", apiBase: "https://api.studio.nebius.ai/v1" },
  { name: "Z.ai (GLM)", apiBase: "https://api.z.ai/api/paas/v4" },
];

// Gateways you run yourself. Kept separate from the list above on purpose: the
// exclusion note there is about third-party *proxies* that hold your account
// and route through their own provider keys. These are the opposite -- they run
// on your machine against keys you added yourself, so the trust question is
// "do you trust this software on your box", not "do you trust a stranger with
// your traffic". Still your call to install; Nova only talks to the port.
const LOCAL_GATEWAY_PRESETS = [
  {
    name: "FreeLLMAPI",
    apiBase: "http://localhost:3001/v1",
    hint: "Self-hosted router that pools the free tiers of ~34 providers behind one endpoint (MIT). Install it separately, add your provider keys in its dashboard, then paste its freellmapi-… key here.",
  },
  { name: "LM Studio", apiBase: "http://localhost:1234/v1", hint: "Local GGUF models, no key needed." },
  { name: "vLLM", apiBase: "http://localhost:8000/v1", hint: "Local high-throughput server, no key needed." },
];

const MCP_PRESETS = [
  // Phase 0 of the original handoff. Sequential Thinking needs no account;
  // Context7 and Brave each need a free key pasted into the env field after
  // adding, which is why they carry the key name in their hint rather than
  // silently failing to connect.
  { name: "Sequential Thinking", command: "npx", args: "-y @modelcontextprotocol/server-sequential-thinking", hint: "Step-by-step reasoning scratchpad — no key needed" },
  { name: "Context7", command: "npx", args: "-y @upstash/context7-mcp", hint: "Up-to-date library docs — free key at context7.com/dashboard (CONTEXT7_API_KEY)" },
  { name: "Brave Search", command: "npx", args: "-y @brave/brave-search-mcp-server --transport stdio", hint: "Web search — free key at brave.com/search/api (BRAVE_API_KEY)" },
  // Remote servers. These are the vendors' own hosted endpoints, verified from
  // their documentation rather than from an aggregator listing -- a wrong MCP
  // URL is a credential prompt pointed at someone else's server.
  { name: "Vercel", transport: "http", url: "https://mcp.vercel.com", hint: "Deployments, build logs, projects, analytics — OAuth on first use" },
  { name: "Hugging Face", transport: "http", url: "https://huggingface.co/mcp", hint: "Models, datasets, Spaces, papers — connect at huggingface.co/settings/mcp" },
  { name: "Figma (desktop)", transport: "http", url: "http://127.0.0.1:3845/mcp", hint: "Read the selected frame. Needs the desktop app open on the file with Dev Mode (Shift+D) enabled" },
  { name: "Replit", transport: "http", url: "https://replit-mcp.com/server/mcp", hint: "Build, update and publish Repls — OAuth on first use. The endpoint really is replit-mcp.com, per docs.replit.com/platforms/mcp-server" },
  { name: "Lovable", transport: "http", url: "https://mcp.lovable.dev", hint: "Create and iterate on Lovable projects — OAuth on first use" },
  { name: "Greptile", transport: "http", url: "https://api.greptile.com/mcp", hint: "Search and ask questions across whole repositories — key at app.greptile.com (Authorization: Bearer)" },
  // Higgsfield is deliberately absent: its own site says to "add the Higgsfield
  // MCP server URL" without printing one, and the URLs in circulation are all
  // third-party write-ups. Add it by hand from your account rather than have
  // Nova point an OAuth prompt at an address nobody at Higgsfield published.
  { name: "Filesystem", command: "npx", args: "-y @modelcontextprotocol/server-filesystem .", hint: "Read project files" },
  { name: "Git", command: "uvx", args: "mcp-server-git --repository .", hint: "Inspect history and diffs (needs uv installed)" },
  { name: "Fetch", command: "uvx", args: "mcp-server-fetch", hint: "Retrieve web pages (needs uv installed)" },
  { name: "Memory", command: "npx", args: "-y @modelcontextprotocol/server-memory", hint: "Structured knowledge graph" },
  { name: "Time", command: "uvx", args: "mcp-server-time", hint: "Time-zone conversions (needs uv installed)" },
];

function Toggle({ on, onClick, label = "Enable model or service" }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={Boolean(on)}
      aria-label={label}
      onClick={onClick}
      className={`relative inline-flex h-5 w-[38px] shrink-0 items-center rounded-full transition-colors ${
        on ? "bg-emerald-600" : "bg-charcoal-700"
      }`}
    >
      <span
        className={`absolute left-0.5 top-1/2 h-4 w-4 -translate-y-1/2 rounded-full bg-white shadow-sm transition-transform ${
          on ? "translate-x-[18px]" : "translate-x-0"
        }`}
      />
    </button>
  );
}

function CategorySelect({ value, onChange }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
    >
      {ASSIGNABLE_CATEGORIES.map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
    </select>
  );
}

function ToggleRow({ label, desc, on, onClick }) {
  return (
    <div className="flex items-center justify-between border-b border-charcoal-800/60 py-3">
      <div className="pr-4">
        <p className="text-sm text-charcoal-200">{label}</p>
        {desc && <p className="mt-0.5 text-xs text-charcoal-500">{desc}</p>}
      </div>
      <Toggle on={on} onClick={onClick} label={label} />
    </div>
  );
}

function AccentColorPicker() {
  const [current, setCurrent] = useState(() => getAccentColor());

  function handleSelect(hex) {
    setCurrent(hex);
    applyAccentColor(hex);
  }

  return (
    <div className="mb-5 rounded-xl border border-charcoal-700/80 bg-charcoal-900/60 p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-white">Appearance & Accent Theme</h3>
          <p className="text-xs text-charcoal-400">Universal accent theme applied to navigation, buttons, and visualizers.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-zinc-300">{current.toUpperCase()}</span>
          <div
            className="h-5 w-5 rounded-full border border-white/20 shadow-sm"
            style={{ backgroundColor: current }}
          />
        </div>
      </div>

      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
        {THEME_PRESETS.map((preset) => {
          const isSelected = current.toLowerCase() === preset.hex.toLowerCase();
          return (
            <button
              key={preset.id}
              type="button"
              onClick={() => handleSelect(preset.hex)}
              className={`flex flex-col items-center gap-1.5 rounded-lg border p-2 transition-all ${
                isSelected
                  ? "border-white/60 bg-charcoal-800 shadow-md ring-1 ring-white/30"
                  : "border-charcoal-800 bg-charcoal-900/40 hover:border-charcoal-700 hover:bg-charcoal-800/50"
              }`}
            >
              <div
                className="h-6 w-6 rounded-full border border-black/30 shadow-inner"
                style={{ backgroundColor: preset.hex }}
              />
              <span className="text-[10.5px] font-medium text-charcoal-300">{preset.name.split(" ")[1] || preset.name}</span>
            </button>
          );
        })}
      </div>

      <div className="mt-3.5 pt-3 border-t border-charcoal-800/80 flex items-center justify-between text-xs">
        <span className="text-charcoal-400">Custom Color Picker</span>
        <div className="flex items-center gap-2">
          <input
            type="color"
            value={current}
            onChange={(e) => handleSelect(e.target.value)}
            className="h-7 w-9 cursor-pointer rounded border border-charcoal-700 bg-charcoal-800 p-0.5 outline-none"
            title="Pick custom color"
          />
          <input
            type="text"
            value={current}
            onChange={(e) => {
              const val = e.target.value;
              if (val.startsWith("#")) handleSelect(val);
            }}
            placeholder="#3B82F6"
            className="w-24 rounded border border-charcoal-700 bg-charcoal-800 px-2 py-1 font-mono text-xs text-white outline-none focus:border-white/50"
          />
        </div>
      </div>
    </div>
  );
}

export default function SettingsModal({ open, onClose }) {
  const urlSection = new URLSearchParams(window.location.search).get("section");
  const [section, setSection] = useState(urlSection || "General");
  // Granted file-access roots (backend/app/file_access.py). Loaded when the
  // Files section is first opened rather than on modal mount, so opening
  // Settings for an unrelated reason costs no filesystem work.
  const [fileRoots, setFileRoots] = useState([]);
  const [fileRootsError, setFileRootsError] = useState("");

  useEffect(() => {
    if (section !== "Files") return;
    listFileRoots()
      .then((data) => { setFileRoots(data.roots); setFileRootsError(""); })
      .catch((err) => setFileRootsError(err.message));
  }, [section]);
  const [saveError, setSaveError] = useState("");
  // Autonomy + Agents sections. Both load lazily on first visit, same as
  // Files above -- /capabilities walks the live tool registry and
  // /acp/agents probes each configured agent's PATH entry, neither of which
  // an unrelated trip to Settings should pay for.
  const [capabilities, setCapabilities] = useState(null);
  const [acpAgents, setAcpAgents] = useState([]);
  const [acpSuggested, setAcpSuggested] = useState([]);
  const [acpBusy, setAcpBusy] = useState(null);

  // Secrets section. Only names ever come back from the backend.
  const [secrets, setSecrets] = useState(null);
  const [secretName, setSecretName] = useState("");
  const [secretValue, setSecretValue] = useState("");
  const [secretBusy, setSecretBusy] = useState(false);

  const refreshSecrets = useCallback(async () => {
    try {
      setSecrets(await listSecrets());
    } catch (err) {
      setSaveError(err.message);
    }
  }, []);

  async function addSecret() {
    setSecretBusy(true);
    setSaveError("");
    try {
      await putSecret(secretName.trim(), secretValue);
      setSecretName("");
      setSecretValue("");
      await refreshSecrets();
    } catch (err) {
      setSaveError(err.message);
    } finally {
      setSecretBusy(false);
    }
  }

  // Canvas section.
  // TypeSafe/Jev. The key is held only long enough to POST it and is cleared
  // on success -- it is a credential and does not belong in the DOM.
  const [typeSafe, setTypeSafe] = useState(null);
  const [typeSafeKey, setTypeSafeKey] = useState("");
  const [typeSafeNote, setTypeSafeNote] = useState("");
  const [typeSafeSaving, setTypeSafeSaving] = useState(false);
  const [canvas, setCanvas] = useState(null);
  const [canvasUrl, setCanvasUrl] = useState("");
  const [canvasToken, setCanvasToken] = useState("");
  // Apple Calendar section.
  const [apple, setApple] = useState(null);
  const [appleId, setAppleId] = useState("");
  const [applePassword, setApplePassword] = useState("");
  const [appleBusy, setAppleBusy] = useState(false);
  const [appleNote, setAppleNote] = useState("");

  const refreshApple = useCallback(async () => {
    try {
      const data = await getAppleCalendarStatus();
      setApple(data);
      if (data.apple_id) setAppleId(data.apple_id);
    } catch (err) {
      setSaveError(err.message);
    }
  }, []);

  const [canvasFeed, setCanvasFeed] = useState("");
  const [canvasMethod, setCanvasMethod] = useState("token");
  const [canvasBusy, setCanvasBusy] = useState("");
  const [canvasNote, setCanvasNote] = useState("");

  // Populates the target picker for the Apple Calendar push. Failing is fine
  // and common (Apple Calendar simply isn't connected), so it stays quiet.
  const [appleCalendars, setAppleCalendars] = useState([]);

  const refreshCanvas = useCallback(async () => {
    listAppleCalendars().then(setAppleCalendars).catch(() => setAppleCalendars([]));
    try {
      const data = await getCanvasStatus();
      setCanvas(data);
      if (data.canvas?.base_url) setCanvasUrl(data.canvas.base_url);
      // Open on whichever method is already in use, so someone who connected by
      // feed doesn't come back to a token form that looks disconnected.
      if (data.canvas?.source === "feed") setCanvasMethod("feed");
    } catch (err) {
      setSaveError(err.message);
    }
  }, []);

  async function connectCanvas() {
    setCanvasBusy("connect");
    setCanvasNote("");
    setSaveError("");
    try {
      const result = await saveCanvasCredentials(canvasUrl.trim(), canvasToken.trim());
      setCanvasToken("");
      setCanvasNote(`Connected — ${result.courses?.length || 0} active course(s) found.`);
      await refreshCanvas();
    } catch (err) {
      setSaveError(err.message);
    } finally {
      setCanvasBusy("");
    }
  }

  async function saveTypeSafe() {
    setTypeSafeSaving(true);
    setTypeSafeNote("");
    setSaveError("");
    try {
      const result = await saveTypeSafeKey(typeSafeKey.trim());
      setTypeSafeKey("");            // a credential; do not leave it in the DOM
      setTypeSafe(result);
      setTypeSafeNote(result.verified ? "Connected and verified." : "Saved.");
    } catch (err) {
      setSaveError(err.message);
    } finally {
      setTypeSafeSaving(false);
    }
  }

  async function connectAppleCalendar() {
    setAppleBusy(true);
    setAppleNote("");
    setSaveError("");
    try {
      const result = await saveAppleCalendarCredentials(appleId.trim(), applePassword.trim());
      setApplePassword("");   // a credential; don't leave it sitting in the DOM
      setApple(result);
      setAppleNote(
        `Connected — ${result.calendars?.length || 0} calendar(s): ` +
        (result.calendars || []).map((c) => c.name).join(", ")
      );
    } catch (err) {
      setSaveError(err.message);
    } finally {
      setAppleBusy(false);
    }
  }

  async function disconnectApple() {
    setAppleBusy(true);
    try {
      setApple(await disconnectAppleCalendar());
      setAppleNote("Disconnected. The app-specific password was deleted from the vault.");
    } catch (err) {
      setSaveError(err.message);
    } finally {
      setAppleBusy(false);
    }
  }

  async function connectCanvasFeed() {
    setCanvasBusy("feed");
    setCanvasNote("");
    setSaveError("");
    try {
      const result = await saveCanvasFeed(canvasFeed.trim());
      setCanvasFeed("");   // it is a credential; don't leave it sitting in the DOM
      setCanvasNote(
        `Feed connected — ${result.found} item(s) across ${result.courses?.length || 0} course(s).`
      );
      await refreshCanvas();
    } catch (err) {
      setSaveError(err.message);
    } finally {
      setCanvasBusy("");
    }
  }

  async function syncCanvasNow() {
    setCanvasBusy("sync");
    setCanvasNote("");
    setSaveError("");
    try {
      const result = await runCanvasSync();
      setCanvasNote(
        `Synced ${result.seen} assignment(s): ${result.new.length} new, ` +
        `${result.due_changed.length} with changed due dates, ${result.pending} still open.`
      );
      await refreshCanvas();
    } catch (err) {
      setSaveError(err.message);
    } finally {
      setCanvasBusy("");
    }
  }

  async function patchCanvas(patch) {
    try {
      setCanvas(await saveCanvasSettings(patch));
    } catch (err) {
      setSaveError(err.message);
    }
  }

  const refreshAcp = useCallback(async () => {
    try {
      const data = await listAcpAgents();
      setAcpAgents(data.agents || []);
      setAcpSuggested(data.suggested || []);
    } catch (err) {
      setSaveError(err.message);
    }
  }, []);

  useEffect(() => {
    if (section === "Autonomy") getCapabilities().then(setCapabilities).catch(() => setCapabilities(null));
    if (section === "Agents") refreshAcp();
    if (section === "Models") getTypeSafeStatus().then(setTypeSafe).catch(() => setTypeSafe(null));
    if (section === "Canvas") refreshCanvas();
    if (section === "Calendar") refreshApple();
    if (section === "Secrets") refreshSecrets();
  }, [section, refreshAcp, refreshCanvas, refreshSecrets, refreshApple]);

  async function addAcpAgent(preset) {
    setSaveError("");
    try {
      await createAcpAgent({ name: preset.name, command: preset.command, args: preset.args || [] });
      await refreshAcp();
    } catch (err) {
      setSaveError(err.message);
    }
  }

  async function removeAcpAgent(id) {
    try {
      await deleteAcpAgent(id);
      await refreshAcp();
    } catch (err) {
      setSaveError(err.message);
    }
  }

  async function toggleAcpAgent(id, enabled) {
    try {
      await toggleAcpAgentApi(id, enabled);
      await refreshAcp();
    } catch (err) {
      setSaveError(err.message);
    }
  }

  async function connectAcp(id) {
    setAcpBusy(id);
    setSaveError("");
    try {
      await connectAcpAgent(id);
    } catch (err) {
      setSaveError(err.message);
    } finally {
      setAcpBusy(null);
      await refreshAcp();
    }
  }

  const [status, setStatus] = useState({ gemini_configured: false, openrouter_configured: false });
  const [openrouterKey, setOpenrouterKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedMessage, setSavedMessage] = useState("");
  const [app, setApp] = useState({
    theme: "dark",
    desktop_notifications: true,
    sound_effects: true,
    always_on_top: false,
    mascot_enabled: false,
    proactive_checkins: true,
    auto_launch: false,
  });
  const [models, setModels] = useState([]);
  const [showFullCatalog, setShowFullCatalog] = useState(false);
  const [stats, setStats] = useState(null);
  const [mcpServers, setMcpServers] = useState([]);
  const [mcpLoading, setMcpLoading] = useState(false);
  const [mcpError, setMcpError] = useState("");
  const [mcpExpanded, setMcpExpanded] = useState(null);
  const [mcpForm, setMcpForm] = useState({ name: "", command: "", args: "", url: "" });
  const [mcpAdding, setMcpAdding] = useState(false);
  const [voices, setVoices] = useState([]);
  const [voiceLoading, setVoiceLoading] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const [voiceName, setVoiceName] = useState("");
  const [voiceFile, setVoiceFile] = useState(null);
  const [voiceAdding, setVoiceAdding] = useState(false);
  const [previewingId, setPreviewingId] = useState(null);
  const voiceFileInputRef = useRef(null);
  // Push-to-talk hotkey (task: "manual push-to-talk hotkey as a backup to
  // wake-word"). Local text-input state, separate from `app.push_to_talk_
  // hotkey`, so a bad/partial accelerator string being typed doesn't
  // register anything until "Apply" -- registering on every keystroke
  // would spam globalShortcut with invalid strings and misleadingly error
  // on every partial edit.
  const [hotkeyInput, setHotkeyInput] = useState("");
  const [hotkeyError, setHotkeyError] = useState("");
  const [hotkeySaving, setHotkeySaving] = useState(false);
  const [addModelType, setAddModelType] = useState("apikey");
  const [apiProviderMode, setApiProviderMode] = useState("openrouter");
  const [connectedAccounts, setConnectedAccounts] = useState({ google: false, openai: false, anthropic: false, github: false });
  const [addModelForm, setAddModelForm] = useState({
    name: "",
    modelId: "",
    category: "general_writing",
    apiBase: "",
    apiKey: "",
  });
  const [addModelAdding, setAddModelAdding] = useState(false);
  const [addModelError, setAddModelError] = useState("");
  // Models an OpenAI-compatible endpoint reports at /v1/models. null = not asked
  // yet, [] = asked and it listed none -- which are different states to show.
  const [discovered, setDiscovered] = useState(null);
  const [discovering, setDiscovering] = useState(false);
  const [discoverError, setDiscoverError] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [orQuery, setOrQuery] = useState("");
  const [orModels, setOrModels] = useState([]);
  const [orLoading, setOrLoading] = useState(false);
  const [pullName, setPullName] = useState("");
  const [pulling, setPulling] = useState(false);
  const [pullStatus, setPullStatus] = useState(null);
  const [pullError, setPullError] = useState("");
  // Routing tab: persistent per-category manual override (task: "let the
  // user manually specify which model handles a category ... as an
  // override on top of automatic routing") -- routingOverrides is
  // {category: model_id}, missing = automatic for that category.
  const [routingCategories, setRoutingCategories] = useState([]);
  const [routingOverrides, setRoutingOverrides] = useState({});
  const [routingSavingCategory, setRoutingSavingCategory] = useState(null);
  // Skills tab (task 5: real "Add Skill" flow, mirroring Add Model, instead
  // of hand-editing backend/app/skills/*.md) -- addSkillForm.keywords is
  // kept as a single comma-separated string in the UI (matches the .md
  // header's own "a, b, c" shape) and only split into an array right before
  // the createSkill() call.
  const [skillsList, setSkillsList] = useState([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [addSkillForm, setAddSkillForm] = useState({
    name: "",
    description: "",
    keywords: "",
    body: "",
    preferredModelId: "",
  });
  const [addSkillAdding, setAddSkillAdding] = useState(false);
  const [addSkillError, setAddSkillError] = useState("");

  async function refreshSkills() {
    setSkillsLoading(true);
    try {
      setSkillsList(await listSkills());
    } catch {
      // backend not reachable yet
    } finally {
      setSkillsLoading(false);
    }
  }

  async function refreshModels() {
    try {
      setModels(await listModels());
    } catch {
      // backend not reachable yet
    }
  }

  async function refreshVoices() {
    setVoiceLoading(true);
    try {
      setVoices(await listTtsVoices());
    } catch {
      // backend not reachable yet
    } finally {
      setVoiceLoading(false);
    }
  }

  async function refreshMcpServers() {
    setMcpLoading(true);
    try {
      setMcpServers(await listMcpServers());
    } catch {
      // backend not reachable yet
    } finally {
      setMcpLoading(false);
    }
  }

  useEffect(() => {
    if (!open) return;
    setSavedMessage("");
    getSettings().then(setStatus).catch(() => {});
    getAppSettings()
      .then((data) => {
        setApp(data);
        setHotkeyInput(data.push_to_talk_hotkey || "");
      })
      .catch(() => {});
    listModels().then(setModels).catch(() => {});
    getWorkspaceStats().then(setStats).catch(() => {});
    refreshMcpServers();
    refreshVoices();
    refreshSkills();
    listRoutingCategories().then(setRoutingCategories).catch(() => {});
    getRoutingOverrides().then(setRoutingOverrides).catch(() => {});
  }, [open]);

  async function handleRoutingOverrideChange(category, modelId) {
    setRoutingSavingCategory(category);
    try {
      const updated = await setRoutingOverride(category, modelId || null);
      setRoutingOverrides(updated);
    } finally {
      setRoutingSavingCategory(null);
    }
  }

  // Backs the OpenRouter browse/search list in Add Model: fetches (or
  // re-searches) the live free-tier roster, debounced while typing so it
  // doesn't hit the backend on every keystroke.
  useEffect(() => {
    if (!open || section !== "Models" || (addModelType !== "openrouter" && addModelType !== "apikey")) return;
    setOrLoading(true);
    const id = setTimeout(() => {
      searchOpenRouterModels(orQuery)
        .then(setOrModels)
        .catch(() => setOrModels([]))
        .finally(() => setOrLoading(false));
    }, 250);
    return () => clearTimeout(id);
  }, [open, section, addModelType, orQuery]);

  if (!open) return null;

  async function patchApp(patch) {
    setSaveError("");
    const previous = Object.fromEntries(Object.keys(patch).map(key => [key, app[key]]));
    setApp((prev) => ({ ...prev, ...patch }));
    const snakePatch = {};
    for (const [k, v] of Object.entries(patch)) snakePatch[k] = v;
    try {
      await updateAppSettings(snakePatch);
    // Real OS-level registration lives in the Electron main process (see
    // electron/preload.cjs) -- undefined outside Electron (e.g. a plain
    // browser dev tab), where there's no OS startup entry to register.
    // Either toggle has to re-register the login item: the pet-only choice is
    // carried as a launch argument on that entry, so changing it without
    // rewriting the entry would leave Windows starting the old shape.
    if ("launch_at_login" in patch || "miniplayer_at_login" in patch) {
      const enabled = "launch_at_login" in patch ? patch.launch_at_login : app.launch_at_login;
      const petOnly = "miniplayer_at_login" in patch
        ? patch.miniplayer_at_login
        : app.miniplayer_at_login !== false;
      await window.electronAPI?.setLaunchAtLogin?.(enabled, petOnly);
    }
    // Keep the legacy preference wired to the compact character window for
    // existing settings databases. The old free-roaming desktop window is no
    // longer created; this action always stays inside Nova's miniplayer.
    if ("desktop_pet_enabled" in patch) {
      if (patch.desktop_pet_enabled) await window.electronAPI?.openDesktopPet?.();
      else await window.electronAPI?.closeDesktopPet?.();
    }
    } catch (error) {
      setApp(current => ({ ...current, ...previous }));
      setSaveError(error.message || "Could not save this setting. Please try again.");
    }
  }

  /** Registers the accelerator with the OS first (electron/main.cjs's
   * globalShortcut.register) and only persists it if that actually
   * succeeded -- an invalid or already-taken combo should show the real
   * error, not silently save a hotkey that isn't actually listening for
   * anything. */
  async function handleApplyHotkey() {
    setHotkeySaving(true);
    setHotkeyError("");
    try {
      const result = await window.electronAPI?.registerPushToTalkHotkey?.(hotkeyInput.trim());
      if (result && !result.success) {
        setHotkeyError(result.error || "Could not register that hotkey.");
        return;
      }
      await patchApp({ push_to_talk_hotkey: hotkeyInput.trim() });
    } finally {
      setHotkeySaving(false);
    }
  }

  async function handleSaveKeys() {
    setSaving(true);
    setSavedMessage("");
    try {
      const newStatus = await saveSettings({ openrouterApiKey: openrouterKey });
      setStatus(newStatus);
      setOpenrouterKey("");
      setSavedMessage("Saved.");
    } catch (err) {
      setSavedMessage(`Failed to save: ${err.message}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleToggleModel(model) {
    const updated = await toggleModel(model.id, !model.enabled);
    setModels(updated);
  }

  async function handleDeleteCustomModel(model) {
    if (!window.confirm(`Remove "${model.name}" from routing?`)) return;
    const rowId = model.id.slice("custom:".length);
    await deleteCustomModel(rowId);
    await refreshModels();
  }

  async function handleAddSkill() {
    const name = addSkillForm.name.trim();
    const body = addSkillForm.body.trim();
    if (!name || !body) return;
    setAddSkillAdding(true);
    setAddSkillError("");
    try {
      await createSkill({
        name,
        description: addSkillForm.description.trim(),
        keywords: addSkillForm.keywords.split(",").map((k) => k.trim()).filter(Boolean),
        body,
        preferredModelId: addSkillForm.preferredModelId || null,
      });
      setAddSkillForm({ name: "", description: "", keywords: "", body: "", preferredModelId: "" });
      await refreshSkills();
    } catch (err) {
      setAddSkillError(err.message);
    } finally {
      setAddSkillAdding(false);
    }
  }

  async function handleDeleteSkill(skill) {
    if (!window.confirm(`Remove the "${skill.name}" skill?`)) return;
    await deleteSkill(skill.name);
    await refreshSkills();
  }

  function selectOpenRouterModel(m) {
    setAddModelForm((f) => ({ ...f, modelId: m.id, name: f.name || m.name }));
  }

  async function handleAddOpenRouterModel() {
    const modelId = addModelForm.modelId.trim();
    if (!modelId) return;
    setAddModelAdding(true);
    setAddModelError("");
    try {
      await createCustomModel({
        name: addModelForm.name.trim() || modelId,
        provider: "openrouter",
        modelId,
        category: addModelForm.category,
      });
      setAddModelForm((f) => ({ ...f, name: "", modelId: "" }));
      await refreshModels();
    } catch (err) {
      setAddModelError(err.message);
    } finally {
      setAddModelAdding(false);
    }
  }

  async function fetchEndpointModels() {
    const apiBase = addModelForm.apiBase.trim();
    if (!apiBase) return;
    setDiscovering(true);
    setDiscoverError("");
    setDiscovered(null);
    try {
      const ids = await discoverCustomModels(apiBase, addModelForm.apiKey.trim());
      setDiscovered(ids);
      setModelFilter("");
      if (ids.length === 0) {
        setDiscoverError("That endpoint answered but listed no models.");
      }
    } catch (err) {
      setDiscoverError(err.message);
    } finally {
      setDiscovering(false);
    }
  }

  async function handleAddCustomModel() {
    const modelId = addModelForm.modelId.trim();
    const apiBase = addModelForm.apiBase.trim();
    if (!modelId || !apiBase) return;
    setAddModelAdding(true);
    setAddModelError("");
    try {
      await createCustomModel({
        name: addModelForm.name.trim() || modelId,
        provider: "custom",
        modelId,
        category: addModelForm.category,
        apiBase,
        apiKey: addModelForm.apiKey.trim(),
      });
      // Keep the base URL, key and fetched list: adding several models from one
      // gateway is the normal case, not the exception.
      setAddModelForm((f) => ({ ...f, name: "", modelId: "" }));
      await refreshModels();
    } catch (err) {
      setAddModelError(err.message);
    } finally {
      setAddModelAdding(false);
    }
  }

  async function handlePullOllamaModel() {
    const name = pullName.trim();
    if (!name) return;
    setPulling(true);
    setPullError("");
    setPullStatus({ status: "starting…" });
    try {
      await pullOllamaModel(
        { name, category: addModelForm.category, displayName: addModelForm.name.trim() || name },
        (event) => {
          if (event.type === "progress") {
            setPullStatus(event);
          } else if (event.type === "error") {
            setPullError(event.message);
          } else if (event.type === "done") {
            setPullStatus({ status: "done" });
          }
        }
      );
      setPullName("");
      setAddModelForm((f) => ({ ...f, name: "" }));
      await refreshModels();
    } catch (err) {
      setPullError(err.message);
    } finally {
      setPulling(false);
    }
  }

  async function handleAddMcpServer() {
    const name = mcpForm.name.trim();
    const command = mcpForm.command.trim();
    const url = (mcpForm.url || "").trim();
    // A URL means a remote server and the command field is irrelevant; a
    // command means a local one. Requiring both made the hosted servers --
    // which is most of the interesting ones now -- unaddable from here.
    if (!name || (!command && !url)) return;
    setMcpAdding(true);
    setMcpError("");
    try {
      const args = mcpForm.args.trim() ? mcpForm.args.trim().split(/\s+/) : [];
      await createMcpServer(
        url ? { name, transport: "http", url } : { name, command, args }
      );
      setMcpForm({ name: "", command: "", args: "", url: "" });
      await refreshMcpServers();
    } catch (err) {
      setMcpError(err.message);
    } finally {
      setMcpAdding(false);
    }
  }

  async function handleDeleteMcpServer(id) {
    if (!window.confirm("Remove this MCP server?")) return;
    await deleteMcpServer(id);
    await refreshMcpServers();
  }

  async function handleToggleMcpServer(server) {
    await toggleMcpServer(server.id, !server.enabled);
    await refreshMcpServers();
  }

  async function handleSelectVoice(voiceId) {
    await patchApp({ tts_voice_id: voiceId });
  }

  async function handleAddVoice() {
    const name = voiceName.trim();
    if (!name || !voiceFile) return;
    setVoiceAdding(true);
    setVoiceError("");
    try {
      const created = await createTtsVoice(name, voiceFile);
      setVoiceName("");
      setVoiceFile(null);
      if (voiceFileInputRef.current) voiceFileInputRef.current.value = "";
      await refreshVoices();
      await handleSelectVoice(String(created.id));
    } catch (err) {
      setVoiceError(err.message);
    } finally {
      setVoiceAdding(false);
    }
  }

  async function handleDeleteVoice(voice) {
    if (!window.confirm(`Delete the cloned voice "${voice.name}"?`)) return;
    await deleteTtsVoice(voice.id);
    await refreshVoices();
    if (app?.tts_voice_id === voice.id) {
      setApp((prev) => ({ ...prev, tts_voice_id: "default" }));
    }
  }

  async function handlePreviewVoice(voice) {
    setPreviewingId(voice.id);
    try {
      const blob = await textToSpeech(
        `Hi, this is the "${voice.name}" voice.`,
        voice.id
      );
      await playTtsAudio(blob, { onEnd: () => setPreviewingId(null) });
    } catch (err) {
      setVoiceError(err.message);
      setPreviewingId(null);
    }
  }

  return (
    // Full-bleed on a phone. The centred dialog with its 16px inset was
    // fighting for width with a 190px sidebar, which left the actual settings
    // in a column too narrow to hold a text input -- fields ran off the right
    // edge, and adding an account from a phone was impossible.
    <div className="settings-modal fixed inset-0 z-50 flex items-center justify-center bg-[#06120f]/80 sm:p-4" onClick={onClose}>
      <div
        className="flex h-full max-h-full w-full flex-col overflow-hidden border-[#1d4d3c] bg-[#0b1915] shadow-[0_24px_100px_rgba(0,0,0,.55)] sm:h-[600px] sm:max-h-[90vh] sm:max-w-3xl sm:flex-row sm:rounded-xl sm:border"
        onClick={(e) => e.stopPropagation()}
      >
        {/* A grouped picker on a phone, a grouped rail on a desktop.
            A horizontal row of seventeen chips was organised only in the
            sense that they were all visible if you swiped far enough. The
            native select gets real headings from optgroup, renders as the
            platform's own wheel, and takes one tap instead of a swipe and a
            tap. */}
        <div className="shrink-0 border-b border-charcoal-800 bg-[#091310] p-2 sm:w-[190px] sm:overflow-y-auto sm:border-b-0 sm:border-r sm:p-3">
          <select
            aria-label="Settings section"
            value={section}
            onChange={(e) => setSection(e.target.value)}
            className="w-full rounded-md border border-charcoal-600 bg-charcoal-900 px-2.5 py-2 text-sm font-medium text-charcoal-100 outline-none focus:border-emerald-500 sm:hidden"
          >
            {SECTION_GROUPS.map(([group, items]) =>
              group ? (
                <optgroup key={group} label={group}>
                  {items.map((s) => <option key={s} value={s}>{s}</option>)}
                </optgroup>
              ) : (
                items.map((s) => <option key={s} value={s}>{s}</option>)
              )
            )}
          </select>

          <div className="hidden sm:block">
            {SECTION_GROUPS.map(([group, items]) => (
              <div key={group || "end"} className={group ? "mb-2" : "mt-3 border-t border-charcoal-800 pt-2"}>
                {group && (
                  <p className="mb-1 px-1 text-[10px] font-semibold uppercase tracking-wide text-charcoal-600">
                    {group}
                  </p>
                )}
                {items.map((s) => (
                  <button
                    key={s}
                    onClick={() => setSection(s)}
                    style={section === s ? { backgroundColor: "var(--accent)", color: "#fff" } : {}}
                    className={`mb-0.5 block w-full rounded-md px-2 py-1.5 text-left text-xs font-medium transition-colors ${
                      section === s ? "font-semibold shadow-sm" : "text-charcoal-400 hover:bg-charcoal-800 hover:text-charcoal-200"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            ))}
            <p className="px-1 pt-2 text-[10.5px] text-charcoal-600">Nova v2.0</p>
          </div>
        </div>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between border-b border-charcoal-800 px-4 py-3 sm:px-5">
            <h2 className="text-sm font-semibold text-charcoal-100">{section}</h2>
            <button onClick={onClose} className="text-charcoal-400 hover:text-charcoal-200">
              ✕
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-5">
            {saveError && <p role="alert" className="mb-3 rounded border border-rose-400/30 p-2 text-xs text-rose-300">{saveError}</p>}
            {section === "Notifications" && <NotificationsPanel />}
            {section === "Access" && <AccessPanel />}
            {section === "Email" && <EmailPanel />}
            {section === "Accounts" && <AccountsPanel />}
            {section === "Sentinel" && <SentinelPanel />}
            {section === "General" && app && (
              <div>
                <AccentColorPicker />
                <ToggleRow
                  label="Automatic routing"
                  desc="Route each request to whichever connected model fits it best."
                  on={app.auto_route}
                  onClick={() => patchApp({ auto_route: !app.auto_route })}
                />
                {!app.auto_route && <label className="mb-3 flex items-center justify-between gap-3 text-xs text-charcoal-300">Default model
                  <select aria-label="Default model" value={app.default_router === "Automatic" ? "ollama:qwen3.5:4b" : app.default_router} onChange={e => patchApp({ default_router: e.target.value })} className="max-w-[220px] rounded border border-charcoal-600 bg-charcoal-900 p-2">
                    {models.filter(model => model.enabled).map(model => <option key={model.id} value={model.id}>{model.name}</option>)}
                  </select>
                </label>}
                <ToggleRow
                  label="Prefer local models"
                  desc="When a category's chain has both a local Ollama step and cloud options, try the local one first."
                  on={app.prefer_local}
                  onClick={() => patchApp({ prefer_local: !app.prefer_local })}
                />
                <ToggleRow
                  label="Enter sends message"
                  desc="Off uses Shift+Enter for a newline, click Send to submit."
                  on={app.enter_sends}
                  onClick={() => patchApp({ enter_sends: !app.enter_sends })}
                />
                <ToggleRow
                  label="Keep window always on top"
                  desc="When turned off, N.O.V.A. layers naturally behind other windows on your desktop instead of floating above."
                  on={Boolean(app.always_on_top)}
                  onClick={() => {
                    const next = !app.always_on_top;
                    patchApp({ always_on_top: next });
                    window.electronAPI?.setAlwaysOnTop?.(next);
                  }}
                />
                <ToggleRow
                  label="Launch at login"
                  desc="Registers N.O.V.A. to start automatically when you sign in to Windows."
                  on={app.launch_at_login}
                  onClick={() => patchApp({ launch_at_login: !app.launch_at_login })}
                />
                <ToggleRow
                  label="Launch in Miniplayer mode"
                  desc="Opens the compact optical acoustic sphere miniplayer instead of the full window. Voice, tools, and background services stay fully active."
                  on={app.miniplayer_at_login !== false}
                  onClick={() => patchApp({ miniplayer_at_login: app.miniplayer_at_login === false })}
                />
                <ToggleRow
                  label="Cross-check coding answers"
                  desc="For coding requests Claude Code CLI answers, a real second call hands that answer to Codex CLI for review and folds its verdict into the reply. Roughly doubles time/cost for coding requests."
                  on={app.handoff_review_enabled}
                  onClick={() => patchApp({ handoff_review_enabled: !app.handoff_review_enabled })}
                />
                <ToggleRow
                  label="Homework: solve instead of tutor"
                  desc="In a Homework Mode conversation, answer the question outright and show the working. Off walks you through it one step at a time instead."
                  on={app.homework_mode === "solve"}
                  onClick={() => patchApp({ homework_mode: app.homework_mode === "solve" ? "tutor" : "solve" })}
                />
                <div className="py-3 border-b border-charcoal-800/60">
                  <div className="flex items-center justify-between mb-1.5">
                    <div>
                      <p className="text-sm font-medium text-charcoal-200">Browser Automation Mode</p>
                      <p className="text-xs text-charcoal-400">
                        Choose whether Nova operates visibly on your desktop or silently in the background.
                      </p>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-2 mt-2">
                    <button
                      type="button"
                      onClick={() => patchApp({ browser_visibility_mode: "visible" })}
                      className={`p-2.5 rounded-lg border text-left text-xs transition-all ${
                        (app.browser_visibility_mode || "visible") === "visible"
                          ? "border-cyan-500/50 bg-cyan-500/10 text-cyan-200 ring-1 ring-cyan-500/30"
                          : "border-charcoal-800 bg-charcoal-900 text-charcoal-400 hover:bg-charcoal-800"
                      }`}
                    >
                      <div className="font-semibold flex items-center gap-1.5 text-white">
                        <span>👁️ Visible Window Mode</span>
                      </div>
                      <p className="text-[11px] text-charcoal-400 mt-1 leading-snug">
                        Watch Nova open Edge/Chrome, click through Canvas, and solve questions in real time.
                      </p>
                    </button>
                    <button
                      type="button"
                      onClick={() => patchApp({ browser_visibility_mode: "silent" })}
                      className={`p-2.5 rounded-lg border text-left text-xs transition-all ${
                        app.browser_visibility_mode === "silent" || app.browser_visibility_mode === "headless"
                          ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-200 ring-1 ring-emerald-500/30"
                          : "border-charcoal-800 bg-charcoal-900 text-charcoal-400 hover:bg-charcoal-800"
                      }`}
                    >
                      <div className="font-semibold flex items-center gap-1.5 text-white">
                        <span>🕶️ Silent Background (Gaming Safe)</span>
                      </div>
                      <p className="text-[11px] text-charcoal-400 mt-1 leading-snug">
                        Decoupled CDP session. Zero mouse cursor hijacking—play games or stream uninterrupted!
                      </p>
                    </button>
                  </div>
                </div>
                <div className="pt-4">
                  <label className="mb-1.5 block text-xs text-charcoal-500">Daily API spend limit (USD)</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    value={app.spend_cap_usd}
                    onChange={(e) => patchApp({ spend_cap_usd: parseFloat(e.target.value) || 0 })}
                    className="w-32 rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                  />
                  <p className="mt-1 text-[11px] text-charcoal-600">
                    Applies immediately. Subscription usage is tracked separately from API spending.
                  </p>
                </div>
              </div>
            )}

            {section === "Autonomy" && app && (
              <div className="space-y-5">
                <div>
                  <p className="text-sm text-charcoal-200">How much Nova does on its own</p>
                  <p className="mt-1 text-xs text-charcoal-500">
                    Nova has real tools — a shell, the filesystem, the browser, the mouse and keyboard.
                    This decides how much of that it uses without checking with you first.
                  </p>
                </div>
                <div className="space-y-2">
                  {AUTONOMY_LEVELS.map((level) => {
                    const active = (app.autonomy_level || "full") === level.id;
                    return (
                      <button
                        key={level.id}
                        type="button"
                        onClick={() => patchApp({ autonomy_level: level.id })}
                        aria-pressed={active}
                        className={`w-full rounded-lg border p-3 text-left transition-colors ${
                          active
                            ? "border-emerald-500/60 bg-emerald-500/[0.07]"
                            : "border-charcoal-700 hover:border-charcoal-600 hover:bg-charcoal-800/40"
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className={`h-3 w-3 shrink-0 rounded-full border-2 ${
                              active ? "border-emerald-400 bg-emerald-400" : "border-charcoal-600"
                            }`}
                            aria-hidden="true"
                          />
                          <span className={`text-sm font-medium ${active ? "text-emerald-200" : "text-charcoal-200"}`}>
                            {level.label}
                          </span>
                          <span className="text-xs text-charcoal-500">— {level.summary}</span>
                        </div>
                        <p className="mt-1.5 pl-5 text-xs leading-relaxed text-charcoal-500">{level.detail}</p>
                      </button>
                    );
                  })}
                </div>
                <ToggleRow
                  label="Give Nova tools at all"
                  desc="Off leaves a plain conversational model: it can talk about your files and your machine, but it cannot look at or change either."
                  on={app.agent_tools_enabled !== false}
                  onClick={() => patchApp({ agent_tools_enabled: app.agent_tools_enabled === false })}
                />

                <div className="border-t border-charcoal-800 pt-5">
                  <p className="text-sm text-charcoal-200">Nova's cursor</p>
                  <p className="mt-1 text-xs leading-relaxed text-charcoal-500">
                    With its own pointer, Nova draws a second cursor tagged "Nova" and clicks through
                    the app itself, so your mouse stays yours and you can keep watching or playing
                    while it works. It never draws over, clicks into, or types into a fullscreen game.
                    To stop Nova at any moment, press Ctrl+Alt+Esc or throw your mouse into a screen
                    corner.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {POINTER_MODES.map((mode) => {
                      const active = (app.desktop_pointer || "own") === mode.id;
                      return (
                        <button
                          key={mode.id}
                          type="button"
                          aria-pressed={active}
                          onClick={() => patchApp({ desktop_pointer: mode.id })}
                          className={`rounded-md border px-2.5 py-1.5 text-xs transition-colors ${
                            active
                              ? "border-emerald-500/60 bg-emerald-500/[0.07] text-emerald-200"
                              : "border-charcoal-700 text-charcoal-400 hover:border-charcoal-600"
                          }`}
                        >
                          {mode.label}
                        </button>
                      );
                    })}
                  </div>
                  {(app.desktop_pointer || "own") === "own" && (
                    <div className="mt-3">
                      <p className="text-xs text-charcoal-400">
                        When an app only listens to your real mouse
                      </p>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {BORROW_POLICIES.map((policy) => {
                          const active = (app.desktop_borrow_mouse || "ask") === policy.id;
                          return (
                            <button
                              key={policy.id}
                              type="button"
                              aria-pressed={active}
                              onClick={() => patchApp({ desktop_borrow_mouse: policy.id })}
                              className={`rounded-md border px-2.5 py-1.5 text-xs transition-colors ${
                                active
                                  ? "border-emerald-500/60 bg-emerald-500/[0.07] text-emerald-200"
                                  : "border-charcoal-700 text-charcoal-400 hover:border-charcoal-600"
                              }`}
                            >
                              {policy.label}
                            </button>
                          );
                        })}
                      </div>
                      <p className="mt-1.5 text-[11px] text-charcoal-600">{
                        (app.desktop_borrow_mouse || "ask") === "ask"
                          ? "Nova asks first. If you say yes, your mouse jumps there, clicks, and comes straight back."
                          : "Nova tells you it could not click, and never touches your mouse."
                      }</p>
                    </div>
                  )}
                  <p className="mt-4 text-xs text-charcoal-400">How fast it moves</p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {CLICK_SPEEDS.map((speed) => {
                      const current = typeof app.desktop_click_seconds === "number"
                        ? app.desktop_click_seconds
                        : 0.45;
                      const active = Math.abs(current - speed.seconds) < 0.02;
                      return (
                        <button
                          key={speed.id}
                          type="button"
                          aria-pressed={active}
                          onClick={() => patchApp({ desktop_click_seconds: speed.seconds })}
                          className={`rounded-md border px-2.5 py-1.5 text-xs transition-colors ${
                            active
                              ? "border-emerald-500/60 bg-emerald-500/[0.07] text-emerald-200"
                              : "border-charcoal-700 text-charcoal-400 hover:border-charcoal-600"
                          }`}
                        >
                          {speed.label}
                        </button>
                      );
                    })}
                  </div>
                  <p className="mt-2 text-[11px] text-charcoal-600">{
                    (app.desktop_click_seconds ?? 0.45) === 0
                      ? "Instant clicks. Faster, but nothing to see and no hover for menus that need it."
                      : "Moving there properly also gives hover menus and arming buttons a chance to notice the pointer."
                  }</p>
                  <div className="mt-3">
                    <ToggleRow
                      label="Mark the spot before clicking"
                      desc="Draws a ring where the click is about to land. Clicks pass straight through it."
                      on={app.desktop_click_marker !== false}
                      onClick={() => patchApp({ desktop_click_marker: app.desktop_click_marker === false })}
                    />
                  </div>
                </div>

                <div className="border-t border-charcoal-800 pt-5">
                  <p className="text-sm text-charcoal-200">Which browser Nova uses</p>
                  <p className="mt-1 text-xs leading-relaxed text-charcoal-500">
                    In Onyx, Nova works in a tab of its own with its own cursor, tagged "Nova", that
                    glides to what it clicks and presses with a real mouse event. Your mouse is never
                    moved, and it keeps working while Onyx is behind a game or minimised. Clicking in
                    the page yourself pauses it. Coursework and Instagram still use Nova's Edge window.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {BROWSER_BACKENDS.map((option) => {
                      const active = (app.browser_backend || "onyx") === option.id;
                      return (
                        <button
                          key={option.id}
                          type="button"
                          aria-pressed={active}
                          onClick={() => patchApp({ browser_backend: option.id })}
                          className={`rounded-md border px-2.5 py-1.5 text-xs transition-colors ${
                            active
                              ? "border-emerald-500/60 bg-emerald-500/[0.07] text-emerald-200"
                              : "border-charcoal-700 text-charcoal-400 hover:border-charcoal-600"
                          }`}
                        >
                          {option.label}
                        </button>
                      );
                    })}
                  </div>
                  <p className="mt-2 text-[11px] text-charcoal-600">{
                    (app.browser_backend || "onyx") === "onyx"
                      ? "If Onyx is not installed, Nova falls back to Edge and says so."
                      : "Edge: a separate window Nova drives with scripted clicks. No hover, no visible cursor."
                  }</p>
                </div>

                {capabilities && (
                  <div>
                    <p className="mb-2 text-xs text-charcoal-500">
                      {capabilities.tools.length} tools available right now
                      {capabilities.background_processes?.length
                        ? ` · ${capabilities.background_processes.length} background process(es) running`
                        : ""}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {capabilities.tools.map((tool) => (
                        <span
                          key={tool.name}
                          title={tool.description}
                          className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                            tool.mutating
                              ? "bg-amber-500/10 text-amber-200/80 ring-1 ring-amber-500/20"
                              : "bg-charcoal-800 text-charcoal-400"
                          }`}
                        >
                          {tool.name}
                        </span>
                      ))}
                    </div>
                    <p className="mt-2 text-[11px] text-charcoal-600">
                      Amber tools change something on this machine. They are the ones the level above governs.
                    </p>
                  </div>
                )}
              </div>
            )}

            {section === "Secrets" && (
              <div className="space-y-5">
                <div>
                  <p className="text-sm text-charcoal-200">Passwords Nova can use but never sees</p>
                  <p className="mt-1 text-xs leading-relaxed text-charcoal-500">
                    Save a secret here and Nova can type it into a login form by name. The value is
                    fetched at the moment of typing and goes straight to the keyboard — it never
                    appears in a prompt, so it never reaches a model, the chat transcript, or the
                    memory index. That is the difference between this and pasting a password into
                    chat.
                  </p>
                  {secrets && (
                    <p className="mt-2 text-[11px] text-charcoal-600">
                      Stored in: <span className="text-charcoal-400">{secrets.backend}</span>
                    </p>
                  )}
                </div>

                {secrets?.names?.length > 0 && (
                  <div className="space-y-1.5">
                    {secrets.names.map((name) => (
                      <div
                        key={name}
                        className="flex items-center justify-between rounded-lg border border-charcoal-700 px-3 py-2"
                      >
                        <div className="min-w-0">
                          <p className="truncate font-mono text-xs text-charcoal-200">{name}</p>
                          <p className="text-[10px] text-charcoal-600">•••••••• — value not readable from here</p>
                        </div>
                        <button
                          onClick={async () => { await deleteSecret(name); await refreshSecrets(); }}
                          className="shrink-0 rounded border border-rose-400/30 px-2 py-1 text-[11px] text-rose-300 hover:bg-rose-500/10"
                        >
                          Delete
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                <div className="space-y-2">
                  <p className="text-xs text-charcoal-500">Add a secret</p>
                  <input
                    value={secretName}
                    onChange={(e) => setSecretName(e.target.value)}
                    placeholder="name Nova will use, e.g. school-login"
                    className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                  />
                  <input
                    type="password"
                    value={secretValue}
                    onChange={(e) => setSecretValue(e.target.value)}
                    placeholder="the value"
                    className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                  />
                  <button
                    onClick={addSecret}
                    disabled={secretBusy || !secretName.trim() || !secretValue}
                    className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                  >
                    {secretBusy ? "Saving…" : "Save secret"}
                  </button>
                  <p className="text-[11px] leading-relaxed text-charcoal-600">
                    Then ask Nova something like “log into the school portal using school-login”. It
                    will open the page, find the field, and type it.
                  </p>
                </div>
              </div>
            )}

            {section === "Calendar" && (
              <div className="space-y-5">
                <div>
                  <p className="text-sm text-charcoal-200">Apple Calendar</p>
                  <p className="mt-1 text-xs leading-relaxed text-charcoal-500">
                    Two-way access to your real iCloud calendar over CalDAV — the same protocol
                    Apple&apos;s own apps use. Nova can read what you have on and add events, and
                    anything it writes shows up on your iPhone and Mac.
                  </p>
                </div>

                <div className="space-y-2.5">
                  <label className="block">
                    <span className="mb-1 block text-xs text-charcoal-500">Apple ID</span>
                    <input
                      value={appleId}
                      onChange={(e) => setAppleId(e.target.value)}
                      placeholder="you@icloud.com"
                      className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs text-charcoal-500">
                      App-specific password{" "}
                      <span className="text-charcoal-600">— not your Apple password</span>
                    </span>
                    <input
                      type="password"
                      value={applePassword}
                      onChange={(e) => setApplePassword(e.target.value)}
                      placeholder={apple?.password_set ? "•••••••• (saved)" : "xxxx-xxxx-xxxx-xxxx"}
                      className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 font-mono text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                    />
                  </label>
                  <p className="text-[11px] leading-relaxed text-charcoal-600">
                    Generate one at{" "}
                    <span className="text-charcoal-400">appleid.apple.com → Sign-In and Security →
                    App-Specific Passwords</span>. Your real Apple password will not work, and
                    requires two-factor authentication to be on. Stored in{" "}
                    {apple?.stored_in || "the OS credential vault"} — never in a prompt, never shown
                    to a model, and revoked from Apple&apos;s side any time you want.
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={connectAppleCalendar}
                      disabled={appleBusy || !appleId.trim() || (!applePassword.trim() && !apple?.password_set)}
                      className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                    >
                      {appleBusy ? "Checking…" : apple?.configured ? "Reconnect" : "Connect"}
                    </button>
                    {apple?.configured && (
                      <button
                        onClick={disconnectApple}
                        disabled={appleBusy}
                        className="rounded-md px-3 py-1.5 text-xs text-charcoal-300 ring-1 ring-charcoal-600 hover:bg-charcoal-800 disabled:opacity-50"
                      >
                        Disconnect
                      </button>
                    )}
                    {apple?.configured && <span className="text-[11px] text-emerald-300">Connected</span>}
                  </div>
                  {appleNote && <p className="text-[11px] leading-relaxed text-emerald-300">{appleNote}</p>}
                </div>

                <p className="text-[11px] leading-relaxed text-charcoal-600">
                  Once connected, ask Nova things like &ldquo;what do I have Thursday?&rdquo; or
                  &ldquo;block out two hours Sunday for the econ chapter&rdquo;. Adding and deleting
                  events count as actions, so in Guarded autonomy they show an approval card first.
                </p>
              </div>
            )}

            {section === "Academics" && <AcademicsPanel />}
            {section === "Canvas" && (
              <div className="space-y-5">
                <div>
                  <p className="text-sm text-charcoal-200">Canvas assignments</p>
                  <p className="mt-1 text-xs text-charcoal-500">
                    Every night Nova pulls your assignments from Canvas, adds anything new to a
                    calendar file with reminders, and writes you a short brief. Assignments are
                    matched on Canvas&apos;s own ID, so re-running it can never create a duplicate.
                  </p>
                </div>

                {/* Two ways in, because a lot of schools disable student access
                    tokens outright. The feed is the fallback that still works
                    when they do — see backend/app/canvas_feed.py. */}
                <div className="flex gap-1.5">
                  {[
                    ["token", "Access token"],
                    ["feed", "Calendar feed"],
                  ].map(([id, label]) => (
                    <button
                      key={id}
                      onClick={() => { setCanvasMethod(id); setCanvasNote(""); }}
                      className={`rounded-md px-2.5 py-1 text-[11px] ${
                        canvasMethod === id
                          ? "bg-charcoal-800 text-emerald-300 ring-1 ring-emerald-600/40"
                          : "text-charcoal-500 hover:text-charcoal-300"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                {canvasMethod === "token" ? (
                  <div className="space-y-2.5">
                    <p className="text-[11px] leading-relaxed text-charcoal-500">
                      The better option when your school allows it: it also knows what you&apos;ve
                      already submitted, so finished work drops off the calendar.
                    </p>
                    <label className="block">
                      <span className="mb-1 block text-xs text-charcoal-500">Canvas URL</span>
                      <input
                        value={canvasUrl}
                        onChange={(e) => setCanvasUrl(e.target.value)}
                        placeholder="yourschool.instructure.com"
                        className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs text-charcoal-500">
                        Access token{" "}
                        <span className="text-charcoal-600">
                          — Canvas → Account → Settings → New Access Token
                        </span>
                      </span>
                      <input
                        type="password"
                        value={canvasToken}
                        onChange={(e) => setCanvasToken(e.target.value)}
                        placeholder={canvas?.canvas?.token_set ? "•••••••• (saved)" : "paste the token"}
                        className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                      />
                    </label>
                    <p className="text-[11px] leading-relaxed text-charcoal-600">
                      No &quot;New Access Token&quot; button, or it errors? Your school has turned
                      them off for students — use Calendar feed instead.
                    </p>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={connectCanvas}
                        disabled={canvasBusy === "connect" || !canvasUrl.trim()}
                        className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                      >
                        {canvasBusy === "connect" ? "Checking…" : "Connect"}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2.5">
                    <p className="text-[11px] leading-relaxed text-charcoal-500">
                      Works without a token and without admin permission. In Canvas open{" "}
                      <span className="text-charcoal-400">Calendar</span>, click{" "}
                      <span className="text-charcoal-400">Calendar Feed</span> at the bottom right,
                      and paste the link here. It doesn&apos;t report what you&apos;ve submitted, so
                      finished work stays on the calendar until its due date passes.
                    </p>
                    <label className="block">
                      <span className="mb-1 block text-xs text-charcoal-500">Calendar feed link</span>
                      <input
                        type="password"
                        value={canvasFeed}
                        onChange={(e) => setCanvasFeed(e.target.value)}
                        placeholder={
                          canvas?.canvas?.feed?.configured
                            ? `•••••••• (saved — ${canvas.canvas.feed.feed_host})`
                            : "https://…instructure.com/feeds/calendars/user_….ics"
                        }
                        className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                      />
                    </label>
                    <p className="text-[11px] leading-relaxed text-charcoal-600">
                      Treat this link like a password — anyone who has it can read your schedule.
                      Nova stores it locally and never shows it again.
                    </p>
                    <button
                      onClick={connectCanvasFeed}
                      disabled={canvasBusy === "feed" || !canvasFeed.trim()}
                      className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                    >
                      {canvasBusy === "feed" ? "Checking…" : "Connect feed"}
                    </button>
                  </div>
                )}

                <div className="flex items-center gap-2">
                  {canvas?.canvas?.any_configured && (
                    <>
                      <button
                        onClick={syncCanvasNow}
                        disabled={canvasBusy === "sync"}
                        className="rounded-md px-3 py-1.5 text-xs text-charcoal-300 ring-1 ring-charcoal-600 hover:bg-charcoal-800 disabled:opacity-50"
                      >
                        {canvasBusy === "sync" ? "Syncing…" : "Sync now"}
                      </button>
                      <span className="text-[11px] text-emerald-300">
                        Connected via {canvas.canvas.source === "api" ? "access token" : "calendar feed"}
                      </span>
                    </>
                  )}
                </div>
                {canvasNote && <p className="text-[11px] text-emerald-300">{canvasNote}</p>}

                {canvas && (
                  <>
                    <ToggleRow
                      label="Nightly sync"
                      desc="Runs once a day. If the machine is asleep at the scheduled time, it syncs when it next wakes rather than skipping the day."
                      on={canvas.enabled}
                      onClick={() => patchCanvas({ enabled: !canvas.enabled })}
                    />
                    <div className="flex items-center justify-between gap-4 border-b border-charcoal-800/60 py-3">
                      <div className="pr-4">
                        <p className="text-sm text-charcoal-200">Run at</p>
                        <p className="mt-0.5 text-xs text-charcoal-500">24-hour local time.</p>
                      </div>
                      <input
                        type="time"
                        value={canvas.time}
                        onChange={(e) => patchCanvas({ syncTime: e.target.value })}
                        className="rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                      />
                    </div>
                    <div className="flex items-center justify-between gap-4 border-b border-charcoal-800/60 py-3">
                      <div className="pr-4">
                        <p className="text-sm text-charcoal-200">Hide long-overdue work</p>
                        <p className="mt-0.5 text-xs leading-relaxed text-charcoal-500">
                          The calendar feed can&apos;t tell Nova what you&apos;ve submitted, so finished
                          work still counts as open. Anything overdue by more than this drops off your
                          calendars. It stays in Nova either way. 0 keeps everything.
                        </p>
                      </div>
                      <input
                        type="number"
                        min={0}
                        max={365}
                        value={canvas.stale_days ?? 14}
                        onChange={(e) => patchCanvas({ staleDays: Number(e.target.value) })}
                        className="w-20 shrink-0 rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                      />
                    </div>

                    {/* The .ics next door can only be subscribed to by something
                        that can reach this machine, which rules out iCloud and
                        Google. Writing events directly is what gets these onto a
                        phone. */}
                    <div className="border-b border-charcoal-800/60 py-3">
                      <div className="flex items-center justify-between gap-4">
                        <div className="pr-4">
                          <p className="text-sm text-charcoal-200">Push to Apple Calendar</p>
                          <p className="mt-0.5 text-xs leading-relaxed text-charcoal-500">
                            Writes each assignment straight into iCloud after every sync, so they show
                            up on your iPhone. Matched on Canvas&apos;s id, so re-running updates
                            rather than duplicates, and submitted or removed work is deleted again.
                          </p>
                        </div>
                        <Toggle
                          on={Boolean(canvas.push_to_apple)}
                          onClick={() => patchCanvas({ pushToApple: !canvas.push_to_apple })}
                          label="Push Canvas assignments to Apple Calendar"
                        />
                      </div>
                      {canvas.push_to_apple && (
                        <div className="mt-2">
                          {appleCalendars.length === 0 ? (
                            <p className="text-[11px] text-amber-300">
                              Connect Apple Calendar first in Settings → Calendar.
                            </p>
                          ) : (
                            <select
                              value={canvas.push_calendar || ""}
                              onChange={(e) => patchCanvas({ pushCalendar: e.target.value })}
                              className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                            >
                              <option value="">Choose a calendar…</option>
                              {appleCalendars.filter((c) => !c.read_only).map((c) => (
                                <option key={c.url} value={c.url}>{c.name}</option>
                              ))}
                            </select>
                          )}
                        </div>
                      )}
                    </div>

                    <div className="border-b border-charcoal-800/60 py-3">
                      <p className="text-sm text-charcoal-200">Reminders</p>
                      <p className="mb-2 mt-0.5 text-xs text-charcoal-500">
                        Hours before each due date. These become real alarms on the calendar events.
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {[72, 48, 24, 12, 6, 3, 1].map((hours) => {
                          const on = canvas.reminder_hours.includes(hours);
                          return (
                            <button
                              key={hours}
                              onClick={() =>
                                patchCanvas({
                                  reminderHours: on
                                    ? canvas.reminder_hours.filter((h) => h !== hours)
                                    : [...canvas.reminder_hours, hours],
                                })
                              }
                              className={`rounded-md px-2 py-1 text-[11px] transition-colors ${
                                on
                                  ? "bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-400/30"
                                  : "text-charcoal-400 ring-1 ring-charcoal-700 hover:bg-charcoal-800"
                              }`}
                            >
                              {hours}h
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    <div>
                      <p className="text-sm text-charcoal-200">Subscribe to the calendar</p>
                      <p className="mt-1 text-xs text-charcoal-500">
                        Add this file in Google Calendar, Outlook or Apple Calendar and it stays
                        current on its own — new assignments appear after each nightly run.
                      </p>
                      <code className="mt-2 block break-all rounded bg-charcoal-900 p-2 font-mono text-[10.5px] text-charcoal-400">
                        {canvas.calendar_path}
                      </code>
                      <p className="mt-2 text-[11px] text-charcoal-600">
                        Last run: {canvas.last_run || "never"}
                      </p>
                    </div>
                  </>
                )}
              </div>
            )}

            {section === "Agents" && (
              <div className="space-y-5">
                <div>
                  <p className="text-sm text-charcoal-200">External coding agents</p>
                  <p className="mt-1 text-xs text-charcoal-500">
                    Agents that speak the Agent Client Protocol. Nova can hand a whole implementation
                    task to one and stream back what it did — useful when the job is bigger than a few
                    files. Nova answers their file reads and permission prompts itself, so your
                    autonomy setting above still applies.
                  </p>
                </div>

                {acpAgents.length > 0 && (
                  <div className="space-y-2">
                    {acpAgents.map((agent) => (
                      <div key={agent.id} className="rounded-lg border border-charcoal-700 p-3">
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                            <p className="truncate text-sm text-charcoal-200">{agent.name}</p>
                            <p className="truncate font-mono text-[11px] text-charcoal-600">
                              {agent.command} {(JSON.parse(agent.args || "[]") || []).join(" ")}
                            </p>
                          </div>
                          <div className="flex shrink-0 items-center gap-2">
                            <span
                              className={`text-[11px] ${
                                agent.status?.connected
                                  ? "text-emerald-300"
                                  : agent.status?.installed
                                    ? "text-charcoal-500"
                                    : "text-amber-300"
                              }`}
                            >
                              {agent.status?.connected
                                ? "Connected"
                                : agent.status?.installed
                                  ? "Not connected"
                                  : "Command not found"}
                            </span>
                            <Toggle
                              on={agent.enabled}
                              onClick={() => toggleAcpAgent(agent.id, !agent.enabled)}
                              label={`Enable ${agent.name}`}
                            />
                          </div>
                        </div>
                        <div className="mt-2 flex gap-2">
                          <button
                            onClick={() => connectAcp(agent.id)}
                            disabled={acpBusy === agent.id}
                            className="rounded border border-charcoal-600 px-2 py-1 text-[11px] text-charcoal-300 hover:bg-charcoal-800 disabled:opacity-50"
                          >
                            {acpBusy === agent.id ? "Connecting…" : agent.status?.connected ? "Reconnect" : "Connect"}
                          </button>
                          <button
                            onClick={() => removeAcpAgent(agent.id)}
                            className="rounded border border-rose-400/30 px-2 py-1 text-[11px] text-rose-300 hover:bg-rose-500/10"
                          >
                            Remove
                          </button>
                        </div>
                        {agent.status?.stderr_tail?.length > 0 && !agent.status?.connected && (
                          <pre className="mt-2 overflow-x-auto rounded bg-charcoal-900 p-2 text-[10px] text-charcoal-500">
                            {agent.status.stderr_tail.join("\n")}
                          </pre>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                <div>
                  <p className="mb-2 text-xs text-charcoal-500">Add an agent</p>
                  <div className="space-y-2">
                    {acpSuggested.map((preset) => (
                      <button
                        key={preset.name}
                        onClick={() => addAcpAgent(preset)}
                        disabled={acpAgents.some((a) => a.name === preset.name)}
                        className="w-full rounded-lg border border-charcoal-700 p-2.5 text-left transition-colors hover:border-charcoal-600 hover:bg-charcoal-800/40 disabled:opacity-40 disabled:hover:bg-transparent"
                      >
                        <p className="text-sm text-charcoal-200">
                          {preset.name}
                          {acpAgents.some((a) => a.name === preset.name) && (
                            <span className="ml-2 text-[11px] text-charcoal-600">already added</span>
                          )}
                        </p>
                        <p className="mt-0.5 text-[11px] text-charcoal-500">{preset.note}</p>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {section === "Routing" && (
              <div>
                <p className="mb-3 text-xs text-charcoal-500">
                  Pin a specific model to a category, overriding automatic routing's fallback chain for every
                  request in that category. Leave "Auto" to keep the built-in chain. Turn automatic routing off in General to use one default model.
                </p>
                {routingCategories.map((category) => (
                  <div key={category} className="flex items-center justify-between gap-3 border-b border-charcoal-800/60 py-2.5">
                    <span className="font-mono text-xs text-charcoal-300">{category}</span>
                    <select
                      value={routingOverrides[category] || ""}
                      onChange={(e) => handleRoutingOverrideChange(category, e.target.value)}
                      disabled={routingSavingCategory === category}
                      className="w-56 rounded-md bg-charcoal-800 px-2 py-1.5 text-xs text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500 disabled:opacity-50"
                    >
                      <option value="">Auto</option>
                      {models.filter((m) => m.enabled).map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
                {routingCategories.length === 0 && (
                  <p className="text-xs text-charcoal-600">Loading categories…</p>
                )}
              </div>
            )}

            {section === "Teams" && (
              <div>
                <p className="mb-3 text-xs text-charcoal-500">
                  Assign a provider/model to each of the director's team roles (task: "Allow provider/model
                  assignments in Settings" -- Chat's own routing stays automatic; this only affects work you
                  hand to the director from Workspace).
                </p>
                <TeamsView />
              </div>
            )}

            {section === "Models" && (
              <div>
                {/* Primary Assistant Model Selector & Workspace Status */}
                <div className="mb-4 rounded-xl border border-charcoal-700 bg-charcoal-900/80 p-3.5 space-y-3">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div>
                      <p className="text-xs font-semibold text-white">Primary Assistant Model</p>
                      <p className="text-[11px] text-charcoal-400">
                        Choose your primary default assistant. You decide your main model — Antigravity is not forced.
                      </p>
                    </div>
                    <select
                      aria-label="Primary assistant model"
                      value={app?.primary_model || ""}
                      onChange={(e) => patchApp({ primary_model: e.target.value })}
                      className="rounded-lg border border-charcoal-600 bg-charcoal-800 px-3 py-1.5 text-xs text-charcoal-200 font-medium"
                    >
                      <option value="">Automatic Intelligent Routing</option>
                      {models.filter((m) => m.enabled).map((m) => (
                        <option key={m.id} value={m.id}>
                          {modelDisplayName(m)} ({providerMeta(m.provider).label})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="pt-2.5 border-t border-charcoal-800 flex items-center justify-between text-xs">
                    <span className="text-charcoal-400">Multi-Agent Workspace:</span>
                    {models.filter((m) => m.enabled).length >= 4 ? (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 font-medium text-[11px]">
                        <span>🌌</span> Unlocked ({models.filter((m) => m.enabled).length} models connected)
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-400 font-medium text-[11px]">
                        <span>🔒</span> {models.filter((m) => m.enabled).length} / 4 Models Connected (Connect {4 - models.filter((m) => m.enabled).length} more to unlock Workspace)
                      </span>
                    )}
                  </div>
                </div>

                <p className="mb-3 text-xs text-charcoal-500">
                  Your active assistants and local models. OpenRouter's changing free catalog
                  and disabled models are available under Show full catalog.
                </p>
                <label className="mb-3 flex items-center gap-2 text-xs text-charcoal-300">
                  <input type="checkbox" checked={showFullCatalog} onChange={e => setShowFullCatalog(e.target.checked)} />
                  Show full catalog ({models.length})
                </label>
                <div className="space-y-1.5">
                  {models.filter(m => showFullCatalog || (m.enabled && (m.provider !== "openrouter" || m.id.startsWith("custom:")))).map((m) => {
                    const meta = providerMeta(m.provider);
                    return (
                      <div
                        key={m.id}
                        className="flex items-center justify-between rounded-md bg-charcoal-800/60 px-2.5 py-2"
                      >
                        <div className="flex min-w-0 items-center gap-2">
                          <span className="h-[7px] w-[7px] shrink-0 rounded-full" style={{ backgroundColor: meta.color }} />
                          <span title={m.id} className="truncate text-sm text-charcoal-200">{modelDisplayName(m)}</span>
                          <span className="shrink-0 rounded-full bg-charcoal-800 px-2 py-0.5 text-[10px] text-charcoal-400">
                            {meta.label}
                          </span>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                          {m.toggleable ? (
                            <Toggle on={m.enabled} onClick={() => handleToggleModel(m)} />
                          ) : (
                            <span className="text-[10px] text-charcoal-600">auto</span>
                          )}
                          {m.id.startsWith("custom:") && (
                            <button
                              onClick={() => handleDeleteCustomModel(m)}
                              className="text-charcoal-500 hover:text-rose-400"
                              title="Remove"
                            >
                              ✕
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                  {models.length === 0 && <p className="text-xs text-charcoal-600">No models detected yet.</p>}
                </div>

                <div className="mt-4 rounded-md border border-dashed border-charcoal-700 p-3">
                  <p className="mb-2 text-xs font-medium text-charcoal-400">Add Model</p>
                  <div className="mb-3 flex gap-1 rounded-md bg-charcoal-800/60 p-0.5">
                    {[
                      ["apikey", "🔑 API Key"],
                      ["local", "💻 Local CLI / Ollama"],
                      ["account", "🌐 Account Login"],
                    ].map(([key, label]) => (
                      <button
                        key={key}
                        onClick={() => {
                          setAddModelType(key);
                          setAddModelError("");
                        }}
                        className={`flex-1 rounded px-2.5 py-1.5 text-[11px] font-medium transition-colors ${
                          addModelType === key
                            ? "bg-emerald-600 text-white shadow-sm"
                            : "text-charcoal-400 hover:text-charcoal-200"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>

                  {addModelType === "apikey" && (
                    <div className="space-y-3">
                      <div className="flex flex-wrap gap-1.5">
                        {[
                          { name: "OpenRouter (Free Catalog)", isOr: true },
                          { name: "OpenAI", apiBase: "https://api.openai.com/v1" },
                          { name: "Anthropic", apiBase: "https://api.anthropic.com/v1" },
                          { name: "Gemini", apiBase: "https://generativelanguage.googleapis.com/v1beta/openai" },
                          { name: "Groq", apiBase: "https://api.groq.com/openai/v1" },
                          { name: "DeepSeek", apiBase: "https://api.deepseek.com/v1" },
                          { name: "Mistral", apiBase: "https://api.mistral.ai/v1" },
                          { name: "Custom URL", apiBase: "" },
                        ].map((preset) => {
                          const active = preset.isOr
                            ? apiProviderMode === "openrouter"
                            : apiProviderMode === "custom" && addModelForm.apiBase === preset.apiBase;
                          return (
                            <button
                              key={preset.name}
                              type="button"
                              onClick={() => {
                                if (preset.isOr) {
                                  setApiProviderMode("openrouter");
                                } else {
                                  setApiProviderMode("custom");
                                  setDiscovered(null);
                                  setDiscoverError("");
                                  setAddModelForm((f) => ({
                                    ...f,
                                    name: f.name || preset.name,
                                    apiBase: preset.apiBase,
                                  }));
                                }
                              }}
                              className={`rounded-full px-2.5 py-1 text-[10.5px] transition-colors ${
                                active
                                  ? "bg-emerald-600/30 text-emerald-300 ring-1 ring-emerald-500/50"
                                  : "text-charcoal-400 ring-1 ring-charcoal-700 hover:bg-charcoal-800 hover:text-charcoal-200"
                              }`}
                            >
                              {preset.name}
                            </button>
                          );
                        })}
                      </div>

                      {apiProviderMode === "openrouter" ? (
                        <div className="space-y-2">
                          <p className="text-[10.5px] text-charcoal-500">
                            Browse OpenRouter's live free-tier catalog or enter an exact model ID:
                          </p>
                          <input
                            value={orQuery}
                            onChange={(e) => setOrQuery(e.target.value)}
                            placeholder="Search free-tier models (e.g. qwen, deepseek, llama)…"
                            className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                          />
                          <div className="max-h-32 overflow-y-auto rounded-md ring-1 ring-charcoal-800">
                            {orLoading && <p className="px-2 py-2 text-[11px] text-charcoal-600">Loading…</p>}
                            {!orLoading &&
                              orModels.map((m) => (
                                <button
                                  key={m.id}
                                  onClick={() => selectOpenRouterModel(m)}
                                  className={`block w-full truncate px-2 py-1.5 text-left text-[11.5px] hover:bg-charcoal-800 ${
                                    addModelForm.modelId === m.id ? "bg-emerald-600/20 text-emerald-300" : "text-charcoal-300"
                                  }`}
                                >
                                  {m.name} <span className="text-charcoal-500">— {m.id}</span>
                                </button>
                              ))}
                            {!orLoading && orModels.length === 0 && (
                              <p className="px-2 py-2 text-[11px] text-charcoal-600">No matching free models right now.</p>
                            )}
                          </div>
                          <input
                            value={addModelForm.modelId}
                            onChange={(e) => setAddModelForm((f) => ({ ...f, modelId: e.target.value }))}
                            placeholder="Model ID (e.g. z-ai/glm-5.2:free)"
                            className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 font-mono text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                          />
                          <input
                            value={addModelForm.name}
                            onChange={(e) => setAddModelForm((f) => ({ ...f, name: e.target.value }))}
                            placeholder="Display name (optional)"
                            className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                          />
                          {addModelError && <p className="text-[11px] text-rose-400">{addModelError}</p>}
                          <button
                            onClick={handleAddOpenRouterModel}
                            disabled={addModelAdding || !addModelForm.modelId.trim()}
                            className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                          >
                            {addModelAdding ? "Adding…" : "Add Model"}
                          </button>
                        </div>
                      ) : (
                        <div className="space-y-2">
                          <input
                            value={addModelForm.apiBase}
                            onChange={(e) => {
                              setDiscovered(null);
                              setAddModelForm((f) => ({ ...f, apiBase: e.target.value }));
                            }}
                            placeholder="API Base URL (e.g. https://api.openai.com/v1)"
                            className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 font-mono text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                          />
                          <input
                            value={addModelForm.apiKey}
                            onChange={(e) => setAddModelForm((f) => ({ ...f, apiKey: e.target.value }))}
                            placeholder="API Key"
                            type="password"
                            className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 font-mono text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                          />
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={fetchEndpointModels}
                              disabled={discovering || !addModelForm.apiBase.trim()}
                              className="rounded-md px-2.5 py-1 text-[11px] text-charcoal-300 ring-1 ring-charcoal-600 hover:bg-charcoal-800 disabled:opacity-50"
                            >
                              {discovering ? "Fetching…" : "Fetch Models"}
                            </button>
                            {discovered && (
                              <span className="text-[10.5px] text-emerald-300">
                                {discovered.length} model{discovered.length === 1 ? "" : "s"} found
                              </span>
                            )}
                          </div>
                          {discoverError && <p className="text-[11px] text-rose-400">{discoverError}</p>}
                          {discovered?.length > 0 && (
                            <div className="max-h-32 space-y-0.5 overflow-y-auto rounded-md ring-1 ring-charcoal-700">
                              {discovered
                                .filter((id) => id.toLowerCase().includes(modelFilter.trim().toLowerCase()))
                                .slice(0, 100)
                                .map((id) => (
                                  <button
                                    key={id}
                                    type="button"
                                    onClick={() => setAddModelForm((f) => ({ ...f, modelId: id }))}
                                    className={`block w-full truncate px-2 py-1 text-left font-mono text-[11px] ${
                                      addModelForm.modelId === id
                                        ? "bg-charcoal-800 text-emerald-300"
                                        : "text-charcoal-400 hover:bg-charcoal-800/70 hover:text-charcoal-200"
                                    }`}
                                    title={id}
                                  >
                                    {id}
                                  </button>
                                ))}
                            </div>
                          )}
                          <input
                            value={addModelForm.modelId}
                            onChange={(e) => setAddModelForm((f) => ({ ...f, modelId: e.target.value }))}
                            placeholder="Model ID (e.g. gpt-4o, claude-3-5-sonnet)"
                            className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 font-mono text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                          />
                          <input
                            value={addModelForm.name}
                            onChange={(e) => setAddModelForm((f) => ({ ...f, name: e.target.value }))}
                            placeholder="Display name (optional)"
                            className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                          />
                          {addModelError && <p className="text-[11px] text-rose-400">{addModelError}</p>}
                          <button
                            onClick={handleAddCustomModel}
                            disabled={addModelAdding || !addModelForm.modelId.trim() || !addModelForm.apiBase.trim()}
                            className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                          >
                            {addModelAdding ? "Adding…" : "Add Model"}
                          </button>
                        </div>
                      )}
                    </div>
                  )}

                  {addModelType === "local" && (
                    <div className="space-y-3">
                      <p className="text-[10.5px] text-charcoal-500">
                        Run models locally using Ollama, LM Studio, vLLM, or other local OpenAI-compatible CLIs.
                      </p>

                      <div className="rounded-md bg-charcoal-900/60 p-2.5 ring-1 ring-charcoal-800 space-y-2">
                        <p className="text-xs font-semibold text-charcoal-300">Pull from Ollama Library</p>
                        <div className="flex gap-2">
                          <input
                            value={pullName}
                            onChange={(e) => setPullName(e.target.value)}
                            placeholder="Model name (e.g. llama3.2, deepseek-r1:8b, mistral)"
                            className="flex-1 rounded-md bg-charcoal-800 px-2 py-1.5 font-mono text-xs text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                          />
                          <button
                            onClick={handlePullOllamaModel}
                            disabled={pulling || !pullName.trim()}
                            className="shrink-0 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                          >
                            {pulling ? "Pulling…" : "Pull & Add"}
                          </button>
                        </div>
                        {pulling && pullStatus && (
                          <div className="rounded-md bg-charcoal-800/80 px-2.5 py-1.5 text-[11px] text-charcoal-300">
                            <p className="truncate">{pullStatus.status}</p>
                            {typeof pullStatus.total === "number" && pullStatus.total > 0 && (
                              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-charcoal-700">
                                <div
                                  className="h-full rounded-full bg-emerald-500 transition-all"
                                  style={{
                                    width: `${Math.min(100, (pullStatus.completed / pullStatus.total) * 100)}%`,
                                  }}
                                />
                              </div>
                            )}
                          </div>
                        )}
                        {pullError && <p className="text-[11px] text-rose-400">{pullError}</p>}
                      </div>

                      <div className="rounded-md bg-charcoal-900/60 p-2.5 ring-1 ring-charcoal-800 space-y-2">
                        <p className="text-xs font-semibold text-charcoal-300">Local Gateways & Servers</p>
                        <div className="flex flex-wrap gap-1">
                          {[
                            { name: "Ollama HTTP", apiBase: "http://localhost:11434/v1" },
                            { name: "LM Studio", apiBase: "http://localhost:1234/v1" },
                            { name: "vLLM", apiBase: "http://localhost:8000/v1" },
                            { name: "FreeLLMAPI", apiBase: "http://localhost:3001/v1" },
                          ].map((preset) => (
                            <button
                              key={preset.name}
                              type="button"
                              onClick={() => {
                                setDiscovered(null);
                                setDiscoverError("");
                                setAddModelForm((f) => ({
                                  ...f,
                                  name: f.name || preset.name,
                                  apiBase: preset.apiBase,
                                }));
                              }}
                              className="rounded-full px-2 py-0.5 text-[10.5px] text-charcoal-400 ring-1 ring-charcoal-700 hover:bg-charcoal-800 hover:text-charcoal-200"
                            >
                              {preset.name}
                            </button>
                          ))}
                        </div>
                        <input
                          value={addModelForm.apiBase}
                          onChange={(e) => {
                            setDiscovered(null);
                            setAddModelForm((f) => ({ ...f, apiBase: e.target.value }));
                          }}
                          placeholder="Local Base URL (e.g. http://localhost:11434/v1)"
                          className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 font-mono text-xs text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                        />
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={fetchEndpointModels}
                            disabled={discovering || !addModelForm.apiBase.trim()}
                            className="rounded-md px-2.5 py-1 text-[11px] text-charcoal-300 ring-1 ring-charcoal-600 hover:bg-charcoal-800 disabled:opacity-50"
                          >
                            {discovering ? "Detecting…" : "Detect Local Models"}
                          </button>
                          {discovered && (
                            <span className="text-[10.5px] text-emerald-300">
                              {discovered.length} local model{discovered.length === 1 ? "" : "s"} found
                            </span>
                          )}
                        </div>
                        {discoverError && <p className="text-[11px] text-rose-400">{discoverError}</p>}
                        {discovered?.length > 0 && (
                          <div className="max-h-28 space-y-0.5 overflow-y-auto rounded-md ring-1 ring-charcoal-700">
                            {discovered.map((id) => (
                              <button
                                key={id}
                                type="button"
                                onClick={() => setAddModelForm((f) => ({ ...f, modelId: id }))}
                                className={`block w-full truncate px-2 py-1 text-left font-mono text-[11px] ${
                                  addModelForm.modelId === id ? "bg-charcoal-800 text-emerald-300" : "text-charcoal-400 hover:bg-charcoal-800/70 hover:text-charcoal-200"
                                }`}
                              >
                                {id}
                              </button>
                            ))}
                          </div>
                        )}
                        <div className="flex gap-2">
                          <input
                            value={addModelForm.modelId}
                            onChange={(e) => setAddModelForm((f) => ({ ...f, modelId: e.target.value }))}
                            placeholder="Model ID"
                            className="flex-1 rounded-md bg-charcoal-800 px-2 py-1.5 font-mono text-xs text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                          />
                          <input
                            value={addModelForm.name}
                            onChange={(e) => setAddModelForm((f) => ({ ...f, name: e.target.value }))}
                            placeholder="Name (optional)"
                            className="flex-1 rounded-md bg-charcoal-800 px-2 py-1.5 text-xs text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                          />
                        </div>
                        <button
                          onClick={handleAddCustomModel}
                          disabled={addModelAdding || !addModelForm.modelId.trim() || !addModelForm.apiBase.trim()}
                          className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                        >
                          {addModelAdding ? "Adding…" : "Add Local Model"}
                        </button>
                      </div>
                    </div>
                  )}

                  {addModelType === "account" && (
                    <div className="space-y-3">
                      <p className="text-[10.5px] text-charcoal-500">
                        Connect your existing provider subscriptions directly. Nova authenticates via your system browser so you don't need manual API keys.
                      </p>

                      <div className="space-y-2">
                        {[
                          { id: "google", name: "Google Account (Gemini)", desc: "Gemini 1.5 Pro, Flash & Live Audio access", icon: "🌐" },
                          { id: "openai", name: "OpenAI / ChatGPT Plus", desc: "Use your existing ChatGPT Plus or Team plan", icon: "⚡" },
                          { id: "anthropic", name: "Anthropic Claude Pro", desc: "Claude 3.5 Sonnet & Haiku access", icon: "✨" },
                          { id: "github", name: "GitHub Copilot", desc: "GitHub Student Developer Pack or Copilot tier", icon: "🐙" },
                        ].map((acc) => {
                          const isConnected = connectedAccounts[acc.id];
                          return (
                            <div key={acc.id} className="flex items-center justify-between rounded-md bg-charcoal-800/60 p-2.5 ring-1 ring-charcoal-700/60">
                              <div className="flex items-center gap-2.5 min-w-0">
                                <span className="text-base">{acc.icon}</span>
                                <div className="truncate">
                                  <p className="text-xs font-medium text-charcoal-200">{acc.name}</p>
                                  <p className="text-[10.5px] text-charcoal-400">{acc.desc}</p>
                                </div>
                              </div>
                              <button
                                type="button"
                                onClick={() => {
                                  setConnectedAccounts((prev) => ({ ...prev, [acc.id]: !prev[acc.id] }));
                                }}
                                className={`shrink-0 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                                  isConnected
                                    ? "bg-emerald-950 text-emerald-300 ring-1 ring-emerald-600/50 hover:bg-rose-950 hover:text-rose-300 hover:ring-rose-500/50"
                                    : "bg-emerald-600 text-white hover:bg-emerald-500"
                                }`}
                              >
                                {isConnected ? "✓ Linked" : "Connect Account"}
                              </button>
                            </div>
                          );
                        })}
                      </div>
                      <p className="text-[10px] text-charcoal-500 italic">
                        Accounts authenticate locally via your system default browser. Credentials and access tokens are never transmitted off your machine.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {section === "Skills" && (
              <div>
                <p className="mb-3 text-xs text-charcoal-500">
                  Domain-specific instructions N.O.V.A. folds into its system prompt only when your message
                  actually matches a skill's keywords — not a static prompt every request pays for. Skills
                  live as files under backend/app/skills/, but you don't need to touch them by hand.
                </p>
                <div className="space-y-1.5">
                  {skillsList.map((s) => (
                    <div
                      key={s.name}
                      className="rounded-md bg-charcoal-800/60 px-2.5 py-2"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className="truncate text-sm text-charcoal-200">{s.name}</span>
                          {s.preferred_model_id && (
                            <span className="shrink-0 rounded-full bg-charcoal-800 px-2 py-0.5 text-[10px] text-charcoal-400">
                              → {s.preferred_model_id}
                            </span>
                          )}
                        </div>
                        <button
                          onClick={() => handleDeleteSkill(s)}
                          className="shrink-0 text-charcoal-500 hover:text-rose-400"
                          title="Remove"
                        >
                          ✕
                        </button>
                      </div>
                      {s.description && <p className="mt-1 text-[11px] text-charcoal-500">{s.description}</p>}
                      {s.keywords?.length > 0 && (
                        <p className="mt-1 truncate text-[10.5px] text-charcoal-600">
                          {s.keywords.join(", ")}
                        </p>
                      )}
                    </div>
                  ))}
                  {!skillsLoading && skillsList.length === 0 && (
                    <p className="text-xs text-charcoal-600">No skills yet.</p>
                  )}
                </div>

                <div className="mt-4 rounded-md border border-dashed border-charcoal-700 p-3">
                  <p className="mb-2 text-xs font-medium text-charcoal-400">Add Skill</p>
                  <div className="space-y-2">
                    <input
                      value={addSkillForm.name}
                      onChange={(e) => setAddSkillForm((f) => ({ ...f, name: e.target.value }))}
                      placeholder="Name (e.g. terraform-review) — becomes skills/<name>.md"
                      className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 font-mono text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                    />
                    <input
                      value={addSkillForm.description}
                      onChange={(e) => setAddSkillForm((f) => ({ ...f, description: e.target.value }))}
                      placeholder="Short description"
                      className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                    />
                    <input
                      value={addSkillForm.keywords}
                      onChange={(e) => setAddSkillForm((f) => ({ ...f, keywords: e.target.value }))}
                      placeholder="Keywords, comma separated (e.g. terraform, hcl, plan, apply)"
                      className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                    />
                    <textarea
                      value={addSkillForm.body}
                      onChange={(e) => setAddSkillForm((f) => ({ ...f, body: e.target.value }))}
                      placeholder="Instructions N.O.V.A. should follow when this skill matches…"
                      rows={5}
                      className="w-full resize-y rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                    />
                    <select
                      value={addSkillForm.preferredModelId}
                      onChange={(e) => setAddSkillForm((f) => ({ ...f, preferredModelId: e.target.value }))}
                      className="w-full rounded-md bg-charcoal-900 px-2 py-1.5 text-xs text-charcoal-300 ring-1 ring-charcoal-700 hover:bg-charcoal-800"
                    >
                      <option value="">Preferred model: none (use normal routing)</option>
                      {models.filter((m) => m.enabled).map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name}
                        </option>
                      ))}
                    </select>
                    {addSkillError && <p className="text-[11px] text-rose-400">{addSkillError}</p>}
                    <button
                      onClick={handleAddSkill}
                      disabled={addSkillAdding || !addSkillForm.name.trim() || !addSkillForm.body.trim()}
                      className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                    >
                      {addSkillAdding ? "Adding…" : "Add skill"}
                    </button>
                  </div>
                </div>
              </div>
            )}

            {section === "MCP" && (
              <div>
                <p className="mb-3 text-xs text-charcoal-500">
                  Connect MCP (Model Context Protocol) servers to give N.O.V.A. real tools during chat — each
                  connection is a command N.O.V.A. runs and talks to over stdio, the same way Claude Desktop
                  connects to MCP servers. When a connected server's tools are relevant, the model can actually call
                  them mid-response; results come back real, not simulated.
                </p>

                <div className="mb-4 space-y-2">
                  {mcpServers.map((s) => (
                    <div key={s.id} className="rounded-md bg-charcoal-800/60 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-2">
                          <span
                            className={`h-[7px] w-[7px] shrink-0 rounded-full ${
                              !s.enabled ? "bg-charcoal-600" : s.connected ? "bg-emerald-500" : "bg-rose-500"
                            }`}
                          />
                          <span className="truncate text-sm text-charcoal-200">{s.name}</span>
                          <span className="shrink-0 rounded-full bg-charcoal-800 px-2 py-0.5 text-[10.5px] text-charcoal-400">
                            {!s.enabled ? "disabled" : s.connected ? `${s.tools.length} tool${s.tools.length === 1 ? "" : "s"}` : "unreachable"}
                          </span>
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <button
                            onClick={() => setMcpExpanded(mcpExpanded === s.id ? null : s.id)}
                            className="text-[11px] text-charcoal-500 hover:text-charcoal-300"
                          >
                            {mcpExpanded === s.id ? "Hide" : "Details"}
                          </button>
                          <Toggle on={s.enabled} onClick={() => handleToggleMcpServer(s)} />
                          <button
                            onClick={() => handleDeleteMcpServer(s.id)}
                            className="ml-1 text-charcoal-500 hover:text-rose-400"
                            title="Remove"
                          >
                            ✕
                          </button>
                        </div>
                      </div>
                      <p className="mt-1 truncate font-mono text-[10.5px] text-charcoal-600">
                        {s.command} {s.args.join(" ")}
                      </p>
                      {s.error && <p className="mt-1 text-[10.5px] text-rose-400">{s.error}</p>}
                      {mcpExpanded === s.id && s.tools.length > 0 && (
                        <div className="mt-2 space-y-1 border-t border-charcoal-700/60 pt-2">
                          {s.tools.map((t) => (
                            <div key={t.name} className="text-[11px]">
                              <span className="font-mono text-emerald-300">{t.name}</span>
                              <span className="text-charcoal-500"> — {t.description || "no description"}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                  {!mcpLoading && mcpServers.length === 0 && (
                    <p className="text-xs text-charcoal-600">No MCP servers configured yet.</p>
                  )}
                </div>

                <div className="rounded-md border border-dashed border-charcoal-700 p-3">
                  <p className="mb-2 text-xs font-medium text-charcoal-400">Add an MCP server</p>
                  <div className="mb-3 flex flex-wrap gap-1.5">
                    {MCP_PRESETS.map((preset) => (
                      <button
                        key={preset.name}
                        type="button"
                        title={preset.hint}
                        onClick={() => setMcpForm({
                          name: preset.name,
                          command: preset.command || "",
                          args: preset.args || "",
                          url: preset.url || "",
                        })}
                        className="rounded-full bg-charcoal-800 px-2.5 py-1 text-[10.5px] text-charcoal-300 ring-1 ring-charcoal-700 hover:bg-charcoal-700 hover:text-white"
                      >
                        + {preset.name}
                      </button>
                    ))}
                  </div>
                  <div className="space-y-2">
                    <input
                      value={mcpForm.name}
                      onChange={(e) => setMcpForm((f) => ({ ...f, name: e.target.value }))}
                      placeholder="Name (e.g. Filesystem)"
                      className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                    />
                    <input
                      value={mcpForm.command}
                      onChange={(e) => setMcpForm((f) => ({ ...f, command: e.target.value }))}
                      placeholder="Command (e.g. npx or python)"
                      className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 font-mono text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                    />
                    <input
                      value={mcpForm.args}
                      onChange={(e) => setMcpForm((f) => ({ ...f, args: e.target.value }))}
                      placeholder="Args, space-separated (e.g. -y @modelcontextprotocol/server-filesystem C:\)"
                      className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 font-mono text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                    />
                    {/* A remote server is addressed by URL and has no command.
                        Filling this switches the whole entry to http. */}
                    <input
                      value={mcpForm.url}
                      onChange={(e) => setMcpForm((f) => ({ ...f, url: e.target.value }))}
                      placeholder="…or a remote server URL (e.g. https://mcp.vercel.com)"
                      className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 font-mono text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                    />
                    {mcpForm.url.trim() && (
                      <p className="text-[10.5px] text-charcoal-500">
                        Remote server — the command and args above are ignored. You may be asked to sign in on first use.
                      </p>
                    )}
                  </div>
                  {mcpError && <p className="mt-2 text-[11px] text-rose-400">{mcpError}</p>}
                  <button
                    onClick={handleAddMcpServer}
                    disabled={mcpAdding || !mcpForm.name.trim() || (!mcpForm.command.trim() && !mcpForm.url.trim())}
                    className="mt-2 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                  >
                    {mcpAdding ? "Connecting…" : "Add server"}
                  </button>
                </div>
              </div>
            )}

            {section === "Voice" && app && (
              <div>
                <ToggleRow
                  label="Speak replies aloud"
                  desc="Local speech: Piper for fast replies, or Chatterbox for cloned voices. Off skips speech synthesis."
                  on={app.voice_replies}
                  onClick={() => patchApp({ voice_replies: !app.voice_replies })}
                />
                <ToggleRow
                  label="Show speaking waveform"
                  on={app.show_reactor}
                  onClick={() => patchApp({ show_reactor: !app.show_reactor })}
                />
                <ToggleRow
                  label="Stop speaking when I type"
                  desc="Actually stops audio playback mid-sentence, not just the animation."
                  on={app.duck_on_type}
                  onClick={() => patchApp({ duck_on_type: !app.duck_on_type })}
                />
                <ToggleRow
                  label="Speak a short summary instead of the full reply"
                  desc="Voice says one quick sentence instead of reading the whole thing — the full reply is still there in chat as normal. Cuts how long you wait for speech to finish, especially on longer replies."
                  on={app.speak_summary_only}
                  onClick={() => patchApp({ speak_summary_only: !app.speak_summary_only })}
                />

                <div className="pt-4">
                  <p className="mb-1 text-xs font-medium text-charcoal-400">Push-to-talk hotkey</p>
                  <p className="mb-2 text-[11px] leading-relaxed text-charcoal-500">
                    Press
                    this system-wide hotkey any time to start (and press again to stop and send) a voice turn on
                    compact Nova, whether or not N.O.V.A. has focus. Electron accelerator format, e.g.{" "}
                    <code className="rounded bg-charcoal-800 px-1 py-0.5 text-[10.5px]">Alt+Shift+Space</code> or{" "}
                    <code className="rounded bg-charcoal-800 px-1 py-0.5 text-[10.5px]">Control+Shift+Space</code>.
                  </p>
                  <div className="flex items-center gap-2">
                    <input
                      value={hotkeyInput}
                      onChange={(e) => setHotkeyInput(e.target.value)}
                      placeholder="Alt+Shift+Space"
                      className="flex-1 rounded-md bg-charcoal-800 px-2 py-1.5 font-mono text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                    />
                    <button
                      onClick={handleApplyHotkey}
                      disabled={hotkeySaving || !hotkeyInput.trim()}
                      className="shrink-0 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                    >
                      {hotkeySaving ? "Applying…" : "Apply"}
                    </button>
                  </div>
                  {app.push_to_talk_hotkey && (
                    <p className="mt-1.5 text-[11px] text-charcoal-500">
                      Currently active: <span className="text-charcoal-300">{app.push_to_talk_hotkey}</span>
                    </p>
                  )}
                  {hotkeyError && <p className="mt-1.5 text-[11px] text-rose-400">{hotkeyError}</p>}
                </div>

                <div className="pt-4">
                  <p className="mb-1 text-xs font-medium text-charcoal-400">Voice</p>
                  <p className="mb-3 text-[11px] leading-relaxed text-charcoal-500">
                    Nova’s fast voice uses Piper on your CPU. Choose Chatterbox or a cloned voice
                    for a different sound; these take longer to generate. All speech stays local.
                  </p>

                  <div className="mb-3 space-y-1.5">
                    {voices.map((v) => {
                      const selected = app.tts_voice_id === v.id || (!app.tts_voice_id && v.id === "default");
                      return (
                        <div
                          key={v.id}
                          className={`flex items-center justify-between gap-2 rounded-md px-3 py-2 ${
                            selected ? "bg-emerald-600/20 ring-1 ring-emerald-500" : "bg-charcoal-800/60"
                          }`}
                        >
                          <button
                            onClick={() => handleSelectVoice(v.id)}
                            className="flex min-w-0 flex-1 items-center gap-2 text-left"
                          >
                            <span
                              className={`h-[9px] w-[9px] shrink-0 rounded-full border ${
                                selected ? "border-emerald-400 bg-emerald-400" : "border-charcoal-600"
                              }`}
                            />
                            <span className="truncate text-sm text-charcoal-200">{v.name}</span>
                            {v.kind === "cloned" && (
                              <span className="shrink-0 rounded-full bg-charcoal-800 px-2 py-0.5 text-[10px] text-charcoal-400">
                                cloned
                              </span>
                            )}
                          </button>
                          <div className="flex shrink-0 items-center gap-2">
                            <button
                              onClick={() => handlePreviewVoice(v)}
                              disabled={previewingId === v.id}
                              className="text-[11px] text-charcoal-500 hover:text-charcoal-300 disabled:opacity-50"
                            >
                              {previewingId === v.id ? "Playing…" : "Preview"}
                            </button>
                            {v.kind === "cloned" && (
                              <button
                                onClick={() => handleDeleteVoice(v)}
                                className="text-charcoal-500 hover:text-rose-400"
                                title="Delete"
                              >
                                ✕
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                    {!voiceLoading && voices.length === 0 && (
                      <p className="text-xs text-charcoal-600">No voices yet.</p>
                    )}
                  </div>

                  <div className="rounded-md border border-dashed border-charcoal-700 p-3">
                    <p className="mb-2 text-xs font-medium text-charcoal-400">Clone a voice from a reference clip</p>
                    <div className="space-y-2">
                      <input
                        value={voiceName}
                        onChange={(e) => setVoiceName(e.target.value)}
                        placeholder="Name (e.g. My voice)"
                        className="w-full rounded-md bg-charcoal-800 px-2 py-1.5 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                      />
                      <input
                        ref={voiceFileInputRef}
                        type="file"
                        accept="audio/*"
                        onChange={(e) => setVoiceFile(e.target.files?.[0] || null)}
                        className="w-full text-xs text-charcoal-400 file:mr-2 file:rounded-md file:border-0 file:bg-charcoal-800 file:px-2 file:py-1.5 file:text-xs file:text-charcoal-200 hover:file:bg-charcoal-700"
                      />
                      <p className="text-[10.5px] text-charcoal-600">
                        A clean, few-second clip of a single speaker works best — wav, mp3, m4a all fine.
                      </p>
                    </div>
                    {voiceError && <p className="mt-2 text-[11px] text-rose-400">{voiceError}</p>}
                    <button
                      onClick={handleAddVoice}
                      disabled={voiceAdding || !voiceName.trim() || !voiceFile}
                      className="mt-2 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                    >
                      {voiceAdding ? "Cloning…" : "Clone voice"}
                    </button>
                  </div>
                </div>

                <p className="pt-3 text-xs leading-relaxed text-charcoal-500">
                  Say “Hey Nova” to begin. Wake-word detection runs locally; after activation,
                  Nova records your request and sends it to the local transcription service.
                  Pause the microphone from the header whenever you need privacy.
                </p>
              </div>
            )}

            {section === "Models" && (
              <div className="mt-5 rounded-lg border border-charcoal-700 p-4">
                <h3 className="mb-2 text-sm font-medium text-charcoal-200">OpenRouter connection</h3>
                <div className="mb-4 space-y-1 text-sm text-charcoal-400">
                  <p>Antigravity: uses the signed-in CLI (no API key required)</p>
                  <p>OpenRouter: {status.openrouter_configured ? "✅ configured" : "⚠️ not set"}</p>
                </div>
                <label className="mb-1 block text-xs font-medium text-charcoal-400">
                  OpenRouter API key (openrouter.ai)
                </label>
                <input
                  type="password"
                  className="mb-4 w-full rounded-md bg-charcoal-800 px-3 py-2 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                  placeholder={status.openrouter_configured ? "•••••••• (leave blank to keep)" : "sk-or-..."}
                  value={openrouterKey}
                  onChange={(e) => setOpenrouterKey(e.target.value)}
                />
                <p className="mb-3 text-[11px] text-charcoal-600">
                  Voice (speech-to-text and text-to-speech) doesn't need a key here — see Voice.
                </p>
                {savedMessage && <p className="mb-2 text-xs text-emerald-400">{savedMessage}</p>}
                <button
                  className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                  onClick={handleSaveKeys}
                  disabled={saving || !openrouterKey}
                >
                  {saving ? "Saving…" : "Save"}
                </button>

                {/* TypeSafe is not a chat model and deliberately does not appear
                    in the model list: it answers typed questions with
                    probabilities, and Nova uses it to classify a message before
                    routing. Without a key the regex heuristic is used, which is
                    why this is presented as a sharpening rather than a
                    requirement. */}
                <div className="mt-6 border-t border-charcoal-700 pt-4">
                  <h3 className="mb-1 text-sm font-medium text-charcoal-200">TypeSafe (Jev)</h3>
                  <p className="mb-3 text-[12px] leading-relaxed text-charcoal-500">
                    Sharpens how Nova decides which model should answer. Jev returns a category and
                    a confidence instead of text; when it is unsure, Nova falls back to the built-in
                    rules. {typeSafe?.configured ? "Currently connected." : "Not set — the built-in rules are in use."}
                  </p>
                  <label className="mb-1 block text-xs font-medium text-charcoal-400">
                    TypeSafe API key <span className="text-charcoal-600">— console.typesafe.ai → API key</span>
                  </label>
                  <input
                    type="password"
                    className="mb-2 w-full rounded-md bg-charcoal-800 px-3 py-2 text-sm text-charcoal-100 outline-none ring-1 ring-charcoal-700 focus:ring-emerald-500"
                    placeholder={typeSafe?.configured ? "•••••••• (leave blank to keep)" : "paste the key"}
                    value={typeSafeKey}
                    onChange={(e) => setTypeSafeKey(e.target.value)}
                  />
                  {typeSafeNote && <p className="mb-2 text-[11px] text-emerald-300">{typeSafeNote}</p>}
                  <button
                    className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                    onClick={saveTypeSafe}
                    disabled={typeSafeSaving || !typeSafeKey.trim()}
                  >
                    {typeSafeSaving ? "Checking…" : "Save & verify"}
                  </button>
                </div>
              </div>
            )}

            {section === "Files" && (
              <div>
                <p className="mb-1 text-sm leading-relaxed text-charcoal-300">
                  Folders N.O.V.A. may read outside the project open in the Code tab.
                </p>
                <p className="mb-4 text-[13px] leading-relaxed text-charcoal-500">
                  Granting a folder lets N.O.V.A. find, read and quote real files in it when you ask
                  about them — assignments, notes, documents. File content can be sent to whichever
                  model answers, including cloud providers, so grant the folders you want it working
                  in rather than your whole drive. Credential files (<code className="text-charcoal-400">.env</code>,
                  private keys, <code className="text-charcoal-400">.ssh</code>) are never read, even
                  inside a granted folder, and are reported as skipped rather than quietly ignored.
                </p>

                {fileRootsError && (
                  <p className="mb-3 rounded-lg bg-rose-500/10 px-3 py-2 text-[13px] text-rose-300">{fileRootsError}</p>
                )}

                <div className="mb-3 divide-y divide-charcoal-800 overflow-hidden rounded-lg ring-1 ring-charcoal-700">
                  {fileRoots.length === 0 && (
                    <p className="px-3 py-3 text-[13px] text-charcoal-500">
                      No folders granted yet. The project open in the Code tab is always readable.
                    </p>
                  )}
                  {fileRoots.map((root) => (
                    <div key={root.path} className="flex items-center gap-3 px-3 py-2.5">
                      <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-charcoal-200" title={root.path}>
                        {root.path}
                      </span>
                      {root.is_workspace ? (
                        <span className="shrink-0 rounded-full bg-charcoal-700 px-2 py-0.5 text-[11px] text-charcoal-300">
                          open project
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={async () => {
                            setFileRootsError("");
                            try {
                              setFileRoots((await removeFileRoot(root.path)).roots);
                            } catch (err) {
                              setFileRootsError(err.message);
                            }
                          }}
                          className="shrink-0 rounded-md px-2 py-1 text-[12px] text-charcoal-400 ring-1 ring-charcoal-700 transition-colors hover:bg-rose-500/10 hover:text-rose-300"
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  ))}
                </div>

                <button
                  type="button"
                  onClick={async () => {
                    setFileRootsError("");
                    // Same provenance as the Code tab's project picker: the path
                    // comes from the OS dialog, never from chat or model output.
                    const picked = window.electronAPI?.chooseProjectFolder
                      ? await window.electronAPI.chooseProjectFolder()
                      : window.prompt("Full path to the folder to grant:");
                    if (!picked) return;
                    try {
                      setFileRoots((await addFileRoot(picked)).roots);
                    } catch (err) {
                      setFileRootsError(err.message);
                    }
                  }}
                  className="rounded-lg bg-emerald-600 px-3 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-emerald-500"
                >
                  Grant a folder…
                </button>
              </div>
            )}

            {section === "About" && (
              <div>
                <UsagePanel />
                <p className="mb-4 text-sm leading-relaxed text-charcoal-400">
                  N.O.V.A. routes each request to whichever connected model fits it best, keeping conversations,
                  projects, and pinned chats in one place.
                </p>
                <div className="grid grid-cols-[100px_1fr] gap-y-2 font-mono text-xs text-charcoal-400">
                  <span className="text-charcoal-600">Version</span>
                  <span>0.1.0</span>
                  {/* UI build identifier (task: "add a build identifier in About for
                      verification") -- a real git short hash + timestamp baked in at
                      Vite config-load time (see vite.config.js's buildId()), not a
                      hardcoded string, so it actually changes when the source does
                      and can be checked against what commit/session produced it. */}
                  <span className="text-charcoal-600">UI build</span>
                  <span>{typeof __NOVA_BUILD_ID__ !== "undefined" ? __NOVA_BUILD_ID__ : "dev (no vite define)"}</span>
                  <span className="text-charcoal-600">Router</span>
                  <span>local · port 8000</span>
                  <span className="text-charcoal-600">Connections</span>
                  <span>{stats?.model_count ?? models.length} models</span>
                  <span className="text-charcoal-600">Storage</span>
                  <span>~/.ai-council</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Per-model mascot art: which one each model is using, and a way to replace it.
 *
 * The characters people actually want here -- Claude's, OpenAI's -- belong to
 * those companies, so Nova cannot ship them. It ships an original set and lets
 * the user point at their own files, which stay in their home directory and
 * never enter the repo or a build. Picking a file is the whole flow; the
 * folder is still shown, and openable, for dropping several at once. */
function MascotsPanel() {
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(false);
  // Keyed by mascot name so one slow upload cannot blank another's row.
  const [pending, setPending] = useState({});
  const [notes, setNotes] = useState({});
  const [stamp, setStamp] = useState(1);

  const reload = useCallback(async () => {
    setBusy(true);
    const next = await refreshCustomMascots();
    setState(next);
    // Custom art is served from one URL per mascot, so a replacement is
    // byte-different at an identical address: bump a cache-buster or the
    // browser keeps showing the old picture and the upload looks ignored.
    setStamp((s) => s + 1);
    // Mascots already rendered in Workspace listen for this; otherwise they
    // keep the old art until they happen to remount.
    window.dispatchEvent(new Event("nova:mascots-updated"));
    setBusy(false);
  }, []);
  useEffect(() => { reload(); }, [reload]);

  async function pick(name, file) {
    if (!file) return;
    setPending((p) => ({ ...p, [name]: true }));
    setNotes((n) => ({ ...n, [name]: "" }));
    try {
      const saved = await uploadMascot(name, file);
      await reload();
      setNotes((n) => ({
        ...n,
        [name]: saved.frames === 2
          ? `${saved.width}×${saved.height} — two frames, animated`
          : `${saved.width}×${saved.height} — one frame. For an animation use a strip twice as wide as it is tall.`,
      }));
    } catch (err) {
      setNotes((n) => ({ ...n, [name]: err.message }));
    } finally {
      setPending((p) => ({ ...p, [name]: false }));
    }
  }

  async function revert(name) {
    setPending((p) => ({ ...p, [name]: true }));
    try {
      await deleteMascot(name);
      await reload();
      setNotes((n) => ({ ...n, [name]: "" }));
    } catch (err) {
      setNotes((n) => ({ ...n, [name]: err.message }));
    } finally {
      setPending((p) => ({ ...p, [name]: false }));
    }
  }

  return (
    <div className="mt-4 rounded-md border border-dashed border-charcoal-700 p-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-medium text-charcoal-400">Mascots</p>
        <div className="flex items-center gap-2">
          <button
            onClick={() => revealMascotDirectory().catch(() => {})}
            className="text-[10.5px] text-charcoal-500 hover:text-charcoal-300"
          >
            Open folder
          </button>
          <button onClick={reload} disabled={busy} className="text-[10.5px] text-charcoal-500 hover:text-charcoal-300 disabled:opacity-50">
            {busy ? "Checking…" : "Recheck"}
          </button>
        </div>
      </div>
      <p className="mb-2.5 text-[10.5px] leading-relaxed text-charcoal-500">
        Each model shows a pixel mascot in Workspace. Nova ships an original set — to use the real
        Claude and OpenAI characters, or anything else, pick your own image per model below. Files are
        copied to your machine only. A strip twice as wide as it is tall animates as two frames; a
        square image is a single frame.
      </p>

      <div className="space-y-1">
        {MASCOT_NAMES.map((name) => {
          const mine = Boolean(state?.found?.[name]);
          const working = Boolean(pending[name]);
          return (
            <div key={name} className="rounded-md bg-charcoal-800/50 px-2 py-1.5">
              <div className="flex items-center gap-2">
                <Mascot key={`${name}-${stamp}`} name={name} size={24} />
                <span className="w-20 shrink-0 text-[11.5px] text-charcoal-200">{name}</span>
                <span className={`shrink-0 text-[10px] ${mine ? "text-emerald-400" : "text-charcoal-600"}`}>
                  {mine ? "your art" : "bundled"}
                </span>
                <span className="flex-1" />
                <label className={`shrink-0 cursor-pointer rounded px-1.5 py-0.5 text-[10.5px] text-charcoal-400 hover:bg-charcoal-800 hover:text-charcoal-200 ${working ? "pointer-events-none opacity-50" : ""}`}>
                  {working ? "Saving…" : mine ? "Replace" : "Choose image"}
                  <input
                    type="file"
                    accept="image/png,image/webp,image/gif,image/jpeg"
                    className="hidden"
                    onChange={(e) => { pick(name, e.target.files?.[0]); e.target.value = ""; }}
                  />
                </label>
                {mine && (
                  <button
                    onClick={() => revert(name)}
                    disabled={working}
                    title="Go back to the bundled mascot"
                    className="shrink-0 rounded px-1 text-charcoal-600 hover:text-rose-400 disabled:opacity-50"
                  >
                    ✕
                  </button>
                )}
              </div>
              {notes[name] && (
                <p className="mt-1 pl-[104px] text-[10px] text-charcoal-500">{notes[name]}</p>
              )}
            </div>
          );
        })}
      </div>

      {state?.directory && (
        <p className="mt-2 break-all font-mono text-[10px] text-charcoal-600">{state.directory}</p>
      )}
      {state?.ignored?.length > 0 && (
        <p className="mt-1.5 text-[10.5px] text-amber-300/90">
          Ignored — a file dropped in by hand must be named exactly claude, codex, gemini, ollama or
          openrouter, with a .png, .webp or .gif extension: {state.ignored.join(", ")}
        </p>
      )}
    </div>
  );
}

/** What Nova has actually cost, and what it has not.
 *
 * The spend log records a flat estimate for every Claude Code and Codex call
 * so repeated escalations count against a daily cap. That number is a
 * rationing device, not a bill -- those CLIs are flat-rate subscriptions. On
 * this machine it accounts for $2.20 of a recorded $2.21, while real metered
 * spend was under a cent.
 *
 * Summing the two would produce a figure that is confident, specific,
 * believable and wrong, which is the worst kind. So they are shown as what
 * they are: money, subscription calls, and free local work.
 */
function UsagePanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getSpendBreakdown(30).then(setData).catch((e) => setError(e.message || "Usage unavailable."));
  }, []);

  if (error) return <p className="mb-4 text-[11.5px] text-charcoal-500">{error}</p>;
  if (!data) return null;

  const money = data.real_spend_usd;
  const groups = [
    { key: "metered", label: "Paid per call", tone: "text-charcoal-100" },
    { key: "subscription", label: "Subscription", tone: "text-charcoal-300" },
    { key: "local", label: "Local", tone: "text-charcoal-300" },
  ];

  return (
    <div className="mb-5 rounded-md border border-charcoal-700 p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <p className="text-xs font-medium text-charcoal-400">Usage · last 30 days</p>
        <p className="text-[11px] text-charcoal-500">
          <span className="font-medium text-emerald-300">
            {money < 0.01 ? "under $0.01" : `$${money.toFixed(2)}`}
          </span>{" "}
          actually spent
        </p>
      </div>

      <div className="space-y-1.5">
        {groups.map(({ key, label, tone }) => {
          const group = data[key];
          if (!group?.calls) return null;
          return (
            <div key={key}>
              <div className="flex items-baseline gap-2 text-[11.5px]">
                <span className={`w-24 shrink-0 ${tone}`}>{label}</span>
                <span className="text-charcoal-500">
                  {group.calls} {group.calls === 1 ? "call" : "calls"}
                </span>
                <span className="flex-1" />
                <span className="text-[10.5px] tabular-nums text-charcoal-500">
                  {/* Dollars only where dollars are meant. */}
                  {key === "metered"
                    ? (group.cost_usd < 0.01 ? "under $0.01" : `$${group.cost_usd.toFixed(2)}`)
                    : `${group.tokens.toLocaleString()} tokens`}
                </span>
              </div>
              <div className="mt-0.5 flex flex-wrap gap-x-3 pl-24 text-[10.5px] text-charcoal-600">
                {group.providers.map((p) => (
                  <span key={p.provider}>{p.provider} {p.calls}</span>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <p className="mt-2.5 text-[10.5px] leading-relaxed text-charcoal-600">
        Claude Code and Codex are flat-rate, so Nova's recorded figure for them
        (${data.subscription.cost_usd.toFixed(2)}) rations a daily cap rather than
        reporting a bill. Local models cost nothing.
      </p>
    </div>
  );
}
