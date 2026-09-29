"""Downloads with receipts and account setup without exposing passwords."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import mimetypes
import os
import secrets
import socket
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urljoin

import httpx

from . import browser_control, identity, mail, operator_store as store, operator_workflows as workflows, secrets_store

MAX_DOWNLOAD = 50_000_000


async def public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use an HTTP(S) download URL without embedded credentials.')
    addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('This download URL resolves to a private or local address.')
    return url


async def download(url, filename=''):
    workflows.require_running()
    destination = store.directory() / 'downloads'
    destination.mkdir(exist_ok=True)
    name = filename or Path(urlsplit(url).path).name or 'download'
    if Path(name).name != name or any(c in name for c in '\\/:*?"<>|') or name in ('.', '..'):
        raise ValueError('Use a filename, not a path.')
    target = destination / f'{uuid.uuid4().hex[:10]}-{name}'
    current, total = url, 0
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False, trust_env=False) as client:
            for _ in range(6):
                await public_url(current)
                async with client.stream('GET', current) as response:
                    if response.is_redirect:
                        current = urljoin(current, response.headers['location'])
                        continue
                    response.raise_for_status()
                    if int(response.headers.get('content-length', 0)) > MAX_DOWNLOAD:
                        raise ValueError('Download exceeds 50 MB.')
                    digest = hashlib.sha256()
                    with target.open('xb') as output:
                        async for chunk in response.aiter_bytes():
                            workflows.require_running()
                            total += len(chunk)
                            if total > MAX_DOWNLOAD:
                                raise ValueError('Download exceeds 50 MB.')
                            output.write(chunk)
                            digest.update(chunk)
                    return store.create('download', source=url, final_url=current, path=str(target),
                                        size=total, sha256=digest.hexdigest(), content_type=response.headers.get('content-type', ''),
                                        executed=False)
            raise ValueError('Too many redirects.')
    except BaseException:
        target.unlink(missing_ok=True)
        raise


async def account(action, service, url='', username='', email='', selector='input[type=password]'):
    workflows.require_running()
    if action == 'prepare':
        if any(row['service'].lower() == service.lower() for row in await identity.listing()):
            raise ValueError('This account is already recorded. Use sign_in instead of replacing its password.')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('An account requires its HTTPS website URL.')
        own_mail = await mail.account()
        address = email or own_mail.address
        if not address:
            raise ValueError('Configure Nova’s email in Settings before creating an account.')
        password = secrets.token_urlsafe(24) + '!Aa9'
        result = await identity.add(service, username or address, url=url, email=address, password=password,
                                    notes='Signup prepared; registration is not yet verified.')
        return {'service': result.get('service', service), 'email': address, 'username': username or address,
                'status': 'prepared', 'next': 'Fill the website signup form, fill the password using operator_account, confirm registration, then verify the inbox.'}
    if action == 'fill_password':
        rows = [row for row in await identity.listing() if row['service'].lower() == service.lower()]
        if len(rows) != 1:
            raise ValueError('Prepare or record this account first.')
        async with browser_control._lock:
            tab = await browser_control.page()
            current, expected = urlsplit(tab.url), urlsplit(rows[0].get('url') or '')
            if current.scheme != 'https' or (current.scheme, current.hostname, current.port or 443) != (expected.scheme, expected.hostname, expected.port or 443):
                raise ValueError('The active browser site does not match the stored account.')
            field = tab.locator(selector)
            if await field.count() != 1 or await field.get_attribute('type') != 'password':
                raise ValueError('Select exactly one password field.')
            secret = secrets_store.get(identity.secret_name(rows[0]['service']))
            if not secret:
                raise ValueError('The password is missing from the vault.')
            await field.fill(secret)
        return {'service': service, 'filled': True, 'submitted': False}
    raise ValueError('Use prepare or fill_password.')
