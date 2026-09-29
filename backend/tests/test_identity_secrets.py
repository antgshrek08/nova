"""A password Nova can use must never be a password Nova can read.

The account feature exists so Nova can sign in to things the user set up in
its name. That is only safe while one property holds: the value reaches the
login field and nothing else -- not a prompt, not a tool result, not a row in
a table that gets listed back to a model.

The property is easy to state and easy to break by accident, because the
obvious implementation of "record an account with its password" is one table
with a password column. These tests fail if that ever happens.
"""
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1] / "app"
PKG = "identity_checks"
package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules[PKG] = package
for name in ("db", "secrets_store"):
    module = types.ModuleType(f"{PKG}.{name}")
    sys.modules[module.__name__] = module
    setattr(package, name, module)

import importlib.util  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


identity = load("identity")

SECRET = "correct-horse-battery-staple"


class Vault:
    """Stands in for the real keyring: stores values, and records every read."""

    def __init__(self):
        self.values = {}
        self.reads = []

    class SecretError(Exception):
        pass

    def put(self, name, value):
        self.values[name] = value
        return {"name": name}

    def get(self, name):
        self.reads.append(name)
        return self.values.get(name)

    def delete(self, name):
        return self.values.pop(name, None) is not None


class PasswordStaysInTheVault(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.vault = Vault()
        self.rows = {}
        package.secrets_store.put = self.vault.put
        package.secrets_store.get = self.vault.get
        package.secrets_store.delete = self.vault.delete
        package.secrets_store.SecretError = Vault.SecretError

        async def upsert(service, username, url, email, notes, has_password=False):
            self.rows[service] = dict(
                id=1, service=service, username=username, url=url, email=email,
                notes=notes, created_at="now", updated_at="now", has_password=has_password,
            )
            return dict(self.rows[service])

        async def listing():
            return [dict(r) for r in self.rows.values()]

        async def delete(service):
            return self.rows.pop(service, None) is not None

        package.db.upsert_account = upsert
        package.db.list_accounts = listing
        package.db.delete_account = delete

    async def test_the_password_is_never_written_to_the_account_row(self):
        row = await identity.add("github", "nova", password=SECRET)
        self.assertNotIn(SECRET, str(row))
        self.assertNotIn(SECRET, str(self.rows))
        self.assertTrue(row["has_password"])

    async def test_listing_accounts_never_carries_the_password(self):
        await identity.add("github", "nova", password=SECRET)
        self.assertNotIn(SECRET, str(await identity.listing()))

    async def test_what_the_model_is_told_never_carries_the_password(self):
        """The one that matters most: describe_for_model's output goes
        straight into a prompt."""
        await identity.add("github", "nova", url="https://github.com", password=SECRET)
        described = str(await identity.describe_for_model())
        self.assertNotIn(SECRET, described)
        # It should still be useful -- knowing the account exists is the point.
        self.assertIn("github", described)
        self.assertIn("nova", described)

    async def test_the_password_does_reach_the_vault(self):
        """The mirror of the above: a secret nobody stored is not secure,
        it is missing."""
        await identity.add("github", "nova", password=SECRET)
        self.assertEqual(self.vault.values[identity.secret_name("github")], SECRET)

    async def test_secret_names_are_namespaced_so_accounts_cannot_clobber_secrets(self):
        self.assertTrue(identity.secret_name("github").startswith(identity.SECRET_PREFIX))
        self.assertNotEqual(identity.secret_name("github"), "github")

    async def test_secret_names_survive_the_vaults_own_validator(self):
        """identity's service rule is a subset of secrets_store's name rule.
        If it ever stops being one, a save fails after writing a row."""
        import re
        allowed = re.compile(r"^[A-Za-z0-9 ._-]{1,49}$")
        for service in ("github", "some forum", "my-site.com", "a" * 39):
            self.assertRegex(identity.secret_name(service), allowed)

    async def test_forgetting_an_account_removes_the_password_too(self):
        """A vault entry whose account row is gone is one nobody can
        identify, and therefore one nobody ever deletes."""
        await identity.add("github", "nova", password=SECRET)
        await identity.forget("github")
        self.assertEqual(self.rows, {})
        self.assertEqual(self.vault.values, {})

    async def test_has_password_is_read_from_the_vault_not_the_row(self):
        """The vault is the authority. A password removed from the Secrets
        screen must show as absent here, not as present because a stale
        column says so."""
        await identity.add("github", "nova", password=SECRET)
        self.vault.values.clear()
        self.assertFalse((await identity.listing())[0]["has_password"])


class OneAccountIsOneAccount(unittest.IsolatedAsyncioTestCase):
    """`accounts.service` is a case-sensitive primary key and `secret_name`
    lowercases, so "Instagram" and "instagram" were two rows sharing one
    vault entry. The second save silently replaced the first's password
    while both rows kept claiming to have their own, and sign_in -- which
    lowercases to look up -- picked whichever it happened to see first.
    """

    async def asyncSetUp(self):
        self.vault = Vault()
        self.rows = {}
        package.secrets_store.put = self.vault.put
        package.secrets_store.get = self.vault.get
        package.secrets_store.delete = self.vault.delete
        package.secrets_store.SecretError = Vault.SecretError

        async def upsert(service, username, url, email, notes, has_password=False):
            self.rows[service] = dict(
                id=1, service=service, username=username, url=url, email=email,
                notes=notes, created_at="now", updated_at="now", has_password=has_password,
            )
            return dict(self.rows[service])

        package.db.upsert_account = upsert
        package.db.list_accounts = lambda: _rows(self.rows)
        package.db.delete_account = lambda service: _pop(self.rows, service)

    async def test_re_adding_with_different_capitals_updates_the_same_row(self):
        await identity.add("instagram", "nova.gpt", password=SECRET)
        await identity.add("Instagram", "nova.gpt", password="a-newer-password")
        self.assertEqual(list(self.rows), ["instagram"])
        self.assertEqual(len(self.vault.values), 1)

    async def test_the_users_own_spelling_is_kept_for_a_new_account(self):
        """Only an existing row overrides the casing -- nothing is silently
        lowercased on the way in."""
        await identity.add("GitHub", "nova")
        self.assertEqual(list(self.rows), ["GitHub"])

    async def test_forgetting_finds_the_row_whatever_case_is_typed(self):
        await identity.add("GitHub", "nova", password=SECRET)
        await identity.forget("github")
        self.assertEqual(self.rows, {})
        self.assertEqual(self.vault.values, {})


async def _rows(rows):
    return [dict(r) for r in rows.values()]


async def _pop(rows, service):
    return rows.pop(service, None) is not None


if __name__ == "__main__":
    unittest.main()
