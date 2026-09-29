"""One calendar view over everything with a date, and planning study time.

The agenda merges every calendar the user connected -- Apple (iCloud), Google
(through the Google Workspace connector) and any calendar by its private link
(calendar_sources) -- with Canvas due dates and work found on other homework
platforms, so "what's my week" has one answer.

A study session is a real event written to the calendar the user picked
(Apple or Google) before an assignment is due, at the hour and length they
chose in Settings > Calendar, skipping time any connected calendar says is
busy. On Apple its UID is derived from the assignment, so planning the same
assignment twice moves the session rather than adding a second one.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from . import apple_calendar, calendar_sources, db


class CalendarError(RuntimeError):
    """Said to the user as-is."""


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:  # an all-day date, or a floating time: local
        d = d.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return d


async def _events(start: datetime, end: datetime) -> tuple[list[dict], list[str]]:
    """Events from every connected calendar, in one shape."""
    items, notes = [], []
    if apple_calendar.status().get("configured"):
        try:
            days = max(1, (end - start).days + 1)
            for e in await apple_calendar.list_events(days=days, start=start.astimezone(timezone.utc)):
                items.append({"kind": "event", "title": e["title"], "start": e["start"], "end": e["end"],
                              "all_day": e["all_day"], "where": e["location"], "source": e["calendar"],
                              "calendar_url": e["calendar_url"], "href": e["href"], "uid": e["uid"]})
        except apple_calendar.AppleCalendarError as exc:
            notes.append(f"Apple Calendar: {exc}")
    other, problems = await calendar_sources.events_between(start, end)
    return items + other, notes + problems


async def agenda(days: int = 14) -> dict:
    """Everything dated from today through `days` ahead, sorted, one list."""
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    horizon = start + timedelta(days=max(1, min(days, 90)))
    items, notes = await _events(start, horizon)
    for a in await db.list_canvas_assignments(include_submitted=False):
        due = _dt(a.get("due_at"))
        if due and start <= due < horizon:
            items.append({"kind": "due", "title": a.get("display_title") or a.get("title"), "start": due.isoformat(),
                          "end": None, "all_day": False, "source": a.get("course_name") or "Canvas", "url": a.get("url")})
    try:
        from . import homework_discovery
        for a in homework_discovery.items():
            due = _dt(a.get("due_at"))
            if due and start <= due < horizon:
                items.append({"kind": "due", "title": a["title"], "start": due.isoformat(), "end": None,
                              "all_day": False, "source": a.get("platform"), "url": a.get("url")})
    except Exception:  # noqa: BLE001 -- another platform's list never blocks the calendar
        pass
    items.sort(key=lambda i: _dt(i["start"]) or horizon)
    connected = apple_calendar.status().get("configured") or bool(calendar_sources.feeds()) or bool(await calendar_sources.google_accounts())
    return {"items": items, "note": "; ".join(notes) or (None if connected else "Connect a calendar in Settings, Calendar, to see your events here."),
            "apple_connected": bool(apple_calendar.status().get("configured")), "connected": bool(connected),
            "can_write": await _can_write()}


async def _can_write() -> bool:
    return bool(apple_calendar.status().get("configured")) or bool(await calendar_sources.google_accounts())


async def _target(settings: dict) -> str:
    """Where Nova writes: the chosen calendar, else Apple's first writable
    one, else the primary calendar of the first connected Google account."""
    chosen = (settings.get("calendar_default_url") or "").strip()
    if chosen:
        return chosen
    if apple_calendar.status().get("configured"):
        writable = [c for c in await apple_calendar.list_calendars() if not c.get("read_only")]
        if writable:
            return writable[0]["url"]
    for account in await calendar_sources.google_accounts():
        cals = await calendar_sources.google_calendars(account)
        primary = next((c for c in cals if c["primary"]), cals[0] if cals else None)
        if primary:
            return f"google:{account['email']}:{primary['id']}"
    raise CalendarError("Connect Apple Calendar or Google Calendar in Settings so Nova has somewhere to add events.")


async def create_event(title: str, start: datetime, end: datetime, *, notes: str = "", uid: str | None = None,
                       calendar: str | None = None) -> dict:
    settings = await db.get_app_settings()
    target = calendar or await _target(settings)
    if target.startswith("google:"):
        return await calendar_sources.google_create(target, title, start, end, notes)
    reminder = int(settings.get("calendar_reminder_minutes") or 30)
    return await apple_calendar.create_event(target, title, start, end, notes=notes,
                                             reminder_minutes=[reminder] if reminder else None, uid=uid)


def _busy(events: list[dict], start: datetime, end: datetime) -> bool:
    for e in events:
        s, f = _dt(e.get("start")), _dt(e.get("end"))
        if s and f and s < end and f > start and not e.get("all_day"):
            return True
    return False


async def plan_study(title: str, due_at: str, url: str = "", minutes: int | None = None) -> dict:
    """Put a study session in the calendar before an assignment is due."""
    if not await _can_write():
        raise CalendarError("Connect Apple Calendar or Google Calendar in Settings first.")
    due = _dt(due_at)
    now = datetime.now().astimezone()
    if not due or due <= now:
        raise CalendarError("That assignment has no due date in the future.")
    settings = await db.get_app_settings()
    length = timedelta(minutes=int(minutes or settings.get("study_block_minutes") or 60))
    hour = int(settings.get("study_block_hour") or 19)
    events, _ = await _events(now, due + timedelta(days=1))

    # The evening before it's due at the chosen hour, else earlier days, else
    # later that evening, else now; always around busy time.
    candidates = []
    for back in range(1, 8):
        day = (due - timedelta(days=back)).replace(hour=hour, minute=0, second=0, microsecond=0)
        for shift in range(0, 4):
            candidates.append(day + timedelta(hours=shift))
    candidates.append(now + timedelta(minutes=15))
    slot = next((c for c in candidates if c > now and c + length <= due and not _busy(events, c, c + length)), None)
    if slot is None:
        raise CalendarError("There's no free time left before it's due.")
    uid = "nova-study-" + hashlib.sha1((url or title).encode()).hexdigest()[:16]
    created = await create_event(
        f"Study: {title}"[:200], slot, slot + length, uid=uid,
        notes=f"Planned by Nova. Due {due.strftime('%a %b %d, %I:%M %p')}." + (f"\n{url}" if url else ""))
    return {"planned": True, "start": slot.isoformat(), "end": (slot + length).isoformat(), "event": created}


async def plan_week(days: int = 7) -> dict:
    """A study session for every open assignment due in the next `days`."""
    items = [i for i in (await agenda(days))["items"] if i["kind"] == "due"]
    done, failed = [], []
    for i in items:
        try:
            r = await plan_study(i["title"], i["start"], i.get("url") or "")
            done.append({"title": i["title"], "start": r["start"]})
        except Exception as exc:  # noqa: BLE001 -- one assignment failing never stops the rest
            failed.append({"title": i["title"], "reason": str(exc)})
    return {"planned": done, "skipped": failed}


async def free_time(days: int = 7, minutes: int = 60, day_start: int = 8, day_end: int = 22) -> list[dict]:
    """Open stretches of at least `minutes` in waking hours, across every calendar."""
    now = datetime.now().astimezone()
    events, _ = await _events(now.replace(hour=0, minute=0, second=0, microsecond=0), now + timedelta(days=days))
    spans = sorted(((_dt(e["start"]), _dt(e["end"])) for e in events
                    if not e.get("all_day") and e.get("start") and e.get("end") and _dt(e["start"]) and _dt(e["end"])),
                   key=lambda s: s[0])
    out = []
    for d in range(days):
        day = (now + timedelta(days=d)).replace(hour=day_start, minute=0, second=0, microsecond=0)
        cursor, stop = max(day, now), day.replace(hour=day_end)
        for s, f in spans:
            if f <= cursor or s >= stop:
                continue
            if (s - cursor) >= timedelta(minutes=minutes):
                out.append({"start": cursor.isoformat(), "end": s.isoformat()})
            cursor = max(cursor, f)
        if stop - cursor >= timedelta(minutes=minutes):
            out.append({"start": cursor.isoformat(), "end": stop.isoformat()})
    return out[:40]
