import ast
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "app"


def load_fast_path():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {"_TIME_INTENT_RE", "_DATE_INTENT_RE", "_fast_path_answer"}
    body = [node for node in tree.body if getattr(node, "name", None) == "_fast_path_answer" or (isinstance(node, ast.Assign) and any(getattr(t, "id", None) in names for t in node.targets))]
    env = {"re": __import__("re"), "datetime": __import__("datetime").datetime, "os": __import__("os")}
    exec(compile(ast.Module(body=body, type_ignores=[]), "main.py", "exec"), env)
    return env["_fast_path_answer"]


class FastPathChecks(unittest.TestCase):
    def test_clock_questions_are_deterministic(self):
        answer = load_fast_path()("What time is it?")
        self.assertRegex(answer, r"^It’s \d{1,2}:\d{2} [AP]M .+\.$")

    def test_unrelated_text_stays_on_model_path(self):
        self.assertIsNone(load_fast_path()("Tell me about Hermes agents."))

    def test_date_question_is_supported(self):
        self.assertIn("Today is ", load_fast_path()("what date is it?"))

    def test_questions_about_other_times_are_not_hijacked(self):
        for query in ("What time is it in Tokyo?", "What time is it? Explain time zones.", "What day is it tomorrow?", "Write code that says what time is it"):
            with self.subTest(query=query):
                self.assertIsNone(load_fast_path()(query))
