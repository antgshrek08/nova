"""Conservative, deterministic source exports. Never uploads or deploys files."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

MANIFEST = 'NOVA_EXPORT_MANIFEST.json'
INSTRUCTIONS = 'NOVA_IMPORT.md'
_EXTENSIONS = {'.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.css', '.scss',
               '.html', '.json', '.toml', '.yaml', '.yml', '.md', '.txt', '.sql',
               '.sh', '.ps1', '.bat', '.cmd', '.xml', '.svg', '.gitignore', '.gitattributes'}
_BLOCKED = {'.git', '.hg', '.svn', 'node_modules', 'vendor', 'dist', 'build',
            'models', 'data', 'storage', 'uploads', 'attachments', 'recordings',
            'screenshots', 'voice-samples', 'profiles', 'browser', 'browsers',
            'browser-profile', 'browser-profiles', 'user_data', 'user-data',
            '__pycache__', 'coverage', 'secrets', 'credentials', 'private', 'logs'}
_SECRET_NAME = re.compile(r'(secret|credential|password|token|cookie|session|profile|history|preferences)', re.I)
_SECRET_CONTENT = re.compile(
    rb'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|(?:sk-[A-Za-z0-9_-]{20,})|'
    rb'(?:gh[pousr]_[A-Za-z0-9]{20,})|AKIA[0-9A-Z]{16}|'
    rb'["\']?(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)["\']?\s*[:=]\s*["\'][^"\'\r\n]{8,}["\']', re.I)
_RELEASE_PREFIXES = ('backend/app/', 'backend/tests/', 'frontend/src/', 'frontend/electron/', 'docs/release/')
_RELEASE_FILES = {
    'README.md', 'CONTRIBUTING.md', 'LICENSE', 'LICENSE.md', 'THIRD_PARTY_NOTICES.md',
    '.gitignore', '.gitattributes', 'backend/requirements.txt', 'backend/requirements-ci.lock',
    'frontend/package.json', 'frontend/package-lock.json', 'frontend/index.html',
    'frontend/vite.config.ts', 'frontend/tsconfig.json', 'frontend/tsconfig.app.json',
    'frontend/tsconfig.node.json', 'frontend/eslint.config.js',
    'scripts/backend_setup.py', 'scripts/backend_check.py', 'scripts/source_release.py',
    'scripts/dependency_inventory.py', '.github/workflows/backend.yml',
}


def _link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def _write(archive: ZipFile, name: str, data: bytes) -> None:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def create_export(root: Path, output_dir: Path, *, target: str = 'portable',
                  source_release: bool = False, max_bytes: int = 100_000_000) -> dict:
    """Export only recognized text source; excludes unknown binaries and private state.

    Content scanning is a guardrail, not proof that source contains no private data.
    The caller must review the manifest and extracted files before publication.
    """
    if target not in {'portable', 'replit', 'lovable'}:
        raise ValueError('Unsupported export target')
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Project must be a directory')
    output_dir = Path(output_dir).resolve()
    files: list[tuple[str, bytes]] = []
    excluded = 0
    total = 0
    for folder, directories, names in os.walk(root, followlinks=False):
        parent = Path(folder)
        for name in list(directories):
            child = parent / name
            if name.lower() in _BLOCKED or name.startswith('.') or _link(child) or child.resolve() == output_dir:
                directories.remove(name)
                excluded += 1
        for name in sorted(names):
            path = parent / name
            relative = path.relative_to(root).as_posix()
            allowed_release = relative in _RELEASE_FILES or relative.startswith(_RELEASE_PREFIXES)
            if (_link(path) or name.startswith('.env') or _SECRET_NAME.search(name)
                    or name in {MANIFEST, INSTRUCTIONS}
                    or (path.suffix.lower() not in _EXTENSIONS and name not in {'Dockerfile', 'Makefile', 'LICENSE', '.gitignore', '.gitattributes'})
                    or (source_release and not allowed_release)):
                excluded += 1
                continue
            # Open without following POSIX symlinks, and compare file identity to
            # reject replacement between inspection and open on other platforms.
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode) or before.st_nlink > 1:
                excluded += 1
                continue
            if before.st_size + total > max_bytes:
                raise ValueError('Export exceeds the configured size limit')
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
            with os.fdopen(fd, 'rb') as source:
                opened = os.fstat(source.fileno())
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino) or _link(path):
                    raise ValueError('Source changed during export; retry from a stable checkout')
                data = source.read(max_bytes - total + 1)
            if len(data) + total > max_bytes:
                raise ValueError('Export exceeds the configured size limit')
            if b'\x00' in data or _SECRET_CONTENT.search(data):
                excluded += 1
                continue
            try:
                data.decode('utf-8')
            except UnicodeDecodeError:
                excluded += 1
                continue
            total += len(data)
            files.append((relative, data))
    files.sort()
    if not files:
        raise ValueError('No eligible source files found')
    instructions = (f'# Manual import: {target}\n\n'
        'This archive is source code, not a deployment. Nothing was uploaded.\n\n'
        '1. Verify the archive with scripts/source_release.py --verify ARCHIVE.\n'
        '2. Extract into a new folder; review included source and the manifest.\n'
        '3. Install dependencies using the project setup instructions and lockfiles.\n'
        '4. Configure secrets directly in your destination environment.\n'
        '5. Follow the destination account UI to import supported source, or upload it\n'
        '   to your own repository and connect that repository where supported.\n\n'
        'Replit and Lovable capabilities vary; this export does not assert ZIP import,\n'
        'Python backend, Electron, or desktop-device support in either service.\n'
        'If the destination cannot import this source, use it as a local handoff.\n'
        'Images, binaries, dependencies, environment files and private state are omitted.\n'
        'Review omissions and restore only deliberately approved public assets.\n').encode()
    manifest = {'schema_version': 1, 'target': target, 'deployed': False,
                'source_release': source_release, 'excluded_count': excluded,
                'review_required': True,
                'files': [{'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in files],
                'instructions_sha256': hashlib.sha256(instructions).hexdigest()}
    output_dir.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix='.zip', prefix='nova-export-', dir=output_dir)
    os.close(fd)
    archive_path = Path(temporary)
    try:
        with ZipFile(archive_path, 'w') as archive:
            for name, data in files:
                _write(archive, name, data)
            _write(archive, INSTRUCTIONS, instructions)
            _write(archive, MANIFEST, json.dumps(manifest, sort_keys=True, indent=2).encode())
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        return {'ok': True, 'status': 'exported_manual_import_required', 'deployed': False,
                'target': target, 'archive_path': str(archive_path), 'sha256': digest,
                'manifest': manifest, 'excluded_count': excluded,
                'message': 'Source ZIP created. Review it before manual import; nothing was deployed.'}
    except BaseException:
        archive_path.unlink(missing_ok=True)
        raise


def verify_export(path: Path) -> dict:
    """Check exact archive membership, path safety and hashes without extracting."""
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > 100_000 or sum(i.file_size for i in infos) > 110_000_000:
                raise ValueError('Archive verification size limit exceeded')
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError('Duplicate archive entries')
            manifest = json.loads(archive.read(MANIFEST))
            if manifest['schema_version'] != 1:
                raise ValueError('Unsupported manifest version')
            expected = {MANIFEST, INSTRUCTIONS}
            for item in manifest['files']:
                name = item['path']
                if name in expected or name.startswith('/') or '\\' in name or ':' in name or '..' in name.split('/'):
                    raise ValueError('Unsafe or duplicate archive path')
                expected.add(name)
                data = archive.read(name)
                if len(data) != item['size'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                    raise ValueError('Source integrity mismatch')
            if set(names) != expected:
                raise ValueError('Unexpected archive entries')
            if hashlib.sha256(archive.read(INSTRUCTIONS)).hexdigest() != manifest['instructions_sha256']:
                raise ValueError('Instruction integrity mismatch')
        return {'ok': True, 'files': len(manifest['files']), 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    except (OSError, ValueError, KeyError, TypeError, __import__('zipfile').BadZipFile) as exc:
        return {'ok': False, 'message': str(exc)}
