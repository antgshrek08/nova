"""Agents the user sets up: a name, what to do, when, and which model.

An agent runs through the same engine as Chat (its tools, memory, rules and
autonomy level), in a conversation of its own, so every run keeps a full
record and one that didn't finish can pick up where it stopped.

- Scheduled agents start on their own (once, daily, weekdays, weekly, or every
  few hours). A run missed while Nova was closed starts at the next launch.
- "Auto" picks the cheapest model that does the job well: this computer's
  own model for light writing, Claude Haiku for general work, Claude Sonnet
  for code and multi-step work -- never the big, slow model by default.
- Runs that stopped part-way (Nova closed, stopped, or an error) are listed
  under "Didn't finish" with Resume. There is no "failed" pile.

Chat can create, list and start agents through Nova's tools (nova_tools).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime, timedelta

from . import operator_store

logger = logging.getLogger(__name__)

AGENT = "crew_agent"
RUN = "crew_run"
SCHEDULES = ("none", "once", "daily", "weekdays", "weekly", "hourly")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
TICK_SECONDS = 20
KEEP_RUNS = 300

_tasks: dict[str, asyncio.Task] = {}   # run id -> the task running it
_loop_task: asyncio.Task | None = None


class CrewError(Exception):
    """Said plainly to the user."""


# ---------------------------------------------------------------- helpers

def short(text: str, limit: int = 80) -> str:
    """One short line: the first sentence, trimmed."""
    text = re.sub(r"[*_`#>\[\]]+", "", str(text or "")).strip()
    text = re.split(r"(?<=[.!?])\s|\n", text, maxsplit=1)[0].strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _now() -> float:
    return time.time()


def _schedule(raw: dict | None) -> dict:
    s = dict(raw or {})
    kind = s.get("kind") or "none"
    if kind not in SCHEDULES:
        raise CrewError(f"Unknown schedule {kind!r}; use once, daily, weekdays, weekly, hourly or none.")
    out = {"kind": kind}
    if kind in ("daily", "weekdays", "weekly"):
        hhmm = str(s.get("time") or "09:00")
        if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", hhmm):
            raise CrewError("Give the time as HH:MM, like 08:30.")
        out["time"] = hhmm.zfill(5)
    if kind == "weekly":
        day = int(s.get("day", 0))
        if not 0 <= day <= 6:
            raise CrewError("Pick a day of the week.")
        out["day"] = day
    if kind == "hourly":
        every = int(s.get("every_hours") or 1)
        if not 1 <= every <= 168:
            raise CrewError("Every 1 to 168 hours.")
        out["every_hours"] = every
    if kind == "once":
        at = s.get("at")
        if not at:
            raise CrewError("Say when to run it.")
        out["at"] = float(at) if isinstance(at, (int, float)) else datetime.fromisoformat(str(at)).astimezone().timestamp()
    return out


def next_run(schedule: dict, after: float | None = None) -> float | None:
    """When a schedule next fires, as a timestamp (local time), or None."""
    after = _now() if after is None else after
    kind = schedule.get("kind", "none")
    if kind == "none":
        return None
    if kind == "once":
        at = schedule.get("at")
        return at if at and at > after - 1 else None
    if kind == "hourly":
        return after + schedule.get("every_hours", 1) * 3600
    base = datetime.fromtimestamp(after).astimezone()
    hour, minute = (int(x) for x in schedule["time"].split(":"))
    for offset in range(0, 8):
        day = base + timedelta(days=offset)
        at = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at.timestamp() <= after:
            continue
        if kind == "weekdays" and at.weekday() >= 5:
            continue
        if kind == "weekly" and at.weekday() != schedule.get("day", 0):
            continue
        return at.timestamp()
    return None


def describe_schedule(schedule: dict) -> str:
    kind = schedule.get("kind", "none")
    if kind == "none":
        return "When you start it"
    if kind == "once":
        return "Once, " + datetime.fromtimestamp(schedule["at"]).strftime("%b %d at %I:%M %p").replace(" 0", " ")
    if kind == "hourly":
        n = schedule.get("every_hours", 1)
        return "Every hour" if n == 1 else f"Every {n} hours"
    clock = datetime.strptime(schedule["time"], "%H:%M").strftime("%I:%M %p").lstrip("0")
    if kind == "daily":
        return f"Every day at {clock}"
    if kind == "weekdays":
        return f"Weekdays at {clock}"
    return f"{DAYS[schedule.get('day', 0)]}s at {clock}"


# ---------------------------------------------------------------- agents

def agents() -> list[dict]:
    return sorted(operator_store.listing(AGENT), key=lambda a: a.get("created_at", 0))


def get_agent(agent_id: str) -> dict:
    a = operator_store.get(AGENT, agent_id)
    if not a:
        raise CrewError("That agent is gone.")
    return a


def create_agent(name: str, task: str, schedule: dict | None = None, model: str = "auto", created_by: str = "you") -> dict:
    name, task = str(name or "").strip(), str(task or "").strip()
    if not task:
        raise CrewError("Say what the agent should do.")
    name = (name or short(task, 40))[:60]
    sched = _schedule(schedule)
    agent_id = uuid.uuid4().hex[:12]
    row = {"id": agent_id, "name": name, "task": task[:4000], "schedule": sched, "model": model or "auto",
           "enabled": True, "created_by": created_by, "created_at": _now(), "next_run_at": next_run(sched),
           "last_run_at": None, "last_status": None}
    operator_store.put(AGENT, agent_id, row)
    return row


def update_agent(agent_id: str, **changes) -> dict:
    a = get_agent(agent_id)
    for key in ("name", "task", "model"):
        if changes.get(key) is not None:
            a[key] = str(changes[key]).strip()[: 4000 if key == "task" else 60] or a[key]
    if changes.get("schedule") is not None:
        a["schedule"] = _schedule(changes["schedule"])
    if changes.get("enabled") is not None:
        a["enabled"] = bool(changes["enabled"])
    a["next_run_at"] = next_run(a["schedule"]) if a["enabled"] else None
    operator_store.put(AGENT, agent_id, a)
    return a


def delete_agent(agent_id: str) -> None:
    get_agent(agent_id)
    for run in runs():
        if run.get("agent_id") == agent_id and run.get("status") == "working":
            stop(run["id"])
    with operator_store.transaction() as conn:
        conn.execute("DELETE FROM records WHERE kind=? AND id=?", (AGENT, agent_id))


# ---------------------------------------------------------------- the cheapest good model

LIGHT = {"quick_simple", "general_writing", "multilingual"}
HEAVY = {"coding", "frontend_ui_code", "reasoning_math", "agentic_planning", "long_context", "design_review", "vision"}
TOOL_WORDS = re.compile(r"\b(browser|website|open|click|canvas|log ?in|file|folder|download|upload|email|send|"
                        r"calendar|homework|assignment|submit|search|web|online|news|app)\b", re.I)


GENERAL_FAMILIES = ("qwen", "gemma", "llama", "mistral", "phi")


def good_local_model(names: list[str]) -> str | None:
    """A local model worth trusting with an agent's job: a general-purpose
    family (not a coder or a reasoning distill), 7B to 14B -- smaller ones
    wander off-task (a 4B model answered "write one sentence" with a made-up
    bug fix), bigger ones take minutes per run on most computers."""
    picks = []
    for name in names:
        low = name.lower()
        if not low.startswith(GENERAL_FAMILIES) or any(w in low for w in ("coder", "code", "-r1", "tiny", "embed", "vision")):
            continue
        size = re.search(r"[:\-_](\d+(?:\.\d+)?)b\b", low)
        if size and 7 <= float(size.group(1)) <= 14:
            picks.append((float(size.group(1)), name))
    return min(picks)[1] if picks else None


async def pick_model(task: str) -> tuple[str | None, str]:
    """(model id, why) for the cheapest model that can do this task well."""
    from . import classifier, providers, routing
    category = classifier.classify(task)
    options: list[tuple[str, str]] = []
    if category in LIGHT and not TOOL_WORDS.search(task):
        try:
            local = [m.id for m in await providers.get_local_ollama_models()]
        except Exception:  # noqa: BLE001
            local = []
        best = good_local_model(local)
        if best:
            options.append((f"ollama:{best}", "free, on this computer"))
    if category not in HEAVY:
        options.append(("claude_cli:haiku", "fast and inexpensive"))
    options.append(("claude_cli:sonnet", "capable with tools"))
    for model_id, why in options:
        try:
            if await routing.resolve_model_id(model_id, category, []) is not None:
                return model_id, why
        except Exception:  # noqa: BLE001
            continue
    return None, "Nova's usual choice"


# ---------------------------------------------------------------- runs

def runs(limit: int | None = None) -> list[dict]:
    rows = sorted(operator_store.listing(RUN), key=lambda r: r.get("started_at", 0), reverse=True)
    return rows[:limit] if limit else rows


def get_run(run_id: str) -> dict:
    r = operator_store.get(RUN, run_id)
    if not r:
        raise CrewError("That run is gone.")
    return r


def _save_run(run: dict) -> dict:
    operator_store.put(RUN, run["id"], run)
    return run


def _trim_runs() -> None:
    old = runs()[KEEP_RUNS:]
    if old:
        with operator_store.transaction() as conn:
            conn.executemany("DELETE FROM records WHERE kind=? AND id=?", [(RUN, r["id"]) for r in old if r.get("status") != "working"])


async def start(agent_id: str, reason: str = "you") -> dict:
    """Start an agent now. One run at a time per agent."""
    from . import db
    agent = get_agent(agent_id)
    if any(r.get("agent_id") == agent_id and r.get("status") == "working" for r in runs(50)):
        raise CrewError(f"{agent['name']} is already working.")
    model_id, why = (agent["model"], "your choice") if agent.get("model") not in (None, "", "auto") else await pick_model(agent["task"])
    # "projects": a conversation kind the chat list doesn't show, so agent runs
    # don't crowd it -- they open from the Agents screen instead.
    convo = await db.create_conversation(tab="projects", title=f"{agent['name']}")
    run = _save_run({"id": uuid.uuid4().hex[:12], "agent_id": agent_id, "agent_name": agent["name"], "status": "working",
                     "started_at": _now(), "finished_at": None, "conversation_id": convo["id"], "model": model_id,
                     "model_why": why, "reason": reason, "summary": "", "error": ""})
    agent.update(last_run_at=run["started_at"], last_status="working")
    if agent["schedule"]["kind"] == "once" and reason == "schedule":
        agent["enabled"] = False
    agent["next_run_at"] = next_run(agent["schedule"]) if agent.get("enabled") else None
    operator_store.put(AGENT, agent_id, agent)
    prompt = (f"You are running as the agent \"{agent['name']}\", set up by the user. Do this now, fully, "
              f"then finish with a short summary of what you did and anything the user needs to know:\n\n{agent['task']}")
    _launch(run, prompt)
    _trim_runs()
    return run


async def resume(run_id: str) -> dict:
    """Carry on a run that didn't finish, in the same conversation."""
    run = get_run(run_id)
    if run.get("status") == "working":
        raise CrewError("It's still working.")
    if run.get("status") == "done":
        raise CrewError("That run finished. Start the agent again instead.")
    run.update(status="working", finished_at=None, error="", resumed_at=_now())
    _save_run(run)
    _launch(run, "Continue the task from where you stopped. Don't redo what's already done; finish it, then give "
                 "a short summary of what you did.")
    return run


def stop(run_id: str) -> dict:
    run = get_run(run_id)
    task = _tasks.pop(run_id, None)
    if task and not task.done():
        task.cancel()
    try:
        from . import chat_runs
        chat_runs.stop(run["conversation_id"])
    except Exception:  # noqa: BLE001
        pass
    if run.get("status") == "working":
        run.update(status="stopped", finished_at=_now(), error="Stopped by you.")
        _save_run(run)
        _set_last(run)
    return run


def delete_run(run_id: str) -> None:
    run = get_run(run_id)
    if run.get("status") == "working":
        stop(run_id)
    with operator_store.transaction() as conn:
        conn.execute("DELETE FROM records WHERE kind=? AND id=?", (RUN, run_id))


def _set_last(run: dict) -> None:
    agent = operator_store.get(AGENT, run.get("agent_id") or "")
    if agent:
        agent["last_status"] = run["status"]
        operator_store.put(AGENT, agent["id"], agent)


def _launch(run: dict, prompt: str) -> None:
    task = asyncio.create_task(_execute(run["id"], prompt))
    _tasks[run["id"]] = task
    task.add_done_callback(lambda _t, rid=run["id"]: _tasks.pop(rid, None))


async def _execute(run_id: str, prompt: str) -> None:
    """Send the prompt through Chat's engine and record how it ended."""
    import json
    from . import main, schemas
    run = get_run(run_id)
    text, failure, stopped = "", "", False
    try:
        body = schemas.ChatRequest(conversation_id=run["conversation_id"], message=prompt,
                                   override_model_id=run.get("model") or None)
        response = await main.chat(body)
        async for chunk in response.body_iterator:
            line = chunk.decode() if isinstance(chunk, bytes) else chunk
            for piece in line.splitlines():
                if not piece.strip():
                    continue
                event = json.loads(piece)
                if event.get("type") == "token":
                    text += event.get("content") or ""
                elif event.get("type") == "error":
                    failure = event.get("message") or "Something went wrong."
                elif event.get("type") == "stopped":
                    stopped = True
                elif event.get("type") == "meta" and event.get("label"):
                    run["model_label"] = event["label"]
    except asyncio.CancelledError:
        stopped = True
    except Exception as exc:  # noqa: BLE001
        failure = str(exc) or type(exc).__name__
    run = {**get_run(run_id), "model_label": run.get("model_label")}
    if run.get("status") != "working":
        return  # stopped from the outside and already recorded
    run["finished_at"] = _now()
    if failure or stopped or not text.strip():
        run.update(status="interrupted", error=short(failure or ("Stopped." if stopped else "No answer came back."), 140),
                   summary=short(text, 140))
    else:
        run.update(status="done", summary=short(text.strip().splitlines()[-1] if len(text) > 400 else text, 160))
    # Recorded first, so the Agents screen is right the moment the run ends.
    _save_run(run)
    _set_last(run)
    if run["status"] == "done":
        asyncio.create_task(_tell(run))


async def _tell(run: dict) -> None:
    """A notification that an agent finished (never holds up the run)."""
    try:
        from . import notify
        await notify.notify("task", f"{run['agent_name']} finished", run.get("summary") or "Done.",
                            url="/app/", tag=f"nova-agent-{run['agent_id']}", view="agents")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- what's going on

def overview(show_finished: bool = False) -> dict:
    """Everything the Agents screen shows, grouped."""
    all_runs = runs(120)
    working = [r for r in all_runs if r.get("status") == "working"]
    unfinished = [r for r in all_runs if r.get("status") in ("interrupted", "stopped")]
    # Only the latest unfinished run per agent: resuming an older one is noise.
    seen, latest_unfinished = set(), []
    for r in unfinished:
        if r.get("agent_id") in seen:
            continue
        seen.add(r.get("agent_id"))
        latest_unfinished.append(r)
    finished = [r for r in all_runs if r.get("status") == "done"][:30] if show_finished else []
    busy = {r.get("agent_id") for r in working}
    agent_rows = []
    for a in agents():
        state = "working" if a["id"] in busy else "scheduled" if a.get("enabled") and a.get("next_run_at") else "paused" if not a.get("enabled") else "ready"
        agent_rows.append({**a, "state": state, "when": describe_schedule(a["schedule"]), "about": short(a["task"], 90)})
    return {"agents": agent_rows, "working": working, "unfinished": latest_unfinished[:20], "finished": finished,
            "finished_count": sum(1 for r in all_runs if r.get("status") == "done")}


# ---------------------------------------------------------------- scheduler

def recover_on_boot() -> None:
    """Runs that were working when Nova closed didn't finish."""
    for r in runs():
        if r.get("status") == "working" and r["id"] not in _tasks:
            r.update(status="interrupted", finished_at=r.get("finished_at") or _now(), error="Nova closed before it finished.")
            _save_run(r)
            _set_last(r)


async def _tick() -> None:
    now = _now()
    for a in agents():
        due = a.get("enabled") and a.get("next_run_at") and a["next_run_at"] <= now
        if not due:
            continue
        try:
            await start(a["id"], reason="schedule")
        except CrewError:
            a["next_run_at"] = next_run(a["schedule"])  # already working: wait for the next slot
            operator_store.put(AGENT, a["id"], a)
        except Exception:  # noqa: BLE001
            logger.exception("Scheduled agent %s failed to start", a.get("name"))


async def _loop() -> None:
    while True:
        try:
            await _tick()
        except Exception:  # noqa: BLE001
            logger.exception("Agent scheduler")
        await asyncio.sleep(TICK_SECONDS)


def start_scheduler() -> None:
    global _loop_task
    recover_on_boot()
    if _loop_task is None or _loop_task.done():
        _loop_task = asyncio.create_task(_loop())


async def stop_scheduler() -> None:
    global _loop_task
    if _loop_task:
        _loop_task.cancel()
        await asyncio.gather(_loop_task, return_exceptions=True)
        _loop_task = None
