"""Modular skill system (task: "a real skills system... with a relevance-
detection mechanism that loads the right skill into context per-request,
not one static system prompt").

One file per skill/domain under skills/*.md, each a small YAML-ish-header +
body file (name/description/keywords, then the instructions themselves --
same shape as Claude Code's own SKILL.md convention this app is modeled
after). Relevance is keyword-matched against the user's message, not a
second LLM call -- same heuristic-first philosophy as classifier.py (see
that module's docstring for the rationale: classification/selection has to
happen *before* the real completion call, so it can't cost one itself).
Matched skills get folded into base_messages as extra system messages (see
main.py's chat()), on top of the persona/self-awareness prompts that are
still always present -- this supplements the static prompt with
domain-specific instructions only when they're actually relevant, rather
than trying to cram every domain's guidance into one prompt every request.
"""
from __future__ import annotations

import re
import json
import logging
import yaml
from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent / "skills"


@dataclass
class Skill:
    name: str
    description: str
    keywords: list[str]
    body: str
    # Task 8 (route a matched skill to the model best suited for its domain,
    # not just whatever the general category router would have picked):
    # optional per-skill model override, same id shape routing.py already
    # accepts for an explicit override (e.g. "ollama:qwen2.5:0.5b",
    # "openrouter:some/model"). None means "no opinion, defer to normal
    # category routing" -- most skills should leave this unset.
    preferred_model_id: str | None = None


def _parse_skill_file(path: Path) -> Skill | None:
    if path.stat().st_size > 40000:
        raise ValueError("Skill file exceeds 40 KB")
    text = path.read_text(encoding="utf-8-sig")
    if not text.startswith("---"):
        return None
    sections = re.split(r"(?m)^---\s*$", text, maxsplit=2)
    if len(sections) != 3:
        return None
    fields = yaml.safe_load(sections[1])
    if not isinstance(fields, dict):
        raise ValueError("Skill header must be a mapping")
    body = sections[2].strip()
    name = fields.get("name", path.stem)
    description = fields.get("description", "")
    keywords = fields.get("keywords", [])
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(',') if k.strip()]
    preferred_model_id = fields.get("preferred_model_id") or None
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name) or not isinstance(description, str):
        raise ValueError("Invalid skill name or description")
    if not isinstance(keywords, list) or any(not isinstance(k, str) or not k.strip() or len(k) > 100 for k in keywords):
        raise ValueError("Skill keywords must be short, nonempty strings")
    if not body or len(body) > 16000 or len(keywords) > 40 or (preferred_model_id is not None and not isinstance(preferred_model_id, str)):
        raise ValueError("Invalid skill body, keywords, or preferred model")
    return Skill(
        name=name,
        description=description,
        keywords=keywords,
        body=body,
        preferred_model_id=preferred_model_id,
    )


def load_skills() -> list[Skill]:
    if not SKILLS_DIR.exists():
        return []
    skills = []
    for path in sorted(SKILLS_DIR.glob("*.md")):
        try:
            skill = _parse_skill_file(path)
        except (OSError, ValueError, yaml.YAMLError):
            logging.getLogger(__name__).warning("Skipped invalid skill file: %s", path.name)
            continue
        if skill:
            skills.append(skill)
    return skills


# Loaded once per process, like classifier.py's compiled regexes -- skill
# files are static app assets, not something that changes at runtime.
_skills_cache: list[Skill] | None = None


def all_skills() -> list[Skill]:
    global _skills_cache
    if _skills_cache is None:
        _skills_cache = load_skills()
    return _skills_cache


def reload_skills() -> list[Skill]:
    """Drops the cache and reloads from disk -- called after create_skill()
    so a newly-added skill (task: real "Add Skill" flow in Settings) is
    matchable on the very next message, not just after a backend restart."""
    global _skills_cache
    _skills_cache = load_skills()
    return _skills_cache


_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def create_skill(
    name: str,
    description: str,
    keywords: list[str],
    body: str,
    preferred_model_id: str | None = None,
) -> Skill:
    """Writes a new skills/<name>.md in the same header+body shape
    _parse_skill_file reads, then reloads the cache. Raises ValueError on a
    bad/duplicate name rather than silently overwriting another skill's
    file -- the Settings UI surfaces this as a real error, not a no-op."""
    slug = name.strip().lower().replace(" ", "-")
    if not _NAME_RE.match(slug):
        raise ValueError(
            "Skill name must be lowercase letters, numbers, and hyphens only (e.g. 'sql-queries')."
        )
    if not body.strip() or len(body) > 16000 or len(description) > 1000 or len(keywords) > 40:
        raise ValueError("Skill needs a body (up to 16,000 characters), a short description and at most 40 keywords.")
    if any(not k.strip() or len(k) > 100 for k in keywords):
        raise ValueError("Keywords must contain 1–100 characters.")
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    path = SKILLS_DIR / f"{slug}.md"
    if path.exists():
        raise ValueError(f"A skill named '{slug}' already exists.")
    header_lines = [
        "---",
        f"name: {slug}",
        f"description: {json.dumps(description.strip())}",
        f"keywords: {json.dumps([k.strip() for k in keywords])}",
    ]
    if preferred_model_id:
        header_lines.append(f"preferred_model_id: {json.dumps(preferred_model_id.strip())}")
    header_lines.append("---")
    with path.open('x', encoding='utf-8') as target:
        target.write("\n".join(header_lines) + "\n\n" + body.strip() + "\n")
    reload_skills()
    return _parse_skill_file(path)


def delete_skill(name: str) -> bool:
    slug = name.strip().lower()
    if not _NAME_RE.fullmatch(slug):
        raise ValueError("Invalid skill name")
    path = SKILLS_DIR / f"{slug}.md"
    if not path.exists():
        return False
    path.unlink()
    reload_skills()
    return True


# Total skill body text folded into one request's system prompt. Ranking alone
# is not enough of a bound: skills vary from ~1.5KB to ~12KB, so "the three
# best matches" can mean 1.5KB or 36KB depending on which three. Measured, the
# three largest came to ~5.9k tokens on top of a ~4.3k tool-and-persona floor.
# This caps the variable part so the budget is predictable regardless of which
# skills a message happens to hit.
SKILL_CONTEXT_BUDGET_CHARS = 14_000


def writing_needs_tools(message: str) -> bool:
    return bool(re.search(r'\b(essay|paper|research|sources?|citations?|canvas|assignment|coursework|browser|submit|file|save|download)\b', message, re.I))


def select_relevant_skills(message: str, max_skills: int = 3) -> list[Skill]:
    """A skill matches if any of its keywords appear in the message as a whole
    word (case-insensitive). Returns at most max_skills, best match first --
    capped so an unrelated skill's instructions don't dilute the system prompt
    on every request; most requests match zero skills and get exactly the same
    base prompt as before this existed.

    Ranking is by the total *length* of the matched keywords, not the count of
    them. Counting treats "essay" and "scholarship essay" as equally strong
    evidence, so "help with my scholarship essay" scored 1 for three different
    skills and the tie fell to whichever happened to load first -- which was
    not the scholarship skill. Length is a good proxy for specificity: a
    multi-word phrase is a deliberate signal, a common single word is not.
    """
    text = message.lower()
    scored: list[tuple[int, int, Skill]] = []
    for skill in all_skills():
        matched = [
            kw for kw in skill.keywords
            if re.search(rf"(?<!\w){re.escape(kw.lower())}(?!\w)", text)
        ]
        if matched:
            scored.append((sum(len(kw) for kw in matched), len(matched), skill))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)

    # Take in rank order until the budget is spent. The best match is always
    # included even if it alone exceeds the budget -- a single large skill is
    # exactly the case where the user asked for that specialism, and dropping
    # it would leave the request with no guidance at all.
    chosen: list[Skill] = []
    spent = 0
    for _, _, skill in scored[:max_skills]:
        size = len(skill.body)
        if chosen and spent + size > SKILL_CONTEXT_BUDGET_CHARS:
            continue
        chosen.append(skill)
        spent += size
    return chosen
