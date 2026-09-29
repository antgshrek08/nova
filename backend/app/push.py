"""Nova reaching the phone first.

Everything else in Nova waits to be asked. This is the one channel that runs
the other way: Nova notices something and says so, whether or not the app is
open. "I want nova to text me whenever" was the ask, and on a phone the honest
implementation of "text me" is a Web Push notification, because it is the only
thing that reaches a locked screen without an App Store listing, a developer
account, or a Mac to build on.

Two constraints shape the whole design.

iOS only delivers Web Push to a site the user has added to the Home Screen.
Not Safari, not a tab, not a bookmark -- an installed PWA. There is no way
around it and no way to detect it server-side, so the subscribe endpoint
records what the browser reports and the UI explains the Home Screen step
rather than failing silently when the permission prompt never appears.

The VAPID key pair is this server's identity to the push services. It is
generated once, stored outside the repo next to the database, and the private
half never leaves the machine. Regenerating it invalidates every existing
subscription, so it is created only when absent.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from . import config, db

logger = logging.getLogger(__name__)

# Beside the database rather than in the repo, for the same reason the
# database is: this is per-installation state, and a key pair committed to git
# is a key pair that is no longer private. Learned the expensive way with a
# Tailscale cert earlier in this project.
KEY_PATH = Path(config.DB_PATH).parent / "vapid-keys.json"

# Push services want a contact for the application server. mailto: is what the
# spec suggests; it is never shown to the user and never sent anywhere else.
VAPID_SUBJECT = "mailto:nova@localhost"

_lock = asyncio.Lock()


def _generate() -> dict:
    from py_vapid import Vapid01
    from cryptography.hazmat.primitives import serialization
    import base64

    vapid = Vapid01()
    vapid.generate_keys()
    private_pem = vapid.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    # The public key goes to the browser in the form PushManager.subscribe
    # wants: raw uncompressed EC point, base64url, no padding.
    raw = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return {"private_pem": private_pem, "public_key": public_b64}


async def keys() -> dict:
    """The server's VAPID pair, generated on first use and reused after.

    Never regenerated automatically. Every subscription a browser has handed
    out is bound to the public half, so a fresh pair would silently orphan
    every device the user had already set up.
    """
    async with _lock:
        if KEY_PATH.exists():
            try:
                return json.loads(KEY_PATH.read_text("utf-8"))
            except OSError as exc:
                # A read that failed is not a key pair that is gone. The file
                # is there; something transient -- a lock, a permissions
                # change, a disk hiccup -- stopped this one read. Regenerating
                # here would overwrite a perfectly good pair and silently
                # unsubscribe every device the user had set up, which is the
                # one thing this function's docstring promises not to do.
                raise RuntimeError(
                    f"Couldn't read the push key file at {KEY_PATH} ({exc}). Not regenerating: "
                    "that would disconnect every device already set up for notifications."
                ) from exc
            except json.JSONDecodeError as exc:
                # Genuinely corrupt content, so a new pair is the only way
                # forward -- but the old bytes are kept, because "the file was
                # truncated and the real key was recoverable" is a thing that
                # happens and an overwrite makes it not.
                backup = KEY_PATH.with_suffix(".json.corrupt")
                try:
                    KEY_PATH.replace(backup)
                    logger.error("VAPID key file was corrupt (%s); kept it at %s", exc, backup)
                except OSError as backup_error:
                    raise RuntimeError(
                        "Couldn't preserve the corrupt push key file. Not regenerating "
                        "or overwriting it; restore access to the backup location first."
                    ) from backup_error
        generated = await asyncio.to_thread(_generate)
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        KEY_PATH.write_text(json.dumps(generated), encoding="utf-8")
        try:  # best effort; Windows ignores it and that is fine
            KEY_PATH.chmod(0o600)
        except OSError:
            pass
        logger.info("Generated a new VAPID key pair at %s", KEY_PATH)
        return generated


async def public_key() -> str:
    return (await keys())["public_key"]


async def subscribe(subscription: dict, label: str | None = None) -> dict:
    """Record a device. Idempotent on the endpoint URL.

    The endpoint is the device's address and is unique per browser install,
    so re-subscribing from the same phone updates that row rather than
    accumulating duplicates that would each deliver the same notification.
    """
    endpoint = (subscription or {}).get("endpoint")
    if not endpoint:
        raise ValueError("That subscription has no endpoint.")
    keys_blob = (subscription or {}).get("keys") or {}
    if not keys_blob.get("p256dh") or not keys_blob.get("auth"):
        raise ValueError("That subscription is missing its encryption keys.")
    return await db.upsert_push_subscription(endpoint, json.dumps(subscription), label)


def _send_one(subscription: dict, payload: str, private_pem: str) -> tuple[bool, str]:
    """Blocking send for one device. Returns (keep_subscription, detail)."""
    from pywebpush import webpush, WebPushException

    try:
        webpush(
            subscription_info=subscription,
            data=payload,
            vapid_private_key=private_pem,
            vapid_claims={"sub": VAPID_SUBJECT},
            timeout=10,
        )
        return True, "sent"
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        # 404/410 mean the browser threw this subscription away -- the app was
        # uninstalled, or site data was cleared. Those are permanent, and
        # keeping the row would retry a dead endpoint on every notification
        # forever. Anything else (network blip, push service 5xx) is kept.
        if status in (404, 410):
            return False, f"expired ({status})"
        return True, f"failed ({status or type(exc).__name__})"
    except Exception as exc:  # noqa: BLE001
        # Everything that is not the push service saying no: an unparseable
        # p256dh raises ValueError out of cryptography before a request is
        # ever made, and a stored row with one would otherwise 500 the whole
        # send and take every other device down with it. The row is dropped
        # because a subscription whose keys cannot be read will never work,
        # and retrying it nightly forever is the same bug with a slower clock.
        logger.warning("Dropping unusable push subscription: %s", exc)
        return False, f"unusable ({type(exc).__name__})"


async def send(title: str, body: str, *, url: str = "/app/", tag: str | None = None) -> dict:
    """Push to every registered device.

    Returns a summary rather than raising: a notification failing to reach a
    phone must never take down whatever noticed it was worth sending. The
    caller logs and moves on.
    """
    rows = await db.list_push_subscriptions()
    if not rows:
        return {"ok": False, "sent": 0, "reason": "no devices are registered for notifications"}

    private_pem = (await keys())["private_pem"]
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag or "nova"})

    sent, dropped, details = 0, 0, []
    for row in rows:
        try:
            subscription = json.loads(row["subscription"])
        except json.JSONDecodeError:
            await db.delete_push_subscription(row["endpoint"])
            dropped += 1
            continue
        keep, detail = await asyncio.to_thread(_send_one, subscription, payload, private_pem)
        if keep:
            if detail == "sent":
                sent += 1
            else:
                details.append(detail)
        else:
            await db.delete_push_subscription(row["endpoint"])
            dropped += 1
            details.append(detail)
    return {"ok": sent > 0, "sent": sent, "dropped": dropped, "details": details}
