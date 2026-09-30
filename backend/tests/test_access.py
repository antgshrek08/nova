"""Who can talk to this backend.

Nova has never had authentication, and has been safe for exactly one reason:
it binds 127.0.0.1. Everything behind that binding is unguarded -- run_command,
write_file, delete_path, the desktop tools, the secrets vault -- so the day
anything reaches it from outside, there is no second line. The mobile app is
that day, which is why this exists before the port is opened rather than after.

The rule is shaped so it cannot break the working local app: loopback is
allowed exactly as before, everything else needs the token. So the tests that
matter are the ones proving both halves of that, and proving the refusals
cannot be talked around.
"""
import asyncio
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import access


def _app(token="secret-token"):
    application = FastAPI()
    application.add_middleware(access.RequireToken)

    @application.get("/health")
    async def health():
        return {"ok": True}

    @application.get("/private")
    async def private():
        return {"ok": True}

    patcher = mock.patch.object(access, "token", return_value=token)
    patcher.start()
    return application, patcher


class Loopback(unittest.TestCase):
    """The local app must keep working with no token and no change."""

    def setUp(self):
        self.app, self.patcher = _app()
        self.addCleanup(self.patcher.stop)

    def test_a_local_request_needs_no_token(self):
        with TestClient(self.app, client=("127.0.0.1", 50000)) as client:
            self.assertEqual(client.get("/private").status_code, 200)

    def test_loopback_is_recognised_in_all_its_spellings(self):
        for host in ("127.0.0.1", "::1", "[::1]", "127.0.0.53", "localhost"):
            self.assertTrue(access.is_loopback(host), host)

    def test_anything_else_is_not_loopback(self):
        for host in ("192.168.1.10", "10.0.0.4", "8.8.8.8", "example.com", "", None,
                     "127.0.0.1.evil.com"):
            self.assertFalse(access.is_loopback(host), repr(host))


class Remote(unittest.TestCase):
    def setUp(self):
        self.app, self.patcher = _app()
        self.addCleanup(self.patcher.stop)

    def _get(self, path, headers=None, params=None):
        # A genuinely remote client address, so the middleware takes the path
        # a phone would rather than the loopback shortcut.
        with TestClient(self.app, client=("203.0.113.9", 51000)) as client:
            return client.get(path, headers=headers or {}, params=params or {})

    def test_a_remote_request_without_a_token_is_refused(self):
        response = self._get("/private")
        self.assertEqual(response.status_code, 401)
        self.assertIn("access token", response.json()["detail"])

    def test_a_remote_request_with_the_token_is_allowed(self):
        response = self._get("/private", headers={"Authorization": "Bearer secret-token"})
        self.assertEqual(response.status_code, 200)

    def test_a_wrong_token_is_refused(self):
        for bad in ("Bearer wrong", "Bearer ", "Basic secret-token", "secret-token"):
            self.assertEqual(self._get("/private", headers={"Authorization": bad}).status_code,
                             401, bad)

    def test_the_query_fallback_works_for_clients_that_cannot_set_headers(self):
        """WebSockets and media elements cannot send an Authorization header."""
        self.assertEqual(self._get("/private", params={"access_token": "secret-token"}).status_code, 200)

    def test_health_is_reachable_without_a_token(self):
        """A phone or proxy has to be able to ask whether Nova is up, and the
        answer reveals nothing."""
        self.assertEqual(self._get("/health").status_code, 200)

    def test_no_other_path_is_public(self):
        self.assertEqual(access.PUBLIC_PATHS, frozenset({"/health"}))


class Tokens(unittest.TestCase):
    def test_a_token_is_created_once_and_reused(self):
        store = {}
        with mock.patch.object(access.config, "read_env_value", lambda n: store.get(n)), \
             mock.patch.object(access.config, "write_env_value",
                               lambda n, v: store.__setitem__(n, v) or v):
            first = access.token()
            second = access.token()
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), 32)

    def test_rotating_produces_a_different_token(self):
        store = {}
        with mock.patch.object(access.config, "read_env_value", lambda n: store.get(n)), \
             mock.patch.object(access.config, "write_env_value",
                               lambda n, v: store.__setitem__(n, v) or v):
            before = access.token()
            after = access.rotate()
        self.assertNotEqual(before, after)

    def test_comparison_is_constant_time(self):
        """A byte-at-a-time comparison leaks the token to anyone patient."""
        import inspect
        source = inspect.getsource(access.RequireToken.dispatch)
        self.assertIn("compare_digest", source)
        self.assertNotIn("supplied == ", source)


class PhoneAccess(unittest.TestCase):
    """The Settings > Access toggle (see AccessPanel.jsx) reads and writes
    these two."""

    def test_off_until_turned_on(self):
        store = {}
        with mock.patch.object(access.config, "read_env_value", lambda n: store.get(n)):
            self.assertFalse(access.phone_access_enabled())

    def test_toggles_and_reads_back(self):
        store = {}
        with mock.patch.object(access.config, "read_env_value", lambda n: store.get(n)), \
             mock.patch.object(access.config, "write_env_value",
                               lambda n, v: store.__setitem__(n, v) or v):
            access.set_phone_access(True)
            self.assertTrue(access.phone_access_enabled())
            access.set_phone_access(False)
            self.assertFalse(access.phone_access_enabled())

    def test_tailscale_address_is_ranked_first(self):
        """The whole point of Tailscale over a plain LAN IP: reachable from
        anywhere, not only this Wi-Fi -- so it has to be the one the link
        offers first, not just any address that happened to resolve first."""
        addrs = [("1.2.3.4", None), ("100.65.120.18", None), ("192.168.1.20", None)]
        with mock.patch("socket.getaddrinfo", return_value=[(None, None, None, None, (a, 0)) for a, _ in addrs]):
            ranked = access.lan_addresses()
        self.assertEqual(ranked[0], "100.65.120.18")

    def test_loopback_addresses_are_left_out(self):
        with mock.patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 0))]):
            self.assertEqual(access.lan_addresses(), [])


class TailscaleHttps(unittest.TestCase):
    """The only link a phone can run voice over -- see tailscale_https_url's
    own docstring for why."""

    def test_none_when_tailscale_is_not_installed(self):
        with mock.patch.object(access, "_tailscale_exe", return_value=None):
            self.assertIsNone(access.tailscale_https_url())

    def test_builds_https_from_the_magicdns_name(self):
        completed = mock.Mock(returncode=0, stdout='{"Self": {"DNSName": "nova-host.tail0000.ts.net."}}')
        with mock.patch.object(access, "_tailscale_exe", return_value="tailscale"), \
             mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(access.tailscale_https_url(), "https://nova-host.tail0000.ts.net")

    def test_none_when_not_logged_in_or_running(self):
        completed = mock.Mock(returncode=1, stdout="")
        with mock.patch.object(access, "_tailscale_exe", return_value="tailscale"), \
             mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(access.tailscale_https_url())

    def test_none_when_the_call_hangs_or_errors(self):
        with mock.patch.object(access, "_tailscale_exe", return_value="tailscale"), \
             mock.patch("subprocess.run", side_effect=TimeoutError()):
            self.assertIsNone(access.tailscale_https_url())


if __name__ == "__main__":
    unittest.main()


class Devices(unittest.TestCase):
    """Each remote device has its own key; removing one leaves the others working."""

    def setUp(self):
        self.app, self.patcher = _app()
        self.addCleanup(self.patcher.stop)
        rows = {}

        class Conn:
            def execute(self, sql, params):
                return mock.Mock(rowcount=1 if rows.pop((params[0], params[1]), None) else 0)

        from contextlib import contextmanager

        @contextmanager
        def transaction():
            yield Conn()

        from app import operator_store
        for name, fn in {"put": lambda kind, key, value, connection=None: rows.__setitem__((kind, key), value),
                         "listing": lambda kind: [v for (k, _), v in rows.items() if k == kind],
                         "transaction": transaction}.items():
            p = mock.patch.object(operator_store, name, fn)
            p.start()
            self.addCleanup(p.stop)
        access._device_cache = None
        self.addCleanup(lambda: setattr(access, "_device_cache", None))

    def get(self, key):
        with TestClient(self.app, client=("100.64.0.9", 50000)) as client:
            return client.get("/private", headers={"Authorization": f"Bearer {key}"} if key else {}).status_code

    def test_a_device_key_works_until_that_device_is_removed(self):
        phone, phone_key = access.add_device("Phone")
        tablet, tablet_key = access.add_device("Tablet")
        self.assertEqual(self.get(phone_key), 200)
        self.assertEqual(self.get(tablet_key), 200)
        self.assertEqual(self.get("secret-token"), 200)  # the original link still works
        self.assertEqual(self.get("made-up"), 401)
        self.assertTrue(access.remove_device(phone["id"]))
        self.assertEqual(self.get(phone_key), 401)
        self.assertEqual(self.get(tablet_key), 200)

    def test_keys_are_never_stored_or_listed(self):
        _device, key = access.add_device("Phone")
        listed = access.devices()
        self.assertEqual([d["name"] for d in listed], ["Phone"])
        self.assertNotIn(key, str(listed))
        self.assertNotIn(key, str(access._devices_by_hash()))
