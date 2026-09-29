"""One process-wide local LLM request at a time, including streaming lifetime."""
import asyncio
import inspect
from urllib.parse import urlparse
import litellm

from . import nova_rules

_slot = asyncio.Semaphore(1)


async def completion(**kwargs):
    # The user's rules go first in every request (see nova_rules.py).
    if "messages" in kwargs:
        kwargs["messages"] = nova_rules.apply(kwargs["messages"])
    model = kwargs.get("model", "")
    local = model.startswith(("ollama/", "ollama_chat/")) or urlparse(kwargs.get("api_base") or "").hostname in ("localhost", "127.0.0.1", "::1")
    if not local:
        return await litellm.acompletion(**kwargs)
    if model.startswith(("ollama/", "ollama_chat/")):
        # Bound local GPU residency independently of the number of team roles.
        kwargs.setdefault("num_ctx", 4096)
        kwargs.setdefault("keep_alive", "2m" if model.endswith("qwen3.5:4b") else 0)
        if model.endswith("qwen3.5:4b"):
            kwargs.setdefault("think", False)
    await _slot.acquire()
    try:
        response = await litellm.acompletion(**kwargs)
    except BaseException:
        _slot.release()
        raise
    if not kwargs.get("stream"):
        _slot.release()
        return response

    return _LocalStream(response)


class _LocalStream:
    """Explicit close releases even before the first chunk is consumed."""
    def __init__(self, response):
        self.response = response
        self.iterator = response.__aiter__()
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed:
            raise StopAsyncIteration
        try:
            return await self.iterator.__anext__()
        except BaseException:
            await self.aclose()
            raise

    async def aclose(self):
        if self.closed:
            return
        self.closed = True
        try:
            close = getattr(self.response, "aclose", None)
            if close:
                value = close()
                if inspect.isawaitable(value):
                    await value
        finally:
            _slot.release()
