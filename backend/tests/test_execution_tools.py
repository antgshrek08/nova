import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, AsyncMock
from playwright.async_api import async_playwright

from app import browser_control, config, execution_tools


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_edit_verification_and_path_boundary(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, 'get_workspace_dir', return_value=Path(directory)):
            Path(directory, 'example.txt').write_text('before')
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                await execution_tools.execute('write_file', {'path': 'example.txt', 'content': 'after'})
            before = await execution_tools.execute('read_file', {'path': 'example.txt'})
            await execution_tools.execute('write_file', {'path': 'example.txt', 'content': 'after', 'fingerprint': before['fingerprint']})
            after = await execution_tools.execute('read_file', {'path': 'example.txt'})
            self.assertEqual(after['content'], 'after')
            with self.assertRaises(ValueError):
                await execution_tools.execute('read_file', {'path': '../outside.txt'})

    async def test_command_exit_code_and_output(self):
        result = await execution_tools.execute('run_command', {'command': "Write-Output 'NOVA_COMMAND_OK'; exit 3"})
        self.assertEqual(result['exit_code'], 3)
        self.assertIn('NOVA_COMMAND_OK', result['output'])


class BrowserIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_navigation_fill_click_and_inspection(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<title>Nova browser test</title><label>Name<input id="name"></label><button onclick="document.getElementById(\'result\').textContent=\'Hello \'+document.getElementById(\'name\').value">Submit</button><p id="result"></p>')
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        # The Edge path, pinned: with Onyx now the default backend, this test
        # launched the user's real Onyx from inside the suite. The Onyx path is
        # covered by tests/test_onyx_backend.py without launching anything.
        async def edge():
            return 'edge', ''
        driver = await async_playwright().start()
        browser = await driver.chromium.launch(headless=True)
        tab = await browser.new_page()
        page_patch = patch.object(browser_control, 'page', AsyncMock(return_value=tab))
        page_patch.start()
        visibility_patch = patch.object(browser_control, 'visibility', AsyncMock(return_value='hidden'))
        visibility_patch.start()
        original = browser_control._backend
        browser_control._backend = edge
        try:
            result = await browser_control.perform('navigate', url=f'http://127.0.0.1:{server.server_port}')
            self.assertEqual(result['title'], 'Nova browser test')
            await browser_control.perform('fill', selector='#name', text='Nova')
            result = await browser_control.perform('click', selector='button')
            self.assertIn('Hello Nova', result['page'])
        finally:
            browser_control._backend = original
            page_patch.stop()
            visibility_patch.stop()
            await browser.close()
            await driver.stop()
            await asyncio.to_thread(server.shutdown)
            server.server_close()
