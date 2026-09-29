"""Calendars other than Apple: any calendar by its private link, and Google.

Two ways in, so every user has one that needs no developer setup:

- A calendar link (iCal/ICS). Google Calendar ("Secret address in iCal
  format"), Outlook and Microsoft 365 ("Publish a calendar"), Yahoo, a school
  or team calendar -- almost every calendar can hand out one. Read only, and
  repeating events are expanded properly (_occurrences, on dateutil's rrule).
- Google Calendar through the Google Workspace connector, when the user has
  connected it (Settings > Connectors). Read and write, every calendar on the
  account. The connector answers in sentences, so its event lines are parsed
  by their fixed shape; anything that doesn't match is skipped, never guessed.

Both feed calendar_hub's agenda, free time and study planning.
"""
from __future__ import annotations

import asyncio
import glob
import logging
import os
import re
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from . import db, operator_store as store

logger = logging.getLogger(__name__)

FEED = "calendar_feed"
_cache: dict[str, tuple[float, object]] = {}
CACHE_SECONDS = 600


class SourceError(RuntimeError):
    """Said to the user as-is."""


def _local(d) -> datetime:
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return datetime(d.year, d.month, d.day, tzinfo=datetime.now().astimezone().tzinfo)


# ---- calendar links (ICS) ----------------------------------------------------

def feeds() -> list[dict]:
    return sorted(store.listing(FEED), key=lambda f: f.get("added_at", 0))


def _normalize(url: str) -> str:
    url = (url or "").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[9:]
    if not re.match(r"^https://", url, re.I):
        raise SourceError("Paste the calendar's https:// or webcal:// link.")
    return url


async def _fetch(url: str) -> bytes:
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "Nova calendar"}) as client:
        r = await client.get(url)
    if r.status_code != 200:
        raise SourceError(f"The calendar link answered {r.status_code}. Check that it's the private or published link.")
    if b"BEGIN:VCALENDAR" not in r.content[:4000]:
        raise SourceError("That link isn't a calendar feed. Use the iCal (.ics) link, not the calendar's web page.")
    _cache[url] = (time.time(), r.content)
    return r.content


def _occurrences(ev, start: datetime, end: datetime) -> list[tuple]:
    """(start, end) of each time a VEVENT happens inside [start, end): its
    RRULE and RDATEs, minus EXDATEs. Moved single instances (RECURRENCE-ID)
    are separate VEVENTs, handled by the caller."""
    from dateutil.rrule import rruleset, rrulestr

    s = ev.get("DTSTART").dt
    timed = isinstance(s, datetime)
    if ev.get("DTEND") is not None:
        length = ev.get("DTEND").dt - s
    elif ev.get("DURATION") is not None:
        length = ev.get("DURATION").dt
    else:
        length = timedelta(0) if timed else timedelta(days=1)
    first = s if timed else datetime(s.year, s.month, s.day)
    floating = first.tzinfo is None  # all-day and "floating" times are wall-clock times

    def norm(d):
        d = d if isinstance(d, datetime) else datetime(d.year, d.month, d.day)
        if floating:
            return d.astimezone().replace(tzinfo=None) if d.tzinfo else d
        return d if d.tzinfo else d.replace(tzinfo=first.tzinfo)

    lo, hi = norm(start), norm(end)
    times = rruleset()
    if ev.get("RRULE") is not None:
        text = ev.get("RRULE").to_ical().decode()
        if floating:
            text = re.sub(r"(UNTIL=\d{8}(?:T\d{6})?)Z", r"\1", text)
        else:  # dateutil wants UNTIL in UTC when the start has a time zone
            text = re.sub(r"UNTIL=(\d{8})(?=;|$)", r"UNTIL=\1T235959Z", text)
            text = re.sub(r"UNTIL=(\d{8}T\d{6})(?=;|$)", r"UNTIL=\1Z", text)
        times.rrule(rrulestr(text, dtstart=first))
    else:
        times.rdate(first)
    for key, add in (("RDATE", times.rdate), ("EXDATE", times.exdate)):
        values = ev.get(key)
        for group in values if isinstance(values, list) else ([values] if values is not None else []):
            for d in group.dts:
                add(norm(d.dt))
    out = []
    for when in times.between(lo - length, hi, inc=True):
        overlaps = when < hi and (when + length > lo or (not length and when >= lo))
        if overlaps:
            begin = when if timed else when.date()
            out.append((begin, begin + length))
    return out


def _events_from_ics(data: bytes, start: datetime, end: datetime, name: str) -> list[dict]:
    import icalendar
    cal = icalendar.Calendar.from_ical(data)
    events = [ev for ev in cal.walk("VEVENT") if ev.get("DTSTART") is not None]
    # A moved or edited single occurrence replaces the one its series would
    # have produced at that RECURRENCE-ID.
    moved = {(str(ev.get("UID")), _local(ev.get("RECURRENCE-ID").dt).isoformat())
             for ev in events if ev.get("RECURRENCE-ID") is not None}
    rows = []
    for ev in events:
        if str(ev.get("STATUS") or "").upper() == "CANCELLED":
            continue
        series = ev.get("RECURRENCE-ID") is None
        for s, e in _occurrences(ev, start, end):
            if series and (str(ev.get("UID")), _local(s).isoformat()) in moved:
                continue
            all_day = isinstance(s, date) and not isinstance(s, datetime)
            rows.append({"kind": "event", "title": str(ev.get("SUMMARY") or "(no title)"),
                         "start": _local(s).isoformat(), "end": _local(e).isoformat() if e else None,
                         "all_day": all_day, "where": str(ev.get("LOCATION") or ""), "source": name, "readonly": True})
    rows.sort(key=lambda r: r["start"])
    return rows


async def add_feed(url: str, name: str = "") -> dict:
    url = _normalize(url)
    for f in feeds():
        if f["url"] == url:
            return f
    data = await _fetch(url)
    import icalendar
    cal = icalendar.Calendar.from_ical(data)
    label = (name or str(cal.get("X-WR-CALNAME") or "") or "Calendar").strip()[:80]
    return store.create(FEED, name=label, url=url, added_at=time.time())


def remove_feed(feed_id: str) -> None:
    with store.transaction() as conn:
        conn.execute("DELETE FROM records WHERE kind=? AND id=?", (FEED, feed_id))


async def feed_events(start: datetime, end: datetime) -> tuple[list[dict], list[str]]:
    rows, problems = [], []
    for f in feeds():
        try:
            rows.extend(_events_from_ics(await _fetch(f["url"]), start, end, f["name"]))
        except Exception as exc:  # noqa: BLE001 -- one broken link never hides the rest
            problems.append(f"{f['name']}: {exc}")
    return rows, problems


# ---- Google, through the Google Workspace connector ----------------------------

EVENT_LINE = re.compile(r'^- "(?P<title>.*)" \(Starts: (?P<start>[^,]+), Ends: (?P<end>[^)]+)\)')
CAL_LINE = re.compile(r'^- "(?P<name>.*)"(?P<primary> \(Primary\))? \(ID: (?P<id>[^)]+)\)')


def _account_email(server_name: str) -> str | None:
    """The signed-in Google account behind a 'Google Workspace (X)' connector:
    its credentials file is named after the address."""
    m = re.search(r"\(([^)]+)\)", server_name)
    role = (m.group(1) if m else "").strip().lower()
    base = os.path.join(os.path.expanduser("~"), ".ai-council")
    pattern = os.path.join(base, f"workspace-mcp-{role}" if role else "workspace-mcp*", "*@*.json")
    files = glob.glob(pattern)
    return os.path.basename(files[0])[:-5] if files else None


async def google_accounts() -> list[dict]:
    """Connected Google Workspace connectors that have calendar tools."""
    out = []
    for row in await db.list_mcp_servers():
        if not row.get("enabled") or "google" not in (row.get("name") or "").lower():
            continue
        email = _account_email(row["name"])
        if email:
            out.append({"row": row, "email": email, "label": row["name"].replace("Google Workspace", "Google").strip()})
    return out


async def _call(row: dict, tool: str, args: dict) -> str:
    from . import mcp_manager
    return await asyncio.wait_for(mcp_manager.call_tool_from_row(row, tool, args), timeout=40)


async def google_calendars(account: dict) -> list[dict]:
    key = f"gcals:{account['email']}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    text = await _call(account["row"], "list_calendars", {"user_google_email": account["email"]})
    cals = [{"id": m["id"], "name": m["name"], "primary": bool(m["primary"])}
            for m in (CAL_LINE.match(line.strip()) for line in text.splitlines()) if m]
    _cache[key] = (time.time(), cals)
    return cals


def _rfc3339(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def google_events(start: datetime, end: datetime) -> tuple[list[dict], list[str]]:
    rows, problems = [], []
    for account in await google_accounts():
        try:
            for cal in await google_calendars(account):
                key = f"gev:{account['email']}:{cal['id']}:{start.date()}:{end.date()}"
                hit = _cache.get(key)
                if hit and time.time() - hit[0] < 300:
                    text = hit[1]
                else:
                    text = await _call(account["row"], "get_events", {
                        "user_google_email": account["email"], "calendar_id": cal["id"],
                        "time_min": _rfc3339(start), "time_max": _rfc3339(end), "max_results": 100})
                    _cache[key] = (time.time(), text)
                for line in text.splitlines():
                    m = EVENT_LINE.match(line.strip())
                    if not m:
                        continue
                    s, e = m["start"].strip(), m["end"].strip()
                    all_day = len(s) == 10
                    try:
                        sd = _local(datetime.fromisoformat(s) if not all_day else date.fromisoformat(s))
                        ed = _local(datetime.fromisoformat(e) if len(e) > 10 else date.fromisoformat(e))
                    except ValueError:
                        continue
                    rows.append({"kind": "event", "title": m["title"], "start": sd.isoformat(), "end": ed.isoformat(),
                                 "all_day": all_day, "where": "", "source": f"{cal['name']} (Google)", "readonly": True})
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{account['label']}: {exc}")
    return rows, problems


async def google_create(target: str, title: str, start: datetime, end: datetime, notes: str = "") -> dict:
    """target is 'google:<email>:<calendar id>'."""
    _, email, cal_id = target.split(":", 2)
    account = next((a for a in await google_accounts() if a["email"] == email), None)
    if not account:
        raise SourceError("That Google account isn't connected any more.")
    text = await _call(account["row"], "manage_event", {
        "user_google_email": email, "action": "create", "calendar_id": cal_id, "summary": title,
        "start_time": _rfc3339(start), "end_time": _rfc3339(end), "description": notes})
    if "success" not in text.lower():
        raise SourceError(f"Google didn't add it: {text[:200]}")
    for k in [k for k in _cache if k.startswith(f"gev:{email}:")]:
        _cache.pop(k, None)
    return {"created": True, "calendar": cal_id}


async def all_sources() -> dict:
    """Everything Nova can read from, and where it can write."""
    from . import apple_calendar
    apple = apple_calendar.status()
    out = {"apple": {"connected": bool(apple.get("configured")), "calendars": []}, "google": [], "feeds": feeds()}
    if apple.get("configured"):
        try:
            out["apple"]["calendars"] = [{"id": c["url"], "name": c["name"], "writable": not c.get("read_only")}
                                         for c in await apple_calendar.list_calendars()]
        except Exception as exc:  # noqa: BLE001
            out["apple"]["error"] = str(exc)
    for account in await google_accounts():
        entry = {"label": account["label"], "email": account["email"], "calendars": []}
        try:
            entry["calendars"] = [{"id": f"google:{account['email']}:{c['id']}", "name": c["name"], "primary": c["primary"], "writable": True}
                                  for c in await google_calendars(account)]
        except Exception as exc:  # noqa: BLE001
            entry["error"] = str(exc)
        out["google"].append(entry)
    return out


async def events_between(start: datetime, end: datetime) -> tuple[list[dict], list[str]]:
    (g, gp), (f, fp) = await asyncio.gather(google_events(start, end), feed_events(start, end))
    return g + f, gp + fp


def reset_cache() -> None:
    _cache.clear()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def horizon(days: int) -> tuple[datetime, datetime]:
    start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=days)
