"""An incomplete MCP tool roster must not be cached like a complete one.

Nova warms the tool roster at startup so the first message does not pay ~30s
of MCP connections. That warm-up races the MCP servers Electron launches
separately: the first build found both Google Workspace servers not yet
listening, contributed 0 of their 44 tools, and cached that for five minutes.
For five minutes after every launch Nova had no Gmail or Calendar tools while
Settings showed both servers connected, and nothing anywhere said otherwise.

Two properties are pinned here. A build where any server failed is retried
soon rather than held for the full TTL, and every server's outcome is
recorded so the failure is visible instead of silent.
"""
import asyncio
import unittest
from unittest import mock

from app import mcp_manager


def run(coro):
    return asyncio.run(coro)


class PartialRosterIsRetried(unittest.TestCase):
    def setUp(self):
        mcp_manager.invalidate_roster()
        mcp_manager._last_roster_report.clear()
        self.addCleanup(mcp_manager.invalidate_roster)
        self.addCleanup(mcp_manager._last_roster_report.clear)

    def _build(self, report, schemas):
        """Stand in for one roster build with a given per-server outcome."""
        async def fake():
            mcp_manager._last_roster_report.clear()
            mcp_manager._last_roster_report.extend(report)
            return schemas, {s: s for s in schemas}
        return fake

    def test_a_complete_roster_is_held_for_the_full_ttl(self):
        report = [{"id": 1, "name": "Good", "seconds": 1.0, "tools": 3, "ok": True, "error": None}]
        with mock.patch.object(mcp_manager, "enabled_tools_for_chat", self._build(report, ["a", "b", "c"])):
            run(mcp_manager.cached_tools_for_chat())
        self.assertFalse(mcp_manager._roster_cache["partial"])

        # A second call inside the TTL must not rebuild.
        with mock.patch.object(mcp_manager, "enabled_tools_for_chat") as again:
            schemas, _ = run(mcp_manager.cached_tools_for_chat())
        again.assert_not_called()
        self.assertEqual(len(schemas), 3)

    def test_a_partial_roster_is_rebuilt_soon(self):
        """The bug: a build missing a server was kept for the full 300s."""
        report = [
            {"id": 1, "name": "Good", "seconds": 1.0, "tools": 3, "ok": True, "error": None},
            {"id": 2, "name": "Google Workspace", "seconds": 2.3, "tools": 0,
             "ok": False, "error": "did not connect"},
        ]
        with mock.patch.object(mcp_manager, "enabled_tools_for_chat", self._build(report, ["a"])):
            run(mcp_manager.cached_tools_for_chat())
        self.assertTrue(mcp_manager._roster_cache["partial"])

        # Age it past the short TTL but nowhere near the full one.
        mcp_manager._roster_cache["at"] -= mcp_manager._PARTIAL_ROSTER_TTL_SECONDS + 1
        self.assertLess(
            mcp_manager._PARTIAL_ROSTER_TTL_SECONDS + 1,
            mcp_manager._ROSTER_TTL_SECONDS,
            "the short TTL has to be shorter, or this test proves nothing",
        )

        recovered = [{"id": 1, "name": "Good", "seconds": 1.0, "tools": 3, "ok": True, "error": None},
                     {"id": 2, "name": "Google Workspace", "seconds": 1.1, "tools": 22,
                      "ok": True, "error": None}]
        with mock.patch.object(mcp_manager, "enabled_tools_for_chat",
                               self._build(recovered, ["a", "b", "c", "d"])):
            run(mcp_manager.cached_tools_for_chat())
            # The stale-but-usable path refreshes behind the request, so let
            # the background task finish before asserting on the result.
            run(asyncio.sleep(0))
            if mcp_manager._roster_refresh is not None:
                run(asyncio.wait_for(asyncio.shield(mcp_manager._roster_refresh), 5))

        self.assertFalse(mcp_manager._roster_cache["partial"])
        self.assertEqual(len(mcp_manager._roster_cache["schemas"]), 4)

    def test_every_server_outcome_is_recorded(self):
        """Silence was the original failure: a server that did not answer was
        skipped with no log, no status, and no count anywhere."""
        report = [
            {"id": 1, "name": "Fine", "seconds": 0.9, "tools": 12, "ok": True, "error": None},
            {"id": 2, "name": "Broken", "seconds": 60.0, "tools": 0, "ok": False,
             "error": "no response in 60s"},
        ]
        with mock.patch.object(mcp_manager, "enabled_tools_for_chat", self._build(report, ["a"])):
            run(mcp_manager.cached_tools_for_chat())
        recorded = mcp_manager.last_roster_report()
        self.assertEqual(len(recorded), 2)
        self.assertEqual([e["name"] for e in recorded if not e["ok"]], ["Broken"])

    def test_the_report_is_a_copy(self):
        """Callers must not be able to edit Nova's own diagnostics."""
        mcp_manager._last_roster_report.append(
            {"id": 1, "name": "X", "seconds": 0.0, "tools": 0, "ok": True, "error": None}
        )
        mcp_manager.last_roster_report().clear()
        self.assertEqual(len(mcp_manager.last_roster_report()), 1)


if __name__ == "__main__":
    unittest.main()
