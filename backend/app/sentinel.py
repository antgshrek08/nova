"""Autonomous Sentinel & Self-Healing Codebase Engine for N.O.V.A.
Monitors runtime exceptions, provides automated diagnostic telemetry,
persists scoped file checkpoints with conflict-aware rollback,
and validates source repairs with syntax, backend tests, and frontend builds.
"""
from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
import json
import logging
from pathlib import Path
import py_compile
import re
import base64
import hashlib
import threading
import uuid
import traceback
from typing import Any

from . import config, selfcheck

logger = logging.getLogger(__name__)

# Bounded in-memory telemetry for recent runtime errors (last 100)
_ERROR_BUFFER: deque[dict[str, Any]] = deque(maxlen=100)
_LAST_CHECKPOINT: dict | None = None
_PATCH_LOCK = threading.Lock()


def clear_error_buffer() -> None:
    """Clears the Sentinel error buffer."""
    _ERROR_BUFFER.clear()


def record_error(source: str, error: Exception | str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Logs and buffers an exception for Sentinel inspection."""
    exc_type = type(error).__name__ if isinstance(error, Exception) else "Error"
    message = str(error)
    tb = traceback.format_exc() if isinstance(error, Exception) else ""
    if tb.strip() == "NoneType: None":
        tb = ""

    # Attempt to locate source file and line from traceback
    fault_file = ""
    fault_line = 0
    if tb:
        matches = list(re.finditer(r'File "([^"]+)", line (\d+)', tb))
        if matches:
            last_match = matches[-1]
            fault_file = last_match.group(1)
            fault_line = int(last_match.group(2))

    record = {
        "id": f"err-{datetime.now().strftime('%Y%m%d%H%M%S%f')[:17]}",
        "timestamp": datetime.now().isoformat(),
        "source": source,
        "type": exc_type,
        "message": message,
        "traceback": tb,
        "fault_file": fault_file,
        "fault_line": fault_line,
        "context": context or {},
    }
    _ERROR_BUFFER.append(record)
    logger.error("Sentinel recorded %s from %s: %s", exc_type, source, message)
    return record


def get_recent_errors(limit: int = 50) -> list[dict[str, Any]]:
    """Returns the most recent errors, newest first."""
    items = list(_ERROR_BUFFER)
    items.reverse()
    return items[:limit]


def get_repo_root() -> Path:
    """Returns the root directory of the Nova repository."""
    from .ide import nova_source_root
    return nova_source_root()


def _target(relative: str) -> Path:
    root = get_repo_root().resolve()
    path = (root / relative).resolve()
    if ":" in relative or Path(relative).is_absolute() or not path.is_relative_to(root):
        raise ValueError("Repair path must stay inside Nova's source checkout")
    rel = path.relative_to(root)
    if any(part in {".git", ".venv", "node_modules", "__pycache__"} for part in rel.parts):
        raise ValueError("Generated files and repository metadata cannot be repaired")
    if path.suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".json", ".md", ".html"}:
        raise ValueError("Unsupported source file type")
    return path


def _checkpoint_path() -> Path:
    key = hashlib.sha256(str(get_repo_root().resolve()).encode()).hexdigest()[:16]
    return Path(config.DB_PATH).parent / "sentinel" / key / "checkpoint.json"


def checkpoint_status() -> dict | None:
    try:
        checkpoint = json.loads(_checkpoint_path().read_text(encoding="utf-8"))
        return {"checkpoint": checkpoint["checkpoint"], "status": checkpoint["status"],
                "files": list(checkpoint["files"])}
    except (OSError, ValueError, KeyError):
        return None


def _save_checkpoint(checkpoint: dict) -> None:
    global _LAST_CHECKPOINT
    path = _checkpoint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(checkpoint), encoding="utf-8")
    temporary.replace(path)
    _LAST_CHECKPOINT = checkpoint


def create_git_checkpoint(label: str = "sentinel_auto", files: list[str] | None = None) -> dict[str, Any]:
    """Persist exact pre-repair bytes without touching git or unrelated edits."""
    if not files:
        return {"status": "error", "error": "Explicit repair files are required"}
    try:
        entries = {}
        for name in files:
            path = _target(name)
            entries[name] = {"before": base64.b64encode(path.read_bytes()).decode() if path.exists() else None}
        checkpoint = {"checkpoint": uuid.uuid4().hex, "label": label, "status": "saved",
                      "root": str(get_repo_root().resolve()), "files": entries}
        _save_checkpoint(checkpoint)
        return checkpoint
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _rollback() -> dict[str, Any]:
    try:
        checkpoint = json.loads(_checkpoint_path().read_text(encoding="utf-8"))
        if checkpoint["root"] != str(get_repo_root().resolve()):
            raise ValueError("Checkpoint belongs to a different source checkout")
        targets = []
        for name, entry in checkpoint["files"].items():
            path = _target(name)
            current = base64.b64encode(path.read_bytes()).decode() if path.exists() else None
            if current not in (entry["before"], entry.get("after", entry["before"])):
                return {"status": "conflict", "error": f"File changed after repair: {name}. Preserved all files."}
            targets.append((path, entry["before"]))
        for path, before in targets:
            if before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(base64.b64decode(before))
        checkpoint["status"] = "reverted"
        _save_checkpoint(checkpoint)
        return {"status": "reverted", "message": "Restored only the checkpoint's repair files."}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def rollback_git_checkpoint() -> dict[str, Any]:
    if not _PATCH_LOCK.acquire(blocking=False):
        return {"status": "error", "error": "A repair is already running"}
    try:
        return _rollback()
    finally:
        _PATCH_LOCK.release()


def validate_syntax(target_dir: str | Path | None = None) -> dict[str, Any]:
    """Compiles all Python files in the given directory to ensure syntax integrity."""
    dir_to_check = Path(target_dir) if target_dir else get_repo_root() / "backend" / "app"
    errors = []
    py_files = list(dir_to_check.rglob("*.py"))
    for py_file in py_files:
        try:
            py_compile.compile(str(py_file), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append({"file": str(py_file.name), "error": str(exc)})

    return {
        "valid": bool(py_files) and len(errors) == 0,
        "files_checked": len(py_files),
        "errors": errors,
    }


async def run_diagnostics(test_pattern: str | None = "test_selfcheck") -> dict[str, Any]:
    """Full diagnostic scan: error logs, syntax integrity, and test suite health."""
    root = get_repo_root()
    syntax_result = validate_syntax()
    recent = get_recent_errors(limit=5)

    test_result = {}
    if test_pattern and test_pattern != "none":
        pat = None if test_pattern == "full" else test_pattern
        test_result = await selfcheck.run_tests(pattern=pat)

    healthy = syntax_result["valid"] and (not test_result or (test_result.get("ok") is True and test_result.get("passed") is True))

    return {
        "healthy": healthy,
        "timestamp": datetime.now().isoformat(),
        "recent_errors_count": len(_ERROR_BUFFER),
        "latest_errors": recent,
        "syntax": syntax_result,
        "tests": test_result,
    }


async def safe_patch_file(file_rel_path: str, new_content: str) -> dict[str, Any]:
    return await safe_patch_files({file_rel_path: new_content})


async def safe_patch_files(files: dict[str, str]) -> dict[str, Any]:
    """Apply a bounded source transaction; require the full backend suite to pass.

    Frontend edits additionally require the project's production build. Checkpoints
    survive restart, and rollback refuses to overwrite subsequent user changes.
    """
    if not isinstance(files, dict) or not files or len(files) > 50:
        return {"ok": False, "error": "Provide between 1 and 50 source files"}
    if not _PATCH_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "A repair is already running"}
    saved = False
    try:
        paths = {}
        for name, content in files.items():
            if not isinstance(name, str) or not isinstance(content, str):
                raise ValueError("File paths and contents must be strings")
            path = _target(name)
            if path in paths.values():
                raise ValueError("Duplicate repair path")
            if path.suffix == ".py":
                compile(content, str(path), "exec")
            if path.suffix == ".json":
                json.loads(content)
            paths[name] = path
        checkpoint = create_git_checkpoint(files=list(files))
        if checkpoint["status"] != "saved":
            raise ValueError(checkpoint.get("error", "Checkpoint failed"))
        for name, content in files.items():
            checkpoint["files"][name]["after"] = base64.b64encode(content.encode("utf-8")).decode()
        _save_checkpoint(checkpoint)
        saved = True
        for name, path in paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(files[name].encode("utf-8"))
        checks = await selfcheck.run_tests()
        if checks.get("ok") is not True or checks.get("passed") is not True:
            raise ValueError(f"Backend verification failed: {checks.get('summary') or checks.get('error') or checks}")
        if any(path.is_relative_to(get_repo_root() / "frontend") for path in paths.values()):
            build = await _verify_frontend()
            if not build["ok"]:
                raise ValueError(f"Frontend verification failed: {build['output']}")
        checkpoint["status"] = "verified"
        _save_checkpoint(checkpoint)
        return {"ok": True, "files": list(files), "checkpoint": checkpoint["checkpoint"],
                "reverted": False, "test_summary": checks.get("summary", ""),
                "message": "Source repair verified. Runtime restart may be required."}
    except BaseException as exc:
        rollback = _rollback() if saved else {"status": "not_needed"}
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
        return {"ok": False, "error": str(exc), "reverted": rollback["status"] == "reverted", "rollback": rollback}
    finally:
        _PATCH_LOCK.release()


async def _verify_frontend() -> dict:
    process = await asyncio.create_subprocess_shell(
        "npm run build", cwd=str(get_repo_root() / "frontend"),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 180)
        return {"ok": process.returncode == 0, "output": output.decode("utf-8", "replace")[-4000:]}
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
