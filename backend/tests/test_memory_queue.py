import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock

import aiosqlite


class MemoryQueueChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await aiosqlite.connect(":memory:")
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY, conversation_id INTEGER, role TEXT, content TEXT, category TEXT, created_at TEXT)")
        await self.conn.execute("INSERT INTO messages VALUES(1, 1, 'user', 'original', 'general', 'today')")
        await self.conn.commit()
        async def get_message(mid):
            cursor = await self.conn.execute("SELECT * FROM messages WHERE id=?", (mid,))
            row = await cursor.fetchone()
            return dict(row) if row else None
        package = types.ModuleType("memory_queue_checks")
        package.__path__ = []
        package.db = types.SimpleNamespace(get_connection=AsyncMock(return_value=self.conn), get_message=get_message)
        package.memory = types.SimpleNamespace(add_message=AsyncMock(), update_content=AsyncMock(), delete=AsyncMock())
        sys.modules[package.__name__] = package
        spec = importlib.util.spec_from_file_location("memory_queue_checks.memory_queue", Path(__file__).resolve().parents[1] / "app/memory_queue.py")
        self.queue = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.queue)
        self.memory = package.memory
        await self.queue.initialize()

    async def asyncTearDown(self):
        await self.queue.stop()
        await self.conn.close()

    async def wait_processed(self):
        async with asyncio.timeout(2):
            while True:
                row = await (await self.conn.execute("SELECT pending FROM memory_index_jobs WHERE message_id=1")).fetchone()
                if row and row[0] == 0:
                    return
                await asyncio.sleep(.01)

    async def test_enqueue_survives_worker_start_and_indexes_once(self):
        await self.queue.enqueue(1)
        await self.queue.enqueue(1)
        self.memory.add_message.assert_not_awaited()
        await self.queue.start()
        await self.wait_processed()
        self.memory.add_message.assert_awaited_once()

    async def test_forgotten_fact_is_not_restored_by_retry(self):
        await self.queue.enqueue(1)
        await self.queue.edit("message-1", forgotten=True)
        await self.queue.enqueue(1)
        await self.queue.start()
        await self.wait_processed()
        self.memory.add_message.assert_not_awaited()
        self.memory.delete.assert_awaited()

    async def test_correction_remains_authoritative_on_indexing(self):
        await self.queue.edit("message-1", content="corrected")
        await self.queue.start()
        await self.wait_processed()
        self.assertEqual(self.memory.add_message.await_args.args[3], "corrected")
        self.assertEqual((await self.queue.db.get_message(1))["content"], "original")
