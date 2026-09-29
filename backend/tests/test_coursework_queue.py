import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from app import config, operator_store as store, coursework_queue as queue

URL = 'https://fixture.test/courses/1/assignments/'

class DurableQueue(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(config, 'DB_PATH', Path(self.tmp.name) / 'test.db')
        p.start(); self.addCleanup(p.stop)
        p = patch.object(queue.coursework, 'read_json', AsyncMock(return_value={'id': '7'}))
        p.start(); self.addCleanup(p.stop)

    def create(self, **kw):
        return queue.create_queue([{'url': URL + str(i)} for i in (1, 2)], account_id='7', authorize_submission=True, **kw)

    async def test_requires_explicit_authorization(self):
        with self.assertRaises(ValueError):
            queue.create_queue([{'url': URL+'1'}], account_id='7')

    async def test_unknown_does_not_block_independent_work_or_replay(self):
        job = self.create()
        run = AsyncMock(side_effect=[{'status': 'unknown'}, {'status': 'completed'}])
        with patch.object(queue.pilot, 'run_autopilot_assignment', run):
            result = await queue.run_queue(job['id'])
            await queue.run_queue(job['id'])
        self.assertEqual(run.await_count, 2)
        self.assertEqual([x['state'] for x in result['items']], ['unknown', 'completed'])

    async def test_attempts_are_bounded(self):
        job = self.create(max_attempts=2)
        run = AsyncMock(return_value={'status': 'blocked'})
        with patch.object(queue.pilot, 'run_autopilot_assignment', run):
            for _ in range(3):
                await queue.run_queue(job['id'])
        self.assertEqual(run.await_count, 4)

    async def test_restart_never_replays_executing_item(self):
        job = self.create()
        job['items'][0]['state'] = 'executing'
        store.put(queue.KIND, job['id'], job)
        run = AsyncMock(return_value={'status': 'completed'})
        with patch.object(queue.pilot, 'run_autopilot_assignment', run):
            result = await queue.run_queue(job['id'])
        self.assertEqual(run.await_count, 1)
        self.assertEqual(result['items'][0]['state'], 'unknown')

    async def test_cancel_persists_and_requires_explicit_resume(self):
        job = self.create()
        queue.cancel_queue(job['id'])
        with patch.object(queue.pilot, 'run_autopilot_assignment', AsyncMock()) as run:
            result = await queue.run_queue(job['id'])
        self.assertEqual(result['state'], 'cancelled')
        run.assert_not_awaited()

    async def test_reconciliation_requires_matching_canvas_receipt(self):
        job = self.create()
        job['items'][0]['state'] = 'unknown'
        store.put(queue.KIND, job['id'], job)
        row = {'id': 1, 'course_id': 1, 'submission': {'assignment_id': 1, 'user_id': 7, 'workflow_state': 'submitted', 'submitted_at': '2026-09-28T00:00:00Z'}}
        with patch.object(queue.coursework, 'read_json', AsyncMock(side_effect=[{'id': 7}, row])):
            result = await queue.reconcile_item(job['id'], job['items'][0]['id'])
        self.assertEqual(result['items'][0]['state'], 'completed')

    async def test_no_receipt_leaves_unknown(self):
        job = self.create()
        job['items'][0]['state'] = 'unknown'
        store.put(queue.KIND, job['id'], job)
        with patch.object(queue.coursework, 'read_json', AsyncMock(return_value={'id': 7})):
            result = await queue.reconcile_item(job['id'], job['items'][0]['id'])
        self.assertEqual(result['items'][0]['state'], 'unknown')

    async def test_changed_account_does_not_execute(self):
        job = self.create()
        with patch.object(queue.coursework, 'read_json', AsyncMock(return_value={'id': 8})), patch.object(queue.pilot, 'run_autopilot_assignment', AsyncMock()) as run:
            result = await queue.run_queue(job['id'])
        run.assert_not_awaited()
        self.assertTrue(all(i['state'] == 'auth_required' for i in result['items']))


class QueueAutopilotContract(unittest.TestCase):
    def test_autopilot_accepts_the_queue_submission_guard(self):
        import inspect
        self.assertIn('submission_guard', inspect.signature(queue.pilot.run_autopilot_assignment).parameters)
