import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

root = Path(__file__).resolve().parents[1] / 'app'
pkg = types.ModuleType('preview_checks')
pkg.__path__ = [str(root)]
sys.modules[pkg.__name__] = pkg
config = types.ModuleType('preview_checks.config')
sys.modules[config.__name__] = config
spec = importlib.util.spec_from_file_location('preview_checks.dev_server', root / 'dev_server.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class PreviewTests(unittest.TestCase):
    def test_next_uses_project_dependency_and_loopback(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(preview.shutil, 'which', return_value='node.exe'):
            project = Path(folder)
            (project / 'package.json').write_text('{"dependencies":{"next":"15"}}')
            entry = project / 'node_modules/next/dist/bin/next'
            entry.parent.mkdir(parents=True)
            entry.touch()
            args = preview.command(project)
            self.assertEqual(args, ['node.exe', str(entry), 'dev', '--hostname', '127.0.0.1', '--port', '3000'])

    def test_missing_dependencies_report_error(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(preview.shutil, 'which', return_value='node.exe'):
            project = Path(folder)
            (project / 'package.json').write_text('{"devDependencies":{"vite":"5"}}')
            with self.assertRaisesRegex(RuntimeError, 'dependencies are missing'):
                preview.command(project)
