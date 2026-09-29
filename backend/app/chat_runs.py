"""Which chat turns are running, and stopping one -- the backend of the chat
box's send/stop button.

While a conversation has a turn in progress the button shows Stop, and
pressing it calls stop(): the turn's task is cancelled wherever it is waiting
(a model, a tool, a browser action), whatever was already said is kept, and
the stream ends with a "stopped" event. When nothing is running the button is
the send arrow again. A second message to a busy conversation is refused
rather than run alongside the first.

This stops one chat turn. It is not the operator Stop (operator_workflows),
which halts every action until the user presses Resume.
"""
from __future__ import annotations

import asyncio
import contextvars
import time
import uuid

# A turn reserved but whose stream never started (the client went away before
# reading it) stops blocking the conversation after this long.
_UNSTARTED_GRACE_SECONDS = 30

_RUNS: dict[int, dict] = {}

# The turn the current code is running inside, so records a turn opens (an
# operator task, say) can be closed when that turn ends.
current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("nova_chat_run", default=None)


class Busy(Exception):
    """The conversation already has a turn in progress."""


def _active(run: dict | None) -> bool:
    if run is None:
        return False
    task = run["task"]
    if task is None:
        return time.time() - run["started_at"] < _UNSTARTED_GRACE_SECONDS
    return not task.done()


def reserve(conversation_id: int) -> dict:
    """Claim the conversation for a new turn; raises Busy if one is running."""
    if _active(_RUNS.get(conversation_id)):
        raise Busy("Nova is still working on this conversation. Stop it or wait for it to finish.")
    run = {"id": uuid.uuid4().hex, "conversation_id": conversation_id,
           "started_at": time.time(), "task": None, "stop_requested": False}
    _RUNS[conversation_id] = run
    return run


def attach(run: dict) -> None:
    """Called from inside the turn's stream, so stop() can cancel that task."""
    run["task"] = asyncio.current_task()
    run["loop"] = asyncio.get_running_loop()
    current_run_id.set(run["id"])
    if run["stop_requested"]:
        run["task"].cancel()


def _cancel(run: dict) -> None:
    # Operator Stop can come from another thread (the stop hotkey, the mouse
    # corner), and Task.cancel is only safe on the task's own loop.
    task, loop = run["task"], run.get("loop")
    if task is None:
        return
    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(task.cancel)
    else:
        task.cancel()


def stop_requested(run: dict) -> bool:
    return run["stop_requested"]


def finish(run: dict) -> None:
    if _RUNS.get(run["conversation_id"]) is run:
        del _RUNS[run["conversation_id"]]
    # Whatever this turn started and didn't close is no longer being worked
    # on; left "running" it would show as Nova working forever.
    try:
        from . import operator_workflows
        operator_workflows.close_open_tasks(run_id=run["id"], reason="The chat turn ended before this task was finished.")
    except Exception:
        pass


def status(conversation_id: int) -> dict:
    run = _RUNS.get(conversation_id)
    if not _active(run):
        return {"conversation_id": conversation_id, "running": False}
    return {"conversation_id": conversation_id, "running": True, "run_id": run["id"],
            "started_at": run["started_at"], "stopping": run["stop_requested"]}


def running() -> list[dict]:
    return [status(cid) for cid, run in list(_RUNS.items()) if _active(run)]


def stop(conversation_id: int) -> dict:
    """Stop the conversation's running turn. Stopping an idle conversation is a no-op."""
    run = _RUNS.get(conversation_id)
    if not _active(run):
        return {"conversation_id": conversation_id, "running": False, "stopped": False}
    run["stop_requested"] = True
    _cancel(run)
    return {"conversation_id": conversation_id, "running": True, "stopped": True, "run_id": run["id"]}


def stop_all() -> int:
    """Operator Stop: end every running turn. Agentic CLI models drive the
    browser from their own process, which no per-action check can reach, so
    the turn itself (and with it that process) has to end."""
    stopped = 0
    for cid, run in list(_RUNS.items()):
        if _active(run):
            run["stop_requested"] = True
            _cancel(run)
            stopped += 1
    return stopped
