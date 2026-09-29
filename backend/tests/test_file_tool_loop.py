"""Guardrails on the tool loop's filesystem reach.

Replaces tests written against `providers.run_file_tool_loop`, which no longer
exists -- agent_loop plus nova_tools replaced it. The three guarantees that
mattered are unchanged and are re-asserted here against the current code:

  (a) credential files stay unreadable through tools,
  (b) a mutating action cannot happen in `guarded` autonomy without the user
      actually approving it, and refusing must leave the filesystem untouched,
  (c) a refusal is reported to the model as a result it can read and route
      around, never as a silent no-op or a crash.

There is one deliberate change of subject. The old suite also checked that the
loop refused to start unless the message mentioned files, because the loop was
expensive and opt-in. Tools are now always attached and the decision of whether
to use one belongs to the model, so that gate no longer exists and testing for
it would be testing a design that was removed on purpose.
"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import nova_tools


class CredentialReadTests(unittest.IsolatedAsyncioTestCase):
    """Reads are blocked by name and location regardless of autonomy level.
    This block was left in place deliberately when the password-typing guards
    were removed: those stopped Nova acting on the user's behalf, this stops a
    secret being copied into a prompt, a transcript and a memory index."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_private_keys_and_credential_files_are_refused(self):
        for name in ("id_rsa", "server.pem", "cert.key", "credentials", "store.p12"):
            target = self.root / name
            target.write_text("SECRET MATERIAL", encoding="utf-8")
            outcome = await nova_tools.execute("read_file", {"path": str(target)}, "full")
            self.assertFalse(outcome["ok"], f"{name} should not be readable")
            self.assertNotIn("SECRET MATERIAL", json.dumps(outcome),
                             f"the contents of {name} leaked into the tool result")

    async def test_the_refusal_says_why_rather_than_pretending_the_file_is_missing(self):
        target = self.root / "id_ed25519"
        target.write_text("x", encoding="utf-8")
        outcome = await nova_tools.execute("read_file", {"path": str(target)}, "full")
        self.assertIn("credential", outcome["error"].lower())

    async def test_an_ordinary_file_beside_them_still_reads(self):
        target = self.root / "notes.txt"
        target.write_text("ordinary content", encoding="utf-8")
        outcome = await nova_tools.execute("read_file", {"path": str(target)}, "full")
        self.assertTrue(outcome["ok"], outcome.get("error"))
        self.assertIn("ordinary content", json.dumps(outcome))


class AutonomyGateTests(unittest.IsolatedAsyncioTestCase):
    """`readonly` refuses mutating tools outright; `guarded` requires approval,
    which the agent loop obtains before anything runs."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_readonly_refuses_a_write_and_the_file_is_not_created(self):
        target = self.root / "should_not_exist.txt"
        outcome = await nova_tools.execute(
            "write_file", {"path": str(target), "content": "nope"}, "readonly")
        self.assertFalse(outcome["ok"])
        self.assertFalse(target.exists(), "a refused write must not touch the filesystem")

    async def test_readonly_still_allows_reading(self):
        target = self.root / "readable.txt"
        target.write_text("hello", encoding="utf-8")
        outcome = await nova_tools.execute("read_file", {"path": str(target)}, "readonly")
        self.assertTrue(outcome["ok"], outcome.get("error"))

    def test_the_mutating_set_covers_what_actually_changes_the_world(self):
        for name in ("write_file", "edit_file", "delete_path", "move_path", "run_command",
                     "desktop_type", "desktop_key", "calendar_create_event",
                     "calendar_delete_event", "type_secret"):
            self.assertIn(name, nova_tools.MUTATING_TOOLS, f"{name} should require approval")
        for name in ("read_file", "grep", "glob", "canvas_assignments", "calendar_events"):
            self.assertNotIn(name, nova_tools.MUTATING_TOOLS,
                             f"{name} is read-only and should not prompt")

    def test_guarded_asks_and_readonly_refuses_for_the_same_tool(self):
        self.assertTrue(nova_tools.needs_approval("write_file", "guarded"))
        self.assertFalse(nova_tools.needs_approval("write_file", "full"))
        self.assertFalse(nova_tools.needs_approval("read_file", "guarded"))
        self.assertTrue(nova_tools.refused_by_autonomy("write_file", "readonly"))
        self.assertFalse(nova_tools.refused_by_autonomy("read_file", "readonly"))


class ApprovalInTheLoopTests(unittest.IsolatedAsyncioTestCase):
    """The approval card has to be raised by the agent loop, because only the
    loop can yield UI events. An earlier version awaited approval inside
    nova_tools.execute, where nothing could be shown -- so the request simply
    sat there for the full timeout with the user never asked anything."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = self.root / "guarded.txt"

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def _run_guarded_write(self, answer: str):
        from app import agent_loop, desktop_registry, providers

        call = {"id": "call_1", "type": "function", "function": {
            "name": "write_file",
            "arguments": json.dumps({"path": str(self.target), "content": "written"})}}

        # _stream_once yields ("token", text) pairs and finally ("calls", [...]).
        # Return the call once, then nothing, so the loop asks for approval and
        # then finishes instead of looping to MAX_STEPS.
        served = {"done": False}

        async def fake_stream(_result, _messages, _schemas):
            if served["done"]:
                yield "token", "all done"
                yield "calls", []
                return
            served["done"] = True
            yield "calls", [call]

        async def answer_when_asked(action_id):
            return answer

        events = []
        with patch.object(agent_loop, "_stream_once", fake_stream), \
             patch.object(desktop_registry.registry, "wait_for_response",
                          AsyncMock(side_effect=answer_when_asked)):
            result = type("R", (), {"provider": "openrouter", "model": "m", "label": "L",
                                    "category": "everyday", "custom_model_row_id": None})()
            async for event in agent_loop._run_with_tools(
                    result, [{"role": "user", "content": "write it"}],
                    [{"type": "function", "function": {"name": "write_file", "parameters": {}}}],
                    {}, "guarded"):
                events.append(event)
                if len(events) > 40:
                    break
        return events

    async def test_a_denied_write_never_touches_the_file(self):
        events = await self._run_guarded_write("denied")
        kinds = [e["type"] for e in events]
        self.assertIn("desktop_confirm", kinds, "the user was never shown an approval card")
        self.assertFalse(self.target.exists(), "a denied write must not have run")
        errors = [e for e in events if e.get("type") == "tool_call" and e.get("status") == "error"]
        self.assertTrue(errors, "the model should be told the action was refused")

    async def test_an_approved_write_happens(self):
        await self._run_guarded_write("approved")
        self.assertTrue(self.target.exists(), "an approved write should have run")
        self.assertEqual(self.target.read_text(encoding="utf-8"), "written")

    async def test_the_card_is_raised_before_anything_runs(self):
        events = await self._run_guarded_write("denied")
        kinds = [e["type"] for e in events]
        confirm = kinds.index("desktop_confirm")
        done = [i for i, e in enumerate(events)
                if e.get("type") == "tool_call" and e.get("status") == "done"]
        self.assertTrue(all(i > confirm for i in done),
                        "nothing may complete before the user is asked")


class ToolFailureTests(unittest.IsolatedAsyncioTestCase):
    """A failing tool becomes a result the model can read, not an exception
    that kills the reply."""

    async def test_a_broken_tool_returns_an_error_result_not_a_crash(self):
        outcome = await nova_tools.execute("read_file", {"path": "/definitely/not/here.txt"}, "full")
        self.assertFalse(outcome["ok"])
        self.assertIsInstance(outcome.get("error"), str)
        self.assertTrue(outcome["error"].strip())

    async def test_an_unknown_tool_is_reported_rather_than_raised(self):
        outcome = await nova_tools.execute("no_such_tool", {}, "full")
        self.assertFalse(outcome["ok"])
        self.assertIn("no_such_tool", outcome["error"])


if __name__ == "__main__":
    unittest.main()
