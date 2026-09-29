"""Concurrency checks against temporary SQLite storage; no real credentials."""
import asyncio
import importlib.util
import sys
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "app"
PKG = "concurrency_checks"
package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules[PKG] = package
for name in ("config", "secrets_store"):
    module = types.ModuleType(f"{PKG}.{name}")
    sys.modules[module.__name__] = module
    setattr(package, name, module)


def load(name):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    setattr(package, name, module)
    spec.loader.exec_module(module)
    return module


db = load("db")
identity = load("identity")


class ConcurrentStorage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        package.config.DB_PATH = Path(self.folder.name) / "test.db"
        db._connection = None
        db._connection_lock = asyncio.Lock()
        identity._account_lock = asyncio.Lock()
        self.connections = []
        original_connect = db.aiosqlite.connect

        async def connect(*args, **kwargs):
            connection = await original_connect(*args, **kwargs)
            self.connections.append(connection)
            await asyncio.sleep(0.01)
            return connection

        self.connector = patch.object(db.aiosqlite, "connect", connect)
        self.connector.start()
        self.vault = {}
        package.secrets_store.put = lambda name, value: self.vault.__setitem__(name, value)
        package.secrets_store.get = self.vault.get
        package.secrets_store.delete = lambda name: self.vault.pop(name, None) is not None
        package.secrets_store.SecretError = ValueError

    async def asyncTearDown(self):
        self.connector.stop()
        for connection in self.connections:
            await connection.close()
        db._connection = None
        self.folder.cleanup()

    async def test_concurrent_startup_returns_one_ready_connection(self):
        async def caller():
            connection = await db.get_connection()
            async with connection.execute("SELECT count(*) FROM accounts") as result:
                await result.fetchone()
            return connection

        results = await asyncio.wait_for(
            asyncio.gather(*(caller() for _ in range(6)), return_exceptions=True), timeout=3)
        self.assertFalse([result for result in results if isinstance(result, BaseException)], results)
        self.assertEqual(len(self.connections), 1)
        self.assertTrue(all(result is results[0] for result in results))

    async def test_concurrent_case_variants_share_one_account(self):
        await db.get_connection()
        listing = db.list_accounts

        async def delayed_snapshot():
            rows = await listing()
            await asyncio.sleep(0.01)
            return rows

        with patch.object(db, "list_accounts", delayed_snapshot):
            await asyncio.gather(
                identity.add("Instagram", "first", password="first-secret"),
                identity.add("instagram", "second", password="second-secret"),
            )
        rows = await db.list_accounts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.vault["account.instagram"], rows[0]["username"] + "-secret")

    async def test_saving_a_url_preserves_metadata_in_real_database(self):
        await identity.add("Instagram", "nova", email="nova@example.com", notes="keep this")
        await identity.add("Instagram", "nova", url="https://www.instagram.com/accounts/login/")
        rows = await db.list_accounts()
        self.assertEqual(rows[0]["email"], "nova@example.com")
        self.assertEqual(rows[0]["notes"], "keep this")

    async def test_failed_startup_does_not_publish_partial_connection(self):
        with patch.object(db, "_migrate", side_effect=RuntimeError("migration interrupted")):
            with self.assertRaises(RuntimeError):
                await db.get_connection()
        self.assertIsNone(db._connection)
        connection = await db.get_connection()
        async with connection.execute("SELECT count(*) FROM accounts") as result:
            self.assertEqual((await result.fetchone())[0], 0)


@unittest.skipUnless(sys.platform == "win32", "Win32 class registration")
class ConcurrentOverlay(unittest.TestCase):
    def test_workers_register_one_callback(self):
        # Stub only registration and pause there to expose the race. No
        # window is opened, and no pointer is moved in this subprocess.
        script = """
import ctypes
import time
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from app import cursor

def register(pointer):
    time.sleep(0.03)
    return 1

with patch.object(ctypes.windll.user32, 'RegisterClassW', side_effect=register) as registration:
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: cursor._register_ring_class(ctypes, wintypes), range(6)))
    assert all(results), results
    assert registration.call_count == 1, registration.call_count
"""
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT.parent,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
