"""Letting Nova actually look at an image.

Before this module, attaching a screenshot to a chat message did three things
and none of them was "look at it". The bytes were stored and shown back in the
bubble, the classifier correctly labelled the turn `vision_multimodal`, and
then `_format_attachment_for_model` replaced the image with the sentence
"[Attached file 'x.png' (image/png, 240000 bytes) -- not a text format,
contents not shown.]" and sent that to a text model.

What made it worse than a missing feature was where the request landed.
`vision_multimodal`'s routing chain is OpenRouter-only, routing strips every
OpenRouter step, and that category is explicitly excluded from the Gemini
fallback -- so the chain resolved to "unavailable" and the request fell
through to the blind local 4B. Measured on a screenshot of Nova's own chat
window, it invented a tool call (`read_media_file`, which does not exist) and
then answered "The screenshot you shared is showing a Roblox game screen."

A confident description of an image the model never received is the worst
outcome available here. It is indistinguishable from a real answer, and it is
the same failure as reporting five assignments due when the answer is twelve.
So this module does two jobs, and the second matters more than the first:
build a real multimodal message when a vision model is reachable, and make it
impossible for an image to reach a model that cannot see it.
"""
from __future__ import annotations

import base64

# Formats worth sending to a vision model. Deliberately a small allowlist
# rather than "anything image/*": SVG is markup a text model reads better as
# source, and TIFF/BMP are not reliably accepted by the vision endpoints.
SUPPORTED_IMAGE_TYPES = frozenset({
    "image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp",
})

# Roughly 7MB of raw bytes, which is about 9.5MB once base64 inflates it by
# a third. Past that the request body starts getting refused by providers,
# and a refusal here reads to the user as "Nova ignored my screenshot".
MAX_IMAGE_BYTES = 7_000_000

# Providers whose models can be given image content. `gemini` is the one that
# matters on this machine: it is configured, every current Gemini model reads
# images, and unlike the OpenRouter vision models it is not stripped out of
# every routing chain. The CLI providers are excluded on purpose -- they take
# a rendered prompt string, so a content-block list would be flattened into
# text and the image silently dropped, which is exactly the class of bug this
# module exists to prevent.
VISION_PROVIDERS = frozenset({"gemini", "openrouter", "custom"})

# Local models are opt-in by name. Ollama will happily accept an image for a
# model with no vision tower and answer from the text alone, which is how the
# original bug produced a Roblox screen out of a screenshot of Nova.
_LOCAL_VISION_MARKERS = ("-vl", "vl-", "llava", "vision", "moondream", "minicpm-v", "gemma3", "qwen3.5:")

# Exceptions to the markers above, checked first. Gemma 3 is a family, not a
# model: 4b, 12b and 27b carry a vision tower and 1b does not. Matching on
# "gemma3" alone therefore declared gemma3:1b sighted, handed it an image, and
# got back a confident description of something that was never in the picture
# -- which is the one failure this module exists to prevent, reintroduced by
# the check meant to prevent it. Anything genuinely blind belongs here.
_LOCAL_BLIND_MARKERS = ("gemma3:1b", "gemma3-1b")


def is_image(record: dict) -> bool:
    """Is this attachment something a vision model could read?"""
    content_type = (record.get("content_type") or "").lower().split(";")[0].strip()
    return content_type in SUPPORTED_IMAGE_TYPES


def usable_images(records: list[dict]) -> list[dict]:
    """Image attachments small enough to send."""
    return [r for r in records if is_image(r) and len(r.get("data") or b"") <= MAX_IMAGE_BYTES]


def oversized_images(records: list[dict]) -> list[dict]:
    return [r for r in records if is_image(r) and len(r.get("data") or b"") > MAX_IMAGE_BYTES]


def provider_can_see(provider: str, model: str | None) -> bool:
    """Whether a resolved route can be given image content.

    Conservative by construction: anything not positively known to read
    images is treated as blind. Being wrong in that direction costs a reroute;
    being wrong the other way costs a fabricated answer.
    """
    if provider == "ollama":
        name = (model or "").lower()
        if any(marker in name for marker in _LOCAL_BLIND_MARKERS):
            return False
        return any(marker in name for marker in _LOCAL_VISION_MARKERS)
    return provider in VISION_PROVIDERS


def as_data_uri(record: dict) -> str:
    content_type = (record.get("content_type") or "image/png").lower().split(";")[0].strip()
    encoded = base64.b64encode(record["data"]).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def has_images(messages: list[dict]) -> bool:
    return any(isinstance(m.get('content'), list) and
               any(b.get('type') == 'image_url' for b in m['content'])
               for m in messages)


def image_tools_supported(provider: str, model: str | None) -> bool:
    """Keep screenshot actions enabled only on known compatible local models.

    The installed Qwen 3.5 Ollama model advertises both vision and tools via
    /api/show. Gemma 3 and other older vision families reject tool schemas.
    """
    return provider != 'ollama' or (model or '').lower().startswith('qwen3.5:')


def build_content(text: str, images: list[dict]) -> list[dict]:
    """The user turn as multimodal content blocks.

    Text first, then the images. Order matters more than it looks: the
    question is what the model should be holding in mind while it looks, and
    several providers weight the trailing content most heavily -- putting the
    images last is what makes "what is the error in this screenshot?" read as
    a question about the screenshot rather than a caption request.
    """
    blocks: list[dict] = [{"type": "text", "text": text}]
    for record in images:
        blocks.append({"type": "image_url", "image_url": {"url": as_data_uri(record)}})
    return blocks


def describe_for_text_model(record: dict) -> str:
    """What a text model is told about an image it cannot be shown.

    Only reached when no vision route was available. It names the limitation
    instead of describing the file, because the previous wording ("contents
    not shown") read to the model as an invitation to guess at them.
    """
    return (
        f"[The user attached an image, '{record['filename']}'. You cannot see it -- "
        "no image-capable model was available for this turn. Say so plainly and do "
        "not describe, guess at, or speculate about its contents.]"
    )
