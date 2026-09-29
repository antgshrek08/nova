"""Ambient pet-awareness for the desktop-roaming character / miniplayer
(integration-plan Phase 2, RESEARCH.md 2026-09-03): translates agents.py's
AgentJob lifecycle (queued/working/done/error) into a small vocabulary the
existing character rig can actually express, and sanitizes any free-text
narration before it ever reaches a speech bubble -- borrowed from openpets'
openpets_say pattern (see RESEARCH.md's desktop-pet prior-art survey).

Deliberately pure/stateless where it matters: no websocket code lives here.
agents.py already owns a broadcast mechanism to every connected window (see
AgentRegistry._broadcast) -- this module only computes WHAT the pet should
be doing/saying, agents.py decides WHEN to send it. That keeps the
dependency one-directional (agents.py imports pet.py) instead of circular.

Scope for this pass: nova_pet_react/nova_pet_say/nova_pet_status are the
three functions the integration plan asked for, wired so AgentRegistry
calls them on every real job-status transition (see agents.py). They are
plain Python functions here, not their own MCP tools or HTTP endpoints --
the plan's ask was specifically "agents.py's AgentJob status transitions
call nova_pet_react directly," not a new external surface. Exposing these
as real MCP tools (so an external agent could narrate its own actions, the
way openpets' actual callers do) is a natural follow-up, not done here.
"""
from __future__ import annotations

import re
import time

# AgentJob.status -> the character's reaction vocabulary. Deliberately
# small -- matches what DesktopPet.jsx/Miniplayer.jsx can actually express
# today (a sustained "thinking" pose, a one-shot "success" bounce, a
# one-shot "error" shake, or plain "idle") rather than openpets' larger
# state set (editing/testing/etc), which would need new character art/
# animation this pass doesn't add.
_STATUS_TO_REACTION = {
    "queued": "thinking",
    "working": "thinking",
    "done": "success",
    "error": "error",
}


def react_state_for_status(status: str) -> str:
    return _STATUS_TO_REACTION.get(status, "idle")


# Friendly one-line blurbs for nova_pet_say, keyed by routing.py's category
# strings (see RESEARCH.md's routing notes for the current roster) -- real
# data already on every AgentJob (job.category), not invented per-job.
_CATEGORY_BLURBS = {
    "coding": "Coding…",
    "frontend_ui_code": "Building UI…",
    "reasoning_math": "Thinking hard…",
    "agentic_planning": "Planning…",
    "general_writing": "Writing…",
    "long_context": "Reading closely…",
    "quick_simple": "On it…",
    "action": "Taking action…",
}


def blurb_for_category(category: str | None) -> str:
    if category and category in _CATEGORY_BLURBS:
        return _CATEGORY_BLURBS[category]
    return "Working on something…"


# Speech-bubble sanitization (integration-plan Phase 2 step 4, borrowed
# from openpets' openpets_say): strips things that shouldn't land in a
# small on-screen bubble even if a future caller passes raw agent-generated
# text instead of one of the curated blurbs above -- code/backtick spans,
# URLs, and filesystem paths -- then hard-truncates. Applied unconditionally
# in nova_pet_say below, not just to the blurbs (which are already safe),
# specifically so a future free-text caller can't skip it.
_CODE_RE = re.compile(r"```[\s\S]*?```|`[^`]*`")
_URL_RE = re.compile(r"https?://\S+")
_PATH_RE = re.compile(r"(?:[A-Za-z]:)?[\\/](?:[\w.\-]+[\\/])+[\w.\-]+")
MAX_BUBBLE_CHARS = 80


def sanitize_for_bubble(text: str) -> str:
    text = _CODE_RE.sub("", text)
    text = _URL_RE.sub("[link]", text)
    text = _PATH_RE.sub("[path]", text)
    text = " ".join(text.split())  # collapse newlines/repeated whitespace
    if len(text) > MAX_BUBBLE_CHARS:
        text = text[: MAX_BUBBLE_CHARS - 1].rstrip() + "…"
    return text


_current: dict = {"state": "idle", "text": None, "updated_at": time.time()}


def nova_pet_react(state: str) -> dict:
    """Sets the character's current reaction state. Pure state update --
    agents.py is responsible for actually broadcasting the result to
    connected windows (see its _broadcast method)."""
    _current["state"] = state
    _current["updated_at"] = time.time()
    return dict(_current)


def nova_pet_say(text: str | None) -> dict:
    """Sets (or clears, if text is falsy) the current speech-bubble line,
    sanitized first -- see sanitize_for_bubble. This is the one path here
    that has to assume its input might be raw/untrusted free text (a future
    MCP-tool-driven caller), unlike the curated category blurbs above."""
    _current["text"] = sanitize_for_bubble(text) if text else None
    _current["updated_at"] = time.time()
    return dict(_current)


def nova_pet_status() -> dict:
    return dict(_current)
