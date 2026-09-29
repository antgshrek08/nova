"""Watching a video, rather than reading about one.

video.py reads captions. That answers "what was said" and is the wrong
question for a reel: most have no captions at all, and the ones that do are
auto-generated from speech, so they miss everything the video actually shows.
A thirty-second clip demonstrating a technique is almost entirely visual, and
its caption track -- when it exists -- is a transcript of someone saying "so
you just do this, like that".

So this watches. Frames are sampled across the clip and read by a vision
model; the audio is transcribed locally by Whisper, which works whether or not
the platform ever generated captions. Together those are what the video
contains.

Then it stops short of summarising. The user's ask was that Nova watch a reel
and ask them how they want to apply what it showed, which is a different
ending: a summary closes a topic, and a question opens one. Picking a *good*
question is the hard part, because "how do you want to apply this?" is a bad
one -- the useful follow-up for a recipe is not the useful follow-up for a
study technique or a UI pattern. That judgement is what Jev is for.

Three implementation notes.

Frames go to the vision model as one contact sheet, not eight images. Local
vision on this machine takes about eighty seconds for a single image; eight
would be ten minutes for one reel. Tiling them into a grid makes it one call,
and a model reading a 3x3 sheet in time order gets the sequence as well as the
content.

Decoding is done with PyAV rather than a system ffmpeg. PyAV ships the ffmpeg
libraries in its wheel and arrives with faster-whisper, which is already a
dependency -- so this needs no install, on Windows or on the Fedora laptop.

The file is deleted when the read finishes. Nova needs the frames and the
audio, not a library of downloaded video.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import shutil
import tempfile
from pathlib import Path

from . import classifier, typesafe

logger = logging.getLogger(__name__)

# Nine frames in a 3x3 sheet. Enough to carry a sequence -- a before, a
# middle and an after -- without the tiles getting too small for a vision
# model to read text on screen, which is often where the actual content is.
FRAME_COUNT = 9
SHEET_COLUMNS = 3
TILE_WIDTH = 384

# Reels and shorts. A longer video is a different problem: nine frames across
# an hour says nothing, and it should be answered from its captions instead.
MAX_WATCH_SECONDS = 360


class WatchError(Exception):
    """Something the user can act on."""


def _sample_frames(path: Path, count: int = FRAME_COUNT) -> tuple[list, float]:
    """Frames spread evenly across the clip, in order, plus its duration."""
    import av

    # PyAV renamed its base exception: `av.AVError` was gone by PyAV 9 and the
    # installed version here is 18, where it is `av.error.FFmpegError`. Named
    # in an `except` clause, a missing attribute does not quietly not-match --
    # Python evaluates the tuple when something is raised, so the AttributeError
    # replaces the real error. The result was a failed seek surfacing as
    # "Couldn't watch that clip: module 'av' has no attribute 'AVError'", which
    # says nothing about the clip. Resolved once, here, tolerating either name.
    _AV_ERROR = getattr(av, "AVError", None) or getattr(av.error, "FFmpegError", Exception)

    frames = []
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type == "video"), None)
        if stream is None:
            raise WatchError("That file has no video track to watch.")
        duration = float(container.duration / 1_000_000) if container.duration else 0.0
        if duration and duration > MAX_WATCH_SECONDS:
            raise WatchError(
                f"That's {int(duration // 60)} minutes long. I watch clips up to "
                f"{MAX_WATCH_SECONDS // 60} minutes; for something longer, ask me to read it instead."
            )
        stream.thread_type = "AUTO"

        # Seeking per frame is faster than decoding everything, but seeking is
        # keyframe-granular and a short reel may hold only one keyframe -- so
        # for anything brief, decode straight through and pick as we go.
        total_frames = stream.frames or 0
        start_time = float((stream.start_time or 0) * (stream.time_base or 0))
        if duration and duration > 12 and total_frames > count * 4:
            for index in range(count):
                target = start_time + (index + 0.5) / count * duration
                try:
                    container.seek(int(target * av.time_base), any_frame=False, backward=True)
                    # Backward seeks land on a keyframe, often far before
                    # the requested moment. Decode forward to that moment
                    # instead of showing the same keyframe in every tile.
                    frame = next((frame for frame in container.decode(video=0)
                                  if frame.time is not None and frame.time >= target), None)
                    if frame is not None:
                        frames.append(frame.to_image())
                except (StopIteration, _AV_ERROR):
                    continue
        if len(frames) < count:
            frames = []
            # Reopen instead of relying on a failed seek or the decoder's
            # current position. Count in one pass, then retain only the
            # selected images in a second pass. Frame counts in container
            # metadata are often missing; holding every decoded frame can
            # otherwise use gigabytes, and stopping early misses the ending.
            decoded_count = 0
            last_time = 0.0
            first_time = None
            with av.open(str(path)) as scan:
                for frame in scan.decode(video=0):
                    decoded_count += 1
                    if frame.time is not None:
                        if first_time is None:
                            first_time = frame.time
                        last_time = max(last_time, frame.time - first_time)
                        if last_time > MAX_WATCH_SECONDS:
                            raise WatchError(
                                f"I watch clips up to {MAX_WATCH_SECONDS // 60} minutes; "
                                "for something longer, ask me to read it instead."
                            )
            if not decoded_count:
                raise WatchError("I couldn't decode any frames from that video.")
            selected = {min(decoded_count - 1, int((i + 0.5) * decoded_count / count))
                        for i in range(count)}
            last_selected = max(selected)
            with av.open(str(path)) as scan:
                for position, frame in enumerate(scan.decode(video=0)):
                    if position in selected:
                        frames.append(frame.to_image())
                    if position >= last_selected:
                        break
            if not duration:
                duration = last_time
    if not frames:
        raise WatchError("I couldn't get any frames out of that video.")
    return frames, duration


def _contact_sheet(frames: list) -> bytes:
    """Tile frames into one image, left to right, top to bottom."""
    from PIL import Image, ImageDraw

    columns = min(SHEET_COLUMNS, len(frames))
    rows = (len(frames) + columns - 1) // columns
    first = frames[0]
    ratio = first.height / first.width if first.width else 1.0
    tile_height = int(TILE_WIDTH * ratio)

    sheet = Image.new("RGB", (TILE_WIDTH * columns, tile_height * rows), (14, 14, 16))
    draw = ImageDraw.Draw(sheet)
    for index, frame in enumerate(frames):
        tile = frame.convert("RGB").resize((TILE_WIDTH, tile_height))
        x = (index % columns) * TILE_WIDTH
        y = (index // columns) * tile_height
        sheet.paste(tile, (x, y))
        # Numbered, because the model is being asked about a sequence and
        # needs to be able to refer to a moment in it.
        draw.text((x + 8, y + 6), str(index + 1), fill=(255, 255, 255))

    buffer = io.BytesIO()
    sheet.save(buffer, format="JPEG", quality=82)
    return buffer.getvalue()


# The contact sheet is Nova's implementation detail, and a small local model
# leaks it however firmly the prompt asks it not to -- "Starting with frame 1,
# the cat is sitting still". Asking again is not a fix; a 4B model has limited
# instruction-following and this is cheaper to clean than to prevent.
#
# Conservative on purpose: these rewrite the mechanical lead-ins that are
# always wrong and leave everything else alone. A description that reads
# slightly oddly is a much smaller problem than one silently mangled by an
# over-eager regex.
_DEFRAME = [
    # A frame reference used as a list label -- "* **Frame 1:** he opens the
    # laptop" -- is a heading, not a noun in a sentence. The generic
    # substitution turned it into "* **a moment:**", which reads worse than
    # leaving it alone. Stripping the label and keeping the bullet says the
    # same thing without naming the mechanism.
    (re.compile(r"^(\s*[-*]\s*)(?:\*\*)?\s*frames?\s*\d+(?:\s*(?:and|,|-|to)\s*\d+)*\s*:?\s*(?:\*\*)?\s*",
                re.I | re.M), r"\1"),
    (re.compile(r"^(\s*)(?:\*\*)?\s*frames?\s*\d+(?:\s*(?:and|,|-|to)\s*\d+)*\s*:\s*(?:\*\*)?\s*",
                re.I | re.M), r"\1"),
    (re.compile(r"\b(?:starting|beginning) (?:with|at|from) (?:the )?(?:first )?frames? ?\d*\s*,?\s*", re.I), "At the start, "),
    (re.compile(r"\bby (?:the )?(?:final|last) frames?\b,?\s*", re.I), "By the end, "),
    (re.compile(r"\bin the (?:final|last) frames?\b", re.I), "at the end"),
    (re.compile(r"\bby frames? ?\d+\s*,?\s*", re.I), "Then "),
    (re.compile(r"\bin frames? ?\d+(?:\s*(?:and|,|-|to)\s*\d+)*\s*,?\s*", re.I), ""),
    # "Frames 4 and 5 show it recoiling" must not become "Then it recoiling":
    # the tile reference is the subject of that verb, so it needs a different
    # subject rather than deletion.
    (re.compile(r"\bframes? ?\d+(?:\s*(?:and|,|-|to)\s*\d+)*\s+shows?\b", re.I), "later the video shows"),
    (re.compile(r"\bframes? ?\d+(?:\s*(?:and|,|-|to)\s*\d+)*\b", re.I), "a moment"),
    (re.compile(r"\b(?:the )?(?:image|photo) sequence\b", re.I), "the video"),
    (re.compile(r"\b(?:this|the) (?:grid|contact sheet|collage)\b", re.I), "the video"),
]


def deframe(text: str) -> str:
    """Describe the video, not the sheet it was read from."""
    cleaned = text
    for pattern, replacement in _DEFRAME:
        cleaned = pattern.sub(replacement, cleaned)
    # Tidy the punctuation those substitutions can leave behind.
    cleaned = re.sub(r"[^\S\r\n]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.])", r"\1", cleaned)
    cleaned = re.sub(r"(^|\n)\s*,\s*", r"\1", cleaned)
    # Re-capitalise sentence starts. Several replacements above are lowercase
    # by necessity -- they usually land mid-sentence -- but when the phrase
    # they replaced began one, the result reads as a typo.
    cleaned = re.sub(r"(^|[.!?]\s+|\n)([a-z])",
                     lambda m: m.group(1) + m.group(2).upper(), cleaned)
    return cleaned.strip()


def _transcribe(path: Path) -> str:
    """What is said, from the audio itself.

    Local Whisper rather than the platform's captions: a reel usually has
    none, and this works the same on a clip with no caption track at all.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return ""
    try:
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(str(path), beam_size=1, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()
    except Exception:  # noqa: BLE001 -- a silent clip is not a failure
        logger.debug("Could not transcribe audio", exc_info=True)
        return ""


def _grab(url: str, folder: Path, fmt: str, name: str) -> Path | None:
    """One yt-dlp download. None when that format does not exist."""
    import yt_dlp
    from . import video

    options = {
        **video._ydl_options(),
        # video._ydl_options exists to fetch captions, so it carries
        # skip_download plus writesubtitles/writeautomaticsub. Inherited
        # wholesale, every "download" here wrote a .vtt and no media, and the
        # first thing to notice was PyAV reporting a subtitle stream where a
        # video track should be. Only the transport bits -- cookies, the JS
        # runtime, the silent logger -- are wanted; the caption behaviour has
        # to be turned off explicitly.
        "skip_download": False,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "format": fmt,
        "outtmpl": str(folder / f"{name}.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                return None
            # Select the extractor's completed output, never an arbitrary
            # larger sidecar or .part file left by a failed download.
            path = Path(ydl.prepare_filename(info))
            return path if path.is_file() and path.stat().st_size > 0 else None
    except Exception:  # noqa: BLE001 -- absent format, not a failure worth raising
        return None


def _download(url: str) -> tuple[Path, Path | None, Path]:
    """The clip, as (video file, audio file or None, temp folder).

    Two files rather than one, because muxing is not available and is not
    needed. Nothing here plays the video: frames come out of a video stream
    and speech comes out of an audio stream, and reading each separately skips
    the merge step entirely.

    That matters because progressive formats are disappearing. Checked against
    YouTube while building this: of twelve formats carrying video, zero also
    carried audio -- so "give me one file with both" is a request that now
    fails outright there. Instagram still serves progressive, so the single
    file is tried first and covers reels in one download.
    """
    folder = Path(tempfile.mkdtemp(prefix="nova-watch-"))

    combined = _grab(url, folder, "best[vcodec!=none][acodec!=none][height<=720]"
                                  "/best[vcodec!=none][acodec!=none]", "clip")
    if combined is not None:
        return combined, combined, folder

    picture = _grab(url, folder, "bestvideo[height<=720]/bestvideo/best[vcodec!=none]", "video")
    if picture is None:
        shutil.rmtree(folder, ignore_errors=True)
        raise WatchError("I couldn't get a video stream from that link.")
    sound = _grab(url, folder, "bestaudio/best[acodec!=none]", "audio")
    return picture, sound, folder


def watch_prompt(spoken: str) -> str:
    """What the vision model is asked, given what was heard.

    Two things here were learned by getting a wrong answer. The first draft
    asked what was "being demonstrated -- the steps, the technique", and on a
    clip of someone talking to camera at a zoo the model duly invented a
    step-by-step demonstration of imitating a gorilla's walk. A question that
    presupposes a technique will be answered with one. So the prompt now
    asks what is happening and says outright that the answer may be "nothing
    is being taught".

    The second is that the transcript belongs here. Nova had it -- Whisper
    runs before this -- and was keeping it for the classifier afterwards,
    leaving the vision model to guess at intent from nine small tiles. The
    words are the cheapest possible grounding for the pictures, and withholding
    them was just an ordering mistake.
    """
    heard = (spoken or "").strip()
    audio_part = (
        f"\n\nWhat the person says, transcribed from the audio:\n\"{heard[:1200]}\"\n"
        "Use this to understand the frames. If the words and the pictures disagree, "
        "say so rather than inventing something that reconciles them."
        if heard else
        "\n\nThere is no audible speech in this clip."
    )
    return (
        "These are frames from one short video, in time order, numbered 1 upward. "
        "Describe what is actually happening in it: who or what is on screen, what "
        "they are doing, and any text visible in the frames."
        + audio_part +
        "\n\nIf the video teaches or demonstrates something, say what and how. If it "
        "does not -- if it is someone talking, or a scene, or a joke -- say that "
        "plainly. Do not invent steps or a technique that is not there.\n\n"
        "Write about the video as a video. Never mention frames, tiles, shots, a "
        "grid, images, or how many of them you were given -- the person reading "
        "this watched a clip, not a contact sheet."
    )


async def watch(url: str) -> dict:
    """Watch a clip: frames, audio, and a judgement about what to ask next."""
    folder = None
    try:
        picture, sound, folder = await asyncio.to_thread(_download, url)
        frames, duration = await asyncio.to_thread(_sample_frames, picture)
        sheet = await asyncio.to_thread(_contact_sheet, frames)
        spoken = await asyncio.to_thread(_transcribe, sound) if sound else ""
    except WatchError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise WatchError(f"Couldn't watch that clip: {str(exc).splitlines()[0][:200]}") from exc
    finally:
        if folder and folder.exists():
            shutil.rmtree(folder, ignore_errors=True)

    return {
        "ok": True,
        "url": url,
        "duration_seconds": round(duration, 1),
        "frames": len(frames),
        "spoken": spoken,
        # Handed back rather than described, so the caller can put it in front
        # of a vision model as a real image.
        "_sheet_png": sheet,
        # Built after the transcript exists, so the pictures arrive with the
        # words that explain them.
        "prompt": watch_prompt(spoken),
    }


# --- what to ask afterwards -------------------------------------------------

# The categories the follow-up question branches on. Deliberately about the
# *shape* of the content rather than its topic: "is this a thing to do, a
# thing to make, or a thing to understand" is what decides a good question,
# and it generalises past whatever subjects the user happens to watch.
KINDS = {
    "technique": "demonstrates a method or skill to practise or copy",
    "recipe": "a set of steps producing a specific result, food or otherwise",
    "idea": "makes an argument or explains a concept, with nothing to physically do",
    "reference": "shows a design, layout, style or example worth imitating",
    "entertainment": "meant to be enjoyed, with nothing to apply",
}

FOLLOW_UPS = {
    "technique": "Do you want to try this yourself, or should I break it into steps you can follow?",
    "recipe": "Want me to write this out as steps and a list, or save it for later?",
    "idea": "Is this something you want applied to a project, or thought through further?",
    "reference": "Should I pull out what makes this work, or find where it fits something you're building?",
    "entertainment": "Anything in this you want me to do something with?",
}


async def suggest_follow_up(description: str, spoken: str) -> dict:
    """What to ask the user, now that Nova knows what it watched.

    Jev rather than another model call, because this is a typed judgement and
    not a conversation: one round trip returns a category and a confidence
    Nova can branch on in code. A chat model asked the same thing returns a
    paragraph that has to be parsed back into a decision.

    The confidence floor matters more than the category. Below it the honest
    move is the open question -- a specific follow-up aimed at the wrong kind
    of content is worse than a general one, because it tells the user Nova
    misunderstood the video.
    """
    document = f"What the video shows:\n{description}\n\nWhat is said:\n{spoken or '(nothing audible)'}"
    if not typesafe.configured():
        return {"kind": None, "confidence": 0.0,
                "question": "How do you want to use this?"}
    try:
        kind, confidence = await typesafe.choose(
            document,
            "Classify what kind of short video this is, by what a viewer could do with it.",
            KINDS,
        )
    except Exception:  # noqa: BLE001 -- never let the judgement break the answer
        logger.debug("Jev classification failed", exc_info=True)
        return {"kind": None, "confidence": 0.0,
                "question": "How do you want to use this?"}

    # Same floor the message classifier uses, and for the same reason: below
    # it the distribution is spread and the category is a guess.
    if confidence < classifier.CONFIDENCE_FLOOR:
        return {"kind": kind, "confidence": confidence,
                "question": "How do you want to use this?"}
    return {"kind": kind, "confidence": confidence, "question": FOLLOW_UPS[kind]}
