"""Nova checking whether it has broken itself.

Nova can already edit its own source -- it has the file tools and knows where
the checkout is. What it has had no way to do is find out whether the edit
worked, which is the difference between changing code and improving it.

This is the step that makes autonomous self-modification defensible rather
than reckless. The loop a person actually uses is: make the change, run the
tests, read the failures, decide. Without the middle two, an agent editing
its own source is just hoping, and the thing it is hoping about is the
program it is currently running.

Scoped deliberately to Nova's own checkout and its own suite. This is not a
general "run the tests" tool -- code_files and run_command already cover the
user's projects. The value here is that it knows exactly where Nova's tests
live and how to read their output, so the answer comes back as "3 failed, and
here is which", not as 4,000 lines of pytest for a model to squint at.
"""
from __future__ import annotations

import asyncio
import re
import os
from pathlib import Path

from .ide import nova_source_root

# The suite takes about 25 seconds warm. The ceiling is for a hang -- a test
# that waits on something that will never arrive -- not for a slow run.
TIMEOUT_SECONDS = 420

_SUMMARY = re.compile(
    r"(?:(\d+) failed)?,?\s*(?:(\d+) passed)?(?:,\s*(\d+) skipped)?(?:,\s*(\d+) error)?",
)
_FAILED_LINE = re.compile(r"^FAILED\s+(\S+)\s*(?:-\s*(.*))?$", re.MULTILINE)
_ERROR_LINE = re.compile(r"^ERROR\s+(\S+)\s*(?:-\s*(.*))?$", re.MULTILINE)


def _python() -> Path:
    return nova_source_root() / "backend" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


async def run_tests(pattern: str | None = None, root: Path | None = None) -> dict:
    """Run Nova's backend suite and report what happened.

    `pattern` is passed to pytest's -k, so a change to one area can be checked
    in a couple of seconds instead of the whole suite. The full run is still
    what decides whether a change is safe.

    `root` runs the suite of another copy of the source -- a staged update --
    with the live checkout's interpreter, since a staged copy has no venv.
    """
    root = Path(root) if root else nova_source_root()
    backend = root / "backend"
    python = _python()
    if not python.is_file():
        return {"ok": False, "error": f"Nova's Python environment is not at {python}."}

    command = [str(python), "-m", "pytest", "tests", "-q", "--no-header", "-p", "no:cacheprovider"]
    if pattern:
        command += ["-k", pattern]

    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(backend),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"The test run did not finish within {TIMEOUT_SECONDS}s."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not run the tests: {exc}"}

    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()

    output = stdout.decode("utf-8", "replace")
    tail = output.strip().splitlines()
    summary_line = next(
        (line for line in reversed(tail) if " passed" in line or " failed" in line or " error" in line),
        "",
    )

    failures = [
        {"test": name, "reason": (reason or "").strip()[:300]}
        for name, reason in _FAILED_LINE.findall(output) + _ERROR_LINE.findall(output)
    ]
    passed = process.returncode == 0

    return {
        "ok": True,
        "passed": passed,
        "summary": summary_line.strip()[:300],
        "failures": failures[:25],
        "failure_count": len(failures),
        # The whole point is that the model does not have to read 4,000 lines
        # to learn one number, but a failure it cannot see is a failure it
        # cannot fix -- so the tail of the output comes back when something
        # broke, and not otherwise.
        "output_tail": "" if passed else "\n".join(tail[-60:]),
        "command": " ".join(command[1:]),
        "root": str(root),
    }


async def status() -> dict:
    """Whether self-checking is even possible here."""
    try:
        root = nova_source_root()
    except Exception:  # noqa: BLE001
        return {"available": False, "reason": "Nova's source checkout was not found."}
    python = _python()
    if not python.is_file():
        return {"available": False, "reason": f"No Python environment at {python}."}
    tests = root / "backend" / "tests"
    count = len(list(tests.glob("test_*.py"))) if tests.is_dir() else 0
    return {"available": count > 0, "root": str(root), "test_files": count,
            "reason": None if count else "No test files found."}
