"""Per-model mascot art, supplied by the user rather than shipped.

Nova bundles an original pixel set (frontend/src/assets/mascots) so the crew
reads correctly out of the box. This module is the override: drop
`claude.png`, `codex.png`, `gemini.png`, `ollama.png` or `openrouter.png` into
~/.ai-council/mascots/ and that art is used instead.

Why a user directory and not the repo: the mascots people actually want here are
other companies' characters -- Anthropic's Clawd, OpenAI's Codex pets -- and
those are their trademarks. On one person's machine that is unremarkable; baked
into a git repository and a 944MB installer it is a different thing entirely.
Keeping them beside .env and the database means they are inherited by the
installed app automatically and never travel with a build.

Any still image works. A two-frame horizontal strip (width twice the height)
animates; a square image is treated as a single frame and the UI bobs it
instead, so a screenshot cropped square is a perfectly good input.
"""
from __future__ import annotations

import io
from pathlib import Path

from . import config

MASCOT_DIR = config.USER_DATA_DIR / "mascots"
# The models the crew can show. Names are the file stems users drop in.
KNOWN = ("claude", "codex", "gemini", "ollama", "openrouter", "nova")
# Order matters: the first extension found wins, and webp is listed because
# OpenAI's own pet sheets are distributed as webp.
EXTENSIONS = (".png", ".webp", ".gif")
MAX_BYTES = 8_000_000


def _safe_name(name: str) -> str:
    """Reject anything that is not a plain known mascot name.

    The value reaches here from a URL path, so a traversal attempt must not be
    able to turn this into a general-purpose file reader for the user's home
    directory.
    """
    cleaned = (name or "").strip().lower()
    if cleaned not in KNOWN:
        raise ValueError(f"Unknown mascot '{name}'. Expected one of: {', '.join(KNOWN)}.")
    return cleaned


def path_for(name: str) -> Path | None:
    """The user's file for this mascot, or None to fall back to the bundled art."""
    stem = _safe_name(name)
    for extension in EXTENSIONS:
        candidate = MASCOT_DIR / f"{stem}{extension}"
        if candidate.is_file() and candidate.stat().st_size <= MAX_BYTES:
            return candidate
    return None


def status() -> dict:
    """What the UI needs to decide between user art and the bundled set, and
    what Settings needs to show why a file did not take."""
    entries = {}
    for name in KNOWN:
        found = path_for(name)
        entries[name] = {
            "custom": found is not None,
            "file": found.name if found else None,
            "bytes": found.stat().st_size if found else None,
        }
    return {
        "directory": str(MASCOT_DIR),
        "mascots": entries,
        "ignored": _ignored_files({e["file"] for e in entries.values() if e["file"]}),
    }


def _ignored_files(loaded: set[str]) -> list[str]:
    """Files sitting in the directory that Nova will never load.

    Almost always a misnamed drop -- `Clawd.PNG`, `claude-pet.png`, a .jpg --
    and silently ignoring them looks identical to the loader being broken.

    Driven by what `path_for` actually resolved rather than by re-deriving the
    expected names: Windows matches paths case-insensitively, so `Claude.PNG`
    loads fine there and must not then be reported as ignored.
    """
    if not MASCOT_DIR.is_dir():
        return []
    return sorted(
        entry.name for entry in MASCOT_DIR.iterdir()
        if entry.is_file() and entry.name not in loaded
    )


def ensure_directory() -> Path:
    MASCOT_DIR.mkdir(parents=True, exist_ok=True)
    return MASCOT_DIR


# The image formats the UI can actually render, mapped to the extension we
# store under. The stored extension comes from what the bytes *are*, never from
# the uploaded filename: "clawd.png" that is really a JPEG would be written as
# a .png the browser then refuses, and a filename is attacker-controlled input
# in the general case even when the attacker here is a mis-click.
_FORMAT_EXTENSIONS = {"PNG": ".png", "WEBP": ".webp", "GIF": ".gif", "JPEG": ".png"}


def save(name: str, data: bytes) -> dict:
    """Store one image as this mascot's art, replacing whatever was there.

    This is the supported way to supply other companies' characters -- Clawd,
    a Codex pet -- which is why it writes to the user's own directory beside
    .env rather than anywhere inside the repo or the installed app.
    """
    from PIL import Image  # deferred: heavy import

    stem = _safe_name(name)
    if not data:
        raise ValueError("The file was empty.")
    if len(data) > MAX_BYTES:
        raise ValueError(
            f"That image is {len(data) // 1_000_000}MB; the limit is {MAX_BYTES // 1_000_000}MB."
        )

    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()  # parses the header; does not decode the whole image
        with Image.open(io.BytesIO(data)) as image:
            fmt, size = image.format, image.size
            if fmt == "JPEG":
                # Stored as PNG so every mascot file is one of the three
                # extensions path_for looks for, and so transparency is
                # possible if the user later replaces it.
                buffer = io.BytesIO()
                image.convert("RGBA").save(buffer, format="PNG")
                data = buffer.getvalue()
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"That file is not an image Nova can read ({exc}).") from exc

    extension = _FORMAT_EXTENSIONS.get(fmt or "")
    if extension is None:
        raise ValueError(
            f"{fmt or 'That file'} is not supported. Use a PNG, WEBP, GIF or JPEG."
        )

    ensure_directory()
    # Remove the other extensions first: path_for takes the first one it finds,
    # so leaving a stale claude.gif beside a new claude.png would keep serving
    # the old art and look like the upload silently failed.
    for other in EXTENSIONS:
        candidate = MASCOT_DIR / f"{stem}{other}"
        if candidate != MASCOT_DIR / f"{stem}{extension}" and candidate.is_file():
            candidate.unlink()
    (MASCOT_DIR / f"{stem}{extension}").write_bytes(data)

    width, height = size
    return {
        "name": stem,
        "file": f"{stem}{extension}",
        "width": width,
        "height": height,
        # A strip twice as wide as it is tall is read as two frames; anything
        # else is a single frame. Reported so the UI can say which it got
        # rather than leaving the user to wonder why it is not animating.
        "frames": 2 if height and width == height * 2 else 1,
    }


def remove(name: str) -> bool:
    """Drop the user's art for one mascot, falling back to the bundled set."""
    stem = _safe_name(name)
    removed = False
    for extension in EXTENSIONS:
        candidate = MASCOT_DIR / f"{stem}{extension}"
        if candidate.is_file():
            candidate.unlink()
            removed = True
    return removed
