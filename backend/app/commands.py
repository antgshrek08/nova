"""Slash commands for chat.

Deliberately prompt expansion rather than a second execution path. A command
rewrites the user's message into a fuller instruction and may set a flag, then
the normal agent loop runs it with the normal tools and skills. That keeps one
code path to reason about: anything a command can do, a plainly-worded message
can also do, and a command that stops working is a prompt problem rather than a
broken subsystem.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Command:
    name: str
    usage: str
    summary: str
    expand: callable          # (argument: str) -> str
    homework: bool = False    # force Homework Mode for this turn


def _homework(argument: str) -> str:
    if argument:
        return (
            f"Find the Canvas assignment matching '{argument}' using the canvas_assignments tool, "
            "then show me: its title, course, exact due date, how much it is worth, and what it "
            "actually asks for. If the description is thin, open its URL with browser_act and read "
            "the real page. Do not start solving it yet."
        )
    return (
        "Use the canvas_assignments tool to get everything due in the next 14 days, then give me a "
        "working brief:\n"
        "- What is due in the next 48 hours, with exact dates and what each is worth.\n"
        "- What needs to be *started* now even though it is not due yet, and why.\n"
        "- Whether any week ahead is overloaded, with rough hour estimates.\n"
        "- One concrete next action I can do today.\n"
        "If Canvas has nothing, say so plainly rather than inventing assignments."
    )


def _solve(argument: str) -> str:
    target = (
        f"the Canvas assignment matching '{argument}'"
        if argument else "the assignment due soonest, per the canvas_assignments tool"
    )
    return (
        f"Work {target}.\n\n"
        "1. Find it with canvas_assignments. Read the full description; if it is thin or truncated, "
        "open its URL with browser_act and read the real page before starting.\n"
        "2. If the assignment references a file, reading, or dataset I have locally, find and read it.\n"
        "3. Answer it completely, showing the working.\n"
        "4. End with the concepts section.\n"
        "State clearly which questions you answered and which, if any, you could not because the "
        "material was unavailable. Do not guess at a question you could not read."
    )


def _explain(argument: str) -> str:
    return (
        f"Explain {argument or 'the concept I just asked about'} at three levels: an intuition with "
        "a concrete analogy (and where the analogy breaks), the course-level explanation with a "
        "worked example, and the edge cases people get wrong. End with one check question."
    )


def _brief(argument: str) -> str:
    return (
        "Give me a short status brief: what is due soon from Canvas, anything that changed, and "
        "what is worth doing next. Use your tools rather than asking me. Keep it under 200 words."
    )


def _slop(argument: str) -> str:
    return (
        "Audit the draft below for AI-slop patterns. Name each pattern you find, quote the line, and "
        "give the fix in a few words. Do not rewrite it and do not score it.\n\n"
        + (argument or "(I will paste the draft next — ask me for it.)")
    )


REGISTRY: dict[str, Command] = {
    c.name: c
    for c in [
        Command("homework", "/homework [assignment]",
                "What's due, or the details of one assignment", _homework),
        Command("solve", "/solve [assignment]",
                "Work an assignment end to end, with the concept summary", _solve, homework=True),
        Command("explain", "/explain <concept>",
                "Three-level explanation: intuition, course level, edge cases", _explain),
        Command("brief", "/brief", "Short status brief on school and anything pending", _brief),
        Command("slop", "/slop [draft]", "Flag AI-slop patterns without rewriting", _slop),
    ]
}

_COMMAND_RE = re.compile(r"^\s*/([a-z][a-z0-9-]*)\b[ \t]*(.*)$", re.IGNORECASE | re.DOTALL)


def direct(message: str) -> str | None:
    """The answer for commands that need no model at all.

    /help asked a model to recite a list, and the model refused -- correctly,
    given it is also told not to claim capabilities it cannot verify. Listing
    what exists is a fact this process already holds, so it answers from here:
    always accurate, instant, and it cannot be argued with by a model having a
    cautious day. Same for a typo'd command, which is not worth a model call.
    """
    match = _COMMAND_RE.match(message or "")
    if not match:
        return None
    name = match.group(1).lower()

    if name in ("help", "commands"):
        lines = ["Commands:"]
        lines += [f"  {c.usage} — {c.summary}" for c in REGISTRY.values()]
        lines.append("  /help — this list")
        lines.append("\nEverything here also works phrased normally; the commands are shorthand.")
        return "\n".join(lines)

    if name not in REGISTRY:
        known = ", ".join(f"/{n}" for n in REGISTRY)
        return f"`/{name}` isn't a command. Available: {known}, /help."
    return None


def expand(message: str) -> tuple[str, dict] | None:
    """(expanded prompt, flags) for a slash command that runs through the model,
    or None for an ordinary message or a command `direct` already answered."""
    match = _COMMAND_RE.match(message or "")
    if not match:
        return None
    command = REGISTRY.get(match.group(1).lower())
    if command is None:
        return None
    return command.expand((match.group(2) or "").strip()), {"homework": command.homework}


def listing() -> list[dict]:
    return [{"name": c.name, "usage": c.usage, "summary": c.summary} for c in REGISTRY.values()]
