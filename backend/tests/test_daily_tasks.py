"""Daily runs use free inference, survive restarts, and expose failures."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1] / 'app'
package = types.ModuleType('daily_checks')
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
for name in ('db', 'providers', 'agents', 'telemetry', 'config', 'sentinel'):
    module = types.ModuleType('daily_checks.' + name)
    sys.modules[module.__name__] = module
    setattr(package, name, module)
spec = importlib.util.spec_from_file_location('daily_checks.daily_tasks', ROOT / 'daily_tasks.py')
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)


class DailyChecks(unittest.IsolatedAsyncioTestCase):
    async def test_daily_run_is_not_repeated_and_provider_failure_is_visible(self):
        today = daily.datetime.now().astimezone().date().isoformat()
        settings = {f'everyday:last:{role}': today for role in ('briefing', 'code_review', 'performance')}
        db = package.db
        db.get_app_settings = AsyncMock(side_effect=lambda: dict(settings))
        db.set_app_settings = AsyncMock(side_effect=lambda values: settings.update(values))
        db.list_tasks = AsyncMock(return_value=[])
        db.create_task = AsyncMock(return_value={'id': 1})
        db.update_task = AsyncMock(side_effect=lambda task_id, **fields: {'id': task_id, **fields})
        package.agents.registry = types.SimpleNamespace(broadcast_task=AsyncMock())
        package.telemetry.snapshot = lambda: {}
        # OpenRouter set up, on a developer's copy: every daily job applies.
        package.config.openrouter_api_key = lambda: 'k'
        package.sentinel.is_checkout = lambda: True
        calls = []
        async def fail(model, messages):
            calls.append(model)
            raise RuntimeError('Free model unavailable')
            yield ''
        package.providers.stream_openrouter = fail
        await daily._run_once()
        await daily._run_once()
        self.assertEqual(calls, ['openrouter/free'])
        db.create_task.assert_awaited_once()
        last = db.update_task.await_args.kwargs
        self.assertEqual(last['status'], 'error')
        self.assertIn('Free model unavailable', last['error'])


if __name__ == '__main__':
    unittest.main()
