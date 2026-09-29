"""Agent Client Protocol client.

ACP is the editor<->agent protocol (JSON-RPC 2.0 over stdio) that Zed
standardised: an editor spawns a coding agent as a child process, opens a
session, sends prompts, and receives streamed `session/update` notifications
while the agent works. Claude Code speaks it through `claude-code-acp`, Gemini
CLI through `--experimental-acp`, and Hermes natively -- so one client here
gives Nova a uniform way to drive all of them.

Nova is the *client* half. That means it must answer requests coming back the
other way, which is most of what this module is:

  fs/read_text_file, fs/write_text_file
      The agent asks Nova to touch the filesystem on its behalf, so unsaved
      editor state and Nova's own path rules apply instead of the agent's.
  session/request_permission
      The agent asks before doing something notable. Nova answers from the
      autonomy setting: `full` approves, `guarded` routes it to the same
      approval card desktop actions use, `readonly` declines.
  terminal/*
      Optional in the spec and not implemented; agents advertise terminal
      support via client capabilities and we do not claim it.

app/hermes.py predates this and speaks the same protocol to one hard-wired
agent. It is left alone -- it carries Hermes-specific queue integration that
would be lost in a merge, and a protocol client is cheap to have twice.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config, db, desktop_registry, nova_tools

PROTOCOL_VERSION = 1
STARTUP_TIMEOUT = 45
PROMPT_TIMEOUT = 1800  # coding agents legitimately run for a long time

# Known-good agent commands offered in Settings so the user does not have to
# remember argv. Nothing here is installed automatically.
SUGGESTED_AGENTS = [
    {
        "name": "Claude Code",
        "command": "npx",
        # @zed-industries/claude-code-acp still works but prints a deprecation
        # notice on every start; this is the package it was renamed to.
        "args": ["-y", "@agentclientprotocol/claude-agent-acp"],
        "note": "Anthropic's Claude Code as an ACP agent. Uses your existing Claude CLI login — run `claude /login` first if it reports an auth error.",
    },
    {
        "name": "Gemini CLI",
        "command": "gemini",
        "args": ["--experimental-acp"],
        "note": "Google's Gemini CLI in ACP mode. Requires the gemini CLI on PATH.",
    },
    {
        "name": "Codex",
        "command": "npx",
        "args": ["-y", "@zed-industries/codex-acp"],
        "note": "OpenAI Codex as an ACP agent.",
    },
]


# Coding agents mark their own child processes with environment variables that
# mean "you are already running inside me" -- session ids, IPC socket paths,
# nesting guards. Inheriting them makes the agent Nova spawns believe it is a
# nested copy of itself and refuse to open a session. Confirmed live: with
# these passed through, claude-code-acp answers session/new with a bare
# "Internal error" and explains only on stderr ("Claude Code cannot be launched
# inside another Claude Code session").
#
# Matched by prefix rather than by an exact list, because the set is large and
# grows with each agent release -- one real environment here carried 20+
# CLAUDE_CODE_* variables, several of them live IPC handles. Nova is the editor
# in this relationship, never a nested agent, so the whole family is dropped.
# A user who genuinely needs one of these set for an agent can add it as an
# explicit env override on that agent in Settings, which is applied after this
# filter.
_ENV_BLOCKLIST_PREFIXES = (
    "CLAUDECODE",
    "CLAUDE_",
    "CODEX_",
    "CURSOR_",
    "GEMINI_CLI",
    "AIDER_",
)


class ACPError(RuntimeError):
    """Protocol or process failure, phrased for display."""


@dataclass
class Session:
    session_id: str
    cwd: str
    created_at: float = field(default_factory=time.time)
    updates: asyncio.Queue = field(default_factory=asyncio.Queue)


@dataclass
class Connection:
    agent_id: int
    name: str
    process: asyncio.subprocess.Process
    capabilities: dict = field(default_factory=dict)
    auth_methods: list = field(default_factory=list)
    sessions: dict[str, Session] = field(default_factory=dict)
    pending: dict[int, asyncio.Future] = field(default_factory=dict)
    next_id: int = 0
    stderr_tail: list[str] = field(default_factory=list)
    reader_task: asyncio.Task | None = None
    stderr_task: asyncio.Task | None = None

    def alive(self) -> bool:
        return self.process.returncode is None


_connections: dict[int, Connection] = {}
_locks: dict[int, asyncio.Lock] = {}


def _lock_for(agent_id: int) -> asyncio.Lock:
    lock = _locks.get(agent_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[agent_id] = lock
    return lock


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
async def _write(connection: Connection, payload: dict) -> None:
    if not connection.alive():
        raise ACPError(f"{connection.name} is not running.")
    line = json.dumps({"jsonrpc": "2.0", **payload}) + "\n"
    connection.process.stdin.write(line.encode())
    await connection.process.stdin.drain()


async def _request(connection: Connection, method: str, params: dict, timeout: float = 60) -> dict:
    connection.next_id += 1
    request_id = connection.next_id
    future = asyncio.get_running_loop().create_future()
    connection.pending[request_id] = future
    try:
        await _write(connection, {"id": request_id, "method": method, "params": params})
        return await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError as exc:
        raise ACPError(f"{connection.name} did not answer {method} within {timeout:.0f}s.") from exc
    finally:
        connection.pending.pop(request_id, None)


async def _respond(connection: Connection, request_id, result=None, error=None) -> None:
    if error is not None:
        await _write(connection, {"id": request_id, "error": error})
    else:
        await _write(connection, {"id": request_id, "result": result if result is not None else {}})


async def _pump_stderr(connection: Connection) -> None:
    try:
        while line := await connection.process.stderr.readline():
            text = line.decode(errors="replace").rstrip()
            connection.stderr_tail.append(text)
            del connection.stderr_tail[:-40]
    except Exception:  # noqa: BLE001 - the pipe closes when the child exits
        pass


async def _pump_stdout(connection: Connection) -> None:
    """Reads the agent's side of the wire forever: results for our requests,
    session/update notifications, and requests the agent makes of us."""
    try:
        while line := await connection.process.stdout.readline():
            try:
                message = json.loads(line)
            except ValueError:
                continue  # some agents print banners before the first frame
            method = message.get("method")
            if method is None:
                future = connection.pending.get(message.get("id"))
                if future is not None and not future.done():
                    if "error" in message and message["error"]:
                        future.set_exception(ACPError(_error_text(connection, message["error"])))
                    else:
                        future.set_result(message.get("result") or {})
                continue
            if "id" in message:
                asyncio.create_task(_handle_agent_request(connection, message))
            else:
                _handle_notification(connection, message)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - a dead pipe is handled by the alive() checks
        pass
    finally:
        for future in connection.pending.values():
            if not future.done():
                future.set_exception(ACPError(f"{connection.name} exited unexpectedly."))
        for session in connection.sessions.values():
            session.updates.put_nowait({"sessionUpdate": "_closed"})


def _error_text(connection: Connection, error) -> str:
    """Agents report protocol failures as a bare code plus a generic message
    ("Internal error") and put the actual cause on stderr. Folding the recent
    stderr lines in is the difference between a message the user can act on and
    one they cannot -- it is how the CLAUDECODE nesting guard was diagnosed."""
    if not isinstance(error, dict):
        return str(error)
    parts = [str(error.get("message") or "The agent reported an error.")]
    data = error.get("data")
    if isinstance(data, dict):
        detail = data.get("details") or data.get("detail")
        if detail:
            parts.append(str(detail))
        elif data:
            parts.append(json.dumps(data)[:300])
    elif data:
        parts.append(str(data)[:300])
    combined = " ".join(parts).lower()
    if "authenticat" in combined or "401" in combined or "oauth" in combined:
        # The agent already told us how to sign in during initialize; repeating
        # it here saves the user going to look for it.
        hints = [m.get("description") or m.get("name") for m in connection.auth_methods]
        hints = [h for h in hints if h]
        return (
            f"{connection.name} needs you to sign in again"
            + (f" — {hints[0]}." if hints else ".")
            + "\nOnce you have, click Connect again in Settings > Agents."
        )
    noise = ("npm warn", "npm notice", "Debugger attached")
    tail = [line for line in connection.stderr_tail[-8:]
            if line.strip() and not line.startswith(noise)]
    if tail:
        parts.append("Agent output:\n" + "\n".join(tail[-5:]))
    return " — ".join(parts[:2]) + ("\n" + parts[2] if len(parts) > 2 else "")


def _handle_notification(connection: Connection, message: dict) -> None:
    if message.get("method") != "session/update":
        return
    params = message.get("params") or {}
    session = connection.sessions.get(params.get("sessionId"))
    if session is not None:
        session.updates.put_nowait(params.get("update") or {})


# ---------------------------------------------------------------------------
# Client-side request handlers
# ---------------------------------------------------------------------------
async def _handle_agent_request(connection: Connection, message: dict) -> None:
    method = message.get("method")
    params = message.get("params") or {}
    try:
        if method == "fs/read_text_file":
            result = await _fs_read(params)
        elif method == "fs/write_text_file":
            result = await _fs_write(params)
        elif method == "session/request_permission":
            result = await _request_permission(connection, params)
        else:
            await _respond(connection, message["id"], error={"code": -32601, "message": f"{method} is not supported by this client."})
            return
        await _respond(connection, message["id"], result=result)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a JSON-RPC error
        try:
            await _respond(connection, message["id"], error={"code": -32000, "message": str(exc)[:400]})
        except Exception:  # noqa: BLE001 - the agent is gone; nothing to report to
            pass


async def _fs_read(params: dict) -> dict:
    path = Path(params["path"]).resolve()
    denial = nova_tools._deny_path(path)
    if denial:
        raise ACPError(denial)
    text = await asyncio.to_thread(path.read_text, "utf-8", "replace")
    line = params.get("line")
    limit = params.get("limit")
    if line or limit:
        lines = text.splitlines()
        start = max(0, (line or 1) - 1)
        text = "\n".join(lines[start: start + limit] if limit else lines[start:])
    return {"content": text}


async def _fs_write(params: dict) -> dict:
    path = Path(params["path"]).resolve()
    denial = nova_tools._deny_path(path)
    if denial:
        raise ACPError(denial)
    if await nova_tools.autonomy_level() == "readonly":
        raise ACPError("Nova's autonomy is set to read-only, so the write was declined.")
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, params.get("content", ""), "utf-8")
    return {}


async def _request_permission(connection: Connection, params: dict) -> dict:
    """Answer the agent's permission prompt from the autonomy setting.

    The response shape is {"outcome": {"outcome": "selected", "optionId": ...}}
    -- the agent supplies its own option list, so pick from what it offered
    rather than assuming ids.
    """
    options = params.get("options") or []
    level = await nova_tools.autonomy_level()

    def pick(*kinds: str) -> str | None:
        for kind in kinds:
            for option in options:
                if option.get("kind") == kind:
                    return option.get("optionId")
        return None

    if level == "readonly":
        chosen = pick("reject_always", "reject_once")
        return {"outcome": {"outcome": "selected", "optionId": chosen} if chosen
                else {"outcome": "cancelled"}}

    if level == "full":
        chosen = pick("allow_always", "allow_once")
        return {"outcome": {"outcome": "selected", "optionId": chosen} if chosen
                else {"outcome": "cancelled"}}

    tool = params.get("toolCall") or {}
    description = f"{connection.name}: {tool.get('title') or tool.get('kind') or 'requested permission'}"
    action = desktop_registry.registry.create_pending("acp_permission", params, description)
    status = await desktop_registry.registry.wait_for_response(action.id)
    desktop_registry.registry.forget(action.id)
    chosen = pick("allow_once", "allow_always") if status == "approved" else pick("reject_once", "reject_always")
    return {"outcome": {"outcome": "selected", "optionId": chosen} if chosen
            else {"outcome": "cancelled"}}


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def _git_bash_path() -> str | None:
    """Where git-bash lives, if it does.

    Claude Code refuses to start on Windows without it, and reports that only
    on stderr while answering the protocol with a generic "Internal error" --
    so finding it here is what turns a dead-end failure into a working agent.
    It is normally passed as CLAUDE_CODE_GIT_BASH_PATH, which the nesting-guard
    filter above strips along with the rest of the CLAUDE_ family; this puts
    the one variable that is configuration rather than session state back.
    """
    if os.name != "nt":
        return None
    existing = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if existing and Path(existing).exists():
        return existing
    git = shutil.which("git")
    if git:
        # <root>/cmd/git.exe and <root>/mingw64/bin/git.exe both sit two levels
        # under the install root that also holds bin/bash.exe.
        for parents in (2, 3):
            try:
                candidate = Path(git).parents[parents - 1] / "bin" / "bash.exe"
            except IndexError:
                continue
            if candidate.exists():
                return str(candidate)
    for drive in ("C:", "D:"):
        for base in (r"\Program Files\Git", r"\Program Files (x86)\Git"):
            candidate = Path(drive + base) / "bin" / "bash.exe"
            if candidate.exists():
                return str(candidate)
    return None


def _resolve_command(command: str) -> str:
    found = shutil.which(command)
    if found:
        return found
    # npx/npm resolve to .cmd shims on Windows, which shutil.which only finds
    # when PATHEXT is consulted -- it usually is, but a bare miss here produces
    # a far more confusing FileNotFoundError later.
    if os.name == "nt":
        for suffix in (".cmd", ".exe", ".bat"):
            found = shutil.which(command + suffix)
            if found:
                return found
    raise ACPError(f"'{command}' is not on PATH. Install it, or give the full path in Settings > Agents.")


async def connect(agent_id: int) -> Connection:
    async with _lock_for(agent_id):
        existing = _connections.get(agent_id)
        if existing is not None and existing.alive():
            return existing
        row = await db.get_acp_agent(agent_id)
        if row is None:
            raise ACPError("That agent is no longer configured.")

        try:
            args = json.loads(row["args"] or "[]")
            env_overrides = json.loads(row["env"] or "{}")
        except ValueError as exc:
            raise ACPError(f"Agent '{row['name']}' has malformed args/env: {exc}") from exc

        environment = {
            k: v for k, v in os.environ.items()
            if not k.upper().startswith(_ENV_BLOCKLIST_PREFIXES)
        }
        git_bash = _git_bash_path()
        if git_bash:
            environment["CLAUDE_CODE_GIT_BASH_PATH"] = git_bash
        environment.update({str(k): str(v) for k, v in env_overrides.items()})
        cwd = row["cwd"] or str(config.get_workspace_dir())
        process = await asyncio.create_subprocess_exec(
            _resolve_command(row["command"]), *[str(a) for a in args],
            cwd=cwd, env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=nova_tools.NO_WINDOW,
        )
        connection = Connection(agent_id=agent_id, name=row["name"], process=process)
        connection.reader_task = asyncio.create_task(_pump_stdout(connection))
        connection.stderr_task = asyncio.create_task(_pump_stderr(connection))
        _connections[agent_id] = connection

        try:
            result = await _request(connection, "initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True},
                    "terminal": False,
                },
            }, timeout=STARTUP_TIMEOUT)
        except ACPError:
            await disconnect(agent_id)
            tail = "\n".join(connection.stderr_tail[-6:])
            raise ACPError(
                f"{row['name']} did not complete the ACP handshake."
                + (f" Its output was:\n{tail}" if tail else "")
            ) from None
        connection.capabilities = result.get("agentCapabilities") or {}
        connection.auth_methods = result.get("authMethods") or []
        return connection


async def disconnect(agent_id: int) -> None:
    connection = _connections.pop(agent_id, None)
    if connection is None:
        return
    for task in (connection.reader_task, connection.stderr_task):
        if task is not None:
            task.cancel()
    if connection.alive():
        try:
            connection.process.terminate()
            await asyncio.wait_for(connection.process.wait(), 5)
        except Exception:  # noqa: BLE001 - kill below is the backstop
            try:
                connection.process.kill()
            except Exception:  # noqa: BLE001
                pass


async def shutdown_all() -> None:
    for agent_id in list(_connections):
        await disconnect(agent_id)


async def new_session(agent_id: int, cwd: str | None = None) -> Session:
    connection = await connect(agent_id)
    working = str(Path(cwd).resolve()) if cwd else str(config.get_workspace_dir())
    result = await _request(connection, "session/new", {
        "cwd": working,
        "mcpServers": await _mcp_servers_for_agent(),
    }, timeout=STARTUP_TIMEOUT)
    session_id = result.get("sessionId")
    if not session_id:
        raise ACPError(f"{connection.name} did not return a session id.")
    session = Session(session_id=session_id, cwd=working)
    connection.sessions[session_id] = session
    return session


async def _mcp_servers_for_agent() -> list[dict]:
    """Hand the agent Nova's own stdio MCP servers so it inherits the same
    tools. Remote (http/sse) servers are skipped: their transport shape is not
    part of the ACP session/new payload."""
    servers = []
    try:
        for row in await db.list_mcp_servers(enabled_only=True):
            if (row.get("transport") or "stdio") != "stdio" or not row.get("command"):
                continue
            try:
                args = json.loads(row["args"] or "[]")
                env = json.loads(row["env"] or "{}")
            except ValueError:
                continue
            servers.append({
                "name": row["name"],
                "command": row["command"],
                "args": [str(a) for a in args],
                "env": [{"name": str(k), "value": str(v)} for k, v in env.items()],
            })
    except Exception:  # noqa: BLE001 - an agent with no MCP servers still works
        return []
    return servers


async def prompt(agent_id: int, session_id: str, text: str):
    """Send a prompt and yield the agent's `session/update` stream until it
    stops. Yields dicts shaped like the ACP updates themselves, plus a final
    {"sessionUpdate": "_done", "stopReason": ...}."""
    connection = _connections.get(agent_id)
    if connection is None or not connection.alive():
        raise ACPError("That agent is not connected.")
    session = connection.sessions.get(session_id)
    if session is None:
        raise ACPError("Unknown session.")

    task = asyncio.create_task(_request(connection, "session/prompt", {
        "sessionId": session_id,
        "prompt": [{"type": "text", "text": text}],
    }, timeout=PROMPT_TIMEOUT))

    try:
        while True:
            queue_get = asyncio.create_task(session.updates.get())
            done, _ = await asyncio.wait({queue_get, task}, return_when=asyncio.FIRST_COMPLETED)
            if queue_get in done:
                update = queue_get.result()
                if update.get("sessionUpdate") == "_closed":
                    break
                yield update
                continue
            queue_get.cancel()
            # The prompt call returned: drain whatever is already queued so no
            # final chunk is lost to the race, then stop.
            while not session.updates.empty():
                update = session.updates.get_nowait()
                if update.get("sessionUpdate") != "_closed":
                    yield update
            break
        result = await task
        yield {"sessionUpdate": "_done", "stopReason": result.get("stopReason", "end_turn")}
    finally:
        if not task.done():
            task.cancel()


async def cancel(agent_id: int, session_id: str) -> None:
    connection = _connections.get(agent_id)
    if connection is None or not connection.alive():
        return
    try:
        await _write(connection, {"method": "session/cancel", "params": {"sessionId": session_id}})
    except Exception:  # noqa: BLE001 - cancelling a dead agent is a no-op
        pass


def text_of(update: dict) -> str:
    """The displayable text in one update, or "" for updates that carry none
    (tool calls, plans, availability changes)."""
    if update.get("sessionUpdate") not in ("agent_message_chunk", "agent_thought_chunk"):
        return ""
    content = update.get("content") or {}
    if isinstance(content, dict):
        return content.get("text") or ""
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


async def status(agent_id: int) -> dict:
    row = await db.get_acp_agent(agent_id)
    connection = _connections.get(agent_id)
    return {
        "id": agent_id,
        "name": row["name"] if row else None,
        "installed": bool(row and shutil.which(row["command"])),
        "connected": bool(connection and connection.alive()),
        "capabilities": connection.capabilities if connection else {},
        "auth_methods": connection.auth_methods if connection else [],
        "sessions": len(connection.sessions) if connection else 0,
        "stderr_tail": connection.stderr_tail[-6:] if connection else [],
    }


async def run_once(agent_id: int, text: str, cwd: str | None = None) -> str:
    """Connect, open a session, prompt, and return the agent's full reply.
    Used by the `delegate_to_agent` tool, where Nova wants a result rather than
    a stream."""
    session = await new_session(agent_id, cwd)
    parts: list[str] = []
    tools: list[str] = []
    async for update in prompt(agent_id, session.session_id, text):
        kind = update.get("sessionUpdate")
        if kind == "_done":
            break
        if kind == "tool_call":
            title = update.get("title") or update.get("kind")
            if title:
                tools.append(str(title))
        parts.append(text_of(update))
    reply = "".join(parts).strip()
    if tools:
        reply += "\n\n_Actions taken: " + ", ".join(dict.fromkeys(tools[:12])) + "_"
    return reply or "The agent finished without producing any text."
