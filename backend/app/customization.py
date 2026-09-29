"""Persist user-requested tabs through the same contract used by Nova's tools."""
import re
import uuid
from . import db


SUGGESTIONS = [
    {"id": "flashcards", "title": "Flashcards", "description": "Optional study decks and practice review.", "installed": False},
    {"id": "custom", "title": "Build a tab with Nova", "description": "Describe the feature you want to add.", "installed": False},
]


async def manage(action: str, id: str = "", title: str = "", icon: str = "Sparkles",
                 description: str = "", content_type: str = "widget", html_content: str = "") -> dict:
    if action == "list":
        return {"ok": True, "tabs": await db.list_custom_tabs()}
    if action == "suggest":
        installed = {tab['id'] for tab in await db.list_custom_tabs()}
        return {"ok": True, "suggestions": [dict(item, installed=item['id'] in installed) for item in SUGGESTIONS]}
    if action not in {"save", "remove"}:
        raise ValueError("Use list, suggest, save, or remove")
    if action == "remove" and not id:
        raise ValueError("The tab id is required")
    tab_id = id or uuid.uuid4().hex[:12]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", tab_id):
        raise ValueError("Tab id must contain 1-64 letters, digits, underscores or hyphens")
    if action == "remove":
        return {"ok": True, "deleted": await db.delete_custom_tab(tab_id), "tab_id": tab_id}
    if not isinstance(title, str) or not title.strip() or len(title) > 80:
        raise ValueError("Tab title must contain 1-80 characters")
    if content_type != "widget":
        raise ValueError("The current tab renderer supports widget content only; use source repair for new components")
    if not isinstance(html_content, str) or len(html_content.encode('utf-8')) > 500_000:
        raise ValueError("Widget HTML must be text of at most 500 KB")
    tab = await db.save_custom_tab(tab_id, title.strip(), icon, description, content_type, html_content)
    return {"ok": True, "tab": tab, "message": "Tab saved. Reload the tab list to display it."}
