"""First version (task 13: "simple first version, not the final system") of
a local-Ollama-driven idle/ambient behavior generator for the mascot widget
(see Miniplayer.jsx). While the mascot is idle -- no active voice turn or
chat generation -- the frontend polls /idle/behavior every so often; this
asks a small, fast local Ollama model for one short in-character ambient
action and hands it back as flavor text shown briefly near the mascot. It's
purely cosmetic (never touches routing, chat history, or any real app
state) and fails silently to "unavailable" if no local Ollama model is
pulled, rather than erroring the widget.
"""
from __future__ import annotations

import random


from . import config, providers
from .local_inference import completion

# Smallest/fastest locally-pulled models preferred, in that order -- idle
# chatter should be cheap and frequent, not compete with a real chat
# request for Ollama's limited local compute. Falls back to whatever's
# actually pulled if none of these are present.
_PREFERRED_KEYWORDS = ["qwen2.5:0.5b", "tinyllama", "phi", "gemma"]

_PROMPT = (
    "You are the tiny internal voice of an idle AI assistant's animated "
    "avatar -- a warm, a little lively character at rest, not a flat or "
    "sleepy one. In 5 words or fewer, describe one small, in-character "
    "ambient action it might do right now while waiting (e.g. 'glances at "
    "the clock', 'hums a little tune', 'stretches and grins'). Reply with "
    "ONLY the action, no punctuation, no quotes, nothing else."
)


async def _pick_model() -> str | None:
    models = await providers.get_local_ollama_models()
    if not models:
        return None
    ids = [m.id for m in models]
    for keyword in _PREFERRED_KEYWORDS:
        for model_id in ids:
            if keyword in model_id.lower():
                return model_id
    return random.choice(ids)


async def generate_idle_action() -> dict:
    model_id = await _pick_model()
    if model_id is None:
        return {"available": False, "action": None, "model": None}
    try:
        response = await completion(
            model=f"ollama_chat/{model_id}",
            messages=[{"role": "user", "content": _PROMPT}],
            api_base=config.OLLAMA_BASE_URL,
        )
        text = (response.choices[0].message.content or "").strip().strip(".\"'")
        # A real local model can still ramble past the "5 words" ask --
        # cosmetic flavor text has no business being a paragraph.
        if len(text) > 60:
            text = text[:57] + "..."
        return {"available": True, "action": text or None, "model": model_id}
    except Exception:  # noqa: BLE001 -- idle flavor text must never break the widget
        return {"available": False, "action": None, "model": model_id}
