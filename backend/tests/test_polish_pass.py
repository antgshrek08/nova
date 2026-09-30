"""Stale "Nova working" records, homework discovery on non-Canvas platforms,
the link opener, and the voice list/routing."""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app import chat_runs, config, coursework_queue as queue, homework_discovery as hd, operator_store as store, operator_workflows as workflows


class _TempStore(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(config, "DB_PATH", Path(self.tmp.name) / "test.db")
        p.start()
        self.addCleanup(p.stop)
        # Discovery notifies; that path reads the real settings database.
        p = patch("app.notify.notify", AsyncMock(return_value={}))
        p.start()
        self.addCleanup(p.stop)


class StaleWork(_TempStore):
    async def test_restart_closes_tasks_left_running(self):
        task = await workflows.task("start", url="https://x.test", workflow="demo")
        self.assertEqual(store.get("task", task["id"])["status"], "running")
        self.assertEqual(workflows.close_open_tasks(), 1)
        closed = store.get("task", task["id"])
        self.assertEqual(closed["status"], "interrupted")
        self.assertIn("restarted", closed["summary"])

    async def test_a_chat_turn_ending_closes_only_its_own_tasks(self):
        run = chat_runs.reserve(424242)

        async def turn():
            chat_runs.attach(run)
            return await workflows.task("start", url="https://x.test", workflow="mine")

        mine = await asyncio.create_task(turn())
        other = await workflows.task("start", url="https://x.test", workflow="someone else's")
        chat_runs.finish(run)
        self.assertEqual(store.get("task", mine["id"])["status"], "interrupted")
        self.assertEqual(store.get("task", other["id"])["status"], "running")

    async def test_finished_tasks_are_left_alone(self):
        task = await workflows.task("start", url="https://x.test", workflow="demo")
        await workflows.task("abort", task_id=task["id"], summary="done here")
        workflows.close_open_tasks()
        self.assertEqual(store.get("task", task["id"])["status"], "failed")

    async def test_queue_mid_assignment_at_boot_becomes_check_receipt(self):
        with patch.object(queue.coursework, "read_json", AsyncMock(return_value={"id": "7"})):
            job = queue.create_queue([{"url": "https://s.test/courses/1/assignments/1"}], account_id="7", authorize_submission=True)
        job["state"] = "running"
        job["lease_until"] = time.time() + 999
        job["items"][0]["state"] = "executing"
        store.put(queue.KIND, job["id"], job)
        self.assertEqual(queue.recover_on_boot(), 1)
        after = queue.status(job["id"])
        self.assertEqual(after["items"][0]["state"], "unknown")
        self.assertEqual(after["lease_until"], 0)
        self.assertNotEqual(after["state"], "running")


class Discovery(_TempStore):
    def test_adding_a_platform_uses_its_list_page(self):
        src = hd.add_source("webassign")
        self.assertEqual(src["url"], hd.START_URLS["webassign"])
        self.assertEqual(hd.add_source("webassign")["id"], src["id"])  # no duplicates

    def test_school_lms_needs_its_address_and_live_tools_are_refused(self):
        with self.assertRaises(hd.DiscoveryError):
            hd.add_source("moodle")
        self.assertEqual(hd.add_source(url="https://moodle.school.edu/my/")["portal"], "moodle")
        with self.assertRaises(hd.DiscoveryError):
            hd.add_source("kahoot")
        with self.assertRaises(hd.DiscoveryError):
            hd.add_source("canvas")
        with self.assertRaises(hd.DiscoveryError):
            hd.add_source(url="http://moodle.school.edu/")

    def test_removing_a_platform_removes_what_it_found(self):
        src = hd.add_source("gradescope")
        store.put(hd.ITEM, "abc", {"id": "abc", "source_id": src["id"], "title": "HW 1", "status": "open"})
        hd.remove_source(src["id"])
        self.assertEqual(hd.sources(), [])
        self.assertEqual(hd.items(), [])

    async def test_sign_in_wall_is_reported_not_guessed(self):
        src = hd.add_source("webassign")
        with patch.object(hd, "_read", AsyncMock(return_value={"status": "needs_sign_in", "items": [], "page": "https://x/login"})):
            report = await hd.discover()
        self.assertEqual(report["platforms"][0]["status"], "needs_sign_in")
        self.assertEqual(hd.sources()[0]["last_status"], "needs_sign_in")
        self.assertEqual(hd.items(), [])
        del src

    async def test_found_assignments_are_stored_and_deduplicated(self):
        hd.add_source("gradescope")
        found = [{"title": "Problem Set 3", "url": "https://www.gradescope.com/courses/1/assignments/9", "due_at": None, "due_text": None, "status": "open"}]
        with patch.object(hd, "_read", AsyncMock(return_value={"status": "ok", "items": found, "page": "https://www.gradescope.com/"})):
            await hd.discover()
            await hd.discover()
        rows = hd.items()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["platform"], "Gradescope")

    async def test_discovery_respects_operator_stop(self):
        hd.add_source("gradescope")
        workflows.stop("test")
        with self.assertRaises(ValueError):
            await hd.discover()
        workflows.resume()


def test_extract_reads_assignment_links_by_platform_shape():
    page = "https://www.webassign.net/web/Student/Home.html"
    links = [
        {"href": "https://www.webassign.net/web/Student/Assignment-Responses/last?dep=123", "text": "Section 4.1 Homework",
         "ctx": "Section 4.1 Homework  Due: Oct 2, 2026 11:59 PM"},
        {"href": "https://www.webassign.net/web/Student/Assignment-Responses/last?dep=124", "text": "Section 3.9 Homework",
         "ctx": "Section 3.9 Homework  Submitted 100%"},
        {"href": "https://www.webassign.net/logout", "text": "Log out", "ctx": ""},
        {"href": "https://evil.example/assignment/1", "text": "Assignment 1", "ctx": "Due Oct 3"},
        {"href": "https://www.webassign.net/help", "text": "Help", "ctx": ""},
    ]
    items = hd.extract("webassign", page, links)
    assert [i["title"] for i in items] == ["Section 4.1 Homework", "Section 3.9 Homework"]
    assert items[0]["due_at"].startswith("2026-10-02T23:59")
    assert items[0]["status"] == "open" and items[1]["status"] == "done"
    assert items[0]["url"].endswith("dep=123")  # ids are kept; credentials are not (see the Moodle case)


def test_extract_moodle_and_gradescope_patterns():
    moodle = hd.extract("moodle", "https://moodle.school.edu/my/", [
        {"href": "https://moodle.school.edu/mod/assign/view.php?id=77&sesskey=SECRET", "text": "Lab report 2", "ctx": "Lab report 2 Due Monday, 5 October 2026"},
        {"href": "https://moodle.school.edu/course/view.php?id=5", "text": "BIO 101", "ctx": ""},
    ])
    assert len(moodle) == 1 and moodle[0]["url"].endswith("view.php?id=77")
    assert "SECRET" not in moodle[0]["url"]
    grade = hd.extract("gradescope", "https://www.gradescope.com/", [
        {"href": "https://www.gradescope.com/courses/1/assignments/2", "text": "Midterm corrections", "ctx": "Late Due Date: Oct 9"},
    ])
    assert grade and grade[0]["status"] == "late"


@pytest.mark.parametrize("text,has_due", [("Due: tomorrow", True), ("Due 10/05/2026 11:59 PM", True), ("Available now", False)])
def test_due_dates_only_when_the_page_states_one(text, has_due):
    due_at, _raw = hd._parse_due(text)
    assert bool(due_at) is has_due


def test_signin_wall_detection():
    assert hd._signin_wall("https://login.pearson.com/sso", "")
    assert hd._signin_wall("https://x.test/", "Sign in to continue. Password")
    assert not hd._signin_wall("https://www.gradescope.com/courses", "Your courses")


def test_voice_catalog_routes_online_and_offline():
    from app import fast_speech
    assert fast_speech.neural_voice("ava") == "en-US-AvaNeural"
    assert fast_speech.neural_voice("en-GB-SoniaNeural") == "en-GB-SoniaNeural"
    assert fast_speech.neural_voice("default") is None
    assert fast_speech.neural_voice("2") is None


def test_voice_list_offers_online_offline_and_cloned():
    from app import fast_speech, main
    with patch.object(main.db, "list_tts_voices", AsyncMock(return_value=[{"id": 5, "name": "Mine"}])),             patch.object(fast_speech, "offline_ready", return_value=True):
        voices = asyncio.run(main.list_tts_voices())["voices"]
    kinds = {v["kind"] for v in voices}
    assert {"online", "offline", "cloned"} <= kinds
    assert any(v["id"] == "default" and "offline" in v["name"].lower() for v in voices)


def test_offline_voice_is_listed_only_when_installed_and_nova_still_speaks():
    from app import fast_speech, main
    with patch.object(main.db, "list_tts_voices", AsyncMock(return_value=[])),             patch.object(fast_speech, "offline_ready", return_value=False):
        voices = asyncio.run(main.list_tts_voices())["voices"]
    assert not any(v["id"] == "default" for v in voices)
    spoken = []

    async def edge(text, voice=None, **_pace):
        spoken.append(voice)
        return b"x" * 200
    with patch.object(fast_speech, "offline_ready", return_value=False),             patch.object(fast_speech, "_synthesize_edge", edge):
        assert asyncio.run(fast_speech.synthesize("Hello there.", voice="default"))
    assert spoken == ["ava"]


def test_open_link_refuses_non_web_and_defaults_to_the_users_browser():
    from fastapi import HTTPException
    from app import main
    with pytest.raises(HTTPException) as refused:
        asyncio.run(main.open_link(main.OpenLinkRequest(url="file:///C:/secret.txt")))
    assert refused.value.status_code == 400
    with patch.object(main.db, "get_app_settings", AsyncMock(return_value={"link_target": "system"})):
        assert asyncio.run(main.open_link(main.OpenLinkRequest(url="https://example.com")))["handled"] is False
