"""Read/write access backing the Code tab's file tree and editor pane (see
main.py's /code/* routes). Scoped strictly to config.get_workspace_dir() --
the same sandbox claude -p / codex exec already operate in (see
providers.py) -- so a browser-facing file browser can never read or write
outside the current project, and so files the CLIs create while doing real
agentic work are exactly what shows up in the tree, not some separate
disconnected root. The root itself is no longer fixed at import time (Code
tab milestone: "Opening an existing project through the native folder
picker") -- every function here resolves it fresh via config.get_workspace_dir()
so a project switch takes effect immediately.
"""
from __future__ import annotations

import difflib
from pathlib import Path

from . import config

# Bounds for the change-review snapshot (task: "Provide a change-review view
# for proposed edits" -- in practice, for edits a CLI already made; see
# main.py's docstring on why there's no real "proposed, not yet applied"
# state here). A real, readable diff for a MODIFIED file needs its actual
# prior text, not just a hash -- so this snapshot keeps real content, capped
# both per-file and in total, rather than growing without bound in a large
# opened folder. Most coding turns touch a handful of files; these caps are
# about bounding the worst case (a huge project), not the common one.
SNAPSHOT_MAX_FILE_BYTES = 256 * 1024
SNAPSHOT_MAX_TOTAL_BYTES = 30 * 1024 * 1024
_SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv", "graphify-out", ".next", "dist", "build"}


class PathEscapeError(ValueError):
    """A requested relative path resolved outside the current project root
    (e.g. via '../..')."""


def _resolve(rel_path: str) -> Path:
    root = config.get_workspace_dir().resolve()
    candidate = (root / rel_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise PathEscapeError(f"'{rel_path}' is outside the current project.")
    return candidate


def list_tree(rel_path: str = "") -> list[dict]:
    """Non-recursive listing of one directory (lazy per-level expansion is
    the frontend's job, same as any real IDE file tree) -- directories
    first, then files, both alphabetical."""
    base = _resolve(rel_path)
    if not base.is_dir():
        return []
    entries = []
    for child in sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if child.name in _SKIP_DIR_NAMES:
            continue
        entries.append(
            {
                "name": child.name,
                "path": str(child.relative_to(config.get_workspace_dir())).replace("\\", "/"),
                "is_dir": child.is_dir(),
            }
        )
    return entries


def _fingerprint(path: Path) -> str:
    """A cheap, real "has this file changed on disk" signature -- mtime
    alone can be unreliable across some filesystems/copy operations, so this
    pairs it with size; good enough to detect "something external touched
    this file since we last read it" without hashing full content on every
    read (task: "Never silently overwrite a file changed externally.
    Detect the conflict")."""
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def read_file(rel_path: str) -> dict:
    path = _resolve(rel_path)
    if not path.is_file():
        raise FileNotFoundError(rel_path)
    content = path.read_text(encoding="utf-8")
    return {"content": content, "fingerprint": _fingerprint(path)}


def write_file(rel_path: str, content: str, expected_fingerprint: str | None = None) -> dict:
    """Raises FileConflictError if the file was modified externally since
    the editor last read it (expected_fingerprint set and doesn't match the
    file's current on-disk state) -- the caller (main.py) turns that into a
    409 with the file's real current content so the frontend can offer a
    genuine compare/reload/overwrite choice, never a silent clobber."""
    path = _resolve(rel_path)
    if expected_fingerprint is not None and path.is_file():
        current = _fingerprint(path)
        if current != expected_fingerprint:
            raise FileConflictError(path.read_text(encoding="utf-8"), current)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"fingerprint": _fingerprint(path)}


class FileConflictError(Exception):
    def __init__(self, current_content: str, current_fingerprint: str):
        super().__init__("File was modified externally since it was last read.")
        self.current_content = current_content
        self.current_fingerprint = current_fingerprint


def _iter_text_files(root: Path):
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            children = list(d.iterdir())
        except OSError:
            continue
        for child in children:
            if child.name in _SKIP_DIR_NAMES:
                continue
            if child.is_dir():
                stack.append(child)
                continue
            try:
                if child.stat().st_size > SNAPSHOT_MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield child


def snapshot_workspace() -> dict[str, str]:
    """Real "what did every text file look like" snapshot of the current
    project, taken immediately before a coding-CLI turn runs (see main.py).
    Keeps actual content (not just a hash) so a MODIFIED file can get a real
    unified diff against what it really said before -- a hash alone can only
    ever tell you THAT something changed, never what. Bounded by
    SNAPSHOT_MAX_FILE_BYTES per file and SNAPSHOT_MAX_TOTAL_BYTES overall so
    a huge opened folder can't make this unbounded; once the total cap is
    hit, remaining files are simply not covered by this turn's diff (an
    honest limitation of a large project, not a silent wrong diff)."""
    root = config.get_workspace_dir()
    snapshot: dict[str, str] = {}
    total = 0
    for path in _iter_text_files(root):
        if total >= SNAPSHOT_MAX_TOTAL_BYTES:
            break
        try:
            data = path.read_bytes()
            text = data.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        snapshot[rel] = text
        total += len(data)
    return snapshot


def diff_against_snapshot(before: dict[str, str]) -> list[dict]:
    """Compares a prior snapshot_workspace() result against the project's
    current state and returns one entry per real, actually-detected change
    -- added, modified, or deleted -- each with a real readable unified
    diff (added/modified always; deleted gets a diff against empty too, so
    "what was lost" is visible the same way).

    Honesty note (task: "If AI changes are already written directly,
    accurately distinguish completed changes from proposals; do not label
    an already-written change 'awaiting approval'"): by the time this runs,
    every change here already happened on disk -- claude -p / codex exec do
    their own file writes as part of answering, before this backend ever
    sees their response. This is a real record of what changed, not a
    pending proposal; main.py's event type is named accordingly
    (file_changes, not file_changes_proposed) and the frontend never offers
    an "Apply" action for these, only "Revert" (a real write back to the
    pre-change content captured here).
    """
    root = config.get_workspace_dir()
    after_texts: dict[str, str] = {}
    for path in _iter_text_files(root):
        try:
            after_texts[str(path.relative_to(root)).replace("\\", "/")] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

    changes: list[dict] = []
    for rel, after_text in after_texts.items():
        before_text = before.get(rel)
        if before_text is None:
            changes.append({"path": rel, "kind": "added", "before": "", "after": after_text, "diff": _unified_diff(rel, "", after_text)})
        elif before_text != after_text:
            changes.append(
                {"path": rel, "kind": "modified", "before": before_text, "after": after_text, "diff": _unified_diff(rel, before_text, after_text)}
            )
    for rel, before_text in before.items():
        if rel not in after_texts:
            changes.append({"path": rel, "kind": "deleted", "before": before_text, "after": "", "diff": _unified_diff(rel, before_text, "")})
    return changes


def _unified_diff(path: str, before: str, after: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=f"a/{path}", tofile=f"b/{path}"
    )
    return "".join(lines)
