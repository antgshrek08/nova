"""One way in, for anything the user sends Nova.

Until now each kind of thing the user could send had its own path and its own
ending. A reel was watched. A YouTube link had its captions read. A website
was saved with "Saved this to look at", which is a polite way of saying it
was not looked at. An image attached in chat went to the vision model but
never reached the share endpoint at all. Four behaviours, and they had to know
which one they were triggering before they sent it.

"I want Nova to look at anything I send it" is one behaviour: work out what
this is, take it in, and decide what to do about it. That is what this
module is -- a dispatcher in front of the readers that already exist, plus
the judgement at the end that turns understanding into a next move.

The judgement is the part worth arguing about. A summary is a dead end: it
closes the topic and leaves the user to think of the next step themselves,
which is the work they were trying to hand over. So every path here ends in
a question, and the question is chosen rather than templated, because "how do
you want to use this?" is a bad question about a recipe and a worse one about
a bug report. Jev answers that in one round trip as a typed choice with a
confidence, which is exactly the shape the decision needs: a category the
code can branch on, and a number that says whether to trust it. Below the
floor it falls back to the open question, because a confidently wrong
follow-up tells the user Nova misread what they sent.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from . import classifier, typesafe

logger = logging.getLogger(__name__)

# What a thing turns out to be, once looked at. Not the same axis as what to
# do with it -- that is KINDS below.
VIDEO_HOSTS = ("youtube.com", "youtu.be", "instagram.com", "tiktok.com",
               "vimeo.com", "reddit.com", "x.com", "twitter.com", "facebook.com")

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

_URL_RE = re.compile(r"https?://[^\s<>\"')]+")


def find_url(text: str) -> str | None:
    match = _URL_RE.search(text or "")
    return match.group(0) if match else None


def kind_of(url: str) -> str:
    """video, image, or page."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = (parsed.path or "").lower()
    if path.endswith(IMAGE_SUFFIXES):
        return "image"
    if any(host == h or host.endswith("." + h) for h in VIDEO_HOSTS):
        # A bare profile or a subreddit is a page, not a video: it has no
        # single clip to watch, and yt-dlp would either fail or start pulling
        # someone's whole feed.
        if host.endswith("reddit.com") and "/comments/" not in path:
            return "page"
        if host in ("x.com", "twitter.com") and "/status/" not in path:
            return "page"
        if host.endswith("instagram.com") and not any(
            part in path for part in ("/reel", "/p/", "/tv/")
        ):
            return "page"
        return "video"
    return "page"


# What the user could do with it. Deliberately about shape rather than
# subject -- "is this a thing to do, to make, to understand, to copy or to
# keep" is what decides a good follow-up, and it survives whatever topics they
# happens to be interested in this month.
KINDS = {
    "technique": "demonstrates a method or skill to practise or copy",
    "recipe": "a set of steps producing a specific result",
    "idea": "makes an argument or explains a concept, with nothing to physically do",
    "reference": "a design, layout, style, tool or example worth imitating or keeping",
    "task": "something with an action or deadline attached -- a form, a signup, an assignment",
    "entertainment": "meant to be enjoyed, with nothing to apply",
}

FOLLOW_UPS = {
    "technique": "Do you want to try this yourself, or should I break it into steps you can follow?",
    "recipe": "Want me to write this out as steps and a list, or save it for later?",
    "idea": "Is this something you want applied to a project, or thought through further?",
    "reference": "Should I pull out what makes this work, or find where it fits something you're building?",
    "task": "Do you want this on your list, or should I do something with it now?",
    "entertainment": "Anything in this you want me to do something with?",
}

OPEN_QUESTION = "What do you want to do with this?"


async def decide(summary: str, extra: str = "") -> dict:
    """What to ask, now that Nova knows what the thing is.

    Never raises and never blocks the answer: an unreachable Jev costs the
    specific question, not the reply.
    """
    if not typesafe.configured():
        return {"kind": None, "confidence": 0.0, "question": OPEN_QUESTION,
                "why": "TypeSafe isn't configured, so this is the general question."}

    document = summary if not extra else f"{summary}\n\n---\n{extra}"
    try:
        kind, confidence = await typesafe.choose(
            document[:8000],
            "Classify what the user could do with this, by its shape rather than its topic.",
            KINDS,
        )
    except Exception:  # noqa: BLE001
        logger.debug("Jev classification failed", exc_info=True)
        return {"kind": None, "confidence": 0.0, "question": OPEN_QUESTION,
                "why": "Couldn't reach TypeSafe, so this is the general question."}

    # The floor matters more than the category. A specific follow-up aimed at
    # the wrong kind of thing tells the user Nova misunderstood what they
    # sent, which is worse than asking plainly.
    if confidence < classifier.CONFIDENCE_FLOOR:
        return {"kind": kind, "confidence": round(confidence, 2), "question": OPEN_QUESTION,
                "why": f"Jev leaned '{kind}' but only at {confidence:.0%}, below the floor."}
    return {"kind": kind, "confidence": round(confidence, 2), "question": FOLLOW_UPS[kind],
            "why": f"Jev: {kind} at {confidence:.0%}."}
