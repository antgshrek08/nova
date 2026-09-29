"""Real MCP (Model Context Protocol) client support.

Two transports, selected per-server by the `transport` column:
- stdio (the original, still the default): a command + args (+ optional
  extra env vars), the same shape as Claude Desktop's mcpServers config.
- http / sse (new -- see mcp_oauth.py): a remote server reached over
  Streamable HTTP or SSE, optionally behind OAuth 2.0 (dynamic client
  registration + authorization-code/PKCE, handled by the SDK's own
  OAuthClientProvider). Mechanism only for this session -- real and
  complete, but not yet exercised against a live provider; see
  mcp_oauth.py's module docstring.

Connections are opened on-demand for each interaction (a status check, or a
single tool call) and closed immediately after, rather than held open in
the background for the app's lifetime, for both transports. That's
deliberate: this session's earlier CLI-subprocess bug (providers.py's
_stream_cli leaving an orphaned claude.exe running after a client
disconnect) was exactly this class of mistake -- a long-lived connection
with a cleanup path that could be missed. A fresh per-interaction
connection costs ~100-500ms (stdio) or one HTTP round trip (remote) to
establish, which is fine at chat cadence and impossible to leak.
"""
from __future__ import annotations

import asyncio
import json
import hashlib
import logging
import time
from mcp.types import PaginatedRequestParams
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from . import mcp_oauth

# Phase 3 (RESEARCH.md, 2026-09-04): bumped from 15 -- ypollak2/llm-router's
# real stdio MCP server does genuine cold-start work (Ollama/vLLM local-
# platform probing, dynamic routing init) that took ~27s live on this
# machine, well past the old timeout, so it never got a chance to finish
# before being marked disconnected. Every other configured server responds
# in well under a second either way, so this only meaningfully changes how
# long a genuinely broken/hung server takes to report as such -- a real,
# deliberate tradeoff (flagged to and confirmed by the user, not made
# unprompted), not a free win.
MCP_CONNECT_TIMEOUT_SECONDS = 35


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict


@dataclass
class MCPStatus:
    connected: bool
    tools: list[MCPTool] = field(default_factory=list)
    error: str | None = None


def _parse_env(env_json: str) -> dict[str, str] | None:
    try:
        parsed = json.loads(env_json or "{}")
    except (TypeError, ValueError):
        raise ValueError("MCP environment must be a JSON object")
    if not isinstance(parsed, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in parsed.items()):
        raise ValueError("MCP environment keys and values must be strings")
    return parsed or None


def _parse_args(args_json: str) -> list[str]:
    try:
        parsed = json.loads(args_json or "[]")
    except (TypeError, ValueError):
        raise ValueError("MCP arguments must be a JSON array")
    if not isinstance(parsed, list) or any(not isinstance(a, str) for a in parsed):
        raise ValueError("MCP arguments must be strings")
    return parsed


async def _list_all_tools(session):
    tools, cursor, seen = [], None, set()
    for _ in range(100):
        page = await session.list_tools(params=PaginatedRequestParams(cursor=cursor) if cursor else None)
        tools.extend(page.tools)
        cursor = page.next_cursor
        if not cursor:
            return tools
        if cursor in seen:
            raise ValueError("MCP server repeated its pagination cursor")
        seen.add(cursor)
    raise ValueError("MCP tool discovery exceeded 100 pages")


def _tool_result_text(result) -> str:
    parts = [block.text for block in result.content if hasattr(block, 'text')]
    if result.structured_content is not None:
        parts.append(json.dumps(result.structured_content, default=str))
    text = '\n'.join(parts) or 'Tool returned no text content.'
    if result.is_error:
        text = 'Tool reported an error: ' + text
    return text[:24000] + ('\n[Tool output truncated]' if len(text) > 24000 else '')


_status_cache = {}
_status_locks = {}
_discovery_slots = asyncio.Semaphore(3)


async def check_server_from_row(row: dict, interactive: bool = False) -> MCPStatus:
    if interactive:
        status = await _check_server_from_row(row, True)
        _status_cache.pop(row['id'], None)
        return status
    fingerprint = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()
    async with _status_locks.setdefault(row['id'], asyncio.Lock()):
        cached = _status_cache.get(row['id'])
        if cached and cached[0] == fingerprint and cached[1] > time.monotonic():
            return cached[2]
        async with _discovery_slots:
            status = await _check_server_from_row(row)
        _status_cache[row['id']] = (fingerprint, time.monotonic() + (60 if status.connected else 10), status)
        return status


@asynccontextmanager
async def _open_streams(row: dict, interactive: bool):
    """Yields (read, write) streams for one mcp_servers row, over whichever
    transport it's configured for. stdio spawns a subprocess (unchanged from
    before this transport existed); http/sse open a real network connection,
    with one of two auth modes (see the static_headers block below): a
    static `Authorization`-style header (for servers like Context7 that use
    a plain API key, not OAuth), or an OAuthClientProvider that makes an
    expired/missing token transparently trigger the auth flow instead of
    just failing with a 401. `interactive` picks which OAuth provider (only
    relevant when there's no static header): mcp_oauth.make_provider
    actually waits for a human to complete sign-in (only appropriate for
    the explicit /mcp/servers/{id}/connect flow); make_noninteractive_
    provider fails fast with AuthRequiredError instead, for passive status
    checks and the /chat tool-roster fetch that run unattended.
    """
    transport = row.get("transport") or "stdio"
    if transport == "stdio":
        params = StdioServerParameters(
            command=row["command"], args=_parse_args(row["args"]), env=_parse_env(row["env"]) or None
        )
        async with stdio_client(params) as streams:
            yield streams
        return

    url = row["url"]
    # Static-header auth (integration-plan Phase 0, 2026-09-03): some remote
    # MCP servers (Context7) use a plain `Authorization: Bearer <key>`
    # header instead of full OAuth. The `env` column already exists for
    # stdio's subprocess env vars and isn't otherwise used for http/sse rows,
    # so it doubles as a header dict here -- avoids a DB migration for a
    # second auth mode. If a row has headers set, use those directly and
    # skip attaching the OAuthClientProvider entirely: mixing the two would
    # mean every request also carries the provider's own auth_flow (token
    # lookup, possible discovery/refresh calls), which could fail or
    # interfere for a server that was never taken through the OAuth dance in
    # the first place. Rows with no headers keep the original OAuth-only
    # behavior, unchanged.
    static_headers = _parse_env(row["env"])
    provider = (
        None
        if static_headers
        else (
            mcp_oauth.make_provider(row["id"], url)
            if interactive
            else mcp_oauth.make_noninteractive_provider(row["id"], url)
        )
    )
    if transport == "sse":
        async with sse_client(url, headers=static_headers, auth=provider) as streams:
            yield streams
        return
    if transport == "http":
        client = create_mcp_http_client(auth=provider, headers=static_headers)
        # terminate_on_close=False: the default (True) sends a DELETE to the
        # server on exit to explicitly end the session -- reproduced live,
        # that DELETE round trip hangs past this module's own connect
        # timeout on this SDK version (server log shows "Terminating
        # session" logged, then nothing -- the response never comes back to
        # the client). Every connection here is already short-lived and
        # per-interaction (see this module's docstring), so an
        # unterminated session on the server side sitting until its own
        # idle timeout is a fine trade for not hanging every single call.
        async with streamable_http_client(url, http_client=client, terminate_on_close=False) as (read, write):
            yield read, write
        return
    raise ValueError(f"Unknown MCP transport '{transport}'.")


async def _check_server_from_row(row: dict, interactive: bool = False) -> MCPStatus:
    """Connect, list tools, disconnect. Used both for the Settings status
    check and to build the tool roster injected into chat requests
    (interactive=False in both cases -- see _open_streams). interactive=True
    is only used from main.py's /mcp/servers/{id}/connect, which is the one
    path meant to actually wait on a human completing OAuth sign-in; its
    timeout is set by the caller (mcp_oauth.FLOW_TIMEOUT_SECONDS plus
    slack), not MCP_CONNECT_TIMEOUT_SECONDS below."""
    timeout = MCP_CONNECT_TIMEOUT_SECONDS if not interactive else mcp_oauth.FLOW_TIMEOUT_SECONDS + 15
    try:
        async with asyncio.timeout(timeout):
            async with _open_streams(row, interactive) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    discovered = await _list_all_tools(session)
                    tools = [
                        MCPTool(
                            name=t.name,
                            description=t.description or "",
                            input_schema=t.input_schema or {"type": "object", "properties": {}},
                        )
                        for t in discovered
                    ]
                    return MCPStatus(connected=True, tools=tools)
    except mcp_oauth.AuthRequiredError as exc:
        return MCPStatus(connected=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - a server being down/misconfigured is a normal state
        return MCPStatus(connected=False, error=str(exc))
    finally:
        mcp_oauth.forget_server(row["id"])


async def call_tool_from_row(row: dict, tool_name: str, arguments: dict) -> str:
    """Open a fresh connection, call one tool, return its text result,
    close. Never interactive -- a mid-chat tool call that suddenly needed a
    fresh OAuth sign-in would have nobody to wait on either; it surfaces as
    a normal tool-call error instead (the model sees it, same as any other
    tool failure), and the user re-authenticates from Settings."""
    try:
        async with asyncio.timeout(MCP_CONNECT_TIMEOUT_SECONDS):
            async with _open_streams(row, interactive=False) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    return _tool_result_text(result)
    finally:
        mcp_oauth.forget_server(row["id"])


async def call_tool_interactive(row: dict, tool_name: str, arguments: dict) -> str:
    """Same as call_tool_from_row, but with a real *interactive* OAuth
    provider (mcp_oauth.make_provider -- waits for a human to complete
    sign-in via the pending-flow registry, same mechanism
    check_server_from_row(interactive=True) uses for /mcp/servers/{id}/
    connect). Needed because tool *discovery* (initialize + list_tools) on
    Gmail/Calendar's MCP servers doesn't require auth at all -- confirmed
    live -- so the existing /connect flow (which only does discovery) never
    actually reaches the OAuth wall. A real tool call is what triggers it.
    Used by main.py's /mcp/servers/{id}/call, the one path that exercises
    real tool invocation with a live human able to complete sign-in.
    """
    try:
        async with asyncio.timeout(mcp_oauth.FLOW_TIMEOUT_SECONDS + 15):
            async with _open_streams(row, interactive=True) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    return _tool_result_text(result)
    finally:
        mcp_oauth.forget_server(row["id"])


async def status_for_row(row: dict) -> dict:
    """Live status for one mcp_servers DB row, shaped for the Settings UI."""
    try:
        status = await check_server_from_row(row) if row["enabled"] else MCPStatus(connected=False)
        args = _parse_args(row["args"])
    except (ValueError, KeyError) as exc:
        status = MCPStatus(connected=False, error=str(exc))
        args = []
    return {
        "id": row["id"],
        "name": row["name"],
        "transport": row.get("transport") or "stdio",
        "command": row["command"],
        "args": args,
        "url": row.get("url"),
        "enabled": bool(row["enabled"]),
        "connected": status.connected,
        "error": status.error,
        # Best-effort, not authoritative: a status check that failed for a
        # reason OTHER than AuthRequiredError (server down, bad command)
        # looks the same as "never tried" here -- the frontend uses this to
        # decide whether to show a "Sign in" button, and a false negative
        # just means the button doesn't appear until the next successful
        # probe, not a broken state.
        "needs_auth": status.error is not None and "OAuth sign-in" in status.error,
        "tools": [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in status.tools
        ],
    }


@dataclass
class ResolvedTool:
    server_id: int
    server_name: str
    row: dict
    tool_name: str = ""


_ROSTER_TTL_SECONDS = 300
# A roster where some server failed is not the same answer as a complete one
# and must not be kept as long. Found the hard way: warming the roster at
# startup races the MCP servers Electron launches separately, so the first
# build had both Google Workspace servers missing -- and caching that for five
# minutes meant no Gmail or Calendar tools for five minutes after every
# launch, with Settings still showing them connected. Retry soon instead.
_PARTIAL_ROSTER_TTL_SECONDS = 20
_roster_cache: dict = {"at": 0.0, "schemas": [], "index": {}, "partial": False}
_roster_refresh: asyncio.Task | None = None

# A backstop, not a performance cap -- see the comment in _timed(). Long
# enough that the slowest real server here (27s) still connects.
_PER_SERVER_TIMEOUT = 60.0
# Worth saying out loud in the log: one server at this level sets the cold
# cost of the whole roster.
_SLOW_SERVER_SECONDS = 8.0
# What the last roster build actually found, per server, so Settings can show
# "connected, 11 tools, 27.3s" instead of leaving a silent gap.
_last_roster_report: list[dict] = []


def last_roster_report() -> list[dict]:
    """Per-server outcome of the most recent roster build."""
    return list(_last_roster_report)


async def cached_tools_for_chat(timeout: float = 75) -> tuple[list[dict], dict[str, ResolvedTool]]:
    """The tool roster, without paying for it on every message.

    enabled_tools_for_chat() opens a real connection to every enabled server.
    Measured on this machine with 10 servers: **29.2 seconds** for 96 tools.
    Doing that per request is untenable, and a short timeout around it is worse
    than useless -- it drops the whole roster silently, which is exactly what
    was happening (a 20s cap meant chat had no MCP tools at all while Settings
    showed ten servers connected).

    So: serve the cache when it is warm, refresh in the background when it goes
    stale, and only block on a cold start. A roster that is five minutes old is
    a far better answer than no roster.
    """
    global _roster_refresh

    age = time.monotonic() - _roster_cache["at"]
    have = bool(_roster_cache["index"]) or _roster_cache["at"] > 0
    ttl = _PARTIAL_ROSTER_TTL_SECONDS if _roster_cache.get("partial") else _ROSTER_TTL_SECONDS

    if have and age < ttl:
        return list(_roster_cache["schemas"]), dict(_roster_cache["index"])

    async def refresh() -> None:
        try:
            schemas, index = await asyncio.wait_for(enabled_tools_for_chat(), timeout)
            partial = any(not entry["ok"] for entry in _last_roster_report)
            _roster_cache.update({
                "at": time.monotonic(), "schemas": schemas, "index": index, "partial": partial,
            })
        except Exception:  # noqa: BLE001 - a failed refresh keeps the previous roster
            logging.getLogger(__name__).warning("MCP tool roster refresh failed", exc_info=True)
            _roster_cache["at"] = time.monotonic()  # don't hammer a broken server every message

    if have:
        # Stale but usable: hand it back now, update behind the request.
        if _roster_refresh is None or _roster_refresh.done():
            _roster_refresh = asyncio.create_task(refresh())
        return list(_roster_cache["schemas"]), dict(_roster_cache["index"])

    await refresh()
    return list(_roster_cache["schemas"]), dict(_roster_cache["index"])


def invalidate_roster() -> None:
    """Called when a server is added, removed, or toggled, so the next message
    sees the change rather than waiting out the TTL."""
    _roster_cache.update({"at": 0.0, "schemas": [], "index": {}, "partial": False})


async def enabled_tools_for_chat() -> tuple[list[dict], dict[str, ResolvedTool]]:
    """Live tool roster from every enabled MCP server, shaped as OpenAI-style
    function-calling tool schemas for litellm's `tools=` kwarg, plus an index
    from tool name -> which server serves it (for dispatching a call_tool).

    Queried fresh per /chat call rather than cached: with typically 0-2
    configured servers this is cheap, and it's the same "always live, never
    stale" principle already used for the Ollama/OpenRouter model rosters.
    """
    from . import db  # local import: avoids a circular import at module load

    rows = await db.list_mcp_servers(enabled_only=True)
    if not rows:
        return [], {}

    async def _timed(row):
        """One server's tools, with its own clock and its own ceiling.

        Per server, not just around the gather: measured on this machine, nine
        servers answer in under 2.4s and one ("LLM Router") takes 27.3, so a
        single row decides what the whole roster costs. The ceiling is
        deliberately generous -- the startup warm-up already keeps that 27s off
        the user's first message, so cutting a merely-slow server off would
        lose its tools to fix a problem that is already fixed. This is a
        backstop against a server that never answers at all.
        """
        started = time.monotonic()
        try:
            status = await asyncio.wait_for(check_server_from_row(row), _PER_SERVER_TIMEOUT)
            return row, status, time.monotonic() - started, None
        except asyncio.TimeoutError:
            return row, None, time.monotonic() - started, f"no response in {_PER_SERVER_TIMEOUT:.0f}s"
        except Exception as exc:  # noqa: BLE001
            return row, None, time.monotonic() - started, f"{type(exc).__name__}: {exc}"

    results = await asyncio.gather(*(_timed(r) for r in rows))

    schemas: list[dict] = []
    index: dict[str, ResolvedTool] = {}
    log = logging.getLogger(__name__)
    _last_roster_report.clear()
    for row, status, elapsed, error in results:
        # Every outcome is recorded, because the failure mode here is silence:
        # a server that does not answer was simply skipped, so Nova ran with
        # fewer tools than Settings claimed and nothing anywhere said so.
        reason = error or (None if (status and status.connected) else "did not connect")
        _last_roster_report.append({
            "id": row["id"], "name": row["name"], "seconds": round(elapsed, 2),
            "tools": len(status.tools) if (status and status.connected) else 0,
            "ok": reason is None, "error": reason,
        })
        if reason:
            log.warning("MCP server %r contributed no tools: %s", row["name"], reason)
        elif elapsed >= _SLOW_SERVER_SECONDS:
            log.warning("MCP server %r took %.1fs to list tools", row["name"], elapsed)
        if reason:
            continue
        for tool in status.tools:
            alias = f"mcp_{row['id']}_{hashlib.sha256(tool.name.encode()).hexdigest()[:16]}"
            resolved = ResolvedTool(server_id=row["id"], server_name=row["name"], row=row, tool_name=tool.name)
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": alias,
                        "description": f"{row['name']} / {tool.name}: {tool.description}"[:1500],
                        "parameters": tool.input_schema,
                    },
                }
            )
            index[alias] = resolved
    return schemas, index
