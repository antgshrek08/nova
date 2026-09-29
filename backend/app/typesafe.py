"""TypeSafe (Jev) — typed judgments with probabilities, for decisions in code.

Not a chat model and not a substitute for one. Jev evaluates a document against
typed questions and returns structured answers your code branches on:

  * choice — pick one option, with a probability per option and a confidence
  * score  — position on an ordered rubric, with a confidence
  * noul   — a single yes/no probability in 0..1

Every question in a call is evaluated in parallel against the same document in
one round trip, so asking five things costs one request rather than five.

Where this belongs in Nova is anywhere the code currently needs a judgement and
has to either guess with a regex or spend a full model call to get one word
back. Classification is the obvious first one; escalation and triage are the
same shape.

The API key lives in the same ~/.ai-council/.env as every other key. Absent, the
module reports itself unconfigured and callers fall back to what they did
before -- this is an improvement to a decision, never a dependency of it.
"""
from __future__ import annotations

import os

import httpx
from dotenv import set_key

from . import config

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "speed_latest"
TIMEOUT = 20


class TypeSafeError(RuntimeError):
    """Configuration or API failure, phrased for display."""


def api_key() -> str | None:
    return os.getenv("TYPESAFE_API_KEY", "").strip() or None


def configured() -> bool:
    return bool(api_key())


def status() -> dict:
    return {"configured": configured(), "model": DEFAULT_MODEL, "endpoint": API_URL}


def update_credentials(key: str | None) -> dict:
    if key is not None:
        cleaned = key.strip()
        set_key(str(config.ENV_PATH), "TYPESAFE_API_KEY", cleaned)
        os.environ["TYPESAFE_API_KEY"] = cleaned
    return status()


async def system_one(document: str, questions: dict, *, model: str = DEFAULT_MODEL,
                     timeout: float = TIMEOUT) -> dict:
    """One call, any mix of choice/score/noul questions, evaluated in parallel.

    `questions` is {name: {"type": ..., "instructions": ..., "criteria": ...}}
    exactly as the API expects it; this deliberately does not wrap the schema in
    a second vocabulary of its own.
    """
    key = api_key()
    if not key:
        raise TypeSafeError("TypeSafe isn't set up. Add a key in Settings > Models.")
    if not questions:
        raise TypeSafeError("At least one question is required.")

    payload = {"document": document, "model": model, "questions": questions}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                API_URL, json=payload,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise TypeSafeError(f"Couldn't reach TypeSafe: {exc}") from exc

    if response.status_code == 401:
        raise TypeSafeError("TypeSafe rejected the API key (401). Check it in Settings > Models.")
    if response.status_code == 429:
        raise TypeSafeError("TypeSafe is rate-limiting this key (429).")
    if response.status_code >= 400:
        raise TypeSafeError(f"TypeSafe returned HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError as exc:
        raise TypeSafeError("TypeSafe returned a response that wasn't JSON.") from exc


async def choose(document: str, instructions: str, criteria: dict[str, str],
                 *, model: str = DEFAULT_MODEL, timeout: float = TIMEOUT) -> tuple[str, float]:
    """One choice question, reduced to (chosen option, confidence).

    Confidence is how concentrated the distribution is, not how correct the
    answer is -- so it is usable as a gate ("decide in code below this") and not
    as a quality score.
    """
    data = await system_one(document, {
        "answer": {"type": "choice", "instructions": instructions, "criteria": criteria},
    }, model=model, timeout=timeout)
    answer = (data.get("answers") or {}).get("answer") or {}
    chosen = answer.get("choice")
    if chosen not in criteria:
        raise TypeSafeError(f"TypeSafe returned an option that wasn't offered: {chosen!r}")
    return chosen, float(answer.get("confidence") or 0.0)


async def is_true(document: str, instructions: str, *, model: str = DEFAULT_MODEL,
                  timeout: float = TIMEOUT) -> float:
    """One noul question, reduced to its 0..1 probability."""
    data = await system_one(document, {
        "answer": {"type": "noul", "instructions": instructions},
    }, model=model, timeout=timeout)
    answer = (data.get("answers") or {}).get("answer") or {}
    return float(answer.get("noul") or 0.0)
