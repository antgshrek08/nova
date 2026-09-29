import asyncio
import pytest
from app import config, extensions


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'nova.db')


def run(action, **kwargs):
    return asyncio.run(extensions.manage(action, **kwargs))


def manifest(id='example', version='1.0.0', **kwargs):
    return dict(schema_version=1, id=id, title='Example', version=version,
                owner='user', kind='backend', compatibility={'api': 1},
                permissions=['storage'], dependencies={}, owned_files=[], data_migrations=[], **kwargs)


def test_durable_lifecycle_history_and_export_preserve_data():
    run('install', manifest=manifest())
    asyncio.run(extensions.set_data('example', {'notes': 'keep me'}))
    run('install', manifest=manifest(version='1.1.0'))
    run('disable', id='example')
    assert run('get', id='example')['extension']['state'] == 'disabled'
    run('remove', id='example')
    run('restore', id='example', version='1.0.0')
    assert run('get', id='example')['extension']['manifest']['version'] == '1.0.0'
    exported = run('export', id='example', include_data=True)['export']
    assert exported['data'] == {'notes': 'keep me'}
    assert len(exported['versions']) == 2
    assert len(run('history', id='example')['history']) == 5


def test_dependency_lifecycle_and_file_ownership():
    a = manifest('base'); a['owned_files'] = ['backend/app/extra.py']
    run('install', manifest=a)
    b = manifest('dependent'); b['dependencies'] = {'base': '1.0.0'}
    run('install', manifest=b)
    with pytest.raises(ValueError, match='depend'):
        run('disable', id='base')
    newer = dict(a, version='2.0.0')
    with pytest.raises(ValueError, match='depend'):
        run('install', manifest=newer)
    c = manifest('conflict'); c['owned_files'] = a['owned_files']
    with pytest.raises(ValueError, match='owned'):
        run('install', manifest=c)
    assert asyncio.run(extensions.check_source_conflicts(['backend/app/extra.py']))


@pytest.mark.parametrize('change', [
    {'compatibility': {'api': 2}}, {'version': 'latest'}, {'permissions': ['shell']},
    {'owned_files': ['../outside.py']}, {'data_migrations': [{'sql': 'DROP TABLE x'}]},
])
def test_invalid_manifests_rejected(change):
    with pytest.raises(ValueError):
        run('install', manifest=dict(manifest(), **change))
    assert run('list')['extensions'] == []


def test_same_version_cannot_change_and_owner_cannot_be_taken_over():
    run('install', manifest=manifest())
    with pytest.raises(ValueError, match='immutable'):
        run('install', manifest=dict(manifest(), title='Changed'))
    with pytest.raises(ValueError, match='owner'):
        run('install', manifest=dict(manifest(version='1.1.0'), owner='other'))


def test_grade_calculator_is_functional_and_persistent():
    result = asyncio.run(extensions.grade_calculator('calculate', entries=[
        {'name': 'Homework', 'earned': 40, 'possible': 50, 'weight': 30},
        {'name': 'Exam', 'earned': 90, 'possible': 100, 'weight': 70},
    ]))
    assert result['data']['result']['percentage'] == 87
    assert asyncio.run(extensions.grade_calculator('get'))['data'] == result['data']
    run('remove', id='grade-calculator')
    run('restore', id='grade-calculator')
    assert asyncio.run(extensions.grade_calculator('get'))['data'] == result['data']


@pytest.mark.parametrize('entries', [[], [{'earned': 1, 'possible': 0}],
    [{'earned': float('nan'), 'possible': 1}], [{'earned': -1, 'possible': 1}],
    [{'earned': 1, 'possible': 1, 'weight': 10}, {'earned': 1, 'possible': 1}]])
def test_grade_calculator_rejects_invalid_inputs(entries):
    with pytest.raises(ValueError):
        asyncio.run(extensions.grade_calculator('calculate', entries=entries))


def test_ownership_is_exact_not_substring():
    a = manifest('a'); a['owned_files'] = ['frontend/src/data.js']
    run('install', manifest=a)
    b = manifest('b'); b['owned_files'] = ['frontend/src/a.js']
    run('install', manifest=b)
    assert not asyncio.run(extensions.check_source_conflicts(['src/a.js']))


def test_unknown_extension_and_version_are_errors():
    with pytest.raises(ValueError, match='not found'):
        run('disable', id='missing')
    run('install', manifest=manifest())
    with pytest.raises(ValueError, match='version'):
        run('restore', id='example', version='9.9.9')


def test_remove_refuses_while_a_dependent_is_active():
    run('install', manifest=manifest('base'))
    b = manifest('dependent'); b['dependencies'] = {'base': '1.0.0'}
    run('install', manifest=b)
    with pytest.raises(ValueError, match='depend'):
        run('remove', id='base')
