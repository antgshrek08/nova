"""What Nova says when nothing can answer: a next step, not an exception name."""
from types import SimpleNamespace

from app.agent_loop import no_model_reply


def test_a_new_install_is_told_how_to_set_up_a_model():
    text = no_model_reply([], ["local fallback: ConnectError: All connection attempts failed"])
    assert "(nova:settings/Models)" in text
    assert "ConnectError" not in text and "ollama serve" not in text


def test_set_up_models_that_all_failed_are_named_plainly():
    models = [SimpleNamespace(provider="openrouter", label="OpenRouter Free Router"),
              SimpleNamespace(provider="unavailable", label="nothing")]
    text = no_model_reply(models, ["OpenRouter Free Router: ProviderError: 429"])
    assert "OpenRouter Free Router" in text and "nothing" not in text
    assert "(nova:settings/Models)" in text
    assert "ProviderError" not in text
