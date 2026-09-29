"""Coursework questions answered from the database, not by a model.

Nova was handed the true figures in its prompt -- "0 due today, 12 in the next
7 days. Use these numbers; do not estimate your own" -- and still told the
user five. A 4B model garbles a number it repeats, and a wrong deadline count
is the single most damaging thing this assistant can say: it sounds exactly
like the truth and it is about the thing they actually need it for.

So the asked case is not left to a model at all. The same treatment "close
Discord" and "what time is it" already get, for the same reason: there is one
correct answer, it is a row lookup, and a language model adds nothing but
latency and the chance of being wrong.

This does not fix a number Nova volunteers unprompted in conversation -- that
is still the model talking, and this module cannot reach it. It fixes every
case where the user actually asks.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from . import db

# Anything suggesting the question is bigger than a lookup: help me plan it,
# explain it, decide what to do. Those want the model.
_DISQUALIFIERS = re.compile(
    # "do" on its own was here and matched "what do i have due", which is the
    # plainest phrasing of the question this module exists to answer. Only the
    # phrases that really signal a bigger request belong in this list.
    r"\b(help|plan|explain|how|why|should|start|write|finish|study|"
    r"prioriti[sz]e|which one|summar|breakdown|break down|do it|do first)\b",
    re.IGNORECASE,
)

_PREFIX = re.compile(
    r"^(?:hey |ok |okay |so |and )*(?:nova[,\s]+)?(?:can you |could you |please )?",
    re.IGNORECASE,
)

# The window a phrasing is asking about. Order matters -- "this week" has to be
# tested before the bare "due" catch-all.
_WINDOWS = (
    (re.compile(r"\b(today|tonight|due now)\b", re.IGNORECASE), 0, "today"),
    (re.compile(r"\btomorrow\b", re.IGNORECASE), 1, "tomorrow"),
    (re.compile(r"\b(this week|next 7 days|next seven days|the week)\b", re.IGNORECASE), 7, "this week"),
    (re.compile(r"\bnext week\b", re.IGNORECASE), 14, "over the next two weeks"),
)

_ASKS_DUE = re.compile(
    r"\b(due|assignments?|homework|coursework|classes|deadlines?)\b", re.IGNORECASE
)
_ASKS_QUESTION = re.compile(
    r"^(what|whats|what's|anything|do i have|have i got|is there|when)\b", re.IGNORECASE
)


def match(message: str) -> dict | None:
    """The coursework window this message is asking about, or None."""
    text = _PREFIX.sub("", (message or "").strip().replace("’", "'"), count=1)
    text = text.rstrip(" .!?").strip()
    if not text or len(text) > 70:
        return None
    if _DISQUALIFIERS.search(text) or not _ASKS_DUE.search(text):
        return None
    if not _ASKS_QUESTION.match(text):
        return None

    for pattern, days, label in _WINDOWS:
        if pattern.search(text):
            return {"days": days, "label": label}
    # "what's due" with no window named: the useful default is the week, not
    # the whole remaining semester.
    return {"days": 7, "label": "this week"}


def _day_phrase(when, today) -> str:
    delta = (when - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta < 7:
        return when.strftime("%A")
    return when.strftime("%A the %d").replace(" 0", " ")


async def answer(window: dict) -> str:
    """A spoken-shaped answer built from the rows themselves."""
    rows = await db.list_canvas_assignments()
    today = datetime.now().astimezone().date()
    horizon = today + timedelta(days=window["days"])

    upcoming = []
    for row in rows:
        raw = row.get("due_at")
        if not raw:
            continue
        try:
            when = datetime.fromisoformat(raw).astimezone().date()
        except (TypeError, ValueError):
            continue
        if today <= when <= horizon:
            upcoming.append((when, row))
    upcoming.sort(key=lambda pair: pair[0])

    if not upcoming:
        if window["days"] == 0:
            return "Nothing due today."
        return f"Nothing due {window['label']}."

    # Grouped by day, because "12 things" is a number and "three Friday, two
    # Sunday" is an answer.
    by_day: dict = {}
    for when, row in upcoming:
        by_day.setdefault(when, []).append(row)

    if len(upcoming) == 1:
        when, row = upcoming[0]
        return f"One thing — {clean_title(row, 70)}, {_day_phrase(when, today)}."

    # All on one day: naming the day twice ("3 tomorrow -- 3 tomorrow") is
    # what the first version did. Say it once and name the work.
    if len(by_day) == 1:
        day, rows_ = next(iter(by_day.items()))
        return f"{_count(len(rows_)).capitalize()} {_day_phrase(day, today)} — {_listed(rows_)}."

    parts = [f"{_count(len(rows_))} {_day_phrase(day, today)}"
             for day, rows_ in list(by_day.items())[:4]]
    spoken = ", ".join(parts[:-1]) + " and " + parts[-1]
    if len(by_day) > 4:
        spoken += ", plus more after that"

    # A count alone is a number, not an answer -- name the nearest day's work
    # so there is something to act on.
    first_day, first_rows = next(iter(by_day.items()))
    return (f"{len(upcoming)} {window['label']}: {spoken}. "
            f"{_day_phrase(first_day, today).capitalize()} is {_listed(first_rows)}.")


_SMALL = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _count(n: int) -> str:
    """Small numbers as words: this is read aloud, and "3" and "three" are
    the same length to the ear but not on the page."""
    return _SMALL[n] if n < len(_SMALL) else str(n)


def clean_title(row: dict, limit: int | None = None) -> str:
    """Canvas titles often carry the same phrase twice -- "3.6 The Chain Rule
    The Chain Rule" -- because the assignment name repeats the module name.
    Out loud that is a stutter; on screen it is what pushes the real words
    past the truncation.

    The repeat is not always at the end: "3.9a Derivatives of Exponential and
    Logarithmic Functions Derivatives of Exponential and Logarithmic Functions
    with Bases other than e" repeats in the middle and carries the part that
    actually distinguishes it afterwards. So this looks for any phrase
    immediately followed by itself, at any position, and drops the second
    copy -- which keeps the tail that makes the title unique.

    `limit` is for speech, where a long title has to be cut somewhere. The
    screen passes none and lets CSS do it, since a clipped line the user can
    widen beats a sentence the server decided to end.
    """
    words = " ".join((row.get("title") or "").split()).split()
    changed = True
    while changed:
        changed = False
        # Longest first: collapsing a long repeat is right where collapsing a
        # short one inside it would leave the rest stranded.
        for size in range(len(words) // 2, 1, -1):
            for at in range(0, len(words) - 2 * size + 1):
                if words[at:at + size] == words[at + size:at + 2 * size]:
                    del words[at + size:at + 2 * size]
                    changed = True
                    break
            if changed:
                break
    title = " ".join(words)
    return (title[:limit] if limit else title).rstrip(" ,-")

def _listed(rows: list[dict]) -> str:
    names = [clean_title(r, 70) for r in rows[:3]]
    listed = ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1]
    extra = len(rows) - len(names)
    return listed + (f", and {_count(extra)} more" if extra > 0 else "")
