"""The one thing Nova says without being asked.

"I want nova to text me whenever" is open-ended, and the temptation is to
build a general notification engine. That is the wrong first move. A channel
that reaches a locked phone spends trust every time it fires, and the fastest
way to get notifications switched off permanently is to send one that did not
need to exist.

So this sends exactly one kind of message, about the one dataset Nova holds
that is both time-sensitive and unambiguously the user's business: what is due
tomorrow. It is checked once a day, in the evening, when there is still time
to act on the answer, and it stays silent when there is nothing to say.

Everything here is deliberately conservative:
  - Nothing due tomorrow means no notification. A nightly "all clear" is how a
    useful reminder becomes background noise.
  - One per day, recorded in app settings, so a restart cannot send a second.
  - Failure is logged and dropped. A push that cannot be delivered must never
    take down the scheduler that noticed it was worth sending.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from . import db, push, school_intents

logger = logging.getLogger(__name__)

# Evening, so "due tomorrow" still leaves an evening to do something about it.
# A morning-of reminder for work due that day is mostly bad news delivered too
# late to help.
REMIND_HOUR = 18

SETTINGS_KEY = "reminders:last:coursework"
ENABLED_KEY = "reminders_coursework_enabled"

_task: asyncio.Task | None = None


def _title_of(row: dict) -> str:
    """The title with Canvas's duplicated phrasing removed.

    Reusing school_intents.clean_title rather than reading the raw field: the
    feed repeats the module name inside the assignment name, so the raw title
    reads "3.6 The Chain Rule The Chain Rule". On a lock screen, where about
    two lines survive, that stutter costs half the space the actual titles
    needed -- the first draft of this notification said "3.6 The Chain Rule
    The Chain Rule, 3.8 Implicit Differentiation Implicit Differentiation,
    and 5 more".
    """
    return school_intents.clean_title(row)


async def due_tomorrow() -> list[dict]:
    rows = await db.list_canvas_assignments()
    target = (datetime.now().astimezone() + timedelta(days=1)).date()
    hits = []
    for row in rows:
        raw = row.get("due_at")
        if not raw:
            continue
        try:
            due = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if due.astimezone().date() == target:
            hits.append(row)
    return hits


def compose(rows: list[dict]) -> tuple[str, str]:
    """Title and body for the notification.

    Written to be readable on a lock screen, where roughly two lines survive.
    The count leads because it is the part that decides whether the user opens
    the app; the titles follow for as far as they fit. Naming one or two
    beats "you have work due", which says nothing they did not already fear.
    """
    count = len(rows)
    titles = [_title_of(r) for r in rows]
    heading = "1 thing due tomorrow" if count == 1 else f"{count} things due tomorrow"
    if count == 1:
        body = titles[0]
    elif count == 2:
        body = f"{titles[0]} and {titles[1]}"
    else:
        body = f"{titles[0]}, {titles[1]}, and {count - 2} more"
    return heading, body


async def _run_once() -> dict:
    settings = await db.get_app_settings()
    if settings.get(ENABLED_KEY, "1") != "1":
        return {"ok": False, "reason": "coursework reminders are turned off"}

    today = datetime.now().astimezone().date().isoformat()
    if settings.get(SETTINGS_KEY) == today:
        return {"ok": False, "reason": "already sent today"}

    rows = await due_tomorrow()
    if not rows:
        # Recorded as done anyway: the decision for today has been made, and
        # without this the loop would re-check every minute until midnight.
        await db.set_app_settings({SETTINGS_KEY: today})
        return {"ok": False, "reason": "nothing due tomorrow"}

    title, body = compose(rows)
    from . import notify
    result = await notify.notify("reminder", title, body, url="/app/", tag="nova-coursework", view="academics")
    await db.set_app_settings({SETTINGS_KEY: today})
    return {"ok": bool(result.get("stored")), "sent": result.get("pushed", 0), **result}


async def _loop() -> None:
    while True:
        try:
            if datetime.now().astimezone().hour >= REMIND_HOUR:
                await _run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- a bad day must not end the loop
            logger.exception("Coursework reminder check failed")
        await asyncio.sleep(300)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        await asyncio.gather(_task, return_exceptions=True)
        _task = None
