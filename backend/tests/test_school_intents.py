"""Coursework questions answered from rows, not by a model.

Nova was given the true figures in its prompt -- "0 due today, 12 in the next
7 days. Use these numbers; do not estimate your own" -- and told the user
five. A wrong deadline count is the most damaging thing this assistant can
say: it sounds exactly like the truth, and it is about the thing it is
actually relied on for.

The refusals matter as much as the matches. "Help me with my homework" and
"what should I work on first" are not lookups, and answering them from a
table would be worse than slower.
"""
import asyncio
import unittest
from datetime import datetime, timedelta
from unittest import mock

from app import school_intents


def run(coro):
    return asyncio.run(coro)


def _rows(*offsets_and_titles):
    """Assignment rows due N days from today."""
    today = datetime.now().astimezone()
    return [
        {"canvas_id": str(i), "title": title, "course_name": "MAC2311",
         "due_at": (today + timedelta(days=offset)).replace(hour=23, minute=59).isoformat()}
        for i, (offset, title) in enumerate(offsets_and_titles)
    ]


class Matching(unittest.TestCase):
    def test_the_plain_phrasings_are_recognised(self):
        for message, label in (
            ("whats due today", "today"),
            ("what is due today", "today"),
            ("anything due tomorrow", "tomorrow"),
            ("whats due this week", "this week"),
            ("what do i have due", "this week"),
            ("what assignments are due", "this week"),
            ("when is my homework due", "this week"),
        ):
            found = school_intents.match(message)
            self.assertIsNotNone(found, message)
            self.assertEqual(found["label"], label, message)

    def test_a_bare_due_question_defaults_to_the_week(self):
        """Not the whole remaining semester, which is 107 rows."""
        self.assertEqual(school_intents.match("whats due")["days"], 7)

    def test_requests_for_help_go_to_the_model(self):
        for message in (
            "help me with my homework",
            "how do i start the calc assignment",
            "explain the chain rule",
            "what should i work on first",
            "summarize whats due",
            "write my essay thats due friday",
            "im tired of doing homework",
            "break down my homework",
        ):
            self.assertIsNone(school_intents.match(message), message)

    def test_unrelated_questions_are_left_alone(self):
        for message in ("what time is it", "close discord", "hello", "", "what's the weather"):
            self.assertIsNone(school_intents.match(message), message)


class Answers(unittest.TestCase):
    def _answer(self, rows, window):
        with mock.patch.object(school_intents.db, "list_canvas_assignments",
                               mock.AsyncMock(return_value=rows)):
            return run(school_intents.answer(window))

    def test_an_empty_day_says_so_plainly(self):
        said = self._answer(_rows((5, "Later thing")), {"days": 0, "label": "today"})
        self.assertEqual(said, "Nothing due today.")

    def test_the_count_is_the_real_count(self):
        """The bug this exists for: twelve reported as five."""
        rows = _rows(*[(1, f"Thing {i}") for i in range(12)])
        said = self._answer(rows, {"days": 7, "label": "this week"})
        self.assertIn("12", said)
        self.assertNotIn("five", said.lower())

    def test_a_single_day_is_not_named_twice(self):
        """The first version said "3 tomorrow -- 3 tomorrow"."""
        said = self._answer(_rows((1, "A"), (1, "B"), (1, "C")), {"days": 7, "label": "this week"})
        self.assertEqual(said.lower().count("tomorrow"), 1, said)

    def test_one_item_reads_as_one_item(self):
        said = self._answer(_rows((1, "Chapter 5 Quiz")), {"days": 7, "label": "this week"})
        self.assertIn("One thing", said)
        self.assertIn("Chapter 5 Quiz", said)

    def test_a_repeated_title_is_said_once(self):
        """Canvas repeats the module name in the assignment name, so titles
        arrive as "3.6 The Chain Rule The Chain Rule" -- a stutter out loud."""
        said = self._answer(_rows((1, "3.6 The Chain Rule The Chain Rule")),
                            {"days": 7, "label": "this week"})
        self.assertIn("3.6 The Chain Rule", said)
        self.assertEqual(said.count("The Chain Rule"), 1, said)

    def test_undated_and_past_work_is_not_counted(self):
        rows = _rows((-3, "Overdue"), (1, "Real"))
        rows.append({"canvas_id": "x", "title": "No date", "course_name": "X", "due_at": None})
        said = self._answer(rows, {"days": 7, "label": "this week"})
        self.assertIn("One thing", said)
        self.assertIn("Real", said)

    def test_small_counts_are_words(self):
        """Read aloud, "three" and "3" are not the same thing."""
        said = self._answer(_rows((1, "A"), (1, "B"), (1, "C")), {"days": 7, "label": "this week"})
        self.assertTrue(said.lower().startswith("three"), said)


class TitleCleaning(unittest.TestCase):
    """Canvas repeats the module name inside the assignment name."""

    def test_a_trailing_repeat_is_dropped(self):
        self.assertEqual(
            school_intents.clean_title({"title": "3.6 The Chain Rule The Chain Rule"}),
            "3.6 The Chain Rule",
        )

    def test_a_repeat_in_the_middle_keeps_what_follows_it(self):
        """The part after the repeat is what distinguishes this assignment
        from the other five with the same module name."""
        raw = ("3.9a Derivatives of Exponential and Logarithmic Functions "
               "Derivatives of Exponential and Logarithmic Functions with Bases other than e")
        self.assertEqual(
            school_intents.clean_title({"title": raw}),
            "3.9a Derivatives of Exponential and Logarithmic Functions with Bases other than e",
        )

    def test_titles_without_repeats_are_untouched(self):
        for title in ("Exam 1: Paleolithic through Ancient Egypt",
                      "Chapter 6 Elasticity Exercises",
                      "Ch 6 SmartBook",
                      "Writing Assignment: Art Experience and Analysis"):
            self.assertEqual(school_intents.clean_title({"title": title}), title)

    def test_a_genuine_repeated_word_is_not_eaten(self):
        """Only a repeated phrase of two or more words collapses; "had had"
        and "the the" are someone's typo, not Canvas's duplication."""
        self.assertEqual(
            school_intents.clean_title({"title": "Paper on had had in English"}),
            "Paper on had had in English",
        )

    def test_speech_still_gets_a_length_limit(self):
        long_title = "Word " * 40
        self.assertLessEqual(len(school_intents.clean_title({"title": long_title}, 70)), 70)


if __name__ == "__main__":
    unittest.main()
