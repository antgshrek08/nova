"""Nova noticing -- and fixing -- bugs in its own code.

Sentinel records every error Nova hits. Most are the world's fault: a site
that is down, a key that expired, a file that moved. Those are handled where
they happen. This module is for the other kind: an error whose traceback ends
in Nova's own code with the kind of exception that means the code is wrong
(a name that doesn't exist, a None where a value was expected, a missing key).

For each such bug:

1. It is remembered once, by where it happens, with how often it recurs.
2. Depending on Settings > Health > "Fix bugs in Nova's own code":
   - "ask" (the default): the user gets a notification and a Fix button.
   - "auto": Nova repairs it straight away.
   - "off": it is only listed.
3. A repair asks a coding model for the smallest change, as exact
   find/replace edits against the file it failed in, and applies them through
   sentinel.safe_patch_files -- which checkpoints the files, runs Nova's whole
   test suite, and puts everything back if a single test fails. A fix that
   can't prove itself is never kept.

The same bug is tried at most once a day, and there is a daily cap, so a bug
the models can't fix costs a bounded amount and never loops.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from pathlib import Path

from . import operator_store

logger = logging.getLogger(__name__)

KIND = "sentinel_bug"
# Exceptions that mean the code is wrong, not the world.
BUG_TYPES = {
    "NameError", "AttributeError", "TypeError", "KeyError", "IndexError", "UnboundLocalError",
    "ImportError", "ModuleNotFoundError", "ZeroDivisionError", "AssertionError", "RecursionError",
}
MODES = ("ask", "auto", "off")
RETRY_AFTER = 24 * 3600
DAILY_REPAIRS = 5
MODEL_TIMEOUT = 300
EXCERPT_LINES = 60

_LOOP: asyncio.AbstractEventLoop | None = None
_REPAIR_LOCK = asyncio.Lock()


def attach(loop: asyncio.AbstractEventLoop) -> None:
    """Called at startup so errors raised on other threads (logging, workers)
    can hand their follow-up to the engine's event loop."""
    global _LOOP
    _LOOP = loop
    # A repair can't still be running in an engine that just started.
    for bug in operator_store.listing(KIND):
        if bug.get("status") == "fixing":
            bug["status"] = "open"
            _save(bug)


def signature(record: dict) -> str:
    raw = f"{record.get('type')}|{record.get('own_file')}|{record.get('own_line')}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _enabled() -> bool:
    # Tests make errors on purpose; they must never set off a real repair.
    return os.environ.get("NOVA_SELF_HEAL", "1") != "0" and "PYTEST_CURRENT_TEST" not in os.environ


def bugs() -> list[dict]:
    rows = [r for r in operator_store.listing(KIND) if r.get("status") != "dismissed"]
    return sorted(rows, key=lambda r: r.get("last_seen", 0), reverse=True)


def get(sig: str) -> dict | None:
    return operator_store.get(KIND, sig)


def _save(bug: dict) -> dict:
    operator_store.put(KIND, bug["sig"], bug)
    return bug


def dismiss(sig: str) -> bool:
    bug = get(sig)
    if not bug:
        return False
    bug["status"] = "dismissed"
    _save(bug)
    return True


def consider(record: dict) -> dict | None:
    """Sentinel's hook: remember a bug in Nova's own code and decide what next."""
    if record.get("type") not in BUG_TYPES or not record.get("own_file") or not _enabled():
        return None
    sig = signature(record)
    now = time.time()
    bug = get(sig) or {"sig": sig, "first_seen": now, "count": 0, "status": "open", "attempts": []}
    if bug.get("status") == "fixed":
        # The fix only takes effect once Nova restarts; until then the old code
        # can still raise. Only a recurrence after a restart means it came back.
        if bug.get("fixed_at", 0) > _STARTED:
            bug["count"] = bug.get("count", 0) + 1
            bug["last_seen"] = now
            return _save(bug)
        bug["status"] = "open"
    bug.update(
        type=record.get("type"), message=str(record.get("message", ""))[:500], file=record.get("own_file"),
        line=record.get("own_line"), source=record.get("source"), traceback=str(record.get("traceback", ""))[-6000:],
        count=bug.get("count", 0) + 1, last_seen=now,
    )
    _save(bug)
    if bug["status"] == "dismissed":
        return bug
    if _LOOP and not _LOOP.is_closed():
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is _LOOP:
            _LOOP.create_task(_follow_up(sig))
        else:
            asyncio.run_coroutine_threadsafe(_follow_up(sig), _LOOP)
    return bug


_STARTED = time.time()


async def mode() -> str:
    from . import db
    try:
        value = (await db.get_app_settings()).get("self_repair", "ask")
    except Exception:  # noqa: BLE001
        value = "ask"
    return value if value in MODES else "ask"


def _repairs_today() -> int:
    cutoff = time.time() - 24 * 3600
    return sum(1 for b in operator_store.listing(KIND) for a in b.get("attempts", []) if a.get("at", 0) > cutoff)


async def _follow_up(sig: str) -> None:
    try:
        bug = get(sig)
        if not bug or bug.get("status") != "open":
            return
        how = await mode()
        if how == "off":
            return
        if how == "auto":
            recent = bug.get("attempts") and time.time() - bug["attempts"][-1].get("at", 0) < RETRY_AFTER
            if not recent and _repairs_today() < DAILY_REPAIRS:
                await repair(sig)
            return
        if not bug.get("asked"):
            bug["asked"] = time.time()
            _save(bug)
            await _tell("Nova found a bug in its own code",
                        f"{_where(bug)}: {bug.get('message') or bug.get('type')}. Open Settings > Health to let Nova fix it.")
    except Exception:  # noqa: BLE001 -- the follow-up must never become a second bug
        logger.debug("self-heal follow-up failed", exc_info=True)


def _where(bug: dict) -> str:
    return f"{Path(str(bug.get('file'))).name}, line {bug.get('line')}"


async def _tell(title: str, body: str) -> None:
    try:
        from . import notify
        await notify.notify("needs_you", title, body, view="settings", tag="nova-self-repair")
    except Exception:  # noqa: BLE001
        logger.debug("self-heal notification failed", exc_info=True)


# ------------------------------------------------------------------ repair

def excerpt(path: Path, line: int, radius: int = EXCERPT_LINES) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start, end = max(0, line - 1 - radius), min(len(lines), line + radius)
    return "\n".join(f"{n + 1:>5}| {lines[n]}" for n in range(start, end))


def build_prompt(bug: dict, root: Path) -> str:
    path = root / bug["file"]
    return f"""Nova (a desktop assistant written in Python) hit a bug in its own code.

Error: {bug.get('type')}: {bug.get('message')}
Where: {bug['file']}, line {bug.get('line')}

Traceback:
{bug.get('traceback', '')[-4000:]}

The code around line {bug.get('line')} of {bug['file']} (line numbers are for reference, not part of the file):
{excerpt(path, int(bug.get('line') or 1))}

Fix the cause with the smallest correct change. Don't hide the error with a
blanket try/except, don't change behavior that isn't broken, and don't touch
tests. Answer with one or more edits in exactly this form and nothing else:

FILE: {bug['file']}
<<<<<<< FIND
exact lines copied from the file, without the line numbers
=======
the replacement lines
>>>>>>> REPLACE

Each FIND must match the file exactly once, including indentation. Edits may
target other files under backend/app/ if the cause is there.
If you can't tell what the fix is, answer only: NO FIX"""


_EDIT = re.compile(r"FILE:\s*(\S+)\s*\n<<<<<<< FIND\n(.*?)\n=======\n(.*?)\n?>>>>>>> REPLACE", re.S)


def parse_edits(text: str) -> list[tuple[str, str, str]]:
    return [(f.strip().strip("`"), find, replace) for f, find, replace in _EDIT.findall(text or "")]


def apply_edits(edits: list[tuple[str, str, str]], root: Path) -> dict[str, str]:
    """The new content of each file the edits touch. Every FIND must match once."""
    out: dict[str, str] = {}
    for rel, find, replace in edits:
        rel = rel.replace("\\", "/")
        if not rel.startswith("backend/app/") or not rel.endswith(".py") or ".." in rel:
            raise ValueError(f"Edits may only change Nova's engine code, not {rel}")
        current = out.get(rel)
        if current is None:
            current = (root / rel).read_text(encoding="utf-8")
        hits = current.count(find)
        if hits != 1:
            raise ValueError(f"A find block matched {hits} places in {rel}")
        out[rel] = current.replace(find, replace, 1)
    return out


async def _coders() -> list:
    """Coding models to try, best first; each only if it's set up here."""
    from . import routing
    found = []
    for model_id in ("claude_cli_plan", "claude_cli:sonnet", "codex_cli_plan", "codex_cli", "gemini_cli", "antigravity_cli"):
        try:
            result = await routing.resolve_model_id(model_id, "coding", [])
        except Exception:  # noqa: BLE001
            result = None
        if result is not None:
            found.append(result)
        if len(found) == 2:
            break
    return found


async def repair(sig: str) -> dict:
    """Try to fix one bug. The fix is kept only if Nova's tests pass after it."""
    from . import providers, sentinel
    bug = get(sig)
    if not bug:
        return {"ok": False, "error": "That problem is no longer listed."}
    if bug.get("status") == "fixed":
        return {"ok": True, "already": True, "message": "Already fixed."}
    if _REPAIR_LOCK.locked():
        return {"ok": False, "error": "Nova is already fixing something. Try again in a minute."}
    async with _REPAIR_LOCK:
        root = sentinel.get_repo_root()
        if not os.access(sentinel.app_dir(), os.W_OK):
            return _finish(bug, False, "This copy of Nova can't change its own files. Updating Nova gets fixes instead.")
        if not (root / str(bug.get("file"))).is_file():
            return _finish(bug, False, "The file this happened in isn't there any more.")
        coders = await _coders()
        if not coders:
            return _finish(bug, False, "No coding model is set up. Sign in to Claude, Codex or Gemini in Settings > Models.")
        bug["status"] = "fixing"
        _save(bug)
        prompt = build_prompt(bug, root)
        last = "No model suggested a fix."
        for result in coders:
            try:
                text = await asyncio.wait_for(providers.run_model_call(result, [{"role": "user", "content": prompt}]), MODEL_TIMEOUT)
            except Exception as exc:  # noqa: BLE001
                last = f"{result.label} couldn't be reached ({type(exc).__name__})."
                continue
            edits = parse_edits(text)
            if not edits:
                last = f"{result.label} didn't find a fix."
                continue
            try:
                files = apply_edits(edits, root)
            except (ValueError, OSError) as exc:
                last = f"{result.label}'s fix didn't fit the code: {exc}"
                continue
            outcome = await sentinel.safe_patch_files(files)
            if outcome.get("ok"):
                bug.update(fixed_at=time.time(), fixed_by=result.label, files=list(files),
                           checkpoint=outcome.get("checkpoint"))
                done = _finish(bug, True, f"Fixed by {result.label}, and all of Nova's checks pass. "
                               "It takes effect the next time Nova starts.")
                await _tell("Nova fixed a bug in itself", f"{_where(bug)}. Restart Nova to use the fix.")
                return done
            last = f"{result.label}'s fix didn't pass Nova's checks, so it was undone. {outcome.get('error', '')}"[:400]
        done = _finish(bug, False, last)
        await _tell("Nova couldn't fix a bug in itself yet", f"{_where(bug)}. {last}"[:380])
        return done


def _finish(bug: dict, ok: bool, message: str) -> dict:
    bug.setdefault("attempts", []).append({"at": time.time(), "ok": ok, "message": message[:400]})
    bug["attempts"] = bug["attempts"][-10:]
    bug["status"] = "fixed" if ok else "open"
    bug["last_result"] = message[:400]
    _save(bug)
    return {"ok": ok, "message" if ok else "error": message, "bug": bug}


class ErrorLogHandler(logging.Handler):
    """Catches errors that never reach a request: background tasks, the
    scheduler, voice. Anything logged with exception info goes to Sentinel."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self._busy = False

    def emit(self, record: logging.LogRecord) -> None:
        if self._busy or not record.exc_info or record.name.startswith("app.sentinel") or record.name == __name__:
            return
        error = record.exc_info[1]
        if not isinstance(error, Exception):
            return
        self._busy = True
        try:
            from . import sentinel
            sentinel.record_error(f"log:{record.name}", error, {"message": record.getMessage()[:300]})
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._busy = False


def install_log_handler() -> None:
    root = logging.getLogger()
    if not any(isinstance(h, ErrorLogHandler) for h in root.handlers):
        root.addHandler(ErrorLogHandler())
