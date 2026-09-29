"""Which spoken commands skip the model, and -- more importantly -- which don't.

"Close Discord" measured 63 seconds end to end, about 47 of which were a 4B
local model prefilling a 13,000-token tool prompt to choose the one obvious
call. This path removes that.

The interesting half of these tests is the refusals. A false positive here
does something to the user's real desktop that they did not ask for, and a
wrong action is far worse than a slow one -- so anything carrying a
conjunction, a question, a condition, or a multi-word target has to fall
through to the model no matter how command-shaped it looks.
"""
import unittest

from app import desktop_intents


class Matches(unittest.TestCase):
    def test_close_uses_the_graceful_window_close(self):
        """Not kill_process: terminating gives the app no chance to save, and
        "close Discord" asks for a window to close, not a process killed."""
        intent = desktop_intents.match("close discord")
        self.assertEqual(intent["tool"], "close_window")
        self.assertEqual(intent["arguments"], {"title_contains": "discord"})
        # The exact wording rotates on purpose, so assert what must be true of
        # any of them rather than pinning one phrasing.
        self.assertIn("Discord", intent["confirmation"])

    def test_kill_is_the_only_way_to_get_the_forceful_one(self):
        self.assertEqual(desktop_intents.match("kill spotify")["tool"], "kill_process")
        self.assertEqual(desktop_intents.match("force quit spotify")["tool"], "kill_process")

    def test_open_maps_to_open_app(self):
        intent = desktop_intents.match("open spotify")
        self.assertEqual(intent["tool"], "open_app")
        self.assertEqual(intent["arguments"], {"path": "spotify"})

    def test_wake_word_and_politeness_are_stripped(self):
        for phrasing in (
            "hey nova close discord",
            "nova, close discord",
            "please close discord",
            "Close Discord.",
            "close discord please",
            "close the discord app",
        ):
            intent = desktop_intents.match(phrasing)
            self.assertIsNotNone(intent, phrasing)
            self.assertEqual(intent["tool"], "close_window", phrasing)
            self.assertEqual(intent["arguments"]["title_contains"].lower(), "discord", phrasing)

    def test_asking_what_is_open_is_read_only_and_needs_no_confirmation_text(self):
        intent = desktop_intents.match("what windows are open")
        self.assertEqual(intent["tool"], "list_windows")
        self.assertIsNone(intent["confirmation"])


class Wording(unittest.TestCase):
    """These strings are Nova's voice for the commands that skip the model."""

    def test_the_same_command_does_not_answer_identically_every_time(self):
        said = {desktop_intents.match("close discord")["confirmation"] for _ in range(4)}
        self.assertGreater(len(said), 1)

    def test_every_phrasing_names_the_target_and_stays_short(self):
        for _ in range(8):
            line = desktop_intents.match("close discord")["confirmation"]
            self.assertIn("Discord", line)
            self.assertLess(len(line), 40, line)

    def test_a_target_that_is_already_capitalised_keeps_its_shape(self):
        """.capitalize() would turn "VS Code" into "Vs code"."""
        self.assertIn("VS Code", desktop_intents.match("open VS Code")["confirmation"])


class Refusals(unittest.TestCase):
    """Everything here must reach the model. Being slow is the safe outcome."""

    def test_anything_with_a_second_clause_is_refused(self):
        for message in (
            "close discord and open spotify",
            "close discord then tell me the time",
            "close discord after the download finishes",
            "close discord if it is still running",
            "close discord but leave chrome",
            "close discord because it is using memory",
        ):
            self.assertIsNone(desktop_intents.match(message), message)

    def test_questions_are_refused(self):
        for message in (
            "should I close discord?",
            "how do I close discord",
            "why is discord open",
            "can you explain what closing discord does",
            "what happens if I close discord",
        ):
            self.assertIsNone(desktop_intents.match(message), message)

    def test_a_sentence_shaped_target_is_refused(self):
        for message in (
            "open the file I was editing",
            "close every window except chrome",
            "open the project folder from yesterday",
        ):
            self.assertIsNone(desktop_intents.match(message), message)

    def test_project_commands_are_left_to_their_own_handlers(self):
        """main.py already handles these; matching them here would shadow it."""
        for message in ("start localhost", "open nova source", "open this website"):
            self.assertIsNone(desktop_intents.match(message), message)

    def test_unrelated_messages_are_refused(self):
        for message in (
            "", "   ", "hello", "what time is it",
            "write me an essay about closing doors",
            "close" ,
            "I had to close my bank account and open a new one somewhere else",
        ):
            self.assertIsNone(desktop_intents.match(message), message)

    def test_a_long_message_is_refused_even_if_it_starts_like_a_command(self):
        message = "close discord " + "x" * 80
        self.assertIsNone(desktop_intents.match(message))


if __name__ == "__main__":
    unittest.main()
