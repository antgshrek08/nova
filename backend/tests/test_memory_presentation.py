import ast
import asyncio
from pathlib import Path
import unittest


class MemoryPresentationTests(unittest.IsolatedAsyncioTestCase):
    def load(self, collection=None):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'app/memory.py').read_text(encoding='utf-8'))
        names = {'_looks_like_question', 'is_operational_error', 'classify_fact_status', 'list_recent'}
        nodes = [n for n in tree.body if getattr(n, 'name', None) in names]
        env = {'asyncio': asyncio, '_QUESTION_WORDS': {'what', 'how'}, 'OPERATIONAL_ERROR_PREFIX': '⚠️', '_collection_sync': lambda: collection}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'memory.py', 'exec'), env)
        return env

    def test_requests_are_not_confirmed_facts(self):
        classify = self.load()['classify_fact_status']
        for text in ('hello', 'Write a Python function', 'Please fix this', 'Show me the layout', 'Say pineapple', 'Reply with banana', 'use codex to make a program'):
            self.assertEqual(classify('user', text), 'question')
        self.assertEqual(classify('user', 'My favorite color is green'), 'confirmed')
        self.assertEqual(classify('assistant', 'Your favorite color is blue'), 'unconfirmed')

    async def test_recent_is_sorted_before_limiting(self):
        class Collection:
            def count(self): return 3
            def get(self, include, ids=None):
                records = [('old', '2020-01-01', 'hello'), ('new', '2026-09-12', 'Write a function'), ('middle', '2025-01-01', 'I prefer green')]
                records = [r for r in records if ids is None or r[0] in ids]
                return {'ids': [r[0] for r in records], 'metadatas': [{'created_at': r[1], 'role': 'user', 'fact_status': 'confirmed'} for r in records], 'documents': [r[2] for r in records]}
        rows = await self.load(Collection())['list_recent'](2)
        self.assertEqual([r['id'] for r in rows], ['new', 'middle'])
        self.assertEqual(rows[0]['fact_status'], 'question')
