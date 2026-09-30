"""Who is allowed to talk to this backend.

Nova has never had authentication. That has been survivable for exactly one
reason: it binds 127.0.0.1, so only this machine can reach it. Everything
behind that binding is unguarded -- run_command, write_file, delete_path, the
desktop tools, the secrets vault -- so the day anything reaches it from
outside, there is no second line.

That day is the point of the mobile app: texting and calling Nova from a
phone means something that is not this machine reaching this backend. So the
binding stops being the security model and has to be replaced by one.

The rule here is deliberately shaped so it cannot break the working local
app, because the failure mode of getting authentication wrong is locking the
user out of their own assistant:

- A request from loopback is allowed, as today. The Electron app keeps
  working with no token and no change.
- A request from anywhere else needs the token, and without one is refused.
  Today nothing else can reach the port at all, so this changes nothing in
  practice -- it is the piece that has to exist *before* the port is opened,
  not after.

The token is generated once, stored beside every other secret, and never
logged or returned by a normal endpoint. Comparison is constant-time: the
cost is nothing and the alternative leaks the token a byte at a time.
"""
from __future__ import annotations

import ipaddress
import logging
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from . import config

TOKEN_NAME = "NOVA_ACCESS_TOKEN"
_HEADER = "authorization"
_QUERY_NAMES = ("token", "access_token")

# Reachable without a token from anywhere: a health check is how a phone, a
# reverse proxy or the user finds out whether Nova is up, and it reveals
# nothing. Everything else is closed.
PUBLIC_PATHS = frozenset({"/health"})

# The web app's own files. A <script src> is issued by the browser and cannot
# carry a header, so protecting the bundle would mean the page loads and then
# does nothing -- which is what happened the first time. Serving it openly
# costs nothing: it is the same compiled frontend that sits in a public git
# repository, and it holds no data. Every API route it then calls is still
# behind the token, which is where the user's files, machine and secrets are.
PUBLIC_PREFIXES = ("/app",)

logger = logging.getLogger(__name__)


def token() -> str:
    """The access token, creating one the first time it is needed."""
    existing = config.read_env_value(TOKEN_NAME)
    if existing:
        return existing
    fresh = secrets.token_urlsafe(32)
    config.write_env_value(TOKEN_NAME, fresh)
    logger.info("Generated a Nova access token for non-local requests.")
    return fresh


def rotate() -> str:
    """Replace the token. Anything holding the old one stops working, which
    is the entire point of being able to do this."""
    fresh = secrets.token_urlsafe(32)
    config.write_env_value(TOKEN_NAME, fresh)
    return fresh


def is_loopback(host: str | None) -> bool:
    """Whether a client address is this machine.

    Parsed rather than string-matched: "127.0.0.1" is not the only loopback
    address, and a check that only knows that one would refuse a legitimate
    ::1 request while feeling thorough.
    """
    if not host:
        return False
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        # A name, not an address. Only the one name that can only ever mean
        # this machine -- and notably not "127.0.0.1.evil.com", which a
        # substring check would have accepted.
        return host == "localhost"


def presented(request: Request) -> str | None:
    """The token this request carries, from the header or the query string.

    The query string exists for WebSockets and for a media element that
    cannot set headers. It is a worse place for a secret -- query strings end
    up in logs -- so the header is preferred and the query is the fallback.
    """
    header = request.headers.get(_HEADER, "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    # Two spellings because two things use this. "token" is what the setup
    # link carries, since that link is the one moment the page itself has no
    # token yet and cannot send a header -- it has to load before it can
    # store anything. "access_token" is the conventional name, used by
    # WebSockets and media elements that also cannot set headers.
    for name in _QUERY_NAMES:
        value = request.query_params.get(name)
        if value:
            return value
    return None


class RequireToken(BaseHTTPMiddleware):
    """Loopback as today; anything else must present the token."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (request.method == "OPTIONS"
                or path in PUBLIC_PATHS
                or path.startswith(PUBLIC_PREFIXES)):
            return await call_next(request)

        client = request.client.host if request.client else None
        if is_loopback(client):
            return await call_next(request)

        supplied = presented(request)
        if supplied and (secrets.compare_digest(supplied, token()) or device_for(supplied)):
            return await call_next(request)

        # Logged because a refused remote request is worth knowing about, and
        # said without detail because the response is read by whoever sent it.
        logger.warning("Refused an unauthenticated request from %s to %s",
                       client, request.url.path)
        return JSONResponse(
            {"detail": "This Nova requires an access token. See Settings > Access."},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )


PHONE_ACCESS_NAME = "NOVA_PHONE_ACCESS"


def phone_access_enabled() -> bool:
    return config.read_env_value(PHONE_ACCESS_NAME) == "1"


def set_phone_access(enabled: bool) -> bool:
    """Turn listening beyond this machine on or off.

    Takes effect at the next restart, because the bind address is fixed for
    the life of the uvicorn process -- Electron reads this at spawn time (see
    electron/main.cjs's phoneAccessEnabled).
    """
    config.write_env_value(PHONE_ACCESS_NAME, "1" if enabled else "0")
    return enabled


_TAILSCALE_CANDIDATES = (
    "tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    "/usr/local/bin/tailscale",
    "/opt/homebrew/bin/tailscale",
)


def _tailscale_exe() -> str | None:
    import os
    import shutil
    for candidate in _TAILSCALE_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
        if os.path.isfile(candidate):
            return candidate
    return None


def tailscale_https_url() -> str | None:
    """This machine's stable, from-anywhere HTTPS address -- MagicDNS name
    over the tailnet's own HTTPS certs (`tailscale cert`) -- if Tailscale is
    installed and running, else None. Voice and anything else needing a
    secure context only works over this, not over a plain http:// address:
    a browser treats a non-loopback http:// origin as insecure regardless of
    Tailscale's own encryption underneath it.

    This says Tailscale is reachable, not that `tailscale serve` has been
    pointed at Nova -- that is a one-time `tailscale serve --bg
    http://127.0.0.1:8000` on this machine (see Settings > Access), checking
    live here would mean another subprocess call on every status read for a
    setting that, once made, does not change.
    """
    import json
    import subprocess
    exe = _tailscale_exe()
    if not exe:
        return None
    try:
        result = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=3)
        if result.returncode != 0:
            return None
        name = (json.loads(result.stdout).get("Self") or {}).get("DNSName", "").rstrip(".")
        return f"https://{name}" if name else None
    except Exception:  # noqa: BLE001 -- not installed, not running, timed out: just not available
        return None


def lan_addresses() -> list[str]:
    """Addresses another device could plausibly reach this machine on.

    Tailscale's 100.64.0.0/10 range is listed first when present: it is the
    one that works from anywhere rather than only on this Wi-Fi, which is the
    difference between "Nova on my phone" and "Nova on my phone at home".
    """
    import socket

    found: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address not in found and not address.startswith("127."):
                found.append(address)
    except Exception:  # noqa: BLE001 -- a name lookup failing is not fatal here
        pass

    def rank(address: str) -> int:
        first, second = (address.split(".") + ["0", "0"])[:2]
        if first == "100" and 64 <= int(second or 0) <= 127:
            return 0  # Tailscale: reachable from anywhere
        return 1

    return sorted(found, key=rank)


def phone_readiness() -> dict:
    """Where this machine is in the phone setup, for a step-by-step guide.

    installed -> signed in -> Nova served over the tailnet's HTTPS -> phone
    access on. Each is checked live, so the guide never claims a step is done
    that isn't, and a missing one says what to do next."""
    import json
    import subprocess
    exe = _tailscale_exe()
    out = {"tailscale_installed": bool(exe), "signed_in": False, "https_url": None, "serving_nova": False,
           "phone_access": config.read_env_value(PHONE_ACCESS_NAME) == "1", "lan": lan_addresses()}
    if not exe:
        return out
    try:
        st = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=4)
        data = json.loads(st.stdout or "{}") if st.returncode == 0 else {}
        out["signed_in"] = data.get("BackendState") == "Running"
        name = (data.get("Self") or {}).get("DNSName", "").rstrip(".")
        out["https_url"] = f"https://{name}" if name and out["signed_in"] else None
        sv = subprocess.run([exe, "serve", "status"], capture_output=True, text=True, timeout=4)
        text = (sv.stdout or "") + (sv.stderr or "")
        out["serving_nova"] = "127.0.0.1:8000" in text or "localhost:8000" in text
    except Exception:  # noqa: BLE001 -- a hung or old CLI reads as "not set up yet"
        pass
    return out


def serve_nova() -> dict:
    """`tailscale serve --bg http://127.0.0.1:8000`: Nova's HTTPS address on
    the user's tailnet only (never the public internet)."""
    import subprocess
    exe = _tailscale_exe()
    if not exe:
        raise RuntimeError("Tailscale isn't installed on this computer.")
    r = subprocess.run([exe, "serve", "--bg", "http://127.0.0.1:8000"], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip()
        if "HTTPS" in detail or "https" in detail:
            detail += " Turn on HTTPS certificates for your tailnet at login.tailscale.com/admin/dns, then try again."
        raise RuntimeError(detail[:400] or "tailscale serve failed.")
    return phone_readiness()


# ---------------------------------------------------------------- devices
#
# Each phone (or other computer) that uses this Nova remotely gets its own
# key, added and removed in Settings > Remote. Removing one device leaves the
# others working. Only a hash of each key is stored.

import hashlib
import time as _time
import uuid as _uuid

DEVICE = "remote_device"
_device_cache: dict[str, dict] | None = None  # key hash -> device
_SEEN_EVERY = 60


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _devices_by_hash() -> dict[str, dict]:
    global _device_cache
    if _device_cache is None:
        from . import operator_store
        _device_cache = {d["key_hash"]: d for d in operator_store.listing(DEVICE) if d.get("key_hash")}
    return _device_cache


def devices() -> list[dict]:
    """Paired devices, newest first -- names and times only, never keys."""
    rows = sorted(_devices_by_hash().values(), key=lambda d: d.get("created_at", 0), reverse=True)
    return [{k: d.get(k) for k in ("id", "name", "created_at", "last_seen")} for d in rows]


def add_device(name: str) -> tuple[dict, str]:
    """A new device and its key (shown once, in the setup link)."""
    global _device_cache
    from . import operator_store
    name = (str(name or "").strip() or "My phone")[:40]
    key = secrets.token_urlsafe(32)
    device = {"id": _uuid.uuid4().hex[:10], "name": name, "key_hash": _hash(key), "created_at": _time.time(), "last_seen": None}
    operator_store.put(DEVICE, device["id"], device)
    _device_cache = None
    return {k: device[k] for k in ("id", "name", "created_at", "last_seen")}, key


def remove_device(device_id: str) -> bool:
    global _device_cache
    from . import operator_store
    with operator_store.transaction() as conn:
        gone = conn.execute("DELETE FROM records WHERE kind=? AND id=?", (DEVICE, device_id)).rowcount
    _device_cache = None
    return bool(gone)


def device_for(key: str | None) -> dict | None:
    """The device this key belongs to (and note that it was just seen)."""
    if not key:
        return None
    device = _devices_by_hash().get(_hash(key))
    if device and (_time.time() - (device.get("last_seen") or 0)) > _SEEN_EVERY:
        device["last_seen"] = _time.time()
        try:
            from . import operator_store
            operator_store.put(DEVICE, device["id"], device)
        except Exception:  # noqa: BLE001 -- a missed "last seen" is not worth failing a request
            pass
    return device


def computer_name() -> str:
    import platform
    return (platform.node() or "your computer").split(".")[0]
