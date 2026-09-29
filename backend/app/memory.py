"""Chroma vector store for semantic recall across conversations (Phase 3).

Every user/assistant message gets embedded and stored here in addition to
its SQLite row (see db.py) -- SQLite stays the source of truth for full
conversation history and ordering; Chroma exists purely to answer "what did
we discuss before that's relevant to this new message", independent of which
conversation it happened in.

Uses Chroma's bundled default embedding function (all-MiniLM-L6-v2, ONNX,
runs locally, no API key or network call needed after the one-time model
download) rather than routing embedding calls through Ollama/OpenRouter --
keeps memory recall decoupled from which LLM providers happen to be
configured or running.

Chroma's client is synchronous; every public function here wraps its call in
asyncio.to_thread so embedding inference doesn't block the event loop during
a /chat request.
"""
from __future__ import annotations

import asyncio
import logging
import threading

import chromadb

from . import config

_client: chromadb.ClientAPI | None = None
_collection = None
_initialization_lock = threading.Lock()


def _collection_sync():
    global _client, _collection
    with _initialization_lock:
        if _collection is None:
            client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
            collection = client.get_or_create_collection("messages")
            _client, _collection = client, collection
    return _collection


async def recall_for_chat(message: str, conversation_id: int) -> list[dict]:
    """Optional recall must not prevent a new conversation response."""
    try:
        return await asyncio.wait_for(search(message, exclude_conversation_id=conversation_id), timeout=5)
    except Exception as exc:
        logging.getLogger(__name__).warning("Chat continuing without recall: %s", type(exc).__name__)
        return []


# --- fact status: operational error / confirmed / unconfirmed / question ---
#
# Milestone 2 refinement: Remembered Facts and the graph's semantic layer
# were showing operational failures ("OpenRouter API key is not configured")
# next to real content, and treating every assistant reply as if it were an
# equally-confirmed "fact." Neither classification below is a content-
# sniffing guess at what's "important" or "junk" -- both are provenance-
# based, using signals this app itself already produces, on purpose, so a
# quiz question ("What is the capital of Spain?") is never misjudged as
# meaningless test noise and quietly hidden; it's simply labeled a question,
# not a fact, and stays fully visible and searchable via the "All" filter.
#
# OPERATIONAL_ERROR_PREFIX matches main.py's own convention (grep the
# literal string "⚠️ " there): every surfaced failure -- provider errors,
# unexpected exceptions, "no provider available for category" -- is
# assembled with this exact prefix before being persisted. This is the same
# real signal `had_error` gates future writes on (see main.py); this
# function lets a LEGACY entry, written before that gate existed, be
# reclassified from its own stored text using the identical rule, not a
# separate heuristic.
OPERATIONAL_ERROR_PREFIX = "⚠️"

_QUESTION_WORDS = {
    "what", "who", "whom", "whose", "where", "when", "why", "how",
    "is", "are", "was", "were", "am", "do", "does", "did",
    "can", "could", "would", "will", "shall", "should", "may", "might",
    "which",
}


def is_operational_error(content: str) -> bool:
    return content.strip().startswith(OPERATIONAL_ERROR_PREFIX)


def _looks_like_question(content: str) -> bool:
    stripped = content.strip()
    if stripped.endswith("?"):
        return True
    first_word = stripped.split(None, 1)[0].strip(",.:;").lower() if stripped else ""
    return first_word in _QUESTION_WORDS or first_word in {
        'write', 'create', 'make', 'build', 'fix', 'show', 'tell', 'explain',
        'please', 'try', 'test', 'run', 'open', 'give', 'find', 'help', 'add',
        'remove', 'update', 'continue', 'hello', 'hi', 'hey', 'thanks', 'okay',
        'say', 'reply', 'respond', 'use', 'repeat', 'summarize', 'translate',
        'check', 'search', 'look', 'read', 'implement', 'set', 'go', 'stop',
    }


def classify_fact_status(role: str, content: str) -> str:
    """Provenance-based status, not a confidence score on the content itself.

    - "operational_error": a surfaced failure, never a fact about anything.
    - "confirmed": the user's own declarative statement -- the one case
      where "the user said X" is itself the fact.
    - "question": the user's own words, but a question isn't an assertion.
    - "unconfirmed": anything the assistant generated. Task: "An assistant
      statement is not automatically a fact about the user" -- so nothing
      assistant-authored is ever auto-promoted past this, regardless of how
      confident or fact-shaped the wording sounds.
    """
    if is_operational_error(content):
        return "operational_error"
    if role == "user":
        return "question" if _looks_like_question(content) else "confirmed"
    return "unconfirmed"


async def add_message(
    message_id: int,
    conversation_id: int,
    role: str,
    content: str,
    category: str | None = None,
    created_at: str | None = None,
) -> None:
    if not content.strip():
        return

    def _do() -> None:
        _collection_sync().upsert(
            ids=[f"message-{message_id}"],
            documents=[content],
            metadatas=[
                {
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "role": role,
                    "category": category or "",
                    "fact_status": classify_fact_status(role, content),
                    # Real SQLite timestamp (task: "Keep source, date,
                    # status ... easy to find") -- Chroma has no timestamp
                    # of its own, so every caller is expected to pass the
                    # real created_at already returned by db.add_message
                    # rather than this defaulting to "whenever this
                    # particular upsert happened to run."
                    "created_at": created_at or "",
                }
            ],
        )

    await asyncio.to_thread(_do)


async def search(
    query: str,
    top_k: int | None = None,
    exclude_conversation_id: int | None = None,
    include_operational_errors: bool = False,
) -> list[dict]:
    def _do() -> list[dict]:
        collection = _collection_sync()
        count = collection.count()
        if count == 0:
            return []
        # Overfetch when errors must be filtered client-side below (see the
        # module docstring note on why this isn't a Chroma-side `where`
        # clause) so excluding them doesn't silently shrink k for callers
        # that asked for a specific result count.
        fetch_k = min((top_k or config.MEMORY_RECALL_TOP_K) * 3, count) if not include_operational_errors else min(top_k or config.MEMORY_RECALL_TOP_K, count)
        where = (
            {"conversation_id": {"$ne": exclude_conversation_id}}
            if exclude_conversation_id is not None
            else None
        )
        result = collection.query(query_texts=[query], n_results=fetch_k, where=where)
        ids = result["ids"][0] if result["ids"] else []
        docs = result["documents"][0] if result["documents"] else []
        metas = result["metadatas"][0] if result["metadatas"] else []
        dists = result["distances"][0] if result["distances"] else []
        rows = [
            {"id": i, "content": d, "distance": dist, **m}
            for i, d, m, dist in zip(ids, docs, metas, dists)
            if dist <= config.MEMORY_RECALL_MAX_DISTANCE
        ]
        if not include_operational_errors:
            # Client-side, not a Chroma `where` filter: legacy entries
            # written before `fact_status` existed have no such metadata
            # key at all, and this app doesn't rely on Chroma's specific
            # (undocumented, version-dependent) behavior for "$ne against a
            # missing key" to decide whether they're included. Filtering the
            # already-fetched rows in plain Python is unambiguous either way.
            rows = [r for r in rows if r.get("fact_status") != "operational_error"]
        for row in rows:
            if not row.get('user_verified'):
                row['fact_status'] = classify_fact_status(row.get('role', ''), row['content'])
        return rows[: (top_k or config.MEMORY_RECALL_TOP_K)]

    return await asyncio.to_thread(_do)


async def search_many(queries: list[str], top_k: int | None = None) -> list[list[dict]]:
    """Real bug found live (graph performance profiling): graph.py's
    semantic layer was calling `search()` once per candidate message in a
    plain loop -- ~30 separate round trips through Chroma's embedding model,
    measured at ~4.4s wall-clock. Wrapping that same loop in
    `asyncio.gather` was tried and made it *worse* (~5s) -- these calls all
    go through `asyncio.to_thread`, and ONNX embedding inference apparently
    doesn't parallelize cleanly across threads here (GIL/lock contention),
    so concurrency just adds overhead without real overlap.

    The actual fix is this function: Chroma's own `collection.query()`
    already accepts a *list* of `query_texts` and batch-embeds/searches all
    of them in one call -- one round trip and one batched embedding pass
    instead of thirty separate ones. Returns one result list per input
    query, same order, each already distance-filtered and operational-error-
    excluded the same way `search()` is.
    """
    if not queries:
        return []

    def _do() -> list[list[dict]]:
        collection = _collection_sync()
        count = collection.count()
        if count == 0:
            return [[] for _ in queries]
        fetch_k = min((top_k or config.MEMORY_RECALL_TOP_K) * 3, count)
        result = collection.query(query_texts=queries, n_results=fetch_k)
        all_rows: list[list[dict]] = []
        for ids, docs, metas, dists in zip(
            result["ids"], result["documents"], result["metadatas"], result["distances"]
        ):
            rows = [
                {"id": i, "content": d, "distance": dist, **m}
                for i, d, m, dist in zip(ids, docs, metas, dists)
                if dist <= config.MEMORY_RECALL_MAX_DISTANCE and m.get("fact_status") != "operational_error"
            ]
            all_rows.append(rows[: (top_k or config.MEMORY_RECALL_TOP_K)])
        return all_rows

    return await asyncio.to_thread(_do)


async def list_recent(limit: int = 50, include_operational_errors: bool = False) -> list[dict]:
    def _do() -> list[dict]:
        collection = _collection_sync()
        if collection.count() == 0:
            return []
        # Chroma's get order is insertion order, not recency. Select newest
        # metadata first, then fetch only the requested documents.
        metadata = collection.get(include=["metadatas"])
        ordered = sorted(zip(metadata['ids'], metadata['metadatas']),
                         key=lambda item: (str(item[1].get('created_at') or '') if str(item[1].get('created_at') or '')[:4].isdigit() else '', item[0]), reverse=True)
        if not include_operational_errors:
            ordered = [(i, m) for i, m in ordered if m.get('fact_status') != 'operational_error']
        ids = [i for i, _ in ordered[:limit]]
        if not ids:
            return []
        result = collection.get(ids=ids, include=["documents", "metadatas"])
        rows = [
            {"id": i, "content": d, **m}
            for i, d, m in zip(result["ids"], result["documents"], result["metadatas"])
        ]
        if not include_operational_errors:
            rows = [r for r in rows if r.get("fact_status") != "operational_error"]
        for row in rows:
            if not row.get('user_verified'):
                row['fact_status'] = classify_fact_status(row.get('role', ''), row['content'])
        positions = {value: index for index, value in enumerate(ids)}
        rows.sort(key=lambda row: positions[row['id']])
        return rows[:limit]

    return await asyncio.to_thread(_do)


async def migrate_legacy_fact_status(dry_run: bool = True) -> dict:
    """One-time, fully reversible backfill for entries written before
    `fact_status`/`created_at` existed (see `add_message` above, and the
    module docstring on why classification is provenance-based). Nothing is
    deleted here -- documents keep their original content and id; only
    metadata is added/corrected, which is exactly what makes this
    reversible: writing different metadata back at any time fully undoes
    the effect. Task: "with a dry-run count first" -- `dry_run=True`
    computes and returns the same counts without writing anything.
    """
    from . import db  # local import: avoids a module-load-order cycle with main.py's own `from . import memory, db, ...`

    def _get_sync() -> tuple[list, list, list]:
        collection = _collection_sync()
        count = collection.count()
        if count == 0:
            return [], [], []
        result = collection.get(limit=count, include=["documents", "metadatas"])
        return result["ids"], result["documents"], result["metadatas"]

    ids, docs, metas = await asyncio.to_thread(_get_sync)
    if not ids:
        return {"total": 0, "already_tagged": 0, "migrated": 0, "by_status": {}, "dry_run": dry_run}

    by_status: dict[str, int] = {}
    already_tagged = 0
    to_update_ids: list[str] = []
    to_update_metas: list[dict] = []
    for doc_id, doc, meta in zip(ids, docs, metas):
        computed_status = classify_fact_status(meta.get("role", ""), doc)
        by_status[computed_status] = by_status.get(computed_status, 0) + 1
        needs_status = not meta.get("fact_status")
        needs_created_at = not meta.get("created_at")
        if not needs_status and not needs_created_at:
            already_tagged += 1
            continue
        new_meta = dict(meta)
        if needs_status:
            new_meta["fact_status"] = computed_status
        if needs_created_at:
            # Real SQLite timestamp for this exact message, not a
            # migration-time placeholder -- message_id is the same id
            # db.py has always assigned, so this is an accurate backfill,
            # not a guess.
            message_id = meta.get("message_id")
            row = await db.get_message(message_id) if message_id else None
            # Real bug found live: a since-deleted conversation (this
            # predates delete_conversation's own cascade cleanup, added in
            # the same pass -- see main.py) has no SQLite row to backfill
            # from. Writing "" back here left `not meta.get("created_at")`
            # true again on every future run, so this exact entry re-showed
            # up as "pending" forever no matter how many times the
            # migration ran. A clearly-labeled sentinel (never empty) is
            # honest about *why* there's no real date and actually resolves
            # -- once, not on a loop.
            new_meta["created_at"] = row["created_at"] if row else "source-deleted"
        to_update_ids.append(doc_id)
        to_update_metas.append(new_meta)

    if not dry_run and to_update_ids:

        def _update_sync() -> None:
            # Chroma's own metadata-only update -- documents/embeddings are
            # untouched, so this cannot alter search relevance or content.
            _collection_sync().update(ids=to_update_ids, metadatas=to_update_metas)

        await asyncio.to_thread(_update_sync)

    return {
        "total": len(ids),
        "already_tagged": already_tagged,
        "migrated": len(to_update_ids),
        "by_status": by_status,
        "dry_run": dry_run,
    }


async def update_content(memory_id: str, content: str) -> None:
    def _do() -> None:
        collection = _collection_sync()
        existing = collection.get(ids=[memory_id], include=["metadatas"])
        metas = existing.get("metadatas") or [{}]
        meta = dict(metas[0] or {})
        # A person just explicitly edited/verified this content through
        # Remembered Facts' "Correct" action -- real, direct confirmation,
        # regardless of the entry's original role or question/statement
        # shape. This is the one place `classify_fact_status`'s provenance
        # rule is deliberately overridden, because a stronger real signal
        # (an actual human correction) just occurred.
        meta["fact_status"] = "confirmed"
        meta["user_verified"] = True
        collection.update(ids=[memory_id], documents=[content], metadatas=[meta])

    await asyncio.to_thread(_do)


async def delete(memory_id: str) -> None:
    def _do() -> None:
        _collection_sync().delete(ids=[memory_id])

    await asyncio.to_thread(_do)
