"""Small durable operator records, separate from Nova's conversation database."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import config


def directory() -> Path:
    path = Path(config.DB_PATH).parent / 'operator'
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def transaction():
    connection = sqlite3.connect(directory() / 'state.sqlite3', timeout=15)
    try:
        connection.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(kind,id))')
        connection.execute('BEGIN IMMEDIATE')
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def get(kind, key, connection=None):
    if connection is None:
        with transaction() as connection:
            return get(kind, key, connection)
    row = connection.execute('SELECT data FROM records WHERE kind=? AND id=?', (kind, str(key))).fetchone()
    return json.loads(row[0]) if row else None


def put(kind, key, value, connection=None):
    if connection is None:
        with transaction() as connection:
            return put(kind, key, value, connection)
    connection.execute('INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',
                       (kind, str(key), json.dumps(value)))
    return value


def listing(kind):
    with transaction() as connection:
        return [json.loads(row[0]) for row in connection.execute('SELECT data FROM records WHERE kind=? ORDER BY rowid DESC LIMIT 200', (kind,))]


def create(kind, **fields):
    key = uuid.uuid4().hex
    return put(kind, key, {'id': key, 'created_at': time.time(), **fields})
