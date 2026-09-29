import asyncio
import os
import time

import pytest

from app import local_inference, nova_rules, providers


@pytest.fixture
def rules_file(tmp_path, monkeypatch):
    """A stand-in rules file; the real one holds only the user's own rules."""
    path = tmp_path / "NOVA_RULES.md"
    monkeypatch.setattr(nova_rules, "RULES_PATH", path)
    monkeypatch.setitem(nova_rules._cache, "mtime", None)

    def write(text: str) -> None:
        path.write_text(text, encoding="utf-8")
        stamp = time.time() + len(text)  # a new mtime every write
        os.utime(path, (stamp, stamp))

    return write


def test_the_rules_file_exists():
    assert nova_rules.RULES_PATH.is_file()


def test_nothing_is_added_while_the_file_holds_no_rules(rules_file):
    rules_file("# Nova's Rules\n")
    convo = [{"role": "user", "content": "hi"}]
    assert nova_rules.apply(convo) is convo


def test_nothing_is_added_when_the_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(nova_rules, "RULES_PATH", tmp_path / "gone.md")
    convo = [{"role": "user", "content": "hi"}]
    assert nova_rules.apply(convo) is convo


def test_rules_go_first_exactly_once_and_the_caller_list_is_untouched(rules_file):
    rules_file("# Nova's Rules\n- sample rule")
    convo = [{"role": "system", "content": "persona"}, {"role": "user", "content": "hi"}]
    out = nova_rules.apply(convo)
    assert out[0]["content"].startswith(nova_rules.MARKER)
    assert "- sample rule" in out[0]["content"]
    assert out[1:] == convo
    assert len(convo) == 2
    assert nova_rules.apply(out) is out, "a second layer must not add them again"


def test_an_edit_applies_to_the_next_request(rules_file):
    rules_file("# Nova's Rules\n- first version")
    assert "first version" in nova_rules.rules_message()["content"]
    rules_file("# Nova's Rules\n- the second version")
    assert "the second version" in nova_rules.rules_message()["content"]


def test_tool_loops_and_local_models_get_the_rules(rules_file, monkeypatch):
    rules_file("# Nova's Rules\n- sample rule")
    seen = {}

    async def fake_acompletion(**kwargs):
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(local_inference.litellm, "acompletion", fake_acompletion)
    asyncio.run(local_inference.completion(model="openrouter/x", messages=[{"role": "user", "content": "hi"}]))
    assert seen["messages"][0]["content"].startswith(nova_rules.MARKER)
    assert seen["messages"][1] == {"role": "user", "content": "hi"}


@pytest.mark.parametrize(
    "name",
    ["stream_openrouter", "stream_ollama", "stream_claude_cli", "stream_codex_cli", "stream_gemini_cli",
     "stream_gemini", "stream_custom", "stream_for_result", "run_model_call"],
)
def test_every_provider_path_is_wrapped(name):
    assert getattr(getattr(providers, name), "__nova_rules__", False), f"{name} can reach a model without the rules"


def test_the_cli_models_receive_the_rules_in_their_prompt(rules_file):
    rules_file("# Nova's Rules\n- sample rule")
    messages = nova_rules.apply([{"role": "user", "content": "open canvas"}])
    prompt = providers._format_cli_transcript(messages)
    assert prompt.startswith(nova_rules.MARKER)
    assert prompt.rstrip().endswith("open canvas")
