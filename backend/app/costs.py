"""Spend tracking against the daily budget cap.

Phase 2: promoted from Phase 1's in-memory counter to the spend_log table in
SQLite (see db.py), so restarting the app no longer resets today's spend.
"today" is computed by summing spend_log rows for today's date rather than
tracking a rollover in Python -- querying by date makes the "reset" implicit
and needs no explicit day-change check.

Same public surface as the Phase 1 tracker (record/is_over_budget/status),
now all async since they touch the database -- callers (routing.py,
providers.py, main.py) await them.
"""
from __future__ import annotations

from datetime import date as date_cls

from . import config, db


class SpendTracker:
    async def record(self, cost_usd: float, tokens: int, provider: str | None = None) -> None:
        await db.record_spend(cost_usd, tokens, provider)

    async def is_over_budget(self) -> bool:
        status = await self.status()
        return status["over_budget"]

    async def status(self) -> dict:
        today = date_cls.today().isoformat()
        total_cost_usd, total_tokens, call_count = await db.spend_totals_for_day(today)
        settings = await db.get_app_settings()
        try:
            budget = max(0.0, float(settings.get("spend_cap_usd", config.DAILY_BUDGET_USD)))
        except (TypeError, ValueError):
            budget = config.DAILY_BUDGET_USD
        return {
            "date": today,
            "total_cost_usd": round(total_cost_usd, 6),
            "total_tokens": total_tokens,
            "call_count": call_count,
            "daily_budget_usd": budget,
            "remaining_usd": round(max(budget - total_cost_usd, 0.0), 6),
            "over_budget": total_cost_usd >= budget,
        }


tracker = SpendTracker()


# How a provider actually costs money -- which is not the same question as
# what the spend_log says it cost.
#
# claude_cli and codex_cli are flat-rate subscriptions with no per-call price.
# Nova assigns them config.CLI_CALL_COST_ESTIMATE_USD purely so repeated
# escalations still count against a daily cap; that number is a rationing
# device, not a bill. Of the $2.21 recorded on this machine, $2.20 was that
# device and about nine tenths of a cent was real.
#
# Presenting the two as one dollar figure would be a confident, specific,
# believable lie -- so they are separated here rather than summed.
METERED_PROVIDERS = frozenset({"openrouter", "gemini", "custom", "diffusion"})
SUBSCRIPTION_PROVIDERS = frozenset({
    "claude_cli", "claude_cli_plan", "codex_cli", "codex_cli_plan", "antigravity_cli",
})
LOCAL_PROVIDERS = frozenset({"ollama", "hermes"})


def classify(provider: str | None) -> str:
    name = (provider or "").lower()
    if name in METERED_PROVIDERS:
        return "metered"
    if name in SUBSCRIPTION_PROVIDERS:
        return "subscription"
    if name in LOCAL_PROVIDERS:
        return "local"
    return "metered"  # unknown: assume it costs money rather than assume free


async def breakdown(days: int = 30) -> dict:
    """Where the money actually goes, kept separate from where it does not."""
    from datetime import timedelta

    since = (date_cls.today() - timedelta(days=max(0, days - 1))).isoformat()
    providers = await db.spend_by_provider(since)

    groups: dict[str, dict] = {
        kind: {"calls": 0, "tokens": 0, "cost_usd": 0.0, "providers": []}
        for kind in ("metered", "subscription", "local")
    }
    for row in providers:
        kind = classify(row["provider"])
        bucket = groups[kind]
        bucket["calls"] += row["calls"]
        bucket["tokens"] += row["tokens"]
        bucket["cost_usd"] += float(row["cost_usd"])
        bucket["providers"].append({
            "provider": row["provider"],
            "calls": row["calls"],
            "tokens": row["tokens"],
            # Only meaningful for metered providers; carried for the others so
            # the budget view can still show what the rationing counter holds.
            "cost_usd": round(float(row["cost_usd"]), 6),
            "last_used": row["last_used"],
        })

    for bucket in groups.values():
        bucket["cost_usd"] = round(bucket["cost_usd"], 6)

    return {
        "since": since,
        "days": days,
        "real_spend_usd": groups["metered"]["cost_usd"],
        "metered": groups["metered"],
        "subscription": groups["subscription"],
        "local": groups["local"],
        "by_day": await db.spend_by_day(since),
        "note": (
            "Only metered providers cost money per call. Subscription CLIs "
            "(Claude Code, Codex) are flat-rate, and the figure Nova tracks for "
            "them exists to ration a daily cap, not to report a bill. Local "
            "models cost nothing."
        ),
    }
