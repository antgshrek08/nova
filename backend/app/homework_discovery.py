"""Finding assignments on homework platforms other than Canvas.

Canvas has an API, so its assignments come from canvas_sync. Most other
platforms (WebAssign, MyLab, ALEKS, Lumen OHM, Connect, Gradescope, a
school's Moodle or Brightspace...) have no student API, so Nova does what a
student does: opens the platform's assignment list in its own browser,
signed in as the user, and reads it.

The user adds a platform once (Settings > Homework platforms, or by asking
Nova). If the platform needs a sign-in, Nova opens its sign-in page in a
visible window and the user signs in there; the session stays in Nova's
browser profile, so later reads need nobody. From then on the nightly sync
and "Find assignments" read every added platform the same way Canvas is read.

What is read is honest about what it is: a link on the platform's own list
page that looks like an assignment (per-platform URL patterns first, then
the words around it), with the due date only when the page states one.
Nothing is submitted or clicked here -- this is reading only.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime
from urllib.parse import urlsplit

from . import browser_control, homework_portals, operator_store as store

logger = logging.getLogger(__name__)

SOURCE = "homework_source"
ITEM = "homework_item"

# Where each platform lists a student's work. LMSs are school-specific, so
# the user gives their school's address for those.
START_URLS = {
    "webassign": "https://www.webassign.net/web/Student/Home.html",
    "pearson": "https://mylab.pearson.com/",
    "aleks": "https://www.aleks.com/",
    "lumen": "https://ohm.lumenlearning.com/",
    "myopenmath": "https://www.myopenmath.com/",
    "mheducation": "https://connect.mheducation.com/",
    "cengage": "https://www.cengage.com/dashboard/",
    "macmillan": "https://achieve.macmillanlearning.com/",
    "wiley": "https://education.wiley.com/",
    "knewton": "https://www.knewtonalta.com/",
    "zybooks": "https://learn.zybooks.com/",
    "hawkes": "https://learn.hawkeslearning.com/",
    "tophat": "https://app.tophat.com/",
    "perusall": "https://app.perusall.com/",
    "gradescope": "https://www.gradescope.com/",
    "classroom": "https://classroom.google.com/a/not-turned-in/all",
}
NEEDS_SCHOOL_URL = {"blackboard", "brightspace", "moodle"}

# Links that are assignments on each platform, by URL shape.
ASSIGNMENT_HREF = {
    "webassign": r"/web/Student/Assignment-Responses/|/v4cgi/student\.pl\?.*UserPass|assignment",
    "pearson": r"PlayerHomework|PlayerTest|DoAssignment|/Student/.*(?:Homework|Assignment)|mastering.*assignment",
    "lumen": r"assess2/\?|showtest\.php|/assessment/|aid=\d+",
    "myopenmath": r"assess2/\?|showtest\.php|aid=\d+",
    "mheducation": r"/assignment|/activity|smartbook|/connect/.*(?:assign|launch)",
    "cengage": r"activity|assignment|/nb/ui/.*(?:activity|learningpath)",
    "macmillan": r"/assignments?/|/activities?/",
    "wiley": r"/assignment|/assessment",
    "knewton": r"/assignments?/|/learn/",
    "zybooks": r"/zybook/[^/]+/chapter/|/assignment",
    "hawkes": r"/(?:lesson|assignment|test)",
    "tophat": r"/(?:assignment|homework|question)",
    "perusall": r"/courses/[^/]+/.+",
    "gradescope": r"/courses/\d+/assignments/\d+",
    "classroom": r"/c/[^/]+/a/[^/]+",
    "moodle": r"/mod/(?:assign|quiz|lesson|workshop|h5pactivity|lti)/view\.php\?id=\d+",
    "brightspace": r"/d2l/lms/(?:dropbox|quizzing)/|/d2l/le/content/\d+/viewContent|/d2l/lms/competencies",
    "blackboard": r"/outline/(?:assessment|edit/document)|uploadAssignment|launchAssessment|/ultra/courses/[^/]+/grades/assessment",
    "aleks": r"alekscgi|/assignment",
}
WORDS = re.compile(r"\b(assignment|homework|hw|quiz|test|exam|problem set|pset|lab|activity|chapter \d|section \d|module \d|lesson|practice|reading|discussion|essay|project|worksheet)\b", re.I)
SKIP = re.compile(r"\b(log ?out|sign ?out|help|support|privacy|terms|settings|profile|account|contact|cookie|faq|home|dashboard|grades? ?book|calendar|inbox|notifications?)\b", re.I)
DONE = re.compile(r"\b(submitted|completed|complete|done|turned in|100\s*%|graded|finished)\b", re.I)
LATE = re.compile(r"\b(past due|overdue|late|missing)\b", re.I)
DUE = re.compile(r"(?:due|closes|close date|deadline|until|available until|by)\s*[:\-]?\s*([A-Za-z]{3,9}\.?\s+\d{1,2}(?:,?\s*\d{4})?(?:\s*(?:at\s*)?\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)?|\d{1,2}/\d{1,2}(?:/\d{2,4})?(?:\s*\d{1,2}:\d{2}\s*[ap]\.?m\.?)?|today|tomorrow)", re.I)

LINKS_JS = """() => Array.from(document.querySelectorAll('a[href]')).slice(0, 2000).map(a => {
  const row = a.closest('tr, li, [role=row], [role=listitem], article, .assignment, .card');
  return {href: a.href, text: (a.innerText || a.getAttribute('aria-label') || a.title || '').trim().slice(0, 200),
          ctx: (row ? row.innerText : (a.parentElement ? a.parentElement.innerText : '')).trim().slice(0, 500)};
})"""


class DiscoveryError(RuntimeError):
    """Said to the user as-is."""


def _key(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


SECRET_PARAM = re.compile(r"(token|key|sess|sig|auth|code|ticket|pass|secret|launch|lti|oauth|jwt|nonce|state|saml)", re.I)


def _clean_url(url: str) -> str:
    """Drop query parameters that could carry a credential (SSO and LTI
    links often do); keep the ones that say which assignment it is."""
    p = urlsplit(url)
    q = "&".join(x for x in p.query.split("&") if x and not SECRET_PARAM.search(x.split("=", 1)[0]))
    return f"{p.scheme}://{p.netloc}{p.path}" + (f"?{q}" if q else "")


def _parse_due(text: str) -> tuple[str | None, str | None]:
    m = DUE.search(text or "")
    if not m:
        return None, None
    raw = m.group(1).strip()
    now = datetime.now().astimezone()
    try:
        if raw.lower() in ("today", "tomorrow"):
            from datetime import timedelta
            base = now.replace(hour=23, minute=59, second=0, microsecond=0)
            if raw.lower() == "tomorrow":
                base += timedelta(days=1)
            return base.isoformat(), raw
        from dateutil import parser
        when = parser.parse(raw, fuzzy=True, default=now.replace(hour=23, minute=59, second=0, microsecond=0))
        if when.tzinfo is None:
            when = when.replace(tzinfo=now.tzinfo)
        # "Oct 2" with no year means the next Oct 2, not last year's.
        if not re.search(r"\d{4}", raw) and (now - when).days > 180:
            when = when.replace(year=when.year + 1)
        return when.isoformat(), raw
    except (ValueError, OverflowError):
        return None, raw


def extract(portal_id: str, page_url: str, links: list[dict]) -> list[dict]:
    """Assignment-looking links from a platform page. Pure; tested directly."""
    pattern = re.compile(ASSIGNMENT_HREF.get(portal_id, r"assignment|homework|quiz"), re.I)
    host = urlsplit(page_url).hostname or ""
    seen: set[str] = set()
    items = []
    for link in links:
        href, text, ctx = link.get("href", ""), " ".join((link.get("text") or "").split()), link.get("ctx") or ""
        if not href.startswith("http") or not text or len(text) < 3 or len(text) > 160:
            continue
        link_host = urlsplit(href).hostname or ""
        portal = homework_portals.detect(href)
        same_site = link_host == host or (portal is not None and portal.id == portal_id)
        if not same_site or SKIP.fullmatch(text.strip()) or SKIP.search(text) and not WORDS.search(text):
            continue
        by_url = bool(pattern.search(href))
        by_words = bool(WORDS.search(text)) and bool(DUE.search(ctx) or DONE.search(ctx) or by_url)
        if not (by_url or by_words):
            continue
        url = _clean_url(href)
        if url in seen:
            continue
        seen.add(url)
        due_at, due_text = _parse_due(ctx)
        status = "done" if DONE.search(ctx) and not LATE.search(ctx) else "late" if LATE.search(ctx) else "open"
        items.append({"title": text, "url": url, "due_at": due_at, "due_text": due_text, "status": status})
    return items[:200]


def _signin_wall(url: str, text: str) -> bool:
    low = (url or "").lower()
    return bool(re.search(r"/(login|log-in|signin|sign-in|sso|auth|cas/login|saml|idp)\b", low)) or bool(
        re.search(r"\b(sign in|log in)\b", text[:600], re.I) and re.search(r"\bpassword\b", text[:2000], re.I))


# ---- sources ---------------------------------------------------------------

def sources() -> list[dict]:
    return sorted(store.listing(SOURCE), key=lambda s: s.get("added_at", 0))


def add_source(portal_id: str | None = None, url: str | None = None) -> dict:
    url = (url or "").strip()
    portal = homework_portals.get(portal_id) if portal_id else homework_portals.detect(url)
    if portal is None:
        raise DiscoveryError("Nova doesn't recognize that platform. Check the address, or pick it from the list.")
    if portal.id == "canvas":
        raise DiscoveryError("Canvas is connected under Settings > Canvas; it doesn't need adding here.")
    if portal.status == "unsupported" or portal.kind == "live":
        raise DiscoveryError(f"{portal.name} is live or proctored work, so Nova doesn't collect it.")
    if not url:
        if portal.id in NEEDS_SCHOOL_URL:
            raise DiscoveryError(f"{portal.name} is run by your school. Paste your school's {portal.name} address.")
        url = START_URLS.get(portal.id, "")
    if not re.match(r"^https://", url, re.I):
        raise DiscoveryError("Use the platform's https:// address.")
    for existing in sources():
        if existing["portal"] == portal.id and urlsplit(existing["url"]).hostname == urlsplit(url).hostname:
            return existing
    return store.create(SOURCE, portal=portal.id, name=portal.name, url=url, added_at=time.time(),
                        last_run=None, last_status="new", last_note="", count=0)


def remove_source(source_id: str) -> dict:
    with store.transaction() as conn:
        conn.execute("DELETE FROM records WHERE kind=? AND id=?", (SOURCE, source_id))
        rows = conn.execute("SELECT id, data FROM records WHERE kind=?", (ITEM,)).fetchall()
        for key, data in rows:
            if f'"source_id": "{source_id}"' in data:
                conn.execute("DELETE FROM records WHERE kind=? AND id=?", (ITEM, key))
    return {"removed": source_id}


def items(include_done: bool = False) -> list[dict]:
    rows = [r for r in store.listing(ITEM) if include_done or r.get("status") != "done"]
    return sorted(rows, key=lambda r: (r.get("due_at") is None, r.get("due_at") or "", r.get("title", "")))


async def open_sign_in(source_id: str) -> dict:
    """Show the platform in a visible Nova browser window so the user signs in."""
    src = store.get(SOURCE, source_id)
    if not src:
        raise DiscoveryError("That platform isn't added.")
    tab = await browser_control.page(visible=True)
    await tab.goto(src["url"], wait_until="domcontentloaded", timeout=45000)
    await tab.bring_to_front()
    src.update(last_status="signing_in", last_note="Sign in in Nova's browser window, then press Find assignments.")
    store.put(SOURCE, source_id, src)
    return {"opened": True, "url": src["url"], "note": src["last_note"]}


async def _read(src: dict) -> dict:
    tab = await browser_control.page()
    await tab.goto(src["url"], wait_until="domcontentloaded", timeout=45000)
    try:
        await tab.wait_for_load_state("networkidle", timeout=8000)
    except Exception:  # noqa: BLE001 -- busy pages never go idle; read what is there
        pass
    text = await tab.evaluate("() => document.body ? document.body.innerText.slice(0, 4000) : ''")
    if _signin_wall(tab.url, text):
        return {"status": "needs_sign_in", "items": [], "page": tab.url}
    links = []
    for frame in tab.frames[:12]:  # platforms often list work inside frames
        try:
            links.extend(await frame.evaluate(LINKS_JS))
        except Exception:  # noqa: BLE001 -- a cross-origin or detached frame
            continue
    return {"status": "ok", "items": extract(src["portal"], tab.url, links), "page": tab.url}


async def discover(source_id: str | None = None) -> dict:
    """Read every added platform (or one) and store what's there."""
    from . import operator_workflows
    operator_workflows.require_running()
    targets = [s for s in sources() if source_id in (None, s["id"])]
    if source_id and not targets:
        raise DiscoveryError("That platform isn't added.")
    report = []
    new_titles = []
    for src in targets:
        try:
            result = await _read(src)
        except Exception as exc:  # noqa: BLE001 -- one platform failing must not stop the rest
            logger.info("Homework discovery failed for %s: %s", src["name"], exc)
            result = {"status": "error", "items": [], "note": str(exc)[:300]}
        now = time.time()
        if result["status"] == "ok":
            fresh = set()
            for item in result["items"]:
                key = _key(item["url"])
                fresh.add(key)
                old = store.get(ITEM, key) or {}
                if not old and item.get("status") != "done":
                    new_titles.append(f"{item['title']} ({src['name']})")
                store.put(ITEM, key, {**old, **item, "id": key, "source_id": src["id"], "portal": src["portal"],
                                      "platform": src["name"], "first_seen": old.get("first_seen", now), "seen_at": now})
            note = f"Found {len(result['items'])} assignment{'s' if len(result['items']) != 1 else ''}." if result["items"] else \
                "Signed in, but no assignments were listed on that page. If your work is on another page, add that address instead."
            src.update(last_status="ok", last_note=note, count=len(result["items"]))
        elif result["status"] == "needs_sign_in":
            src.update(last_status="needs_sign_in", last_note="Needs you to sign in once in Nova's browser.")
        else:
            src.update(last_status="error", last_note=f"Couldn't read it: {result.get('note', '')}")
        src["last_run"] = now
        store.put(SOURCE, src["id"], src)
        report.append({"source": src["name"], "status": src["last_status"], "note": src["last_note"], "found": len(result["items"])})
    try:
        from . import notify
        if new_titles:
            await notify.notify("homework", f"{len(new_titles)} new assignment{'s' if len(new_titles) != 1 else ''} found",
                                "; ".join(new_titles[:4]), tag="nova-homework", view="academics")
        signin = [r["source"] for r in report if r["status"] == "needs_sign_in"]
        if signin:
            await notify.notify("needs_you", "Sign in needed", f"{', '.join(signin)} needs you to sign in once in Nova's browser.",
                                tag="nova-homework-signin", view="settings:Homework platforms")
    except Exception:  # noqa: BLE001
        pass
    return {"platforms": report, "assignments": len(items()), "new": len(new_titles)}
