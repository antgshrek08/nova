"""Durable, single-worker indexing. Chat persistence never waits for ONNX."""
import asyncio
import logging
import time

from . import db, memory

_task = None
_lock = asyncio.Lock()
_wake = asyncio.Event()
_log = logging.getLogger(__name__)


async def initialize():
    conn = await db.get_connection()
    await conn.execute("""CREATE TABLE IF NOT EXISTS memory_index_jobs (
        message_id INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
        content_override TEXT, forgotten INTEGER NOT NULL DEFAULT 0,
        pending INTEGER NOT NULL DEFAULT 1, attempts INTEGER NOT NULL DEFAULT 0,
        retry_at REAL NOT NULL DEFAULT 0, last_error TEXT
    )""")
    await conn.commit()


async def enqueue(message_id):
    conn = await db.get_connection()
    await conn.execute("INSERT OR IGNORE INTO memory_index_jobs(message_id) VALUES (?)", (message_id,))
    await conn.commit()
    _wake.set()


async def edit(memory_id, content=None, forgotten=False):
    if not memory_id.startswith("message-") or not memory_id[8:].isdigit():
        raise ValueError("Memory has no message provenance")
    message_id = int(memory_id[8:])
    async with _lock:
        if not await db.get_message(message_id):
            raise ValueError("The source message no longer exists")
        conn = await db.get_connection()
        await conn.execute("""INSERT INTO memory_index_jobs(message_id, content_override, forgotten)
            VALUES (?, ?, ?) ON CONFLICT(message_id) DO UPDATE SET
            content_override=excluded.content_override, forgotten=excluded.forgotten,
            pending=1, attempts=0, retry_at=0, last_error=NULL""", (message_id, content, int(forgotten)))
        await conn.commit()
        if forgotten:
            await memory.delete(memory_id)
        elif content is not None:
            await memory.update_content(memory_id, content)
    _wake.set()


async def _run():
    while True:
        _wake.clear()
        async with _lock:
            conn = await db.get_connection()
            cursor = await conn.execute("SELECT * FROM memory_index_jobs WHERE pending=1 AND retry_at<=? ORDER BY message_id LIMIT 1", (time.time(),))
            row = await cursor.fetchone()
            if row:
                job = dict(row)
                message_id = job["message_id"]
                try:
                    message = await db.get_message(message_id)
                    if message and not job["forgotten"]:
                        content = job["content_override"] if job["content_override"] is not None else message["content"]
                        await memory.add_message(message_id, message["conversation_id"], message["role"], content, category=message["category"], created_at=message["created_at"])
                        if job["content_override"] is not None:
                            await memory.update_content(f"message-{message_id}", content)
                        if not await db.get_message(message_id):
                            await memory.delete(f"message-{message_id}")
                    else:
                        await memory.delete(f"message-{message_id}")
                    await conn.execute("UPDATE memory_index_jobs SET pending=0, last_error=NULL WHERE message_id=?", (message_id,))
                except Exception as exc:
                    delay = min(300, 2 ** min(job["attempts"] + 1, 8))
                    await conn.execute("UPDATE memory_index_jobs SET attempts=attempts+1, retry_at=?, last_error=? WHERE message_id=?", (time.time() + delay, type(exc).__name__, message_id))
                    _log.warning("Memory indexing will retry message %s: %s", message_id, type(exc).__name__)
                await conn.commit()
        if row:
            await asyncio.sleep(.05)
        else:
            try:
                await asyncio.wait_for(_wake.wait(), 2)
            except asyncio.TimeoutError:
                pass


async def start():
    global _task
    await initialize()
    if _task is None or _task.done():
        _task = asyncio.create_task(_run(), name="nova-memory-index")


async def stop():
    if _task:
        async with _lock:
            _task.cancel()
            await asyncio.gather(_task, return_exceptions=True)
