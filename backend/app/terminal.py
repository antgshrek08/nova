"""Real interactive terminals, one per session, over a WebSocket.

A PTY rather than a subprocess pipe, because the difference is everything a
terminal is for: programs that check `isatty()` behave normally, `git log`
pages, prompts and progress bars render, and Ctrl-C reaches the foreground
process instead of the parent. `nova_tools.run_command` already covers
"run this and give me the output" -- this covers "let me drive it."

Output is streamed raw (escape sequences and all) and rendered by xterm.js on
the other end; nothing here interprets ANSI.

Lifetime is tied to the session, not to a request: the process keeps running
while the panel is closed, and is killed on explicit close or backend shutdown.
Every spawn is registered in `_sessions` so shutdown can reach it -- the same
lesson as providers.py's orphaned-CLI bug.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field

from . import config

MAX_SESSIONS = 8
READ_CHUNK = 8192
IDLE_REAP_SECONDS = 60 * 60 * 6   # a forgotten terminal should not live forever
SCROLLBACK_BYTES = 200_000

log = logging.getLogger(__name__)


class TerminalError(RuntimeError):
    """Spawn or lookup failure, phrased for display."""


@dataclass
class Session:
    id: str
    process: object                  # winpty.PtyProcess
    shell: str
    cwd: str
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    scrollback: bytearray = field(default_factory=bytearray)
    subscribers: set = field(default_factory=set)
    reader: asyncio.Task | None = None

    def alive(self) -> bool:
        try:
            return self.process.isalive()
        except Exception:  # noqa: BLE001 - a dead handle is a dead process
            return False


_sessions: dict[str, Session] = {}


def default_shell() -> str:
    """PowerShell on Windows; zsh/bash on macOS/Linux -- matches run_command."""
    if os.name != "nt":
        return os.environ.get("SHELL") or shutil.which("zsh") or shutil.which("bash") or shutil.which("sh") or "/bin/sh"
    return (
        shutil.which("pwsh.exe")
        or shutil.which("powershell.exe")
        or shutil.which("cmd.exe")
        or "cmd.exe"
    )


def _reap_idle() -> None:
    cutoff = time.time() - IDLE_REAP_SECONDS
    for session in list(_sessions.values()):
        if not session.alive() or (session.last_used < cutoff and not session.subscribers):
            close(session.id)


def create(cwd: str | None = None, shell: str | None = None, cols: int = 120, rows: int = 30) -> Session:
    _reap_idle()
    if len(_sessions) >= MAX_SESSIONS:
        raise TerminalError(f"Too many open terminals ({MAX_SESSIONS}). Close one first.")

    if os.name == "nt":
        try:
            from winpty import PtyProcess
        except ImportError as exc:  # noqa: BLE001
            raise TerminalError(
                "Interactive terminals on Windows need pywinpty: pip install pywinpty"
            ) from exc
    else:
        try:
            from ptyprocess import PtyProcess
        except ImportError as exc:  # noqa: BLE001
            raise TerminalError(
                "Interactive terminals on Unix/macOS need ptyprocess: pip install ptyprocess"
            ) from exc

    working = str(config.get_workspace_dir())
    if cwd:
        from . import nova_tools
        working = str(nova_tools._resolve_any(cwd))

    command = shell or default_shell()
    try:
        dims = (max(6, min(rows, 200)), max(20, min(cols, 500)))
        if os.name == "nt":
            process = PtyProcess.spawn(command, cwd=working, dimensions=dims)
        else:
            argv = [command] if isinstance(command, str) else list(command)
            process = PtyProcess.spawn(argv, cwd=working, dimensions=dims)
    except Exception as exc:  # noqa: BLE001
        raise TerminalError(f"Could not start {command}: {exc}") from exc

    session = Session(id=uuid.uuid4().hex[:12], process=process, shell=command, cwd=working)
    _sessions[session.id] = session
    session.reader = asyncio.get_running_loop().create_task(_pump(session))
    return session


async def _pump(session: Session) -> None:
    """Read the PTY forever and fan out to subscribers.

    winpty's read is blocking, so it runs in a worker thread. A closed PTY
    raises rather than returning EOF, which is the normal exit path.
    """
    loop = asyncio.get_running_loop()
    try:
        while True:
            try:
                data = await loop.run_in_executor(None, session.process.read, READ_CHUNK)
            except Exception:  # noqa: BLE001 - EOF / closed handle
                break
            if not data:
                if not session.alive():
                    break
                await asyncio.sleep(0.03)
                continue
            raw = data.encode("utf-8", "replace") if isinstance(data, str) else data
            session.scrollback.extend(raw)
            if len(session.scrollback) > SCROLLBACK_BYTES:
                del session.scrollback[: len(session.scrollback) - SCROLLBACK_BYTES]
            for queue in list(session.subscribers):
                queue.put_nowait(raw)
    except asyncio.CancelledError:
        raise
    finally:
        for queue in list(session.subscribers):
            queue.put_nowait(None)  # sentinel: the shell exited


def get(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise TerminalError("That terminal is no longer open.")
    session.last_used = time.time()
    return session


def write(session_id: str, data: str) -> None:
    session = get(session_id)
    try:
        session.process.write(data)
    except Exception as exc:  # noqa: BLE001
        raise TerminalError(f"Terminal write failed: {exc}") from exc


def resize(session_id: str, cols: int, rows: int) -> None:
    session = get(session_id)
    try:
        session.process.setwinsize(max(6, min(rows, 200)), max(20, min(cols, 500)))
    except Exception:  # noqa: BLE001 - not fatal; the shell just keeps its old size
        pass


def close(session_id: str) -> bool:
    session = _sessions.pop(session_id, None)
    if session is None:
        return False
    if session.reader is not None:
        session.reader.cancel()
    try:
        session.process.terminate(force=True)
    except Exception:  # noqa: BLE001 - already gone
        pass
    for queue in list(session.subscribers):
        queue.put_nowait(None)
    return True


def listing() -> list[dict]:
    _reap_idle()
    return [
        {
            "id": s.id,
            "shell": os.path.basename(s.shell),
            "cwd": s.cwd,
            "alive": s.alive(),
            "viewers": len(s.subscribers),
            "age_seconds": round(time.time() - s.created_at),
        }
        for s in _sessions.values()
    ]


async def shutdown_all() -> None:
    for session_id in list(_sessions):
        close(session_id)
