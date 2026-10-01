"""What a brand-new install (no Ollama, no keys, not a developer's copy) gets
from features that used to assume a developer's machine."""
import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import daily_tasks, idle_behavior, main


def _no_ollama():
    return patch("app.providers.get_local_ollama_models", AsyncMock(side_effect=ConnectionError("no Ollama")))


def test_the_idle_animation_without_ollama_is_simply_unavailable():
    with _no_ollama():
        assert asyncio.run(idle_behavior.generate_idle_action())["available"] is False


def test_a_spoken_summary_without_a_local_model_is_the_opening_not_an_error():
    text = "**Product rule:** multiply, then add. " + "More detail follows here. " * 40
    with _no_ollama():
        r = TestClient(main.app, client=("127.0.0.1", 50000)).post("/tts/summarize", json={"text": text})
    assert r.status_code == 200
    summary = r.json()["summary"]
    assert summary.startswith("Product rule: multiply, then add.") and len(summary) <= 280 and "*" not in summary


def test_daily_jobs_do_nothing_without_openrouter():
    with patch.object(daily_tasks, "_run_once", wraps=daily_tasks._run_once), \
         patch("app.config.openrouter_api_key", return_value=None), \
         patch("app.db.create_task", AsyncMock()) as create:
        asyncio.run(daily_tasks._run_once())
    create.assert_not_called()


def test_developer_reviews_only_run_on_a_developer_copy():
    made = []

    async def create_task(**kw):
        made.append(kw["role"])
        return {"id": len(made)}

    with patch("app.config.openrouter_api_key", return_value="k"), \
         patch("app.sentinel.is_checkout", return_value=False), \
         patch("app.db.get_app_settings", AsyncMock(return_value={})), \
         patch("app.db.set_app_settings", AsyncMock()), \
         patch("app.db.list_tasks", AsyncMock(return_value=[])), \
         patch("app.db.create_task", side_effect=create_task), \
         patch("app.db.update_task", AsyncMock(return_value={})), \
         patch("app.agents.registry.broadcast_task", AsyncMock()), \
         patch("app.providers.stream_openrouter", side_effect=RuntimeError("offline")):
        asyncio.run(daily_tasks._run_once())
    assert made == ["briefing", "reminder"]
