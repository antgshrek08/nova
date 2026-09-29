"""Durable admission limits for director task trees (not account quota estimates)."""
import asyncio
from . import db

SUBSCRIPTIONS = frozenset({'claude_cli', 'codex_cli', 'gemini_cli', 'antigravity_cli', 'claude_cli_plan', 'codex_cli_plan'})
MAX_DISPATCHES = 2
MAX_CONTEXT_CHARS = 24000
_admission = asyncio.Lock()

async def reserve(root_id: int, provider: str, messages: list[dict]) -> None:
    if provider not in SUBSCRIPTIONS:
        return
    if sum(len(str(m.get('content', ''))) for m in messages) > MAX_CONTEXT_CHARS:
        raise RuntimeError('Specialist context exceeds 24,000 characters. Reduce the task context before retrying; nothing was sent.')
    async with _admission:
        events = await db.get_task_activity(root_id)
        used = sum(e['kind'] == 'subscription_dispatch' for e in events)
        if used >= MAX_DISPATCHES:
            raise RuntimeError('Subscription task budget reached (2 specialist dispatches). Work stopped; no paid fallback. Review the results before authorizing more work.')
        # Persist before dispatch, including failed attempts, so retries/restarts
        # cannot silently replenish the allowance. CLI internal calls are separate.
        await db.add_task_activity(root_id, 'subscription_dispatch',
                                   f'{provider}: specialist dispatch {used + 1}/{MAX_DISPATCHES}; includes failed attempts. CLI internal requests are not counted individually.')
