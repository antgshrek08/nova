"""Consented, bounded read access to files outside the open project.

Why this exists
---------------
`code_files.py` is deliberately locked to one folder -- `config.get_workspace_dir()`
-- because it backs a file tree and editor for the *currently open project*, and
the coding CLIs run in that same sandbox. That is the right scope for the Code
tab and the wrong scope for a question like "what's in my Key Club assignment
folder", where the answer lives somewhere else entirely.

`project_context.py` already closes half of that gap: it finds *folders by name*
across the user's home directory and reports entry-point filenames. But it
deliberately never reads a file's contents -- its own evidence block says
"Directory names only. File contents have not been read." So N.O.V.A. could tell
you a project existed and never tell you what was in it.

This module is the other half: reading, searching and editing real file content
under folders the user has explicitly granted, with the guardrails that a
capability like that actually needs.

The three guardrails, and why each is load-bearing
--------------------------------------------------
1. **Explicit roots.** Nothing is readable until the user grants a folder (see
   `/files/roots` in main.py). The open project is granted implicitly because
   the user already chose it through the native folder picker. Granting is a
   deliberate act, not a default -- "read anything on the machine" is not a
   setting this app offers, and `_resolve` refuses any path that does not sit
   inside a granted root after full symlink resolution.

2. **A credential deny-list that applies inside granted roots too.** This is
   the one that matters most and is easy to get wrong. N.O.V.A. routes requests
   to *cloud* providers -- OpenRouter, the Claude and Codex CLIs, Antigravity.
   Anything read here can end up in a prompt sent off this machine. A single
   `.env` read from a granted project folder would hand over the very API keys
   the app's own README tells the user to keep out of git. So credential-shaped
   files are refused even when they sit in a folder the user granted, and the
   refusal is *reported* (see `SkipReason`) rather than silently dropped, so
   nobody concludes a key file was empty when it was actually withheld.

3. **Bounds.** Per-file byte caps, total result caps, a wall-clock deadline and
   a directory-count ceiling. A grant of a large folder must not turn one chat
   message into a multi-minute filesystem crawl, and a 400 MB binary must not
   be decoded into a prompt.

Everything here is synchronous and CPU/IO-bound by nature; callers run it in a
worker thread (`asyncio.to_thread`) exactly the way main.py already calls
`project_context.context_for`, so the event loop is never blocked.
"""
from __future__ import annotations

import fnmatch
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config

# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------
MAX_FILE_BYTES = 512 * 1024          # a single file folded into a prompt
MAX_TOTAL_BYTES = 4 * 1024 * 1024    # across one search/read batch
MAX_RESULTS = 200
MAX_DIRECTORIES = 20_000
DEFAULT_DEADLINE_SECONDS = 4.0

# Directories never worth walking: dependency trees, build output, VCS
# internals, and OS areas that are either huge, uninteresting, or both.
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "env", "site-packages", "dist", "build", "out", "target", ".next",
    ".nuxt", ".cache", ".gradle", ".idea", ".vs", "bin", "obj",
    "$Recycle.Bin", "System Volume Information", "Windows",
    "Program Files", "Program Files (x86)", "AppData", "Library",
    "graphify-out", ".terraform", "vendor", "Pods", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache",
}

# Credential-shaped files. Matched case-insensitively against the file NAME, so
# a rename cannot walk a secret past this by moving it to another folder.
# Deliberately broad: a false positive costs the user one "this file was
# skipped" line, a false negative can put a live API key into a cloud prompt.
DENY_FILENAMES = {
    ".env", ".env.local", ".env.production", ".env.development", ".npmrc",
    ".pypirc", ".netrc", "_netrc", ".git-credentials", "credentials",
    "credentials.json", "client_secret.json", "service-account.json",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "known_hosts",
    "secrets.json", "secrets.yaml", "secrets.yml", "shadow", "sam",
    ".htpasswd", "keyring", "wallet.dat", "master.key",
}
DENY_PATTERNS = (
    "*.pem", "*.key", "*.pfx", "*.p12", "*.keystore", "*.jks", "*.asc",
    "*.gpg", "*.kdbx", "*.ppk", "*.crt", "*.cer", "*.der",
    ".env.*", "*_rsa", "*_dsa", "*_ed25519", "*.sqlite-wal",
)
# Directory NAMES that mark a credential store, matched as whole path
# components. Whole-component matching is deliberate: an earlier revision of
# this also substring-matched the joined path, which wrongly blocked innocent
# paths like "cookies-recipes/notes.md". A credential directory is always an
# exact component, so the looser test bought nothing and cost false positives.
DENY_PATH_COMPONENTS = {
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", "gcloud",
    "keychains", "keyrings", "credentials", "protect",
}

# Multi-component suffixes that only mean "credential store" in sequence.
DENY_PATH_SEQUENCES = (
    (".config", "gcloud"),
    ("microsoft", "credentials"),
    ("microsoft", "protect"),
)

# Binary sniffing: a NUL byte in the first block is the standard cheap test.
_TEXT_HINT_BYTES = 8192

_ISJUNCTION = getattr(os.path, "isjunction", None)


class FileAccessError(Exception):
    """A request that the guardrails refused, phrased for the user."""


@dataclass
class SkipReason:
    path: str
    reason: str


@dataclass
class SearchResult:
    matches: list[dict] = field(default_factory=list)
    skipped: list[SkipReason] = field(default_factory=list)
    truncated: bool = False
    searched_roots: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "matches": self.matches,
            "skipped": [{"path": s.path, "reason": s.reason} for s in self.skipped],
            "truncated": self.truncated,
            "searched_roots": self.searched_roots,
        }


# ---------------------------------------------------------------------------
# Roots
# ---------------------------------------------------------------------------
def _is_reparse_point(path: Path) -> bool:
    """Symlinks, and on Python 3.12+ Windows directory junctions.

    Same guarded shape as project_context._is_reparse_point: os.path.isjunction
    is 3.12+, and requirements.txt declares no Python floor.
    """
    try:
        if path.is_symlink():
            return True
        return bool(_ISJUNCTION(path)) if _ISJUNCTION else False
    except OSError:
        return True


def granted_roots(extra: list[str] | None = None) -> list[Path]:
    """Folders this session may read from.

    Always includes the currently open project -- the user picked that one
    through the OS folder dialog, which is a stronger consent signal than any
    in-app toggle. `extra` comes from the persisted app setting.
    """
    roots: list[Path] = []
    seen: set[str] = set()

    def add(raw) -> None:
        try:
            resolved = Path(raw).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return
        if not resolved.is_dir():
            return
        key = str(resolved).casefold()
        if key not in seen:
            seen.add(key)
            roots.append(resolved)

    add(config.get_workspace_dir())
    for item in extra or []:
        add(item)
    return roots


def _resolve(candidate: str, roots: list[Path]) -> Path:
    """Resolve `candidate` and prove it sits inside a granted root.

    Resolution happens BEFORE the containment test, so a symlink pointing out
    of a granted root fails rather than being followed. `..` is handled by the
    same resolution.
    """
    if not roots:
        raise FileAccessError(
            "No folders have been granted yet. Open a project, or add a folder "
            "under Settings, before asking N.O.V.A. to read files."
        )
    try:
        path = Path(candidate).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise FileAccessError(f"That path could not be resolved: {exc}") from exc
    for root in roots:
        if path == root or root in path.parents:
            return path
    raise FileAccessError(
        f"'{candidate}' is outside every granted folder. Grant the folder it "
        f"lives in first — N.O.V.A. does not read arbitrary paths."
    )


# ---------------------------------------------------------------------------
# Deny-list
# ---------------------------------------------------------------------------
def denial_reason(path: Path) -> str | None:
    """Why this file must not be read, or None if it is allowed.

    Checked on the resolved path, so it applies inside granted roots too.
    """
    name = path.name.casefold()
    if name in DENY_FILENAMES:
        return "looks like a credential file"
    for pattern in DENY_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return "looks like a key or certificate"
    parts = [part.casefold() for part in path.parts]
    if any(part in DENY_PATH_COMPONENTS for part in parts):
        return "sits in a credentials or profile directory"
    for sequence in DENY_PATH_SEQUENCES:
        span = len(sequence)
        if any(tuple(parts[i:i + span]) == sequence for i in range(len(parts) - span + 1)):
            return "sits in a credentials or profile directory"
    return None


def _looks_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\0" in handle.read(_TEXT_HINT_BYTES)
    except OSError:
        return True


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def read_text(candidate: str, roots: list[Path], max_bytes: int = MAX_FILE_BYTES) -> dict:
    """One file's text, or a FileAccessError explaining the refusal."""
    path = _resolve(candidate, roots)
    if not path.is_file():
        raise FileAccessError(f"'{candidate}' is not a file.")
    if _is_reparse_point(path):
        raise FileAccessError(f"'{candidate}' is a link; N.O.V.A. reads real files only.")
    reason = denial_reason(path)
    if reason:
        raise FileAccessError(
            f"Refused to read {path.name}: it {reason}. N.O.V.A. sends file "
            f"content to model providers, so credential files are never read — "
            f"paste the specific value yourself if a task genuinely needs it."
        )
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise FileAccessError(f"Could not stat '{candidate}': {exc}") from exc
    if _looks_binary(path):
        raise FileAccessError(f"'{path.name}' is a binary file ({size} bytes), not text.")
    try:
        data = path.read_bytes()[:max_bytes]
    except OSError as exc:
        raise FileAccessError(f"Could not read '{candidate}': {exc}") from exc
    return {
        "path": str(path),
        "name": path.name,
        "bytes": size,
        "truncated": size > max_bytes,
        "content": data.decode("utf-8", errors="replace"),
    }


# ---------------------------------------------------------------------------
# Walking / searching
# ---------------------------------------------------------------------------
def _walk(roots: list[Path], deadline: float):
    """Yield (path, directories_seen) over granted roots, pruned and bounded."""
    seen_dirs = 0
    for root in roots:
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=lambda _e: None):
            seen_dirs += 1
            if seen_dirs > MAX_DIRECTORIES or time.monotonic() > deadline:
                return
            dirs[:] = [
                d for d in dirs
                if d not in SKIP_DIRS
                and not d.startswith(".")
                and not _is_reparse_point(Path(directory, d))
            ]
            for name in files:
                yield Path(directory, name)


def find_files(query: str, roots: list[Path], *, seconds: float = DEFAULT_DEADLINE_SECONDS) -> SearchResult:
    """Filename search across granted roots. Names only; no content is read."""
    result = SearchResult(searched_roots=[str(r) for r in roots])
    terms = [t for t in re.findall(r"[\w.-]+", query.lower()) if len(t) > 1]
    if not terms:
        return result
    deadline = time.monotonic() + seconds
    for path in _walk(roots, deadline):
        name = path.name.lower()
        if not all(t in name for t in terms):
            continue
        if denial_reason(path):
            result.skipped.append(SkipReason(str(path), "credential file"))
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        result.matches.append({
            "path": str(path),
            "name": path.name,
            "bytes": stat.st_size,
            "modified": int(stat.st_mtime),
        })
        if len(result.matches) >= MAX_RESULTS:
            result.truncated = True
            return result
    return result


def search_contents(
    query: str,
    roots: list[Path],
    *,
    seconds: float = DEFAULT_DEADLINE_SECONDS,
    max_per_file: int = 5,
) -> SearchResult:
    """Literal, case-insensitive text search across granted roots.

    Returns matching lines with their line numbers -- enough for N.O.V.A. to
    quote real evidence rather than paraphrase from a filename.
    """
    result = SearchResult(searched_roots=[str(r) for r in roots])
    needle = query.strip().lower()
    if len(needle) < 2:
        raise FileAccessError("Search for at least two characters.")
    deadline = time.monotonic() + seconds
    total = 0
    for path in _walk(roots, deadline):
        if time.monotonic() > deadline:
            result.truncated = True
            break
        if denial_reason(path):
            continue  # not reported per-file here; find_files reports by name
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        if _looks_binary(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        total += len(text)
        if total > MAX_TOTAL_BYTES:
            result.truncated = True
            break
        hits = []
        for number, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                hits.append({"line": number, "text": line.strip()[:300]})
                if len(hits) >= max_per_file:
                    break
        if hits:
            result.matches.append({"path": str(path), "name": path.name, "hits": hits})
            if len(result.matches) >= MAX_RESULTS:
                result.truncated = True
                break
    return result


def list_directory(candidate: str, roots: list[Path]) -> list[dict]:
    """One directory level, same shape code_files.list_tree returns."""
    path = _resolve(candidate, roots)
    if not path.is_dir():
        raise FileAccessError(f"'{candidate}' is not a folder.")
    entries = []
    try:
        children = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError as exc:
        raise FileAccessError(f"Could not list '{candidate}': {exc}") from exc
    for child in children:
        if child.name in SKIP_DIRS:
            continue
        try:
            is_dir = child.is_dir()
            size = 0 if is_dir else child.stat().st_size
        except OSError:
            continue
        entries.append({
            "name": child.name,
            "path": str(child),
            "is_dir": is_dir,
            "bytes": size,
            "restricted": bool(denial_reason(child)) if not is_dir else False,
        })
    return entries


def check_writable(candidate: str, content: str, roots: list[Path]) -> Path:
    """Every guardrail a write must pass, without performing it.

    Split out from write_text so the tool loop can validate BEFORE prompting
    the user for approval -- there is no point asking someone to approve a
    write that would be refused anyway, and the model learns why immediately
    instead of after a pointless round trip. write_text calls this itself, so
    the two can never drift apart and validating here is never a way to skip
    a check there.
    """
    path = _resolve(candidate, roots)
    if _is_reparse_point(path):
        raise FileAccessError(f"'{candidate}' is a link; N.O.V.A. writes real files only.")
    reason = denial_reason(path)
    if reason:
        raise FileAccessError(f"Refused to write {path.name}: it {reason}.")
    if path.is_dir():
        raise FileAccessError(f"'{candidate}' is a folder, not a file.")
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise FileAccessError(f"That content exceeds the {MAX_FILE_BYTES // 1024} KB write limit.")
    return path


def write_text(candidate: str, content: str, roots: list[Path]) -> dict:
    """Write a file inside a granted root.

    Refuses the same paths reading refuses: overwriting a `.env` or a private
    key is at least as damaging as reading one, and a model that cannot read a
    file has no business rewriting it either.
    """
    path = check_writable(candidate, content, roots)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        stat = path.stat()
    except OSError as exc:
        raise FileAccessError(f"Could not write '{candidate}': {exc}") from exc
    return {"path": str(path), "bytes": stat.st_size}
