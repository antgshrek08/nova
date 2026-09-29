"""Nova finding out whether it has broken itself.

Nova can already edit its own source. This is the step that makes doing so
defensible rather than reckless: without it, an agent changing the program it
is currently running is just hoping.

So the property that matters is not "can it run pytest" -- it is that a
failure comes back as something actionable. A summary the model cannot read,
or a pass reported when the suite failed, would be worse than no tool.
"""
import asyncio
import unittest
from unittest import mock

from app import selfcheck


def run(coro):
    return asyncio.run(coro)


class _Process:
    def __init__(self, output: str, code: int):
        self._output, self.returncode = output.encode(), code

    async def communicate(self):
        return self._output, b""


def _with_output(output: str, code: int, pattern=None):
    async def fake_exec(*args, **kwargs):
        fake_exec.command = args
        return _Process(output, code)

    with mock.patch.object(selfcheck.asyncio, "create_subprocess_exec", fake_exec), \
         mock.patch.object(selfcheck, "_python", return_value=mock.Mock(is_file=lambda: True)):
        result = run(selfcheck.run_tests(pattern))
    return result, getattr(fake_exec, "command", ())


class Reporting(unittest.TestCase):
    def test_a_passing_run_is_reported_as_passing(self):
        result, _ = _with_output("....\n222 passed, 4 subtests passed in 25.69s\n", 0)
        self.assertTrue(result["ok"])
        self.assertTrue(result["passed"])
        self.assertEqual(result["failure_count"], 0)
        self.assertIn("222 passed", result["summary"])

    def test_a_passing_run_does_not_return_the_whole_log(self):
        """The point is that the model does not read 4,000 lines to learn one
        number."""
        result, _ = _with_output("\n".join(f"line {i}" for i in range(500)) + "\n9 passed\n", 0)
        self.assertEqual(result["output_tail"], "")

    def test_failures_are_named(self):
        output = (
            "FAILED tests/test_video.py::CaptionParsing::test_rolling - AssertionError: x != y\n"
            "FAILED tests/test_ship.py::Blockers::test_ready - KeyError: 'git'\n"
            "2 failed, 220 passed in 26.0s\n"
        )
        result, _ = _with_output(output, 1)
        self.assertFalse(result["passed"])
        self.assertEqual(result["failure_count"], 2)
        self.assertIn("test_rolling", result["failures"][0]["test"])
        self.assertIn("AssertionError", result["failures"][0]["reason"])

    def test_a_failing_run_returns_enough_log_to_act_on(self):
        """A failure the model cannot see is a failure it cannot fix."""
        output = "\n".join(f"line {i}" for i in range(200)) + "\nFAILED tests/a.py::b - boom\n1 failed\n"
        result, _ = _with_output(output, 1)
        self.assertTrue(result["output_tail"])
        self.assertIn("1 failed", result["output_tail"])

    def test_collection_errors_count_as_failures(self):
        """A suite that cannot even import is not a pass."""
        output = "ERROR tests/test_x.py - ImportError: no module named y\n1 error in 0.4s\n"
        result, _ = _with_output(output, 1)
        self.assertFalse(result["passed"])
        self.assertEqual(result["failure_count"], 1)


class Invocation(unittest.TestCase):
    def test_a_pattern_is_passed_to_pytest(self):
        _, command = _with_output("1 passed\n", 0, pattern="test_video")
        self.assertIn("-k", command)
        self.assertIn("test_video", command)

    def test_no_pattern_runs_everything(self):
        _, command = _with_output("1 passed\n", 0)
        self.assertNotIn("-k", command)

    def test_a_missing_environment_is_reported_not_raised(self):
        with mock.patch.object(selfcheck, "_python", return_value=mock.Mock(is_file=lambda: False)):
            result = run(selfcheck.run_tests())
        self.assertFalse(result["ok"])
        self.assertIn("Python environment", result["error"])

    def test_a_hung_suite_times_out_rather_than_blocking_forever(self):
        async def never(*args, **kwargs):
            raise asyncio.TimeoutError()

        with mock.patch.object(selfcheck.asyncio, "create_subprocess_exec", never), \
             mock.patch.object(selfcheck, "_python", return_value=mock.Mock(is_file=lambda: True)):
            result = run(selfcheck.run_tests())
        self.assertFalse(result["ok"])
        self.assertIn("did not finish", result["error"])


if __name__ == "__main__":
    unittest.main()
