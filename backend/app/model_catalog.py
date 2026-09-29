"""Every way to give Nova a model, with its real status on this computer.

Backs the Models step of onboarding and Settings > Models' guide, so a user
who has never touched an API key can see what each option is, what it costs,
exactly how to set it up, and whether it's already working here. Status is
checked live -- a program on PATH, a local server answering, a key saved, a
model added -- never assumed.
"""
from __future__ import annotations

import asyncio
import shutil

import httpx

from . import config, db

# id, name, group, cost, what it's like, how to set it up, link, kind, extra
# kind: "local" (install a program), "app" (sign in to a program), "key"
# (paste an API key). api_base for key providers Nova adds models from.
CATALOG = [
    {"id": "ollama", "name": "Ollama", "group": "local", "cost": "Free",
     "about": "Runs open models on this computer. Private, works offline. Needs a decent computer; small models run on most.",
     "steps": ["Download Ollama and install it.", "Come back here and press Download a starter model.", "Nova finds every Ollama model on its own."],
     "link": "https://ollama.com/download", "kind": "local"},
    {"id": "lmstudio", "name": "LM Studio", "group": "local", "cost": "Free",
     "about": "An app for downloading and running open models, with a simple window.",
     "steps": ["Install LM Studio and download a model inside it.", "In LM Studio, open Developer and start the local server.", "Press Check again; Nova adds its models."],
     "link": "https://lmstudio.ai", "kind": "local", "api_base": "http://localhost:1234/v1"},
    {"id": "claude_cli", "name": "Claude Code", "group": "app", "cost": "Uses your Claude subscription",
     "about": "Anthropic's Claude, through the app you sign in to. Strong at coding and careful reasoning.",
     "steps": ["Install Node.js from nodejs.org if you don't have it.", "In a terminal run: npm install -g @anthropic-ai/claude-code", "Run claude once and sign in with your Claude account."],
     "link": "https://docs.anthropic.com/en/docs/claude-code", "kind": "app", "command": "npm install -g @anthropic-ai/claude-code"},
    {"id": "codex_cli", "name": "Codex", "group": "app", "cost": "Uses your ChatGPT subscription",
     "about": "OpenAI's coding agent, through the app you sign in to with ChatGPT.",
     "steps": ["Install Node.js from nodejs.org if you don't have it.", "In a terminal run: npm install -g @openai/codex", "Run codex once and sign in with ChatGPT."],
     "link": "https://github.com/openai/codex", "kind": "app", "command": "npm install -g @openai/codex"},
    {"id": "gemini_cli", "name": "Gemini CLI", "group": "app", "cost": "Free with a Google account (limits apply)",
     "about": "Google's Gemini, through the command-line app you sign in to.",
     "steps": ["Install Node.js from nodejs.org if you don't have it.", "In a terminal run: npm install -g @google/gemini-cli", "Run gemini once and sign in with Google."],
     "link": "https://github.com/google-gemini/gemini-cli", "kind": "app", "command": "npm install -g @google/gemini-cli"},
    {"id": "antigravity_cli", "name": "Antigravity", "group": "app", "cost": "Uses your Google account",
     "about": "Google's agent app, used by Nova for planning.",
     "steps": ["Install Antigravity from Google.", "Open it once and sign in.", "Press Check again."],
     "link": "https://antigravity.google", "kind": "app"},
    {"id": "openrouter", "name": "OpenRouter", "group": "free", "cost": "Free models available",
     "about": "One key for hundreds of models, many free. The easiest way to start.",
     "steps": ["Make a free account at openrouter.ai.", "Open Keys and create a key.", "Paste it here."],
     "link": "https://openrouter.ai/keys", "kind": "key", "setting": "openrouter"},
    {"id": "gemini", "name": "Google Gemini", "group": "free", "cost": "Free tier",
     "about": "Google's models with a generous free tier. Good all-rounder, reads images.",
     "steps": ["Go to Google AI Studio and sign in with Google.", "Press Get API key, then Create API key.", "Paste it here."],
     "link": "https://aistudio.google.com/apikey", "kind": "key", "setting": "gemini"},
    {"id": "groq", "name": "Groq", "group": "free", "cost": "Free tier",
     "about": "Very fast open models (Llama and others). Great for quick answers.",
     "steps": ["Make a free account at console.groq.com.", "Open API Keys and create one.", "Paste it here and pick models."],
     "link": "https://console.groq.com/keys", "kind": "key", "api_base": "https://api.groq.com/openai/v1"},
    {"id": "cerebras", "name": "Cerebras", "group": "free", "cost": "Free tier",
     "about": "Extremely fast open models.",
     "steps": ["Make a free account at cloud.cerebras.ai.", "Create an API key.", "Paste it here and pick models."],
     "link": "https://cloud.cerebras.ai", "kind": "key", "api_base": "https://api.cerebras.ai/v1"},
    {"id": "mistral", "name": "Mistral", "group": "free", "cost": "Free tier",
     "about": "Mistral's own models, strong in European languages.",
     "steps": ["Make an account at console.mistral.ai.", "Open API Keys and create one (the free Experiment plan works).", "Paste it here and pick models."],
     "link": "https://console.mistral.ai/api-keys", "kind": "key", "api_base": "https://api.mistral.ai/v1"},
    {"id": "github", "name": "GitHub Models", "group": "free", "cost": "Free with a GitHub account (limits apply)",
     "about": "Try GPT, Llama, Mistral and more with your GitHub account.",
     "steps": ["Sign in at github.com.", "Settings, Developer settings, Personal access tokens: create a token with the models permission.", "Paste it here and pick models."],
     "link": "https://github.com/settings/personal-access-tokens", "kind": "key", "api_base": "https://models.github.ai/inference"},
    {"id": "huggingface", "name": "Hugging Face", "group": "free", "cost": "Free credits monthly",
     "about": "Thousands of open models through one key.",
     "steps": ["Make an account at huggingface.co.", "Settings, Access Tokens: create a token.", "Paste it here and pick models."],
     "link": "https://huggingface.co/settings/tokens", "kind": "key", "api_base": "https://router.huggingface.co/v1"},
    {"id": "openai", "name": "OpenAI", "group": "paid", "cost": "Paid, per use",
     "about": "GPT models. You pay OpenAI for what you use; set a daily limit in Settings, General.",
     "steps": ["Sign in at platform.openai.com and add a payment method.", "API keys: create a key.", "Paste it here and pick models."],
     "link": "https://platform.openai.com/api-keys", "kind": "key", "api_base": "https://api.openai.com/v1"},
    {"id": "anthropic", "name": "Anthropic", "group": "paid", "cost": "Paid, per use",
     "about": "Claude models by API key, if you'd rather not use the Claude Code app.",
     "steps": ["Sign in at console.anthropic.com and add credit.", "API Keys: create a key.", "Paste it here and pick models."],
     "link": "https://console.anthropic.com/settings/keys", "kind": "key", "api_base": "https://api.anthropic.com/v1"},
    {"id": "deepseek", "name": "DeepSeek", "group": "paid", "cost": "Paid, low cost",
     "about": "Strong reasoning and coding models at a low price.",
     "steps": ["Sign in at platform.deepseek.com and add credit.", "API keys: create one.", "Paste it here and pick models."],
     "link": "https://platform.deepseek.com/api_keys", "kind": "key", "api_base": "https://api.deepseek.com/v1"},
    {"id": "xai", "name": "xAI (Grok)", "group": "paid", "cost": "Paid, per use",
     "about": "Grok models.",
     "steps": ["Sign in at console.x.ai.", "Create an API key.", "Paste it here and pick models."],
     "link": "https://console.x.ai", "kind": "key", "api_base": "https://api.x.ai/v1"},
]
GROUPS = {"local": "On this computer", "app": "Apps you sign in to", "free": "Free with an account", "paid": "Paid"}


async def _answers(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get(url)
        return r.status_code < 500
    except Exception:  # noqa: BLE001
        return False


async def status() -> dict:
    """The catalog with each option's live state on this computer."""
    from .main import _build_models  # the same model list the rest of Nova uses
    models = await _build_models()
    enabled = [m for m in models if m.get("enabled")]
    customs = await db.list_custom_models()
    keys = config.key_status()
    ollama_up, lmstudio_up = await asyncio.gather(_answers("http://127.0.0.1:11434/api/tags"), _answers("http://127.0.0.1:1234/v1/models"))
    out = []
    for item in CATALOG:
        s = {**item}
        count = 0
        if item["id"] == "ollama":
            count = sum(1 for m in enabled if m["provider"] == "ollama")
            installed = bool(shutil.which("ollama")) or ollama_up
            s["state"] = "ready" if count else ("running" if ollama_up else ("installed" if installed else "not_installed"))
        elif item["id"] == "lmstudio":
            count = sum(1 for c in customs if (c.get("api_base") or "").startswith("http://localhost:1234"))
            s["state"] = "ready" if count else ("running" if lmstudio_up else "not_installed")
        elif item["kind"] == "app":
            row = next((m for m in models if m["id"] == item["id"]), None)
            present = bool(row and row.get("enabled"))
            s["state"] = "ready" if present else "not_installed"
            count = int(present)
            if row and row.get("availability_reason"):
                s["note"] = row["availability_reason"]
        elif item.get("setting") == "openrouter":
            ok = bool(keys.get("openrouter_configured"))
            count = sum(1 for m in enabled if m["provider"] == "openrouter") if ok else 0
            s["state"] = "ready" if ok else "needs_key"
        elif item.get("setting") == "gemini":
            ok = bool(keys.get("gemini_configured"))
            s["state"] = "ready" if ok else "needs_key"
            count = int(ok)
        else:
            base = item.get("api_base", "")
            mine = [c for c in customs if (c.get("api_base") or "").rstrip("/") == base.rstrip("/")]
            count = sum(1 for c in mine if c.get("enabled"))
            s["state"] = "ready" if count else "needs_key"
        s["count"] = count
        out.append(s)
    return {"providers": out, "groups": GROUPS, "ready_models": len(enabled)}
