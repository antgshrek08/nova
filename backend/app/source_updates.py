"""Safe source-update pipeline for N.O.V.A. (Plan §4 & §8).

When Nova modifies its own code -- whether to self-heal a procedure or to
build a user-requested feature -- those edits run in an isolated staging
copy, never directly in the live checkout.  The flow is:

    prepare  ->  verify  ->  activate  ->  boot check  ->  (rollback if needed)

Prepare copies the source to a staging area and applies the proposed edits.
Verify runs syntax checks, the backend suite and (for frontend edits) the
production build against the staged copy.
Activate replaces the live files only after verification passes.
Boot check confirms the app actually starts; a launch that never confirms
health is rolled back on the following launch (see recover_on_boot).

State is persisted beside Nova's data, not in memory, so rollback and boot
recovery survive the restart that an update requires.

Private files (.env, .db, secrets) are excluded from staged copies.
Path-traversal out of the project root is rejected.
Candidates are tamper-detected: if the staged files change between verify
and activate, activation is refused.  Live files changed by someone else are
never overwritten by activation or rollback.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

# ── Configuration ───────────────────────────────────────────────────────────

_PRIVATE_PATTERNS = {".env", ".db", ".sqlite", ".sqlite3", ".key", ".pem",
                     "personal.db", "secrets", ".secret"}
# Build output, dependencies, and runtime state -- never part of a candidate.
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".venv-hermes", "dist",
              "release", "extracted_asar", ".pytest_cache", ".hermes", "vendor"}
_LOCK = threading.Lock()


def _update_home() -> Path:
    """Where staged candidates live.  Respects NOVA_UPDATE_HOME for testing.

    Resolved without requiring config to import cleanly, because boot recovery
    must still work when an update broke the module that defines it.
    """
    home = os.environ.get("NOVA_UPDATE_HOME")
    if home:
        return Path(home)
    try:
        from . import config
        data = Path(config.DB_PATH).parent
    except Exception:  # noqa: BLE001
        data = Path(os.getenv("DB_PATH", str(Path.home() / ".ai-council" / "ai_council.db"))).parent
    return data / "source_updates"


def _is_private(rel: str) -> bool:
    for part in Path(rel).parts:
        if part in _PRIVATE_PATTERNS:
            return True
    name = Path(rel).name
    return any(name == pat or name.endswith(pat) for pat in _PRIVATE_PATTERNS)


# ── Persistent state ────────────────────────────────────────────────────────

def _state_path() -> Path:
    return _update_home() / "state.json"


def _load() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"active_id": None, "candidates": {}}


def _save(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=1), encoding="utf-8")
    temporary.replace(path)


def _candidate(state: dict, candidate_id: str) -> dict:
    c = state["candidates"].get(candidate_id)
    if not c:
        raise ValueError(f"Unknown candidate: {candidate_id}")
    return c


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    return _hash_bytes(path.read_bytes())


def _source_files(root: Path) -> list[str]:
    """Files that make up the source: git's view when available, else a pruned walk."""
    if (root / ".git").exists():
        try:
            listed = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
                capture_output=True, check=True, timeout=60).stdout.decode("utf-8", "replace")
            names = [n for n in listed.split("\0") if n]
            return [n for n in names if not (set(Path(n).parts) & _SKIP_DIRS) and (root / n).is_file()]
        except (OSError, subprocess.SubprocessError):
            pass
    files = []
    for directory, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in names:
            files.append(str((Path(directory) / name).relative_to(root)))
    return files


# ── Core pipeline ───────────────────────────────────────────────────────────

async def prepare(edits: dict[str, str], root: Path | None = None) -> dict:
    """Stage a set of file edits in an isolated copy.

    edits: {relative_path: new_content}
    root:  project root (defaults to Nova's source root)
    """
    if not isinstance(edits, dict) or not edits or len(edits) > 50:
        raise ValueError("Provide between 1 and 50 file edits.")
    if root is None:
        from .ide import nova_source_root
        root = nova_source_root()
    root = Path(root).resolve()

    for rel, content in edits.items():
        if not isinstance(rel, str) or not isinstance(content, str):
            raise ValueError("Edit paths and contents must be strings.")
        resolved = (root / rel).resolve()
        if Path(rel).is_absolute() or not resolved.is_relative_to(root) or resolved == root:
            raise ValueError(f"Path traversal detected: {rel}")
        if _is_private(rel) or set(Path(rel).parts) & _SKIP_DIRS:
            raise ValueError(f"Private or generated files cannot be updated: {rel}")

    update_home = _update_home()
    update_home.mkdir(parents=True, exist_ok=True)
    candidate_id = f"update-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    stage_dir = update_home / candidate_id
    stage_dir.mkdir(parents=True)

    files = await asyncio.to_thread(_source_files, root)
    for rel in files:
        if _is_private(rel):
            continue
        dst = stage_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dst)

    original_hashes, staged_hashes, new_files = {}, {}, []
    for rel, content in edits.items():
        original_file = root / rel
        if original_file.exists():
            original_hashes[rel] = _hash_file(original_file)
        else:
            new_files.append(rel)
        data = content.encode("utf-8")
        staged_file = stage_dir / rel
        staged_file.parent.mkdir(parents=True, exist_ok=True)
        staged_file.write_bytes(data)  # exact bytes: no platform newline translation
        staged_hashes[rel] = _hash_bytes(data)

    candidate = {
        "id": candidate_id,
        "path": str(stage_dir),
        "root": str(root),
        "edits": list(edits.keys()),
        "new_files": new_files,
        "status": "prepared",
        "staged_hashes": staged_hashes,
        "original_hashes": original_hashes,
        "created_at": datetime.now().isoformat(),
        "verified_at": None,
        "checks": None,
    }
    with _LOCK:
        state = _load()
        state["candidates"][candidate_id] = candidate
        _save(state)
    return candidate


async def verify(candidate_id: str) -> dict:
    """Run validation checks against a staged candidate."""
    c = _candidate(_load(), candidate_id)
    if c["status"] != "prepared":
        raise ValueError(f"Only prepared candidates can be verified (status={c['status']}).")

    result = await _validate_candidate(c)

    with _LOCK:
        state = _load()
        c = _candidate(state, candidate_id)
        if result.get("ok"):
            c["status"] = "verified"
            c["verified_at"] = datetime.now().isoformat()
            c["checks"] = result.get("checks", [])
        else:
            c["status"] = "failed"
            c["checks"] = result.get("error", "Verification failed")
        _save(state)
    return c


async def _validate_candidate(candidate: dict) -> dict:
    """Syntax, the full backend suite, and the frontend build when frontend files changed."""
    import py_compile
    stage = Path(candidate["path"])
    errors = []
    for rel in candidate["edits"]:
        path = stage / rel
        if path.suffix == ".py":
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(str(e))
        elif path.suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except ValueError as e:
                errors.append(f"{rel}: {e}")
    if errors:
        return {"ok": False, "error": "; ".join(errors)}
    checks = ["syntax"]

    from . import selfcheck
    tests = await selfcheck.run_tests(root=stage)
    if tests.get("ok") is not True or tests.get("passed") is not True:
        return {"ok": False, "error": f"Backend verification failed: {tests.get('summary') or tests.get('error') or tests}"}
    checks.append(f"backend tests: {tests.get('summary', 'passed')}")

    if any(Path(rel).parts[0] == "frontend" for rel in candidate["edits"]):
        build = await _build_frontend(stage, Path(candidate["root"]))
        if not build["ok"]:
            return {"ok": False, "error": f"Frontend verification failed: {build['output']}"}
        checks.append("frontend build")
    return {"ok": True, "checks": checks}


async def _build_frontend(stage: Path, live_root: Path) -> dict:
    """Build the staged frontend against the live checkout's installed dependencies."""
    modules = stage / "frontend" / "node_modules"
    live_modules = live_root / "frontend" / "node_modules"
    if not live_modules.is_dir():
        return {"ok": False, "output": "Frontend dependencies are not installed in the live checkout."}
    linked = False
    try:
        if not modules.exists():
            if os.name == "nt":
                import _winapi
                _winapi.CreateJunction(str(live_modules), str(modules))
            else:
                os.symlink(live_modules, modules, target_is_directory=True)
            linked = True
        process = await asyncio.create_subprocess_shell(
            "npm run build", cwd=str(stage / "frontend"),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 300)
            return {"ok": process.returncode == 0, "output": output.decode("utf-8", "replace")[-4000:]}
        except asyncio.TimeoutError:
            return {"ok": False, "output": "The frontend build did not finish within 300s."}
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
    finally:
        if linked:
            # Remove only the link; never recurse into the live dependencies.
            if os.name == "nt":
                os.rmdir(modules)
            else:
                os.unlink(modules)


def activate(candidate_id: str) -> dict:
    """Promote a verified candidate to live.  Returns pending_boot=True."""
    with _LOCK:
        state = _load()
        c = _candidate(state, candidate_id)
        if c["status"] != "verified":
            raise ValueError(f"Cannot activate: candidate is not verified (status={c['status']}).")
        active = state["candidates"].get(state.get("active_id") or "")
        if active and active["status"] == "activated":
            raise ValueError(f"Update {active['id']} is still awaiting its boot check; confirm or roll it back first.")

        stage = Path(c["path"])
        root = Path(c["root"])

        # Tamper detection: staged files must not have changed since verify
        for rel, expected_hash in c["staged_hashes"].items():
            staged_file = stage / rel
            if not staged_file.exists():
                raise ValueError(f"Staged file missing: {rel}")
            if _hash_file(staged_file) != expected_hash:
                raise ValueError(f"Candidate changed after verification: {rel}")

        # Concurrent-edit detection: live source must match what was staged from
        for rel in c["edits"]:
            live_file = root / rel
            expected = c["original_hashes"].get(rel)
            current = _hash_file(live_file) if live_file.exists() else None
            if current != expected:
                raise ValueError(
                    f"Live source changed since prepare for '{rel}'. "
                    "Aborting to avoid overwriting concurrent edits."
                )

        # Original bytes are kept in the persisted state so rollback survives restart
        backup = {}
        for rel in c["edits"]:
            live_file = root / rel
            backup[rel] = base64.b64encode(live_file.read_bytes()).decode() if live_file.exists() else None
        c["backup"] = backup

        for rel in c["edits"]:
            live_file = root / rel
            live_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage / rel, live_file)

        c["status"] = "activated"
        c["boots"] = 0
        c["activated_at"] = datetime.now().isoformat()
        state["active_id"] = candidate_id
        _save(state)
    return {"pending_boot": True, "id": candidate_id}


def _restore(state: dict, c: dict) -> dict:
    """Put back the pre-activation bytes, refusing if files changed after activation."""
    root = Path(c["root"])
    backup = c.get("backup") or {}
    for rel in c["edits"]:
        live_file = root / rel
        current = _hash_file(live_file) if live_file.exists() else None
        if current not in (c["staged_hashes"].get(rel), c["original_hashes"].get(rel)):
            return {"active_id": state.get("active_id"), "status": "conflict",
                    "error": f"File changed after activation: {rel}. Preserved all files."}
    for rel in c["edits"]:
        live_file = root / rel
        before = backup.get(rel)
        if before is None:
            live_file.unlink(missing_ok=True)
        else:
            live_file.write_bytes(base64.b64decode(before))
    c["status"] = "rolled_back"
    state["active_id"] = None
    return {"active_id": None, "rolled_back": c["id"]}


def rollback() -> dict:
    """Restore original files from the backup made during activation."""
    with _LOCK:
        state = _load()
        active_id = state.get("active_id")
        if not active_id:
            return {"active_id": None, "message": "Nothing to roll back."}
        c = state["candidates"].get(active_id)
        if not c:
            state["active_id"] = None
            _save(state)
            return {"active_id": None}
        result = _restore(state, c)
        _save(state)
        return result


def boot_result(candidate_id: str, healthy: bool, reason: str = "") -> dict:
    """Record whether the activated update survived boot."""
    with _LOCK:
        state = _load()
        c = _candidate(state, candidate_id)
        if healthy:
            c["status"] = "live"
            _save(state)
            return {"status": "live", "id": candidate_id}
        c["boot_failure_reason"] = reason
        result = _restore(state, c) if state.get("active_id") == candidate_id else {"active_id": state.get("active_id")}
        if result.get("status") == "conflict":
            _save(state)
            return {"status": "conflict", "reason": reason, "error": result["error"]}
        c["status"] = "boot_failed"
        _save(state)
        return {"status": "boot_failed", "reason": reason}


def recover_on_boot() -> dict | None:
    """Called as the backend package loads, before any updated module is imported.

    The first launch after activation counts itself; confirm_boot() marks the
    update live once startup completes.  If a later launch finds the count still
    set, the previous launch never became healthy, so the update is rolled back
    before its code can break this launch too.
    """
    if "pytest" in sys.modules:
        # Test runs (including verification of a staged copy) are not launches;
        # counting them would roll back a healthy pending update.
        return None
    try:
        with _LOCK:
            state = _load()
            c = state["candidates"].get(state.get("active_id") or "")
            if not c or c["status"] != "activated":
                return None
            if c.get("boots", 0) >= 1:
                reason = "The previous launch after this update never finished starting."
                c["boot_failure_reason"] = reason
                result = _restore(state, c)
                if result.get("status") != "conflict":
                    c["status"] = "boot_failed"
                _save(state)
                return {"status": c["status"], "id": c["id"], "reason": reason}
            c["boots"] = c.get("boots", 0) + 1
            _save(state)
            return {"status": "pending_boot", "id": c["id"]}
    except Exception:  # noqa: BLE001 -- recovery must never be why Nova cannot start
        return None


def confirm_boot() -> dict | None:
    """Startup completed: an update awaiting its boot check is now live."""
    state = _load()
    c = state["candidates"].get(state.get("active_id") or "")
    if c and c["status"] == "activated":
        return boot_result(c["id"], healthy=True)
    return None


def status() -> dict:
    """Current state of the update pipeline."""
    state = _load()
    return {
        "active_id": state.get("active_id"),
        "candidates": {k: {
            "id": v["id"],
            "status": v["status"],
            "edits": v["edits"],
            "created_at": v["created_at"],
            "checks": v.get("checks"),
            "boot_failure_reason": v.get("boot_failure_reason"),
        } for k, v in state["candidates"].items()},
    }


def get(candidate_id: str) -> dict:
    """Get a specific candidate's details."""
    c = dict(_candidate(_load(), candidate_id))
    c.pop("backup", None)
    return c
