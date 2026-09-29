"""Recovery when a provider fails: sanitised errors, and never replaying
a partial answer.

The second half of this used to assert a `can_retry_unavailable` helper in
providers.py that decided whether a failed candidate could be retried. That
function no longer exists, and the guarantee it protected is now enforced
somewhere better: agent_loop tries the next candidate regardless, but tells the
consumer to *discard* whatever the failed one already streamed. Same promise --
a user never sees a partial answer welded to the real one -- without asking
every call site to remember a rule.

So these test the behaviour rather than the old name.
"""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock


class SanitisedErrorTests(unittest.IsolatedAsyncioTestCase):
    """providers.stream_openrouter, loaded in isolation.

    Parsed out of the source rather than imported so the test does not drag in
    litellm, the database and the whole provider stack to check one error path.
    """

    def load(self):
        source = (Path(__file__).resolve().parents[1] / "app/providers.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {"ProviderUnavailableError", "ProviderRateLimitedError", "stream_openrouter"}
        nodes = [n for n in tree.body if getattr(n, "name", None) in names]

        class RateLimit(Exception):
            pass

        missing = RuntimeError("404 raw provider body user_id=private")
        missing.status_code = 404
        env = {
            "asyncio": asyncio,
            "AsyncIterator": __import__("typing").AsyncIterator,
            "litellm": SimpleNamespace(RateLimitError=RateLimit),
            "config": SimpleNamespace(openrouter_api_key=lambda: "test",
                                      OPENROUTER_STREAM_IDLE_TIMEOUT_SECONDS=1),
            "completion": AsyncMock(side_effect=missing),
            "time": SimpleNamespace(time=lambda: 100),
            "_unavailable_free_models": {},
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "providers.py", "exec"), env)
        return env

    async def test_a_missing_free_model_never_leaks_the_raw_provider_body(self):
        env = self.load()
        with self.assertRaises(env["ProviderUnavailableError"]) as caught:
            await anext(env["stream_openrouter"]("removed:free", []))
        # The upstream body carries an internal user id and a bare status code.
        # Neither helps the user and the first is not ours to show.
        self.assertNotIn("private", str(caught.exception))
        self.assertNotIn("404", str(caught.exception))
        self.assertEqual(env["completion"].await_count, 1)
        self.assertEqual(env["completion"].call_args.kwargs["model"], "openrouter/removed:free")

    async def test_a_dead_free_model_is_benched_temporarily_not_permanently(self):
        """OpenRouter's free roster rotates weekly, so a model that 404s today
        may exist next week. It is benched with an expiry rather than removed,
        and the roster filter compares that expiry against the clock."""
        env = self.load()
        with self.assertRaises(env["ProviderUnavailableError"]):
            await anext(env["stream_openrouter"]("removed:free", []))

        benched = env["_unavailable_free_models"]
        self.assertEqual(benched["removed:free"], 1900)     # stubbed now (100) + 1800s

        now = 100
        self.assertGreater(benched["removed:free"], now, "should be excluded right now")
        later = 100 + 1801
        self.assertLessEqual(benched["removed:free"], later, "should be eligible again after the window")


class PartialAnswerTests(unittest.IsolatedAsyncioTestCase):
    """A provider can emit text and *then* fail -- the CLI providers print
    their own error ("OAuth session expired…") as output before raising. That
    text belongs to the failed attempt, not to the answer."""

    async def _run(self, candidates, stream_factory):
        from app import agent_loop, nova_tools, providers

        original_stream = providers.stream_for_result
        original_collect = agent_loop._collect_tools
        original_level = nova_tools.autonomy_level
        original_fallback = agent_loop._local_fallback

        async def no_tools(*_args, **_kwargs):
            return [], {}

        async def dead_fallback(_messages):
            raise RuntimeError("no local model in this test")
            yield  # pragma: no cover - makes this an async generator

        providers.stream_for_result = stream_factory
        agent_loop._collect_tools = no_tools
        nova_tools.autonomy_level = AsyncMock(return_value="full")
        agent_loop._local_fallback = dead_fallback
        try:
            return [event async for event in agent_loop.run(
                candidates, [{"role": "user", "content": "hi"}], enable_tools=False)]
        finally:
            providers.stream_for_result = original_stream
            agent_loop._collect_tools = original_collect
            nova_tools.autonomy_level = original_level
            agent_loop._local_fallback = original_fallback

    @staticmethod
    def candidate(label, provider="openrouter"):
        return SimpleNamespace(provider=provider, model="m", label=label,
                               category="everyday", custom_model_row_id=None)

    async def test_text_from_a_failed_candidate_is_marked_for_discard(self):
        first, second = self.candidate("Broken"), self.candidate("Working")

        def stream_factory(result, _messages):
            async def gen():
                if result.label == "Broken":
                    yield "OAuth session expired"       # the failure, printed as output
                    raise RuntimeError("provider died after emitting text")
                yield "the real answer"
            return gen()

        events = await self._run([first, second], stream_factory)
        kinds = [e["type"] for e in events]
        self.assertIn("reroute", kinds)

        reroute = next(e for e in events if e["type"] == "reroute")
        self.assertTrue(reroute["discard"],
                        "the failed candidate's partial text must be discarded, not kept")
        self.assertEqual(reroute["from"], "Broken")

        # The working candidate still answers, and its text comes after the reroute.
        text = "".join(e["content"] for e in events if e["type"] == "token")
        self.assertIn("the real answer", text)
        self.assertLess(kinds.index("reroute"), len(kinds) - 1)

    async def test_a_reroute_is_announced_so_the_ui_can_correct_the_model_badge(self):
        first, second = self.candidate("Broken"), self.candidate("Working")

        def stream_factory(result, _messages):
            async def gen():
                if result.label == "Broken":
                    raise RuntimeError("down")
                yield "answer"
            return gen()

        events = await self._run([first, second], stream_factory)
        metas = [e for e in events if e["type"] == "meta"]
        self.assertEqual([m["label"] for m in metas], ["Broken", "Working"])
        self.assertFalse(metas[0]["rerouted"])
        self.assertTrue(metas[1]["rerouted"], "the second attempt must be flagged as a reroute")
        self.assertTrue(metas[1]["attempts"], "the reason the first failed should be carried along")

    async def test_every_candidate_failing_still_produces_an_answer_not_a_crash(self):
        """The whole point of the loop: never return 'Failed'."""
        events = await self._run(
            [self.candidate("A"), self.candidate("B")],
            lambda result, _messages: self._always_fails(),
        )
        text = "".join(e["content"] for e in events if e["type"] == "token")
        self.assertTrue(text.strip(), "user must get words back even when everything failed")

    @staticmethod
    async def _always_fails():
        raise RuntimeError("provider unavailable")
        yield  # pragma: no cover - makes this an async generator


if __name__ == "__main__":
    unittest.main()
