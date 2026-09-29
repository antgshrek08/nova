import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from app.project_export import create_export, verify_export


class ProjectExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'
        self.root.mkdir()
        self.out = Path(self.tmp.name) / 'exports'

    def put(self, name, value='private'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')

    def test_real_archive_excludes_private_data_and_has_integrity(self):
        # Write in binary to ensure deterministic LF bytes on all platforms
        (self.root / 'src').mkdir(parents=True, exist_ok=True)
        (self.root / 'src' / 'app.py').write_bytes(b'print("hello")\n')
        for name in ['.env', '.env.example', 'node_modules/lib/index.js',
                     'browser-profile/Preferences.json', 'backend/nova.db',
                     '.git/config', 'recordings/test.wav', 'credentials.json',
                     'src/token.pem', 'src/config.json']:
            self.put(name, '{"api_key":"real-private-value"}')
        result = create_export(self.root, self.out, target='replit')
        self.assertTrue(result['ok'])
        self.assertFalse(result['deployed'])
        self.assertEqual(result['status'], 'exported_manual_import_required')
        with ZipFile(result['archive_path']) as archive:
            self.assertEqual(set(archive.namelist()), {'src/app.py', 'NOVA_EXPORT_MANIFEST.json', 'NOVA_IMPORT.md'})
            manifest = json.loads(archive.read('NOVA_EXPORT_MANIFEST.json'))
            self.assertEqual(manifest['files'][0]['sha256'], hashlib.sha256(b'print("hello")\n').hexdigest())
        self.assertTrue(verify_export(Path(result['archive_path']))['ok'])

    def test_tampering_is_detected(self):
        self.put('main.py', 'print(1)')
        result = create_export(self.root, self.out)
        with ZipFile(result['archive_path'], 'a') as archive:
            archive.writestr('extra.py', 'injected')
        self.assertFalse(verify_export(Path(result['archive_path']))['ok'])

    def test_release_allowlist_and_determinism(self):
        self.put('backend/app/a.py', 'x = 1')
        self.put('voice-samples/private.py')
        self.put('scripts/private.py')
        self.put('docs/plans/private.md')
        first = create_export(self.root, self.out, source_release=True)
        second = create_export(self.root, self.out, source_release=True)
        self.assertEqual(first['sha256'], second['sha256'])
        self.assertEqual([f['path'] for f in first['manifest']['files']], ['backend/app/a.py'])

    def test_symlink_not_followed(self):
        self.put('main.py', 'pass')
        outside = Path(self.tmp.name) / 'private.py'
        outside.write_text('secret')
        try:
            (self.root / 'link.py').symlink_to(outside)
        except OSError:
            self.skipTest('Symlink privilege unavailable')
        result = create_export(self.root, self.out)
        self.assertNotIn('link.py', [f['path'] for f in result['manifest']['files']])

    def test_no_source_or_bad_target_fail(self):
        with self.assertRaises(ValueError):
            create_export(self.root, self.out)
        self.put('main.py', 'pass')
        with self.assertRaises(ValueError):
            create_export(self.root, self.out, target='shell;evil')


class ShipExportTests(unittest.TestCase):
    def test_replit_target_returns_a_real_archive_and_deploys_nothing(self):
        import asyncio
        from unittest.mock import patch
        from app import config, ship
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'project'
            (root / 'src').mkdir(parents=True)
            (root / 'src' / 'app.py').write_bytes(b'x = 1\n')
            with patch.object(config, 'DB_PATH', Path(tmp) / 'data' / 'nova.db'):
                result = asyncio.run(ship.deploy_zero_api(str(root), 'replit'))
            self.assertTrue(result['ok'])
            self.assertFalse(result['deployed'])
            self.assertTrue(Path(result['archive_path']).is_file())
            self.assertTrue(Path(result['archive_path']).is_relative_to(Path(tmp) / 'data' / 'exports'))
