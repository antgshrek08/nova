"""When a reasoning model is allowed to deliberate before answering.

Latency on a local model is generation, not prefill: a 3,900-token tool
prompt costs less than 200 generated tokens, because prefill is parallel and
generation is one token at a time. Measured on qwen3.5:4b with "whats 12
percent of 250" -- thinking on, 755 completion tokens in 47.8s; thinking off,
98 tokens in 7.8s, same answer.

So the lever is how much the model writes, and on a simple question almost
all of it is thinking nobody reads. These tests pin which categories keep it,
because the failure mode of getting this wrong is not slowness -- it is a
worse answer to a question that needed the deliberation.
"""
import unittest

from app import providers


class ThinkingByCategory(unittest.TestCase):
    def test_hard_work_keeps_its_thinking(self):
        """The categories where deliberating changes the answer."""
        for category in ("reasoning_math", "coding", "agentic_planning",
                         "long_context", "vision_multimodal", "research"):
            self.assertTrue(providers.wants_thinking(category), category)

    def test_simple_turns_do_not_deliberate(self):
        for category in ("quick_simple", "everyday", "general_writing", "creative_writing"):
            self.assertFalse(providers.wants_thinking(category), category)

    def test_an_unknown_or_missing_category_keeps_thinking(self):
        """The safe default. Losing deliberation on something that needed it
        is a worse answer; keeping it is only slower."""
        for category in (None, "", "something_new"):
            self.assertTrue(providers.wants_thinking(category), repr(category))


class OllamaKwargs(unittest.TestCase):
    def test_think_false_is_sent_for_a_simple_category(self):
        kwargs = providers._litellm_kwargs("ollama", "qwen3.5:4b", "quick_simple")
        self.assertIs(kwargs["think"], False)

    def test_the_field_is_omitted_rather_than_set_true(self):
        """Passing think=True to a model with no thinking mode errors on some
        Ollama builds; omitting it always means "the model's own default"."""
        kwargs = providers._litellm_kwargs("ollama", "qwen3.5:4b", "coding")
        self.assertNotIn("think", kwargs)

    def test_other_providers_are_untouched(self):
        """think is an Ollama concept. OpenRouter and Gemini must not see it."""
        for provider in ("openrouter", "gemini"):
            self.assertNotIn("think", providers._litellm_kwargs(provider, "m", "quick_simple"))

    def test_the_default_call_still_works_without_a_category(self):
        """execution_tools calls this with two arguments."""
        kwargs = providers._litellm_kwargs("ollama", "qwen3.5:4b")
        self.assertNotIn("think", kwargs)
        self.assertEqual(kwargs["model"], "ollama_chat/qwen3.5:4b")


if __name__ == "__main__":
    unittest.main()
