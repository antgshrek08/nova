"""OAuth 2.0 (authorization code + PKCE) support for remote MCP servers --
see mcp_manager.py for where this actually gets used, and main.py's
/mcp/servers/{id}/connect + /mcp/oauth/callback for the two HTTP endpoints
that drive it.

Scope for this session: the mechanism is real and complete end to end --
dynamic client registration, DB-backed token/client-info persistence, a
real callback endpoint, token refresh (all handled by the SDK's own
OAuthClientProvider once wired up here) -- but it has not been exercised
against a real provider (Gmail/Calendar/Notion) tonight. That needs a human
actually clicking through a real consent screen in a browser, which isn't a
good fit for a time-boxed, unattended session; left in a clean,
add-a-server-and-click-Connect-when-ready state instead.

The pending-flow registry below is the same asyncio.Event pending-action
pattern as desktop_registry.py, for the same reason: a real pause on a real
user action (completing sign-in in their browser), not a poll loop --
/mcp/servers/{id}/connect starts the connection attempt as a background
task and races it against this registry's auth_url_ready event so it can
return the sign-in link to the frontend the moment the SDK asks for one,
without blocking on the whole flow; /mcp/oauth/callback resolves the
matching entry's result_ready event once the provider redirects back.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from mcp.client.auth import OAuthClientProvider
from mcp.client.auth.oauth2 import TokenStorage
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)

from . import config, db

# ---------------------------------------------------------------------------
# WORKAROUND for a known bug in the upstream `mcp` Python SDK (confirmed on
# v2.1.1, the latest published version as of writing -- NOT fixed upstream
# yet). Remove this whole block once a newer `mcp` release fixes the real
# issue; nothing else in this file depends on it existing.
#
# The bug: mcp.client.auth.utils.validate_metadata_issuer() does a strict
# RFC 8414 byte-exact string comparison between two URLs that are supposed
# to identify the same OAuth authorization server:
#   - the `authorization_servers` entry from the MCP resource server's own
#     Protected Resource Metadata (RFC 9728) -- for Gmail/Calendar's MCP
#     endpoints this is "https://accounts.google.com/" (WITH a trailing
#     slash)
#   - the `issuer` field in that same server's real Authorization Server
#     Metadata document (RFC 8414) -- Google publishes this as
#     "https://accounts.google.com" (NO trailing slash)
# Google's own two endpoints simply disagree on the URL's exact string
# form, so the SDK's real (and otherwise correct/important) issuer-pinning
# check fails on every single real Google OAuth attempt, before a sign-in
# URL is ever produced. Reproduced live: a direct call through
# mcp_manager.call_tool_from_row against a connected Gmail server raised
# `mcp.client.auth.exceptions.OAuthFlowError: Authorization server metadata
# issuer mismatch: https://accounts.google.com != https://accounts.google.com/`.
#
# The fix: normalize a trailing slash off both sides before comparing --
# the narrowest change that preserves the actual security property (a
# genuinely different issuer is still rejected; only a trailing-slash
# formatting difference is tolerated, which is standard RFC 3986 6.2.2.1
# "add/remove trailing slash on an authority-only path" normalization).
#
# Mechanics: oauth2.py does `from mcp.client.auth.utils import
# validate_metadata_issuer`, which binds the function object directly into
# oauth2's own module namespace at import time -- patching
# `mcp.client.auth.utils.validate_metadata_issuer` alone would NOT affect
# oauth2.py's already-bound reference. Both are patched below so every call
# path sees the fix.
import mcp.client.auth.oauth2 as _mcp_oauth2
import mcp.client.auth.utils as _mcp_auth_utils
from mcp.client.auth import OAuthFlowError as _OAuthFlowError


def _validate_metadata_issuer_tolerant(oauth_metadata, expected_issuer: str) -> None:
    actual = str(oauth_metadata.issuer).rstrip("/")
    expected = str(expected_issuer).rstrip("/")
    if actual != expected:
        raise _OAuthFlowError(
            f"Authorization server metadata issuer mismatch: {oauth_metadata.issuer} != {expected_issuer}"
        )


_mcp_oauth2.validate_metadata_issuer = _validate_metadata_issuer_tolerant
_mcp_auth_utils.validate_metadata_issuer = _validate_metadata_issuer_tolerant
# --- end workaround ---------------------------------------------------------

# Single shared redirect URI for every remote server -- the OAuth `state`
# param (not the redirect URI itself) is what correlates a provider's
# callback back to the specific server's in-flight flow (see
# _pending_by_state below), so one registered URI is enough regardless of
# how many remote servers are configured.
REDIRECT_URI = f"{config.MCP_OAUTH_CALLBACK_BASE_URL}/mcp/oauth/callback"
FLOW_TIMEOUT_SECONDS = 300  # 5 minutes to complete the browser consent step


class DBTokenStorage(TokenStorage):
    """Persists one mcp_servers row's OAuth client registration + tokens --
    one instance per server, backing the SDK's TokenStorage protocol
    directly against the DB rather than a file/keyring, consistent with
    every other credential in this app living in SQLite."""

    def __init__(self, server_id: int):
        self.server_id = server_id

    async def get_tokens(self) -> OAuthToken | None:
        row = await db.get_mcp_server(self.server_id)
        if not row or not row.get("oauth_tokens"):
            return None
        return OAuthToken.model_validate_json(row["oauth_tokens"])

    async def set_tokens(self, tokens: OAuthToken) -> None:
        await db.set_mcp_oauth_tokens(self.server_id, tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        row = await db.get_mcp_server(self.server_id)
        if not row or not row.get("oauth_client_info"):
            return None
        return OAuthClientInformationFull.model_validate_json(row["oauth_client_info"])

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        await db.set_mcp_oauth_client_info(self.server_id, client_info.model_dump_json())


@dataclass
class _PendingFlow:
    server_id: int
    auth_url: str | None = None
    result: AuthorizationCodeResult | None = None
    auth_url_ready: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    result_ready: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


_pending_by_server: dict[int, _PendingFlow] = {}
_pending_by_state: dict[str, _PendingFlow] = {}


def make_provider(server_id: int, server_url: str) -> OAuthClientProvider:
    """One OAuthClientProvider per connection attempt. redirect_handler
    doesn't open a browser itself (this is a headless backend process) --
    it just records the authorization URL so /mcp/servers/{id}/connect can
    hand it to the frontend, which is what actually shows the user a
    "Sign in" link. callback_handler blocks (up to FLOW_TIMEOUT_SECONDS)
    until /mcp/oauth/callback resolves this same pending entry.
    """
    flow = _PendingFlow(server_id=server_id)
    _pending_by_server[server_id] = flow

    async def redirect_handler(auth_url: str) -> None:
        state = (parse_qs(urlparse(auth_url).query).get("state") or [None])[0]
        flow.auth_url = auth_url
        if state:
            _pending_by_state[state] = flow
        flow.auth_url_ready.set()

    async def callback_handler() -> AuthorizationCodeResult:
        try:
            await asyncio.wait_for(flow.result_ready.wait(), timeout=FLOW_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"OAuth sign-in for server {server_id} wasn't completed within "
                f"{FLOW_TIMEOUT_SECONDS}s."
            ) from None
        if flow.result is None:
            raise RuntimeError("OAuth callback resolved with no result.")
        return flow.result

    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="N.O.V.A.",
            redirect_uris=[REDIRECT_URI],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=DBTokenStorage(server_id),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


class AuthRequiredError(Exception):
    """Raised by a non-interactive connection attempt (passive status
    checks, /chat's tool-roster fetch) when the server needs a fresh
    interactive OAuth sign-in it can't wait around for -- nobody's watching
    a background poll tick to click through a consent screen. The explicit
    /mcp/servers/{id}/connect flow is the only path that actually waits."""


def make_noninteractive_provider(server_id: int, server_url: str) -> OAuthClientProvider:
    """Same DB-backed token storage as make_provider (so a still-valid or
    refreshable token keeps working silently), but redirect_handler raises
    immediately instead of registering a pending flow and waiting -- this
    is for status checks and the tool-roster fetch, which run unattended on
    a timer and must fail fast and clearly rather than hang."""

    async def redirect_handler(auth_url: str) -> None:
        raise AuthRequiredError(f"Server {server_id} needs interactive OAuth sign-in.")

    async def callback_handler() -> AuthorizationCodeResult:
        raise AuthRequiredError(f"Server {server_id} needs interactive OAuth sign-in.")

    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="N.O.V.A.",
            redirect_uris=[REDIRECT_URI],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=DBTokenStorage(server_id),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


def resolve_callback(state: str, code: str, iss: str | None) -> bool:
    """Called from GET /mcp/oauth/callback once the provider redirects back
    with a real authorization code. Returns False if `state` doesn't match
    any in-flight flow (expired, already resolved, or never started here) --
    the caller shows that as an error page rather than a silent success."""
    flow = _pending_by_state.pop(state, None)
    if flow is None:
        return False
    flow.result = AuthorizationCodeResult(code=code, state=state, iss=iss)
    flow.result_ready.set()
    return True


async def wait_for_auth_url(server_id: int, timeout: float) -> str | None:
    """Races a just-started connection attempt: returns the sign-in URL as
    soon as the SDK asks for one, or None if the attempt didn't need one
    within `timeout` (already has valid tokens, or the server needs no auth
    at all) -- the caller (the /connect endpoint) is expected to pick a
    short timeout and treat None as "check /mcp/servers status instead"."""
    flow = _pending_by_server.get(server_id)
    if flow is None:
        return None
    try:
        await asyncio.wait_for(flow.auth_url_ready.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        return None
    return flow.auth_url


def forget_server(server_id: int) -> None:
    flow = _pending_by_server.pop(server_id, None)
    if flow and flow.auth_url:
        state = (parse_qs(urlparse(flow.auth_url).query).get("state") or [None])[0]
        if state:
            _pending_by_state.pop(state, None)
