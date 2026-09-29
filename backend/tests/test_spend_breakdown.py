"""Money and not-money must not be added together.

The spend log records a flat estimate for every Claude Code and Codex call so
repeated escalations count against a daily cap. config.py says it outright:
"not a real billed price". Those CLIs are flat-rate subscriptions.

On this machine that device accounts for $2.20 of a recorded $2.21, while
real metered spend over thirty days was $0.0092. A dashboard summing the two
would report "$2.21 spent" -- confident, specific, believable and wrong,
which is the worst combination and the same failure as telling the user they
had five assignments due when they had twelve.
"""
import asyncio
import unittest
from unittest import mock

from app import costs


def run(coro):
    return asyncio.run(coro)


class Classification(unittest.TestCase):
    def test_metered_providers_cost_money(self):
        for provider in ("openrouter", "gemini", "custom"):
            self.assertEqual(costs.classify(provider), "metered", provider)

    def test_subscription_clis_are_not_metered(self):
        for provider in ("claude_cli", "codex_cli", "claude_cli_plan",
                         "codex_cli_plan", "antigravity_cli"):
            self.assertEqual(costs.classify(provider), "subscription", provider)

    def test_local_models_are_free(self):
        for provider in ("ollama", "hermes"):
            self.assertEqual(costs.classify(provider), "local", provider)

    def test_an_unknown_provider_is_assumed_to_cost_money(self):
        """The safe direction. Under-reporting spend is worse than
        over-reporting it, and a new paid provider must not read as free."""
        for provider in ("some_new_api", "", None):
            self.assertEqual(costs.classify(provider), "metered", repr(provider))


class Breakdown(unittest.IsolatedAsyncioTestCase):
    ROWS = [
        {"provider": "claude_cli", "calls": 29, "cost_usd": 1.45, "tokens": 3548, "last_used": "x"},
        {"provider": "codex_cli", "calls": 15, "cost_usd": 0.75, "tokens": 676, "last_used": "x"},
        {"provider": "openrouter", "calls": 68, "cost_usd": 0.0075, "tokens": 83414, "last_used": "x"},
        {"provider": "gemini", "calls": 10, "cost_usd": 0.0017, "tokens": 455, "last_used": "x"},
        {"provider": "ollama", "calls": 114, "cost_usd": 0.0, "tokens": 64503, "last_used": "x"},
    ]

    async def _breakdown(self):
        with mock.patch.object(costs.db, "spend_by_provider",
                               mock.AsyncMock(return_value=self.ROWS)), \
             mock.patch.object(costs.db, "spend_by_day", mock.AsyncMock(return_value=[])):
            return await costs.breakdown(30)

    async def test_real_spend_excludes_the_rationing_figure(self):
        """The number this whole module exists to get right."""
        result = await self._breakdown()
        self.assertAlmostEqual(result["real_spend_usd"], 0.0092, places=4)

    async def test_the_subscription_figure_is_kept_but_kept_separate(self):
        """Not discarded -- the daily cap still needs it -- just never summed
        into the money figure."""
        result = await self._breakdown()
        self.assertAlmostEqual(result["subscription"]["cost_usd"], 2.20, places=2)
        self.assertEqual(result["subscription"]["calls"], 44)

    async def test_local_work_is_counted_but_costs_nothing(self):
        result = await self._breakdown()
        self.assertEqual(result["local"]["calls"], 114)
        self.assertEqual(result["local"]["cost_usd"], 0.0)

    async def test_every_provider_lands_in_exactly_one_group(self):
        result = await self._breakdown()
        counted = sum(len(result[k]["providers"]) for k in ("metered", "subscription", "local"))
        self.assertEqual(counted, len(self.ROWS))

    async def test_the_note_says_which_number_is_not_a_bill(self):
        result = await self._breakdown()
        self.assertIn("flat-rate", result["note"])


if __name__ == "__main__":
    unittest.main()
