"""Exercise Canvas form adapters in a real browser against a local fixture.

All school URLs are intercepted; these tests never contact a real institution.
The form adapter is also checked with real browser input on named controls.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from playwright.async_api import async_playwright
from app import config, coursework

URL = 'https://school.example/courses/12/assignments/34'
PAGE = '''<!doctype html><html><body>
<a class="submit_assignment_link" href="#" onclick="document.querySelector('#submit_assignment').hidden=false">Start Assignment</a>
<form id="submit_assignment" hidden onsubmit="event.preventDefault();window.submitted=true">
<button type="button">Text Entry</button><button type="button">Website URL</button><button type="button">File Upload</button>
<textarea name="submission[body]"></textarea><input name="submission[url]"><input type="file" multiple>
<button type="submit">Submit Assignment</button></form></body></html>'''


class BrowserForms(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patcher = patch.object(config, 'DB_PATH', Path(self.temp.name) / 'test.db')
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.driver = await async_playwright().start()
        self.browser = await self.driver.chromium.launch(headless=True)
        self.tab = await self.browser.new_page()
        await self.tab.route('https://school.example/**', lambda route: route.fulfill(body=PAGE, content_type='text/html'))
        coursework.grant(URL, True, user_id=7)
        profile = patch.object(coursework, 'read_json', AsyncMock(return_value={'id': 7}))
        profile.start()
        self.addCleanup(profile.stop)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.driver.stop()

    async def click(self, tab, label, authorize=None):
        if authorize:
            await authorize()
        name = next(name for name in ('Start Assignment', 'File Upload', 'Website URL', 'Text Entry', 'Submit Assignment') if name in label)
        await tab.get_by_text(name, exact=True).click()

    async def test_text_form_preserves_unicode(self):
        draft = {'packet': {'user_id': '7'}, 'id': 'fixture', 'url': URL, 'submission_type': 'online_text_entry', 'text': 'Résumé — π = 3.14\nSecond line.'}
        with patch.object(coursework, 'visible_click', self.click):
            await coursework._form(self.tab, draft)
        self.assertEqual(await self.tab.locator('textarea').input_value(), draft['text'])
        self.assertTrue(await self.tab.evaluate('window.submitted'))

    async def test_actual_named_controls_submit_fixture(self):
        draft = {'packet': {'user_id': '7'}, 'id': 'named', 'url': URL, 'submission_type': 'online_text_entry', 'text': 'Checked draft'}
        await coursework._form(self.tab, draft)
        self.assertTrue(await self.tab.evaluate('window.submitted'))
        self.assertEqual(await self.tab.locator('textarea').input_value(), 'Checked draft')

    async def test_actual_click_rechecks_authorization(self):
        await self.tab.goto(URL)
        await coursework.visible_click(self.tab, 'Start Assignment')
        async def denied():
            raise coursework.CourseworkError('Authorization revoked')
        with self.assertRaisesRegex(coursework.CourseworkError, 'Authorization revoked'):
            await coursework.visible_click(self.tab, 'Submit Assignment', authorize=denied)
        self.assertFalse(await self.tab.evaluate('Boolean(window.submitted)'))

    async def test_file_form_uploads_the_real_file(self):
        file = Path(self.temp.name) / 'essay.txt'
        file.write_text('Coursework')
        draft = {'packet': {'user_id': '7'}, 'id':'filefixture', 'url':URL, 'submission_type':'online_upload', 'files':[coursework.fingerprint(file)]}
        with patch.object(coursework, 'visible_click', self.click):
            await coursework._form(self.tab, draft)
        self.assertEqual(await self.tab.locator('input[type=file]').evaluate('(el) => el.files[0].name'), 'essay.txt')
        self.assertTrue(await self.tab.evaluate('window.submitted'))

    async def test_url_form(self):
        draft = {'packet': {'user_id': '7'}, 'id':'urlfixture', 'url':URL, 'submission_type':'online_url', 'submission_url':'https://example.org/work'}
        with patch.object(coursework, 'visible_click', self.click):
            await coursework._form(self.tab, draft)
        self.assertEqual(await self.tab.locator('input[name="submission[url]"]').input_value(), draft['submission_url'])

    async def test_file_changed_during_navigation_is_never_submitted(self):
        file = Path(self.temp.name) / 'essay.txt'
        file.write_bytes(b'original')
        draft = {'packet': {'user_id': '7'}, 'id': 'changed', 'url': URL, 'submission_type': 'online_upload', 'files': [coursework.fingerprint(file)]}
        async def click(tab, label, authorize=None):
            await self.click(tab, label, authorize)
            if 'File Upload' in label:
                file.write_bytes(b'modified')
        with patch.object(coursework, 'visible_click', click):
            with self.assertRaisesRegex(ValueError, 'changed'):
                await coursework._form(self.tab, draft)
        self.assertFalse(await self.tab.evaluate('Boolean(window.submitted)'))

    async def test_form_check_does_not_submit_or_fill(self):
        packet = {'url':URL,'title':'Practice assignment','locked':False,'submission_types':['online_upload'],'submission':{}}
        with patch.object(coursework, 'assignment', AsyncMock(return_value=packet)), \
             patch.object(coursework.browser_control, 'page', AsyncMock(return_value=self.tab)), \
             patch.object(coursework, 'visible_click', self.click):
            result = await coursework.check_form(URL)
        self.assertFalse(result['submitted'])
        self.assertEqual(result['fields']['file_inputs'], 1)
        self.assertEqual(await self.tab.locator('textarea').input_value(), '')
        self.assertFalse(await self.tab.evaluate('Boolean(window.submitted)'))
