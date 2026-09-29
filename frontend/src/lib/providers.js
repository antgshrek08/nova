// Provider color/label map for the Workspace network view. Matches the
// N.O.V.A. design's exact palette (Claude Design project ed60998f, template
// NovaNetwork.dc.html) so nodes are recognizable at a glance by company.
export const PROVIDERS = {
  hermes: { color: "#2dd4bf", label: "Hermes" },
  antigravity_cli: { color: "#60a5fa", label: "Antigravity" },
  anthropic: { color: "#f0913e", label: "Anthropic" },
  openai: { color: "#34d399", label: "OpenAI" },
  google: { color: "#60a5fa", label: "Google" },
  openrouter: { color: "#a78bfa", label: "OpenRouter" },
  ollama: { color: "#f472b6", label: "Ollama" },
  // Not an LLM provider -- the OpenClaw Gateway bridge ("Send to Claw"
  // manual action, see backend/app/openclaw.py). Deliberately a distinct
  // color/bucket ("actions", not fast/code/reasoning) from every model
  // provider above so it reads as a different kind of node in the Workspace
  // network, not just another model.
  openclaw: { color: "#2dd4bf", label: "OpenClaw" },
  // User-added generic OpenAI-compatible endpoint (Settings > Models > Add
  // Model > Custom) -- previously had no entry here at all, so every
  // custom node fell through to UNKNOWN_PROVIDER's flat gray "Other" with
  // no colored dot, reading as an unfinished/broken card rather than a
  // real connected model. Not a company brand color (there's no single
  // "custom" company), so an amber distinct from every real provider's
  // color above.
  custom: { color: "#fbbf24", label: "Custom" },
};
export const UNKNOWN_PROVIDER = { color: "#94a3b8", label: "Other" };

export function providerMeta(provider) {
  return PROVIDERS[provider] || UNKNOWN_PROVIDER;
}

export function modelDisplayName(model) {
  if (model.id === "claude_cli") return `Claude Code${model.name === "opus" ? " · Opus" : ""}`;
  if (model.id === "codex_cli") return "Codex";
  if (model.id === "antigravity_cli") return "Antigravity";
  const names = {
    "ollama:qwen3.5:4b": "Qwen 3.5 · 4B",
    "ollama:qwen2.5:0.5b": "Qwen 2.5 · 0.5B",
    "ollama:deepseek-r1:7b": "DeepSeek R1 · 7B",
    "ollama:deepseek-r1:1.5b": "DeepSeek R1 · 1.5B",
    "ollama:hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M": "Liquid LFM 2.5 · 2.6B (Q4)",
  };
  return names[model.id] || model.name;
}

// Mirrors backend main.py's CATEGORY_BUCKET -- kept here as the reference
// mapping for the network view's 3 spines (reasoning=left, code=right,
// fast/local=down). No longer used for OpenRouter job matching (jobNodeId
// now matches OpenRouter jobs on their exact live model id instead, since
// /models lists every free model individually -- see jobNodeId below).
export const CATEGORY_BUCKET = {
  coding: "code",
  frontend_ui_code: "code",
  reasoning_math: "reasoning",
  agentic_planning: "reasoning",
  long_context: "reasoning",
  vision_multimodal: "reasoning",
  design_review: "reasoning",
  quick_simple: "fast",
  general_writing: "fast",
  multilingual: "fast",
  image_generation: "reasoning",
};

/** Maps a live agent job (from /ws/agents) onto a node id from /models. */
export function jobNodeId(job) {
  if (!job) return null;
  if (job.provider === "claude_cli") return "claude_cli";
  if (job.provider === "codex_cli") return "codex_cli";
  if (job.provider === "gemini") return "gemini";
  if (job.provider === "openclaw") return "openclaw";
  if (job.provider === "ollama" && job.model) return `ollama:${job.model}`;
  if (job.provider === "custom" && job.custom_model_row_id) return `custom:${job.custom_model_row_id}`;
  // /models now lists every live free OpenRouter model individually as
  // `openrouter:<model id>` (see main.py's _build_models) rather than one
  // aggregate node per category bucket, so a job matches its exact model,
  // not just its category -- more precise than the old bucket match, and
  // has to change together with that node-id scheme or every OpenRouter
  // dispatch would stop finding a node to pulse at all.
  if (job.provider === "openrouter" && job.model) return `openrouter:${job.model}`;
  return null;
}
