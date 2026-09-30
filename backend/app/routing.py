"""Category -> provider routing, matching the build spec's routing rules.

Each category has an ordered chain of steps exactly as described in the spec
(free choice, then fallback free choice, then local Ollama, escalate to
Claude/Codex CLI only as a last resort — coding skips straight to the CLIs).
Claude CLI, Codex CLI, and Ollama are now wired up (see providers.py): CLI
steps route straight to the subprocess wrapper, and Ollama steps match
against whatever's actually pulled locally, live, the same way OpenRouter
steps match its live free-tier roster. Only diffusion (image generation)
remains unavailable in Phase 1 — it needs a separate pipeline, not a text
completion call.

If a whole spec chain is exhausted for a category that spec allows a
free-tier attempt on, Gemini is used as a Phase-1-only interim safety net so
the app stays usable while a given category's local/free options are down or
exhausted — this is called out explicitly in the trace as "not in spec chain,
Phase 1 interim only". Coding and image_generation never get this interim
fallback: the spec is explicit that coding is CLI-only with "no free-first
attempt", and image generation needs a separate diffusion pipeline, not a
text completion call.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass

from . import config, costs, db, providers

PROVIDER_AVAILABLE = {
    "claude_cli": True,
    "codex_cli": True,
    "ollama": True,
    "openrouter": True,
    "diffusion": False,
}


@dataclass
class ChainStep:
    provider: str  # "claude_cli" | "codex_cli" | "ollama" | "openrouter" | "diffusion"
    label: str
    keywords: list[str] | None = None  # required for provider == "openrouter"


@dataclass
class RoutingResult:
    category: str
    provider: str  # "openrouter" | "ollama" | "custom" | "claude_cli" | "codex_cli" | "antigravity_cli" | "unavailable"
    model: str | None
    label: str
    trace: list[str]
    # Set only when provider == "custom": main.py looks the row back up by
    # id to get api_base/api_key at dispatch time, rather than carrying
    # secrets on this object -- RoutingResult's other fields get echoed back
    # to the frontend verbatim as the /chat "meta" event.
    custom_model_row_id: int | None = None


CATEGORY_CHAINS: dict[str, list[ChainStep]] = {
    "coding": [
        ChainStep("claude_cli", "Claude Code CLI"),
        ChainStep("codex_cli", "Codex CLI"),
    ],
    "frontend_ui_code": [
        ChainStep("openrouter", "Kimi K3", ["kimi-k3", "kimi k3", "moonshotai/kimi"]),
        ChainStep("claude_cli", "Claude Code CLI"),
        ChainStep("codex_cli", "Codex CLI"),
    ],
    "reasoning_math": [
        ChainStep("claude_cli", "Claude Code CLI"),
        ChainStep("codex_cli", "Codex CLI"),
        ChainStep("antigravity_cli", "Antigravity CLI"),
        ChainStep("openrouter", "Math & Reasoning (Qwen / Gemma / DeepSeek)", ["qwen", "gemma", "nemotron", "deepseek", "glm"]),
        ChainStep("openrouter", "Qwen / Nemotron", ["qwen", "nemotron", "gemma"]),
        ChainStep("ollama", "Local Ollama distill", ["qwen", "distill"]),
    ],
    "agentic_planning": [
        ChainStep("claude_cli", "Claude Code CLI"),
        ChainStep("codex_cli", "Codex CLI"),
        ChainStep("antigravity_cli", "Antigravity CLI"),
        ChainStep("openrouter", "Kimi K2.6/K3", ["kimi-k2.6", "kimi-k3", "kimi"]),
        ChainStep("openrouter", "GLM-5.2", ["glm-5", "glm-4.5", "glm"]),
        ChainStep("openrouter", "Qwen3.7", ["qwen3.7", "qwen-3.7", "qwen3", "qwen"]),
    ],
    "general_writing": [
        ChainStep("openrouter", "GLM-5.2", ["glm-5", "glm-4.5", "glm"]),
        ChainStep("openrouter", "Kimi", ["kimi"]),
        ChainStep("openrouter", "Qwen3.7", ["qwen3.7", "qwen-3.7", "qwen"]),
    ],
    "multilingual": [
        ChainStep("openrouter", "Qwen3.6/3.7", ["qwen3.7", "qwen3.6", "qwen-3", "qwen"]),
        ChainStep("openrouter", "GLM-5.2", ["glm-5", "glm-4.5", "glm"]),
    ],
    "long_context": [
        ChainStep("openrouter", "DeepSeek V4 Flash", ["deepseek-flash", "deepseek-v4", "deepseek"]),
        ChainStep("openrouter", "Qwen long-context", ["qwen-long", "qwen1m", "qwen-2.5-1m", "qwen"]),
    ],
    "quick_simple": [
        ChainStep("ollama", "Qwen3.5 4B (local)", ["qwen3.5:4b"]),
    ],
    # Local vision first, for the same reason the rest of Nova prefers local:
    # a screenshot is the most private thing the user can hand it. Screenshots
    # carry whatever else was on screen -- messages, tabs, account pages -- so
    # a model on this machine is the right default and the cloud steps are the
    # fallback, not the other way round.
    "vision_multimodal": [
        ChainStep("ollama", "Local vision model", ["gemma3:4b", "qwen2.5-vl", "qwen2-vl", "llava", "minicpm-v", "moondream", "gemma3"]),
        ChainStep("openrouter", "Ling 3.0 Flash VL", ["ling-3.0-flash-vl", "flash-vl", "-vl"]),
        ChainStep("openrouter", "Nemotron Omni", ["nemotron-3-nano-omni", "omni"]),
    ],
    "design_review": [
        ChainStep("ollama", "Local vision model", ["gemma3:4b", "qwen2.5-vl", "qwen2-vl", "llava", "minicpm-v", "moondream", "gemma3"]),
        ChainStep("openrouter", "Ling 3.0 Flash VL", ["ling-3.0-flash-vl", "flash-vl", "-vl"]),
        ChainStep("openrouter", "Nemotron Omni", ["nemotron-3-nano-omni", "omni"]),
    ],
    "image_generation": [
        ChainStep("diffusion", "Qwen-Image (2512)", ["qwen-image"]),
        ChainStep("diffusion", "FLUX.1 [dev]", ["flux"]),
    ],
}

# Categories where the spec chain is a free-first attempt (not the strict
# "coding always goes to Claude/Codex" rule), so a Gemini interim fallback is
# reasonable if every OpenRouter/Ollama step in the chain is exhausted.
_ALLOW_GEMINI_INTERIM = {
    cat for cat in CATEGORY_CHAINS if cat not in ("coding", "image_generation")
}

# Emergency-only fallback, used strictly when the daily budget cap has just
# blocked a claude_cli/codex_cli dispatch. Not part of the spec's routing
# table (coding is deliberately CLI-only there, "no free-first attempt") --
# this exists so a blown budget degrades to a free coding-capable model
# instead of refusing outright. Ollama tried first (free, local, no rate
# limit), then OpenRouter's free tier.
_BUDGET_FALLBACK_KEYWORDS = ["coder", "codestral", "code", "coding"]


async def _resolve_budget_fallback(
    category: str,
    trace: list[str],
    free_models: list | None,
    local_models: list | None,
    exclude_models: set[str] | None = None,
) -> RoutingResult | None:
    """Emergency free-tier fallback after a claude_cli/codex_cli step was
    blocked by the daily budget cap. Tries local Ollama first (free, no rate
    limit), then OpenRouter's free tier, both against a generic coding-model
    keyword set. Returns None if neither has a match, so the caller can
    report a clean "blocked" result instead of silently going unavailable.
    """
    if local_models is None:
        try:
            local_models = await providers.get_local_ollama_models()
        except Exception as exc:  # noqa: BLE001
            trace.append(f"Could not fetch local Ollama model list for budget fallback: {exc}")
            local_models = []
    disabled = await db.list_disabled_models()
    local_models = [m for m in (local_models or []) if m.id not in disabled]
    match = providers.find_free_model_by_keywords(local_models, _BUDGET_FALLBACK_KEYWORDS, exclude=exclude_models)
    if match is not None:
        label = "Local Ollama coding model (budget fallback)"
        trace.append(f"Daily budget cap reached -- falling back to {label} -> {match.id} (local Ollama).")
        return RoutingResult(category, "ollama", match.id, label, trace)

    if free_models is None:
        try:
            free_models = await providers.get_free_openrouter_models()
        except Exception as exc:  # noqa: BLE001
            trace.append(f"Could not fetch OpenRouter free model list for budget fallback: {exc}")
            free_models = []
    match = providers.find_free_model_by_keywords(free_models or [], _BUDGET_FALLBACK_KEYWORDS, exclude=exclude_models) if config.openrouter_api_key() else None
    if match is not None:
        label = "Free OpenRouter coding model (budget fallback)"
        trace.append(
            f"Daily budget cap reached -- falling back to {label} -> {match.id} (OpenRouter free tier)."
        )
        return RoutingResult(category, "openrouter", match.id, label, trace)

    trace.append(
        "Daily budget cap reached and no free coding-capable model is currently "
        "available either (checked local Ollama and OpenRouter free tier). Blocked "
        "until the cap resets tomorrow, or raise DAILY_BUDGET_USD."
    )
    return None


# app_settings key (see db.get_app_settings/set_app_settings) holding a JSON
# {category: model_id} map -- a persistent manual pin set from Settings, on
# top of (checked before) the automatic chain below. model_id uses the same
# id shape /models returns ("claude_cli:opus", "openrouter:<id>",
# "ollama:<id>", "custom:<row_id>", "codex_cli", "antigravity_cli"), so the same
# resolve_model_id() parser below serves both this persistent per-category
# override and main.py's one-off per-request override.
CATEGORY_OVERRIDES_SETTINGS_KEY = "category_model_overrides"


async def resolve_model_id(model_id: str, category: str, trace: list[str]) -> RoutingResult | None:
    """Builds a RoutingResult directly from a specific catalog model id,
    bypassing the category's automatic fallback chain entirely -- the
    mechanism behind "let the user manually specify which model handles a
    category or a specific request, as an override on top of automatic
    routing". Returns None for an id that doesn't parse or no longer
    resolves (e.g. a custom model row that's since been deleted, or a
    Claude CLI alias detection didn't find on this subscription) so the
    caller can fall back to the automatic chain instead of hard-erroring on
    a stale override.
    """
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    family = model_id.split(':', 1)[0]
    if family in ('claude_cli', 'claude_cli_plan', 'codex_cli', 'codex_cli_plan'):
        path = config.CLAUDE_CLI_PATH if family.startswith('claude') else config.CODEX_CLI_PATH
        if not shutil.which(path) or await costs.tracker.is_over_budget():
            return None
    if model_id == "hermes":
        from . import hermes
        if not hermes.status()["installed"]:
            return None
        return RoutingResult(category, "hermes", "qwen3.5:4b", "Hermes · Qwen 3.5 4B", trace)
    if model_id == "codex_cli":
        real_model = config.CODEX_CLI_MODEL or None
        return RoutingResult(category, "codex_cli", real_model, real_model or "Codex CLI", trace)

    if model_id == "claude_cli" or model_id.startswith("claude_cli:"):
        alias = model_id.split(":", 1)[1] if ":" in model_id else None
        if alias is None:
            real_model = config.CLAUDE_CLI_MODEL or None
            return RoutingResult(category, "claude_cli", real_model, real_model or "Claude Code CLI", trace)
        return RoutingResult(category, "claude_cli", alias, f"Claude ({alias})", trace)

    if model_id in ("claude_cli_plan", "codex_cli_plan"):
        return RoutingResult(category, model_id, None, "Claude" if model_id == "claude_cli_plan" else "Codex", trace)
    if model_id == "gemini":
        return None  # This installation uses Antigravity for Google-account access.
    if model_id == "antigravity_cli":
        from .antigravity_cli import availability
        if not availability()['available']:
            return None
        return RoutingResult(category, "antigravity_cli", "gemini-3.8-flash-low", "Antigravity", trace)
    if model_id == "gemini_cli":
        from .gemini_cli import availability
        if not availability()['available']:
            return None
        return RoutingResult(category, "gemini_cli", None, "Gemini CLI", trace)

    if model_id.startswith("openrouter:"):
        if not category.startswith('everyday'):
            return None
        real_id = model_id.split(":", 1)[1]
        if not config.openrouter_api_key():
            return None
        if real_id == "openrouter/free":
            return RoutingResult(category, "openrouter", real_id, "OpenRouter Free Router", trace)
        try:
            roster = await providers.get_free_openrouter_models()
        except Exception:
            return None
        match = next((m for m in roster if m.id == real_id), None)
        if match is None or (category in ('vision_multimodal', 'design_review') and 'image' not in match.input_modalities):
            return None
        return RoutingResult(category, "openrouter", real_id, real_id, trace)

    if model_id.startswith("ollama:"):
        real_id = model_id.split(":", 1)[1]
        if real_id in await db.list_disabled_models():
            return None
        try:
            if not any(m.id == real_id for m in await providers.get_local_ollama_models()):
                return None
        except Exception:
            return None
        return RoutingResult(category, "ollama", real_id, real_id, trace)

    if model_id.startswith("custom:"):
        try:
            row_id = int(model_id.split(":", 1)[1])
        except ValueError:
            return None
        row = await db.get_custom_model(row_id)
        if row is None or not row.get('enabled', True):
            return None
        if row['provider'] in ('ollama', 'openrouter'):
            return await resolve_model_id(f"{row['provider']}:{row['model_id']}", category, trace)
        if row['provider'] == 'custom' and not row.get('api_base'):
            return None
        return RoutingResult(
            category, "custom", row["model_id"], row["name"], trace, custom_model_row_id=row_id
        )

    return None


async def get_category_overrides() -> dict[str, str]:
    stored = (await db.get_app_settings()).get(CATEGORY_OVERRIDES_SETTINGS_KEY)
    if not stored:
        return {}
    try:
        parsed = json.loads(stored)
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}


async def set_category_override(category: str, model_id: str | None) -> dict[str, str]:
    """model_id=None clears the override for that category (back to automatic)."""
    if category not in CATEGORY_CHAINS:
        raise ValueError('Unknown routing category')
    if model_id is not None and await resolve_model_id(model_id, category, []) is None:
        raise ValueError('Selected model is unavailable, disabled, or incompatible with this category')
    overrides = await get_category_overrides()
    if model_id is None:
        overrides.pop(category, None)
    else:
        overrides[category] = model_id
    await db.set_app_settings({CATEGORY_OVERRIDES_SETTINGS_KEY: json.dumps(overrides)})
    return overrides


# Homework has its own model (the user's setup: the Token Harbor key is for homework
# only). A homework request is routed under this category, whose custom
# model (Settings > Models, category "homework") is tried first; with no such
# model, or when it fails, the request falls back to the usual chain.
HOMEWORK_CATEGORY = "homework"

_HOMEWORK_RE = re.compile(
    r"\b(homework|hw|assignments?|coursework|canvas|knewton|alta|smartbook|worksheet|problem\s+set|"
    r"quiz(?:zes)?|study\s+guide|essay|lab\s+report|discussion\s+post|syllabus|(?:my|school|college|calculus|economics)\s+(?:course(?:s)?|class(?:es)?))\b",
    re.IGNORECASE,
)

def is_homework(message: str, homework_mode: bool = False) -> bool:
    """A request about schoolwork: Homework Mode is on, or the message says so.

    This includes hands-on Onyx-driving requests ("continue that homework")
    on purpose -- the user wants those on the homework model too. What used to
    go wrong there (a weak model spinning uselessly) is handled downstream
    instead: agent_loop's ProviderNoProgressError makes that count as a
    failure so the chain falls through to Claude, which the homework chain
    now ends on for exactly this reason (see CATEGORY_CHAINS[HOMEWORK_CATEGORY]
    below)."""
    return bool(homework_mode or _HOMEWORK_RE.search(message or ""))


async def has_homework_model() -> bool:
    return bool(await db.list_custom_models(category=HOMEWORK_CATEGORY, enabled_only=True))


async def resolve(
    category: str, exclude_models: set[str] | None = None, prefer_local: bool = False
) -> RoutingResult:
    """Resolve a category to a provider/model per its spec chain.

    `exclude_models` skips model ids already tried and rejected earlier in
    *this same request* (see main.py's /chat retry loop) -- a step whose
    keyword match is excluded is treated the same as "no matching model" and
    the walk continues to the next step, which is what turns a single
    provider's rate limit into an automatic reroute instead of a dead end.

    `prefer_local` (Settings > General > "Prefer local") moves this
    category's ollama step(s) ahead of its cloud (openrouter/claude_cli/
    codex_cli) steps -- a stable reorder, so relative order within each
    group is unchanged -- rather than inventing a local option for
    categories whose spec chain has none (frontend_ui_code, agentic_
    planning, vision_multimodal, etc. stay exactly as-is: nothing to prefer
    when the chain never offered a local step to begin with).
    """
    chain = list(CATEGORY_CHAINS.get(category, CATEGORY_CHAINS["general_writing"]))
    # OpenRouter's free tier is reserved for the nightly Everyday jobs
    # (daily_tasks.py, canvas_sync.py) so chat cannot exhaust their quota, so
    # every OpenRouter step is normally dropped from chat routing.
    #
    # The two image categories are the exception, because for them the rule
    # produced an empty chain rather than a cheaper one. Their spec steps are
    # all OpenRouter, they are denied the local text fallback below, and the
    # result was that an attached screenshot resolved to "unavailable" and
    # fell through to a blind model that described it anyway. A handful of
    # image questions will not drain a nightly quota; a confidently invented
    # description of the user's own screen is a real cost. Local vision still
    # ranks first in both chains, so this is only reached when nothing on
    # this machine can see.
    _VISION_CATEGORIES = ('vision_multimodal', 'design_review')
    if category not in _VISION_CATEGORIES:
        chain = [step for step in chain if step.provider != 'openrouter']
    if category not in ('coding', 'frontend_ui_code', *_VISION_CATEGORIES, 'image_generation', 'long_context') and not any(s.provider == 'ollama' for s in chain):
        chain.append(ChainStep('ollama', 'Qwen3.5 4B (local)', ['qwen3.5:4b']))
    exclude_models = exclude_models or set()
    trace: list[str] = []

    overrides = await get_category_overrides()
    override_id = overrides.get(category)
    if override_id:
        forced = await resolve_model_id(override_id, category, trace)
        if forced is not None and forced.model not in exclude_models:
            trace.append(f"Manual override for '{category}' (Settings) -> {forced.label}.")
            return forced
        trace.append(
            f"Manual override for '{category}' ('{override_id}') is no longer available -- "
            "falling back to automatic routing."
        )

    # User's Explicit Primary Model Choice (Settings > Models):
    # The user chooses their primary model -- never locked to Antigravity or any single provider
    app_settings = await db.get_app_settings()
    primary_model_id = app_settings.get("primary_model")
    if primary_model_id and category not in ("coding", "image_generation"):
        primary_forced = await resolve_model_id(primary_model_id, category, trace)
        if primary_forced is not None and primary_forced.model not in exclude_models:
            # Quick questions don't need the biggest model, and it is the
            # slowest to answer: Opus through Claude Code takes about twice
            # Sonnet's time for "what's 2+2". Settings > Models can turn this off.
            fast = FAST_SIBLINGS.get((primary_forced.provider, _tier(primary_forced.model)))
            if category == "quick_simple" and fast and app_settings.get("fast_simple_replies", "1") != "0":
                quick = await resolve_model_id(fast, category, trace)
                if quick is not None and quick.model not in exclude_models:
                    trace.append(f"Quick question -> {quick.label}, the faster sibling of your main model "
                                 f"({primary_forced.label}).")
                    return quick
            trace.append(f"User primary model selected in Settings -> {primary_forced.label}.")
            return primary_forced

    if prefer_local and any(step.provider == "ollama" for step in chain):
        chain = sorted(chain, key=lambda step: step.provider != "ollama")
        trace.append("'Prefer local' is on -- local Ollama step(s) moved ahead of cloud options in this chain.")

    custom_steps = await db.list_custom_models(category=category, enabled_only=True)
    custom_steps = [step for step in custom_steps if step['provider'] != 'openrouter']

    free_models = None
    if any(step.provider == "openrouter" for step in chain) or any(
        c["provider"] == "openrouter" for c in custom_steps
    ):
        try:
            free_models = await providers.get_free_openrouter_models()
        except Exception as exc:  # noqa: BLE001
            trace.append(f"Could not fetch OpenRouter free model list: {exc}")
            free_models = []

    local_models = None
    if any(step.provider == "ollama" for step in chain) or any(
        c["provider"] == "ollama" for c in custom_steps
    ):
        try:
            local_models = await providers.get_local_ollama_models()
            disabled = await db.list_disabled_models()
            if disabled:
                local_models = [m for m in local_models if m.id not in disabled]
        except Exception as exc:  # noqa: BLE001
            trace.append(f"Could not fetch local Ollama model list: {exc}")
            local_models = []

    # User-added models (Settings > Models > Add Model) are tried first, in
    # the order they were added -- an explicit per-category addition is
    # taken as a preference over the spec's built-in keyword chain below.
    for custom in custom_steps:
        if custom["model_id"] in exclude_models:
            trace.append(
                f"Skipped custom model '{custom['name']}': already tried and rate-limited this request."
            )
            continue

        if custom["provider"] == "openrouter":
            if not config.openrouter_api_key() or not any(m.id == custom['model_id'] for m in (free_models or [])):
                continue
            trace.append(f"Routed to custom model '{custom['name']}' -> {custom['model_id']} (OpenRouter).")
            return RoutingResult(category, "openrouter", custom["model_id"], custom["name"], trace)

        if custom["provider"] == "ollama":
            still_pulled = any(m.id == custom["model_id"] for m in (local_models or []))
            if not still_pulled:
                trace.append(
                    f"Skipped custom model '{custom['name']}': '{custom['model_id']}' is no longer "
                    "pulled in local Ollama (or was disabled in Settings > Models)."
                )
                continue
            trace.append(f"Routed to custom model '{custom['name']}' -> {custom['model_id']} (local Ollama).")
            return RoutingResult(category, "ollama", custom["model_id"], custom["name"], trace)

        if custom["provider"] == "custom":
            trace.append(f"Routed to custom model '{custom['name']}' -> {custom['model_id']} (custom endpoint).")
            return RoutingResult(
                category, "custom", custom["model_id"], custom["name"], trace, custom_model_row_id=custom["id"]
            )

    budget_blocked = False

    for step in chain:
        if not PROVIDER_AVAILABLE.get(step.provider, False):
            trace.append(f"Skipped {step.label} ({step.provider}): not available in Phase 1.")
            continue

        if step.provider == "openrouter":
            if not config.openrouter_api_key():
                continue
            candidates = free_models or []
            if category in ('vision_multimodal', 'design_review'):
                candidates = [m for m in candidates if 'image' in m.input_modalities]
            match = providers.find_free_model_by_keywords(
                candidates, step.keywords or [], exclude=exclude_models
            )
            if match is None:
                # A candidate existed pre-exclusion but got filtered out here
                # specifically means IT was the one rate-limited earlier this
                # request -- not "no matching model", which would be wrong
                # and misleading in the trace (this category's other steps
                # weren't touched, they just have nothing free right now).
                unfiltered = providers.find_free_model_by_keywords(free_models or [], step.keywords or [])
                reason = (
                    f"{unfiltered.id} already tried and rate-limited this request"
                    if unfiltered is not None
                    else "no matching free model currently on OpenRouter"
                )
                trace.append(f"Skipped {step.label}: {reason}.")
                continue
            trace.append(f"Routed to {step.label} -> {match.id} (OpenRouter free tier).")
            return RoutingResult(category, "openrouter", match.id, step.label, trace)

        if step.provider == "ollama":
            match = providers.find_free_model_by_keywords(
                local_models or [], step.keywords or [], exclude=exclude_models
            )
            if match is None:
                unfiltered = providers.find_free_model_by_keywords(local_models or [], step.keywords or [])
                reason = (
                    f"{unfiltered.id} already tried and rate-limited this request"
                    if unfiltered is not None
                    else "no matching model currently pulled in local Ollama"
                )
                trace.append(f"Skipped {step.label}: {reason}.")
                continue
            trace.append(f"Routed to {step.label} -> {match.id} (local Ollama).")
            return RoutingResult(category, "ollama", match.id, step.label, trace)

        if step.provider in ("claude_cli", "codex_cli"):
            cli_path = config.CLAUDE_CLI_PATH if step.provider == 'claude_cli' else config.CODEX_CLI_PATH
            if not shutil.which(cli_path):
                trace.append(f'Skipped {step.label}: executable not installed.')
                continue
            if await costs.tracker.is_over_budget():
                budget_blocked = True
                spend = await costs.tracker.status()
                trace.append(
                    f"Skipped {step.label}: daily budget cap (${spend['daily_budget_usd']:.2f}) "
                    f"reached (${spend['total_cost_usd']:.4f} spent today) -- blocking paid-tier dispatch."
                )
                continue
            # Each CLI is dispatched with config.CLAUDE_CLI_MODEL /
            # config.CODEX_CLI_MODEL (see providers.stream_claude_cli/
            # stream_codex_cli) -- empty means "whatever the CLI's own
            # default resolves to". step.label is a generic fallback; the
            # real model, detected empirically against that same override
            # (see providers.detect_claude_cli_model/detect_codex_cli_model),
            # is what actually gets shown wherever this label surfaces (chat
            # badges, Workspace nodes, agent job cards).
            real_model = (config.CLAUDE_CLI_MODEL if step.provider == "claude_cli" else config.CODEX_CLI_MODEL) or None
            label = real_model or step.label
            trace.append(f"Routed to {label} ({step.provider}).")
            return RoutingResult(category, step.provider, real_model, label, trace)

        # diffusion steps that report available would land here
        trace.append(f"Skipped {step.label}: provider type '{step.provider}' has no Phase 1 handler.")

    if budget_blocked:
        fallback = await _resolve_budget_fallback(category, trace, free_models, local_models, exclude_models)
        if fallback is not None:
            return fallback
        return RoutingResult(category, "unavailable", None, "Blocked (budget cap)", trace)

    # Vision categories get Gemini, and get it before the text fallbacks.
    #
    # Their spec chains are OpenRouter-only (Qwen-VL, MiniMax), every
    # OpenRouter step is stripped at the top of this function, and these two
    # categories are also denied the local Ollama step -- so the chain
    # resolved to nothing and the request fell through to a blind local model
    # that answered anyway. Gemini is configured on this machine, reads
    # images, and is not stripped, which makes it the only route here that
    # can actually look at the thing it is being asked about.
    # Built here rather than through resolve_model_id('gemini'), which returns
    # None on purpose: this installation reaches Google accounts through the
    # Antigravity CLI. That is right for text and wrong for images, because a
    # CLI provider takes a rendered prompt string, so image content blocks
    # would be flattened into it and silently dropped -- the model would
    # receive the question with no picture and answer it anyway. The direct
    # Gemini API is the only configured route that carries image parts intact.
    if category in ('vision_multimodal', 'design_review') and config.gemini_api_key():
        trace.append(
            f"Image-capable route: {config.GEMINI_MODEL} over the Gemini API, which "
            "receives the attached image itself rather than a description of it."
        )
        return RoutingResult(category, "gemini", config.GEMINI_MODEL, f"Gemini ({config.GEMINI_MODEL})", trace)

    if category in _ALLOW_GEMINI_INTERIM and category not in ('vision_multimodal', 'design_review'):
        fallback = await resolve_model_id('antigravity_cli', category, trace)
        if fallback is not None and not await costs.tracker.is_over_budget():
            trace.append('Text-model chain exhausted; using authenticated Antigravity in plan mode.')
            return fallback

    trace.append(
        "No provider available for this category in Phase 1. "
        "This category requires Claude CLI / Codex CLI / a diffusion service, "
        "which need the home machine's local hardware and CLI logins."
    )
    return RoutingResult(category, "unavailable", None, "Unavailable", trace)


MAX_CHAIN_CANDIDATES = 4


# The faster model from the same account, for quick questions (see
# resolve_chain). Keyed by (provider, tier).
FAST_SIBLINGS = {("claude_cli", "opus"): "claude_cli:sonnet", ("claude_cli", "fable"): "claude_cli:sonnet"}


def _tier(model: str | None) -> str:
    name = (model or "").lower()
    return next((t for t in ("opus", "fable", "sonnet", "haiku") if t in name), name)


async def resolve_chain(
    category: str,
    prefer_local: bool = False,
    first: RoutingResult | None = None,
    limit: int = MAX_CHAIN_CANDIDATES,
) -> list[RoutingResult]:
    """Every provider worth trying for this category, best first.

    resolve() answers "what should I use"; the agent loop needs "and what
    after that, if this one is down." Built by walking resolve() with a
    growing exclude set rather than duplicating the chain logic, so an
    override, a budget block, or a Prefer-local reorder applies identically
    to every position in the list.

    `first` pins a caller-chosen result (an explicit model override, a
    detected handoff, a skill preference) at the head; the automatic chain
    still follows it, which is what makes an override recoverable rather than
    a single point of failure.
    """
    candidates: list[RoutingResult] = []
    excluded: set[str] = set()
    if first is not None and first.provider != "unavailable":
        candidates.append(first)
        if first.model:
            excluded.add(first.model)

    seen = {(c.provider, c.model) for c in candidates}
    while len(candidates) < max(1, limit):
        try:
            nxt = await resolve(category, exclude_models=set(excluded), prefer_local=prefer_local)
        except Exception:  # noqa: BLE001 - a chain that can't extend is still usable as-is
            break
        if nxt.provider == "unavailable" or (nxt.provider, nxt.model) in seen:
            break
        candidates.append(nxt)
        seen.add((nxt.provider, nxt.model))
        if nxt.model:
            excluded.add(nxt.model)
        else:
            # A CLI step resolves with no model id, so exclude_models can't
            # move past it. Stop walking and let the local tail below supply
            # the remaining fallback.
            break

    if not candidates:
        candidates.append(await resolve(category, prefer_local=prefer_local))

    # Local tail: whatever else happened above, end on something that needs no
    # network, no account, and no budget. This is what lets the agent loop
    # promise an answer rather than an outage message.
    if not any(c.provider == "ollama" for c in candidates):
        try:
            local = await providers.get_local_ollama_models()
            disabled = await db.list_disabled_models()
            local = [m for m in local if m.id not in disabled]
        except Exception:  # noqa: BLE001 - no Ollama is a valid state, not an error
            local = []
        if local:
            preferred = next((m for m in local if "qwen3.5:4b" in m.id), local[0])
            candidates.append(
                RoutingResult(category, "ollama", preferred.id,
                              f"{preferred.id} (local)",
                              ["Local model appended as the chain's last resort."])
            )
    return candidates


# Homework's own category (see HOMEWORK_CATEGORY above): its custom model
# (Token Harbor) is tried first; if that is missing or fails, the
# math-reasoning chain is next. None of those steps can actually drive Onyx
# through a multi-step Canvas task -- found live: Token Harbor's DeepSeek
# called browser_act 24 times with zero narration and gave up (see
# agent_loop.py's ProviderNoProgressError, which is what now makes that
# count as a failure and reach this fallback instead of just stopping).
# Claude Code CLI is the one thing that does drive Onyx reliably (see
# providers.stream_claude_cli's Onyx MCP wiring), so it closes out the
# chain: tried only once the cheaper homework model has already failed, not
# in place of it.
CATEGORY_CHAINS.setdefault(HOMEWORK_CATEGORY, list(CATEGORY_CHAINS["reasoning_math"]))
CATEGORY_CHAINS[HOMEWORK_CATEGORY].append(ChainStep("claude_cli", "Claude Code CLI"))
