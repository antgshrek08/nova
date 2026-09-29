"""Environment / API key management.

Phase 1 only needs GEMINI_API_KEY and OPENROUTER_API_KEY. The settings screen
in the frontend reads/writes these through the /settings endpoints in
main.py, which call back into update_keys() below so a running server picks
up new keys without a restart.

Keys live in ~/.ai-council/.env, not backend/.env -- packaged installs put
the backend under Program Files, which a standard user can't write to, so
the settings-save flow needs a location that's always writable regardless of
install location (same externalization already used for DB_PATH/CHROMA_DIR/
etc.). A one-time migration copies over an existing backend/.env from the
source-checkout dev workflow, if present, so switching over doesn't lose
keys someone already entered.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from dotenv import load_dotenv, set_key

BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEV_ENV_PATH = BACKEND_DIR / ".env"

USER_DATA_DIR = Path.home() / ".ai-council"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
ENV_PATH = USER_DATA_DIR / ".env"

if not ENV_PATH.exists():
    if _DEV_ENV_PATH.exists():
        shutil.copy(_DEV_ENV_PATH, ENV_PATH)
    else:
        ENV_PATH.touch()

load_dotenv(ENV_PATH)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
# Phase 4 (RESEARCH.md, 2026-09-03): screen-control coordinate grounding.
# bytedance/ui-tars-1.5-7b on OpenRouter -- a model purpose-trained for
# screenshot-to-coordinate GUI grounding, separate from whatever model is
# actually running the chat conversation. NOT free (confirmed live against
# OpenRouter's /api/v1/models -- a free 72b listing this was originally
# researched against no longer exists there), but cheap: $0.10/M input +
# $0.20/M output tokens -- real spend, tracked via costs.tracker like every
# other paid call. See providers.resolve_screen_target.
DESKTOP_GROUNDING_MODEL = os.getenv("DESKTOP_GROUNDING_MODEL", "bytedance/ui-tars-1.5-7b")
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_FREE_CACHE_TTL_SECONDS = int(os.getenv("OPENROUTER_FREE_CACHE_TTL_SECONDS", "3600"))
# Real bug found live: stream_openrouter had no timeout at all -- a free
# model's upstream connection can be accepted (the request routes fine,
# shows up in the trace) and then just never send another chunk, and the
# whole /chat request hangs forever with no recovery. This is a per-chunk
# IDLE timeout (reset on every chunk received), not a cap on total response
# time, so a long-but-actively-streaming reply is never punished -- only a
# stream that's gone genuinely silent is.
OPENROUTER_STREAM_IDLE_TIMEOUT_SECONDS = float(os.getenv("OPENROUTER_STREAM_IDLE_TIMEOUT_SECONDS", "30"))

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# Keep a stalled local generation from leaving the chat spinner forever. The
# timeout is an idle limit between chunks, so a model that is actively
# streaming can continue beyond it.
OLLAMA_FIRST_TOKEN_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_FIRST_TOKEN_TIMEOUT_SECONDS", "30"))
# Vision gets its own, longer budget. An image is worth on the order of a
# thousand prompt tokens and this machine prefills at roughly 217 tok/s, so a
# screenshot can spend most of a minute before the first token appears --
# under the 30s text timeout that reads as a dead model and reroutes to the
# cloud, which is the opposite of what a local-first vision path is for.
OLLAMA_VISION_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_VISION_TIMEOUT_SECONDS", "180"))
OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS", "20"))

# Claude Code CLI / Codex CLI subprocess wrappers (see providers.py). Both are
# expected to already be installed and logged in with the user's existing
# subscriptions per the build spec's "before you start" section.
CLAUDE_CLI_PATH = os.getenv("CLAUDE_CLI_PATH", "claude")
CODEX_CLI_PATH = os.getenv("CODEX_CLI_PATH", "codex")
CLI_TIMEOUT_SECONDS = int(os.getenv("CLI_TIMEOUT_SECONDS", "120"))

# Explicit model target for the "coding" category's CLI dispatch. Without
# this, `claude -p`/`codex exec` silently answer with whatever each CLI's own
# bare default currently resolves to for this login (see
# providers.stream_claude_cli/stream_codex_cli) -- on this account that's
# Sonnet 5, not a deliberate choice, just whatever the CLI happens to default
# to. "coding" gets no free-first attempt in the spec precisely because it's
# meant to hit the strongest available model, so the default here is Opus,
# not the CLI's own default. Accepts anything the CLI's own --model flag
# does: an alias ("opus", "sonnet") or a full model name. Empty string
# reverts to the old "let the CLI pick" behavior. No equivalent "intended
# model" was specified for Codex, so CODEX_CLI_MODEL defaults empty --
# unchanged from before, just now overridable the same way.
CLAUDE_CLI_MODEL = os.getenv("CLAUDE_CLI_MODEL", "opus")
CODEX_CLI_MODEL = os.getenv("CODEX_CLI_MODEL", "")

# Isolated cwd for claude -p / codex exec subprocess calls, kept outside this
# repo so any file tools those CLIs invoke while answering a chat message
# can't touch the AI Council project itself. This is the DEFAULT project --
# a real, always-available sandbox that exists before the user ever opens a
# project of their own -- not the only one anymore. See get_workspace_dir/
# set_workspace_dir below (Code tab milestone: "Opening an existing project
# through the native folder picker" -- the file tree, editor, AND the coding
# CLIs all need to agree on the same current project, or "review what N.O.V.A.
# changed" would silently be reviewing the wrong folder).
CLI_WORKSPACE_DIR = Path.home() / ".ai-council" / "cli-workspace"
CLI_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

_workspace_dir_override: Path | None = None


def get_workspace_dir() -> Path:
    """The current project root -- CLI_WORKSPACE_DIR (the built-in default
    sandbox) until the user explicitly opens a different real folder via the
    native picker. Read fresh on every call (not cached at import time) so a
    project switch takes effect immediately for the file tree, the editor,
    AND the next CLI invocation, without a backend restart."""
    return _workspace_dir_override or CLI_WORKSPACE_DIR


def set_workspace_dir(path: Path) -> None:
    global _workspace_dir_override
    _workspace_dir_override = path


def reset_workspace_dir() -> None:
    """Back to the built-in default sandbox."""
    global _workspace_dir_override
    _workspace_dir_override = None

# Phase 2: SQLite persistence for conversations/messages/projects/spend, kept
# outside the repo alongside the CLI workspace rather than inside backend/
# (so it survives a `git clean`, matches the CLI workspace's precedent).
DB_PATH = Path(os.getenv("DB_PATH", str(Path.home() / ".ai-council" / "ai_council.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Cost control per spec: hard daily budget ceiling on paid providers.
DAILY_BUDGET_USD = float(os.getenv("DAILY_BUDGET_USD", "1.0"))

# Claude/Codex CLI usage isn't observable per-call (subprocess text output,
# no litellm/API usage object) since they're flat-rate subscriptions, not
# metered APIs. This is a configurable heuristic cost assigned per CLI call
# purely so repeated escalations to that "paid" tier still count against the
# daily budget cap -- not a real billed price.
CLI_CALL_COST_ESTIMATE_USD = float(os.getenv("CLI_CALL_COST_ESTIMATE_USD", "0.05"))

# Agentic task step cap before requiring a check-in (spec: "start at 5").
AGENTIC_STEP_CAP = int(os.getenv("AGENTIC_STEP_CAP", "5"))

# Phase 3: Chroma vector store for semantic recall across conversations.
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", str(Path.home() / ".ai-council" / "chroma")))
CHROMA_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_RECALL_TOP_K = int(os.getenv("MEMORY_RECALL_TOP_K", "3"))
# Chroma's default embedder returns L2 distance, not similarity -- lower is
# closer. Hits farther than this are dropped rather than injected as noise
# into an otherwise-unrelated new conversation.
MEMORY_RECALL_MAX_DISTANCE = float(os.getenv("MEMORY_RECALL_MAX_DISTANCE", "1.6"))

# Phase 3: a real Obsidian vault on disk. Our own writes go straight to the
# filesystem (works whether or not Obsidian is even running); the Local REST
# API plugin is used specifically to read/update notes through the live app
# so a note the user hand-edited in Obsidian isn't clobbered -- see
# obsidian.py. The plugin has to be installed/enabled and its API key copied
# here by hand (there's no non-interactive way to do that part -- same
# category of one-time manual step as the Claude/Codex CLI logins).
OBSIDIAN_VAULT_DIR = Path(
    os.getenv("OBSIDIAN_VAULT_DIR", str(Path.home() / ".ai-council" / "obsidian-vault"))
)
OBSIDIAN_VAULT_DIR.mkdir(parents=True, exist_ok=True)
(OBSIDIAN_VAULT_DIR / "Projects").mkdir(parents=True, exist_ok=True)

OBSIDIAN_API_BASE_URL = os.getenv("OBSIDIAN_API_BASE_URL", "https://127.0.0.1:27124")
OBSIDIAN_API_KEY = os.getenv("OBSIDIAN_API_KEY") or None

# Phase: OpenClaw Gateway bridge ("Send to Claw" manual action, see
# openclaw.py). The Gateway itself is configured at ~/.openclaw/openclaw.json
# (its own file, not ours). OPENCLAW_GATEWAY_URL + the token are used for a
# lightweight reachability/auth check; the actual task dispatch goes through
# the openclaw CLI (see openclaw.py's module docstring for why -- this
# Gateway's POST /v1/chat/completions is disabled by default and enabling it
# is a config change outside this app's remit). Token is read fresh from the
# env on every use (never hardcoded) so a token rotated in the Gateway's own
# config can be updated here without a code change.
OPENCLAW_GATEWAY_URL = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
OPENCLAW_CLI_PATH = os.getenv("OPENCLAW_CLI_PATH", "openclaw")
OPENCLAW_AGENT_ID = os.getenv("OPENCLAW_AGENT_ID", "main")
# 600s (not the previous 240s) to match `openclaw agent`'s own CLI-side
# default timeout (`openclaw agent --help`: "default 600 or config value") --
# the old 240s was a tighter ceiling than the CLI's own, which is almost
# certainly why a genuinely slow run (a slow local model on OpenClaw's end,
# e.g. the qwen3:32b case) looked like a bridge failure: we were giving up
# before the CLI itself would have. Safe to widen now that send_task() polls
# OpenClaw's real task ledger during the wait (see _poll_status below) so a
# long run is a visibly "still working" Workspace node, not a silent hang.
OPENCLAW_TIMEOUT_SECONDS = int(os.getenv("OPENCLAW_TIMEOUT_SECONDS", "600"))
# Status-polling cadence during send_task()'s wait: tasks.list/tasks.get
# calls against OpenClaw's task ledger (see openclaw.py's _poll_status) are
# metadata-only, no model call, so no cost implication -- but still backed
# off so a long run doesn't hammer the Gateway with a query every few
# seconds for ten minutes straight.
OPENCLAW_POLL_INITIAL_SECONDS = float(os.getenv("OPENCLAW_POLL_INITIAL_SECONDS", "4"))
OPENCLAW_POLL_MAX_INTERVAL_SECONDS = float(os.getenv("OPENCLAW_POLL_MAX_INTERVAL_SECONDS", "20"))
# Timeout for a single tasks.list/tasks.get status probe -- short and
# separate from OPENCLAW_TIMEOUT_SECONDS (the real task's own ceiling): a
# hung status probe should never be able to stall or extend the real wait,
# it should just skip that one update.
OPENCLAW_STATUS_CALL_TIMEOUT_SECONDS = float(os.getenv("OPENCLAW_STATUS_CALL_TIMEOUT_SECONDS", "8"))

# Remote MCP servers (HTTP/SSE + OAuth, see mcp_oauth.py). This has to be
# reachable from whatever browser tab the user completes sign-in in -- for
# a real deployment (Tailscale, a hosted instance) this would need to be
# the actual externally-reachable origin, not localhost. Loopback-only for
# now since this app itself only runs locally.
MCP_OAUTH_CALLBACK_BASE_URL = os.getenv("MCP_OAUTH_CALLBACK_BASE_URL", "http://127.0.0.1:8000")

# Wake-word (see app/wakeword.py). "hey_jarvis" is a TEMPORARY placeholder
# for the real "Hey Nova" phrase -- openWakeWord's stock pretrained models
# don't include it, and training a real custom one needs their
# synthetic-data pipeline (too large for this session). Swap this env var
# to a real "hey_nova" model name (and drop the trained .onnx file where
# openwakeword.utils.download_models would otherwise fetch it from) once
# that model exists -- nothing else in the pipeline needs to change.
WAKEWORD_MODEL_NAME = os.getenv("WAKEWORD_MODEL_NAME", "hey_jarvis")


def openclaw_gateway_token() -> str | None:
    return os.getenv("OPENCLAW_GATEWAY_TOKEN", "").strip() or None

# Phase: real voice. TTS runs fully locally via Chatterbox (Resemble AI,
# MIT-licensed) -- no API key, no external service. "cpu" is the correct
# default on this machine (an AMD GPU with no CUDA support); override via
# .env on a machine with a real CUDA GPU for much faster inference.
CHATTERBOX_DEVICE = os.getenv("CHATTERBOX_DEVICE", "cpu")

# Integration-plan Phase 1b (RESEARCH.md, 2026-09-03): resemble-ai shipped an
# official smaller/faster Turbo variant (ChatterboxTurboTTS, a 350M-param,
# 1-step diffusion decoder vs. the base model's 0.5B/10-step one) as a
# genuinely separate class in the same `chatterbox-tts` pip package -- not a
# config flag on the base model, and not something that requires running any
# third-party server (devnen/Chatterbox-TTS-Server just wraps this same
# official class). Behind a flag, defaulted off, because:
#  - it needs `chatterbox-tts` new enough to include `chatterbox.tts_turbo`
#    (confirmed present on resemble-ai's GitHub master; NOT confirmed against
#    the exact 0.1.7 pinned in requirements.txt -- tts.py handles a missing
#    module by raising a clear "upgrade chatterbox-tts" error rather than
#    crashing the whole TTS path)
#  - voice cloning (audio_prompt_path) and .generate()/.sr's exact behavior
#    on ChatterboxTurboTTS haven't been verified live yet, only assumed
#    compatible from resemble-ai's own "hot-swappable" framing.
CHATTERBOX_TURBO = os.getenv("CHATTERBOX_TURBO", "false").strip().lower() in ("1", "true", "yes")
# Turbo's own further-distilled "nano" variant -- even smaller/faster, at
# some further quality cost. Off by default; worth trying if Turbo alone
# still isn't fast enough on CPU.
CHATTERBOX_TURBO_NANO = os.getenv("CHATTERBOX_TURBO_NANO", "false").strip().lower() in ("1", "true", "yes")

# Task 9: real image generation. Same CPU-only reality as CHATTERBOX_DEVICE
# above (no CUDA GPU on this machine) -- SD-Turbo is a real, published,
# diffusers-native model distilled for 1-4 step inference, genuinely fast
# enough on CPU for a chat turnaround. FLUX.1-dev/Qwen-Image (the models
# this app's routing.py names as the eventual target) are 12-20B+ param
# models that would take many minutes per image on CPU -- swap
# IMAGE_GEN_MODEL_ID below once this runs on real CUDA hardware.
IMAGE_GEN_DEVICE = os.getenv("IMAGE_GEN_DEVICE", "cpu")
IMAGE_GEN_MODEL_ID = os.getenv("IMAGE_GEN_MODEL_ID", "stabilityai/sd-turbo")

# Reference audio clips for cloned TTS voices (Settings > Voice), one WAV per
# voice, named by db id. Chatterbox's audio_prompt_path needs a real file on
# disk, so clones are written here once at upload time rather than round-
# tripped through a DB blob on every synthesis call.
VOICES_DIR = Path.home() / ".ai-council" / "voices"
VOICES_DIR.mkdir(parents=True, exist_ok=True)


def gemini_api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY", "").strip() or None


def openrouter_api_key() -> str | None:
    return os.getenv("OPENROUTER_API_KEY", "").strip() or None


def key_status() -> dict:
    return {
        "gemini_configured": gemini_api_key() is not None,
        "openrouter_configured": openrouter_api_key() is not None,
    }


def update_keys(gemini_api_key_value: str | None = None, openrouter_api_key_value: str | None = None) -> dict:
    """Persist new keys to backend/.env and to the current process env."""
    if gemini_api_key_value and gemini_api_key_value.strip():
        set_key(str(ENV_PATH), "GEMINI_API_KEY", gemini_api_key_value.strip())
        os.environ["GEMINI_API_KEY"] = gemini_api_key_value.strip()
    if openrouter_api_key_value and openrouter_api_key_value.strip():
        set_key(str(ENV_PATH), "OPENROUTER_API_KEY", openrouter_api_key_value.strip())
        os.environ["OPENROUTER_API_KEY"] = openrouter_api_key_value.strip()
    return key_status()


def read_env_value(name: str) -> str | None:
    """One value from the shared .env, preferring the live process copy so a
    value written this run is visible without a reload."""
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def write_env_value(name: str, value: str) -> str:
    """Persist one value to the shared .env and this process's environment.

    Same file every other credential lives in, so it is inherited by the
    installed app and never travels with a build."""
    set_key(str(ENV_PATH), name, value)
    os.environ[name] = value
    return value
