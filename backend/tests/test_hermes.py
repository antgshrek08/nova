import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import hermes


class HermesChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        hermes._turn_lock = asyncio.Lock()
        hermes._sessions.clear()
        hermes._updates.clear()

    async def test_stream_preserves_context_and_finishes(self):
        captured = {}
        async def rpc(method, params, **kwargs):
            if method == "session/new":
                return {"sessionId": "test-session"}
            if method == "session/prompt":
                captured.update(params)
                hermes._updates["test-session"].put_nowait({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "ready"}})
            return {"stopReason": "end_turn"}
        with patch.object(hermes, "start", AsyncMock()), patch.object(hermes, "_rpc", rpc):
            result = [part async for part in hermes.stream([{"role": "system", "content": "Project context"}, {"role": "user", "content": "Hello"}])]
        self.assertEqual(result, ["ready"])
        self.assertIn("Project context", captured["prompt"][0]["text"])
        self.assertFalse(hermes._updates)
        self.assertFalse(hermes._turn_lock.locked())

    async def test_timed_out_prompt_stops_agent_before_releasing_turn(self):
        async def rpc(method, params, **kwargs):
            if method == "session/new":
                return {"sessionId": "test-session"}
            if method == "session/prompt":
                raise TimeoutError("test timeout")
            return {}
        with patch.object(hermes, "start", AsyncMock()), patch.object(hermes, "_rpc", rpc), patch.object(hermes, "stop", AsyncMock()) as stop:
            with self.assertRaises(TimeoutError):
                _ = [part async for part in hermes.stream([{"role": "user", "content": "Hello"}])]
            stop.assert_awaited_once()
        self.assertFalse(hermes._turn_lock.locked())
        self.assertFalse(hermes._updates)

    async def test_closing_stream_stops_active_agent(self):
        async def rpc(method, params, **kwargs):
            if method == "session/new":
                return {"sessionId": "test-session"}
            if method == "session/prompt":
                hermes._updates["test-session"].put_nowait({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "started"}})
                await asyncio.Future()
            return {}
        with patch.object(hermes, "start", AsyncMock()), patch.object(hermes, "_rpc", rpc), patch.object(hermes, "stop", AsyncMock()) as stop:
            stream = hermes.stream([{"role": "user", "content": "Hello"}])
            self.assertEqual(await anext(stream), "started")
            await stream.aclose()
            stop.assert_awaited_once()
        self.assertFalse(hermes._turn_lock.locked())


if __name__ == "__main__":
    unittest.main()
