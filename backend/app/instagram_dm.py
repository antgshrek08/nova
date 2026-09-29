"""Reading the reels sent to Nova's own Instagram inbox.

The user wants to send Nova a reel the way they'd send it to a friend -- pick
Nova in the DM list, tap send -- rather than going through iOS's share sheet.
That means Nova has to read its own inbox, which means driving a browser
against Instagram, which Instagram's terms prohibit and their detection is
built to catch. The user was told that plainly, twice, and chose this anyway. It is
their account.

What that decision buys, and what it costs, both live in this file, so the
design is shaped around keeping the cost as small as the feature allows:

**Read-only, absolutely.** Nothing here likes, follows, replies, posts or
opens a profile. It loads the inbox, collects reel links, and leaves. The
riskiest thing it does is exist.

**Slow on purpose.** The default poll is fifteen minutes with jitter, not
thirty seconds. A fixed fast interval is the single most machine-looking
signal available, and there is no version of this feature where checking
four times a minute is worth what it costs.

**Links, not the DOM.** Instagram's class names are generated and change
weekly; anything built on them breaks silently and looks like "no new
messages". Collecting anchors whose href matches a reel or post URL survives
a redesign, because the links are the part that cannot change without
breaking Instagram itself.

**A challenge stops everything.** Same rule as signin.py: if Instagram asks
for a human, this backs off and says so rather than trying to look like one.
That is also the early warning that the account is under scrutiny, so it
disables the poll rather than hammering on.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from urllib.parse import urlparse

from . import browser_control, config, db, site_session

logger = logging.getLogger(__name__)

INBOX_URL = "https://www.instagram.com/direct/inbox/"

# Instagram quarantines messages from anyone the account does not follow into
# a separate Requests folder, and never shows them in the inbox. A brand-new
# account follows nobody, so *every* message it receives starts here -- which
# is why the first real check found a logged-in, entirely empty inbox while
# two reels sat one tab away.
REQUESTS_URL = "https://www.instagram.com/direct/requests/"

# The inbox says this when it has no accepted conversations. Distinguishing
# "empty" from "broken" is the difference between telling the user to accept
# a request and sending them to debug a session that is fine.
EMPTY_INBOX_MARKERS = (
    "chats will appear here", "send a message to start a chat", "your messages",
)

ENABLED_KEY = "instagram_dm_enabled"
SEEN_KEY = "instagram_dm_seen"
INTERVAL_KEY = "instagram_dm_interval_minutes"

DEFAULT_INTERVAL_MINUTES = 15

# How many links to remember as already handled. Comfortably more than a
# person sends in a week, and small enough that the settings row stays a row
# rather than a log.
SEEN_LIMIT = 300

# Reel, post and TV permalinks. Deliberately not profile or story URLs:
# a story expires before a poll cycle and a profile is not a thing to watch.
_SHARE_RE = re.compile(r"/(reel|reels|p|tv)/([A-Za-z0-9_-]{5,})")

CHALLENGE_MARKERS = (
    "suspicious login", "we detected", "confirm it's you", "confirm its you",
    "challenge_required", "help us confirm", "unusual activity", "captcha",
)


class DMError(Exception):
    """Something the user can act on."""


async def _seen_list() -> list[str]:
    """Everything already handled, oldest first.

    Order is not decoration here -- it is what makes the cap safe. See
    _remember.
    """
    raw = (await db.get_app_settings()).get(SEEN_KEY) or "[]"
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return list(dict.fromkeys(str(url) for url in loaded if isinstance(url, str)))


async def _seen() -> set[str]:
    return set(await _seen_list())


async def _remember(urls: list[str]) -> None:
    """Add these to the handled list, dropping the oldest past the cap.

    This used to be `list(seen | set(urls))[-SEEN_LIMIT:]`, which reads as
    "keep the most recent 300" and is not: a set has no order, so the slice
    kept an arbitrary 300 and could drop the URLs being added in the same
    call. Past the cap that turns into a loop -- the reel is watched,
    forgotten, and watched again on the next poll, with a notification each
    time. Keeping an ordered list and trimming the front is the only version
    of this where the cap means what the name says.
    """
    urls = list(dict.fromkeys(urls))
    added = set(urls)
    keep = [url for url in await _seen_list() if url not in added]
    keep.extend(urls)
    await db.set_app_settings({SEEN_KEY: json.dumps(keep[-SEEN_LIMIT:])})


def canonical(url: str) -> str:
    """One shortcode, one identity.

    The same reel arrives as /reel/, /reels/ and /p/ depending on where it
    was shared from, and with a tail of tracking parameters. Without this,
    the same clip is watched three times and notified three times.
    """
    match = _SHARE_RE.search(url or "")
    if not match:
        return (url or "").split("?")[0].rstrip("/")
    kind = "reel" if match.group(1) in ("reel", "reels") else match.group(1)
    return f"https://www.instagram.com/{kind}/{match.group(2)}/"


async def _links_on_page(tab, selector: str = "a[href]") -> list[str]:
    """Every reel/post permalink currently rendered."""
    try:
        hrefs = await tab.eval_on_selector_all(
            selector, "els => els.map(e => e.getAttribute('href'))"
        )
    except Exception as exc:  # noqa: BLE001
        raise DMError("I couldn't read the links on Instagram's page; the DM check is incomplete.") from exc
    out = []
    for href in hrefs or []:
        if not href or not _SHARE_RE.search(href):
            continue
        full = href if href.startswith("http") else f"https://www.instagram.com{href}"
        out.append(canonical(full))
    # Order-preserving dedupe: the newest thread is rendered last, and
    # keeping order means the oldest unseen reel is handled first.
    return list(dict.fromkeys(out))


async def _page_text(tab) -> str:
    try:
        return (await tab.locator("body").inner_text())[:6000].lower()
    except Exception as exc:  # noqa: BLE001
        raise DMError("I couldn't read Instagram's page; the DM check is incomplete.") from exc


async def _guard(tab) -> None:
    """Stop on a challenge at any navigation step, including iframe shells."""
    path = urlparse(tab.url).path.lower()
    challenge_paths = ("/challenge", "/checkpoint", "/two_factor", "/2fa", "/verify")
    challenge = any(path == prefix or path.startswith(prefix + "/")
                    for prefix in challenge_paths)
    if not challenge:
        text = await _page_text(tab)
        challenge = any(marker in text for marker in CHALLENGE_MARKERS)
    if challenge:
        await db.set_app_settings({ENABLED_KEY: "0"})
        raise DMError(
            "Instagram is asking to confirm it's you, so I've stopped checking DMs. "
            "Clear it in Nova's browser, then turn DM checking back on."
        )
    if path == "/accounts/login" or path.startswith("/accounts/login/"):
        raise DMError("Instagram bounced Nova back to the login page; the session didn't hold.")


async def _fresh_tab(url: str):
    """A new tab at `url`, with none of the app's previous state.

    Instagram is a single-page app that restores its last route. After a
    check ended on Hidden Requests, goto(/direct/inbox/) came back with
    location.href still reading /direct/requests/ -- and a reload afterwards
    did not help, because the reload reloads wherever the redirect landed.
    Every read after that was of the wrong folder, reported as an empty
    inbox, with total confidence.

    A page that has never been anywhere cannot be restored to anywhere. The
    caller closes it, so the session's cookies persist in the profile while
    the routing state does not.
    """
    context = browser_control._browser
    if not browser_control._alive(context):
        await browser_control.page()  # launches it
        context = browser_control._browser
    tab = await context.new_page()
    try:
        tab.set_default_timeout(15000)
        await tab.goto(url, wait_until="domcontentloaded", timeout=45000)
    except (Exception, asyncio.CancelledError):
        # The caller never receives the tab when navigation fails, so its
        # finally block cannot close it. Preserve the original failure.
        try:
            await tab.close()
        except Exception:  # noqa: BLE001
            logger.debug("Couldn't close failed Instagram navigation", exc_info=True)
        raise
    return tab


async def inspect_inbox() -> dict:
    """What the inbox list is actually made of.

    Written after three rounds of confidently reporting an empty inbox that
    had a conversation in it. The thread rows are not anchors, so every
    selector built on `a[href*='/direct/t/']` matched nothing and the code
    read that as "no messages" rather than "I don't know how to see them".
    This dumps the structure so the selector can be chosen from what is
    there instead of from what seemed likely.
    """
    tab = await _fresh_tab(INBOX_URL)
    await tab.wait_for_timeout(9000)
    structure = await tab.evaluate(
        """() => {
            const rows = [];
            // Anything that looks like a row with a name and a preview.
            for (const el of document.querySelectorAll('div,li,a')) {
                const t = (el.innerText || '').trim();
                if (!t || t.length > 120) continue;
                const kids = el.querySelectorAll('img').length;
                const clickable = el.getAttribute('role') === 'button'
                    || el.tagName === 'A'
                    || el.getAttribute('tabindex') !== null;
                if (kids >= 1 && clickable) {
                    rows.push({
                        tag: el.tagName,
                        role: el.getAttribute('role'),
                        tabindex: el.getAttribute('tabindex'),
                        href: el.getAttribute('href'),
                        aria: el.getAttribute('aria-label'),
                        text: t.slice(0, 60).replace(/\\n/g, ' | '),
                    });
                }
            }
            return {
                url: location.href,
                rowCount: rows.length,
                rows: rows.slice(0, 12),
                listRoles: [...document.querySelectorAll('[role="list"],[role="listbox"],[role="grid"]')]
                    .map(e => e.getAttribute('aria-label') || e.getAttribute('role')).slice(0, 6),
            };
        }"""
    )
    # Open the first conversation and dump what a shared reel looks like
    # inside it -- the row click works now, but the reels in the thread are
    # not anchors either, so the shape has to be read rather than assumed.
    inside = {}
    try:
        row = _conversation_rows(tab).first
        if await row.count():
            await row.click(timeout=6000)
            await tab.wait_for_timeout(5000)
            hrefs = await tab.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.getAttribute('href'))")
            srcs = await tab.eval_on_selector_all(
                "img[src], video[src], video[poster]",
                "els => els.map(e => e.getAttribute('src') || e.getAttribute('poster'))")
            body = await tab.locator("body").inner_text()
            inside = {
                "url": tab.url,
                "anchors": list(dict.fromkeys(h for h in (hrefs or []) if h))[:30],
                "media": list(dict.fromkeys(x for x in (srcs or []) if x))[:10],
                "buttons": await tab.locator("div[role='button']").count(),
                "bodyText": body.replace(chr(10), " | ")[:600],
            }
    except Exception as exc:  # noqa: BLE001
        inside = {"error": f"{type(exc).__name__}: {exc}"}

    shot = str(config.DB_PATH).replace("ai_council.db", "instagram-inbox-debug.png")
    try:
        await tab.screenshot(path=shot, full_page=False)
    except Exception:  # noqa: BLE001
        shot = None
    await tab.close()
    return {**structure, "screenshot": shot, "inside_thread": inside}


async def _open_hidden_requests(tab) -> dict:
    """Click into Hidden Requests, and say which attempt worked.

    Several selectors rather than one, because the row is a styled div with
    generated class names and no stable role -- get_by_text alone matched the
    label but clicking the text node did nothing, and the failure was
    invisible because it was wrapped in a bare except. Reporting which
    strategy landed is what turns the next silent failure into a fixable one.
    """
    label = re.compile(r"hidden requests", re.I)
    strategies = [
        ("role=button", lambda: tab.get_by_role("button", name=label).first),
        ("role=link", lambda: tab.get_by_role("link", name=label).first),
        # The clickable row is an ancestor of the text, not the text itself.
        ("row containing text", lambda: tab.locator(
            "div[role='button']:has-text('Hidden Requests'), "
            "a:has-text('Hidden Requests'), "
            "div:has(> div > span:text-is('Hidden Requests'))").first),
        ("text node", lambda: tab.get_by_text(label).first),
    ]
    before = urlparse(tab.url).path
    heading = tab.get_by_role("heading", name=label).first
    had_heading = bool(await heading.count() and await heading.is_visible())
    attempted = False
    for name, build in strategies:
        try:
            target = build()
            if not await target.count():
                continue
            attempted = True
            await target.click(timeout=4000)
            await tab.wait_for_timeout(2000)
            await _guard(tab)
            path = urlparse(tab.url).path
            has_heading = bool(await heading.count() and await heading.is_visible())
            # The entry's own text is already visible before clicking. Require
            # a new heading or an actual move to a hidden-folder route.
            if (has_heading and not had_heading) or (
                    path != before and path.startswith("/direct/")
                    and "hidden" in path.split("/")):
                return {"opened": True, "via": name}
            if path != before:
                raise DMError("Instagram opened an unexpected page instead of Hidden Requests.")
        except DMError:
            raise
        except Exception as exc:  # noqa: BLE001
            attempted = True
            logger.debug("Hidden Requests via %s failed: %s", name, exc)
            continue
    if attempted:
        raise DMError("I couldn't confirm that Hidden Requests opened; the DM check is incomplete.")
    return {"opened": False, "via": None}


def _conversation_rows(tab):
    """The clickable conversation rows in whichever list is showing.

    `div[role="button"]` carrying an avatar. Not anchors -- Instagram renders
    threads as styled divs with click handlers and generated class names, so
    every selector built on `a[href*='/direct/t/']` matched nothing and read
    as an empty inbox. The note composer at the top of the list matches the
    same shape and is excluded by its label.
    """
    return (tab.locator("div[role='button']")
            .filter(has=tab.locator("img"))
            .filter(has_not_text="Your note"))


async def _reels_in_thread(tab, max_cards: int = 8) -> list[str]:
    """Open each shared-post card and take the URL it lands on.

    A reel shared into a DM has no permalink in the page. The card renders a
    CDN thumbnail and a link to the *creator's profile* -- so scraping
    anchors yields /chris.raroque/, which is the author, not the reel. The
    only place the shortcode exists is the address bar after the card is
    opened.

    Clicking here is navigation inside Nova's own inbox to read a message it
    was sent. Nothing is liked, followed or replied to, and the card is
    closed again straight afterwards.
    """
    found: list[str] = []
    # Thumbnails served from Instagram's media CDN, sized like a post rather
    # than an avatar. Avatars are the other cdninstagram images in a thread
    # and are small, so the size filter is what separates them.
    cards = tab.locator("img[src*='cdninstagram']")
    try:
        total = await cards.count()
    except Exception as exc:  # noqa: BLE001
        raise DMError("I couldn't read the shared cards; the DM check is incomplete.") from exc

    for index in range(min(total, max_cards)):
        try:
            card = tab.locator("img[src*='cdninstagram']").nth(index)
            if not await card.count():
                continue
            box = await card.bounding_box()
            if not box or box["width"] < 90 or box["height"] < 90:
                continue  # avatar, not a shared post
            before = tab.url
            await card.click(timeout=5000)
            await tab.wait_for_timeout(2600)
            await _guard(tab)
            if _SHARE_RE.search(tab.url):
                found.append(canonical(tab.url))
            # Back to the thread whether or not that was a reel.
            if tab.url != before:
                await tab.go_back(wait_until="domcontentloaded", timeout=20000)
                await tab.wait_for_timeout(1400)
            else:
                # Read the overlay while it is present. Links from the page
                # underneath may be unrelated to the card the user shared.
                try:
                    links = await _links_on_page(tab, "[role='dialog'] a[href]")
                    if not links:
                        raise DMError("I couldn't identify the shared reel in the overlay.")
                    found.extend(links)
                finally:
                    await tab.keyboard.press("Escape")
                    await tab.wait_for_timeout(900)
        except DMError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("Couldn't open shared card %s", index, exc_info=True)
            raise DMError("I couldn't open a shared card; the DM check is incomplete.") from exc
    return list(dict.fromkeys(found))


async def _harvest_threads(tab, max_threads: int) -> list[str]:
    """Open each conversation in turn and collect the reels inside it."""
    found: list[str] = []
    try:
        count = await _conversation_rows(tab).count()
    except Exception as exc:  # noqa: BLE001
        raise DMError("I couldn't read Instagram's conversation list; the DM check is incomplete.") from exc

    for index in range(min(count, max_threads)):
        try:
            # Re-queried every time: going back re-renders the list, and a
            # locator captured before that points at a detached node.
            row = _conversation_rows(tab).nth(index)
            if not await row.count():
                continue
            await row.click(timeout=6000)
            await tab.wait_for_timeout(2500 + random.randint(0, 800))
            await _guard(tab)
            found.extend(await _links_on_page(tab))
            # The links on a thread page are profiles and chrome; the reels
            # themselves only exist once a card is opened.
            found.extend(await _reels_in_thread(tab))
            await tab.go_back(wait_until="domcontentloaded", timeout=20000)
            await tab.wait_for_timeout(1500)
        except DMError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("Couldn't read conversation %s", index, exc_info=True)
            raise DMError("I couldn't finish reading an Instagram conversation; the DM check is incomplete.") from exc
    return found


async def check(max_threads: int = 5) -> dict:
    """Look through every folder and return reels not seen before.

    Each folder gets its own fresh tab. Instagram restores its last route, so
    reusing one tab means the second folder is read as the first -- which is
    how an inbox holding a conversation got reported as empty three times
    running, with total confidence.
    """
    session = site_session.status()
    if not (session.get("linked") or await _has_instagram_account()):
        raise DMError(
            "Nova has no Instagram account set up. Add one in Settings -> Signing in -> "
            "Accounts, with the service named 'instagram'."
        )

    ready = await site_session.ensure_session("instagram")
    if not ready.get("ok"):
        raise DMError(ready.get("message") or "Couldn't get an Instagram session.")

    found: list[str] = []
    rows_seen = 0
    notes: list[str] = []
    shot_path = None
    tab = None

    try:
        # --- inbox ---------------------------------------------------------
        tab = await _fresh_tab(INBOX_URL)
        await tab.wait_for_timeout(6000)
        await _guard(tab)
        found.extend(await _links_on_page(tab))
        inbox_rows = await _conversation_rows(tab).count()
        rows_seen += inbox_rows
        notes.append(f"inbox:{inbox_rows}")
        found.extend(await _harvest_threads(tab, max_threads))
        if not rows_seen:
            shot_path = await _snapshot(tab)
        await tab.close()

        # --- requests, and the hidden folder behind it ----------------------
        tab = await _fresh_tab(REQUESTS_URL)
        await tab.wait_for_timeout(4000)
        await _guard(tab)
        found.extend(await _links_on_page(tab))
        request_rows = await _conversation_rows(tab).count()
        rows_seen += request_rows
        notes.append(f"requests:{request_rows}")
        found.extend(await _harvest_threads(tab, max_threads))

        if (await _open_hidden_requests(tab))["opened"]:
            found.extend(await _links_on_page(tab))
            hidden_rows = await _conversation_rows(tab).count()
            rows_seen += hidden_rows
            notes.append(f"hidden:{hidden_rows}")
            found.extend(await _harvest_threads(tab, max_threads))
    except DMError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.debug("Instagram DM check failed mid-walk", exc_info=True)
        raise DMError("I couldn't finish checking Instagram's folders. Please try again later.") from exc
    finally:
        if tab is not None:
            try:
                await tab.close()
            except Exception:  # noqa: BLE001
                pass

    found = list(dict.fromkeys(found))
    already = await _seen()
    fresh = [url for url in found if url not in already]
    return {
        "ok": True,
        "found": len(found),
        "new": fresh,
        # Per-folder counts rather than one total: "inbox:1 requests:0" says
        # the session is fine and the message is where it should be, which is
        # a different problem from "inbox:0" and needs a different answer.
        "rows": ", ".join(notes),
        "threads_seen": rows_seen,
        "screenshot": shot_path,
    }


async def _snapshot(tab) -> str | None:
    """A picture of the page when nothing was found.

    Text extraction and link scraping both describe the page through a
    keyhole: signed out, challenged, empty, and not-yet-rendered read
    identically through them and look completely different in an image.
    """
    try:
        from pathlib import Path as _Path
        path = str(_Path(config.DB_PATH).parent / "instagram-dm-debug.png")
        await tab.screenshot(path=path, full_page=False)
        return path
    except Exception:  # noqa: BLE001
        return None


async def _has_instagram_account() -> bool:
    from . import identity
    return any(a["service"].lower() == "instagram" for a in await identity.listing())


# One check at a time. The background poll and a manual "check now" can
# otherwise both be inside check() at once, both see the same unseen reel
# before either has recorded it, and both watch and announce it -- which is
# exactly what happened on the first successful run: one reel, two identical
# descriptions in the thread. Recording happens at the end of process(), so
# the window between finding and remembering is the whole watch, about ninety
# seconds, which is plenty of room for the poll to land in.
_check_lock = asyncio.Lock()


async def process(max_threads: int = 5) -> dict:
    """Check the inbox, look at anything new, and say so.

    Each reel goes through the same look_at everything else does, so a DM'd
    reel and a shared one produce the same description, the same follow-up
    question and the same notification. The route in should not change what
    Nova does with it.
    """
    from . import nova_tools, push, share

    if _check_lock.locked():
        return {"ok": True, "new": 0, "message": "A check is already running."}

    async with _check_lock:
        return await _process_locked(max_threads, nova_tools, push, share)


async def _process_locked(max_threads, nova_tools, push, share) -> dict:
    result = await check(max_threads=max_threads)
    fresh = result["new"]
    if not fresh:
        return {
            "ok": True, "new": 0,
            "message": "Nothing new in the DMs."
                       if result["threads_seen"]
                       else "No conversations were visible at all -- the session may have "
                            "lapsed, or Instagram served a page Nova couldn't read.",
            "found": result["found"],
            "threads_seen": result["threads_seen"],
            "rows": result["rows"],
            "screenshot": result.get("screenshot"),
        }

    conversation_id = await share._conversation()
    handled = []
    for url in fresh:
        await db.add_message(conversation_id, "user",
                             f"Sent to Nova on Instagram: {url}", category="everyday")
        try:
            looked = await nova_tools._look_at(url)
        except Exception as exc:  # noqa: BLE001
            logger.debug("look_at failed for a DM'd reel", exc_info=True)
            looked = {"ok": False, "error": str(exc)[:200]}

        if not looked.get("ok"):
            message = looked.get("error") or "I couldn't watch that one."
            await db.add_message(conversation_id, "assistant",
                                 f"{message}\n{url}", category="everyday")
            continue

        body = [(looked.get("shows") or "").strip()[:4000]]
        if looked.get("spoken"):
            body.append(f"\n**What's said:** {looked['spoken'][:600]}")
        body.append(f"\n{looked['ask_the_user']}")
        body.append(f"\n{url}")
        await db.add_message(conversation_id, "assistant", "\n".join(body), category="everyday")
        await push.send("Watched what you sent", looked["ask_the_user"],
                        url="/app/", tag="nova-dm")
        handled.append(url)

    # Remembered whether or not each one could be watched: a reel Nova cannot
    # read will still be unreadable in fifteen minutes, and retrying it every
    # cycle forever is how a quiet feature becomes a loop.
    await _remember(fresh)
    return {"ok": True, "new": len(fresh), "watched": len(handled)}


# --- the poll ---------------------------------------------------------------

_task: asyncio.Task | None = None


async def _loop() -> None:
    while True:
        delay = DEFAULT_INTERVAL_MINUTES * 60
        try:
            settings = await db.get_app_settings()
            if settings.get(ENABLED_KEY) == "1":
                try:
                    delay = max(300, int(settings.get(INTERVAL_KEY) or DEFAULT_INTERVAL_MINUTES) * 60)
                except ValueError:
                    pass
                await process()
        except DMError as exc:
            # Expected, actionable, and already explained -- a challenge has
            # switched the poll off by this point.
            logger.info("Instagram DM check stopped: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Instagram DM check failed")
        # Jitter, so the requests do not land on a metronome.
        await asyncio.sleep(delay + random.randint(0, 180))


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        await asyncio.gather(_task, return_exceptions=True)
        _task = None
