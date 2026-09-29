"""The accounts Nova holds in its own name.

secrets_store already answers "what is the password". This answers the
questions around it: which service, which username, which address it was
registered under, whether the signup was ever confirmed, and where to go to
sign in. Without that, an account Nova is meant to use is a bare string in a
vault named "github" and nobody -- including Nova -- can tell whose login it
is or whether it works.

The distinction that matters: this is a record of accounts *created by the
user* in Nova's name. Nova does not sign itself up for anything. Automated
account creation needs CAPTCHA defeat and breaks the terms of nearly every
site that has them, so the human step stays a human step. What Nova does is
everything either side of it -- hold the address the confirmation goes to,
read the code out of it, remember which username went with which site, and
sign in later using a password it can use but never read.

Values live in secrets_store under a namespaced name; only the metadata is
here. So this table can be read, listed, exported and shown to a model
freely: the worst it ever discloses is that an account exists.
"""
from __future__ import annotations

import re
import asyncio

from . import db, secrets_store

# Namespaced so an account's password cannot collide with a hand-added secret
# of the same name, and so deleting an account cannot delete something else.
#
# A dot rather than a colon because secrets_store validates names against
# "letters, digits, spaces, dot, dash, underscore" and rejects anything else.
# Widening that validator to fit a prefix would be the wrong trade: it guards
# what becomes a Credential Manager entry name, and this side can simply use a
# character it already allows.
SECRET_PREFIX = "account."

# Canonicalization, vault mutation, and row mutation form one operation.
# Otherwise two simultaneous saves can both see no row and create differently
# cased accounts that share a single password entry.
_account_lock = asyncio.Lock()

# Deliberately a subset of what secrets_store accepts, and short enough that
# SECRET_PREFIX plus the service still fits its 49-character limit. Validating
# here against the downstream rule means a name is rejected at the form, with
# the field to fix named, rather than halfway through a save that has already
# written a row.
_SERVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}$")


class IdentityError(Exception):
    """Something the user can fix, safe to show."""


def secret_name(service: str) -> str:
    return f"{SECRET_PREFIX}{service.strip().lower()}"


def _check_service(service: str) -> str:
    service = (service or "").strip()
    if not _SERVICE_RE.match(service):
        raise IdentityError(
            "Give the service a simple name -- letters, numbers, spaces, dots or dashes."
        )
    return service


async def _canonical_service(service: str) -> str:
    """The spelling an existing row already uses, if there is one.

    `accounts.service` is a case-sensitive primary key, while `secret_name`
    lowercases. So "Instagram" and "instagram" are two rows sharing one vault
    entry: adding the second overwrites the first's password while both rows
    keep claiming they have one, and sign_in -- which lowercases to look up --
    silently picks whichever it sees first. Resolving to the stored spelling
    keeps one account one account, without lowercasing what the user typed or
    needing a migration to make the column case-insensitive.
    """
    service = _check_service(service)
    lowered = service.lower()
    for row in await db.list_accounts():
        if (row.get("service") or "").lower() == lowered:
            return row["service"]
    return service


async def add(service: str, username: str, url: str | None = None,
              email: str | None = None, password: str | None = None,
              notes: str | None = None) -> dict:
    """Record an account. The password, if given, goes to the vault only."""
    async with _account_lock:
        return await _add(service, username, url, email, password, notes)


async def _add(service, username, url, email, password, notes) -> dict:
    service = await _canonical_service(service)
    if not (username or "").strip():
        raise IdentityError("An account needs a username or login.")
    if password:
        try:
            secrets_store.put(secret_name(service), password)
        except secrets_store.SecretError as exc:
            # A vault that refuses the name is a 400, not a 500: the service
            # name the user typed is the thing to fix.
            raise IdentityError(f"Couldn't store that password: {exc}") from exc
    return await db.upsert_account(
        service=service,
        username=username.strip(),
        url=(url or "").strip() or None,
        email=(email or "").strip() or None,
        notes=(notes or "").strip() or None,
        has_password=bool(password) or secrets_store.get(secret_name(service)) is not None,
    )


async def forget(service: str) -> dict:
    """Remove the record and the stored password together.

    Deleting one without the other is how a vault fills with secrets nobody
    can identify: a password named "account:someforum" with no row to say what
    it was for is unremovable in practice, because nobody dares.
    """
    async with _account_lock:
        return await _forget(service)


async def _forget(service: str) -> dict:
    service = await _canonical_service(service)
    removed_secret = secrets_store.delete(secret_name(service))
    removed_row = await db.delete_account(service)
    if not removed_row and not removed_secret:
        raise IdentityError(f"No account recorded for '{service}'.")
    return {"ok": True, "service": service, "password_removed": removed_secret}


async def listing() -> list[dict]:
    """Every account, metadata only. Safe to show a model."""
    rows = await db.list_accounts()
    for row in rows:
        # Recomputed rather than trusted: the vault is the authority on
        # whether a password exists, and the two can drift if a secret is
        # removed from the Secrets screen directly.
        #
        # This was briefly changed to consult secrets_store.names() instead,
        # to avoid decrypting a password just to answer a yes/no question.
        # That is cheaper and it is wrong: names() reads an index file, so a
        # secret removed out of band still appears in it, and the account
        # would keep claiming it could sign in. The value never leaves this
        # function either way; the staleness would have been permanent.
        row["has_password"] = secrets_store.get(secret_name(row["service"])) is not None
    return rows


async def describe_for_model() -> dict:
    """What Nova is told about its own accounts.

    Names, usernames and sites -- never a password, and never a hint at one.
    The useful fact for the model is which services it already has a login
    for, so it can say "you already have an account there" instead of
    suggesting one be made.
    """
    rows = await listing()
    if not rows:
        return {"accounts": [], "note": "No accounts are recorded in Nova's name yet."}
    return {
        "accounts": [
            {
                "service": r["service"],
                "username": r["username"],
                "url": r["url"],
                "registered_to": r["email"],
                "can_sign_in": r["has_password"],
            }
            for r in rows
        ],
        "note": (
            "Passwords are stored where you cannot read them. To sign in, use type_secret "
            f"with the name '{SECRET_PREFIX}<service>' -- the value is typed for you and never "
            "shown. You cannot create new accounts; the user makes those."
        ),
    }
