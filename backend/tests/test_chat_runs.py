import asyncio
import time

import pytest

from app import chat_runs


@pytest.fixture(autouse=True)
def clean():
    chat_runs._RUNS.clear()
    yield
    chat_runs._RUNS.clear()


def test_idle_conversation_shows_send():
    assert chat_runs.status(1) == {"conversation_id": 1, "running": False}
    assert chat_runs.running() == []
    assert chat_runs.stop(1)["stopped"] is False


def test_a_running_turn_shows_stop_and_blocks_a_second_send():
    async def main():
        run = chat_runs.reserve(1)
        chat_runs.attach(run)
        assert chat_runs.status(1)["running"] is True
        assert [r["conversation_id"] for r in chat_runs.running()] == [1]
        with pytest.raises(chat_runs.Busy):
            chat_runs.reserve(1)
        chat_runs.reserve(2)  # other conversations are unaffected
        chat_runs.finish(run)
        assert chat_runs.status(1)["running"] is False
        chat_runs.reserve(1)  # sendable again
    asyncio.run(main())


def test_stop_cancels_the_turn_where_it_waits():
    async def turn(run, seen):
        chat_runs.attach(run)
        try:
            await asyncio.sleep(30)  # a slow model or tool
        except asyncio.CancelledError:
            seen.append(chat_runs.stop_requested(run))
            asyncio.current_task().uncancel()
        finally:
            chat_runs.finish(run)
        return "ended cleanly"

    async def main():
        seen = []
        run = chat_runs.reserve(1)
        task = asyncio.create_task(turn(run, seen))
        await asyncio.sleep(0.05)
        assert chat_runs.stop(1)["stopped"] is True
        assert chat_runs.status(1).get("stopping") in (True, None)
        assert await asyncio.wait_for(task, 2) == "ended cleanly"
        assert seen == [True]
        assert chat_runs.status(1)["running"] is False
    asyncio.run(main())


def test_stop_before_the_stream_starts_still_stops_it():
    async def main():
        run = chat_runs.reserve(1)
        chat_runs.stop(1)

        async def turn():
            chat_runs.attach(run)
            await asyncio.sleep(30)

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.create_task(turn()), 2)
    asyncio.run(main())


def test_a_stream_that_never_started_stops_blocking(monkeypatch):
    chat_runs.reserve(1)
    later = time.time() + 60
    monkeypatch.setattr(chat_runs.time, "time", lambda: later)
    assert chat_runs.status(1)["running"] is False
    chat_runs.reserve(1)


def test_finishing_an_old_run_does_not_clear_a_newer_one():
    async def main():
        old = chat_runs.reserve(1)
        chat_runs.attach(old)
        chat_runs._RUNS[1]["task"] = None
        chat_runs._RUNS[1]["started_at"] = 0  # stale, so a new turn can claim it
        new = chat_runs.reserve(1)
        chat_runs.finish(old)
        assert chat_runs._RUNS[1] is new
    asyncio.run(main())


def test_operator_stop_ends_every_running_turn_even_from_another_thread(monkeypatch):
    import threading
    from app import operator_workflows

    monkeypatch.setattr(operator_workflows.store, "put", lambda *a, **k: {"stopped": True})

    async def turn(run, seen):
        chat_runs.attach(run)
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            seen.append(chat_runs.stop_requested(run))
        finally:
            chat_runs.finish(run)

    async def main():
        seen = []
        runs = [chat_runs.reserve(1), chat_runs.reserve(2)]
        tasks = [asyncio.create_task(turn(r, seen)) for r in runs]
        await asyncio.sleep(0.05)
        hotkey = threading.Thread(target=operator_workflows.stop, args=("Stopped with the hotkey.",))
        hotkey.start(); hotkey.join()
        await asyncio.wait_for(asyncio.gather(*tasks), 2)
        assert seen == [True, True]
        assert chat_runs.running() == []
    asyncio.run(main())


def test_agentic_cli_models_sit_out_while_stopped(monkeypatch):
    import types
    from app import agent_loop, operator_workflows, nova_tools, providers

    async def level():
        return "full"
    monkeypatch.setattr(nova_tools, "autonomy_level", level)
    monkeypatch.setattr(operator_workflows, "stopped", lambda: True)
    cli = types.SimpleNamespace(provider="claude_cli", model=None, label="Claude")

    async def first():
        async for event in agent_loop.run([cli], [{"role": "user", "content": "hi"}]):
            return event
    with pytest.raises(providers.ProviderUnavailableError, match="Resume"):
        asyncio.run(first())
