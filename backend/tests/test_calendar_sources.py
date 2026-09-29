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


MOVED = b"""BEGIN:VCALENDAR
BEGIN:VEVENT
UID:class
DTSTART;TZID=America/New_York:20260106T090000
DTEND;TZID=America/New_York:20260106T100000
RRULE:FREQ=WEEKLY;UNTIL=20260127
EXDATE;TZID=America/New_York:20260113T090000
SUMMARY:Class
END:VEVENT
BEGIN:VEVENT
UID:class
RECURRENCE-ID;TZID=America/New_York:20260120T090000
DTSTART;TZID=America/New_York:20260120T110000
DTEND;TZID=America/New_York:20260120T120000
SUMMARY:Class (moved)
END:VEVENT
BEGIN:VEVENT
UID:break
DTSTART;VALUE=DATE:20260110
DTEND;VALUE=DATE:20260111
RRULE:FREQ=DAILY;COUNT=2
SUMMARY:Break
END:VEVENT
END:VCALENDAR
"""


def test_skipped_and_moved_repeats_and_all_day_events():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = calendar_sources._events_from_ics(MOVED, start, start + timedelta(days=40), "School")
    got = [(r["title"], r["start"][:16], r["all_day"]) for r in rows]
    assert got == [
        ("Class", "2026-01-06T09:00", False),
        ("Break", "2026-01-10T00:00", True),
        ("Break", "2026-01-11T00:00", True),
        ("Class (moved)", "2026-01-20T11:00", False),
        ("Class", "2026-01-27T09:00", False),
    ]
