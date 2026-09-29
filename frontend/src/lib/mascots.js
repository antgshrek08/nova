/** Per-model mascots: which sprite belongs to a model, and where to get it.
 *
 * Two sources, in order. A file the user dropped into ~/.ai-council/mascots/
 * wins — that is how the real Clawd or a Codex pet gets in without any of that
 * artwork entering the repo. Otherwise the bundled originals ship with Nova, so
 * the crew reads correctly before anyone has collected a single file.
 *
 * Sprites are two frames side by side (a 128x64 strip is two 64x64 frames), so
 * the idle bob is a background-position swap rather than a second image. A
 * dropped-in square image is treated as one frame and simply does not animate.
 */
import claudeSprite from "../assets/mascots/claude.png";
import codexSprite from "../assets/mascots/codex.png";
import geminiSprite from "../assets/mascots/gemini.png";
import ollamaSprite from "../assets/mascots/ollama.png";
import openrouterSprite from "../assets/mascots/openrouter.png";
import { BACKEND_URL } from "../api.js";

const BUNDLED = {
  claude: claudeSprite,
  codex: codexSprite,
  gemini: geminiSprite,
  ollama: ollamaSprite,
  openrouter: openrouterSprite,
};

/** Provider id -> mascot name. Nova is deliberately absent: it keeps its own
 * rigged character and is not part of this pixel set. */
const BY_PROVIDER = {
  claude_cli: "claude",
  claude_cli_plan: "claude",
  anthropic: "claude",
  codex_cli: "codex",
  codex_cli_plan: "codex",
  openai: "codex",
  antigravity_cli: "gemini",
  gemini_cli: "gemini",
  gemini: "gemini",
  google: "gemini",
  ollama: "ollama",
  local: "ollama",
  openrouter: "openrouter",
};

/** Fallbacks when only a model id is known. Checked as substrings, longest
 * first, so "claude-3-5-sonnet" and "anthropic/claude" both land correctly and
 * "gemini-2.0-flash" does not get caught by a shorter, earlier pattern. */
const BY_MODEL_HINT = [
  ["antigravity", "gemini"],
  ["anthropic", "claude"],
  ["claude", "claude"],
  ["codex", "codex"],
  ["gpt-", "codex"],
  ["openai", "codex"],
  ["gemini", "gemini"],
  ["qwen", "ollama"],
  ["llama", "ollama"],
  ["mistral", "ollama"],
  ["deepseek", "openrouter"],
  ["glm", "openrouter"],
  ["kimi", "openrouter"],
  ["nemotron", "openrouter"],
];

export const MASCOT_NAMES = Object.keys(BUNDLED);

/** The mascot for a model, or null when nothing sensible matches -- callers
 * show Nova's own mark rather than an arbitrary character. */
export function mascotFor({ provider, model } = {}) {
  const byProvider = BY_PROVIDER[String(provider || "").toLowerCase()];
  if (byProvider) return byProvider;
  const id = String(model || "").toLowerCase();
  if (!id) return null;
  for (const [hint, name] of BY_MODEL_HINT) {
    if (id.includes(hint)) return name;
  }
  return null;
}

/** Custom art the user has dropped in, as {name: true}. Fetched once and
 * cached: it changes when someone copies a file into a folder, which is not
 * something worth polling for. */
let customPromise = null;
// Bumped on every refresh and appended to custom art URLs. Replacing
// claude.png puts different bytes at an identical address, so without this the
// browser serves the old picture from cache and the upload looks ignored.
let stamp = 1;

export function loadCustomMascots() {
  if (!customPromise) {
    customPromise = fetch(`${BACKEND_URL}/mascots`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("unavailable"))))
      .then((data) => {
        const found = {};
        for (const [name, entry] of Object.entries(data.mascots || {})) {
          if (entry.custom) found[name] = true;
        }
        return { found, ignored: data.ignored || [], directory: data.directory };
      })
      .catch(() => ({ found: {}, ignored: [], directory: null }));
  }
  return customPromise;
}

/** Forget the cached list — call after the user has been told to drop files in. */
export function refreshCustomMascots() {
  customPromise = null;
  stamp += 1;
  return loadCustomMascots();
}

/** The image URL for a mascot. `custom` is the map from loadCustomMascots. */
export function mascotUrl(name, custom = {}) {
  if (!name) return null;
  if (custom[name]) return `${BACKEND_URL}/mascots/${name}?v=${stamp}`;
  return BUNDLED[name] || null;
}
