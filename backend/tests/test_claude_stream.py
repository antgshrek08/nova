"""Reading Claude Code's stream-json output (providers._claude_stream_text)."""
import asyncio
import json

import pytest

from app import providers


def _run(lines, split=7):
    raw = "".join(json.dumps(line) + "\n" for line in lines)
    async def chunks():  # arbitrary chunk boundaries, like a real pipe
        for i in range(0, len(raw), split):
            yield raw[i:i + split]
    async def collect():
        return [t async for t in providers._claude_stream_text(chunks())]
    return asyncio.run(collect())


def delta(text):
    return {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}}


def test_text_arrives_as_it_is_written_and_the_result_is_not_repeated():
    out = _run([{"type": "system"}, delta("Hel"), delta("lo"), {"type": "result", "result": "Hello", "is_error": False}])
    assert out == ["Hel", "lo"]


def test_final_result_is_used_when_nothing_streamed():
    assert _run([{"type": "result", "result": "Hi", "is_error": False}]) == ["Hi"]


def test_text_after_a_tool_starts_a_new_paragraph():
    start = {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}}
    assert "".join(_run([delta("Checking."), start, delta("Done.")])) == "Checking.\n\nDone."


def test_an_error_result_raises():
    with pytest.raises(providers.ProviderUnavailableError):
        _run([{"type": "result", "result": "usage limit", "is_error": True}])
