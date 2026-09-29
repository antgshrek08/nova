import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from app import customization


def test_flashcards_is_only_a_suggestion():
    with patch.object(customization.db, 'list_custom_tabs', AsyncMock(return_value=[])), patch.object(customization.db, 'save_custom_tab', AsyncMock()) as save:
        result = asyncio.run(customization.manage('suggest'))
    assert result['suggestions'][0]['id'] == 'flashcards'
    assert not result['suggestions'][0]['installed']
    save.assert_not_called()


def test_tab_roundtrip_uses_existing_persistence_contract():
    with patch.object(customization.db, 'save_custom_tab', AsyncMock(return_value={'id': 'timer'})) as save:
        result = asyncio.run(customization.manage('save', id='timer', title='Timer', html_content='<p>Timer</p>'))
    assert result['tab']['id'] == 'timer'
    save.assert_awaited_once_with('timer', 'Timer', 'Sparkles', '', 'widget', '<p>Timer</p>')


def test_unsupported_components_are_not_reported_as_working():
    with pytest.raises(ValueError, match='renderer'):
        asyncio.run(customization.manage('save', title='Test', content_type='react'))
