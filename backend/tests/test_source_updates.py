import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app import source_updates as updates


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / 'workspace'
    (root / 'backend/app').mkdir(parents=True)
    (root / 'backend/app/main.py').write_text('value = 1\n')
    (root / 'frontend/src').mkdir(parents=True)
    (root / 'frontend/package.json').write_text('{"scripts":{"build":"vite build"}}')
    (root / 'frontend/src/App.jsx').write_text('export default 1')
    (root / 'backend/.env').write_text('PRIVATE=secret')
    (root / 'backend/personal.db').write_bytes(b'private data')
    monkeypatch.setenv('NOVA_UPDATE_HOME', str(tmp_path / 'updates'))
    return root


def test_prepare_is_isolated_and_excludes_private_files(workspace):
    result = asyncio.run(updates.prepare({'backend/app/main.py': 'value = 2\n'}, root=workspace))
    candidate = Path(result['path'])
    assert (workspace / 'backend/app/main.py').read_text() == 'value = 1\n'
    assert (candidate / 'backend/app/main.py').read_text() == 'value = 2\n'
    assert not (candidate / 'backend/.env').exists()
    assert not (candidate / 'backend/personal.db').exists()
    assert result['status'] == 'prepared'


def test_activation_requires_verification(workspace):
    item = asyncio.run(updates.prepare({'backend/app/main.py': 'value = 2'}, root=workspace))
    with pytest.raises(ValueError, match='verified'):
        updates.activate(item['id'])


def test_verified_release_activates_and_rolls_back(workspace, monkeypatch):
    monkeypatch.setattr(updates, '_validate_candidate', AsyncMock(return_value={'ok': True, 'checks': ['fixture']}))
    item = asyncio.run(updates.prepare({'backend/app/main.py': 'value = 2'}, root=workspace))
    assert asyncio.run(updates.verify(item['id']))['status'] == 'verified'
    active = updates.activate(item['id'])
    assert active['pending_boot'] is True
    assert updates.status()['active_id'] == item['id']
    assert updates.rollback()['active_id'] is None
    assert (workspace / 'backend/app/main.py').read_text() == 'value = 1\n'


def test_verification_and_activation_detect_changed_candidate(workspace, monkeypatch):
    monkeypatch.setattr(updates, '_validate_candidate', AsyncMock(return_value={'ok': True}))
    item = asyncio.run(updates.prepare({'backend/app/main.py': 'value = 2'}, root=workspace))
    asyncio.run(updates.verify(item['id']))
    (Path(item['path']) / 'backend/app/main.py').write_text('value = 3')
    with pytest.raises(ValueError, match='changed'):
        updates.activate(item['id'])


def test_core_edits_are_detected_before_activation(workspace, monkeypatch):
    monkeypatch.setattr(updates, '_validate_candidate', AsyncMock(return_value={'ok': True}))
    item = asyncio.run(updates.prepare({'backend/app/main.py': 'value = 2'}, root=workspace))
    asyncio.run(updates.verify(item['id']))
    (workspace / 'backend/app/main.py').write_text('user edit')
    with pytest.raises(ValueError, match='source changed'):
        updates.activate(item['id'])


def test_failure_never_changes_active_release(workspace, monkeypatch):
    monkeypatch.setattr(updates, '_validate_candidate', AsyncMock(return_value={'ok': False, 'error': 'test failure'}))
    item = asyncio.run(updates.prepare({'backend/app/main.py': 'value = 2'}, root=workspace))
    assert asyncio.run(updates.verify(item['id']))['status'] == 'failed'
    assert updates.status()['active_id'] is None


def test_traversal_cannot_escape_stage(workspace):
    with pytest.raises(ValueError):
        asyncio.run(updates.prepare({'../../escape.py': 'x=1'}, root=workspace))


def test_boot_failure_restores_previous_selection(workspace, monkeypatch):
    monkeypatch.setattr(updates, '_validate_candidate', AsyncMock(return_value={'ok': True}))
    item = asyncio.run(updates.prepare({'backend/app/main.py': 'value = 2'}, root=workspace))
    asyncio.run(updates.verify(item['id']))
    updates.activate(item['id'])
    updates.boot_result(item['id'], healthy=False, reason='startup import failed')
    assert updates.status()['active_id'] is None
    assert updates.get(item['id'])['status'] == 'boot_failed'


def _activated(workspace, monkeypatch, edits):
    monkeypatch.setattr(updates, '_validate_candidate', AsyncMock(return_value={'ok': True}))
    item = asyncio.run(updates.prepare(edits, root=workspace))
    asyncio.run(updates.verify(item['id']))
    updates.activate(item['id'])
    return item


def test_multiline_content_activates_on_every_platform(workspace, monkeypatch):
    item = _activated(workspace, monkeypatch, {'backend/app/main.py': 'a = 1\nb = 2\n'})
    assert (workspace / 'backend/app/main.py').read_bytes() == b'a = 1\nb = 2\n'
    assert updates.get(item['id'])['status'] == 'activated'


def test_rollback_removes_files_the_update_added(workspace, monkeypatch):
    _activated(workspace, monkeypatch, {'backend/app/added.py': 'x = 1\n'})
    assert (workspace / 'backend/app/added.py').exists()
    updates.rollback()
    assert not (workspace / 'backend/app/added.py').exists()


def test_rollback_never_overwrites_later_user_edits(workspace, monkeypatch):
    _activated(workspace, monkeypatch, {'backend/app/main.py': 'value = 2\n'})
    (workspace / 'backend/app/main.py').write_text('user kept editing')
    assert updates.rollback()['status'] == 'conflict'
    assert (workspace / 'backend/app/main.py').read_text() == 'user kept editing'


def test_state_survives_restart_and_unconfirmed_boot_rolls_back(workspace, monkeypatch):
    item = _activated(workspace, monkeypatch, {'backend/app/main.py': 'value = 2\n'})
    monkeypatch.delitem(__import__('sys').modules, 'pytest')  # behave like a real launch
    assert updates.recover_on_boot()['status'] == 'pending_boot'   # first launch starts...
    result = updates.recover_on_boot()                              # ...and never confirmed
    assert result['status'] == 'boot_failed'
    assert (workspace / 'backend/app/main.py').read_text() == 'value = 1\n'
    assert updates.status()['active_id'] is None


def test_confirmed_boot_goes_live(workspace, monkeypatch):
    item = _activated(workspace, monkeypatch, {'backend/app/main.py': 'value = 2\n'})
    assert updates.confirm_boot()['status'] == 'live'
    assert updates.recover_on_boot() is None
    assert (workspace / 'backend/app/main.py').read_text() == 'value = 2\n'


def test_second_activation_waits_for_boot_check(workspace, monkeypatch):
    _activated(workspace, monkeypatch, {'backend/app/main.py': 'value = 2\n'})
    other = asyncio.run(updates.prepare({'frontend/src/App.jsx': 'export default 2'}, root=workspace))
    asyncio.run(updates.verify(other['id']))
    with pytest.raises(ValueError, match='boot check'):
        updates.activate(other['id'])


def test_private_and_generated_paths_cannot_be_edited(workspace):
    for rel in ['backend/.env', 'frontend/node_modules/x.js', 'backend/personal.db']:
        with pytest.raises(ValueError):
            asyncio.run(updates.prepare({rel: 'x'}, root=workspace))
