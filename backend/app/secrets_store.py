"""Secrets Nova can use but never see.

The problem this solves: for Nova to type a password, the password has to be in
the prompt. That means it reaches whichever provider answered that turn, gets
written to the chat transcript, and is embedded into the memory index. Removing
the window-title guard from desktop.py did not change any of that -- it only
removed the last check.

Here the model asks for a secret *by name*. The value is fetched at type time
inside this process, typed straight into the focused window or browser field,
and never appears in a prompt, a tool argument, a tool result, or the
transcript. The model learns that "github" was typed, not what it was.

Storage is Windows Credential Manager via keyring when available, so the value
sits in the same vault the OS uses for everything else and is protected by the
user's login. The encrypted-file fallback exists for machines without it and is
honestly weaker -- the key lives beside the data, so it protects against a
casual read of the file, not against someone with the user's account.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path

from . import config

SERVICE = "nova-secrets"
FALLBACK_PATH = config.USER_DATA_DIR / "secrets.dat"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9 ._-]{0,48}$", re.IGNORECASE)


class SecretError(RuntimeError):
    """Storage or lookup failure, phrased for display. Never contains a value."""


def _keyring():
    try:
        import keyring
        # A backend that silently does nothing is worse than no backend: the
        # save would appear to succeed and the value would be gone.
        from keyring.backends.fail import Keyring as FailKeyring
        if isinstance(keyring.get_keyring(), FailKeyring):
            return None
        return keyring
    except Exception:  # noqa: BLE001 - keyring missing or no usable backend
        return None


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_RE.fullmatch(name):
        raise SecretError("A secret name must be 1-49 characters: letters, digits, spaces, dot, dash, underscore.")
    return name.lower()


# --- encrypted-file fallback ----------------------------------------------
def _fallback_key() -> bytes:
    seed = f"{os.environ.get('USERNAME', '')}|{os.environ.get('COMPUTERNAME', '')}|{FALLBACK_PATH}"
    return hashlib.sha256(seed.encode()).digest()


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _read_fallback() -> dict:
    if not FALLBACK_PATH.exists():
        return {}
    try:
        return json.loads(_xor(base64.b64decode(FALLBACK_PATH.read_bytes()), _fallback_key()).decode())
    except Exception:  # noqa: BLE001 - corrupt or from another machine
        return {}


def _write_fallback(values: dict) -> None:
    FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    FALLBACK_PATH.write_bytes(base64.b64encode(_xor(json.dumps(values).encode(), _fallback_key())))
    try:
        os.chmod(FALLBACK_PATH, 0o600)
    except OSError:
        pass


# --- public API ------------------------------------------------------------
def backend_name() -> str:
    return "Windows Credential Manager" if _keyring() else "encrypted file (weaker)"


def put(name: str, value: str) -> dict:
    name = _check_name(name)
    if not value:
        raise SecretError("Refusing to store an empty secret.")
    ring = _keyring()
    if ring:
        ring.set_password(SERVICE, name, value)
    else:
        values = _read_fallback()
        values[name] = value
        _write_fallback(values)
    index = set(_index())
    index.add(name)
    _write_index(sorted(index))
    return {"name": name, "stored_in": backend_name()}


def get(name: str) -> str | None:
    """Only ever called from inside this process, by type_secret. The value is
    never returned to a model."""
    name = _check_name(name)
    ring = _keyring()
    if ring:
        return ring.get_password(SERVICE, name)
    return _read_fallback().get(name)


def delete(name: str) -> bool:
    name = _check_name(name)
    ring = _keyring()
    existed = False
    if ring:
        try:
            existed = ring.get_password(SERVICE, name) is not None
            ring.delete_password(SERVICE, name)
        except Exception:  # noqa: BLE001 - not present
            pass
    else:
        values = _read_fallback()
        existed = name in values
        values.pop(name, None)
        _write_fallback(values)
    _write_index([n for n in _index() if n != name])
    return existed


# keyring has no "list everything for this service" call, so names are tracked
# separately. Names only -- never values.
_INDEX_PATH = config.USER_DATA_DIR / "secret-names.json"


def _index() -> list[str]:
    try:
        return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - absent or corrupt
        return []


def _write_index(names: list[str]) -> None:
    _INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    _INDEX_PATH.write_text(json.dumps(sorted(set(names))), encoding="utf-8")


def names() -> list[str]:
    """What Nova is allowed to know: which secrets exist, not what they are."""
    return _index()
