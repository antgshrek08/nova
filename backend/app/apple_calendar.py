"""Read/write access to the user's Apple (iCloud) Calendar over CalDAV.

Why CalDAV and not an API: Apple publishes no REST calendar API. iCloud speaks
CalDAV (RFC 4791) at caldav.icloud.com, which is how Apple's own clients sync,
so it is a first-class path rather than a workaround -- and unlike the .ics
subscription this is two-way: Nova can read the real calendar and write to it.

Auth is the Apple ID plus an **app-specific password**, which requires 2FA on
the account. The real Apple password will not work here, and that is the single
most common cause of a 401. App-specific passwords are revoked wholesale when
the primary password changes, which is the usual cause of a sync that worked
yesterday and doesn't today -- both are called out in the error text rather than
left as a bare 401.

The password lives in the secrets vault (Windows Credential Manager via
keyring), not in .env and never in a prompt: see secrets_store. Only the Apple
ID -- an identifier, not a credential -- is kept in settings so the UI can show
which account is connected.

Discovery is two hops, per the spec: ask the server who you are
(current-user-principal), then ask that principal where its calendars live
(calendar-home-set). iCloud answers the second with a numbered partition host
(p61-caldav.icloud.com and so on) that is per-account, so it is discovered every
time rather than guessed or hardcoded.
"""
from __future__ import annotations

import asyncio
import os
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import set_key

from . import config, secrets_store

ROOT_URL = "https://caldav.icloud.com"
SECRET_NAME = "apple-calendar"      # key in the secrets vault
TIMEOUT = 30
MAX_EVENTS = 500

DAV = "DAV:"
CALDAV = "urn:ietf:params:xml:ns:caldav"
APPLE = "http://apple.com/ns/ical/"
ET.register_namespace("d", DAV)
ET.register_namespace("c", CALDAV)

_discovery_cache: dict[str, str] = {}


class AppleCalendarError(RuntimeError):
    """Configuration or CalDAV failure, phrased for display. Never contains the
    password."""


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
def apple_id() -> str | None:
    return os.getenv("APPLE_ID", "").strip() or None


def _password() -> str | None:
    """Read inside this process only. Never returned to a model or an endpoint."""
    try:
        return secrets_store.get(SECRET_NAME)
    except secrets_store.SecretError:
        return None


def configured() -> bool:
    return bool(apple_id() and _password())


def status() -> dict:
    return {
        "configured": configured(),
        "apple_id": apple_id(),          # an identifier, not a secret
        "password_set": bool(_password()),
        "stored_in": secrets_store.backend_name(),
        "calendar_home": _discovery_cache.get("home"),
    }


async def update_credentials(account: str | None, app_password: str | None) -> dict:
    """Save, then prove it works by actually discovering the calendar home.

    Verifying on save matters more here than usual: a wrong app-specific
    password is indistinguishable from a right one until something tries to use
    it, and the next thing to use it would be a background job at midnight.
    """
    if account and account.strip():
        cleaned = account.strip()
        set_key(str(config.ENV_PATH), "APPLE_ID", cleaned)
        os.environ["APPLE_ID"] = cleaned
    if app_password and app_password.strip():
        secrets_store.put(SECRET_NAME, app_password.strip())
    _discovery_cache.clear()

    if not configured():
        raise AppleCalendarError("Both an Apple ID and an app-specific password are needed.")
    calendars = await list_calendars()
    return {**status(), "calendars": calendars}


def disconnect() -> dict:
    secrets_store.delete(SECRET_NAME)
    _discovery_cache.clear()
    return status()


# ---------------------------------------------------------------------------
# CalDAV plumbing
# ---------------------------------------------------------------------------
def _client() -> httpx.AsyncClient:
    password = _password()
    if not apple_id() or not password:
        raise AppleCalendarError(
            "Apple Calendar isn't connected. Add your Apple ID and an app-specific "
            "password in Settings > Calendar."
        )
    return httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
        auth=(apple_id(), password),
        headers={"User-Agent": "Nova/1.0", "Content-Type": "application/xml; charset=utf-8"},
    )


def _raise_for_auth(response: httpx.Response) -> None:
    if response.status_code == 401:
        raise AppleCalendarError(
            "iCloud rejected those credentials (401). Two things cause this almost every "
            "time: using your real Apple password instead of an app-specific one, or an "
            "app-specific password that was revoked when you last changed your Apple ID "
            "password. Generate a fresh one at appleid.apple.com > Sign-In and Security > "
            "App-Specific Passwords."
        )
    if response.status_code == 403:
        raise AppleCalendarError("iCloud refused that request (403) — the account may not have iCloud Calendar enabled.")


async def _request(client: httpx.AsyncClient, method: str, url: str, body: str | None = None,
                   depth: str = "0", extra_headers: dict | None = None) -> httpx.Response:
    headers = {"Depth": depth}
    if extra_headers:
        headers.update(extra_headers)
    try:
        response = await client.request(method, url, content=body.encode("utf-8") if body else None,
                                        headers=headers)
    except httpx.HTTPError as exc:
        raise AppleCalendarError(f"Couldn't reach iCloud: {exc}") from exc
    _raise_for_auth(response)
    return response


def _multistatus(response: httpx.Response) -> ET.Element:
    if response.status_code not in (200, 207):
        raise AppleCalendarError(f"iCloud returned HTTP {response.status_code} for {response.request.url}.")
    try:
        return ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise AppleCalendarError(f"iCloud returned a response that didn't parse as XML: {exc}") from exc


def _first_href(element: ET.Element, path: str) -> str | None:
    found = element.find(path)
    if found is None:
        return None
    href = found.find(f"{{{DAV}}}href")
    return href.text.strip() if href is not None and href.text else None


def _absolute(base: str, href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    root = "/".join(base.split("/")[:3])   # scheme://host
    return root + href


PROPFIND_PRINCIPAL = f"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="{DAV}"><d:prop><d:current-user-principal/></d:prop></d:propfind>"""

PROPFIND_HOME = f"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="{DAV}" xmlns:c="{CALDAV}">
  <d:prop><c:calendar-home-set/></d:prop>
</d:propfind>"""

PROPFIND_CALENDARS = f"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="{DAV}" xmlns:c="{CALDAV}" xmlns:a="{APPLE}">
  <d:prop>
    <d:displayname/>
    <d:resourcetype/>
    <c:supported-calendar-component-set/>
    <a:calendar-color/>
    <d:current-user-privilege-set/>
  </d:prop>
</d:propfind>"""


async def _calendar_home(client: httpx.AsyncClient) -> str:
    """The two-hop discovery. Cached per process: it costs two round trips and
    the answer only changes if the account does."""
    if "home" in _discovery_cache:
        return _discovery_cache["home"]

    response = await _request(client, "PROPFIND", ROOT_URL + "/", PROPFIND_PRINCIPAL, depth="0")
    tree = _multistatus(response)
    principal = _first_href(tree, f".//{{{DAV}}}current-user-principal")
    if not principal:
        raise AppleCalendarError("iCloud didn't return a user principal — the account may not have Calendar enabled.")
    principal_url = _absolute(str(response.url), principal)

    response = await _request(client, "PROPFIND", principal_url, PROPFIND_HOME, depth="0")
    tree = _multistatus(response)
    home = _first_href(tree, f".//{{{CALDAV}}}calendar-home-set")
    if not home:
        raise AppleCalendarError("iCloud didn't return a calendar home for that account.")
    home_url = _absolute(str(response.url), home)
    if not home_url.endswith("/"):
        home_url += "/"
    _discovery_cache["home"] = home_url
    return home_url


async def list_calendars() -> list[dict]:
    """Every calendar collection that can hold events.

    Filtered on supported-calendar-component-set containing VEVENT: an iCloud
    home also contains task lists and other collections, and writing an event
    into one of those fails in a way that is hard to read.
    """
    async with _client() as client:
        home = await _calendar_home(client)
        response = await _request(client, "PROPFIND", home, PROPFIND_CALENDARS, depth="1")
        tree = _multistatus(response)

    calendars = []
    for resp in tree.findall(f"{{{DAV}}}response"):
        href_el = resp.find(f"{{{DAV}}}href")
        if href_el is None or not href_el.text:
            continue
        url = _absolute(home, href_el.text.strip())
        if url.rstrip("/") == home.rstrip("/"):
            continue                                   # the home collection itself
        if resp.find(f".//{{{DAV}}}resourcetype/{{{CALDAV}}}calendar") is None:
            continue
        comps = [c.get("name") for c in resp.findall(f".//{{{CALDAV}}}comp")]
        if comps and "VEVENT" not in comps:
            continue                                   # reminders / task list
        name_el = resp.find(f".//{{{DAV}}}displayname")
        color_el = resp.find(f".//{{{APPLE}}}calendar-color")
        privileges = {p.tag for p in resp.findall(f".//{{{DAV}}}current-user-privilege-set/*/*")}
        calendars.append({
            "url": url,
            "name": (name_el.text or "").strip() if name_el is not None else "Calendar",
            "color": (color_el.text or "").strip() if color_el is not None else "",
            "read_only": bool(privileges) and f"{{{DAV}}}write-content" not in privileges,
        })
    calendars.sort(key=lambda c: c["name"].lower())
    return calendars


# ---------------------------------------------------------------------------
# Reading events
# ---------------------------------------------------------------------------
def _utc_stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _query_body(start: datetime, end: datetime) -> str:
    # <c:expand> is not optional for correctness. A time-range filter *matches*
    # a recurring event whose occurrences fall in the window, but without expand
    # the server returns the master VEVENT -- so a birthday that recurs every
    # year comes back with its original DTSTART (2025-09-18 for an event asked
    # about in 2026). Found live against real iCloud data. With expand the
    # server returns one component per occurrence, already dated correctly.
    return f"""<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="{DAV}" xmlns:c="{CALDAV}">
  <d:prop>
    <d:getetag/>
    <c:calendar-data>
      <c:expand start="{_utc_stamp(start)}" end="{_utc_stamp(end)}"/>
    </c:calendar-data>
  </d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT">
        <c:time-range start="{_utc_stamp(start)}" end="{_utc_stamp(end)}"/>
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>"""


def _event_rows(tree: ET.Element, calendar_url: str, calendar_name: str) -> list[dict]:
    from icalendar import Calendar

    rows = []
    for resp in tree.findall(f"{{{DAV}}}response"):
        href_el = resp.find(f"{{{DAV}}}href")
        data_el = resp.find(f".//{{{CALDAV}}}calendar-data")
        if data_el is None or not data_el.text:
            continue
        try:
            parsed = Calendar.from_ical(data_el.text)
        except Exception:  # noqa: BLE001 - one unreadable event must not sink the list
            continue
        for component in parsed.walk("VEVENT"):
            start = getattr(component.get("DTSTART"), "dt", None)
            end = getattr(component.get("DTEND"), "dt", None)
            all_day = start is not None and not isinstance(start, datetime)
            rows.append({
                "uid": str(component.get("UID") or ""),
                "title": str(component.get("SUMMARY") or "(no title)"),
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
                "all_day": all_day,
                "location": str(component.get("LOCATION") or ""),
                "notes": str(component.get("DESCRIPTION") or "")[:2000],
                "calendar": calendar_name,
                "calendar_url": calendar_url,
                "href": _absolute(calendar_url, href_el.text.strip()) if href_el is not None and href_el.text else "",
            })
    return rows


async def list_events(days: int = 14, calendar_url: str | None = None,
                      start: datetime | None = None) -> list[dict]:
    """Events in a window, across every writable calendar unless one is named."""
    begin = start or datetime.now(timezone.utc)
    finish = begin + timedelta(days=max(1, min(days, 365)))

    calendars = await list_calendars()
    if calendar_url:
        calendars = [c for c in calendars if c["url"].rstrip("/") == calendar_url.rstrip("/")]
        if not calendars:
            raise AppleCalendarError("No calendar with that URL — call list_calendars first.")

    rows: list[dict] = []
    async with _client() as client:
        body = _query_body(begin, finish)
        for calendar in calendars:
            try:
                response = await _request(
                    client, "REPORT", calendar["url"], body, depth="1",
                    extra_headers={"Content-Type": "application/xml; charset=utf-8"},
                )
                rows.extend(_event_rows(_multistatus(response), calendar["url"], calendar["name"]))
            except AppleCalendarError:
                continue            # a single unreadable calendar shouldn't fail the lot
    rows.sort(key=lambda r: r["start"] or "9999")
    return rows[:MAX_EVENTS]


# ---------------------------------------------------------------------------
# Writing events
# ---------------------------------------------------------------------------
def build_event(title: str, start: datetime, end: datetime | None, *, uid: str | None = None,
                location: str = "", notes: str = "", all_day: bool = False,
                reminder_minutes: list[int] | None = None) -> tuple[str, str]:
    """One VEVENT as a complete VCALENDAR. Returns (uid, ics_text)."""
    from icalendar import Alarm, Calendar, Event

    uid = uid or f"nova-{uuid.uuid4()}"
    calendar = Calendar()
    calendar.add("prodid", "-//N.O.V.A.//Apple Calendar//EN")
    calendar.add("version", "2.0")

    event = Event()
    event.add("uid", uid)
    event.add("dtstamp", datetime.now(timezone.utc))
    event.add("summary", title)
    if all_day:
        # An all-day VEVENT uses DATE values and a DTEND of the *next* day --
        # DTEND is exclusive, so same-day start/end renders as a zero-length
        # event that some clients hide entirely.
        event.add("dtstart", start.date())
        event.add("dtend", (end or start).date() + timedelta(days=1))
    else:
        event.add("dtstart", start)
        event.add("dtend", end or start + timedelta(hours=1))
    if location:
        event.add("location", location)
    if notes:
        event.add("description", notes)
    for minutes in reminder_minutes or []:
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", title)
        alarm.add("trigger", timedelta(minutes=-abs(int(minutes))))
        event.add_component(alarm)

    calendar.add_component(event)
    return uid, calendar.to_ical().decode("utf-8")


async def create_event(calendar_url: str, title: str, start: datetime, end: datetime | None = None,
                       *, location: str = "", notes: str = "", all_day: bool = False,
                       reminder_minutes: list[int] | None = None, uid: str | None = None) -> dict:
    """PUT a new event. Idempotent on `uid`: passing the same uid twice updates
    rather than duplicating, which is what makes a repeating sync safe."""
    uid, ics = build_event(title, start, end, uid=uid, location=location, notes=notes,
                           all_day=all_day, reminder_minutes=reminder_minutes)
    target = calendar_url.rstrip("/") + f"/{uid}.ics"
    async with _client() as client:
        response = await client.put(
            target, content=ics.encode("utf-8"),
            headers={"Content-Type": "text/calendar; charset=utf-8"},
        )
        _raise_for_auth(response)
    if response.status_code not in (200, 201, 204):
        raise AppleCalendarError(
            f"iCloud refused the event (HTTP {response.status_code}). "
            "If this calendar is a subscription or shared read-only, it can't be written to."
        )
    return {"uid": uid, "url": target, "title": title,
            "start": start.isoformat(), "created": response.status_code == 201}


async def delete_event(event_url: str) -> dict:
    async with _client() as client:
        response = await client.delete(event_url)
        _raise_for_auth(response)
    if response.status_code not in (200, 204, 404):
        raise AppleCalendarError(f"iCloud refused the delete (HTTP {response.status_code}).")
    return {"deleted": True, "url": event_url, "was_missing": response.status_code == 404}
