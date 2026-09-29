"""Any API key by a name (app/custom_keys.py)."""
import os

import pytest

from app import config, custom_keys


@pytest.fixture()
def env(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_PATH", path)
    for k in [k for k in os.environ if k.endswith("_API_KEY") and k.startswith(("MY_", "TOGETHER"))] + [custom_keys.INDEX]:
        monkeypatch.delenv(k, raising=False)
    return path


def test_names_route_to_where_the_key_belongs():
    assert custom_keys.match("Jev") == "typesafe"
    assert custom_keys.match("TypeSafe") == "typesafe"
    assert custom_keys.match("OpenRouter") == "openrouter"
    assert custom_keys.match("Google Gemini") == "gemini"
    assert custom_keys.match("Groq") == "groq"
    assert custom_keys.match("xAI (Grok)") == "xai"
    assert custom_keys.match("my school's AI") is None


def test_unknown_keys_are_kept_by_name_and_only_names_are_listed(env, monkeypatch):
    saved = custom_keys.store("my school AI", "sk-secret-123")
    assert saved["env"] == "MY_SCHOOL_AI_API_KEY"
    assert "MY_SCHOOL_AI_API_KEY=" in env.read_text(encoding="utf-8")
    listed = custom_keys.saved()
    assert listed == [{"env": "MY_SCHOOL_AI_API_KEY", "name": "My School Ai", "set": True}]
    assert "sk-secret" not in str(listed)
    custom_keys.store("my school AI", "sk-other")  # same name: replaced, not duplicated
    assert len(custom_keys.saved()) == 1
    custom_keys.forget("MY_SCHOOL_AI_API_KEY")
    assert custom_keys.saved() == []


def test_a_name_is_required():
    with pytest.raises(ValueError):
        custom_keys.env_name("  ***  ")
