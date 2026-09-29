"""Git for the Code tab.

Shells out to the real `git` binary rather than using a library: it is already
installed (the coding CLIs need it), it is the thing the user's muscle memory
and the rest of their tooling agree with, and its porcelain formats are a
stable contract.

Read operations are free. The write operations exposed here are deliberately
the reversible ones -- stage, unstage, commit, create a branch, discard a
single file. Nothing pushes, force-pushes, resets hard, or deletes a branch;
those are the ones that lose work or touch a shared remote, and they belong in
the terminal where the user types them deliberately.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from . import config

TIMEOUT = 30
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class GitError(RuntimeError):
    """A git failure, with git's own message attached."""


def _repo_root(path: str | None = None) -> Path:
    return Path(path).resolve() if path else config.get_workspace_dir()


async def _git(args: list[str], cwd: Path, stdin: str | None = None) -> str:
    binary = shutil.which("git")
    if not binary:
        raise GitError("git is not installed, or not on PATH.")
    proc = await asyncio.create_subprocess_exec(
        binary, *args, cwd=str(cwd),
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        creationflags=NO_WINDOW,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(stdin.encode() if stdin is not None else None), TIMEOUT
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise GitError(f"git {args[0]} timed out.") from exc
    if proc.returncode != 0:
        message = (err or out).decode("utf-8", "replace").strip()
        raise GitError(message or f"git {args[0]} failed with code {proc.returncode}.")
    return out.decode("utf-8", "replace")


async def is_repo(path: str | None = None) -> bool:
    try:
        await _git(["rev-parse", "--git-dir"], _repo_root(path))
        return True
    except GitError:
        return False


# `git status --porcelain=v1 -z` is the parseable contract: NUL-separated so
# filenames with spaces, quotes or newlines survive, and a fixed two-character
# XY code per entry rather than prose that changes between versions.
_STATUS_WORDS = {
    "M": "modified", "A": "added", "D": "deleted", "R": "renamed",
    "C": "copied", "U": "conflicted", "?": "untracked", "!": "ignored", " ": "",
}


async def status(path: str | None = None) -> dict:
    root = _repo_root(path)
    if not await is_repo(str(root)):
        return {"is_repo": False, "root": str(root)}

    branch_line = (await _git(["status", "--porcelain=v1", "-z", "--branch"], root)).split("\0", 1)
    header = branch_line[0] if branch_line else ""
    branch, ahead, behind = "?", 0, 0
    if header.startswith("## "):
        info = header[3:]
        branch = info.split("...", 1)[0].split(" ")[0]
        if "[ahead " in info:
            ahead = int(info.split("[ahead ", 1)[1].split("]")[0].split(",")[0])
        if "behind " in info:
            behind = int(info.split("behind ", 1)[1].split("]")[0].strip())

    raw = await _git(["status", "--porcelain=v1", "-z"], root)
    entries, parts, index = [], raw.split("\0"), 0
    while index < len(parts):
        chunk = parts[index]
        index += 1
        if len(chunk) < 4:
            continue
        code, name = chunk[:2], chunk[3:]
        renamed_from = None
        if code[0] in ("R", "C"):
            renamed_from = parts[index] if index < len(parts) else None
            index += 1
        entries.append({
            "path": name,
            "staged": _STATUS_WORDS.get(code[0], ""),
            "unstaged": _STATUS_WORDS.get(code[1], ""),
            "untracked": code == "??",
            "conflicted": "U" in code,
            "renamed_from": renamed_from,
        })

    return {
        "is_repo": True, "root": str(root), "branch": branch,
        "ahead": ahead, "behind": behind, "files": entries,
        "clean": not entries,
    }


async def diff(path: str | None = None, file: str | None = None, staged: bool = False) -> dict:
    root = _repo_root(path)
    args = ["diff", "--no-color"]
    if staged:
        args.append("--cached")
    if file:
        args += ["--", file]
    try:
        text = await _git(args, root)
    except GitError as exc:
        return {"diff": "", "error": str(exc)}
    if not text and file and not staged:
        # An untracked file has no diff; show it as an all-additions patch so
        # the panel isn't mysteriously empty for a brand-new file.
        candidate = root / file
        try:
            if candidate.is_file() and candidate.stat().st_size < 400_000:
                body = candidate.read_text("utf-8", "replace")
                text = f"+++ {file} (untracked)\n" + "".join(f"+{line}\n" for line in body.splitlines())
        except OSError:
            pass
    return {"diff": text[:400_000]}


async def log(path: str | None = None, limit: int = 40) -> dict:
    root = _repo_root(path)
    # Unit separator between fields, record separator between commits: neither
    # occurs in commit text, unlike the pipes and tabs usually used here.
    fmt = "%H%x1f%h%x1f%an%x1f%ar%x1f%s%x1e"
    raw = await _git(["log", f"-{max(1, min(limit, 200))}", f"--pretty=format:{fmt}"], root)
    commits = []
    for record in raw.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        fields = record.split("\x1f")
        if len(fields) >= 5:
            commits.append({
                "hash": fields[0], "short": fields[1], "author": fields[2],
                "when": fields[3], "subject": fields[4],
            })
    return {"commits": commits}


async def branches(path: str | None = None) -> dict:
    root = _repo_root(path)
    raw = await _git(["branch", "--format=%(refname:short)%09%(HEAD)"], root)
    items = []
    for line in raw.splitlines():
        name, _, marker = line.partition("\t")
        if name.strip():
            items.append({"name": name.strip(), "current": marker.strip() == "*"})
    return {"branches": items}


# --- reversible writes -----------------------------------------------------
async def stage(paths: list[str], root_path: str | None = None) -> dict:
    root = _repo_root(root_path)
    if not paths:
        raise GitError("Nothing selected to stage.")
    await _git(["add", "--", *paths], root)
    return await status(root_path)


async def _has_commits(root: Path) -> bool:
    try:
        await _git(["rev-parse", "--verify", "HEAD"], root)
        return True
    except GitError:
        return False


async def unstage(paths: list[str], root_path: str | None = None) -> dict:
    root = _repo_root(root_path)
    if not paths:
        raise GitError("Nothing selected to unstage.")
    # `restore --staged` restores the index *from HEAD*, so in a repository with
    # no commits yet it fails with "fatal: could not resolve HEAD" -- which is
    # exactly the first thing anyone does in a fresh repo: stage a file, change
    # their mind. With no HEAD the un-staged state is "untracked", which is what
    # `rm --cached` produces; --cached keeps the working copy, so nothing is lost.
    if await _has_commits(root):
        await _git(["restore", "--staged", "--", *paths], root)
    else:
        await _git(["rm", "--cached", "-r", "--", *paths], root)
    return await status(root_path)


async def discard(paths: list[str], root_path: str | None = None) -> dict:
    """Throw away uncommitted changes to specific files. Irreversible for those
    files, which is why it is per-file and never a bare `git checkout .`."""
    root = _repo_root(root_path)
    if not paths:
        raise GitError("Nothing selected to discard.")
    await _git(["restore", "--worktree", "--", *paths], root)
    return await status(root_path)


async def commit(message: str, root_path: str | None = None, stage_all: bool = False) -> dict:
    root = _repo_root(root_path)
    if not message.strip():
        raise GitError("A commit needs a message.")
    if stage_all:
        await _git(["add", "-A"], root)
    # Message on stdin via -F -, so it is never parsed as arguments and can
    # contain quotes, newlines and leading dashes.
    await _git(["commit", "-F", "-"], root, stdin=message)
    return await status(root_path)


async def create_branch(name: str, root_path: str | None = None) -> dict:
    root = _repo_root(root_path)
    name = name.strip()
    if not name or name.startswith("-"):
        raise GitError("Invalid branch name.")
    await _git(["switch", "-c", name], root)
    return await status(root_path)


async def switch_branch(name: str, root_path: str | None = None) -> dict:
    root = _repo_root(root_path)
    await _git(["switch", name.strip()], root)
    return await status(root_path)
