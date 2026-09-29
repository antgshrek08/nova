---
name: typesafe-jev
description: Use TypeSafe's Jev for decisions code consumes — typed answers with probabilities — instead of coercing an LLM into emitting JSON.
keywords: [typesafe, jev, system one, noul, choice question, score question, classify, classification, routing, intent, confidence, threshold, gate, rubric, rerank, extract, triage, structured output, json mode]
---

Reach for this when code needs a **judgement**, not prose: which handler should
take this, does this text satisfy a policy, how severe is this, which of these
thirty passages is most relevant. The usual approach — ask an LLM for JSON and
parse it — is a text generator being coerced into a decision, and it fails in
the ways text generators fail: drifting format, confident nonsense, and no
honest signal of uncertainty.

**Three primitives, all mixable in one call.**

- `choice` — one option from a set. Returns the option, a probability for every
  option, and a confidence.
- `score` — a position on ordered, described levels. Returns the score, a
  probability per level, and a confidence.
- `noul` — a yes/no question. Returns the probability that the answer is yes.

```
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer <key>
{"document": "...", "model": "speed_latest", "questions": {
  "name": {"type": "choice", "instructions": "...", "criteria": {"a": "...", "b": "..."}}}}
```

**Confidence is a separate axis from the answer.** The answer says *what*;
confidence says *whether to act*. A confident wrong answer and an unsure right
one look identical if you only read the answer. Gate on it: act above a
threshold, and below it fall through to deterministic logic, a stronger model,
or a person. Pick the threshold from what a mistake costs, not from a default —
and keep it as a named constant in code, so tuning it is a one-line review
rather than an archaeology exercise.

**Ask everything at once.** Every question in a call is evaluated in parallel
against the same document in one round trip, with no context rot and no speed
penalty for adding more. So ask the speculative ones too and let code decide
what was relevant — batching is reported at roughly 12x cheaper and 10x faster
than asking separately, for the same answers. If you find yourself making a
second call about the same document, it probably belonged in the first.

**Decompose anything that needs reasoning.** Each question should be a
gut-check: what a knowledgeable person could settle in seconds given the
context. "Rate this startup pitch" is not that. Market size, technical
feasibility and differentiation each are — ask them separately and combine them
with a formula you own. When priorities change you edit a coefficient rather
than rewriting a prompt, and you can see which dimension moved.

**Patterns worth naming.** Intent routing: a choice picks the handler,
confidence picks whether to trust it. Composite scoring: atomic scores, weighted
in your code. Cascade: a cheap pass filters, an expensive one runs only on what
survives. Reranking: one question per query-candidate pair rather than asking a
model to sort a list.

**What it is not.** Not a chat model, not a summariser, not a writer. If the
output is meant for a person to read, this is the wrong tool. If the output is
meant for an `if` statement, it is very likely the right one.
