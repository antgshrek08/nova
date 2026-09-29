"""Classification must not cost more than the answer it is paying for.

Jev (TypeSafe) classifies a message to decide which model should handle it.
That is worth a hosted round trip when a model is about to be chosen, and
worth nothing at all when one is not: "close Discord" is answered locally in
about 30ms by desktop_intents, and "what time is it" from the clock. Asking a
service over the network first would put the slowest step in front of the
fastest ones.

This is invisible until a TypeSafe key is configured -- without one,
classify_async falls straight through to the 0.008ms regex and nobody
notices. So it is pinned here rather than left to be discovered as "Nova got
slower after I added that key".
"""
import asyncio
import unittest
from unittest import mock

from app import classifier, main


def run(coro):
    return asyncio.run(coro)


class ClassificationCost(unittest.TestCase):
    def test_an_already_understood_message_never_calls_the_hosted_classifier(self):
        with mock.patch.object(classifier, "classify_async") as hosted, \
             mock.patch.object(classifier, "classify", return_value="everyday") as cheap:
            category = run(main._category_for("close discord", already_understood=True))
        hosted.assert_not_called()
        cheap.assert_called_once()
        self.assertEqual(category, "everyday")

    def test_an_ordinary_message_does_use_the_hosted_classifier(self):
        async def hosted(_message):
            return "coding"

        with mock.patch.object(classifier, "classify_async", hosted):
            category = run(main._category_for(
                "refactor this module to use async", already_understood=False
            ))
        self.assertEqual(category, "coding")

    def test_the_cheap_path_still_returns_a_real_category(self):
        """The category is stored on the message row, so it cannot be blank
        just because no model was picked."""
        category = run(main._category_for("close discord", already_understood=True))
        self.assertIn(category, classifier.CATEGORIES)


if __name__ == "__main__":
    unittest.main()
