import importlib.util
from pathlib import Path
import sys
import types
import unittest
import unittest.mock
import tempfile

root = Path(__file__).resolve().parents[1] / 'app'
pkg = types.ModuleType('context_checks')
pkg.__path__ = [str(root)]
sys.modules[pkg.__name__] = pkg
pkg.config = types.ModuleType('context_checks.config')
pkg.code_files = types.ModuleType('context_checks.code_files')
sys.modules[pkg.config.__name__] = pkg.config
sys.modules[pkg.code_files.__name__] = pkg.code_files
spec = importlib.util.spec_from_file_location('context_checks.project_context', root / 'project_context.py')
context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(context)


class ProjectContextTests(unittest.TestCase):
    def test_project_question_receives_live_listing_without_claiming_content_access(self):
        pkg.config.get_workspace_dir = lambda: Path.cwd()
        pkg.code_files.list_tree = lambda: [{'name': 'index.html', 'is_dir': False}, {'name': '.env', 'is_dir': False}]
        result = context.context_for('Can you see my key club website project now?')
        self.assertIn('index.html', result)
        self.assertIn('File contents have not been read', result)
        self.assertNotIn('.env', result)

    def test_general_chat_does_not_inspect_files(self):
        pkg.code_files.list_tree = lambda: self.fail('Unnecessary project read')
        self.assertIsNone(context.context_for('hello'))

    def test_find_named_project_and_skip_dependency_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder, 'Key-Club-Website')
            project.mkdir()
            (project / 'package.json').write_text('{}')
            hidden = Path(folder, 'node_modules', 'key-club')
            hidden.mkdir(parents=True)
            result = context.find_projects('Can you see my key club website project now?', [Path(folder)])
            self.assertEqual(len(result['matches']), 1)
            self.assertEqual(result['matches'][0]['folder'], str(project))
            self.assertEqual(result['matches'][0]['entry_files'], ['package.json'])

    def test_search_time_limit_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            result = context.find_projects('find key club project', [Path(folder)], seconds=-1)
            self.assertTrue(result['partial'])

    def test_walk_degrades_without_isjunction(self):
        """os.path.isjunction() is Python 3.12+. On 3.11 the attribute is
        absent, and calling it unguarded raised AttributeError in an ordinary
        chat path. Symlink detection alone is already complete on POSIX, so
        the walk must degrade rather than crash."""
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'src').mkdir()
            Path(folder, 'node_modules').mkdir()
            with unittest.mock.patch.object(context, '_ISJUNCTION', None):
                self.assertEqual(context._walkable(folder, ['src', 'node_modules', '.git']), ['src'])

    def test_granted_roots_add_real_content_evidence(self):
        """Without a grant this module can only report directory names. With
        one it must quote real lines, and must still withhold credentials."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / 'Biology-Notes.md').write_text(
                'Cell wall\nThe mitochondria is the powerhouse\nOsmosis', encoding='utf-8')
            (root / '.env').write_text('OPENROUTER_API_KEY=sk-live-secret', encoding='utf-8')
            pkg.config.get_workspace_dir = lambda: root
            pkg.code_files.list_tree = lambda: [{'name': 'Biology-Notes.md', 'is_dir': False}]

            result = context.context_for(
                'find the notes file that says "the mitochondria is the powerhouse"', [root])

            self.assertIsNotNone(result)
            self.assertIn('Biology-Notes.md', result)
            self.assertIn('powerhouse', result)          # a real quoted line
            self.assertNotIn('sk-live-secret', result)   # the key never leaves

    def test_granted_roots_report_withheld_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / '.env').write_text('KEY=1', encoding='utf-8')
            pkg.config.get_workspace_dir = lambda: root
            pkg.code_files.list_tree = lambda: []
            result = context.context_for('show me the .env file in my project', [root])
            self.assertIsNotNone(result)
            self.assertIn('withheld', result)
            self.assertNotIn('KEY=1', result)

    def test_walk_excludes_symlinked_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'real').mkdir()
            try:
                Path(folder, 'link').symlink_to(Path(folder, 'real'), target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('symlink creation not permitted here')
            self.assertEqual(context._walkable(folder, ['real', 'link']), ['real'])
