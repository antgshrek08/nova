"""Whether this project can actually be deployed, and what is in the way.

Nova can reach deploy providers through MCP (Vercel, Replit, Lovable), but a
panel of deploy buttons wired to servers nobody has connected is worse than
no panel: it implies a capability that is not there. So this answers the
question that is useful either way -- "what state is this project in, and what
would stop me shipping it right now" -- and names the providers as connected
or not rather than pretending.

The checks are deliberately the boring ones, because they are the ones that
actually catch people out: uncommitted work, commits that only exist locally,
no remote at all, and a build that does not pass. Every one of those is
something you would rather find here than after a deploy.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from pathlib import Path

from . import config, db, git_panel

# Files that say "this project already knows how it deploys". Presence is a
# fact about the repo, not a guess from its dependencies.
_DEPLOY_MARKERS = {
    "vercel.json": "Vercel",
    "netlify.toml": "Netlify",
    "Dockerfile": "Docker",
    "fly.toml": "Fly.io",
    "render.yaml": "Render",
    "railway.json": "Railway",
    "app.yaml": "App Engine",
}

# MCP servers that can actually deploy something, by the name Nova stores.
# Matched loosely because the user names these rows themselves.
_DEPLOY_PROVIDERS = ("vercel", "replit", "lovable", "netlify", "railway", "render", "fly")

# CSI escape sequences: what npm, vite and friends use for colour. The
# panel is not a terminal, so without this the output reads "[2mdist/[22m".
_ANSI = re.compile(chr(27) + r"\[[0-9;?]*[ -/]*[@-~]")

_BUILD_TIMEOUT_SECONDS = 600
# One build at a time, process-wide. `root` records which project it was,
# so another project cannot inherit its result -- see build_status().
_build: dict = {"running": False, "started": 0.0, "finished": 0.0, "root": None,
                "ok": None, "code": None, "output": [], "command": None}


def _read_package(root: Path) -> dict:
    try:
        return json.loads((root / "package.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- absent or unreadable is just "not node"
        return {}


def detect_project(root: Path) -> dict:
    """What kind of thing this is and how it builds."""
    package = _read_package(root)
    scripts = package.get("scripts") or {}
    dependencies = {**package.get("dependencies", {}), **package.get("devDependencies", {})}

    framework = None
    for name in ("next", "vite", "astro", "remix", "nuxt"):
        if name in dependencies:
            framework = name
            break
    if not framework and (root / "requirements.txt").is_file():
        framework = "python"
    if not framework and (root / "pyproject.toml").is_file():
        framework = "python"

    build_command = None
    if "build" in scripts:
        build_command = "npm run build"
    elif framework in {"next", "vite", "astro", "remix", "nuxt"}:
        build_command = f"npx {framework} build"

    return {
        "name": package.get("name") or root.name,
        "framework": framework,
        "build_command": build_command,
        "has_package_json": bool(package),
        "markers": [label for filename, label in _DEPLOY_MARKERS.items() if (root / filename).is_file()],
    }


async def _providers() -> list[dict]:
    """Deploy-capable MCP servers, and whether they are actually enabled."""
    try:
        rows = await db.list_mcp_servers()
    except Exception:  # noqa: BLE001
        return []
    found = []
    for row in rows:
        lowered = (row.get("name") or "").lower()
        match = next((p for p in _DEPLOY_PROVIDERS if p in lowered), None)
        if match:
            found.append({"name": row["name"], "provider": match, "enabled": bool(row.get("enabled"))})
    return found


async def status(path: str | None = None) -> dict:
    """Everything the Ship panel needs, including why it cannot ship."""
    root = Path(path) if path else config.get_workspace_dir()
    project = detect_project(root)

    git: dict = {"is_repo": False}
    try:
        git = await git_panel.status(str(root))
    except Exception:  # noqa: BLE001 -- a non-repo is a normal answer here
        pass

    remote = None
    if git.get("is_repo"):
        try:
            remote = (await git_panel._git(["remote", "get-url", "origin"], root)).strip() or None
        except Exception:  # noqa: BLE001 -- no origin configured
            remote = None

    providers = await _providers()
    connected = [p for p in providers if p["enabled"]]

    # Ordered by what you would hit first, and phrased as the thing to do
    # rather than the thing that is wrong.
    blockers: list[str] = []
    if not git.get("is_repo"):
        blockers.append("This folder isn't a git repository. Most deploy targets need one.")
    else:
        dirty = len(git.get("entries") or [])
        if dirty:
            blockers.append(f"{dirty} uncommitted change{'s' if dirty != 1 else ''} — commit them in Code → Git.")
        if not remote:
            blockers.append("No git remote. Add one before a provider can pull the code.")
        elif git.get("ahead"):
            blockers.append(f"{git['ahead']} commit{'s' if git['ahead'] != 1 else ''} not pushed yet.")
    if not project["build_command"]:
        blockers.append("No build command found, so Nova can't check the build before shipping.")
    if not connected:
        blockers.append(
            "No deploy provider connected. Settings → MCP has presets for Vercel, Replit and "
            "Lovable; each signs in with OAuth on first use."
        )

    return {
        "root": str(root),
        "project": project,
        "git": {
            "is_repo": bool(git.get("is_repo")),
            "branch": git.get("branch"),
            "ahead": git.get("ahead", 0),
            "behind": git.get("behind", 0),
            "uncommitted": len(git.get("entries") or []),
            "remote": remote,
        },
        "providers": providers,
        "ready": not blockers,
        "blockers": blockers,
        "build": build_status(root),
    }


def build_status(root: Path | None = None) -> dict:
    """The last build, but only if it was this project's.

    There is one build slot for the whole process, so without this check the
    panel showed "passed" for a build that ran in a different folder -- seen
    live: an empty sandbox with no build command at all reported a successful
    npm build inherited from another project. A stale green tick on the wrong
    project is worse than no tick.
    """
    if root is not None and _build["root"] and Path(_build["root"]) != Path(root):
        return {"running": False, "started": 0.0, "finished": 0.0,
                "ok": None, "code": None, "output": [], "command": None}
    out = dict(_build)
    out["output"] = list(_build["output"])[-200:]
    return out


async def run_build(path: str | None = None) -> dict:
    """Run the project's own build and keep the output.

    "Does it build" is the question worth answering before a deploy, and it is
    the one a provider answers slowest and least clearly -- a failed remote
    build costs a push, a queue and a log hunt to learn something reproducible
    in seconds here."""
    if _build["running"]:
        return {"started": False, "reason": "A build is already running."}

    root = Path(path) if path else config.get_workspace_dir()
    project = detect_project(root)
    command = project["build_command"]
    if not command:
        return {"started": False, "reason": "No build command found for this project."}

    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if command.startswith("npm ") and not npm:
        return {"started": False, "reason": "npm is not on PATH."}

    _build.update({"running": True, "started": time.time(), "finished": 0.0,
                   "root": str(root), "ok": None, "code": None, "output": [],
                   "command": command})

    async def _run():
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async def _drain():
                assert process.stdout
                async for line in process.stdout:
                    # Build tools colour their output, and the panel is not a
                    # terminal -- the raw codes render as "[2mdist/[22m".
                    text = _ANSI.sub("", line.decode("utf-8", "replace")).rstrip()
                    _build["output"].append(text)
                    # Bounded: a webpack build can emit tens of thousands of
                    # lines and this is held in memory for the panel.
                    if len(_build["output"]) > 2000:
                        del _build["output"][:1000]
            await asyncio.wait_for(asyncio.gather(_drain(), process.wait()), _BUILD_TIMEOUT_SECONDS)
            _build["code"] = process.returncode
            _build["ok"] = process.returncode == 0
        except asyncio.TimeoutError:
            _build["output"].append(f"— build exceeded {_BUILD_TIMEOUT_SECONDS}s and was stopped —")
            _build["ok"], _build["code"] = False, -1
        except Exception as exc:  # noqa: BLE001
            _build["output"].append(f"— build could not start: {exc} —")
            _build["ok"], _build["code"] = False, -1
        finally:
            _build["running"] = False
            _build["finished"] = time.time()

    asyncio.create_task(_run())
    return {"started": True, "command": command}


async def push_to_remote(path: str | None = None, remote: str = "origin", branch: str | None = None) -> dict:
    """Push commits to git remote (Zero-API / GitHub sync)."""
    root = Path(path) if path else config.get_workspace_dir()
    git = shutil.which("git")
    if not git:
        return {"ok": False, "message": "git is not installed or not on PATH"}
    try:
        if not branch:
            b_proc = await asyncio.create_subprocess_exec(
                git, "rev-parse", "--abbrev-ref", "HEAD",
                cwd=str(root), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            out, _ = await b_proc.communicate()
            branch = out.decode("utf-8", "replace").strip() or "main"

        proc = await asyncio.create_subprocess_exec(
            git, "push", "-u", remote, branch,
            cwd=str(root), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        msg = (out.decode("utf-8", "replace") + "\n" + err.decode("utf-8", "replace")).strip()
        if proc.returncode == 0:
            return {"ok": True, "message": f"Successfully pushed to {remote}/{branch}.\n{msg}"}
        else:
            return {"ok": False, "message": f"Push failed: {msg}"}
    except Exception as e:
        return {"ok": False, "message": f"Error running push: {e}"}


async def deploy_zero_api(path: str | None = None, target: str = "vercel") -> dict:
    """Zero-API 1-click deployments for Vercel, Netlify, GitHub Pages, Replit, Lovable."""
    root = Path(path) if path else config.get_workspace_dir()
    target = target.lower()

    if target == "vercel":
        cmd = "npx vercel --prod --yes"
    elif target == "netlify":
        cmd = "npx netlify deploy --prod --dir=dist"
    elif target == "github_pages":
        cmd = "npx gh-pages -d dist"
    elif target in ("replit", "lovable"):
        # Neither service has an import API Nova can drive, so this produces a
        # reviewed source ZIP for the user to import; nothing is uploaded.
        from . import project_export
        try:
            return await asyncio.to_thread(
                project_export.create_export, root, Path(config.DB_PATH).parent / "exports", target=target)
        except (OSError, ValueError) as e:
            return {"ok": False, "status": "export_failed", "target": target, "message": f"Export failed: {e}"}
    else:
        return {"ok": False, "message": "Unsupported deployment target", "target": target}

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
        output_str = out.decode("utf-8", "replace")
        clean_out = _ANSI.sub("", output_str).strip()
        return {
            "ok": proc.returncode == 0,
            "command": cmd,
            "output": clean_out,
            "message": f"Deployment command finished (exit {proc.returncode})."
        }
    except Exception as e:
        return {"ok": False, "command": cmd, "message": f"Deployment failed: {e}"}

