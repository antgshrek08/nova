import asyncio
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import inference_scheduler


class SchedulerChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        inference_scheduler._global_cloud = asyncio.Semaphore(2)
        inference_scheduler._provider_slots = {name: asyncio.Semaphore(1) for name in ("claude", "codex", "antigravity")}

    async def test_child_task_cannot_inherit_parent_lease(self):
        entered = asyncio.Event()
        async def child():
            async with inference_scheduler.slot("claude_cli_plan"):
                entered.set()
        async with inference_scheduler.slot("claude_cli"):
            task = asyncio.create_task(child())
            await asyncio.sleep(.02)
            self.assertFalse(entered.is_set())
        await asyncio.wait_for(task, 1)
        self.assertTrue(entered.is_set())

    async def test_nested_same_task_is_reentrant(self):
        async with inference_scheduler.slot("codex_cli"):
            async with inference_scheduler.slot("codex_cli_plan"):
                self.assertTrue(inference_scheduler._provider_slots["codex"].locked())
        self.assertFalse(inference_scheduler._provider_slots["codex"].locked())

    async def test_cancel_waiting_for_global_releases_provider(self):
        await inference_scheduler._global_cloud.acquire()
        await inference_scheduler._global_cloud.acquire()
        async def waiter():
            async with inference_scheduler.slot("antigravity_cli"):
                self.fail("Global slots are occupied")
        task = asyncio.create_task(waiter())
        await asyncio.sleep(.02)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(inference_scheduler._provider_slots["antigravity"].locked())
        inference_scheduler._global_cloud.release()
        inference_scheduler._global_cloud.release()

    async def test_same_provider_serializes_and_different_providers_overlap(self):
        active = {"n": 0, "max": 0}

        async def work(provider):
            async with inference_scheduler.slot(provider):
                active["n"] += 1
                active["max"] = max(active["max"], active["n"])
                await asyncio.sleep(0.03)
                active["n"] -= 1

        await asyncio.gather(work("claude_cli"), work("claude_cli_plan"), work("codex_cli"))
        self.assertEqual(active["max"], 2)

    async def test_cancellation_releases_slot(self):
        entered = asyncio.Event()

        async def hold():
            async with inference_scheduler.slot("codex_cli"):
                entered.set()
                await asyncio.sleep(10)

        first = asyncio.create_task(hold())
        await entered.wait()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        async with inference_scheduler.slot("codex_cli_plan"):
            pass

    def test_provider_aliases_and_limits(self):
        self.assertEqual(inference_scheduler.provider_family("claude_cli_plan"), "claude")
        self.assertEqual(inference_scheduler.provider_family("codex_cli"), "codex")
        self.assertEqual(inference_scheduler.limits(), {"cloud_total": 2, "per_provider": 1})
