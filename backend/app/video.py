"""Reading a video without watching it.

The ask: send Nova a YouTube link or an Instagram reel and say "add this to
your source code" -- so Nova has to get from a URL to what the video actually
says, reliably enough to act on.

What this does NOT do is download the video. Captions are the content for
anything explanatory, they are a text fetch rather than a media transfer, and
they cost a second instead of a minute. A link Nova cannot read is reported
as exactly that: "this one has no captions" is a useful answer, and guessing
from a title would be worse than useless when the next step is editing code.

Instagram and TikTok go through the same extractor. They work when the post
is public; a private or login-walled one fails, and that failure is passed
through in the words the extractor used rather than flattened into
"couldn't read it", because "login required" and "video unavailable" need
different things from the user.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import config

# Hosts worth claiming support for. Anything else is still attempted -- the
# extractor handles a thousand sites -- but these are the ones the tool
# description promises, so they are the ones that get tested.
KNOWN_HOSTS = (
    "youtube.com", "youtu.be", "instagram.com", "tiktok.com",
    "twitter.com", "x.com", "vimeo.com", "reddit.com",
)

_URL = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)

# A transcript long enough to bury the request it was attached to. Two hours
# of speech is roughly 20k words; the useful part of "watch this and add it"
# is never the whole thing.
MAX_TRANSCRIPT_CHARS = 24_000
MAX_DURATION_SECONDS = 4 * 60 * 60
_FETCH_TIMEOUT = 30


def find_urls(text: str) -> list[str]:
    """Video links in a message, in the order they appear."""
    found = []
    for url in _URL.findall(text or ""):
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        if any(host == known or host.endswith("." + known) for known in KNOWN_HOSTS):
            if url not in found:
                found.append(url)
    return found


def looks_like_video(url: str) -> bool:
    return bool(find_urls(url))


class _Silent:
    """yt-dlp writes straight to stderr even with quiet=True; a logger of our
    own keeps extractor chatter out of the backend log, while `read` still
    returns the error text to the caller."""

    def debug(self, message): pass
    def info(self, message): pass
    def warning(self, message): pass
    def error(self, message): pass


def _ydl_options(cookies_from_browser: str | None = None) -> dict:
    options = {
        "logger": _Silent(),
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
        "extract_flat": False,
    }
    # yt-dlp needs a JavaScript runtime for some YouTube formats and warns
    # loudly without one. Electron already ships Node on this machine, so
    # point at it when it is there rather than making the user install deno.
    node = shutil.which("node")
    if node:
        options["js_runtimes"] = {"node": {"path": node}}
    # Instagram and TikTok serve almost nothing to a logged-out client. Their
    # own answer is to reuse the browser session, which means reading the
    # user's cookies -- their data, on their machine, at their request, but
    # not something to do by default. Off unless explicitly configured.
    if cookies_from_browser:
        options["cookiesfrombrowser"] = (cookies_from_browser,)
    # A cookies.txt exported from the browser. This is the path that actually
    # works on Windows: reading Chrome's store directly fails because the
    # database is locked while Chrome runs (yt-dlp #7271), and Edge's newer
    # app-bound encryption defeats DPAPI (#10927). An exported file has
    # neither problem, at the cost of being re-exported when it expires.
    cookie_file = config.read_env_value("NOVA_COOKIES_FILE")
    if cookie_file and Path(cookie_file).is_file():
        options["cookiefile"] = cookie_file
    return options


def _text_from_json3(payload: dict) -> str:
    """YouTube's json3 caption format: events of timed text segments."""
    lines = []
    for event in payload.get("events") or []:
        segments = event.get("segs") or []
        text = "".join(seg.get("utf8", "") for seg in segments).strip()
        if text and text != "\n":
            lines.append(text)
    return "\n".join(lines)


def _text_from_vtt(raw: str) -> str:
    """WEBVTT/SRT: drop cue numbers, timestamps and markup, keep the words,
    and collapse the repetition rolling captions produce."""
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        if "-->" in line or line.isdigit():
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        # Rolling captions repeat the previous line with one word added, so
        # consecutive duplicates are noise, not emphasis.
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return "\n".join(lines)


async def _fetch_transcript(info: dict) -> tuple[str, str | None]:
    """(transcript, how) -- how is "captions", "auto-captions" or None."""
    manual = (info.get("subtitles") or {}).get("en") or []
    automatic = (info.get("automatic_captions") or {}).get("en") or []
    for tracks, label in ((manual, "captions"), (automatic, "auto-captions")):
        # json3 parses cleanly; vtt and srt are the widely available fallback.
        for extension in ("json3", "vtt", "srt"):
            track = next((t for t in tracks if t.get("ext") == extension and t.get("url")), None)
            if not track:
                continue
            try:
                async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
                    response = await client.get(track["url"])
                    response.raise_for_status()
                    body = response.text
            except Exception:  # noqa: BLE001 -- try the next format/track
                continue
            if extension == "json3":
                try:
                    text = _text_from_json3(json.loads(body))
                except json.JSONDecodeError:
                    continue
            else:
                text = _text_from_vtt(body)
            if text.strip():
                return text.strip(), label
    return "", None


async def read(url: str, cookies_from_browser: str | None = None) -> dict:
    """Everything Nova can learn about one video without downloading it."""
    import yt_dlp  # deferred: a heavy import for a feature most turns never use

    def _extract():
        with yt_dlp.YoutubeDL(_ydl_options(cookies_from_browser)) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.to_thread(_extract)
    except Exception as exc:  # noqa: BLE001
        # Passed through rather than flattened: "login required" and "video
        # unavailable" need different things from the user, and the extractor
        # already says which it is.
        message = str(exc).split("\n")[0]
        message = re.sub(r"^ERROR:\s*", "", message)
        return {"ok": False, "url": url, "error": message[:300]}

    if info is None:
        return {"ok": False, "url": url, "error": "Nothing readable at that link."}

    duration = info.get("duration") or 0
    if duration and duration > MAX_DURATION_SECONDS:
        return {
            "ok": False, "url": url,
            "error": f"That video is {duration // 3600}h long; Nova reads up to "
                     f"{MAX_DURATION_SECONDS // 3600}h.",
        }

    transcript, how = await _fetch_transcript(info)
    truncated = len(transcript) > MAX_TRANSCRIPT_CHARS
    if truncated:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS]

    return {
        "ok": True,
        "url": info.get("webpage_url") or url,
        "title": info.get("title"),
        "channel": info.get("uploader") or info.get("channel"),
        "duration_seconds": duration,
        "description": (info.get("description") or "")[:2000],
        "transcript": transcript,
        "transcript_source": how,
        "transcript_truncated": truncated,
        # Said plainly, because the next step is usually "now act on this" and
        # acting on a title alone is how you get confident nonsense.
        "note": None if transcript else (
            "This video has no captions, so Nova has the title and description "
            "but not what was actually said."
        ),
    }
