"""Task classifier.

Per the build spec: "The task classifier (small/cheap model or heuristics to
start) determines category before routing — get this working end to end in
Phase 1, even in rough form." This is the heuristic version: fast, free,
regex/keyword based, no extra LLM call in the hot path (which also keeps us
honest on the spec's cost-control principles). It can be swapped for a
small-model classifier later without touching routing.py.

Categories mirror the routing table in the build spec exactly.
"""
from __future__ import annotations

import re

CATEGORIES = (
    "coding",
    "frontend_ui_code",
    "reasoning_math",
    "agentic_planning",
    "multilingual",
    "long_context",
    "quick_simple",
    "vision_multimodal",
    "design_review",
    "image_generation",
    "general_writing",
)

_IMAGE_GEN_RE = re.compile(
    r"\b(generate|create|draw|make|render)\b.{0,30}\b(image|picture|logo|icon|illustration|mockup|graphic|artwork|photo)\b",
    re.IGNORECASE,
)

_DESIGN_REVIEW_RE = re.compile(
    r"\b(review|feedback on|critique|thoughts on)\b.{0,30}\b(screenshot|design|mockup|ui|layout|wireframe)\b"
    r"|attached (a |this )?(screenshot|design|image)",
    re.IGNORECASE,
)

_VISION_RE = re.compile(
    r"\b(this image|this screenshot|this photo|in the picture|what.?s in this image)\b",
    re.IGNORECASE,
)

_FRONTEND_RE = re.compile(
    r"\b(css|html|tailwind|react component|vue|svelte|jsx|tsx|frontend|front-end|"
    r"ui component|button styling|responsive layout|webpage layout|flexbox|grid layout|"
    r"landing page|dom|stylesheet)\b",
    re.IGNORECASE,
)

_CODING_RE = re.compile(
    r"\b(function|class |def |import |bug|debug|stack trace|traceback|refactor|"
    r"write (a|an|some) (script|program|function|code|class|test)|code review|"
    r"unit test|api endpoint|regex|compile|exception|null pointer|segfault|"
    r"pull request|git |sql query|algorithm implementation|python|javascript|typescript|"
    r"golang|\bC\+\+\b|rust\b|syntax error)\b",
    re.IGNORECASE,
)

_MATH_RE = re.compile(
    r"\b(calculus|algebra|geometry|trigonometry|solve|prove|proof|theorem|equation|integral|derivative|probability|"
    r"algorithm complexity|big-o|calculate|optimi[sz]e the|logic puzzle|"
    r"reasoning problem|knewton|alta)\b|[0-9]\s*[\+\-\*/\^=]\s*[0-9]",
    re.IGNORECASE,
)

_AGENTIC_RE = re.compile(
    r"\b(step[- ]by[- ]step plan|multi-step|workflow|automate|agentic|"
    r"plan out|break (this|it) down into steps|orchestrate|tool.?use|"
    r"chain of tasks|homework|assignment|quiz|canvas|flvs|flvs\.net|blackboard|brightspace|moodle|d2l|coursework|do all|review center|exam review)\b",
    re.IGNORECASE,
)


_MULTILINGUAL_RE = re.compile(r"\b(translate|in spanish|in french|in german|in japanese|in mandarin|in korean)\b", re.IGNORECASE)

# CJK, Cyrillic, Arabic, Devanagari ranges — a cheap signal the input itself
# isn't plain English, independent of keyword matches above.
_NON_LATIN_RE = re.compile(
    r"[一-鿿぀-ヿ가-힯Ѐ-ӿ؀-ۿऀ-ॿ]"
)

_LONG_CONTEXT_CHARS = 6000
_QUICK_MAX_CHARS = 80
_QUICK_RE = re.compile(r"^\s*(what|who|when|where|define|is |are |does |do (you|we|they|i)\b)", re.IGNORECASE)


def classify(message: str, has_image_attachment: bool = False) -> str:
    """Return one of CATEGORIES for the given user message."""
    text = message.strip()

    if has_image_attachment:
        return "design_review" if _DESIGN_REVIEW_RE.search(text) else "vision_multimodal"
    if _VISION_RE.search(text):
        return "vision_multimodal"
    if _DESIGN_REVIEW_RE.search(text):
        return "design_review"
    if _IMAGE_GEN_RE.search(text):
        return "image_generation"

    if _CODING_RE.search(text):
        return "frontend_ui_code" if _FRONTEND_RE.search(text) else "coding"
    if _FRONTEND_RE.search(text):
        return "frontend_ui_code"

    if _AGENTIC_RE.search(text):
        return "agentic_planning"
    if _MATH_RE.search(text):
        return "reasoning_math"
    if _MULTILINGUAL_RE.search(text) or _NON_LATIN_RE.search(text):
        return "multilingual"
    if len(text) >= _LONG_CONTEXT_CHARS:
        return "long_context"
    if len(text) <= _QUICK_MAX_CHARS and _QUICK_RE.match(text):
        return "quick_simple"

    return "general_writing"


# --- Jev-backed classification (see typesafe.py) ----------------------------
#
# This module's own docstring anticipated it: "It can be swapped for a
# small-model classifier later without touching routing.py." Choosing one of
# eleven categories is exactly the shape TypeSafe's `choice` primitive answers,
# and it is a decision the regexes above get wrong in predictable ways -- "can
# you make this faster" is coding, "make this look faster" is not, and no
# keyword list separates them.
#
# Two properties make this safe to put in the hot path of every message. It is
# one round trip, and confidence is a real gate: TypeSafe reports how
# concentrated the distribution is, so a hedged answer can be discarded in
# favour of the heuristic rather than acted on. Absent a key, unreachable, slow,
# or unsure, the behaviour is exactly what it was before.

CLASSIFIER_CRITERIA = {
    "coding": "Writing, changing, debugging or explaining code that is not primarily about visual appearance",
    "frontend_ui_code": "Building or changing user interface code — components, layout, styling, CSS",
    "reasoning_math": "Mathematics, logic puzzles, proofs, or multi-step quantitative reasoning",
    "agentic_planning": "Planning or carrying out a multi-step task, using tools, or operating the computer",
    "multilingual": "Written in, or asking about, a language other than English",
    "long_context": "Supplying a large body of text to be read, summarised or analysed",
    "quick_simple": "A short factual question or greeting answerable in a sentence",
    "vision_multimodal": "Asking about the content of an attached image, screenshot or photo",
    "design_review": "Asking for critique or feedback on a design, mockup or interface",
    "image_generation": "Asking for an image, logo, illustration or other picture to be created",
    "general_writing": "Writing or editing prose — essays, emails, posts, documents",
}

# Below this, the distribution is spread across several categories and the
# answer is a guess. The heuristic's guess is at least a predictable one.
CONFIDENCE_FLOOR = 0.35


async def classify_async(message: str) -> str:
    """The category for a message, asking Jev when it is configured.

    Falls back to classify() -- never raises, and never blocks a reply on a
    third-party service being up.
    """
    text = (message or "").strip()
    if not text:
        return classify(message)

    from . import typesafe

    if not typesafe.configured():
        return classify(message)
    try:
        chosen, confidence = await typesafe.choose(
            text[:8000],
            "Which category best describes what this message is asking for",
            CLASSIFIER_CRITERIA,
        )
    except Exception:  # noqa: BLE001 - classification must never break a reply
        return classify(message)
    if confidence < CONFIDENCE_FLOOR or chosen not in CATEGORIES:
        return classify(message)
    return chosen
