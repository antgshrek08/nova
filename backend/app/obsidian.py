"""Obsidian vault integration via the Local REST API community plugin
(Phase 3).

Our own writes always land directly on disk (OBSIDIAN_VAULT_DIR) -- that
works whether or not Obsidian is even open, and is how the vault gets its
content in the first place. The Local REST API plugin is used specifically
to read a note back through the live app before overwriting it: if the user
has hand-edited a project note in Obsidian, this merges our regenerated
content back in above their edits rather than clobbering them, by
preserving everything below the AUTO_MARKER line. When the plugin isn't
reachable (Obsidian not running, or no API key configured), sync still
works -- it just reads/writes straight to disk instead of through the API.
"""
from __future__ import annotations

import re

import httpx

from . import config

AUTO_MARKER = "<!-- ai-council:auto-generated-above (anything below this line is yours) -->"

_DEFAULT_USER_SECTION = (
    "\n\n## Your notes\n\n"
    "_Anything you write below the marker above is kept as-is the next time "
    "this note regenerates._\n"
)


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.OBSIDIAN_API_KEY}"} if config.OBSIDIAN_API_KEY else {}


async def is_api_available() -> bool:
    if not config.OBSIDIAN_API_KEY:
        return False
    try:
        async with httpx.AsyncClient(verify=False, timeout=3) as client:
            resp = await client.get(config.OBSIDIAN_API_BASE_URL + "/")
            return resp.status_code == 200
    except Exception:  # noqa: BLE001 - plugin/app simply isn't up
        return False


async def _read_note(vault_relative_path: str) -> str | None:
    """Read a note's current content, preferring the live plugin (so an
    edit sitting unsaved in an open Obsidian tab isn't missed), falling
    back to a direct file read when the plugin isn't reachable.
    """
    if config.OBSIDIAN_API_KEY:
        try:
            async with httpx.AsyncClient(verify=False, timeout=5) as client:
                resp = await client.get(
                    f"{config.OBSIDIAN_API_BASE_URL}/vault/{vault_relative_path}",
                    headers=_headers(),
                )
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code == 404:
                    return None
        except Exception:  # noqa: BLE001
            pass  # fall through to a direct file read

    path = config.OBSIDIAN_VAULT_DIR / vault_relative_path
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


async def _write_note(vault_relative_path: str, content: str) -> None:
    """Write a note both ways: directly to disk (the durable copy, correct
    even when Obsidian isn't running) and, when reachable, through the live
    plugin too so an already-open Obsidian view refreshes immediately.
    """
    path = config.OBSIDIAN_VAULT_DIR / vault_relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    if config.OBSIDIAN_API_KEY:
        try:
            async with httpx.AsyncClient(verify=False, timeout=5) as client:
                await client.put(
                    f"{config.OBSIDIAN_API_BASE_URL}/vault/{vault_relative_path}",
                    headers={**_headers(), "Content-Type": "text/markdown"},
                    content=content.encode("utf-8"),
                )
        except Exception:  # noqa: BLE001
            pass  # the direct file write above already covers the durable copy


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "untitled"


def _render_project_note(project: dict, conversations: list[dict], files: list[dict]) -> str:
    lines = [
        "---",
        f"project_id: {project['id']}",
        "tags: [ai-council, project]",
        "---",
        "",
        f"# {project['name']}",
        "",
        "## Instructions",
        "",
        project["instructions"] or "_None set._",
        "",
        "## Files",
        "",
    ]
    lines += (
        [f"- {f['filename']} ({f['size_bytes']} bytes)" for f in files]
        if files
        else ["_No files attached._"]
    )
    lines += ["", "## Conversations", ""]
    lines += (
        [f"- **{c['title']}** -- updated {c['updated_at']}" for c in conversations]
        if conversations
        else ["_No conversations yet._"]
    )
    lines += ["", AUTO_MARKER]
    return "\n".join(lines)


async def sync_project_note(project: dict, conversations: list[dict], files: list[dict]) -> str:
    """Regenerate a project's note, preserving any hand-written content the
    user added below AUTO_MARKER. Returns the vault-relative path written.
    """
    relative_path = f"Projects/{_safe_filename(project['name'])}.md"

    existing = await _read_note(relative_path)
    if existing and AUTO_MARKER in existing:
        user_section = existing.split(AUTO_MARKER, 1)[1]
    else:
        user_section = _DEFAULT_USER_SECTION

    content = _render_project_note(project, conversations, files) + user_section
    await _write_note(relative_path, content)
    return relative_path


_TAB_LABEL = {"chat": "Chat", "code": "Code"}


def conversation_note_path(conversation: dict, project: dict | None) -> str:
    """Every conversation's note path -- project-attached conversations live
    alongside their project note; everything else is organized by tab and
    creation date (a "general/unassigned" grouping falls out naturally,
    since ungrouped chats simply land under Conversations/<tab>/<date>/
    rather than under Projects/).

    Keyed by title, same as project notes -- not by id -- so it stays
    human-browsable in the Obsidian file tree. Title collisions (very
    common; "New conversation" is the default) are broken by appending the
    conversation id, which also keeps the path stable enough in practice
    since conversations are rarely renamed.
    """
    safe_title = _safe_filename(conversation["title"])
    suffix = f"{safe_title} ({conversation['id']}).md"
    if project is not None:
        return f"Projects/{_safe_filename(project['name'])}/{suffix}"
    date = (conversation["created_at"] or "")[:10] or "unknown-date"
    tab_label = _TAB_LABEL.get(conversation["tab"], conversation["tab"])
    return f"Conversations/{tab_label}/{date}/{suffix}"


def _render_conversation_note(conversation: dict, messages: list[dict], project: dict | None) -> str:
    flags = []
    if conversation.get("pinned"):
        flags.append("pinned")
    if conversation.get("homework"):
        flags.append("homework")
    if conversation.get("schedule_label"):
        flags.append(f"scheduled: {conversation['schedule_label']}")

    lines = [
        "---",
        f"conversation_id: {conversation['id']}",
        f"tab: {conversation['tab']}",
        f"project_id: {conversation['project_id'] if conversation['project_id'] is not None else 'none'}",
        f"pinned: {bool(conversation.get('pinned'))}",
        f"homework: {bool(conversation.get('homework'))}",
        f"schedule_label: {conversation.get('schedule_label') or 'none'}",
        f"created_at: {conversation['created_at']}",
        f"updated_at: {conversation['updated_at']}",
        f"tags: [ai-council, conversation, {conversation['tab']}]",
        "---",
        "",
        f"# {conversation['title']}",
        "",
    ]
    if project is not None:
        lines += [f"Part of project: **{project['name']}**", ""]
    if flags:
        lines += [f"_{', '.join(flags)}_", ""]

    lines += ["## Messages", ""]
    if not messages:
        lines += ["_No messages yet._"]
    for m in messages:
        if m["role"] == "user":
            lines += [f"**User** ({m['created_at']}):", "", m["content"], ""]
        elif m["role"] == "assistant":
            badge_bits = [b for b in (m.get("label") or m.get("provider"), m.get("category")) if b]
            badge = f" — {' · '.join(badge_bits)}" if badge_bits else ""
            lines += [f"**Assistant**{badge} ({m['created_at']}):", "", m["content"], ""]
        else:
            lines += [f"_{m['role']}: {m['content']}_", ""]

    lines += [AUTO_MARKER]
    return "\n".join(lines)


async def sync_conversation_note(conversation: dict, messages: list[dict], project: dict | None) -> str:
    """Regenerate one conversation's note (every Chat/Code conversation gets
    one, project-attached or not), preserving hand-written content below
    AUTO_MARKER the same way project notes do. Returns the vault-relative
    path written.
    """
    relative_path = conversation_note_path(conversation, project)

    existing = await _read_note(relative_path)
    if existing and AUTO_MARKER in existing:
        user_section = existing.split(AUTO_MARKER, 1)[1]
    else:
        user_section = _DEFAULT_USER_SECTION

    content = _render_conversation_note(conversation, messages, project) + user_section
    await _write_note(relative_path, content)
    return relative_path


def ensure_vault_bootstrap() -> None:
    """Create a friendly top-level note the first time the vault is used, so
    opening the folder in Obsidian ("Open folder as vault") shows something
    immediately instead of an empty vault.
    """
    welcome = config.OBSIDIAN_VAULT_DIR / "Welcome.md"
    if welcome.exists():
        return
    welcome.write_text(
        "# AI Council vault\n\n"
        "This vault is written to automatically by the AI Council backend.\n\n"
        "- `Projects/<name>.md` -- one summary note per project, regenerated whenever "
        "the project's instructions, files, or conversation list change.\n"
        "- `Projects/<name>/<conversation> (id).md` -- one note per conversation "
        "attached to that project, regenerated after every message.\n"
        "- `Conversations/<Chat|Code>/<date>/<conversation> (id).md` -- every other "
        "conversation (not attached to a project), grouped by tab and the date it was "
        "created, regenerated after every message.\n\n"
        "Anything you write below the marker comment in any of these notes is "
        "preserved across regenerations.\n\n"
        "To get live two-way sync (so hand-edits here are read back correctly instead "
        "of being overwritten), install and enable the **Local REST API** community "
        "plugin in Obsidian, then copy its API key into `backend/.env` as "
        "`OBSIDIAN_API_KEY`.\n",
        encoding="utf-8",
    )


ensure_vault_bootstrap()
