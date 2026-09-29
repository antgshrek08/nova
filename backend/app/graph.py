"""Memory graph assembly (Milestone 2).

Combines three independently-real sources into one node/edge graph. Nothing
here invents a connection that isn't backed by an actual record:

- **conversation** nodes/edges -- every message already in SQLite (see
  db.py), with an EXPLICIT edge to the next message in the same
  conversation. A real thread, not a guess.
- **code** nodes/edges -- Graphify's own AST-derived extraction (see
  GRAPHIFY_PILOT_PATHS below), also EXPLICIT: an import or a function call is
  a parsed fact, not a probability. Scoped to this pilot's own source tree
  (backend/app, frontend/src) per the milestone's "pilot Graphify on Nova's
  project notes and code first" -- this is not (yet) run over the user's
  personal conversations or Obsidian vault.
- **semantic** edges -- real nearest-neighbor distances from the existing
  Chroma embedding store (see memory.py). This is the one genuinely
  INFERRED (model-based, not certain) layer here, and it's computed live on
  every request rather than cached, so correcting or forgetting a memory in
  Chroma is reflected on the very next graph fetch -- no stale index to go
  looking for it.

Nothing in this module calls a paid API. Graphify's own extraction runs with
--no-cluster, which is tree-sitter-only (confirmed via its own CLI output:
"re-extract code files ... no LLM needed") -- no API key involved. If a
local Ollama model is ever wired in for optional LLM-assisted cluster
naming, `get_status()`'s `local_model_available` is where that would be
gated; nothing here falls back to a paid provider automatically.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

from . import config, db, memory, obsidian, providers

NOVA_ROOT = Path(__file__).resolve().parents[2]
GRAPHIFY_PILOT_PATHS = [NOVA_ROOT / "backend" / "app", NOVA_ROOT / "frontend" / "src"]

# Files this app itself writes into the vault (see obsidian.py) -- excluded
# from ingestion by name/marker so a note we generated FROM a conversation
# doesn't get indexed a second time as if it were independent content (the
# conversation/message layers above already represent that same data).
# Task: "Exclude generated graph exports from ingestion to prevent recursive
# indexing" -- applied here to our own generated notes for the identical
# reason it applies to Graphify's graphify-out/ directory.
_VAULT_BOOTSTRAP_FILENAMES = {"welcome.md"}
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")

# Bounds keep one /memory/graph request fast and the default view readable
# (task: "Show labels selectively to prevent an unreadable wall of text" /
# avoid overwhelming an initial view) -- code nodes in particular can number
# in the hundreds even for a modest pilot scope (516 nodes for backend/app
# alone), so they're opt-in via the `kinds` filter rather than always-on.
DEFAULT_CONVERSATION_LIMIT = 40
SEMANTIC_SAMPLE_LIMIT = 30
SEMANTIC_TOP_K = 3
SEMANTIC_MAX_DISTANCE = 0.85

_reindex_state: dict = {"running": False, "started_at": None, "finished_at": None, "error": None, "results": None}


def graphify_installed() -> bool:
    return importlib.util.find_spec("graphify") is not None


def _load_graphify_graph(path: Path) -> dict | None:
    graph_path = path / "graphify-out" / "graph.json"
    if not graph_path.exists():
        return None
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {"mtime": graph_path.stat().st_mtime, "data": data}


async def get_status() -> dict:
    """Honest indexing status (task: "Show genuine indexing status" /
    "explain the indexing requirement within Memory settings"). Every field
    here reflects something actually checked this call, not a cached guess."""
    pilots = []
    total_nodes = 0
    total_edges = 0
    latest_mtime = None
    for p in GRAPHIFY_PILOT_PATHS:
        loaded = _load_graphify_graph(p)
        rel = str(p.relative_to(NOVA_ROOT)).replace("\\", "/")
        if loaded:
            n = len(loaded["data"].get("nodes", []))
            e = len(loaded["data"].get("links", loaded["data"].get("edges", [])))
            total_nodes += n
            total_edges += e
            latest_mtime = max(latest_mtime or 0, loaded["mtime"])
            pilots.append({"path": rel, "indexed": True, "nodes": n, "edges": e, "indexed_at": loaded["mtime"]})
        else:
            pilots.append({"path": rel, "indexed": False, "nodes": 0, "edges": 0, "indexed_at": None})

    try:
        local_models = await providers.get_local_ollama_models()
        local_model_available = len(local_models) > 0
    except Exception:  # noqa: BLE001 - Ollama simply isn't reachable
        local_model_available = False

    recent = await memory.list_recent(limit=1)

    # Obsidian status (task: "Inspect the configured vault and current
    # ingestion path" / "show 'Obsidian not connected' " when it genuinely
    # isn't). `opened_in_obsidian` checks for the real `.obsidian/` config
    # folder the Obsidian app itself creates the first time someone opens
    # this directory as a vault -- a much stronger signal than "the
    # directory exists," since this app creates the plain directory
    # unconditionally on startup regardless of whether anyone ever opens it.
    vault_dir = config.OBSIDIAN_VAULT_DIR
    opened_in_obsidian = (vault_dir / ".obsidian").exists()
    api_reachable = await obsidian.is_api_available()
    note_count = sum(1 for _ in _iter_vault_notes())

    return {
        "graphify_installed": graphify_installed(),
        "pilots": pilots,
        "graphify_total_nodes": total_nodes,
        "graphify_total_edges": total_edges,
        "graphify_indexed_at": latest_mtime,
        "reindexing": _reindex_state["running"],
        "reindex_error": _reindex_state["error"],
        "reindex_finished_at": _reindex_state["finished_at"],
        "local_model_available": local_model_available,
        "semantic_memory_available": bool(recent),
        "obsidian": {
            "vault_dir": str(vault_dir),
            "opened_in_obsidian": opened_in_obsidian,
            "live_api_connected": api_reachable,
            "api_key_configured": bool(config.OBSIDIAN_API_KEY),
            "indexable_note_count": note_count,
        },
    }


async def run_reindex() -> dict:
    """Runs Graphify's own no-LLM extraction over the pilot paths. This is a
    real subprocess call, not simulated -- deliberately invoked from a
    dedicated endpoint (see main.py's POST /memory/graph/reindex), never
    from the /chat or voice request path, per the milestone's "run indexing
    outside the chat/voice request path." --no-cluster skips even the
    *optional* LLM-assisted community naming step, so this never attempts a
    model call of any kind, local or paid."""
    import subprocess

    if _reindex_state["running"]:
        return {"already_running": True}
    _reindex_state.update(running=True, started_at=time.time(), error=None, results=None)
    results = []
    error = None
    try:
        for path in GRAPHIFY_PILOT_PATHS:
            if not path.exists():
                continue
            # A real bug found live: asyncio.create_subprocess_exec raises a
            # bare NotImplementedError (str(exc) == "", surfacing as a
            # blank, useless error) under uvicorn's default event loop on
            # Windows, which doesn't support asyncio subprocesses. A plain
            # synchronous subprocess.run, pushed off the event loop via
            # asyncio.to_thread, sidesteps that entirely and works
            # identically on every platform.
            proc = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "graphify", "update", str(path), "--no-cluster"],
                cwd=str(NOVA_ROOT),
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or "")[-800:] or f"exit code {proc.returncode}")
            loaded = _load_graphify_graph(path)
            results.append(
                {
                    "path": str(path.relative_to(NOVA_ROOT)).replace("\\", "/"),
                    "nodes": len(loaded["data"].get("nodes", [])) if loaded else 0,
                    "edges": len(loaded["data"].get("links", loaded["data"].get("edges", []))) if loaded else 0,
                }
            )
    except Exception as exc:  # noqa: BLE001 - surfaced via /memory/graph/status
        error = str(exc)
    finally:
        _reindex_state.update(running=False, finished_at=time.time(), error=error, results=results)
    return _reindex_state


def _excerpt(text: str, length: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= length else text[: length - 1] + "…"


async def _project_layer(conversations: list[dict]) -> tuple[list[dict], list[dict], dict[int, str]]:
    """Real `projects` rows (db.py's own table -- name + instructions a user
    actually created via Projects), not a fabricated grouping. Only projects
    that own at least one of the conversations already in this graph's
    window are included, so this never introduces an empty-looking node for
    a project with nothing currently in view."""
    nodes: list[dict] = []
    edges: list[dict] = []
    conv_ids_by_project: dict[int, list[int]] = {}
    for c in conversations:
        if c.get("project_id") is not None:
            conv_ids_by_project.setdefault(c["project_id"], []).append(c["id"])
    node_id_by_project: dict[int, str] = {}
    if not conv_ids_by_project:
        return nodes, edges, node_id_by_project
    for project in await db.list_projects():
        if project["id"] not in conv_ids_by_project:
            continue
        proj_node_id = f"project-{project['id']}"
        node_id_by_project[project["id"]] = proj_node_id
        nodes.append(
            {
                "id": proj_node_id,
                "kind": "project",
                "label": project["name"],
                "subtitle": "project",
                "date": project.get("created_at"),
                "content": project.get("instructions") or project["name"],
                "project_id": project["id"],
            }
        )
        for conv_id in conv_ids_by_project[project["id"]]:
            edges.append(
                {
                    "id": f"project-contains-{project['id']}-{conv_id}",
                    "source": proj_node_id,
                    "target": f"conversation-{conv_id}",
                    "kind": "explicit",
                    "relation": "contains",
                    "explanation": f"Grouped under the project “{project['name']}”.",
                }
            )
    return nodes, edges, node_id_by_project


async def _conversation_layer(limit: int) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    edges: list[dict] = []
    conversations = await db.list_conversations()
    conversations = sorted(conversations, key=lambda c: c["updated_at"], reverse=True)[:limit]

    project_nodes, project_edges, _ = await _project_layer(conversations)
    nodes += project_nodes
    edges += project_edges

    for conv in conversations:
        conv_node_id = f"conversation-{conv['id']}"
        nodes.append(
            {
                "id": conv_node_id,
                "kind": "conversation",
                "label": conv["title"],
                "subtitle": conv["tab"],
                "date": conv["updated_at"],
                "content": conv["title"],
                "conversation_id": conv["id"],
                "tab": conv["tab"],
                "project_id": conv.get("project_id"),
            }
        )
        messages = await db.list_messages(conv["id"])
        prev_id = None
        for m in messages:
            if not (m["content"] or "").strip():
                continue
            msg_node_id = f"message-{m['id']}"
            # Same provenance rule memory.py uses for Remembered Facts (see
            # its module docstring) -- computed here too so the graph can be
            # honest about an operational failure ("⚠️ ...") being just
            # that, never a real conversational exchange, without a second
            # round trip to Chroma just to find out.
            fact_status = memory.classify_fact_status(m["role"], m["content"])
            nodes.append(
                {
                    "id": msg_node_id,
                    "kind": "message",
                    "label": _excerpt(m["content"], 48),
                    "subtitle": m["role"],
                    "role": m["role"],
                    "category": m.get("category"),
                    "fact_status": fact_status,
                    "date": m["created_at"],
                    "content": m["content"],
                    "conversation_id": conv["id"],
                    "conversation_title": conv["title"],
                    "tab": conv["tab"],
                }
            )
            # Explicit: this message belongs to this conversation.
            edges.append(
                {
                    "id": f"belongs-{msg_node_id}",
                    "source": msg_node_id,
                    "target": conv_node_id,
                    "kind": "explicit",
                    "relation": "in_conversation",
                    "explanation": f"Part of the conversation “{conv['title']}”.",
                }
            )
            if prev_id is not None:
                # Explicit: real sequential adjacency in one thread.
                edges.append(
                    {
                        "id": f"next-{prev_id}-{msg_node_id}",
                        "source": prev_id,
                        "target": msg_node_id,
                        "kind": "explicit",
                        "relation": "followed_by",
                        "explanation": "Sequential messages in the same conversation.",
                    }
                )
            prev_id = msg_node_id
    return nodes, edges


async def _code_layer() -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    edges: list[dict] = []
    for path in GRAPHIFY_PILOT_PATHS:
        loaded = _load_graphify_graph(path)
        if not loaded:
            continue
        rel_root = str(path.relative_to(NOVA_ROOT)).replace("\\", "/")
        data = loaded["data"]
        pilot_node_ids: set[str] = set()
        for n in data.get("nodes", []):
            node_id = f"code-{rel_root}-{n['id']}"
            pilot_node_ids.add(node_id)
            nodes.append(
                {
                    "id": node_id,
                    "kind": "code",
                    "label": n.get("label") or n.get("id"),
                    "subtitle": n.get("source_file", rel_root),
                    "date": None,
                    "content": f"{n.get('source_file', '')} ({n.get('source_location', '')})",
                    "file_type": n.get("file_type"),
                    "pilot_path": rel_root,
                }
            )
        for link in data.get("links", data.get("edges", [])):
            src = f"code-{rel_root}-{link['source']}"
            tgt = f"code-{rel_root}-{link['target']}"
            # Real data-integrity gap found live (Milestone 2 performance
            # pass): Graphify records an edge to an external/stdlib import
            # (e.g. "asyncio") as a link TARGET without ever emitting that
            # import as its own node -- a dangling reference this app's own
            # graph never actually asked for. The frontend's physics engine
            # (d3-force) throws outright on an edge referencing a node
            # that isn't present, which is what surfaced this; filtering it
            # out at the source is more correct regardless of which
            # renderer consumes it next -- an edge to a node this response
            # never included was already meaningless.
            if src not in pilot_node_ids or tgt not in pilot_node_ids:
                continue
            edges.append(
                {
                    "id": f"code-edge-{rel_root}-{link['source']}-{link['target']}-{link.get('relation')}",
                    "source": src,
                    "target": tgt,
                    "kind": "explicit",
                    "relation": link.get("relation", "related"),
                    "explanation": f"Graphify (AST-parsed): {link.get('relation', 'related')}.",
                }
            )
    return nodes, edges


def _iter_vault_notes():
    """Every genuinely independent markdown file in the vault -- excludes
    Obsidian's own `.obsidian/` config folder, this app's own generated
    conversation/project notes (identified by the same AUTO_MARKER they're
    written with, or by filename for the one marker-less bootstrap file),
    and any `graphify-out/` directory that might exist inside the vault.
    Real user-authored content only, which is honestly often nothing --
    see get_status()'s note_count for what's actually there right now."""
    vault = config.OBSIDIAN_VAULT_DIR
    if not vault.exists():
        return
    for path in vault.rglob("*.md"):
        rel_parts = path.relative_to(vault).parts
        if any(part == ".obsidian" or part == "graphify-out" for part in rel_parts):
            continue
        if path.name.lower() in _VAULT_BOOTSTRAP_FILENAMES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if obsidian.AUTO_MARKER in text:
            continue
        yield path, text


async def _notes_layer() -> tuple[list[dict], list[dict]]:
    """Obsidian vault notes as real, independent nodes (task: "Verify
    Obsidian input" / treat the vault as a genuine ingestion source, not
    just an export target). Live-scanned on every call -- a plain directory
    walk over Markdown files is cheap enough that there's no separate
    "reindex" step to run or go stale the way Graphify's AST extraction
    needs one; editing a note and refetching the graph is already a fresh
    read. Wikilink edges (Obsidian's own `[[Note Name]]` syntax) are the one
    EXPLICIT relation available here -- a real link the user wrote, not an
    inferred one -- and only ever connects two notes that are both already
    indexed (never a dangling reference to nothing)."""
    nodes: list[dict] = []
    notes_by_stem: dict[str, str] = {}  # filename stem (lowercased) -> node id
    entries = list(_iter_vault_notes())
    vault = config.OBSIDIAN_VAULT_DIR
    for path, text in entries:
        rel = str(path.relative_to(vault)).replace("\\", "/")
        node_id = f"note-{rel}"
        notes_by_stem[path.stem.lower()] = node_id
        title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        label = title_match.group(1).strip() if title_match else path.stem
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        nodes.append(
            {
                "id": node_id,
                "kind": "note",
                "label": label,
                "subtitle": rel,
                "date": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(mtime)) if mtime else None,
                "content": text,
                "vault_path": rel,
            }
        )

    edges: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    for path, text in entries:
        source_id = f"note-{str(path.relative_to(vault)).replace(chr(92), '/')}"
        for match in _WIKILINK_RE.finditer(text):
            target_stem = match.group(1).strip().lower()
            target_id = notes_by_stem.get(target_stem)
            if not target_id or target_id == source_id:
                continue
            pair = tuple(sorted((source_id, target_id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            edges.append(
                {
                    "id": f"wikilink-{pair[0]}-{pair[1]}",
                    "source": pair[0],
                    "target": pair[1],
                    "kind": "explicit",
                    "relation": "wikilinked",
                    "explanation": "Linked directly with Obsidian's own [[wikilink]] syntax.",
                }
            )
    return nodes, edges


async def _semantic_layer(message_nodes: list[dict]) -> list[dict]:
    """Real inferred edges from Chroma's own nearest-neighbor distances --
    sampled (see SEMANTIC_SAMPLE_LIMIT) to keep one request fast, and only
    ever connecting nodes already present in this graph (never introducing a
    node the caller didn't ask for).

    Real bug found live (fixture test): querying with each node's SQLite
    `content` (from `_conversation_layer`, i.e. `messages.content`) instead
    of Chroma's own current document text meant an edit made through
    Remembered Facts -- which calls `memory.update_content`, touching only
    Chroma, not the SQLite row the transcript itself shows -- left a stale
    semantic edge in the graph: the *other* node in the pair was still
    queried with its own unedited SQLite text, which still matched the old
    embedding fine. Fetching current content straight from Chroma
    (`memory.list_recent`) for every query fixes this at the source instead
    of trying to keep two stores' text in sync.
    """
    edges: list[dict] = []
    node_ids = {n["id"] for n in message_nodes}
    try:
        current = await memory.list_recent(limit=500)
    except Exception:  # noqa: BLE001 - Chroma unavailable; no semantic layer this call
        return edges
    current_content_by_id = {f"message-{m.get('message_id')}": m.get("content", "") for m in current}
    # Real bug found live (fixture test, second pass): sampling from
    # `node_ids` (a set, no defined order) meant a just-added message could
    # land anywhere in Python's arbitrary set iteration order and get cut
    # off by the [:SEMANTIC_SAMPLE_LIMIT] slice even though it was the most
    # recent thing in the graph. Iterating `message_nodes` instead (already
    # ordered most-recently-updated-conversation-first by
    # `_conversation_layer`) makes the sample deterministically favor recent
    # content, not an arbitrary hash-driven subset of it.
    candidates = [
        n["id"]
        for n in message_nodes
        if len((current_content_by_id.get(n["id"]) or "").strip()) > 15
    ][:SEMANTIC_SAMPLE_LIMIT]

    # Real bug found live (profiling, Milestone 2 performance pass): these
    # SEMANTIC_SAMPLE_LIMIT queries are independent reads against the same
    # Chroma collection, but were being awaited one at a time in a plain
    # for-loop -- measured at ~4.4s wall-clock for 30 candidates (roughly
    # 145ms/query), entirely on this one request, every single time the
    # graph loads with "Inferred links" on (which is on by default, so this
    # hit every load, not just the ones toggling Code or Show messages).
    # `asyncio.gather`-ing the same per-query calls was tried first and
    # measured *worse* (~5s) -- these all go through `asyncio.to_thread`, and
    # ONNX embedding inference doesn't parallelize cleanly across threads
    # here (GIL/lock contention), so concurrency alone just adds overhead.
    # The real fix: `memory.search_many` sends every candidate's text to
    # Chroma in ONE batched `query_texts=[...]` call, letting the embedding
    # model batch-embed all of them in a single pass instead of thirty
    # separate ones -- one round trip, not thirty concurrent or sequential
    # ones.
    try:
        query_results = await memory.search_many(
            [current_content_by_id[node_id] for node_id in candidates], top_k=SEMANTIC_TOP_K + 1
        )
    except Exception:  # noqa: BLE001 - Chroma unavailable this call; no semantic layer this call
        return edges

    seen_pairs: set[tuple[str, str]] = set()
    for node_id, results in zip(candidates, query_results):
        for r in results:
            neighbor_id = f"message-{r.get('message_id')}"
            if neighbor_id == node_id or neighbor_id not in node_ids:
                continue
            if r.get("distance") is None or r["distance"] > SEMANTIC_MAX_DISTANCE:
                continue
            pair = tuple(sorted((node_id, neighbor_id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            edges.append(
                {
                    "id": f"semantic-{pair[0]}-{pair[1]}",
                    "source": pair[0],
                    "target": pair[1],
                    "kind": "inferred",
                    "relation": "semantically_similar",
                    "score": round(1 - r["distance"], 3),
                    "explanation": (
                        f"Inferred: similar meaning (embedding similarity "
                        f"{round(1 - r['distance'], 2)}), not a stated connection."
                    ),
                }
            )
    return edges


async def get_graph(kinds: list[str] | None = None, conversation_limit: int = DEFAULT_CONVERSATION_LIMIT) -> dict:
    """Assembles the full graph. `kinds` (a subset of {"conversation",
    "code", "semantic"}) narrows which layers to include -- code defaults
    OFF (see DEFAULT_CONVERSATION_LIMIT's doc comment) so a first visit to
    Memory shows a readable personal graph, not 500+ code nodes."""
    # knowledge is on by default: it is the layer that represents what Nova
    # has actually learned, and it is small, so hiding it behind a toggle
    # would mean the graph looks unchanged no matter how much it knows.
    want = set(kinds) if kinds else {"conversation", "notes", "semantic", "knowledge"}
    nodes: list[dict] = []
    edges: list[dict] = []

    if "knowledge" in want:
        knowledge_nodes, knowledge_edges = await _knowledge_layer()
        nodes += knowledge_nodes
        edges += knowledge_edges

    message_nodes: list[dict] = []
    if "conversation" in want:
        conv_nodes, conv_edges = await _conversation_layer(conversation_limit)
        nodes += conv_nodes
        edges += conv_edges
        message_nodes = [n for n in conv_nodes if n["kind"] == "message"]

    if "code" in want:
        code_nodes, code_edges = await _code_layer()
        nodes += code_nodes
        edges += code_edges

    if "notes" in want:
        note_nodes, note_edges = await _notes_layer()
        nodes += note_nodes
        edges += note_edges

    if "semantic" in want and message_nodes:
        edges += await _semantic_layer(message_nodes)

    # Normalize at the API boundary. Graphify versions have emitted both
    # `links` and `edges`, and semantic/notes sources can repeat an inferred
    # pair. Canvas force layouts require unique, resolvable endpoints.
    unique_nodes = []
    node_ids = set()
    for node in nodes:
        node_id = str(node.get("id", ""))
        if node_id and node_id not in node_ids:
            node_ids.add(node_id)
            unique_nodes.append(node)
    unique_edges = []
    edge_keys = set()
    for edge in edges:
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        if source not in node_ids or target not in node_ids or source == target:
            continue
        key = (source, target, edge.get("kind", ""), edge.get("relation", ""))
        if key in edge_keys:
            continue
        edge_keys.add(key)
        unique_edges.append({**edge, "source": source, "target": target})
    return {"nodes": unique_nodes, "edges": unique_edges}


async def _knowledge_layer() -> tuple[list[dict], list[dict]]:
    """Distilled statements as their own nodes (see knowledge.py).

    This is the layer that makes the graph get better the more Nova is used.
    Every other layer here is a view of something that already existed -- a
    transcript, a source tree, a vault. These nodes are the only ones that
    represent something Nova worked out and kept.

    Two kinds of edge, both real:

    - to the conversation a statement was learned in, which is a recorded
      fact (the row stores conversation_id), so EXPLICIT.
    - between statements that share a subject, which is a genuine shared key
      rather than a similarity score -- also EXPLICIT. This is what makes a
      subject discussed across months read as one cluster instead of a
      scatter of unrelated dots.
    """
    rows = await db.list_knowledge()
    nodes: list[dict] = []
    edges: list[dict] = []
    by_subject: dict[str, list[str]] = {}

    for row in rows:
        node_id = f"knowledge-{row['id']}"
        nodes.append(
            {
                "id": node_id,
                "kind": "knowledge",
                "label": row["subject"],
                "subtitle": _excerpt(row["statement"], 120),
                "date": row["last_seen_at"],
                # Surfaced so the UI can distinguish what the user asserted
                # from what Nova merely produced -- never collapse the two.
                "status": row["status"],
                "category": row["category"],
                "times_seen": row["times_seen"],
                "conversation_id": row["conversation_id"],
            }
        )
        by_subject.setdefault(row["subject"].strip().lower(), []).append(node_id)
        if row["conversation_id"]:
            edges.append(
                {
                    "source": node_id,
                    "target": f"conversation-{row['conversation_id']}",
                    "kind": "explicit",
                    "relation": "learned_in",
                }
            )

    # Chain each subject's statements rather than fully connecting them: a
    # subject with ten statements would otherwise contribute 45 edges and
    # dominate the layout for no extra information.
    for shared in by_subject.values():
        for first, second in zip(shared, shared[1:]):
            edges.append(
                {"source": first, "target": second, "kind": "explicit", "relation": "same_subject"}
            )

    return nodes, edges
