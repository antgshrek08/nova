"""Agents the user sets up (app/crew.py)."""
import asyncio
import json
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest

from app import crew, operator_store


@pytest.fixture()
def store(monkeypatch):
    rows = {}

    class Conn:
        def execute(self, sql, params):
            rows.pop((params[0], params[1]), None)

        def executemany(self, sql, seq):
            for p in seq:
                self.execute(sql, p)

    @contextmanager
    def transaction():
        yield Conn()

    monkeypatch.setattr(operator_store, "get", lambda kind, key, connection=None: rows.get((kind, key)))
    monkeypatch.setattr(operator_store, "put", lambda kind, key, value, connection=None: rows.__setitem__((kind, key), value))
    monkeypatch.setattr(operator_store, "listing", lambda kind: [v for (k, _), v in rows.items() if k == kind])
    monkeypatch.setattr(operator_store, "transaction", transaction)
    return rows


def ts(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi).astimezone().timestamp()


def test_schedules_fire_at_the_right_local_times():
    wed_10am = ts(2026, 9, 30, 10, 0)  # a Wednesday
    assert crew.next_run({"kind": "daily", "time": "09:00"}, wed_10am) == ts(2026, 10, 1, 9, 0)
    assert crew.next_run({"kind": "daily", "time": "11:30"}, wed_10am) == ts(2026, 9, 30, 11, 30)
    fri_6pm = ts(2026, 10, 2, 18, 0)
    assert crew.next_run({"kind": "weekdays", "time": "08:00"}, fri_6pm) == ts(2026, 10, 5, 8, 0)  # Monday
    assert crew.next_run({"kind": "weekly", "time": "08:00", "day": 6}, wed_10am) == ts(2026, 10, 4, 8, 0)  # Sunday
    assert crew.next_run({"kind": "hourly", "every_hours": 3}, wed_10am) == wed_10am + 3 * 3600
    assert crew.next_run({"kind": "once", "at": wed_10am - 60}, wed_10am) is None
    assert crew.next_run({"kind": "none"}, wed_10am) is None


def test_schedule_descriptions_are_short():
    assert crew.describe_schedule({"kind": "weekdays", "time": "08:30"}) == "Weekdays at 8:30 AM"
    assert crew.describe_schedule({"kind": "hourly", "every_hours": 1}) == "Every hour"
    assert crew.describe_schedule({"kind": "none"}) == "When you start it"


def test_bad_schedules_are_refused_plainly(store):
    with pytest.raises(crew.CrewError):
        crew.create_agent("x", "do it", {"kind": "daily", "time": "25:00"})
    with pytest.raises(crew.CrewError):
        crew.create_agent("x", "", {"kind": "none"})


def test_agents_are_created_paused_edited_and_deleted(store):
    a = crew.create_agent("", "Summarize my Canvas assignments due this week. Keep it short.", {"kind": "daily", "time": "07:00"})
    assert a["name"] == "Summarize my Canvas assignments due…" or len(a["name"]) <= 40
    assert a["next_run_at"]
    paused = crew.update_agent(a["id"], enabled=False)
    assert paused["next_run_at"] is None
    view = crew.overview()
    assert view["agents"][0]["state"] == "paused" and view["agents"][0]["when"] == "Every day at 7:00 AM"
    crew.delete_agent(a["id"])
    assert crew.agents() == []


def test_runs_are_grouped_without_a_failed_pile(store):
    a = crew.create_agent("Digest", "Write a digest")
    for i, status in enumerate(["done", "interrupted", "interrupted", "working"]):
        crew._save_run({"id": f"r{i}", "agent_id": a["id"], "agent_name": "Digest", "status": status, "started_at": i})
    view = crew.overview()
    assert [r["id"] for r in view["working"]] == ["r3"]
    assert [r["id"] for r in view["unfinished"]] == ["r2"]  # only the latest unfinished per agent
    assert view["finished"] == [] and view["finished_count"] == 1
    assert [r["id"] for r in crew.overview(show_finished=True)["finished"]] == ["r0"]


def test_cheapest_capable_model(monkeypatch):
    from app import classifier, providers, routing
    available = {"claude_cli:haiku", "claude_cli:sonnet"}
    monkeypatch.setattr(routing, "resolve_model_id", lambda mid, cat, trace: _async(object() if mid in available or mid.startswith("ollama:") else None))
    monkeypatch.setattr(providers, "get_local_ollama_models", lambda: _async([SimpleNamespace(id="qwen3.5:4b"), SimpleNamespace(id="qwen2.5:7b")]))
    monkeypatch.setattr(classifier, "classify", lambda text: "general_writing")
    assert asyncio.run(crew.pick_model("Write a short poem about autumn"))[0] == "ollama:qwen2.5:7b"
    assert asyncio.run(crew.pick_model("Search the web for AI news and write a digest"))[0] == "claude_cli:haiku"
    monkeypatch.setattr(classifier, "classify", lambda text: "coding")
    assert asyncio.run(crew.pick_model("Review the git diff"))[0] == "claude_cli:sonnet"


def _async(value):
    async def f():
        return value
    return f()


def test_a_run_goes_through_chat_and_can_be_resumed(store, monkeypatch):
    from app import db, main
    monkeypatch.setattr(db, "create_conversation", lambda **kw: _async({"id": 77}))
    replies = iter([
        [{"type": "meta", "label": "Claude (haiku)"}, {"type": "token", "content": "Half"}, {"type": "error", "message": "Rate limited"}],
        [{"type": "token", "content": "All done. Sent the digest."}, {"type": "done"}],
    ])

    async def fake_chat(body):
        events = next(replies)
        async def body_iter():
            for e in events:
                yield json.dumps(e) + "\n"
        return SimpleNamespace(body_iterator=body_iter())

    monkeypatch.setattr(main, "chat", fake_chat)
    monkeypatch.setattr(crew, "_tell", lambda run: _async(None))

    async def scenario():
        a = crew.create_agent("Digest", "Write a digest", model="claude_cli:haiku")
        run = await crew.start(a["id"])
        await asyncio.sleep(0.05)
        first = crew.get_run(run["id"])
        assert first["status"] == "interrupted" and "Rate limited" in first["error"]
        assert crew.overview()["unfinished"][0]["id"] == run["id"]
        await crew.resume(run["id"])
        await asyncio.sleep(0.05)
        done = crew.get_run(run["id"])
        assert done["status"] == "done" and done["summary"].startswith("All done")
        assert crew.get_agent(a["id"])["last_status"] == "done"

    asyncio.run(scenario())


def test_runs_left_working_when_nova_closed_are_unfinished(store):
    crew._save_run({"id": "r1", "agent_id": "x", "agent_name": "X", "status": "working", "started_at": 1})
    crew.recover_on_boot()
    assert crew.get_run("r1")["status"] == "interrupted"


def test_only_capable_local_models_are_trusted():
    assert crew.good_local_model(["qwen3.5:4b", "gemma3:27b", "qwen3:32b", "dolphincoder:7b", "deepseek-r1:7b"]) is None
    assert crew.good_local_model(["qwen3.5:4b", "llama3.1:8b", "gemma3:12b"]) == "llama3.1:8b"
