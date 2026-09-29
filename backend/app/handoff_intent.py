"""Detects an explicit, in-chat request to hand THIS message to a specific
named model -- the fix for the known bug "multi-model handoff not triggering
from normal chat" (user says "hand this to Codex" and N.O.V.A. just talks
about doing it instead of actually routing there).

This is deliberately a *narrower* mechanism than /agents/chain (main.py's
user-directed multi-model chain, task 11): that endpoint runs a whole
sequence of steps the user configured explicitly in the Workspace tab's
chain-builder UI. This module instead answers one much smaller question --
"does this single chat message, in plain English, name one of N.O.V.A.'s
fixed CLI/API providers and ask for it by name?" -- and if so, main.py's
/chat routes THIS message directly to that provider instead of running the
category's automatic chain.

Scoped deliberately narrow to the three fixed, always-present providers a
user would actually type from memory: Claude Code CLI, Codex CLI, and
Gemini. NOT matched against the OpenRouter free-tier roster (Kimi, GLM,
DeepSeek, Qwen, ...) -- that roster rotates weekly and is fetched live, so
matching it here would mean silently guessing at a moving target instead of
a real fix. A user naming an OpenRouter model by hand can still reach it via
the existing per-message override_model_id (Chat's model picker).
"""
from __future__ import annotations

import re

# (name pattern, routing.resolve_model_id id, display label)
_HANDOFF_TARGETS: list[tuple[str, str, str]] = [
    (r"codex(?:\s*cli)?", "codex_cli", "Codex CLI"),
    (r"claude(?:\s*(?:cli|code))?", "claude_cli", "Claude Code CLI"),
    (r"gemini", "gemini", "Gemini"),
]


def _handoff_pattern(name_re: str) -> re.Pattern:
    """Matches a small set of verb constructions in either order: the verb
    before the name ("send this to Codex", "have Codex do this") or the
    target-seeking verb right on the name ("ask Codex to...", "get Codex's
    opinion"). Deliberately conservative -- requires an explicit handoff verb
    adjacent to the name, not just the name appearing anywhere in the
    message, so "I heard Claude is good at coding" or "how does Codex work"
    don't false-positive.
    """
    return re.compile(
        r"\b("
        rf"(?:hand|send|give|pass)\s+(?:this|it|that)(?:\s+(?:off|over|on))?\s+to\s+(?:the\s+)?{name_re}\b"
        rf"|have\s+(?:the\s+)?{name_re}\s+(?:do|handle|write|take|review|look\s+at|finish)\s+(?:this|it)\b"
        rf"|let\s+(?:the\s+)?{name_re}\s+(?:do|handle|take)\s+(?:this|it)\b"
        rf"|ask\s+(?:the\s+)?{name_re}\s+to\b"
        rf"|get\s+(?:the\s+)?{name_re}(?:'s)?\s+(?:opinion|take|review|thoughts|input)\b"
        r")",
        re.IGNORECASE,
    )


_COMPILED = [(_handoff_pattern(name_re), model_id, label) for name_re, model_id, label in _HANDOFF_TARGETS]


def detect_handoff_intent(message: str) -> tuple[str, str] | None:
    """Return (model_id, label) for routing.resolve_model_id if `message`
    explicitly asks to hand this message to a named provider, else None.
    Checked against the raw user message (same convention as
    classifier.classify and skills.select_relevant_skills), before any
    attachment text is folded in.
    """
    text = message.strip()
    if not text:
        return None
    for pattern, model_id, label in _COMPILED:
        if pattern.search(text):
            return model_id, label
    return None
