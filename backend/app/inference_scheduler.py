"""Process-wide inference limits shared by teams and normal chat.

Cloud subscriptions get one active request per provider and two active cloud
requests overall.  The leases cover the whole streaming lifetime and are
released on cancellation or generator failure.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar

_GLOBAL_CLOUD_LIMIT = 2
_global_cloud = asyncio.Semaphore(_GLOBAL_CLOUD_LIMIT)
_provider_slots = {
    "claude": asyncio.Semaphore(1),
    "codex": asyncio.Semaphore(1),
    "antigravity": asyncio.Semaphore(1),
}
_held: ContextVar[tuple] = ContextVar("inference_slots", default=())


def provider_family(provider: str) -> str | None:
    value = (provider or "").lower()
    if value.startswith("claude_cli"):
        return "claude"
    if value.startswith("codex_cli"):
        return "codex"
    if value.startswith("antigravity_cli"):
        return "antigravity"
    return None


@asynccontextmanager
async def slot(provider: str):
    """Acquire a provider and global cloud lease, safely reentrant per task."""
    family = provider_family(provider)
    lease = (asyncio.current_task(), family)
    if family is None or lease in _held.get():
        yield
        return
    await _provider_slots[family].acquire()
    try:
        await _global_cloud.acquire()
    except BaseException:
        _provider_slots[family].release()
        raise
    token = _held.set((*_held.get(), lease))
    try:
        yield
    finally:
        _held.reset(token)
        _global_cloud.release()
        _provider_slots[family].release()


def limits() -> dict:
    return {"cloud_total": _GLOBAL_CLOUD_LIMIT, "per_provider": 1}
