import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app import sentinel


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'source'
    (root / 'backend/app').mkdir(parents=True)
    (root / 'backend/app/example.py').write_bytes(b'value = 1\r\n')
    with patch.object(sentinel, 'get_repo_root', return_value=root), patch.object(
        sentinel.config, 'DB_PATH', tmp_path / 'data/nova.db'
    ):
        sentinel._LAST_CHECKPOINT = None
        yield root


def test_failed_suite_restores_exact_original_bytes(source):
    with patch.object(sentinel.selfcheck, 'run_tests', AsyncMock(return_value={'ok': True, 'passed': False})):
        result = asyncio.run(sentinel.safe_patch_file('backend/app/example.py', 'value = 2\n'))
    assert result['ok'] is False
    assert (source / 'backend/app/example.py').read_bytes() == b'value = 1\r\n'


def test_diagnostics_requires_passing_tests(source):
    with patch.object(sentinel.selfcheck, 'run_tests', AsyncMock(return_value={'ok': True, 'passed': False})):
        assert not asyncio.run(sentinel.run_diagnostics())['healthy']


def test_repair_rejects_outside_source(source):
    outside = source.parent / 'outside.py'
    outside.write_text('value = 1')
    with patch.object(sentinel.selfcheck, 'run_tests', AsyncMock(return_value={'ok': True, 'passed': True})):
        result = asyncio.run(sentinel.safe_patch_file('../outside.py', 'value = 2'))
    assert not result['ok']
    assert outside.read_text() == 'value = 1'


def test_rollback_preserves_unrelated_and_refuses_concurrent_edit(source):
    with patch.object(sentinel.selfcheck, 'run_tests', AsyncMock(return_value={'ok': True, 'passed': True})):
        assert asyncio.run(sentinel.safe_patch_file('backend/app/example.py', 'value = 2'))['ok']
    unrelated = source / 'notes.txt'
    unrelated.write_text('keep me')
    target = source / 'backend/app/example.py'
    target.write_text('value = 3')
    assert sentinel.rollback_git_checkpoint()['status'] == 'conflict'
    assert target.read_text() == 'value = 3'
    target.write_text('value = 2')
    sentinel._LAST_CHECKPOINT = None  # survives process restart
    assert sentinel.rollback_git_checkpoint()['status'] == 'reverted'
    assert target.read_bytes() == b'value = 1\r\n'
    assert unrelated.read_text() == 'keep me'


def test_multiple_new_files_reverted_on_failure(source):
    with patch.object(sentinel.selfcheck, 'run_tests', AsyncMock(return_value={'ok': False, 'error': 'timeout'})):
        result = asyncio.run(sentinel.safe_patch_files({'backend/app/new.py': 'x = 1', 'backend/app/example.py': 'x = 2'}))
    assert not result['ok']
    assert not (source / 'backend/app/new.py').exists()
    assert (source / 'backend/app/example.py').read_bytes() == b'value = 1\r\n'


def test_failed_frontend_build_removes_new_component(source):
    with patch.object(sentinel.selfcheck, 'run_tests', AsyncMock(return_value={'ok': True, 'passed': True})), patch.object(
        sentinel, '_verify_frontend', AsyncMock(return_value={'ok': False, 'output': 'Invalid component'})
    ):
        result = asyncio.run(sentinel.safe_patch_file('frontend/src/New.jsx', 'invalid jsx'))
    assert not result['ok']
    assert not (source / 'frontend/src/New.jsx').exists()


def test_cancelled_verification_restores_source(source):
    with patch.object(sentinel.selfcheck, 'run_tests', AsyncMock(side_effect=asyncio.CancelledError)):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(sentinel.safe_patch_file('backend/app/example.py', 'value = 2'))
    assert (source / 'backend/app/example.py').read_bytes() == b'value = 1\r\n'
