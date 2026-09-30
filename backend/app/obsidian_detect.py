"""Finding the user's Obsidian vaults without asking them to browse for one.

Two sources, strongest first:

1. Obsidian's own list of vaults (obsidian.json in its settings folder on
   Windows, macOS and Linux) -- every vault the user ever opened here, and
   which one is open now.
2. A short, bounded look through the usual places a vault lives (Documents,
   Desktop, OneDrive, iCloud Drive, Dropbox, the home folder) for folders
   holding a `.obsidian` directory -- vaults synced to this computer that
   Obsidian hasn't opened on it yet.

Folders that no longer exist are skipped, each vault says how many notes it
has, and ones Nova already reads are marked, so the list is something the
user can tick rather than something they have to interpret.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SKIP = {"node_modules", ".git", "AppData", "Library", "$RECYCLE.BIN", "Program Files", "Program Files (x86)",
        "Windows", ".cache", ".venv", "venv", "__pycache__", ".npm", ".nuget", ".vscode", ".cursor", "site-packages"}
SCAN_DEPTH = 4
SCAN_SECONDS = 4.0


def _config_files() -> list[Path]:
    home = Path.home()
    out = []
    if os.getenv("APPDATA"):
        out.append(Path(os.environ["APPDATA"]) / "obsidian" / "obsidian.json")
    out += [
        home / "AppData" / "Roaming" / "obsidian" / "obsidian.json",
        home / "Library" / "Application Support" / "obsidian" / "obsidian.json",
        Path(os.getenv("XDG_CONFIG_HOME", str(home / ".config"))) / "obsidian" / "obsidian.json",
        home / ".var" / "app" / "md.obsidian.Obsidian" / "config" / "obsidian" / "obsidian.json",
    ]
    seen, uniq = set(), []
    for p in out:
        if str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq


def _scan_roots() -> list[Path]:
    home = Path.home()
    roots = [home / "Documents", home / "Desktop", home / "OneDrive", home / "Dropbox", home / "Obsidian",
             home / "iCloudDrive", home / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents"]
    roots += [p for p in home.glob("OneDrive*") if p.is_dir()]
    roots.append(home)
    return [r for r in dict.fromkeys(roots) if r.is_dir()]


def _note_count(path: Path, cap: int = 5000) -> int:
    n = 0
    for _root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        n += sum(1 for f in files if f.endswith(".md"))
        if n >= cap:
            return cap
    return n


def _from_config() -> dict[str, dict]:
    found: dict[str, dict] = {}
    for cfg in _config_files():
        if not cfg.exists():
            continue
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Couldn't read %s: %s", cfg, exc)
            continue
        for info in (data.get("vaults") or {}).values():
            path = info.get("path")
            if path and Path(path).is_dir():
                key = os.path.normcase(os.path.abspath(path))
                found[key] = {"path": path, "is_open": bool(info.get("open")), "ts": info.get("ts") or 0, "source": "obsidian"}
    return found


def _from_disk(known: dict[str, dict]) -> None:
    deadline = time.monotonic() + SCAN_SECONDS
    for root in _scan_roots():
        depth0 = len(root.parts)
        for current, dirs, _files in os.walk(root):
            if time.monotonic() > deadline:
                return
            here = Path(current)
            if ".obsidian" in dirs:
                key = os.path.normcase(os.path.abspath(current))
                known.setdefault(key, {"path": str(here), "is_open": False, "ts": 0, "source": "found"})
                dirs[:] = []  # a vault inside a vault isn't a separate vault
                continue
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".") and len(here.parts) - depth0 < SCAN_DEPTH]


def detect(connected_paths: list[str] | None = None) -> dict:
    vaults = _from_config()
    _from_disk(vaults)
    connected = {os.path.normcase(os.path.abspath(p)) for p in (connected_paths or [])}
    from . import config
    nova_own = os.path.normcase(os.path.abspath(str(config.OBSIDIAN_VAULT_DIR)))
    out = []
    for key, v in vaults.items():
        path = Path(v["path"])
        out.append({
            "name": "Nova's notes" if key == nova_own else (path.name or "Obsidian vault"),
            "path": v["path"],
            "notes": _note_count(path),
            "is_open": v["is_open"],
            "ts": v["ts"],
            "source": v["source"],
            "connected": key in connected,
            "nova_own": key == nova_own,
        })
    # Open in Obsidian first, then most recently used, then what the scan found.
    out.sort(key=lambda x: (x["nova_own"], not x["is_open"], x["source"] != "obsidian", -(x["ts"] or 0), x["name"].lower()))
    return {"detected": bool(out), "vaults": out}


WELCOME = """# Welcome to your notes

This folder is an Obsidian vault: plain notes you own, kept on this computer.

- Open it in Obsidian (free, obsidian.md) with "Open folder as vault".
- Ask Nova to take notes from a reading, a lecture or a chat, and they land here.
- Nova reads these notes when it answers, so it knows what you already wrote.
"""


def create_vault(name: str = "Nova Notes") -> dict:
    """A new, ready-to-open Obsidian vault in the user's Documents folder."""
    clean = "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip() or "Nova Notes"
    base = Path.home() / "Documents"
    base.mkdir(parents=True, exist_ok=True)
    path = base / clean
    n = 2
    while path.exists() and any(path.iterdir()) and not (path / ".obsidian").is_dir():
        path = base / f"{clean} {n}"
        n += 1
    (path / ".obsidian").mkdir(parents=True, exist_ok=True)
    welcome = path / "Welcome.md"
    if not welcome.exists():
        welcome.write_text(WELCOME, encoding="utf-8")
    return {"name": path.name, "path": str(path)}
