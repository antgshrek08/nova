"""Dismissed help notes and popups stay dismissed (app/main.py /ui/dismissed)."""
import asyncio

import pytest

from app import main, operator_store


@pytest.fixture()
def store(monkeypatch):
    saved = {}
    monkeypatch.setattr(operator_store, "get", lambda kind, key: saved.get((kind, key)))
    monkeypatch.setattr(operator_store, "put", lambda kind, key, value: saved.__setitem__((kind, key), value))
    return saved


def test_dismissed_notes_are_remembered_and_can_come_back(store):
    assert asyncio.run(main.ui_dismissed()) == {"ids": []}
    asyncio.run(main.ui_dismiss({"ids": ["guide.chat", "workspace.unlock"]}))
    asyncio.run(main.ui_dismiss({"ids": ["guide.chat"]}))  # twice is still once
    assert asyncio.run(main.ui_dismissed()) == {"ids": ["guide.chat", "workspace.unlock"]}
    asyncio.run(main.ui_undismiss("guide.chat"))
    assert asyncio.run(main.ui_dismissed()) == {"ids": ["workspace.unlock"]}
