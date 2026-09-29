import unittest
import tempfile
from pathlib import Path
from app import config
from unittest.mock import AsyncMock, patch
from playwright.async_api import async_playwright
from app import coursework_autopilot as pilot


class AutopilotBrowser(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        data_patch = patch.object(config, "DB_PATH", Path(self.temp.name) / "fixture.db")
        data_patch.start()
        self.addCleanup(data_patch.stop)
        self.driver = await async_playwright().start()
        self.browser = await self.driver.chromium.launch(headless=True)
        self.tab = await self.browser.new_page()
        self.html = '''<div class="prompt">What is 2 + 2?</div><input type="text">
        <button onclick="window.submits=(window.submits||0)+1;document.querySelector('#feedback').innerText=window.feedback">Submit</button>
        <p id="feedback"></p>'''
        await self.tab.route('https://fixture.test/**', lambda r: r.fulfill(body=self.html, content_type='text/html'))
        self.patches = [
            patch.object(pilot.browser_control, 'page', AsyncMock(return_value=self.tab)),
            patch.object(pilot.operator_workflows, 'require_running'),
            patch.object(pilot.operator_workflows, 'stopped', return_value=False),
            patch.object(pilot, 'solve_math_problem', return_value={'success': True, 'answer': '4'}),
            patch.object(pilot.asyncio, 'sleep', AsyncMock()),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.driver.stop()

    async def run_assignment(self, feedback='', mode='autopilot'):
        await self.tab.add_init_script('window.feedback=' + __import__('json').dumps(feedback))
        return await pilot.run_autopilot_assignment({'url': 'https://fixture.test/assignment'}, mode=mode)

    async def test_tutor_leaves_answers_and_submission_untouched(self):
        result = await self.run_assignment(mode='tutor')
        self.assertEqual(result['status'], 'guidance_ready')
        self.assertEqual(await self.tab.locator('input').input_value(), '')
        self.assertIsNone(await self.tab.evaluate('window.submits'))

    async def test_missing_feedback_is_unknown_not_completed(self):
        result = await self.run_assignment()
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['questions_solved'], 0)
        self.assertEqual(await self.tab.evaluate('window.submits'), 1)

    async def test_incorrect_answer_is_not_counted(self):
        result = await self.run_assignment('Your answer is incorrect')
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['questions_solved'], 0)

    async def test_one_correct_answer_is_not_assignment_completion(self):
        result = await self.run_assignment('Your answer is correct')
        self.assertEqual(result['status'], 'attempted')
        self.assertEqual(result['questions_solved'], 1)

    async def test_explicit_receipt_completes_assignment(self):
        result = await self.run_assignment('Your answer is correct\nAssignment complete')
        self.assertEqual(result['status'], 'completed')

    async def test_stop_prevents_final_submission(self):
        with patch.object(pilot.operator_workflows, 'require_running', side_effect=[None, None, ValueError('Stopped')]), patch.object(pilot.operator_workflows, 'stopped', return_value=True):
            result = await self.run_assignment()
        self.assertEqual(result['status'], 'cancelled')
        self.assertIsNone(await self.tab.evaluate('window.submits'))

    async def test_uncertain_submission_is_not_replayed_in_a_new_run(self):
        await self.run_assignment()
        result = await self.run_assignment()
        self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(await self.tab.evaluate('window.submits'))
