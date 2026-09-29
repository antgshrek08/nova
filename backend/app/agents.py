"""In-memory registry of live "agent" jobs (Phase 5).

Each /chat request becomes one job that moves through
queued -> working -> done/error, broadcasting itself over a websocket as it
changes so the Agent Workspace tab can render a live card per active
model/agent. Deliberately ephemeral: this is a live dashboard, not a history
(SQLite already covers that -- see db.py) -- jobs are capped at MAX_JOBS,
oldest evicted first, and nothing here survives a restart.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict, dataclass, field

from fastapi import WebSocket

from . import pet

MAX_JOBS = 30


@dataclass
class AgentJob:
    id: str
    conversation_id: int
    category: str | None = None
    provider: str | None = None
    model: str | None = None
    label: str | None = None
    # Set only when provider == "custom" (see routing.RoutingResult):
    # user-added custom-endpoint model, not one of routing's spec chains.
    # /models exposes these as node id f"custom:{id}" -- carried here too so
    # the Workspace network view's live-dispatch pulse can find the right
    # node instead of having no way to resolve a custom job to any node id
    # at all (a real bug -- see providers.js's jobNodeId).
    custom_model_row_id: int | None = None
    status: str = "queued"  # queued | working | done | error
    output: str = ""
    error: str | None = None
    # Set only for a real agent-to-agent handoff (see main.py's coding-review
    # handoff): the provider id of the upstream job whose OUTPUT became this
    # job's input. Lets the Workspace network view draw a direct node-to-node
    # wire instead of routing through the hub, same dispatch-animation
    # mechanism, different path -- this is the real handoff, not the design
    # mockup's decorative one.
    handoff_from_provider: str | None = None
    handoff_command: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class AgentRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, AgentJob] = {}
        self._order: list[str] = []  # insertion order, oldest first
        self._sockets: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def create_job(
        self,
        conversation_id: int,
        category: str | None = None,
        handoff_from_provider: str | None = None,
        handoff_command: str | None = None,
    ) -> AgentJob:
        job = AgentJob(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            category=category,
            handoff_from_provider=handoff_from_provider,
            handoff_command=handoff_command,
        )
        async with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > MAX_JOBS:
                oldest_id = self._order.pop(0)
                self._jobs.pop(oldest_id, None)
        # Integration-plan Phase 2 (RESEARCH.md, 2026-09-03): a fresh job
        # gives the pet something real to say (its category, already on
        # every job -- see pet.blurb_for_category), not just a reaction
        # pose. A single shared "what's it currently saying" is a fine
        # simplification even with multiple concurrent jobs (Workspace
        # agent chains, a handoff running alongside normal chat) -- it's
        # ambient flavor text, not the source of truth for whether the
        # character should look busy, which the frontend derives itself
        # from the per-job status stream instead (see DesktopPet.jsx/
        # Miniplayer.jsx).
        pet.nova_pet_say(pet.blurb_for_category(job.category))
        await self._broadcast_job(job)
        return job

    async def update_job(self, job_id: str, **fields) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = time.time()
        if job.status == "done":
            pet.nova_pet_say(None)  # clear the bubble -- nothing left to say
        elif job.status == "error":
            pet.nova_pet_say("Hit a snag.")
        await self._broadcast_job(job)

    async def append_output(self, job_id: str, chunk: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.output += chunk
        job.updated_at = time.time()
        await self._broadcast_job(job)

    async def reset_output(self, job_id: str) -> None:
        """Discard what has streamed so far. Used when a provider fails partway
        and the agent loop reroutes: the failed attempt's output is not part of
        the answer, so the job card should not keep showing it either."""
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.output = ""
        job.updated_at = time.time()
        await self._broadcast_job(job)

    def snapshot(self) -> list[dict]:
        return [asdict(self._jobs[jid]) for jid in self._order if jid in self._jobs]

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._sockets.add(websocket)
        from . import desktop_registry

        # The approval count rides along with the snapshot so a window that
        # opens *while* something is already waiting shows it immediately,
        # rather than staying wrong until the next approval happens to change.
        await websocket.send_json({
            "type": "snapshot",
            "jobs": self.snapshot(),
            "approvals_pending": desktop_registry.registry.pending_count(),
        })

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._sockets.discard(websocket)

    async def broadcast_task(self, task: dict) -> None:
        """Workspace/team-orchestration milestone: reuses this exact same
        socket set and /ws/agents endpoint for durable task events (task:
        "Connect Workspace to real job events") -- the frontend's existing
        agentSocket.js connection picks these up automatically, no new
        websocket needed. `task` is a plain dict (db.py's task row shape),
        not an AgentJob -- tasks are durable (SQLite) and can span several
        AgentJobs over their lifetime, so they're broadcast as their own
        message type rather than shoehorned into the job dataclass."""
        await self._broadcast({"type": "task", "task": task})

    async def broadcast_activity(self, *, provider: str | None, model: str | None,
                                 label: str | None, tool: str, summary: str,
                                 status: str) -> None:
        """What one model is doing right this second.

        Jobs already say *that* a model is busy; this says *what* it is doing --
        "editing agent_loop.py" rather than a spinner. That difference is the
        whole point of showing characters at all: a bot that only ever wiggles
        is decoration, and decoration stops being looked at.

        Fire-and-forget by design. Tool execution must never wait on, or fail
        because of, a UI broadcast.
        """
        await self._broadcast({
            "type": "activity",
            "provider": provider,
            "model": model,
            "label": label,
            "tool": tool,
            "summary": summary,
            "status": status,        # running | done | error
        })

    async def broadcast_approvals(self) -> None:
        """Tell every window how many actions are waiting on the user.

        Same socket as jobs and tasks, for the same reason those share it. The
        miniplayer needs this because the approval card is raised in the chat
        window's stream, which it cannot see -- and "needs input" outranks every
        other state it can show, so guessing from job status is not enough.
        """
        from . import desktop_registry

        await self._broadcast({
            "type": "approvals",
            "pending": desktop_registry.registry.pending_count(),
        })

    async def _broadcast_job(self, job: AgentJob) -> None:
        # Integration-plan Phase 2 (RESEARCH.md, 2026-09-03): every job
        # broadcast is a real AgentJob status transition, so this is the one
        # place that can call nova_pet_react "directly" the way the plan
        # asked -- every current and future job-creating code path in
        # main.py funnels through create_job/update_job/append_output
        # (append_output re-broadcasts the same job unchanged, so its status
        # -> reaction mapping is idempotent), so nothing has to remember to
        # wire pet-awareness in separately.
        pet.nova_pet_react(pet.react_state_for_status(job.status))
        await self._broadcast({"type": "job", "job": asdict(job), "pet": pet.nova_pet_status()})

    async def _broadcast(self, message: dict) -> None:
        dead = []
        for ws in list(self._sockets):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - a dead socket shouldn't break the others
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._sockets.discard(ws)


registry = AgentRegistry()
