"""Canvas assignments read from the per-user Calendar Feed, no API token.

Why this exists: many institutions disable personal access tokens for students,
which makes `canvas.py` unusable no matter how the user configures it. Canvas
still hands every user a private, read-only iCalendar URL (Canvas -> Calendar ->
"Calendar Feed"), and that URL carries its own opaque auth token in the path, so
it needs no header, no OAuth, and no live SSO session. It keeps working from a
background job at 11:59pm for the same reason a subscribed phone calendar does.

What it costs, stated plainly rather than discovered later:

  * **No submission state.** The feed lists an assignment whether or not it has
    been handed in, so `submitted` is always False here. The consequence is that
    finished work keeps showing in the calendar until its due date passes. The
    API path does know, which is why that one is still preferred when available.
  * **No points, and only the plain-text description Canvas chose to include.**
  * **Roughly a year's window.** Canvas trims very old and very distant events.

Assignment ids are pulled out of the event URL (or the UID) so that a row synced
from the feed and the same row synced from the API share one `canvas_id`. That
is what lets a user switch sources -- or get a token later -- without the nightly
job suddenly reporting every assignment as new.

Read-only, like the rest of the Canvas code. Nothing here submits or posts.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone

import httpx
from dotenv import set_key

from . import config

TIMEOUT = 45
MAX_BYTES = 8_000_000  # a year of assignments is ~100KB; this is a runaway guard

# Canvas builds these as `event-assignment-<id>@<host>` (and
# `event-calendar-event-<id>@<host>` for things a professor posted straight to
# the calendar). The URL is the more reliable of the two, so it is tried first.
_URL_ASSIGNMENT = re.compile(r"/assignments/(\d+)")
_URL_COURSE = re.compile(r"/courses/(\d+)")
_UID_ID = re.compile(r"event-(?:calendar-)?(?:assignment|event)-(\d+)")
# Canvas appends the course name in brackets: "Problem Set 4 [MATH 231-02]".
_SUMMARY_COURSE = re.compile(r"^(.*?)\s*\[([^\]]+)\]\s*$", re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")


class FeedError(RuntimeError):
    """Configuration or fetch failure, phrased for display."""


def feed_url() -> str | None:
    return os.getenv("CANVAS_ICS_URL", "").strip() or None


def configured() -> bool:
    return bool(feed_url())


def status() -> dict:
    url = feed_url()
    return {
        "configured": bool(url),
        # Never echo the whole URL back to the UI or a model: the token in it is
        # the credential, and anyone holding it can read this user's schedule.
        "feed_host": url.split("/")[2] if url and "//" in url else None,
    }


def update_feed_url(url: str | None) -> dict:
    if url is not None:
        cleaned = url.strip()
        if cleaned:
            if cleaned.startswith("webcal://"):
                cleaned = "https://" + cleaned[len("webcal://"):]
            if not cleaned.startswith(("http://", "https://")):
                raise FeedError("That doesn't look like a calendar feed URL — it should start with https:// or webcal://.")
            if not cleaned.split("?")[0].endswith(".ics"):
                raise FeedError(
                    "That URL doesn't end in .ics. In Canvas open Calendar, click "
                    "\"Calendar Feed\" at the bottom right, and copy the link it shows."
                )
        set_key(str(config.ENV_PATH), "CANVAS_ICS_URL", cleaned)
        os.environ["CANVAS_ICS_URL"] = cleaned
    return status()


def _text(value) -> str:
    """icalendar hands back vText/vUri objects; some feeds carry HTML."""
    if value is None:
        return ""
    return _TAGS.sub(" ", str(value)).replace("&nbsp;", " ").strip()


def _as_datetime(value) -> datetime | None:
    """VEVENT DTSTART is a datetime for timed events and a plain date for
    all-day ones. An all-day assignment is treated as due at the end of that
    local day, which is what Canvas means by it."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.astimezone()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 23, 59).astimezone()
    return None


def parse(ics_text: str) -> list[dict]:
    """Normalise a Canvas calendar feed into the same shape `canvas.list_assignments`
    returns, so everything downstream (dedupe, .ics rebuild, digest) is unchanged."""
    from icalendar import Calendar

    try:
        calendar = Calendar.from_ical(ics_text)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
        raise FeedError(f"That feed didn't parse as a calendar: {exc}") from exc

    rows: list[dict] = []
    seen: set[str] = set()
    for component in calendar.walk("VEVENT"):
        uid = _text(component.get("UID"))
        url = _text(component.get("URL"))
        summary = _text(component.get("SUMMARY"))
        due = _as_datetime(getattr(component.get("DTSTART"), "dt", None))
        if not summary or due is None:
            continue

        # Prefer the bare assignment id from the URL so this row collides
        # (correctly) with the same assignment fetched through the API. Anything
        # that is not an assignment -- a calendar event a professor posted
        # directly -- gets a prefix: Canvas numbers calendar events in their own
        # space, so an unprefixed id could collide with an unrelated assignment
        # and silently overwrite it in the dedupe table.
        found = _URL_ASSIGNMENT.search(url) or _UID_ID.search(uid)
        is_assignment = bool(_URL_ASSIGNMENT.search(url)) or "assignment" in uid
        if found:
            canvas_id = found.group(1) if is_assignment else f"cal-{found.group(1)}"
        else:
            canvas_id = f"feed-{abs(hash(uid or summary))}"
        if canvas_id in seen:
            continue        # recurring or duplicated event: one row is enough
        seen.add(canvas_id)

        title, course_name = summary, ""
        named = _SUMMARY_COURSE.match(summary)
        if named:
            title, course_name = named.group(1).strip(), named.group(2).strip()
        course = _URL_COURSE.search(url)

        rows.append({
            "canvas_id": canvas_id,
            "course_id": course.group(1) if course else "feed",
            "course_name": course_name or "Canvas",
            "title": title or "Untitled assignment",
            "due_at": due.isoformat(),
            "points": None,                       # not in the feed
            "url": url,
            "description": _text(component.get("DESCRIPTION"))[:4000],
            "submitted": False,                   # not in the feed -- see module docstring
        })

    rows.sort(key=lambda r: r["due_at"] or "9999")
    return rows


async def fetch() -> list[dict]:
    url = feed_url()
    if not url:
        raise FeedError(
            "No Canvas calendar feed set. In Canvas open Calendar, click \"Calendar Feed\" "
            "at the bottom right, copy that link, and paste it into Settings -> Canvas."
        )
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers={"Accept": "text/calendar, */*"})
    except httpx.HTTPError as exc:
        raise FeedError(f"Couldn't reach the Canvas calendar feed: {exc}") from exc

    if response.status_code in (401, 403):
        raise FeedError(
            "Canvas rejected the calendar feed link. Feed links are reset when you "
            "reset your Canvas password — open Calendar -> Calendar Feed and copy the new one."
        )
    if response.status_code == 404:
        raise FeedError("Canvas returned 404 for that feed link — recopy it from Calendar -> Calendar Feed.")
    response.raise_for_status()

    body = response.content[:MAX_BYTES].decode("utf-8", "replace")
    # A login page is HTML with a 200, which would otherwise fail as a confusing
    # parse error several layers down.
    if "BEGIN:VCALENDAR" not in body:
        raise FeedError(
            "That link returned a web page rather than a calendar. Make sure you copied the "
            "\"Calendar Feed\" link from Canvas and not the address of the calendar page itself."
        )
    return parse(body)


async def upcoming(days: int = 14) -> list[dict]:
    now = datetime.now(timezone.utc).timestamp()
    horizon = now + days * 86400
    out = []
    for row in await fetch():
        try:
            due = datetime.fromisoformat(row["due_at"]).timestamp()
        except ValueError:
            continue
        if now <= due <= horizon:
            out.append(row)
    return out
