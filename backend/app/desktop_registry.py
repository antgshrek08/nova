"""In-memory registry of desktop actions awaiting -- or having received --
explicit per-action user approval (see desktop.py's module docstring for the
policy/mechanism split this implements the "policy" half of).

A gated action (click/type/open_app) the model wants to perform creates a
PendingDesktopAction here and the chat request genuinely blocks (awaits an
asyncio.Event) on create_pending()'s caller side -- see main.py's desktop
tool loop -- until the user responds via POST /desktop/actions/{id}/respond,
or a timeout elapses, whichever comes first. This is what makes "explicitly
confirmed by the user in the moment" real rather than decorative: nothing
about the action has executed yet when the frontend shows the approval
card, and nothing executes if the user never answers.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

DEFAULT_TIMEOUT_SECONDS = 120


@dataclass
class PendingDesktopAction:
    id: str
    kind: str  # "click" | "type" | "open_app"
    args: dict
    description: str
    status: str = "pending"  # pending | approved | denied | timed_out
    created_at: float = field(default_factory=time.time)
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


class DesktopActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, PendingDesktopAction] = {}

    def create_pending(self, kind: str, args: dict, description: str) -> PendingDesktopAction:
        action = PendingDesktopAction(id=str(uuid.uuid4()), kind=kind, args=args, description=description)
        self._actions[action.id] = action
        return action

    def get(self, action_id: str) -> PendingDesktopAction | None:
        return self._actions.get(action_id)

    def respond(self, action_id: str, approved: bool) -> PendingDesktopAction | None:
        action = self._actions.get(action_id)
        if action is None or action.status != "pending":
            return action
        action.status = "approved" if approved else "denied"
        action._event.set()
        return action

    async def wait_for_response(self, action_id: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> str:
        """Blocks until the user responds or `timeout` elapses. Returns the
        final status ("approved" | "denied" | "timed_out")."""
        action = self._actions[action_id]
        try:
            await asyncio.wait_for(action._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            if action.status == "pending":
                action.status = "timed_out"
        return action.status

    def forget(self, action_id: str) -> None:
        self._actions.pop(action_id, None)

    def pending_count(self) -> int:
        """How many actions are waiting on the user right now.

        The miniplayer is a separate window from the chat that raised the
        approval, so it cannot see the `desktop_confirm` stream event. Without
        a count it has no way to show "needs input" -- which is the state
        ChatGPT's pet prioritises above every other, and rightly: it is the
        only one where the work is stopped until the user does something.
        """
        return sum(1 for action in self._actions.values() if action.status == "pending")


registry = DesktopActionRegistry()
