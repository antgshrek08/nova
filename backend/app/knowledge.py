"""What Nova learns from a conversation, as opposed to what was said in it.

The memory graph already gained nodes after every chat -- one per message.
That is a transcript, not knowledge: a thousand nodes called "New
conversation" tell you nothing, and nothing in the graph got better as Nova
talked to you more. This module is the layer that actually accumulates.

After each exchange, a small local model reads the last user message and
Nova's reply and returns the durable statements worth keeping -- "The user is
taking BIO 101 this semester", not "The user said hi". Those become rows in
the `knowledge` table and, from there, first-class nodes in the memory graph
(see graph.py's _knowledge_layer).

Three rules this module will not bend:

**Provenance decides status, not confidence.** memory.classify_fact_status
already establishes that an assistant statement is not automatically a fact
about the user, however fact-shaped it sounds. The same rule holds here: only
statements the *user* made are stored "confirmed". Everything traceable to
Nova's own reply stays "unconfirmed" forever unless the user later says it
themselves. A memory that quietly promotes the model's guesses into facts
about a person is worse than no memory.

**Local models only.** Extraction runs on every single chat, so anything
metered would turn talking to Nova into a bill that grows with use. If no
local model is available this does nothing at all and says so -- it never
falls back to a paid provider.

**Nothing blocks the reply.** Extraction happens after the response has been
streamed and is wrapped so a failure is logged and dropped. Nova failing to
learn something must never turn into Nova failing to answer.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from . import db, providers

logger = logging.getLogger(__name__)

# The local model used for extraction, in preference order. Small instruct
# models are enough -- this is structured extraction from a short window, not
# reasoning -- and a small model keeps a per-chat job cheap in wall time.
_PREFERRED_MODELS = ("qwen3.5:4b", "qwen2.5:3b", "llama3.2:3b")

# Skip extraction on trivial exchanges. "thanks", "ok", "do that" carry
# nothing durable, and asking a model about them is pure cost.
MIN_USER_CHARS = 24

# A hard ceiling on what one exchange may contribute. Without it a long
# rambling message can produce twenty low-value statements and bury the graph
# in a single turn.
MAX_PER_EXCHANGE = 5

# Cap the text handed to the model. Extraction quality does not improve past
# this, and a 40k-character code dump would just be slow.
MAX_CHARS = 4000

_PROMPT = """You extract durable knowledge from a conversation for a personal assistant's long-term memory.

Return ONLY a JSON object: {"facts": [...]}. Each fact is:
  {"subject": "<2-4 words naming what this is about>",
   "statement": "<one standalone sentence>",
   "category": "person|preference|project|schedule|skill|tool|fact",
   "from": "user|assistant"}

Rules:
- Keep only what is still true and worth remembering weeks from now.
- Each statement must name what it is about, in full, and make sense read on
  its own months later with no other context. Never begin a statement with
  It, They, He, She, This, That or These, and never rely on the subject field
  to supply the noun.
  BAD:  {"subject": "BIO 101", "statement": "It meets every weekday at 8am."}
  GOOD: {"subject": "BIO 101", "statement": "BIO 101 meets every weekday at 8am."}
- "from" is "user" ONLY if the USER asserted it about themselves or their world.
  Anything the assistant claimed, suggested, explained or looked up is "assistant".
- Do NOT record: greetings, requests, questions, the assistant's offers,
  chit-chat, general knowledge anyone could look up, or what was done in this
  chat.
- If nothing is worth keeping, return {"facts": []}. That is a good answer and
  it is the most common one. Do not invent facts to fill the list.

USER SAID:
{user}

ASSISTANT REPLIED:
{assistant}"""


def fingerprint(statement: str) -> str:
    """Normalized form used to recognise a statement already known.

    Deliberately crude -- lowercase, strip punctuation, collapse whitespace.
    It catches the exact and near-exact repeats that a per-chat extractor
    actually produces. Genuine paraphrases will slip through and create a
    second node, which is the acceptable failure: a duplicate is visible and
    removable, whereas over-eager merging silently loses a distinct fact.
    """
    cleaned = re.sub(r"[^\w\s]", "", (statement or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


async def available_model() -> str | None:
    """The local model extraction will use, or None if there isn't one."""
    try:
        local = await providers.get_local_ollama_models()
    except Exception:  # noqa: BLE001 -- Ollama not running is not an error here
        return None
    installed = {model.id for model in local}
    for name in _PREFERRED_MODELS:
        if name in installed:
            return name
    # Any local model is better than no learning at all, but only as a
    # fallback -- the preferred list is ordered for a reason.
    return next(iter(sorted(installed)), None)


def _parse(raw: str) -> list[dict]:
    """Pull the facts array out of a model response, tolerantly."""
    text = (raw or "").strip()
    if not text:
        return []
    # json_mode should give a bare object, but small models still wrap output
    # in prose or a code fence often enough to be worth handling.
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    facts = payload.get("facts")
    return facts if isinstance(facts, list) else []


def _clean(fact: dict, source_default: str = "assistant") -> dict | None:
    """Validate one extracted fact, or None to drop it."""
    if not isinstance(fact, dict):
        return None
    statement = str(fact.get("statement") or "").strip()
    subject = str(fact.get("subject") or "").strip()
    if len(statement) < 8 or not subject:
        return None
    if len(statement) > 400 or len(subject) > 80:
        return None

    # A statement opening with a bare pronoun is not standalone -- read back
    # in three months, "It meets every weekday at 8am" names nothing. The
    # prompt asks for this and a small model still slips; dropping the row is
    # better than storing memory that cannot be understood later.
    if re.match(r"^(it|they|he|she|this|that|these|those)\b", statement, re.IGNORECASE):
        return None

    role = str(fact.get("from") or source_default).lower()
    role = "user" if role == "user" else "assistant"
    category = str(fact.get("category") or "fact").lower()
    if category not in {"person", "preference", "project", "schedule", "skill", "tool", "fact"}:
        category = "fact"

    return {
        "subject": subject,
        "statement": statement,
        "category": category,
        "source_role": role,
        # The one place provenance becomes status. See the module docstring:
        # the model does not get a vote on whether its own output is a fact.
        "status": "confirmed" if role == "user" else "unconfirmed",
        "fingerprint": fingerprint(statement),
    }


async def extract(user_text: str, assistant_text: str) -> list[dict]:
    """Candidate facts from one exchange. Never raises; [] means 'nothing'."""
    if len((user_text or "").strip()) < MIN_USER_CHARS:
        return []
    model = await available_model()
    if not model:
        return []

    prompt = (
        _PROMPT
        .replace("{user}", (user_text or "")[:MAX_CHARS])
        .replace("{assistant}", (assistant_text or "")[:MAX_CHARS])
    )
    chunks: list[str] = []
    try:
        async for chunk in providers.stream_ollama(
            model, [{"role": "user", "content": prompt}], json_mode=True
        ):
            chunks.append(chunk)
    except Exception:  # noqa: BLE001
        logger.debug("Knowledge extraction failed", exc_info=True)
        return []

    seen: set[str] = set()
    facts: list[dict] = []
    for raw in _parse("".join(chunks)):
        cleaned = _clean(raw)
        if not cleaned or cleaned["fingerprint"] in seen:
            continue
        seen.add(cleaned["fingerprint"])
        facts.append(cleaned)
        if len(facts) >= MAX_PER_EXCHANGE:
            break
    return facts


async def learn_from_exchange(
    conversation_id: int,
    message_id: int | None,
    user_text: str,
    assistant_text: str,
) -> list[dict]:
    """Extract and store. Returns the rows written or refreshed."""
    facts = await extract(user_text, assistant_text)
    stored = []
    for fact in facts:
        try:
            stored.append(await db.upsert_knowledge({
                **fact,
                "conversation_id": conversation_id,
                "message_id": message_id,
            }))
        except Exception:  # noqa: BLE001
            logger.debug("Could not store knowledge row", exc_info=True)
    if stored:
        logger.info("Learned %d statement(s) from conversation %s", len(stored), conversation_id)
    return stored


def learn_in_background(
    conversation_id: int,
    message_id: int | None,
    user_text: str,
    assistant_text: str,
) -> None:
    """Fire-and-forget. The reply has already been streamed by this point and
    must not be held up, or failed, by anything that happens here."""
    async def _run():
        try:
            await learn_from_exchange(conversation_id, message_id, user_text, assistant_text)
        except Exception:  # noqa: BLE001
            logger.debug("Background knowledge extraction failed", exc_info=True)

    task = asyncio.create_task(_run())
    # Hold a reference so the task is not garbage collected mid-flight, and
    # drop it once done -- asyncio only keeps weak references to running tasks.
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)


_PENDING: set[asyncio.Task] = set()


async def status() -> dict:
    """What Settings and the graph need to explain the state of learning."""
    model = await available_model()
    return {
        "model": model,
        "available": bool(model),
        "count": await db.count_knowledge(),
        "reason": None if model else (
            "No local Ollama model is installed, so Nova is not learning from chats. "
            "Extraction runs on every message and is deliberately local-only, so it "
            "never falls back to a paid provider."
        ),
    }
