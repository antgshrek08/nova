"""One place every notification goes through.

Something worth telling the user -- a reply finished, a team job finished or
failed, new homework appeared, a reminder, or Nova needs them -- calls
notify(). It is then:

- kept in a short history, which the app's bell shows and the desktop app
  polls to raise a real Windows notification (only when Nova's window isn't
  the one in front: the app decides that, it's the one that knows);
- pushed to every phone that turned notifications on (app/push.py), unless
  the user switched that kind off, it's quiet hours, or it's a chat reply
  and they haven't asked for replies on the phone.

Nothing here may break the thing that noticed: every failure is logged and
swallowed, and notify() always returns what it did.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime

from . import db, operator_store as store

logger = logging.getLogger(__name__)

KIND = "notice"
KEEP = 200

# kind -> the setting that turns it on, and a default tag (same tag replaces
# an earlier notification instead of stacking another).
KINDS = {
    "reply": "notify_replies",
    "task": "notify_tasks",
    "homework": "notify_homework",
    "reminder": "notify_reminders",
    "needs_you": "notify_needs_you",
}


def _on(settings: dict, key: str, default: bool = True) -> bool:
    raw = settings.get(key)
    if raw is None:
        return default
    return str(raw) in ("1", "True", "true")


def quiet_now(spec: str | None, now: datetime | None = None) -> bool:
    """Whether "HH:MM-HH:MM" covers now; the range may cross midnight."""
    if not spec or "-" not in spec:
        return False
    try:
        start, end = (datetime.strptime(x.strip(), "%H:%M").time() for x in spec.split("-", 1))
    except ValueError:
        return False
    t = (now or datetime.now()).time()
    return start <= t < end if start <= end else (t >= start or t < end)


def recent(since: float = 0, limit: int = 50) -> list[dict]:
    rows = [r for r in store.listing(KIND) if r.get("at", 0) > since]
    return sorted(rows, key=lambda r: r["at"], reverse=True)[:limit]


def mark_read(ids: list[str] | None = None) -> int:
    # Read first, then write each row in its own short transaction: a second
    # connection opened inside BEGIN IMMEDIATE would wait on the first.
    rows = store.listing(KIND) if ids is None else [store.get(KIND, i) for i in ids]
    changed = 0
    for row in rows:
        if row and not row.get("read"):
            row["read"] = True
            store.put(KIND, row["id"], row)
            changed += 1
    return changed


def clear() -> None:
    with store.transaction() as conn:
        conn.execute("DELETE FROM records WHERE kind=?", (KIND,))


def _trim() -> None:
    with store.transaction() as conn:
        conn.execute(
            "DELETE FROM records WHERE kind=? AND rowid NOT IN "
            "(SELECT rowid FROM records WHERE kind=? ORDER BY rowid DESC LIMIT ?)", (KIND, KIND, KEEP))


async def notify(kind: str, title: str, body: str, *, url: str = "/app/", tag: str | None = None,
                 view: str | None = None) -> dict:
    """Record a notification and push it to phones if the user wants that."""
    result = {"kind": kind, "stored": False, "pushed": 0, "skipped": None}
    try:
        settings = await db.get_app_settings()
    except Exception:  # noqa: BLE001
        settings = {}
    setting = KINDS.get(kind)
    if setting and not _on(settings, setting):
        result["skipped"] = "turned off"
        return result
    try:
        # put(), not create(): create()'s first parameter is also called kind.
        key = uuid.uuid4().hex
        row = store.put(KIND, key, {"id": key, "kind": kind, "title": title[:140], "body": body[:400], "url": url,
                                    "view": view, "tag": tag or f"nova-{kind}", "at": time.time(), "read": False})
        _trim()
        result.update(stored=True, id=row["id"])
    except Exception:  # noqa: BLE001
        logger.exception("Could not record a notification")

    if not _on(settings, "notify_phone"):
        result["skipped"] = "phone notifications are off"
    elif kind == "reply" and not _on(settings, "notify_phone_replies", False):
        result["skipped"] = "replies aren't sent to the phone"
    elif quiet_now(settings.get("quiet_hours")) and kind != "needs_you":
        result["skipped"] = "quiet hours"
    else:
        try:
            from . import push
            sent = await push.send(title, body, url=url, tag=tag or f"nova-{kind}")
            result["pushed"] = sent.get("sent", 0)
            if sent.get("sent"):
                await db.touch_push_subscriptions()
        except Exception:  # noqa: BLE001
            logger.exception("Push failed")
    return result
