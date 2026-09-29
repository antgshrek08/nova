"""Nova's hands in Onyx, the user's own browser.

Onyx exposes itself as a local MCP server (see the Onyx repo,
docs/superpowers/specs/2026-09-24-onyx-agent-surface-design.md). Through it
Nova gets a browser it drives with a cursor you can watch: every click glides
a second pointer -- tagged "Nova" -- to its target and presses with a real,
trusted mouse event, over the page, without ever touching the user's own
mouse. It keeps working while Onyx is behind a game or minimised.

Why not keep driving Edge through Playwright for everything: some sites
ignore scripted clicks and only respond to a pointer that actually travels
there (hover menus, buttons that arm on mouseenter). Onyx's clicks are real
mouse events along a real path, which is what those sites need.

Transport is plain JSON-RPC over HTTP to 127.0.0.1, authenticated by the
token Onyx writes to its data folder. No SDK: Nova needs six calls, and the
Python MCP SDK's client API has already changed shape once under us.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import re
import subprocess
from pathlib import Path

import httpx

AGENT_NAME = "Nova"
LAUNCH_TIMEOUT_S = 30.0
CALL_TIMEOUT_S = 120.0


class OnyxError(RuntimeError):
    """Onyx answered, and the answer was a refusal or a failure."""


class OnyxUnavailable(OnyxError):
    """There is no Onyx to talk to: not installed, or it would not start."""


def _appdata() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).name().lower().startswith("onyx")
    except Exception:  # noqa: BLE001 -- psutil missing or the process vanished: treat as gone
        return False


# Which Onyx window Nova drives, from the browser visibility setting (see
# browser_control.visibility): "hidden" is Nova's own profile (nova-window.ts),
# a second, always-hidden window with its own session, so the user's mouse or
# keyboard in their window never lands in a tab Nova is driving. "visible" is
# the user's open Onyx window, so they can watch -- and taking over pauses Nova.
_visibility = "hidden"


def set_visibility(mode: str) -> None:
    global _visibility
    _visibility = "visible" if mode == "visible" else "hidden"


def endpoint_path(visibility: str | None = None) -> Path:
    nova_ep = _appdata() / "onyx" / "agent-endpoint-nova.json"
    if (visibility or _visibility) != "visible":
        return nova_ep
    main_ep = _appdata() / "onyx" / "agent-endpoint.json"
    try:
        data = json.loads(main_ep.read_text(encoding="utf-8"))
        if _pid_alive(data.get("pid", 0)):
            return main_ep
    except (OSError, ValueError, AttributeError):
        pass
    # The user's window is not open: work in Nova's own rather than fail.
    return nova_ep


def exe_candidates(configured: str = "") -> list[Path]:
    """Where Onyx might be, most specific first: the path the user set, the
    per-user install the NSIS installer makes, then the local dev build."""
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    if os.name == "nt":
        candidates.append(local / "Programs" / "onyx" / "Onyx.exe")
    elif sys.platform == "darwin":
        candidates += [Path("/Applications/Onyx.app/Contents/MacOS/Onyx"),
                       Path.home() / "Applications" / "Onyx.app" / "Contents" / "MacOS" / "Onyx"]
    else:
        candidates += [Path("/usr/bin/onyx"), Path("/opt/Onyx/onyx"), Path.home() / "Applications" / "Onyx.AppImage"]
    return candidates


def find_exe(configured: str = "") -> Path | None:
    """The Onyx to launch. A path the user configured always wins. Otherwise
    the most recently built copy: an old installed Onyx from before agent
    control existed would start, open no agent port, and look exactly like
    a hang -- which is what happened the first time this ran for real."""
    if configured and Path(configured).is_file():
        return Path(configured)
    found = [p for p in exe_candidates() if p.is_file()]
    return max(found, key=lambda p: p.stat().st_mtime, default=None)


def read_endpoint(path: Path | None = None) -> dict | None:
    """The endpoint file, if it is well-formed and its process is alive. A
    file left behind by a crashed Onyx points at a port some other process
    may now own, so a dead pid means no endpoint."""
    try:
        data = json.loads((path or endpoint_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not (isinstance(data, dict) and isinstance(data.get("url"), str)
            and isinstance(data.get("token"), str) and isinstance(data.get("pid"), int)):
        return None
    if not data["url"].startswith("http://127.0.0.1:"):
        return None  # never send the token anywhere but loopback
    if not _pid_alive(data["pid"]):
        return None
    return data


# A hook so tests can hand in an httpx.MockTransport.
_transport: httpx.AsyncBaseTransport | None = None
_rpc_id = 0


async def _rpc(endpoint: dict, method: str, params: dict | None = None) -> dict:
    global _rpc_id
    _rpc_id += 1
    headers = {
        "Authorization": f"Bearer {endpoint['token']}",
        "Accept": "application/json, text/event-stream",
        "X-Agent-Name": AGENT_NAME,
    }
    async with httpx.AsyncClient(transport=_transport, timeout=CALL_TIMEOUT_S) as client:
        response = await client.post(
            endpoint["url"], headers=headers,
            json={"jsonrpc": "2.0", "id": _rpc_id, "method": method, "params": params or {}},
        )
    if response.status_code == 401:
        raise OnyxError("Onyx refused Nova's key -- it has probably restarted; try again.")
    if response.status_code >= 400:
        raise OnyxError(f"Onyx answered HTTP {response.status_code}.")
    body = response.json()
    if "error" in body:
        raise OnyxError(body["error"].get("message", "Onyx reported an error."))
    return body.get("result") or {}


async def _ping(endpoint: dict) -> bool:
    try:
        await _rpc(endpoint, "tools/list")
        return True
    except (OnyxError, httpx.HTTPError, ValueError):
        return False


def _launch(exe: Path) -> None:
    # Detached, so Onyx outlives a Nova restart; --background so starting it
    # never pulls the user out of whatever is in front (a game, a video).
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(  # noqa: S603 -- a fixed, located executable with fixed flags
        [str(exe), "--agent-control", "--background"],
        close_fds=True, creationflags=flags,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


async def ensure(configured_path: str = "") -> dict:
    """An endpoint that answers, starting Onyx if it has to.

    If Onyx is open without agent control, launching it again with
    --agent-control hands the flag to the running window (Onyx is single
    instance) and switches control on for that session only.
    """
    endpoint = read_endpoint()
    if endpoint and await _ping(endpoint):
        return endpoint
    exe = find_exe(configured_path)
    if exe is None:
        raise OnyxUnavailable(
            "Onyx is not installed where Nova looks for it "
            f"({', '.join(str(p) for p in exe_candidates(configured_path))})."
        )
    _launch(exe)
    deadline = asyncio.get_running_loop().time() + LAUNCH_TIMEOUT_S
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.5)
        endpoint = read_endpoint()
        if endpoint and await _ping(endpoint):
            return endpoint
    raise OnyxUnavailable(f"Started {exe} but it did not open its agent port within {int(LAUNCH_TIMEOUT_S)}s.")


async def call(tool: str, configured_path: str = "", **arguments) -> dict:
    """Run one Onyx tool. Returns its JSON result, or {'_image': base64} for
    a screenshot. A tool-level refusal ("ref 12 is stale", "Paused: you took
    over") raises OnyxError with Onyx's own words, which are written to be
    read by the model and acted on."""
    endpoint = await ensure(configured_path)
    args = {k: v for k, v in arguments.items() if v is not None}
    result = await _rpc(endpoint, "tools/call", {"name": tool, "arguments": args})
    content = (result.get("content") or [{}])[0]
    if result.get("isError"):
        raise OnyxError(content.get("text", "Onyx could not do that."))
    if content.get("type") == "image":
        return {"_image": content.get("data", "")}
    try:
        return json.loads(content.get("text") or "{}")
    except ValueError:
        return {"text": content.get("text", "")}


# ---------------------------------------------------------------------------
# Translating Nova's browser_act vocabulary into Onyx targets

_REF = re.compile(r"^\s*(?:ref\s*[=:#]?\s*)?\[?(\d+)\]?\s*$", re.IGNORECASE)
_TEXT = re.compile(r"""^\s*text\s*=\s*(["']?)(.+?)\1\s*$""", re.IGNORECASE)
# A pixel point on the page, for dragging to a spot computed from a graph's
# own box and axis range (see describe_elements' "graph" note) -- there is no
# element there to click by ref or text.
_POINT = re.compile(r"^\s*x\s*=\s*(-?\d+(?:\.\d+)?)\s*,\s*y\s*=\s*(-?\d+(?:\.\d+)?)\s*$", re.IGNORECASE)


def target(selector: str | None) -> dict:
    """What `inspect` printed ("12", "[12]", "ref=12"), a `text=Label`,
    `x=123,y=456` (a page pixel point -- see _POINT), or otherwise a CSS
    selector -- in that order. A number is always a ref: `inspect` hands out
    refs, and a bare number is never a useful CSS selector."""
    if not selector:
        return {}
    if m := _REF.match(selector):
        return {"ref": int(m.group(1))}
    if m := _TEXT.match(selector):
        return {"text": m.group(2)}
    if m := _POINT.match(selector):
        return {"x": float(m.group(1)), "y": float(m.group(2))}
    return {"selector": selector}


def _graph_pixel(axis: dict, box: dict, x: float, y: float) -> tuple[float, float]:
    """A data-space point on a graph, as a pixel point in the box -- see
    describe_elements' "graph" note and SnapshotElement.graph in Onyx."""
    px = box["x"] + (x - axis["xMin"]) / (axis["xMax"] - axis["xMin"]) * box["width"]
    py = box["y"] + (axis["yMax"] - y) / (axis["yMax"] - axis["yMin"]) * box["height"]
    return px, py


def describe_elements(elements: list[dict], limit: int = 250) -> str:
    """The page map as lines a model can act on: `[ref] role "name"`.

    A password field is listed so it can be filled with type_secret, but its
    value never appears -- Onyx does not send it, and this does not ask."""
    lines = []
    for el in elements[:limit]:
        line = f"[{el.get('ref')}] {el.get('role', 'element')} \"{el.get('name', '')}\""
        if el.get("math"):
            line += " (math box -- fill it; ^ for powers, / for fractions, parentheses around each)"
        if el.get("graph"):
            g, b = el["graph"], el["box"]
            origin = _graph_pixel(g, b, 0, 0)
            line += (f" (graph, axis x:{g['xMin']}..{g['xMax']} y:{g['yMin']}..{g['yMax']}, box "
                     f"x:{b['x']} y:{b['y']} w:{b['width']} h:{b['height']} -- data (0,0) is at pixel "
                     f"x={origin[0]:.0f},y={origin[1]:.0f}; for another data point (dx,dy), pixel x is "
                     f"box.x + (dx-xMin)/(xMax-xMin)*box.width and pixel y is box.y + (yMax-dy)/(yMax-yMin)*box.height "
                     "-- y is flipped. Drag with browser_act using selector/to=\"x=<px>,y=<py>\")")
        if el.get("frame"):
            line += f" (in {el['frame']})"
        if el.get("secret"):
            line += " (secret field -- fill it with type_secret; its value is never shown)"
        elif el.get("value"):
            line += f" = \"{el['value']}\""
        if el.get("checked") is not None:
            line += " [checked]" if el["checked"] else " [unchecked]"
        if el.get("disabled"):
            line += " (disabled)"
        if not el.get("inViewport", True):
            line += " (off screen)"
        lines.append(line)
    if len(elements) > limit:
        lines.append(f"... {len(elements) - limit} more not shown")
    return "\n".join(lines)
