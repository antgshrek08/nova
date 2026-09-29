"""Sending Nova something the way you'd send it to a friend.

The ask: share an Instagram reel, a YouTube video or a TikTok from the phone
and have Nova actually take it in -- not store a URL, but watch the thing and
know what is in it.

On iOS there is no Web Share Target API, so a web app cannot appear in the
share sheet however it is installed. An iOS Shortcut can, and it needs no App
Store, no developer account and no Mac -- which matters, because the machine
Nova lives on is a PC. The Shortcut posts here.

What arrives is a URL and sometimes a title, and what should come back is
short: this is read on a phone, a second after tapping Share, usually while
the user is still in Instagram. So the reply is one or two sentences, and the
real work -- the transcript, the conversation it lands in -- is waiting in
Nova when they next open it.

A share is deliberately NOT a command. "Add this to your source code" is a
thing to say in a conversation, with the video already read and Nova able to
ask what part was meant. Acting on a link the instant it arrives, with no
chance to confirm, is how you end up with a feature nobody asked for.
"""
from __future__ import annotations

import asyncio
import logging

from . import db, knowledge, look, video

logger = logging.getLogger(__name__)

# Shares land in one long-running conversation rather than a new one each
# time: twenty conversations called "Shared link" is a worse history than one
# thread of things the user sent, which is also how it reads on a phone.
CONVERSATION_TITLE = "Shared with Nova"


async def _conversation() -> int:
    for row in await db.list_conversations():
        if row["title"] == CONVERSATION_TITLE:
            return row["id"]
    created = await db.create_conversation("chat", title=CONVERSATION_TITLE)
    return created["id"]


_HEADLINES = {
    "video": "Watched that",
    "image": "Looked at that image",
    "page": "Read that page",
    "text": "Read that",
}


async def _look_and_notify(url: str, conversation_id: int) -> None:
    """Take in whatever was shared, write it into the thread, and say so.

    One function for every kind of thing, because the ending is the same for
    all of them: a description in the conversation and a question on the
    phone. What differs is only which reader runs, and look_at already
    decides that.

    Everything here is best-effort. The share was answered a minute ago, so a
    failure now has to land in the conversation as a sentence the user can
    act on rather than disappearing into a log.
    """
    from . import nova_tools, push

    try:
        result = await nova_tools._look_at(url)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Looking at a shared link failed", exc_info=True)
        result = {"ok": False, "error": str(exc)[:200]}

    if not result.get("ok"):
        message = result.get("error") or "I couldn't make sense of that one."
        await db.add_message(conversation_id, "assistant", f"{message}\n{url}", category="everyday")
        await push.send("Couldn't read that", message[:140], tag="nova-look")
        return

    kind = result.get("kind_of_thing", "page")
    shows = (result.get("shows") or result.get("content") or "").strip()
    body = [shows[:4000]]
    if result.get("spoken"):
        body.append(f"\n**What's said:** {result['spoken'][:600]}")
    body.append(f"\n{result['ask_the_user']}")
    body.append(f"\n{url}")
    await db.add_message(conversation_id, "assistant", "\n".join(body), category="everyday")

    # The question is the notification, not a summary. He shared it to decide
    # what to do with it; the description is waiting in the thread.
    await push.send(
        _HEADLINES.get(kind, "Looked at that"),
        result["ask_the_user"],
        url="/app/",
        tag="nova-look",
    )

    try:
        knowledge.learn_in_background(
            conversation_id, None, f"I shared this: {url}", shows[:4000]
        )
    except Exception:  # noqa: BLE001
        logger.debug("Could not queue knowledge from a shared link", exc_info=True)


async def receive(url: str | None = None, text: str | None = None,
                  title: str | None = None) -> dict:
    """Take in something shared from the phone."""
    candidate = (url or "").strip() or (text or "").strip()
    if not candidate:
        return {"ok": False, "reply": "Nothing came through with that share."}

    found = video.find_urls(candidate)
    conversation_id = await _conversation()

    # The user's own message, so the thread reads like they sent it -- which
    # they did.
    await db.add_message(conversation_id, "user",
                         f"Shared: {title or candidate}".strip(), category="everyday")

    # Anything with a link in it gets looked at; anything else is text.
    #
    # One path rather than four. A reel used to be watched, a YouTube link
    # had its captions read, and a website was met with "Saved this to look
    # at" -- which is a polite way of saying it was not looked at. The user
    # should not have to know which branch they are triggering before they tap
    # Share.
    #
    # And the looking happens after the reply, not before it. This endpoint
    # answers at the share sheet, a second after the tap, while they are still
    # inside Instagram; watching a clip takes about ninety seconds. So the
    # reply goes back immediately and the work reports itself through the
    # notification channel when it lands -- which is what push was built for.
    target = found[0] if found else look.find_url(candidate)
    if not target:
        await db.add_message(conversation_id, "assistant",
                             f"Saved this: {candidate}", category="everyday")
        return {"ok": True, "kind": "note", "reply": "Saved that.",
                "conversation_id": conversation_id}

    asyncio.create_task(_look_and_notify(target, conversation_id))
    return {
        "ok": True, "kind": "looking", "watching": True,
        "reply": "Got it — looking at that now. I'll tell you what's in it.",
        "conversation_id": conversation_id,
    }
