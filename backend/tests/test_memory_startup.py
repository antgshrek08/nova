import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


class MemoryStartupTests(unittest.IsolatedAsyncioTestCase):
    def load(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'app/memory.py').read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if getattr(n, 'name', '') in ('_collection_sync', 'recall_for_chat')]
        env = {'asyncio': asyncio, 'logging': logging, '__name__': __name__, '_client': None,
               '_collection': None, '_initialization_lock': threading.Lock(),
               'config': SimpleNamespace(CHROMA_DIR='test-memory')}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'memory.py', 'exec'), env)
        return env

    def test_parallel_startup_creates_one_client(self):
        env = self.load()
        collection = object()
        def create(**kwargs):
            time.sleep(.02)
            return SimpleNamespace(get_or_create_collection=lambda name: collection)
        factory = Mock(side_effect=create)
        env['chromadb'] = SimpleNamespace(PersistentClient=factory)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: env['_collection_sync'](), range(16)))
        self.assertEqual(factory.call_count, 1)
        self.assertTrue(all(result is collection for result in results))

    async def test_recall_failure_does_not_fail_chat(self):
        env = self.load()
        env['search'] = AsyncMock(side_effect=KeyError('chroma startup'))
        self.assertEqual(await env['recall_for_chat']('hello', 123), [])

    async def test_successful_recall_is_preserved(self):
        env = self.load()
        env['search'] = AsyncMock(return_value=[{'content': 'Remembered preference'}])
        self.assertEqual(len(await env['recall_for_chat']('hello', 123)), 1)
        env['search'].assert_awaited_once_with('hello', exclude_conversation_id=123)
