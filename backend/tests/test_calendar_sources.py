"""Calendars other than Apple (app/calendar_sources.py)."""
from datetime import datetime, timedelta, timezone

from app import calendar_sources

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
X-WR-CALNAME:Lab schedule
BEGIN:VEVENT
UID:lab-1
DTSTART:20260105T140000Z
DTEND:20260105T160000Z
RRULE:FREQ=WEEKLY;COUNT=10
SUMMARY:Chem lab
LOCATION:Room 204
END:VEVENT
END:VCALENDAR
"""


def test_calendar_link_events_expand_repeats():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = calendar_sources._events_from_ics(ICS, start, start + timedelta(days=21), "Lab schedule")
    assert [r["title"] for r in rows] == ["Chem lab"] * 3
    assert rows[0]["where"] == "Room 204" and rows[0]["readonly"]


def test_calendar_links_are_https_or_webcal_only():
    assert calendar_sources._normalize("webcal://calendar.example.com/x.ics") == "https://calendar.example.com/x.ics"
    for bad in ("http://example.com/x.ics", "file:///C:/x.ics", "javascript:alert(1)"):
        try:
            calendar_sources._normalize(bad)
            raise AssertionError(bad)
        except calendar_sources.SourceError:
            pass


def test_google_event_lines_are_parsed_by_shape_only():
    text = "\n".join([
        "Successfully retrieved 2 events:",
        '- "Office hours" (Starts: 2026-10-01T15:00:00-04:00, Ends: 2026-10-01T16:00:00-04:00)',
        "  ID: abc | Link: https://x",
        '- "Holiday" (Starts: 2026-10-02, Ends: 2026-10-03)',
        "garbage line (Starts: nope)",
    ])
    hits = [m for m in (calendar_sources.EVENT_LINE.match(line.strip()) for line in text.splitlines()) if m]
    assert [m["title"] for m in hits] == ["Office hours", "Holiday"]
    cal = calendar_sources.CAL_LINE.match('- "Family" (ID: fam@group.calendar.google.com)')
    assert cal["name"] == "Family" and cal["id"].startswith("fam@")
    primary = calendar_sources.CAL_LINE.match('- "me@example.com" (Primary) (ID: me@example.com)')
    assert primary["primary"]
