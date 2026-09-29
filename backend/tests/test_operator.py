import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app import config, coursework, operator_store as store, operator_workflows as workflows, operator_resources, nova_tools, agent_loop

URL = 'https://school.example/courses/12/assignments/34'


class OperatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.object(config, 'DB_PATH', Path(self.temp.name) / 'test.db')
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def draft(self, **changes):
        return store.create('draft', url=URL, packet={'assignment_id': '34', 'user_id': '7'}, submission_type='online_text_entry',
                            text='My answer', files=[], status='prepared', **changes)

    async def test_task_cannot_claim_success_without_evidence(self):
        task = await workflows.task('start', workflow='Canvas', url=URL)
        with self.assertRaisesRegex(ValueError, 'verified'):
            await workflows.task('finish', task_id=task['id'], success=True)
        workflows.record_step(task['id'], {'verified': True})
        workflows.record_step(task['id'], {'verified': False})
        with self.assertRaisesRegex(ValueError, 'verified'):
            await workflows.task('finish', task_id=task['id'], success=True)

    async def test_playbook_retains_working_steps_after_failure(self):
        task = await workflows.task('start', workflow='Canvas', url=URL)
        workflows.record_step(task['id'], {'verified': True})
        await workflows.task('finish', task_id=task['id'], success=True, steps=['Open assignment'], landmarks=['Start Assignment'])
        task2 = await workflows.task('start', workflow='Canvas', url=URL)
        self.assertEqual(task2['playbook']['steps'], ['Open assignment'])
        await workflows.task('finish', task_id=task2['id'], success=False, failures=['Login expired'])
        book = store.listing('playbook')[0]
        self.assertEqual(book['success_rate'], 0.5)
        self.assertEqual(book['steps'], ['Open assignment'])

    async def test_abort_is_latched_across_tools(self):
        workflows.stop()
        with patch.object(nova_tools, '_write_file', AsyncMock()) as write:
            result = await nova_tools.execute('write_file', {'path': 'test.txt', 'content': 'oops'}, 'full')
            self.assertFalse(result['ok'])
            write.assert_not_called()
        workflows.resume()
        self.assertFalse(workflows.stopped())

    async def test_corner_aborts_without_retry(self):
        item = await workflows.task('start', workflow='Desktop')
        with patch.object(workflows.desktop, 'capture_screenshot', AsyncMock(return_value=b'before')), \
             patch.object(workflows.desktop, 'click', AsyncMock(side_effect=ValueError('mouse corner'))) as click:
            with self.assertRaises(ValueError):
                await workflows.step(item['id'], 'click', 'Opened app', x=4, y=5)
            self.assertTrue(workflows.stopped())
            self.assertEqual(click.await_count, 1)
            with self.assertRaisesRegex(ValueError, 'stopped'):
                await workflows.step(item['id'], 'click', 'Opened app', x=4, y=5)

    async def test_ambiguous_vision_never_becomes_success(self):
        with patch.object(workflows.providers, 'describe_screen', AsyncMock(return_value='Probably worked')):
            self.assertFalse((await workflows.assess(b'png', 'Saved'))['verified'])

    async def test_budget_is_capped_and_idempotent(self):
        budget = await workflows.ledger('create', title='Work', budget_cents=1000, end_at=time.time()+60)
        args = dict(budget_id=budget['id'], amount_cents=700, direction='expense', receipt='receipt-1', entry_id='entry-1')
        await workflows.ledger('record', **args)
        duplicate = await workflows.ledger('record', **args)
        self.assertEqual(duplicate['expenses_cents'], 700)
        with self.assertRaisesRegex(ValueError, 'cap'):
            await workflows.ledger('record', **{**args, 'entry_id': 'entry-2'})

    async def test_expired_budget_refuses_spending(self):
        budget = await workflows.ledger('create', budget_cents=1000, end_at=time.time()+60)
        budget['end_at'] = time.time()-1
        store.put('budget', budget['id'], budget)
        with self.assertRaises(ValueError):
            await workflows.ledger('record', budget_id=budget['id'], amount_cents=1, direction='expense', receipt='x', entry_id='x')

    async def test_submit_requires_specific_unexpired_grant(self):
        draft = self.draft()
        coursework.grant(URL.replace('/34', '/35'), True)
        with patch.object(coursework, '_form', AsyncMock()) as form:
            with self.assertRaisesRegex(ValueError, 'authorization'):
                await coursework.submit(draft['id'])
            form.assert_not_called()
        coursework.grant(URL, True, hours=0)
        with self.assertRaisesRegex(ValueError, 'authorization'):
            await coursework.submit(draft['id'])

    async def test_unknown_submission_reconciles_without_second_post(self):
        draft = self.draft()
        draft['status'] = 'unknown'
        store.put('draft', draft['id'], draft)
        coursework.grant(URL, True, user_id=7)
        receipt = {'user_id': 7, 'assignment_id': 34, 'submitted_at': '2026-09-23', 'submission_type': 'online_text_entry', 'body': '<p>My answer</p>'}
        with patch.object(coursework, 'current_receipt', AsyncMock(return_value=receipt)), patch.object(coursework, '_form', AsyncMock()) as form:
            result = await coursework.submit(draft['id'])
            self.assertEqual(result['status'], 'submitted')
            form.assert_not_called()

    async def test_unknown_unmatched_submission_is_not_retried(self):
        draft = self.draft()
        draft['status'] = 'unknown'
        store.put('draft', draft['id'], draft)
        coursework.grant(URL, True, user_id=7)
        with patch.object(coursework, 'current_receipt', AsyncMock(return_value={'user_id': 7})), patch.object(coursework, '_form', AsyncMock()) as form:
            with self.assertRaisesRegex(ValueError, 'unknown'):
                await coursework.submit(draft['id'])
            form.assert_not_called()

    async def test_failed_post_persists_unknown_outcome(self):
        draft = self.draft()
        coursework.grant(URL, True, user_id=7)
        packet = {'locked': False, 'submission_types': ['online_text_entry']}
        with patch.object(coursework, 'current_receipt', AsyncMock(return_value={'user_id': 7})), \
             patch.object(coursework, 'assignment', AsyncMock(return_value=packet)), \
             patch.object(coursework.browser_control, 'page', AsyncMock()), \
             patch.object(coursework, '_form', AsyncMock(side_effect=TimeoutError('Network lost'))):
            with self.assertRaises(TimeoutError):
                await coursework.submit(draft['id'])
        self.assertEqual(store.get('draft', draft['id'])['status'], 'unknown')

    async def test_wrong_assignment_receipt_is_rejected(self):
        draft = self.draft()
        receipt = {'assignment_id': 35, 'submitted_at': 'now', 'submission_type': 'online_text_entry', 'body': 'My answer'}
        self.assertFalse(coursework.matches(draft, receipt))

    async def test_changed_file_refused_before_form(self):
        file = Path(self.temp.name) / 'essay.txt'
        file.write_text('Original')
        draft = self.draft()
        draft.update(submission_type='online_upload', files=[coursework.fingerprint(file)])
        store.put('draft', draft['id'], draft)
        file.write_text('Changed')
        coursework.grant(URL, True, user_id=7)
        with patch.object(coursework, 'current_receipt', AsyncMock(return_value={'user_id': 7})), \
             patch.object(coursework, 'assignment', AsyncMock(return_value={'locked': False, 'submission_types': ['online_upload']})), \
             patch.object(coursework, '_form', AsyncMock()) as form:
            with self.assertRaisesRegex(ValueError, 'changed'):
                await coursework.submit(draft['id'])
            form.assert_not_called()

    async def test_cookie_read_reports_login_instead_of_html(self):
        request = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(status=302, headers={'content-type': 'text/html'})))
        tab = SimpleNamespace(context=SimpleNamespace(request=request))
        with patch.object(coursework.canvas, 'configured', return_value=False), patch.object(coursework.browser_control, 'page', AsyncMock(return_value=tab)):
            with self.assertRaisesRegex(ValueError, 'Sign into'):
                await coursework.read_json(URL, 'courses/12/assignments/34')

    async def test_private_download_address_rejected(self):
        with patch.object(operator_resources.socket, 'getaddrinfo', return_value=[(0,0,0,'',('127.0.0.1',80))]):
            with self.assertRaisesRegex(ValueError, 'private'):
                await operator_resources.public_url('http://localhost/private')

    async def test_registry_and_approval_contract(self):
        for schema in nova_tools.operator_tools.SCHEMAS:
            self.assertIn(schema['function']['name'], nova_tools._EXECUTORS)
        self.assertTrue(nova_tools.needs_approval('operator_commit', 'full'))
        self.assertTrue(nova_tools.refused_by_autonomy('coursework_submit', 'readonly'))

    async def test_model_failure_after_action_does_not_replay(self):
        result = SimpleNamespace(provider='ollama', model='test', label='test')
        counter = 0
        async def stream(*args):
            nonlocal counter
            counter += 1
            if counter == 1:
                yield 'calls', [{'id':'1','type':'function','function':{'name':'write_file','arguments':'{}'}}]
            else:
                raise RuntimeError('provider disconnected')
        with patch.object(agent_loop, '_stream_once', stream), patch.object(agent_loop, '_run_tool', AsyncMock(return_value={'ok':True,'result':{}})) as run, patch.object(agent_loop, '_announce', AsyncMock()):
            events = [event async for event in agent_loop._run_with_tools(result, [], [], {}, 'full')]
        self.assertEqual(run.await_count, 1)
        self.assertTrue(any('rather than replaying' in event.get('content','') for event in events))

    async def test_reserved_purchases_share_cap_and_settle_once(self):
        budget = await workflows.ledger('create', budget_cents=1000, end_at=time.time()+60)
        async def reserve(key):
            return await workflows.ledger('reserve', budget_id=budget['id'], amount_cents=700, reservation_id=key)
        results = await asyncio.gather(reserve('one'), reserve('two'), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, ValueError) for r in results), 1)
        await workflows.ledger('record', budget_id=budget['id'], amount_cents=650, direction='expense', receipt='paid', entry_id='paid', reservation_id='one')
        result = await workflows.ledger('status', budget_id=budget['id'])
        self.assertEqual(result['expenses_cents'], 650)
        self.assertEqual(result['reservations']['one']['status'], 'settled')
        with self.assertRaisesRegex(ValueError, 'different transaction'):
            await workflows.ledger('record', budget_id=budget['id'], amount_cents=10, direction='expense', receipt='paid', entry_id='paid')

    async def test_over_budget_purchase_never_clicks(self):
        budget = await workflows.ledger('create', budget_cents=100, end_at=time.time()+60)
        with patch.object(workflows, 'step', AsyncMock()) as step:
            with self.assertRaisesRegex(ValueError, 'cap'):
                await workflows.purchase(budget['id'], 101, 'buy', task_id='task', action='click', expected='Purchased')
            step.assert_not_called()

    async def test_new_draft_cannot_bypass_unknown_submission(self):
        draft = self.draft()
        coursework.grant(URL, True, user_id=7)
        store.put('attempt', URL + ':7', {'draft_id': 'older-draft', 'status': 'unknown'})
        with patch.object(coursework, 'current_receipt', AsyncMock(return_value={'user_id': 7})), patch.object(coursework, '_form', AsyncMock()) as form:
            with self.assertRaisesRegex(ValueError, 'Another draft'):
                await coursework.submit(draft['id'])
            form.assert_not_called()

    async def test_changed_canvas_identity_prevents_submission(self):
        draft = self.draft()
        coursework.grant(URL, True, user_id=7)
        with patch.object(coursework, 'current_receipt', AsyncMock(return_value={'user_id': 8})), patch.object(coursework, '_form', AsyncMock()) as form:
            with self.assertRaisesRegex(ValueError, 'account changed'):
                await coursework.submit(draft['id'])
            form.assert_not_called()

    async def test_uploaded_file_receipt_checks_content(self):
        file = Path(self.temp.name) / 'essay.txt'
        file.write_bytes(b'NEW!')
        draft = self.draft()
        draft.update(submission_type='online_upload', files=[coursework.fingerprint(file)])
        receipt = {'user_id': 7, 'assignment_id': 34, 'submitted_at': 'now', 'submission_type': 'online_upload',
                   'attachments': [{'id': 42, 'display_name': 'essay.txt', 'size': 4}]}
        response = SimpleNamespace(status=200, body=AsyncMock(return_value=b'OLD!'))
        tab = SimpleNamespace(context=SimpleNamespace(request=SimpleNamespace(get=AsyncMock(return_value=response))))
        with patch.object(coursework.browser_control, 'page', AsyncMock(return_value=tab)):
            self.assertFalse(await coursework.verify_receipt(draft, receipt))
            response.body.return_value = b'NEW!'
            self.assertTrue(await coursework.verify_receipt(draft, receipt))

    async def test_desktop_key_waits_for_submission_lock(self):
        lock = asyncio.Lock()
        with patch.object(workflows, 'action_lock', lock), patch.dict(nova_tools._EXECUTORS, {'desktop_key': AsyncMock(return_value={})}):
            async with lock:
                action = asyncio.create_task(nova_tools.execute('desktop_key', {'keys': 'enter'}, 'full'))
                await asyncio.sleep(0)
                self.assertFalse(action.done())
                workflows.stop()
            self.assertFalse((await action)['ok'])

    async def test_outer_failure_after_tool_attempt_does_not_fallback(self):
        candidate = SimpleNamespace(provider='ollama', model='test', label='test')
        async def broken(*args):
            yield {'type': 'tool_call', 'name': 'write_file', 'status': 'running'}
            raise RuntimeError('tool result serialization failed')
        with patch.object(nova_tools, 'autonomy_level', AsyncMock(return_value='full')), \
             patch.object(agent_loop, '_collect_tools', AsyncMock(return_value=([{}], {}))), \
             patch.object(agent_loop, '_run_with_tools', broken):
            events = [event async for event in agent_loop.run([candidate, candidate], [])]
        self.assertEqual(sum(e['type'] == 'meta' for e in events), 1)
        self.assertTrue(any('not replayed' in e.get('content', '') for e in events))

    async def test_no_progress_after_a_tool_attempt_falls_back_anyway(self):
        # ProviderNoProgressError is the one failure that *should* still
        # reroute even though a mutating tool was attempted (see its own
        # docstring): a model that spun on tools with zero narration left
        # nothing a retry could duplicate. Found live: Token Harbor's
        # DeepSeek called browser_act 24 times this way on a homework task.
        from app import providers
        candidate = SimpleNamespace(provider='ollama', model='test', label='test')
        async def broken(*args):
            yield {'type': 'tool_call', 'name': 'browser_act', 'status': 'running'}
            raise providers.ProviderNoProgressError('test: called tools without explaining')
        async def local_fallback_stub(*args):
            yield {'type': 'token', 'content': 'local fallback answer'}
        with patch.object(nova_tools, 'autonomy_level', AsyncMock(return_value='full')), \
             patch.object(agent_loop, '_collect_tools', AsyncMock(return_value=([{}], {}))), \
             patch.object(agent_loop, '_run_with_tools', broken), \
             patch.object(agent_loop, '_local_fallback', local_fallback_stub):
            events = [event async for event in agent_loop.run([candidate, candidate], [])]
        # Both candidates were actually tried (a meta event per attempt) --
        # it did NOT take the "stopped after an action was attempted" exit
        # after the first one, the way a plain error does.
        self.assertEqual(sum(e['type'] == 'meta' for e in events), 2)
        self.assertTrue(any(e['type'] == 'reroute' for e in events))
        self.assertFalse(any('stopped after an action was attempted' in e.get('content', '') for e in events))

    async def test_step_budget_with_no_narration_raises_no_progress(self):
        # Same shape as test_a_denied_write_never_touches_the_file in
        # test_file_tool_loop.py: fake _stream_once returns a tool call every
        # step and never any text, all the way to MAX_STEPS.
        result = SimpleNamespace(provider='custom', model='test', label='Cheap Model',
                                 category='homework', custom_model_row_id=1)
        call = {'id': 'c', 'type': 'function', 'function': {'name': 'browser_act', 'arguments': '{}'}}
        async def fake_stream(*args):
            yield 'calls', [call]
        from app import providers
        with patch.object(agent_loop, '_stream_once', fake_stream), \
             patch.object(agent_loop, '_run_tool', AsyncMock(return_value={'ok': True, 'result': {}})), \
             patch.object(agent_loop, '_announce', AsyncMock()):
            with self.assertRaises(providers.ProviderNoProgressError):
                async for _ in agent_loop._run_with_tools(
                        result, [{'role': 'user', 'content': 'do the homework'}],
                        [{'type': 'function', 'function': {'name': 'browser_act', 'parameters': {}}}],
                        {}, 'full'):
                    pass

    async def test_step_budget_with_narration_does_not_raise(self):
        # The same loop, but the model explains itself along the way -- the
        # normal "stopped after N steps, say keep going" ending stays as-is.
        result = SimpleNamespace(provider='custom', model='test', label='Claude',
                                 category='homework', custom_model_row_id=None)
        call = {'id': 'c', 'type': 'function', 'function': {'name': 'browser_act', 'arguments': '{}'}}
        async def fake_stream(*args):
            yield 'token', 'Clicking KEEP GOING.'
            yield 'calls', [call]
        with patch.object(agent_loop, '_stream_once', fake_stream), \
             patch.object(agent_loop, '_run_tool', AsyncMock(return_value={'ok': True, 'result': {}})), \
             patch.object(agent_loop, '_announce', AsyncMock()):
            events = [event async for event in agent_loop._run_with_tools(
                    result, [{'role': 'user', 'content': 'do the homework'}],
                    [{'type': 'function', 'function': {'name': 'browser_act', 'parameters': {}}}],
                    {}, 'full')]
        self.assertTrue(any('Stopped after' in e.get('content', '') for e in events))

    async def test_purchase_rechecks_expiry_after_vision_and_holds_reservation(self):
        budget = await workflows.ledger('create', budget_cents=1000, end_at=time.time()+60)
        task = await workflows.task('start', workflow='Purchase')
        async def resolve(*args):
            with self.assertRaises(ValueError):
                await workflows.ledger('release', budget_id=budget['id'], reservation_id='buy', receipt='cancelled')
            current = store.get('budget', budget['id'])
            current['end_at'] = time.time()-1
            store.put('budget', budget['id'], current)
            return 10, 20
        with patch.object(workflows.desktop, 'capture_screenshot', AsyncMock(return_value=b'png')), \
             patch.object(workflows.providers, 'resolve_screen_target', resolve), \
             patch.object(workflows.desktop, 'click', AsyncMock()) as click:
            with self.assertRaisesRegex(ValueError, 'expired'):
                await workflows.purchase(budget['id'], 700, 'buy', task_id=task['id'], action='click', expected='Purchased', target='Buy')
            click.assert_not_called()
        self.assertEqual(store.get('budget', budget['id'])['reservations']['buy']['status'], 'unknown')

    async def test_reconciliation_preserves_other_draft_barrier(self):
        draft = self.draft()
        draft['status'] = 'unknown'
        store.put('draft', draft['id'], draft)
        key = URL + ':7'
        store.put('attempt', key, {'draft_id': 'newer', 'status': 'unknown'})
        receipt = {'user_id': 7, 'assignment_id': 34, 'submitted_at': 'now', 'submission_type': 'online_text_entry', 'body': 'My answer'}
        with patch.object(coursework, 'current_receipt', AsyncMock(return_value=receipt)):
            self.assertEqual((await coursework.status(draft['id']))['status'], 'submitted')
        self.assertEqual(store.get('attempt', key)['draft_id'], 'newer')

    async def test_cancelled_native_typing_latches_stop(self):
        started = asyncio.Event()
        async def typing(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()
        with patch.object(nova_tools.desktop, 'type_text', typing):
            operation = asyncio.create_task(nova_tools.execute('desktop_type', {'text': 'Long text'}, 'full'))
            await started.wait()
            operation.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await operation
        self.assertTrue(workflows.stopped())
