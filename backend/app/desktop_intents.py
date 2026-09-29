"""Desktop commands that do not need a model to understand them.

"Close Discord" took 63 seconds to run, measured end to end. Only about two
of those were classification and routing; roughly 47 were the local 4B model
prefilling a 13,000-token system prompt (see measure_context.py) before it
could emit a single tool call, and another 8 were it writing a sentence to
confirm what it had done.

None of that work was needed. "Close Discord" is not a request that benefits
from a language model: it names the verb and the target, there is exactly one
sensible action, and the confirmation sentence is the same every time. This
module recognises that shape and hands back a tool call directly, which is
the same thing _fast_path_answer already does for "what time is it".

Deliberately narrow. This matches imperative commands with an explicit verb
and nothing else going on -- no conjunctions, no questions, no conditions.
Anything with a hint of ambiguity falls through to the model, because the
cost of being wrong here is doing something to the user's real desktop that
they did not ask for, and 63 seconds is a far better outcome than that.

The autonomy gate is NOT reimplemented here. main.py only uses this path when
the tool would run without an approval prompt anyway; anything else goes the
normal route so the real approval flow stays the only approval flow.
"""
from __future__ import annotations

import re

# Words that mean the sentence is doing more than one thing, or is not an
# instruction at all. Their presence alone sends the message to the model.
_DISQUALIFIERS = re.compile(
    r"\b(and|then|after|before|if|when|unless|but|while|because|"
    r"how|why|what|which|who|should|could|would|can you|tell me|explain)\b"
    r"|[?]",
    re.IGNORECASE,
)

# Politeness and wake-word noise that carries no meaning for the command.
_PREFIX = re.compile(
    r"^(?:hey |ok |okay |yo |please |could you |can you |would you )*"
    r"(?:nova[,\s]+)?(?:please\s+)?",
    re.IGNORECASE,
)
_SUFFIX = re.compile(r"\s*(?:please|for me|right now|now)\s*$", re.IGNORECASE)

_CLOSE = re.compile(r"^(?:close|quit|exit|shut)\s+(?:down\s+)?(?:the\s+)?(.+?)(?:\s+(?:app|application|window))?$", re.IGNORECASE)
_OPEN = re.compile(r"^(?:open|launch|start|run)\s+(?:up\s+)?(?:the\s+)?(.+?)(?:\s+(?:app|application))?$", re.IGNORECASE)
_KILL = re.compile(r"^(?:kill|force[- ]?quit|force close)\s+(?:the\s+)?(.+?)(?:\s+(?:app|application|process))?$", re.IGNORECASE)

# Read-only desktop questions with one obvious answer.
_LIST_WINDOWS = {
    "list my windows", "list my open windows", "list open windows",
    "what windows are open", "what is open", "whats open", "what apps are open",
    "show my windows", "show open windows",
}

# "start localhost" and friends are already handled in main.py, and "open"
# here must not swallow them or the project's own commands.
_NOT_APPS = {
    "localhost", "the local server", "local server", "this website",
    "nova source", "your source code", "nova source code", "the website",
    "a new conversation", "settings", "preview", "canvas",
}

# Messages or targets referencing web browsing, browsers, websites or coursework
# must be handled by the model and agent loop (e.g. browser_act, onyx, coursework),
# NOT desktop open_app / close_window / kill_process.
_WEB_OR_COURSEWORK = re.compile(
    r"\b(in|on|with|using|through|to)\s+(onyx|edge|chrome|firefox|brave|browser|canvas)\b"
    r"|\b(canvas|assignment|homework|calculus|alta|knewton|problem|quiz|test|exam|course|coursework|math|module|grade)\b"
    r"|https?://|\b\w+\.(com|edu|org|net|gov|io)\b",
    re.IGNORECASE,
)


def _strip(message: str) -> str:
    text = (message or "").strip().replace("’", "'")
    text = _PREFIX.sub("", text, count=1)
    text = text.rstrip(" .!").strip()
    text = _SUFFIX.sub("", text).strip()
    return text


def match(message: str) -> dict | None:
    """The tool call this message plainly means, or None to use the model.

    Returns {"tool", "arguments", "confirmation"} -- the confirmation is the
    sentence to say back, written here so no second model pass is needed to
    produce "Closed Discord."
    """
    text = _strip(message)
    if not text or len(text) > 60:
        return None
    # The read-only phrases are checked first and exactly. They are questions,
    # so the disqualifier below would otherwise reject every one of them --
    # and a question is only dangerous here when it might be interpreted as an
    # instruction, which an exact match on a fixed list cannot be.
    lowered = text.lower()
    if lowered in _LIST_WINDOWS:
        return {"tool": "list_windows", "arguments": {}, "confirmation": None}

    if _DISQUALIFIERS.search(text) or _WEB_OR_COURSEWORK.search(text):
        return None

    # Each tool takes a differently-named argument, and "close" maps to the
    # graceful close_window rather than kill_process on purpose: terminating a
    # process gives the app no chance to save, and "close Discord" is a
    # request to close a window, not to kill it. Only an explicit "kill" or
    # "force quit" gets the forceful one.
    for pattern, tool, field, verb in (
        (_CLOSE, "close_window", "title_contains", "close"),
        (_KILL, "kill_process", "name", "kill"),
        (_OPEN, "open_app", "path", "open"),
    ):
        found = pattern.match(text)
        if not found:
            continue
        target = found.group(1).strip().strip("\"'")
        if not target or target.lower() in _NOT_APPS or _WEB_OR_COURSEWORK.search(target):
            return None
        # A target of several words is more likely a sentence than an app
        # name: "open the file I was editing" is not something to resolve
        # without a model.
        if len(target.split()) > 3:
            return None
        return {
            "tool": tool,
            "arguments": {field: target},
            "confirmation": confirmation(verb, target),
        }
    return None


# Said out loud, several times a day. "Closed discord." is how a log line
# reads, not how a person answers -- and because this path skips the model
# entirely, whatever is written here IS Nova's voice for these commands.
# Varied so the same three words are not repeated every single time, and
# short because the whole point of this path is that it is quick.
_SAID = {
    "close": ("{t}'s gone.", "Done — {t}'s closed.", "Closed {t}.", "{t}, shut."),
    "kill": ("Killed {t}.", "{t}'s dead.", "Force-quit {t}."),
    "open": ("{t}'s up.", "Opened {t}.", "There's {t}.", "{t}, coming up."),
}


def confirmation(verb: str, target: str) -> str:
    """One way of saying it. Rotates rather than randomises so the same
    command twice in a row does not answer identically, while a given
    session stays predictable enough not to feel like a slot machine."""
    options = _SAID[verb]
    _COUNTER[verb] = (_COUNTER.get(verb, -1) + 1) % len(options)
    # The target arrives however it was said -- usually all lowercase from
    # speech. Only the first letter is raised, so "VS Code" keeps its shape
    # where .capitalize() would flatten it to "Vs code".
    shown = target[0].upper() + target[1:] if target else target
    return options[_COUNTER[verb]].format(t=shown)


_COUNTER: dict[str, int] = {}
