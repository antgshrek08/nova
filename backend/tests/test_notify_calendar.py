"""Notification hub (app/notify.py) and calendar helpers (app/calendar_hub.py)."""
import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import calendar_hub, config, notify


class Hub(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        for target, attr, value in ((config, "DB_PATH", Path(self.tmp.name) / "t.db"),):
            p = patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        self.push = AsyncMock(return_value={"sent": 1})
        p = patch("app.push.send", self.push)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(notify.db, "touch_push_subscriptions", AsyncMock())
        p.start()
        self.addCleanup(p.stop)

    def settings(self, **values):
        p = patch.object(notify.db, "get_app_settings", AsyncMock(return_value=values))
        p.start()
        self.addCleanup(p.stop)

    async def test_stored_and_pushed(self):
        self.settings()
        r = await notify.notify("task", "Team job finished", "Research the topics")
        self.assertTrue(r["stored"])
        self.assertEqual(r["pushed"], 1)
        rows = notify.recent()
        self.assertEqual(rows[0]["kind"], "task")
        self.assertFalse(rows[0]["read"])
        self.assertEqual(notify.mark_read(), 1)
        self.assertTrue(notify.recent()[0]["read"])

    async def test_a_kind_turned_off_is_neither_stored_nor_pushed(self):
        self.settings(notify_homework="0")
        r = await notify.notify("homework", "New", "x")
        self.assertEqual(r["skipped"], "turned off")
        self.assertEqual(notify.recent(), [])
        self.push.assert_not_awaited()

    async def test_replies_stay_off_the_phone_unless_asked(self):
        self.settings()
        r = await notify.notify("reply", "Chat", "answer")
        self.assertTrue(r["stored"])
        self.push.assert_not_awaited()

    async def test_quiet_hours_hold_phone_pushes_except_needs_you(self):
        now = datetime.now()
        start = (now - timedelta(minutes=5)).strftime("%H:%M")
        end = (now + timedelta(minutes=30)).strftime("%H:%M")
        self.settings(quiet_hours=f"{start}-{end}")
        r = await notify.notify("task", "Done", "x")
        self.assertEqual(r["skipped"], "quiet hours")
        await notify.notify("needs_you", "OK?", "x")
        self.push.assert_awaited_once()

    async def test_history_is_capped(self):
        self.settings(notify_phone="0")
        for i in range(notify.KEEP + 15):
            await notify.notify("task", f"n{i}", "x")
        self.assertLessEqual(len(notify.recent(limit=500)), notify.KEEP)


def test_quiet_hours_across_midnight():
    assert notify.quiet_now("22:00-07:00", datetime(2026, 1, 1, 23, 30))
    assert notify.quiet_now("22:00-07:00", datetime(2026, 1, 1, 6, 59))
    assert not notify.quiet_now("22:00-07:00", datetime(2026, 1, 1, 12, 0))
    assert not notify.quiet_now("", datetime(2026, 1, 1, 23, 0))
    assert not notify.quiet_now("nonsense", datetime(2026, 1, 1, 23, 0))


def test_study_session_goes_the_evening_before_around_busy_time():
    now = datetime.now().astimezone()
    due = (now + timedelta(days=3)).replace(hour=23, minute=59, second=0, microsecond=0)
    evening = (due - timedelta(days=1)).replace(hour=19, minute=0)
    busy = [{"title": "Practice", "start": evening.isoformat(), "end": (evening + timedelta(hours=1)).isoformat(), "all_day": False,
             "location": "", "calendar": "Home", "calendar_url": "cal", "href": "", "uid": "x"}]
    created = {}

    async def create(calendar_url, title, start, end, **kw):
        created.update(title=title, start=start, end=end, uid=kw.get("uid"), reminder=kw.get("reminder_minutes"))
        return {"uid": kw.get("uid")}

    with patch.object(calendar_hub.apple_calendar, "status", return_value={"configured": True}), \
            patch.object(calendar_hub.apple_calendar, "list_calendars", AsyncMock(return_value=[{"url": "cal", "read_only": False}])), \
            patch.object(calendar_hub.apple_calendar, "list_events", AsyncMock(return_value=busy)), \
            patch.object(calendar_hub.apple_calendar, "create_event", AsyncMock(side_effect=create)), \
            patch.object(calendar_hub.calendar_sources, "events_between", AsyncMock(return_value=([], []))), \
            patch.object(calendar_hub.calendar_sources, "google_accounts", AsyncMock(return_value=[])), \
            patch.object(calendar_hub.db, "get_app_settings", AsyncMock(return_value={"study_block_minutes": "60", "study_block_hour": "19", "calendar_reminder_minutes": "30"})):
        r1 = asyncio.run(calendar_hub.plan_study("Lab 3", due.isoformat(), "https://x/a/1"))
        first_uid = created["uid"]
        asyncio.run(calendar_hub.plan_study("Lab 3", due.isoformat(), "https://x/a/1"))
    start = datetime.fromisoformat(r1["start"])
    assert start == evening + timedelta(hours=1)  # the 7 pm slot was busy
    assert created["title"] == "Study: Lab 3" and created["reminder"] == [30]
    assert created["uid"] == first_uid  # planning again moves it, never duplicates


def test_no_study_session_for_past_or_undated_work():
    with patch.object(calendar_hub.apple_calendar, "status", return_value={"configured": True}):
        for due in ("", (datetime.now().astimezone() - timedelta(hours=1)).isoformat()):
            try:
                asyncio.run(calendar_hub.plan_study("Old", due))
                raise AssertionError("should refuse")
            except calendar_hub.CalendarError:
                pass
