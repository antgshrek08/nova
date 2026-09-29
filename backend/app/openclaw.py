"""Bridge to a local OpenClaw Gateway (https://docs.openclaw.ai/gateway) --
backs the manual, explicit "Send to Claw" action in N.O.V.A.'s chat UI (the
Workspace tab shows it as its own node). Not part of automatic routing --
routing.py never dispatches here on its own.

Task dispatch goes through the `openclaw` CLI (`openclaw agent --agent
<id> --message-file <file> --json`), not a raw HTTP call to the Gateway,
despite the Gateway exposing an OpenAI-compatible POST /v1/chat/completions
per its docs (https://docs.openclaw.ai/gateway/openai-http-api). Verified
live against this install (OpenClaw 2026.7.1-2): that endpoint 404s because
it's gated behind `gateway.http.endpoints.chatCompletions.enabled`, which
defaults to false and isn't set here -- flipping it is a Gateway config/
security-surface change outside this app's remit, left for the user to do
themselves. `openclaw agent ...` runs a real turn through the *same* live
Gateway (confirmed: real model call, real tool/skill loadout, ~30s round
trip even for a one-word reply) using the CLI's own already-authenticated
connection, so this is still a genuine bridge to the Gateway, just over a
different transport. If chatCompletions is enabled later, send_task() below
is the only place that would need to change.

The message is passed via a temp file + --message-file, never as a bare
--message argv element: OpenClaw's own npm shim (`openclaw.cmd` on Windows)
mangles/truncates argv text containing newlines or shell-special characters
the same way Codex CLI's shim does (see providers.py's stream_codex_cli
docstring) -- a temp file sidesteps that entirely regardless of task content.

The Gateway auth token is only used for the reachability/auth check
(is_gateway_available) via config.openclaw_gateway_token() (backed by .env
-- never hardcoded here) and is never interpolated into any exception
message, log line, or value returned to callers.

send_task()'s wait is a real blocking subprocess call (still the only
channel for the actual reply text -- see send_task's own docstring), but
while it's in flight an optional on_progress callback gets live status
updates polled from OpenClaw's own task ledger (`openclaw gateway call
tasks.list`/`tasks.get`, confirmed live to track every agent run regardless
of dispatch method, not just the separate Webhooks plugin's TaskFlow
records -- see _poll_status). This exists because the Gateway has no
outbound webhook/callback mechanism at all (confirmed directly against
docs.openclaw.ai/plugins/webhooks: inbound-only), so polling is the only way
to show live progress instead of a single silent wait.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from . import config

# Called as on_progress(status, label) from send_task()'s background poll
# loop -- status is always "working" (send_task's own success/failure path
# still owns the terminal "done"/"error" transition), label is free text for
# display (see _poll_status).
ProgressCallback = Callable[[str, str], Awaitable[None]]


class OpenClawUnavailableError(Exception):
    """Gateway/CLI unreachable, not configured, or returned an error.
    Message text is always token-free -- safe to show directly in the UI."""


class OpenClawNotConfiguredError(OpenClawUnavailableError):
    pass


async def is_gateway_available() -> bool:
    """Live check for the Workspace node's `enabled` flag: the openclaw CLI
    must be on PATH (what send_task() actually shells out to) and the
    Gateway itself must be up and accepting the configured token. Uses
    POST /tools/invoke with a deliberately-empty body as the auth probe --
    a real (401) auth failure is distinguishable from a real (400) "missing
    tool name" response, so this validates the *token*, not just that
    something is listening on the port. Short timeout so an unreachable
    Gateway can't stall the /models poll the frontend runs every 15s.
    """
    if shutil.which(config.OPENCLAW_CLI_PATH) is None:
        return False
    token = config.openclaw_gateway_token()
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.post(
                f"{config.OPENCLAW_GATEWAY_URL}/tools/invoke",
                headers={"Authorization": f"Bearer {token}"},
                json={},
            )
            return resp.status_code != 401
    except Exception:  # noqa: BLE001 -- Gateway simply isn't reachable right now
        return False


def _agent_sessions_dir() -> Path:
    return Path.home() / ".openclaw" / "agents" / config.OPENCLAW_AGENT_ID / "sessions"


def _session_file_from_result(data: dict) -> Path | None:
    """Prefer the exact session file the CLI itself reports for this run
    (result.meta.agentMeta.sessionFile) -- only missing when the process
    never produced JSON at all (killed on our own timeout)."""
    agent_meta = ((data.get("result") or {}).get("meta") or {}).get("agentMeta") or {}
    path = agent_meta.get("sessionFile")
    return Path(path) if path else None


def _most_recent_session_file() -> Path | None:
    """Fallback for when send_task's own timeout kills the process before
    any JSON comes back: `--agent <id>` with no explicit --session-key
    reuses one persistent session across calls, so the most-recently-
    modified real session log (never the .trajectory.jsonl sidecar) in this
    agent's sessions dir is this run's, as long as calls aren't concurrent
    -- true here, "Send to Claw" is one request at a time."""
    sessions_dir = _agent_sessions_dir()
    if not sessions_dir.is_dir():
        return None
    candidates = [p for p in sessions_dir.glob("*.jsonl") if not p.name.endswith(".trajectory.jsonl")]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _find_successful_tool_result_since(session_file: Path, since_ms: int) -> tuple[str, str] | None:
    """Scans a session log's real toolResult entries (see module docstring
    for the exact shape) for the last one timestamped at/after `since_ms`
    (epoch ms, captured right before this run's subprocess started) with
    isError == false. Returns (tool_name, result_text) if real work
    completed during this run, regardless of whatever the model's own
    follow-up chatter did or didn't manage to say -- or None if nothing
    succeeded (including: file unreadable, no matching entries).
    """
    try:
        lines = session_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    found: tuple[str, str] | None = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("message") or {}
        if message.get("role") != "toolResult" or message.get("isError") is not False:
            continue
        if (message.get("timestamp") or 0) < since_ms:
            continue
        content = message.get("content") or []
        text = " ".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
        if text:
            found = (message.get("toolName") or "a tool", text)
    return found


def _success_despite_trouble_message(tool_name: str, result_text: str) -> str:
    return (
        f"OpenClaw's '{tool_name}' tool completed successfully: {result_text} "
        "(the model's own follow-up reply ran into trouble after that, but the "
        "task itself finished -- confirmed directly from OpenClaw's session log.)"
    )


# --- live status polling (task ledger, not the Webhooks plugin) ------------
#
# The Gateway has no outbound webhook/callback mechanism at all (confirmed
# directly against docs.openclaw.ai/plugins/webhooks -- inbound-only, no
# callback_url/webhook_url anywhere), so there's no way for OpenClaw to push
# progress to us. What it does have, confirmed live against this install: a
# general task ledger (`openclaw gateway call tasks.list`/`tasks.get`, not
# tied to the Webhooks plugin's TaskFlow records) that tracks every agent
# run regardless of how it was dispatched, including the plain `openclaw
# agent --json` calls send_task() already makes -- verified by dispatching a
# real task and finding it in tasks.list by sessionKey/createdAt straight
# after. Each entry has status (queued/running/completed/failed/cancelled/
# timed_out) and timestamps, but no result/output text -- that only ever
# comes from the CLI subprocess's own stdout once it exits. So polling here
# is purely a status *color* for the Workspace node while send_task's real
# subprocess wait is still in flight; it never decides success/failure and
# never supplies the actual reply text.


async def _gateway_call(method: str, params: dict) -> dict | None:
    """Best-effort call to a Gateway RPC method via the CLI's own
    already-authenticated connection (same rationale as send_task's own
    dispatch -- see module docstring: the CLI is a genuine bridge to the
    live Gateway, just not over raw HTTP). Returns None on any failure --
    this is only ever used for a supplementary status update, never the
    source of truth for the task's actual outcome, so a failed probe just
    means one skipped update, not a broken dispatch."""
    resolved = shutil.which(config.OPENCLAW_CLI_PATH)
    if not resolved:
        return None
    try:
        process = await asyncio.create_subprocess_exec(
            resolved,
            "gateway", "call", method,
            "--json",
            "--params", json.dumps(params),
            "--timeout", str(int(config.OPENCLAW_STATUS_CALL_TIMEOUT_SECONDS * 1000)),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(
            process.communicate(), timeout=config.OPENCLAW_STATUS_CALL_TIMEOUT_SECONDS + 3
        )
        if process.returncode != 0:
            return None
        return json.loads(stdout.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 -- best-effort status polling, never fatal
        return None


async def _find_task_id(agent_id: str, since_ms: int) -> str | None:
    """This run's task in the ledger. sessionKey is reused across every
    `openclaw agent --agent <id>` call with no explicit --session-key
    (confirmed live: every "Send to Claw" dispatch lands in the same
    "agent:<id>:<id>" session), so `createdAt >= since_ms` -- captured right
    before this run's subprocess started, same pattern as
    _find_successful_tool_result_since's `since_ms` -- is what disambiguates
    this call from any earlier one in that same shared session, including a
    rapid-fire second "Send to Claw" while an earlier one is still running.
    A small slack (2s) absorbs clock/logging skew between when we captured
    since_ms and when the Gateway actually timestamped task creation."""
    data = await _gateway_call("tasks.list", {"agentId": agent_id, "limit": 5})
    if data is None:
        return None
    candidates = [
        t for t in (data.get("tasks") or [])
        if isinstance(t.get("createdAt"), (int, float)) and t["createdAt"] >= since_ms - 2000
    ]
    if not candidates:
        return None
    newest = max(candidates, key=lambda t: t["createdAt"])
    return newest.get("taskId") or newest.get("id")


async def _get_task_status(task_id: str) -> str | None:
    data = await _gateway_call("tasks.get", {"taskId": task_id})
    task = (data or {}).get("task") or {}
    return task.get("status")


_TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled", "timed_out"}


async def _poll_status(agent_id: str, since_ms: int, on_progress: ProgressCallback) -> None:
    """Background loop, run concurrently with send_task's real subprocess
    wait and cancelled the moment that settles (see send_task) -- so its own
    ceiling is whatever OPENCLAW_TIMEOUT_SECONDS already is, never a separate
    unbounded wait. Two phases: find this run's taskId in the ledger (may not
    exist yet the instant the subprocess starts), then poll its status on a
    backoff schedule until terminal or cancelled. Never raises -- a status
    probe failing degrades to fewer UI updates, not a broken dispatch.
    """
    await on_progress("working", "OpenClaw -- dispatching...")
    delay = config.OPENCLAW_POLL_INITIAL_SECONDS
    elapsed = 0.0

    task_id: str | None = None
    while task_id is None:
        await asyncio.sleep(delay)
        elapsed += delay
        task_id = await _find_task_id(agent_id, since_ms)
        if task_id is None:
            await on_progress("working", f"OpenClaw -- starting... ({int(elapsed)}s)")
            delay = min(delay * 1.5, config.OPENCLAW_POLL_MAX_INTERVAL_SECONDS)

    delay = config.OPENCLAW_POLL_INITIAL_SECONDS
    while True:
        status = await _get_task_status(task_id)
        label = f"OpenClaw -- {status or 'running'} ({int(elapsed)}s)"
        await on_progress("working", label)
        if status in _TERMINAL_TASK_STATUSES:
            return
        await asyncio.sleep(delay)
        elapsed += delay
        delay = min(delay * 1.3, config.OPENCLAW_POLL_MAX_INTERVAL_SECONDS)


async def send_task(task: str, on_progress: ProgressCallback | None = None) -> str:
    """Runs `task` as a real agent turn (openclaw agent --json) and returns
    its final text reply once the whole run -- including any tool/skill use
    the agent decides to do -- has completed. Raises OpenClawUnavailableError
    with a token-free message on any failure: CLI missing, run failed, timed
    out, or returned an unexpected shape.

    Real bug found in practice: OpenClaw can report trouble at the *very
    last* step -- generating the model's own closing "done"-style reply --
    even after the task's actual tool call already succeeded (a slow local
    model can time out on that trailing generation call). Left alone, that
    surfaces as a flat "timed out"/failure message even though the real work
    completed, which is actively misleading. So every place below that would
    otherwise return/raise something failure-shaped first checks the raw
    session log (via _find_successful_tool_result_since) for a real,
    successful toolResult logged after this call started; if one exists, a
    plain success message describing what actually happened is returned
    instead of the misleading text.
    """
    resolved = shutil.which(config.OPENCLAW_CLI_PATH)
    if not resolved:
        raise OpenClawNotConfiguredError(
            f"OpenClaw CLI ('{config.OPENCLAW_CLI_PATH}') isn't on PATH."
        )

    start_ms = int(time.time() * 1000)
    # Purely observational -- polls OpenClaw's own task ledger for a live
    # status color on the Workspace node while the real wait below is in
    # flight (see _poll_status). Never awaited for its result, cancelled the
    # moment the real subprocess settles either way, so it can never extend
    # or shorten how long this function actually waits.
    poll_task = (
        asyncio.create_task(_poll_status(config.OPENCLAW_AGENT_ID, start_ms, on_progress))
        if on_progress
        else None
    )
    fd, task_file = tempfile.mkstemp(prefix="nova-openclaw-task-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(task)

        try:
            try:
                process = await asyncio.create_subprocess_exec(
                    resolved,
                    "agent",
                    "--agent", config.OPENCLAW_AGENT_ID,
                    "--message-file", task_file,
                    "--json",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=config.OPENCLAW_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                process.kill()
                session_file = _most_recent_session_file()
                found = _find_successful_tool_result_since(session_file, start_ms) if session_file else None
                if found:
                    return _success_despite_trouble_message(*found)
                raise OpenClawUnavailableError(
                    f"OpenClaw agent run timed out after {config.OPENCLAW_TIMEOUT_SECONDS}s."
                ) from None
        finally:
            if poll_task:
                poll_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await poll_task
    finally:
        try:
            os.remove(task_file)
        except OSError:
            pass

    if process.returncode != 0:
        session_file = _most_recent_session_file()
        found = _find_successful_tool_result_since(session_file, start_ms) if session_file else None
        if found:
            return _success_despite_trouble_message(*found)
        detail = stderr.decode("utf-8", errors="replace").strip() or f"exit code {process.returncode}"
        raise OpenClawUnavailableError(f"OpenClaw agent run failed: {detail[:400]}")

    try:
        data = json.loads(stdout.decode("utf-8", errors="replace"))
    except ValueError:
        raise OpenClawUnavailableError(
            "OpenClaw agent returned output that wasn't valid JSON."
        ) from None

    result = data.get("result") or {}
    meta = result.get("meta") or {}

    # OpenClaw can report trouble at the very last step -- generating the
    # model's own closing reply -- even after the task's real tool call
    # already succeeded (see send_task's docstring). The authoritative
    # signal for that is the TOP-LEVEL `status` field (a clean run is
    # "ok"; this specific bug reproduces with "timeout", stopReason "rpc",
    # timeoutPhase "provider" -- verified against a real captured response).
    # executionTrace.attempts (nested under result.meta) is a second,
    # independent signal seen on other runs -- it isn't always present
    # (absent entirely on the "status":"timeout" shape above, which is
    # exactly why relying on it alone missed this the first time), so both
    # are checked; either one being off-nominal is enough to warrant a
    # session-log check before trusting the returned text at face value.
    attempts = (meta.get("executionTrace") or {}).get("attempts") or []
    had_trouble = data.get("status") not in (None, "ok") or any(a.get("result") != "success" for a in attempts)
    if had_trouble:
        session_file = _session_file_from_result(data) or _most_recent_session_file()
        found = _find_successful_tool_result_since(session_file, start_ms) if session_file else None
        if found:
            return _success_despite_trouble_message(*found)

    payloads = result.get("payloads") or []
    if payloads and payloads[0].get("text"):
        return payloads[0]["text"]
    fallback = meta.get("finalAssistantVisibleText")
    if fallback:
        return fallback
    raise OpenClawUnavailableError("OpenClaw agent run completed but returned no reply text.")
