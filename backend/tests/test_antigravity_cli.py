import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('antigravity_checks', Path(__file__).resolve().parents[1] / 'app' / 'antigravity_cli.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

class AntigravityChecks(unittest.TestCase):
    def test_unverified_login_refuses_launch(self):
        with patch.dict(os.environ, {'NOVA_ANTIGRAVITY_CLI_VERIFIED': '0'}), patch.object(Path, 'is_file', return_value=True), patch.object(cli, 'dotenv_values', return_value={'NOVA_ANTIGRAVITY_CLI_VERIFIED': '1'}):
            with self.assertRaises(RuntimeError):
                cli.command('hello')

    def test_plan_mode_preserves_multiline_input_without_shell(self):
        with patch.dict(os.environ, {'NOVA_ANTIGRAVITY_CLI_VERIFIED': '1'}), patch.object(Path, 'is_file', return_value=True):
            prompt = 'First line\nSecond line with "quotes" and $variables'
            command = cli.command(prompt)
            self.assertEqual(command[-1], prompt)
            self.assertEqual(command[command.index('--mode') + 1], 'plan')
            # agy warns that disabling slash commands also disables --mode plan.
            self.assertNotIn('--disable-slash-commands', command)
            self.assertNotIn('--dangerously-skip-permissions', command)
            with self.assertRaises(ValueError):
                cli.command('a' * 24001)

    def test_api_credentials_removed_case_insensitively(self):
        self.assertEqual(cli.environment({'Path': 'keep', 'google_api_key': 'secret', 'GEMINI_API_KEY': 'secret', 'GOOGLE_GENAI_USE_VERTEXAI': 'true', 'OPENAI_API_KEY': 'secret'}), {'Path': 'keep'})

    def test_quoted_persisted_verification_marker_is_accepted(self):
        with patch.dict(os.environ, {'NOVA_ANTIGRAVITY_CLI_VERIFIED': "'1'"}), patch.object(Path, 'is_file', return_value=True):
            self.assertTrue(cli.availability()['available'])

    def test_persisted_marker_used_when_process_marker_absent(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'home', return_value=Path('test-user')), patch.object(Path, 'is_file', return_value=True), patch.object(cli, 'dotenv_values', return_value={'NOVA_ANTIGRAVITY_CLI_VERIFIED': '1'}):
            self.assertTrue(cli.availability()['available'])
