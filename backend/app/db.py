"""SQLite persistence for Phase 2: conversations, messages, projects,
project files, and the spend log (see costs.py, which now reads/writes the
spend_log table instead of an in-memory counter).

A single shared connection is opened lazily and reused for the life of the
process -- this is a local, single-user desktop app, so there's no need for
a connection pool. WAL mode lets a read (e.g. GET /conversations) proceed
without blocking a concurrent write.
"""
from __future__ import annotations

import json
import asyncio
from datetime import date as date_cls
from typing import Any

import aiosqlite

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    instructions TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tab TEXT NOT NULL CHECK (tab IN ('chat', 'code', 'homework', 'projects')),
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'New conversation',
    pinned INTEGER NOT NULL DEFAULT 0,
    homework INTEGER NOT NULL DEFAULT 0,
    schedule_label TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Small key/value store for N.O.V.A. Settings toggles (General/Voice sections).
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Ollama model ids the user has disabled from routing via Settings > Models.
-- Nothing else in the model roster (CLI/Gemini/OpenRouter) is user-toggleable
-- here since those aren't a fixed local list -- see main.py's /models.
CREATE TABLE IF NOT EXISTS disabled_models (
    model_id TEXT PRIMARY KEY
);

-- User-added model connections (Settings > Models > Add Model). Tried FIRST
-- in routing.resolve() for their assigned category, ahead of the spec's
-- built-in keyword chain -- see routing.py. provider is 'openrouter' (an
-- exact model id, dispatched directly, no free-tier gating -- the user
-- picked it deliberately, possibly from the browse/search list of current
-- free models, possibly typed by hand), 'ollama' (a model this app pulled
-- locally; routing re-checks it's still actually present before using it),
-- or 'custom' (any OpenAI-compatible endpoint: api_base required, api_key
-- optional for a local server that doesn't check one).
CREATE TABLE IF NOT EXISTS custom_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('openrouter', 'ollama', 'custom')),
    model_id TEXT NOT NULL,
    category TEXT NOT NULL,
    api_base TEXT,
    api_key TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- MCP server connections configured via Settings > MCP. Stdio transport only
-- (a command + args, same shape as Claude Desktop's mcpServers config) --
-- see mcp_manager.py. args/env are JSON-encoded rather than normalized into
-- their own tables since they're opaque to everything except the MCP client.
CREATE TABLE IF NOT EXISTS mcp_servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    command TEXT NOT NULL,
    args TEXT NOT NULL DEFAULT '[]',
    env TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Canvas assignments mirrored by the nightly sync (see canvas_sync.py).
-- canvas_id is UNIQUE and is what makes "never duplicate an assignment" a
-- property of the schema rather than of the job's logic: re-running the sync
-- any number of times in a day can only ever update a row, never add a second
-- copy. due_at is tracked separately from last_seen so a professor moving a
-- deadline shows up as a real change (and re-alerts) instead of silently
-- overwriting, which is the failure mode that actually costs a grade.
CREATE TABLE IF NOT EXISTS canvas_assignments (
    canvas_id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL,
    course_name TEXT NOT NULL,
    title TEXT NOT NULL,
    due_at TEXT,
    points REAL,
    url TEXT,
    submitted INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen TEXT NOT NULL DEFAULT (datetime('now')),
    due_changed_at TEXT,
    notified_at TEXT
);

-- ACP agents (Settings > Agents -- see acp.py). External coding agents that
-- speak the Agent Client Protocol over stdio (Claude Code via claude-code-acp,
-- Gemini CLI's --experimental-acp, Hermes, any other conforming agent). Same
-- shape as mcp_servers on purpose: both are "a subprocess we speak JSON-RPC
-- to," and keeping the columns aligned means the Settings UI for one is the
-- Settings UI for the other.
CREATE TABLE IF NOT EXISTS acp_agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    command TEXT NOT NULL,
    args TEXT NOT NULL DEFAULT '[]',
    env TEXT NOT NULL DEFAULT '{}',
    cwd TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Cloned TTS voices (Settings > Voice). The reference audio itself lives on
-- disk under config.VOICES_DIR/{id}.wav (see tts.py) -- audio_filename here
-- is just that file's on-disk name. Chatterbox's single shipped built-in
-- voice isn't a DB row; it's represented by the app_settings tts_voice_id
-- value "default" and needs no reference file.
CREATE TABLE IF NOT EXISTS tts_voices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    audio_filename TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    category TEXT,
    provider TEXT,
    model TEXT,
    label TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    data BLOB NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Chat-tab file attachments (Settings/Projects already had file storage;
-- this is the same shape, scoped to a single chat message instead of a
-- whole project -- see main.py's /chat/attachments). Uploaded once, before
-- the message is sent, then referenced by id from ChatRequest.attachment_ids
-- and folded into that message's content server-side.
CREATE TABLE IF NOT EXISTS chat_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    data BLOB NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS spend_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    tokens INTEGER NOT NULL,
    provider TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Workspace/team-orchestration milestone: durable task state (task:
-- "Store task state durably. On restart, reconcile interrupted jobs rather
-- than marking them successful or blindly rerunning actions"). One row per
-- unit of work the director hands out, top-level (parent_id NULL, the
-- director's own plan for one user request) or a subtask underneath it.
-- Deliberately separate from agents.py's AgentJob (in-memory, one provider
-- call, capped at 30, gone on restart) -- a task can span several provider
-- calls over its lifetime (queued -> running -> done) and must survive a
-- restart; AgentJob remains the live per-call streaming layer a running
-- task's `job_id` points at while it's actually executing.
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    team TEXT,
    role TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'blocked', 'done', 'error', 'cancelled', 'interrupted')),
    provider TEXT,
    model TEXT,
    job_id INTEGER,
    result_summary TEXT,
    error TEXT,
    artifacts TEXT NOT NULL DEFAULT '[]',
    writes_files INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT
);

-- Many-to-many: a task may need more than one prior task done first (task:
-- "verify dependency scheduling with two independent subtasks and a final
-- synthesis step" -- the synthesis task depends on both).
CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, depends_on_id)
);

-- Append-only activity log per task (task: Workspace's detail panel needs
-- real "activity", not a single status field) -- one row per meaningful
-- state change or note, shown newest-first in the UI.
CREATE TABLE IF NOT EXISTS task_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversations_tab ON conversations(tab);
CREATE INDEX IF NOT EXISTS idx_project_files_project ON project_files(project_id);
-- Durable things Nova has learned, distilled from conversations rather than
-- stored verbatim (see knowledge.py). One row is one standalone statement.
-- `status` follows memory.classify_fact_status's provenance rule: only the
-- user's own assertions are "confirmed"; anything the assistant produced
-- stays "unconfirmed" no matter how fact-shaped it sounded.
-- `subject` is what the statement is about, and is what lets two statements
-- from different months end up on the same node in the graph.
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
    message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    subject TEXT NOT NULL,
    statement TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'fact',
    status TEXT NOT NULL DEFAULT 'unconfirmed',
    source_role TEXT NOT NULL DEFAULT 'user',
    -- Lowercased, whitespace-collapsed statement. UNIQUE so re-learning the
    -- same thing in a later chat updates one node instead of growing a pile
    -- of near-identical ones -- a graph that gains a duplicate every time a
    -- subject comes up is noise, not memory.
    fingerprint TEXT NOT NULL UNIQUE,
    times_seen INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Accounts held in Nova's name (see identity.py). Metadata only: the password
-- lives in secrets_store under "account:<service>" and never appears here, so
-- this table is safe to read, list and show a model. `service` is the natural
-- key because one login per site is the case that matters; a second account on
-- the same site is recorded by naming it distinctly ("github work").
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL,
    url TEXT,
    email TEXT,               -- the address the signup was registered to
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Devices Nova is allowed to reach unprompted (see push.py). `endpoint` is
-- the push service's address for one browser install and is therefore the
-- natural key: re-subscribing from the same phone must update this row, not
-- add a second one that would deliver every notification twice.
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL UNIQUE,
    subscription TEXT NOT NULL,   -- the whole PushSubscription JSON, as the browser gave it
    label TEXT,                   -- "My iPhone", for the Settings list
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_sent_at TEXT
);
CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY DEFAULT 1,
    name TEXT NOT NULL DEFAULT 'Student',
    school TEXT DEFAULT '',
    major TEXT DEFAULT '',
    graduation_year TEXT DEFAULT '',
    timezone TEXT DEFAULT '',
    onboarding_completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    instructor TEXT DEFAULT '',
    schedule TEXT DEFAULT '',
    portal_type TEXT DEFAULT 'manual',
    portal_url TEXT DEFAULT '',
    color TEXT DEFAULT '#3b82f6',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS syllabi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    raw_text TEXT,
    parsed_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS obsidian_vaults (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    auto_sync INTEGER NOT NULL DEFAULT 1,
    last_synced_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS study_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'text',
    content TEXT,
    ocr_raw TEXT,
    file_path TEXT,
    obsidian_note_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS learned_homework_procedures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portal_pattern TEXT NOT NULL,
    widget_signature TEXT NOT NULL UNIQUE,
    widget_type TEXT NOT NULL,
    instruction_summary TEXT NOT NULL DEFAULT '',
    recipe_json TEXT NOT NULL,
    times_used INTEGER NOT NULL DEFAULT 1,
    success_rate REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS custom_tabs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT 'Sparkles',
    description TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'widget',
    html_content TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS custom_connectors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'deployment',
    auth_type TEXT NOT NULL DEFAULT 'zero_api',
    description TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_knowledge_conversation ON knowledge(conversation_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_subject ON knowledge(subject);
CREATE INDEX IF NOT EXISTS idx_spend_log_day ON spend_log(day);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_task_deps_task ON task_dependencies(task_id);
CREATE INDEX IF NOT EXISTS idx_task_activity_task ON task_activity(task_id);
CREATE INDEX IF NOT EXISTS idx_courses_code ON courses(code);
CREATE INDEX IF NOT EXISTS idx_syllabi_course ON syllabi(course_id);
CREATE INDEX IF NOT EXISTS idx_study_notes_course ON study_notes(course_id);
CREATE INDEX IF NOT EXISTS idx_learned_procedures_sig ON learned_homework_procedures(widget_signature);
"""

_UNSET = object()

_connection: aiosqlite.Connection | None = None
_connection_lock = asyncio.Lock()

# Columns added after the initial Phase 2 schema. CREATE TABLE IF NOT EXISTS
# above only applies to a fresh DB -- an existing ai_council.db from an
# earlier phase needs these added by hand, one ALTER TABLE per column,
# ignoring "duplicate column" so this stays idempotent across restarts.
_CONVERSATION_COLUMNS = [
    ("pinned", "INTEGER NOT NULL DEFAULT 0"),
    ("homework", "INTEGER NOT NULL DEFAULT 0"),
    ("schedule_label", "TEXT"),
]

# JSON-encoded list of {id, filename, content_type, size_bytes} for whatever
# chat_attachments rows this message referenced -- NULL/absent for every
# message before this feature existed, same "old rows just don't have it"
# idempotent-migration pattern as _CONVERSATION_COLUMNS above.
_MESSAGE_COLUMNS = [
    ("attachments", "TEXT"),
]

# Remote MCP support (HTTP/SSE + OAuth, see mcp_manager.py/mcp_oauth.py) --
# every row before this was implicitly transport='stdio' with these all
# NULL/empty, which is exactly what the DEFAULT below preserves. url is only
# meaningful for transport in ('http', 'sse'). oauth_client_info/
# oauth_tokens are JSON-encoded mcp.shared.auth.OAuthClientInformationFull /
# OAuthToken respectively (see mcp_oauth.DBTokenStorage) -- NULL until a
# server has actually completed dynamic client registration / a token
# exchange.
_ASSIGNMENT_COLUMNS = [
    ("source", "TEXT DEFAULT 'canvas'"),
    ("description", "TEXT DEFAULT ''"),
]

_MCP_SERVER_COLUMNS = [
    ("transport", "TEXT NOT NULL DEFAULT 'stdio'"),
    ("url", "TEXT"),
    ("oauth_client_info", "TEXT"),
    ("oauth_tokens", "TEXT"),
]


async def _migrate(conn: aiosqlite.Connection) -> None:
    for name, ddl in _CONVERSATION_COLUMNS:
        try:
            await conn.execute(f"ALTER TABLE conversations ADD COLUMN {name} {ddl}")
        except aiosqlite.OperationalError:
            pass  # column already exists
    for name, ddl in _MESSAGE_COLUMNS:
        try:
            await conn.execute(f"ALTER TABLE messages ADD COLUMN {name} {ddl}")
        except aiosqlite.OperationalError:
            pass  # column already exists
    for name, ddl in _ASSIGNMENT_COLUMNS:
        try:
            await conn.execute(f"ALTER TABLE canvas_assignments ADD COLUMN {name} {ddl}")
        except aiosqlite.OperationalError:
            pass

    # Ensure academic hub & profile tables exist on existing DBs
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS user_profile (
        id INTEGER PRIMARY KEY DEFAULT 1,
        name TEXT NOT NULL DEFAULT 'Student',
        school TEXT DEFAULT '',
        major TEXT DEFAULT '',
        graduation_year TEXT DEFAULT '',
        timezone TEXT DEFAULT '',
        onboarding_completed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)
    # Ensure default user profile row exists
    await conn.execute("INSERT OR IGNORE INTO user_profile (id, name) VALUES (1, 'Student');")

    await conn.execute("""
    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL,
        name TEXT NOT NULL,
        instructor TEXT DEFAULT '',
        schedule TEXT DEFAULT '',
        portal_type TEXT DEFAULT 'manual',
        portal_url TEXT DEFAULT '',
        color TEXT DEFAULT '#3b82f6',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS syllabi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
        filename TEXT NOT NULL,
        raw_text TEXT,
        parsed_json TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS obsidian_vaults (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        path TEXT NOT NULL UNIQUE,
        auto_sync INTEGER NOT NULL DEFAULT 1,
        last_synced_at TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS study_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL,
        title TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'text',
        content TEXT,
        ocr_raw TEXT,
        file_path TEXT,
        obsidian_note_path TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)
    for name, ddl in _MCP_SERVER_COLUMNS:
        try:
            await conn.execute(f"ALTER TABLE mcp_servers ADD COLUMN {name} {ddl}")
        except aiosqlite.OperationalError:
            pass  # column already exists
    # N.O.V.A.'s redesign folds the old standalone 'homework' and 'projects'
    # tabs into Chat: homework becomes a per-conversation toggle, projects
    # becomes a sidebar section. Move any pre-existing rows so they still
    # show up somewhere in the new 2-tab (chat/code) sidebar.
    await conn.execute("UPDATE conversations SET homework = 1, tab = 'chat' WHERE tab = 'homework'")
    await conn.execute("UPDATE conversations SET tab = 'chat' WHERE tab = 'projects'")
    # Task reconciliation (task: "On restart, reconcile interrupted jobs
    # rather than marking them successful or blindly rerunning actions").
    # Runs once per process start (this function only runs when _connection
    # was None). Any task still 'running' or 'queued' from a prior process
    # was mid-flight (running) or never picked up (queued) when that process
    # died -- neither is "done", and none of it is silently retried; a human
    # decides via a real Retry action once they see it in Workspace. Ids are
    # captured before the UPDATE so the activity note is only added for rows
    # this restart actually reconciled, not every already-interrupted task
    # from some earlier restart too.
    cursor = await conn.execute("SELECT id FROM tasks WHERE status IN ('running', 'queued')")
    interrupted_ids = [row["id"] for row in await cursor.fetchall()]
    if interrupted_ids:
        await conn.execute(
            "UPDATE tasks SET status = 'interrupted', updated_at = datetime('now') "
            "WHERE status IN ('running', 'queued')"
        )
        await conn.executemany(
            "INSERT INTO task_activity (task_id, kind, message) VALUES (?, 'interrupted', "
            "'Backend restarted while this task was in progress.')",
            [(tid,) for tid in interrupted_ids],
        )
    await conn.commit()


async def get_connection() -> aiosqlite.Connection:
    global _connection
    async with _connection_lock:
        if _connection is None:
            connection = await aiosqlite.connect(config.DB_PATH)
            try:
                connection.row_factory = aiosqlite.Row
                await connection.execute("PRAGMA foreign_keys = ON")
                await connection.execute("PRAGMA journal_mode = WAL")
                await connection.executescript(_SCHEMA)
                await connection.commit()
                await _migrate(connection)
            except BaseException:
                # Includes cancellation: never cache a partially initialized
                # connection, and allow the next request to retry startup.
                await connection.close()
                raise
            _connection = connection
        return _connection


def _row(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


# --- projects ---------------------------------------------------------


async def create_project(name: str, instructions: str = "") -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO projects (name, instructions) VALUES (?, ?)", (name, instructions)
    )
    await conn.commit()
    return await get_project(cursor.lastrowid)


async def list_projects() -> list[dict]:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM projects ORDER BY created_at DESC")
    return [dict(r) for r in await cursor.fetchall()]


async def get_project(project_id: int) -> dict | None:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    return _row(await cursor.fetchone())


async def update_project(
    project_id: int, name: str | None = None, instructions: str | None = None
) -> dict | None:
    conn = await get_connection()
    if name is not None:
        await conn.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project_id))
    if instructions is not None:
        await conn.execute(
            "UPDATE projects SET instructions = ? WHERE id = ?", (instructions, project_id)
        )
    await conn.commit()
    return await get_project(project_id)


async def delete_project(project_id: int) -> None:
    conn = await get_connection()
    await conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    await conn.commit()


# --- project files -----------------------------------------------------


async def add_project_file(
    project_id: int, filename: str, content_type: str, data: bytes
) -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO project_files (project_id, filename, content_type, data, size_bytes) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, filename, content_type, data, len(data)),
    )
    await conn.commit()
    return await get_project_file(cursor.lastrowid, include_data=False)


async def list_project_files(project_id: int) -> list[dict]:
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT id, project_id, filename, content_type, size_bytes, created_at "
        "FROM project_files WHERE project_id = ? ORDER BY created_at ASC",
        (project_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_project_file(file_id: int, include_data: bool = True) -> dict | None:
    conn = await get_connection()
    columns = "*" if include_data else "id, project_id, filename, content_type, size_bytes, created_at"
    cursor = await conn.execute(f"SELECT {columns} FROM project_files WHERE id = ?", (file_id,))
    return _row(await cursor.fetchone())


async def delete_project_file(file_id: int) -> None:
    conn = await get_connection()
    await conn.execute("DELETE FROM project_files WHERE id = ?", (file_id,))
    await conn.commit()


# --- chat attachments (Chat tab "attach a file", see main.py /chat/attachments) --


async def add_chat_attachment(filename: str, content_type: str, data: bytes) -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO chat_attachments (filename, content_type, data, size_bytes) VALUES (?, ?, ?, ?)",
        (filename, content_type, data, len(data)),
    )
    await conn.commit()
    return await get_chat_attachment(cursor.lastrowid, include_data=False)


async def get_chat_attachment(attachment_id: int, include_data: bool = True) -> dict | None:
    conn = await get_connection()
    columns = "*" if include_data else "id, filename, content_type, size_bytes, created_at"
    cursor = await conn.execute(f"SELECT {columns} FROM chat_attachments WHERE id = ?", (attachment_id,))
    return _row(await cursor.fetchone())


# --- conversations -------------------------------------------------------


async def create_conversation(
    tab: str, project_id: int | None = None, title: str = "New conversation", homework: bool = False
) -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO conversations (tab, project_id, title, homework) VALUES (?, ?, ?, ?)",
        (tab, project_id, title, int(homework)),
    )
    await conn.commit()
    return await get_conversation(cursor.lastrowid)


async def list_conversations(tab: str | None = None, project_id: int | None = None) -> list[dict]:
    conn = await get_connection()
    clauses, params = [], []
    if tab is not None:
        clauses.append("c.tab = ?")
        params.append(tab)
    if project_id is not None:
        clauses.append("c.project_id = ?")
        params.append(project_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    # `preview` (Memory History task: "short preview ... use a source-derived
    # preview when a title is simply 'New conversation'") -- the most recent
    # message's own text, correlated per-row rather than a second round trip
    # per conversation. Only its first ~160 chars are worth sending; the
    # frontend never needs the rest just to render a list-row preview.
    cursor = await conn.execute(
        f"""
        SELECT c.*,
            (SELECT substr(m.content, 1, 160) FROM messages m
             WHERE m.conversation_id = c.id ORDER BY m.id DESC LIMIT 1) AS preview
        FROM conversations c {where} ORDER BY c.updated_at DESC
        """,
        params,
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_conversation(conversation_id: int) -> dict | None:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    return _row(await cursor.fetchone())


async def rename_conversation(conversation_id: int, title: str) -> dict | None:
    conn = await get_connection()
    await conn.execute(
        "UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)
    )
    await conn.commit()
    return await get_conversation(conversation_id)


async def update_conversation(
    conversation_id: int,
    title: str | None = None,
    pinned: bool | None = None,
    schedule_label: str | None | Any = _UNSET,
    homework: bool | None = None,
) -> dict | None:
    """Partial update for the sidebar's Pinned/Scheduled actions, and for
    ChatWindow's Homework Mode toggle.

    schedule_label distinguishes "leave alone" (arg omitted, the _UNSET
    sentinel) from "clear it" (explicit None) -- title/pinned/homework don't
    need this since the UI never wants to set them to a false-y no-op value.
    """
    conn = await get_connection()
    if title is not None:
        await conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))
    if pinned is not None:
        await conn.execute(
            "UPDATE conversations SET pinned = ? WHERE id = ?", (int(pinned), conversation_id)
        )
    if schedule_label is not _UNSET:
        await conn.execute(
            "UPDATE conversations SET schedule_label = ? WHERE id = ?",
            (schedule_label, conversation_id),
        )
    if homework is not None:
        await conn.execute(
            "UPDATE conversations SET homework = ? WHERE id = ?", (int(homework), conversation_id)
        )
    await conn.commit()
    return await get_conversation(conversation_id)


async def touch_conversation(conversation_id: int) -> None:
    conn = await get_connection()
    await conn.execute(
        "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?", (conversation_id,)
    )
    await conn.commit()


async def delete_conversation(conversation_id: int) -> None:
    conn = await get_connection()
    await conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    await conn.commit()


# --- accounts held in Nova's name -----------------------------------------


async def upsert_account(service: str, username: str, url: str | None,
                         email: str | None, notes: str | None,
                         has_password: bool = False) -> dict:
    conn = await get_connection()
    await conn.execute(
        """
        INSERT INTO accounts (service, username, url, email, notes)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(service) DO UPDATE SET
            username   = excluded.username,
            -- COALESCE so re-saving with a field left blank keeps what was
            -- there. Editing one detail should not silently clear the rest.
            url        = COALESCE(excluded.url, accounts.url),
            email      = COALESCE(excluded.email, accounts.email),
            notes      = COALESCE(excluded.notes, accounts.notes),
            updated_at = datetime('now')
        """,
        (service, username, url, email, notes),
    )
    await conn.commit()
    async with conn.execute("SELECT * FROM accounts WHERE service = ?", (service,)) as cursor:
        row = await cursor.fetchone()
    result = dict(row) if row else {}
    result["has_password"] = has_password
    return result


async def list_accounts() -> list[dict]:
    conn = await get_connection()
    async with conn.execute("SELECT * FROM accounts ORDER BY service COLLATE NOCASE") as cursor:
        return [dict(r) for r in await cursor.fetchall()]


async def delete_account(service: str) -> bool:
    conn = await get_connection()
    cursor = await conn.execute("DELETE FROM accounts WHERE service = ?", (service,))
    await conn.commit()
    return cursor.rowcount > 0


# --- push subscriptions ---------------------------------------------------


async def upsert_push_subscription(endpoint: str, subscription: str, label: str | None) -> dict:
    """Register a device, or refresh the one already at this endpoint.

    ON CONFLICT rather than a delete-then-insert so `created_at` survives a
    re-subscribe -- the browser re-registers on its own schedule, and a device
    that silently reset its "registered since" date every few weeks would make
    the Settings list useless for answering "is my phone still set up?".
    """
    conn = await get_connection()
    await conn.execute(
        """
        INSERT INTO push_subscriptions (endpoint, subscription, label)
        VALUES (?, ?, ?)
        ON CONFLICT(endpoint) DO UPDATE SET
            subscription = excluded.subscription,
            label = COALESCE(excluded.label, push_subscriptions.label)
        """,
        (endpoint, subscription, label),
    )
    await conn.commit()
    async with conn.execute(
        "SELECT id, endpoint, label, created_at, last_sent_at FROM push_subscriptions WHERE endpoint = ?",
        (endpoint,),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else {}


async def list_push_subscriptions() -> list[dict]:
    conn = await get_connection()
    async with conn.execute(
        "SELECT id, endpoint, subscription, label, created_at, last_sent_at "
        "FROM push_subscriptions ORDER BY id"
    ) as cursor:
        return [dict(r) for r in await cursor.fetchall()]


async def delete_push_subscription(endpoint: str) -> None:
    conn = await get_connection()
    await conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    await conn.commit()


async def touch_push_subscriptions() -> None:
    conn = await get_connection()
    await conn.execute("UPDATE push_subscriptions SET last_sent_at = datetime('now')")
    await conn.commit()


# --- messages ------------------------------------------------------------


async def add_message(
    conversation_id: int,
    role: str,
    content: str,
    category: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    label: str | None = None,
    attachments: list[dict] | None = None,
) -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO messages (conversation_id, role, content, category, provider, model, label, attachments) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            conversation_id, role, content, category, provider, model, label,
            json.dumps(attachments) if attachments else None,
        ),
    )
    await conn.commit()
    result = await conn.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,))
    return _decode_message_attachments(_row(await result.fetchone()))


def _decode_message_attachments(message: dict | None) -> dict | None:
    """attachments is stored as a JSON string (see add_message) -- decode it
    back to a list here so every API response returns real objects, not a
    string the frontend would have to JSON.parse itself."""
    if message and message.get("attachments"):
        message["attachments"] = json.loads(message["attachments"])
    return message


async def list_messages(conversation_id: int) -> list[dict]:
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC", (conversation_id,)
    )
    return [_decode_message_attachments(dict(r)) for r in await cursor.fetchall()]


async def get_message(message_id: int) -> dict | None:
    """Single-row lookup by primary key -- used by memory.py's legacy
    fact-status migration to backfill a real `created_at` for Chroma entries
    written before that metadata field existed, by cross-referencing the
    same message_id SQLite has always kept as the source of truth."""
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
    return _decode_message_attachments(_row(await cursor.fetchone()))


# --- spend log -------------------------------------------------------------


async def record_spend(cost_usd: float, tokens: int, provider: str | None) -> None:
    conn = await get_connection()
    today = date_cls.today().isoformat()
    await conn.execute(
        "INSERT INTO spend_log (day, cost_usd, tokens, provider) VALUES (?, ?, ?, ?)",
        (today, cost_usd, tokens, provider),
    )
    await conn.commit()


async def spend_totals_for_day(day: str) -> tuple[float, int, int]:
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0), COALESCE(SUM(tokens), 0), COUNT(*) "
        "FROM spend_log WHERE day = ?",
        (day,),
    )
    total_cost, total_tokens, call_count = await cursor.fetchone()
    return float(total_cost), int(total_tokens), int(call_count)


# --- app settings (N.O.V.A. Settings > General/Voice) -----------------------


async def get_app_settings() -> dict[str, str]:
    conn = await get_connection()
    cursor = await conn.execute("SELECT key, value FROM app_settings")
    return {row["key"]: row["value"] for row in await cursor.fetchall()}


async def set_app_settings(values: dict[str, str]) -> None:
    conn = await get_connection()
    await conn.executemany(
        "INSERT INTO app_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        list(values.items()),
    )
    await conn.commit()


# --- disabled models (N.O.V.A. Settings > Models, local Ollama only) --------


async def list_disabled_models() -> set[str]:
    conn = await get_connection()
    cursor = await conn.execute("SELECT model_id FROM disabled_models")
    return {row["model_id"] for row in await cursor.fetchall()}


async def set_model_enabled(model_id: str, enabled: bool) -> None:
    conn = await get_connection()
    if enabled:
        await conn.execute("DELETE FROM disabled_models WHERE model_id = ?", (model_id,))
    else:
        await conn.execute(
            "INSERT OR IGNORE INTO disabled_models (model_id) VALUES (?)", (model_id,)
        )
    await conn.commit()


# --- MCP servers (N.O.V.A. Settings > MCP) ----------------------------------


async def list_mcp_servers(enabled_only: bool = False) -> list[dict]:
    conn = await get_connection()
    where = "WHERE enabled = 1" if enabled_only else ""
    cursor = await conn.execute(f"SELECT * FROM mcp_servers {where} ORDER BY created_at ASC")
    return [dict(r) for r in await cursor.fetchall()]


async def get_mcp_server(server_id: int) -> dict | None:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,))
    return _row(await cursor.fetchone())


async def create_mcp_server(
    name: str,
    command: str,
    args_json: str,
    env_json: str,
    transport: str = "stdio",
    url: str | None = None,
) -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO mcp_servers (name, command, args, env, transport, url) VALUES (?, ?, ?, ?, ?, ?)",
        (name, command, args_json, env_json, transport, url),
    )
    await conn.commit()
    return await get_mcp_server(cursor.lastrowid)


async def delete_mcp_server(server_id: int) -> None:
    conn = await get_connection()
    await conn.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
    await conn.commit()


async def set_mcp_oauth_client_info(server_id: int, client_info_json: str) -> None:
    conn = await get_connection()
    await conn.execute(
        "UPDATE mcp_servers SET oauth_client_info = ? WHERE id = ?", (client_info_json, server_id)
    )
    await conn.commit()


async def set_mcp_oauth_tokens(server_id: int, tokens_json: str | None) -> None:
    conn = await get_connection()
    await conn.execute("UPDATE mcp_servers SET oauth_tokens = ? WHERE id = ?", (tokens_json, server_id))
    await conn.commit()


async def set_mcp_server_enabled(server_id: int, enabled: bool) -> dict | None:
    conn = await get_connection()
    await conn.execute(
        "UPDATE mcp_servers SET enabled = ? WHERE id = ?", (int(enabled), server_id)
    )
    await conn.commit()
    return await get_mcp_server(server_id)


# --- Canvas assignments (nightly sync, see canvas_sync.py) ------------------


async def upsert_canvas_assignment(item: dict) -> dict:
    """Insert or update one assignment, keyed on canvas_id.

    Returns {"status": "new" | "due_changed" | "unchanged", "row": ...}. The
    caller uses that to decide what is worth telling the user about: a brand
    new assignment and a moved deadline both matter, a row that simply still
    exists does not.
    """
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT * FROM canvas_assignments WHERE canvas_id = ?", (item["canvas_id"],)
    )
    existing = _row(await cursor.fetchone())

    if existing is None:
        await conn.execute(
            """INSERT INTO canvas_assignments
                   (canvas_id, course_id, course_name, title, due_at, points, url, submitted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (item["canvas_id"], item["course_id"], item["course_name"], item["title"],
             item["due_at"], item.get("points"), item.get("url", ""), int(item.get("submitted", False))),
        )
        await conn.commit()
        cursor = await conn.execute("SELECT * FROM canvas_assignments WHERE canvas_id = ?", (item["canvas_id"],))
        return {"status": "new", "row": _row(await cursor.fetchone())}

    due_changed = (existing["due_at"] or "") != (item["due_at"] or "")
    await conn.execute(
        """UPDATE canvas_assignments
              SET course_name = ?, title = ?, due_at = ?, points = ?, url = ?,
                  submitted = ?, last_seen = datetime('now'),
                  due_changed_at = CASE WHEN ? THEN datetime('now') ELSE due_changed_at END
            WHERE canvas_id = ?""",
        (item["course_name"], item["title"], item["due_at"], item.get("points"),
         item.get("url", ""), int(item.get("submitted", False)), int(due_changed), item["canvas_id"]),
    )
    await conn.commit()
    cursor = await conn.execute("SELECT * FROM canvas_assignments WHERE canvas_id = ?", (item["canvas_id"],))
    return {"status": "due_changed" if due_changed else "unchanged", "row": _row(await cursor.fetchone())}


async def list_canvas_assignments(include_submitted: bool = False, limit: int = 300) -> list[dict]:
    conn = await get_connection()
    where = "" if include_submitted else "WHERE submitted = 0"
    cursor = await conn.execute(
        f"SELECT * FROM canvas_assignments {where} ORDER BY due_at IS NULL, due_at ASC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def mark_canvas_notified(canvas_ids: list[str]) -> None:
    if not canvas_ids:
        return
    conn = await get_connection()
    await conn.executemany(
        "UPDATE canvas_assignments SET notified_at = datetime('now') WHERE canvas_id = ?",
        [(cid,) for cid in canvas_ids],
    )
    await conn.commit()


# --- ACP agents (N.O.V.A. Settings > Agents, see acp.py) --------------------


async def list_acp_agents(enabled_only: bool = False) -> list[dict]:
    conn = await get_connection()
    where = "WHERE enabled = 1" if enabled_only else ""
    cursor = await conn.execute(f"SELECT * FROM acp_agents {where} ORDER BY created_at ASC")
    return [dict(r) for r in await cursor.fetchall()]


async def get_acp_agent(agent_id: int) -> dict | None:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM acp_agents WHERE id = ?", (agent_id,))
    return _row(await cursor.fetchone())


async def get_acp_agent_by_name(name: str) -> dict | None:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM acp_agents WHERE name = ? COLLATE NOCASE", (name,))
    return _row(await cursor.fetchone())


async def create_acp_agent(
    name: str, command: str, args_json: str, env_json: str, cwd: str | None = None
) -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO acp_agents (name, command, args, env, cwd) VALUES (?, ?, ?, ?, ?)",
        (name, command, args_json, env_json, cwd),
    )
    await conn.commit()
    return await get_acp_agent(cursor.lastrowid)


async def delete_acp_agent(agent_id: int) -> None:
    conn = await get_connection()
    await conn.execute("DELETE FROM acp_agents WHERE id = ?", (agent_id,))
    await conn.commit()


async def set_acp_agent_enabled(agent_id: int, enabled: bool) -> dict | None:
    conn = await get_connection()
    await conn.execute("UPDATE acp_agents SET enabled = ? WHERE id = ?", (int(enabled), agent_id))
    await conn.commit()
    return await get_acp_agent(agent_id)


# --- custom models (N.O.V.A. Settings > Models > Add Model) ----------------


async def list_custom_models(category: str | None = None, enabled_only: bool = False) -> list[dict]:
    conn = await get_connection()
    clauses, params = [], []
    if category is not None:
        clauses.append("category = ?")
        params.append(category)
    if enabled_only:
        clauses.append("enabled = 1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cursor = await conn.execute(f"SELECT * FROM custom_models {where} ORDER BY created_at ASC", params)
    return [dict(r) for r in await cursor.fetchall()]


async def get_custom_model(model_id: int) -> dict | None:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM custom_models WHERE id = ?", (model_id,))
    return _row(await cursor.fetchone())


async def create_custom_model(
    name: str, provider: str, model_id: str, category: str, api_base: str | None, api_key: str | None
) -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO custom_models (name, provider, model_id, category, api_base, api_key) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, provider, model_id, category, api_base, api_key),
    )
    await conn.commit()
    return await get_custom_model(cursor.lastrowid)


async def delete_custom_model(model_id: int) -> None:
    conn = await get_connection()
    await conn.execute("DELETE FROM custom_models WHERE id = ?", (model_id,))
    await conn.commit()


async def set_custom_model_enabled(model_id: int, enabled: bool) -> dict | None:
    conn = await get_connection()
    await conn.execute("UPDATE custom_models SET enabled = ? WHERE id = ?", (int(enabled), model_id))
    await conn.commit()
    return await get_custom_model(model_id)


# --- TTS voices (N.O.V.A. Settings > Voice) ---------------------------------


async def list_tts_voices() -> list[dict]:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM tts_voices ORDER BY created_at ASC")
    return [dict(r) for r in await cursor.fetchall()]


async def get_tts_voice(voice_id: int) -> dict | None:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM tts_voices WHERE id = ?", (voice_id,))
    return _row(await cursor.fetchone())


async def create_tts_voice(name: str, audio_filename: str) -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO tts_voices (name, audio_filename) VALUES (?, ?)", (name, audio_filename)
    )
    await conn.commit()
    return await get_tts_voice(cursor.lastrowid)


async def delete_tts_voice(voice_id: int) -> None:
    conn = await get_connection()
    await conn.execute("DELETE FROM tts_voices WHERE id = ?", (voice_id,))
    await conn.commit()


# --- workspace tasks (director/team orchestration) --------------------------


async def create_task(
    title: str,
    description: str = "",
    parent_id: int | None = None,
    team: str | None = None,
    role: str | None = None,
    conversation_id: int | None = None,
    writes_files: bool = False,
) -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO tasks (title, description, parent_id, team, role, conversation_id, writes_files) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (title, description, parent_id, team, role, conversation_id, int(writes_files)),
    )
    await conn.commit()
    task = await get_task(cursor.lastrowid)
    await add_task_activity(task["id"], "created", f"Task created: {title}")
    return task


async def get_task(task_id: int) -> dict | None:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    return _row(await cursor.fetchone())


async def list_tasks(parent_id: int | None | object = _UNSET, status: str | None = None) -> list[dict]:
    """`parent_id=_UNSET` (default) returns every task regardless of nesting
    (Workspace's flat task list, top-level and subtasks alike -- the UI
    groups by status/team itself). `parent_id=None` explicitly returns only
    top-level tasks (director-created requests, no subtasks). An integer
    returns that task's direct subtasks."""
    conn = await get_connection()
    clauses, params = [], []
    if parent_id is not _UNSET:
        if parent_id is None:
            clauses.append("parent_id IS NULL")
        else:
            clauses.append("parent_id = ?")
            params.append(parent_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cursor = await conn.execute(f"SELECT * FROM tasks {where} ORDER BY created_at DESC", params)
    return [dict(r) for r in await cursor.fetchall()]


async def update_task(task_id: int, **fields: Any) -> dict | None:
    """Arbitrary-column update, same pattern as agents.py's AgentJob.update_job
    -- callers pass only the columns that actually changed. Always bumps
    updated_at so Workspace's "latest meaningful update" / elapsed-time
    display has a real timestamp to show."""
    if not fields:
        return await get_task(task_id)
    conn = await get_connection()
    set_clause = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = datetime('now')"
    await conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", [*fields.values(), task_id])
    await conn.commit()
    row = await get_task(task_id)
    # A team job the user gave (a root task, not Nova's daily routines)
    # finishing or failing is worth a notification (app/notify.py).
    if row and fields.get("status") in ("done", "error") and row.get("parent_id") is None and row.get("team") != "everyday":
        try:
            import asyncio
            from . import notify
            ok = fields["status"] == "done"
            asyncio.create_task(notify.notify(
                "task", "Team job finished" if ok else "Team job hit a problem",
                (row.get("title") or "")[:160], tag=f"nova-task-{task_id}", view="workspace"))
        except Exception:  # noqa: BLE001
            pass
    return row


async def add_task_dependency(task_id: int, depends_on_id: int) -> None:
    conn = await get_connection()
    await conn.execute(
        "INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_id) VALUES (?, ?)",
        (task_id, depends_on_id),
    )
    await conn.commit()


async def get_task_graph(root_id: int) -> dict:
    """A root task, its subtasks, and every dependency edge between them.

    The Workspace constellation shows live *team* structure -- which role is
    working -- which is a different question from what actually blocks what.
    This is the plan's real shape, read from task_dependencies rather than
    inferred from status.
    """
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT * FROM tasks WHERE id = ? OR parent_id = ? ORDER BY id ASC", (root_id, root_id)
    )
    tasks = [dict(r) for r in await cursor.fetchall()]
    if not tasks:
        return {"nodes": [], "edges": []}

    ids = [t["id"] for t in tasks]
    placeholders = ",".join("?" * len(ids))
    cursor = await conn.execute(
        f"SELECT task_id, depends_on_id FROM task_dependencies "
        f"WHERE task_id IN ({placeholders}) AND depends_on_id IN ({placeholders})",
        (*ids, *ids),
    )
    edges = [{"from": r["depends_on_id"], "to": r["task_id"]} for r in await cursor.fetchall()]
    return {
        "nodes": [
            {
                "id": t["id"], "title": t["title"], "status": t["status"],
                "team": t["team"], "role": t["role"], "is_root": t["id"] == root_id,
                "error": t.get("error"),
            }
            for t in tasks
        ],
        "edges": edges,
    }


async def get_task_dependencies(task_id: int) -> list[int]:
    conn = await get_connection()
    cursor = await conn.execute("SELECT depends_on_id FROM task_dependencies WHERE task_id = ?", (task_id,))
    return [row["depends_on_id"] for row in await cursor.fetchall()]


async def get_task_dependents(task_id: int) -> list[int]:
    """Inverse of get_task_dependencies -- tasks that are waiting on this one."""
    conn = await get_connection()
    cursor = await conn.execute("SELECT task_id FROM task_dependencies WHERE depends_on_id = ?", (task_id,))
    return [row["task_id"] for row in await cursor.fetchall()]


async def add_task_activity(task_id: int, kind: str, message: str) -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO task_activity (task_id, kind, message) VALUES (?, ?, ?)", (task_id, kind, message)
    )
    await conn.commit()
    row_cursor = await conn.execute("SELECT * FROM task_activity WHERE id = ?", (cursor.lastrowid,))
    return _row(await row_cursor.fetchone())


async def get_task_activity(task_id: int) -> list[dict]:
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT * FROM task_activity WHERE task_id = ? ORDER BY created_at DESC", (task_id,)
    )
    return [dict(r) for r in await cursor.fetchall()]


# --- Knowledge (distilled facts, see knowledge.py) --------------------------


async def upsert_knowledge(row: dict) -> dict:
    """Store one learned statement, or fold it into the existing one.

    Re-learning something already known is the common case, not an error: the
    same fact comes up across months of conversations. Those hits bump
    times_seen and last_seen_at instead of creating another node, and a
    statement first heard from the assistant is allowed to be *upgraded* to
    confirmed when the user later says it themselves -- never the reverse.
    """
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT * FROM knowledge WHERE fingerprint = ?", (row["fingerprint"],)
    )
    existing = await cursor.fetchone()
    if existing:
        promote = row.get("status") == "confirmed" and existing["status"] != "confirmed"
        await conn.execute(
            """UPDATE knowledge
               SET times_seen = times_seen + 1,
                   last_seen_at = datetime('now'),
                   status = CASE WHEN ? THEN 'confirmed' ELSE status END,
                   source_role = CASE WHEN ? THEN ? ELSE source_role END
             WHERE id = ?""",
            (promote, promote, row.get("source_role", "user"), existing["id"]),
        )
        await conn.commit()
        cursor = await conn.execute("SELECT * FROM knowledge WHERE id = ?", (existing["id"],))
        return dict(await cursor.fetchone())

    cursor = await conn.execute(
        """INSERT INTO knowledge
             (conversation_id, message_id, subject, statement, category, status,
              source_role, fingerprint)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row.get("conversation_id"),
            row.get("message_id"),
            row["subject"],
            row["statement"],
            row.get("category", "fact"),
            row.get("status", "unconfirmed"),
            row.get("source_role", "user"),
            row["fingerprint"],
        ),
    )
    await conn.commit()
    cursor = await conn.execute("SELECT * FROM knowledge WHERE id = ?", (cursor.lastrowid,))
    return dict(await cursor.fetchone())


async def list_knowledge(limit: int = 500, conversation_id: int | None = None) -> list[dict]:
    conn = await get_connection()
    if conversation_id is None:
        cursor = await conn.execute(
            "SELECT * FROM knowledge ORDER BY last_seen_at DESC LIMIT ?", (limit,)
        )
    else:
        cursor = await conn.execute(
            "SELECT * FROM knowledge WHERE conversation_id = ? ORDER BY last_seen_at DESC LIMIT ?",
            (conversation_id, limit),
        )
    return [dict(r) for r in await cursor.fetchall()]


async def delete_knowledge(knowledge_id: int) -> bool:
    conn = await get_connection()
    cursor = await conn.execute("DELETE FROM knowledge WHERE id = ?", (knowledge_id,))
    await conn.commit()
    return cursor.rowcount > 0


async def update_knowledge(knowledge_id: int, statement: str, fingerprint: str) -> dict | None:
    """The user's correction of a learned statement. What they wrote is
    confirmed and theirs, whoever first said it. Raises ValueError when the
    corrected statement is one Nova already knows."""
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT id FROM knowledge WHERE fingerprint = ? AND id != ?", (fingerprint, knowledge_id)
    )
    if await cursor.fetchone():
        raise ValueError("Nova already knows that.")
    cursor = await conn.execute(
        "UPDATE knowledge SET statement = ?, fingerprint = ?, status = 'confirmed', source_role = 'user', "
        "last_seen_at = datetime('now') WHERE id = ?",
        (statement, fingerprint, knowledge_id),
    )
    await conn.commit()
    if cursor.rowcount == 0:
        return None
    cursor = await conn.execute("SELECT * FROM knowledge WHERE id = ?", (knowledge_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def count_knowledge() -> int:
    conn = await get_connection()
    cursor = await conn.execute("SELECT COUNT(*) AS n FROM knowledge")
    return (await cursor.fetchone())["n"]


async def spend_by_provider(since_day: str) -> list[dict]:
    """Per-provider totals from a day onward, newest activity first."""
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT provider, COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost_usd, "
        "COALESCE(SUM(tokens), 0) AS tokens, MAX(created_at) AS last_used "
        "FROM spend_log WHERE day >= ? GROUP BY provider ORDER BY calls DESC",
        (since_day,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def spend_by_day(since_day: str) -> list[dict]:
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT day, COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost_usd, "
        "COALESCE(SUM(tokens), 0) AS tokens "
        "FROM spend_log WHERE day >= ? GROUP BY day ORDER BY day DESC",
        (since_day,),
    )
    return [dict(r) for r in await cursor.fetchall()]


# --- User Profile & Academic Hub Helpers ---

async def get_user_profile() -> dict:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM user_profile WHERE id = 1")
    row = await cursor.fetchone()
    if not row:
        await conn.execute("INSERT OR IGNORE INTO user_profile (id, name) VALUES (1, 'Student')")
        await conn.commit()
        cursor = await conn.execute("SELECT * FROM user_profile WHERE id = 1")
        row = await cursor.fetchone()
    return dict(row) if row else {"id": 1, "name": "Student", "school": "", "major": "", "graduation_year": "", "timezone": "", "onboarding_completed": 0}


async def update_user_profile(**fields) -> dict:
    conn = await get_connection()
    allowed = {"name", "school", "major", "graduation_year", "timezone", "onboarding_completed"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if updates:
        clauses = [f"{k} = ?" for k in updates]
        values = list(updates.values())
        values.append(1)
        await conn.execute(f"UPDATE user_profile SET {', '.join(clauses)}, updated_at = datetime('now') WHERE id = ?", tuple(values))
        await conn.commit()
    return await get_user_profile()


async def list_courses() -> list[dict]:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM courses ORDER BY code ASC")
    courses = [dict(r) for r in await cursor.fetchall()]

    
    for c in courses:
        code_prefix = c.get("code", "")
        asgn_cur = await conn.execute(
            "SELECT count(*), min(due_at) FROM canvas_assignments WHERE course_name LIKE ?",
            (f"{code_prefix}%",)
        )
        asgn_row = await asgn_cur.fetchone()
        if asgn_row:
            c["assignment_count"] = asgn_row[0] or 0
            c["next_due"] = asgn_row[1]
        else:
            c["assignment_count"] = 0
            c["next_due"] = None
    return courses


async def get_course(course_id: int) -> dict | None:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def create_course(code: str, name: str, instructor: str = "", schedule: str = "", portal_type: str = "manual", portal_url: str = "", color: str = "#3b82f6") -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO courses (code, name, instructor, schedule, portal_type, portal_url, color) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (code, name, instructor, schedule, portal_type, portal_url, color)
    )
    await conn.commit()
    return await get_course(cursor.lastrowid)


async def update_course(course_id: int, **fields) -> dict | None:
    conn = await get_connection()
    allowed = {"code", "name", "instructor", "schedule", "portal_type", "portal_url", "color"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if updates:
        clauses = [f"{k} = ?" for k in updates]
        values = list(updates.values())
        values.append(course_id)
        await conn.execute(f"UPDATE courses SET {', '.join(clauses)}, updated_at = datetime('now') WHERE id = ?", tuple(values))
        await conn.commit()
    return await get_course(course_id)


async def delete_course(course_id: int) -> bool:
    conn = await get_connection()
    cursor = await conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
    await conn.commit()
    return cursor.rowcount > 0


async def add_syllabus(course_id: int, filename: str, raw_text: str = "", parsed_json: str = "{}") -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO syllabi (course_id, filename, raw_text, parsed_json) VALUES (?, ?, ?, ?)",
        (course_id, filename, raw_text, parsed_json)
    )
    await conn.commit()
    c = await conn.execute("SELECT * FROM syllabi WHERE id = ?", (cursor.lastrowid,))
    return dict(await c.fetchone())


async def list_syllabi(course_id: int | None = None) -> list[dict]:
    conn = await get_connection()
    if course_id is not None:
        cursor = await conn.execute("SELECT * FROM syllabi WHERE course_id = ? ORDER BY id DESC", (course_id,))
    else:
        cursor = await conn.execute("SELECT * FROM syllabi ORDER BY id DESC")
    return [dict(r) for r in await cursor.fetchall()]


async def list_obsidian_vaults() -> list[dict]:
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM obsidian_vaults ORDER BY created_at ASC")
    return [dict(r) for r in await cursor.fetchall()]


async def add_obsidian_vault(name: str, path: str, auto_sync: int = 1) -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO obsidian_vaults (name, path, auto_sync) VALUES (?, ?, ?) ON CONFLICT(path) DO UPDATE SET name = excluded.name, auto_sync = excluded.auto_sync",
        (name, path, auto_sync)
    )
    await conn.commit()
    c = await conn.execute("SELECT * FROM obsidian_vaults WHERE path = ?", (path,))
    return dict(await c.fetchone())


async def delete_obsidian_vault(vault_id: int) -> bool:
    conn = await get_connection()
    cursor = await conn.execute("DELETE FROM obsidian_vaults WHERE id = ?", (vault_id,))
    await conn.commit()
    return cursor.rowcount > 0


async def list_study_notes(course_id: int | None = None) -> list[dict]:
    conn = await get_connection()
    if course_id is not None:
        cursor = await conn.execute("SELECT * FROM study_notes WHERE course_id = ? ORDER BY updated_at DESC", (course_id,))
    else:
        cursor = await conn.execute("SELECT * FROM study_notes ORDER BY updated_at DESC")
    return [dict(r) for r in await cursor.fetchall()]


async def create_study_note(title: str, content: str = "", course_id: int | None = None, source_type: str = "text", ocr_raw: str = "", file_path: str = "", obsidian_note_path: str = "") -> dict:
    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO study_notes (title, content, course_id, source_type, ocr_raw, file_path, obsidian_note_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (title, content, course_id, source_type, ocr_raw, file_path, obsidian_note_path)
    )
    await conn.commit()
    c = await conn.execute("SELECT * FROM study_notes WHERE id = ?", (cursor.lastrowid,))
    return dict(await c.fetchone())


async def update_study_note(note_id: int, **fields) -> dict | None:
    conn = await get_connection()
    allowed = {"title", "content", "course_id", "source_type", "ocr_raw", "file_path", "obsidian_note_path"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if updates:
        clauses = [f"{k} = ?" for k in updates]
        values = list(updates.values())
        values.append(note_id)
        await conn.execute(f"UPDATE study_notes SET {', '.join(clauses)}, updated_at = datetime('now') WHERE id = ?", tuple(values))
        await conn.commit()
    cursor = await conn.execute("SELECT * FROM study_notes WHERE id = ?", (note_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def delete_study_note(note_id: int) -> bool:
    conn = await get_connection()
    cursor = await conn.execute("DELETE FROM study_notes WHERE id = ?", (note_id,))
    await conn.commit()
    return cursor.rowcount > 0


# --- Learned Homework Procedures (Self-Healing Procedural Memory) -------------


async def get_learned_procedure(signature: str) -> dict | None:
    """Retrieve a previously learned interaction recipe for a novel widget or portal modality."""
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT * FROM learned_homework_procedures WHERE widget_signature = ?", (signature,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    res = dict(row)
    try:
        res["recipe"] = json.loads(res["recipe_json"])
    except Exception:
        res["recipe"] = {}
    return res


async def save_learned_procedure(
    portal_pattern: str,
    widget_signature: str,
    widget_type: str,
    instruction_summary: str,
    recipe: dict,
    success: bool = True
) -> dict:
    """Save or update a learned procedure recipe so Nova can execute it automatically in the future."""
    conn = await get_connection()
    recipe_json = json.dumps(recipe)
    cursor = await conn.execute(
        "SELECT * FROM learned_homework_procedures WHERE widget_signature = ?", (widget_signature,)
    )
    existing = await cursor.fetchone()
    if existing:
        new_times = existing["times_used"] + 1
        new_rate = (existing["success_rate"] * existing["times_used"] + (1.0 if success else 0.0)) / new_times
        await conn.execute(
            """UPDATE learned_homework_procedures
               SET recipe_json = ?,
                   instruction_summary = ?,
                   times_used = ?,
                   success_rate = ?,
                   updated_at = datetime('now')
               WHERE widget_signature = ?""",
            (recipe_json, instruction_summary, new_times, new_rate, widget_signature)
        )
        await conn.commit()
        cursor = await conn.execute(
            "SELECT * FROM learned_homework_procedures WHERE widget_signature = ?", (widget_signature,)
        )
        res = dict(await cursor.fetchone())
        res["recipe"] = recipe
        return res

    await conn.execute(
        """INSERT INTO learned_homework_procedures
             (portal_pattern, widget_signature, widget_type, instruction_summary, recipe_json, times_used, success_rate)
           VALUES (?, ?, ?, ?, ?, 1, ?)""",
        (portal_pattern, widget_signature, widget_type, instruction_summary, recipe_json, 1.0 if success else 0.0)
    )
    await conn.commit()
    cursor = await conn.execute(
        "SELECT * FROM learned_homework_procedures WHERE widget_signature = ?", (widget_signature,)
    )
    res = dict(await cursor.fetchone())
    res["recipe"] = recipe
    return res


async def list_learned_procedures() -> list[dict]:
    """List all autonomous interaction recipes Nova has discovered and mastered."""
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT * FROM learned_homework_procedures ORDER BY times_used DESC, updated_at DESC"
    )
    rows = await cursor.fetchall()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["recipe"] = json.loads(d["recipe_json"])
        except Exception:
            d["recipe"] = {}
        results.append(d)
    return results


async def list_custom_tabs() -> list[dict]:
    """List all custom user/Nova-designed UI tabs."""
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT * FROM custom_tabs ORDER BY created_at ASC"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def save_custom_tab(
    tab_id: str,
    title: str,
    icon: str = "Sparkles",
    description: str = "",
    content_type: str = "widget",
    html_content: str = "",
) -> dict:
    """Save or update a custom UI tab."""
    conn = await get_connection()
    await conn.execute(
        """INSERT INTO custom_tabs (id, title, icon, description, content_type, html_content)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             title = excluded.title,
             icon = excluded.icon,
             description = excluded.description,
             content_type = excluded.content_type,
             html_content = excluded.html_content""",
        (tab_id, title, icon, description, content_type, html_content)
    )
    await conn.commit()
    cursor = await conn.execute("SELECT * FROM custom_tabs WHERE id = ?", (tab_id,))
    return dict(await cursor.fetchone())


async def delete_custom_tab(tab_id: str) -> bool:
    """Delete a custom UI tab."""
    conn = await get_connection()
    cursor = await conn.execute("DELETE FROM custom_tabs WHERE id = ?", (tab_id,))
    await conn.commit()
    return cursor.rowcount > 0


DEFAULT_CONNECTORS = [
    {
        "id": "github",
        "name": "GitHub (Zero-API)",
        "category": "deployment",
        "auth_type": "zero_api",
        "description": "Direct Git CLI & SSH zero-cost repository push and synchronization.",
        "config_json": "{\"remote\":\"origin\",\"branch\":\"main\"}",
        "enabled": 1,
    },
    {
        "id": "vercel",
        "name": "Vercel (Zero-API)",
        "category": "deployment",
        "auth_type": "zero_api",
        "description": "Instant zero-API deployment via Vercel CLI or automated Git triggers.",
        "config_json": "{\"deploy_cmd\":\"npx vercel --prod --yes\"}",
        "enabled": 1,
    },
    {
        "id": "netlify",
        "name": "Netlify (Zero-API)",
        "category": "deployment",
        "auth_type": "zero_api",
        "description": "Zero-API static & SSR website deployment via Netlify CLI.",
        "config_json": "{\"deploy_cmd\":\"npx netlify deploy --prod\"}",
        "enabled": 1,
    },
    {
        "id": "replit",
        "name": "Replit (Zero-API)",
        "category": "deployment",
        "auth_type": "zero_api",
        "description": "Zero-API project export and cloud workspace mirror.",
        "config_json": "{\"export_type\":\"zip_and_git\"}",
        "enabled": 1,
    },
    {
        "id": "lovable",
        "name": "Lovable UI (Zero-API)",
        "category": "deployment",
        "auth_type": "zero_api",
        "description": "Full-stack React & Tailwind component design sync to Lovable.",
        "config_json": "{\"export_type\":\"component_tree\"}",
        "enabled": 1,
    },
    {
        "id": "obsidian",
        "name": "Obsidian Vault (Local FileSync)",
        "category": "academic",
        "auth_type": "zero_api",
        "description": "Local zero-API Markdown note sync directly into your Obsidian vault.",
        "config_json": "{\"auto_link\":true}",
        "enabled": 1,
    },
]


async def list_custom_connectors() -> list[dict]:
    """List all connectors (both built-in zero-API connectors and user custom connectors)."""
    conn = await get_connection()
    cursor = await conn.execute("SELECT * FROM custom_connectors ORDER BY category ASC, name ASC")
    rows = await cursor.fetchall()
    if not rows:
        # Seed defaults
        for c in DEFAULT_CONNECTORS:
            await conn.execute(
                """INSERT OR IGNORE INTO custom_connectors (id, name, category, auth_type, description, config_json, enabled)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (c["id"], c["name"], c["category"], c["auth_type"], c["description"], c["config_json"], c["enabled"])
            )
        await conn.commit()
        cursor = await conn.execute("SELECT * FROM custom_connectors ORDER BY category ASC, name ASC")
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def save_custom_connector(
    conn_id: str,
    name: str,
    category: str = "deployment",
    auth_type: str = "zero_api",
    description: str = "",
    config_json: str = "{}",
    enabled: int = 1,
) -> dict:
    """Save or update a connector configuration."""
    conn = await get_connection()
    await conn.execute(
        """INSERT INTO custom_connectors (id, name, category, auth_type, description, config_json, enabled)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             name = excluded.name,
             category = excluded.category,
             auth_type = excluded.auth_type,
             description = excluded.description,
             config_json = excluded.config_json,
             enabled = excluded.enabled""",
        (conn_id, name, category, auth_type, description, config_json, enabled)
    )
    await conn.commit()
    cursor = await conn.execute("SELECT * FROM custom_connectors WHERE id = ?", (conn_id,))
    return dict(await cursor.fetchone())

