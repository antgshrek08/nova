"""Letting Nova read the sites the user is signed in to.

Instagram and TikTok serve almost nothing to a logged-out client. Every reel
the user shares to Nova comes back as "Saved the link. I can't watch Instagram
posts -- they need a logged-in session", which is an honest answer to the
wrong problem: the session exists, it just lives in a browser Nova cannot
reach.

Nova now has its own persistent browser profile (see browser_control). So the
shape of the fix is: the user signs in there, once, by hand -- their
credentials, their two-factor prompt, their challenge if one appears -- and
Nova exports the resulting cookies for yt-dlp to reuse. After that, a shared
reel is readable.

Nova can also do the signing in itself, when the user has recorded an account
for the site (see ensure_session). "Look at the reel I sent you" should be the
whole instruction, not the first of three. What that means in practice: Nova
authenticates as itself, to its own account, so that it can read a link the
user handed it.

The line that does not move is what happens after. This is not scraping and
not engagement. The only thing that reads a page is yt-dlp, fetching the
captions of a specific URL the user chose to send. No feed is walked, nothing
is liked, nobody is followed, nothing is posted. Automated interaction is what
Instagram's terms actually prohibit and what gets accounts disabled; reading
one link you were given is neither.

And a challenge still ends it. If the site asks for a human, Nova stops and
says so rather than working around it -- the browser is left open on the
challenge, the user clears it once, and the session persists from then on.

The cookies.txt route rather than yt-dlp's own --cookies-from-browser is
forced by Windows: Chrome's cookie database is locked while it runs (yt-dlp
#7271) and Edge's app-bound encryption defeats DPAPI (#10927). Reading them
out of the live Playwright context sidesteps both, because that context is
Nova's own and already open.

"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from . import browser_control, config

logger = logging.getLogger(__name__)

ENV_NAME = "NOVA_COOKIES_FILE"

# Where the exported jar lives: beside the database, never in the repo. These
# are live session cookies for the user's real accounts -- the same category
# of secret as the browser profile itself.
def cookies_path() -> Path:
    path = Path(config.DB_PATH).parent / "site-cookies.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# Sites worth linking, and where signing in starts.
KNOWN_SITES = {
    "instagram": ("https://www.instagram.com/accounts/login/", [".instagram.com", "instagram.com"]),
    "tiktok": ("https://www.tiktok.com/login", [".tiktok.com", "tiktok.com"]),
    "youtube": ("https://accounts.google.com/ServiceLogin?service=youtube",
                [".youtube.com", "youtube.com", ".google.com", "google.com"]),
    "x": ("https://x.com/i/flow/login", [".x.com", "x.com", ".twitter.com", "twitter.com"]),
    "reddit": ("https://www.reddit.com/login", [".reddit.com", "reddit.com"]),
}

# The key is a lookup token; this is what a person calls it. Worth the four
# lines: the first draft said "I don't have a instagram account", which reads
# as carelessness in the one message whose whole job is telling the user what
# to go and do.
DISPLAY_NAMES = {
    "instagram": "Instagram", "tiktok": "TikTok", "youtube": "YouTube",
    "x": "X", "reddit": "Reddit",
}


def display_name(site: str) -> str:
    return DISPLAY_NAMES.get(site, site)


def an(site: str) -> str:
    """"an Instagram account" / "a TikTok account" -- article included."""
    name = display_name(site)
    return f"{'an' if name[:1].upper() in 'AEIOUX' else 'a'} {name}"


class SiteSessionError(Exception):
    """Something the user can act on."""


async def open_login(site: str) -> dict:
    """Open the site's login page in Nova's browser for the user to use.

    Nova does not type anything here. The window is handed over.
    """
    key = (site or "").strip().lower()
    if key not in KNOWN_SITES:
        raise SiteSessionError(
            f"I don't have a login page for '{site}'. Known: {', '.join(sorted(KNOWN_SITES))}."
        )
    url, _ = KNOWN_SITES[key]
    tab = await browser_control.page()
    await tab.goto(url, wait_until="domcontentloaded", timeout=30000)
    return {
        "ok": True,
        "site": key,
        "url": tab.url,
        "message": (
            f"Opened {display_name(key)} in Nova's browser. Sign in there yourself -- including any "
            "two-factor step. When you're done, tell me to save the session."
        ),
    }


def _netscape_line(cookie: dict) -> str | None:
    """One cookie in the Netscape format yt-dlp reads.

    Fields: domain, include-subdomains flag, path, secure flag, expiry, name,
    value -- tab separated. A session cookie has no expiry; yt-dlp accepts 0
    there, and those are the ones that matter least anyway since they die with
    the browser.
    """
    domain = cookie.get("domain") or ""
    name = cookie.get("name")
    if not domain or not name:
        return None
    include_sub = "TRUE" if domain.startswith(".") else "FALSE"
    secure = "TRUE" if cookie.get("secure") else "FALSE"
    expires = cookie.get("expires")
    # Playwright uses -1 for session cookies.
    expiry = 0 if not expires or expires < 0 else int(expires)
    return "\t".join([
        domain, include_sub, cookie.get("path") or "/", secure,
        str(expiry), name, cookie.get("value") or "",
    ])


def _wanted_domains(site: str | None) -> list[str]:
    if site:
        key = site.strip().lower()
        if key not in KNOWN_SITES:
            raise SiteSessionError(f"Unknown site '{site}'.")
        return KNOWN_SITES[key][1]
    # Every linkable site, and nothing else. The first version exported the
    # whole jar on the reasoning that the profile only holds sites the user
    # chose to sign into -- which is false: Edge arrives with its own
    # bing.com and msn.com cookies from the new-tab page, and the first real
    # run wrote live Microsoft account tokens into a plaintext file nobody
    # had asked for. An allowlist cannot make that mistake.
    return [domain for _url, domains in KNOWN_SITES.values() for domain in domains]


async def save_session(site: str | None = None) -> dict:
    """Export cookies from Nova's browser so yt-dlp can reuse the session.

    Scoped to the sites this feature is for. Anything else in the profile --
    including whatever the browser vendor put there itself -- stays where it
    is.
    """
    context = browser_control._browser
    if not browser_control._alive(context):
        raise SiteSessionError("Nova's browser isn't open. Ask me to open the login page first.")

    wanted = [d.lstrip(".") for d in _wanted_domains(site)]

    def _allowed(domain: str) -> bool:
        # The domain or a subdomain of it -- not merely a string ending in it.
        # `endswith("instagram.com")` also accepts `notinstagram.com`, which is
        # the one thing an allowlist exists to prevent, and site_for_url below
        # already got this right. Two spellings of the same rule is how the
        # careless one survives review.
        host = (domain or "").lstrip(".").lower()
        return any(host == d or host.endswith("." + d) for d in wanted)

    cookies = [c for c in await context.cookies() if _allowed(c.get("domain") or "")]

    lines = [line for line in (_netscape_line(c) for c in cookies) if line]
    if not lines:
        raise SiteSessionError(
            "No cookies found for that site yet -- sign in in Nova's browser window first."
        )

    path = cookies_path()
    # newline="" so Python does not translate these to CRLF on Windows.
    # yt-dlp's Netscape parser splits on \n and keeps the \r, which lands on
    # the end of the cookie's value and quietly corrupts every one of them --
    # a jar that loads without complaint and authenticates nothing.
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(
            "# Netscape HTTP Cookie File\n"
            f"# Written by Nova from its own browser profile, {time.strftime('%Y-%m-%d %H:%M')}\n"
            + "\n".join(lines) + "\n"
        )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    config.write_env_value(ENV_NAME, str(path))

    domains = sorted({(c.get("domain") or "").lstrip(".") for c in cookies})
    return {
        "ok": True,
        "cookies": len(lines),
        "domains": domains[:12],
        "path": str(path),
        "message": (
            f"Saved {len(lines)} cookies. Nova can now read links from "
            f"{', '.join(domains[:4])}{'…' if len(domains) > 4 else ''} that you share to it."
        ),
    }


# What a login wall looks like coming back from yt-dlp. Matched loosely on
# purpose: each extractor words it differently and the wording changes, and
# the cost of a false positive here is one wasted sign-in attempt, while the
# cost of a false negative is the feature silently not working.
LOGIN_WALL_MARKERS = (
    "login required", "log in", "rate-limit reached", "empty media response",
    "requested content is not available", "sign in", "cookies", "private",
    "restricted video", "age-restricted", "age restricted", "authenticate",
)

# Matched on word boundaries. As plain substrings this list was effectively
# always true: "age" is inside "message", "page" and "usage", so any error
# mentioning a page -- which is most of them -- looked like a login wall and
# Nova offered to sign in to fix a 404. The marker that caused it is now
# spelled out as "age-restricted", which is what it was ever meant to catch.
_LOGIN_WALL_RE = re.compile(
    "|".join(rf"\b{re.escape(marker)}\b" for marker in LOGIN_WALL_MARKERS)
)


def looks_login_walled(error: str) -> bool:
    return bool(_LOGIN_WALL_RE.search((error or "").lower()))


def site_for_url(url: str) -> str | None:
    """Which linkable site a URL belongs to, if any."""
    from urllib.parse import urlparse
    host = (urlparse(url or "").hostname or "").lower().lstrip(".")
    for key, (_login_url, domains) in KNOWN_SITES.items():
        if any(host == d.lstrip(".") or host.endswith("." + d.lstrip(".")) for d in domains):
            return key
    return None


def has_session_for(site: str) -> bool:
    """Is there already an exported session covering this site?"""
    state = status()
    if not state.get("linked"):
        return False
    wanted = [d.lstrip(".") for d in KNOWN_SITES.get(site, ("", []))[1]]
    hosts = [(domain or "").lower().lstrip(".") for domain in state.get("domains", [])]
    return any(host == domain or host.endswith("." + domain)
               for host in hosts for domain in wanted)


async def ensure_session(site: str) -> dict:
    """Get a usable session for `site`, signing in if Nova can.

    This is the difference between "Nova can read Instagram once you set it
    up" and "ask Nova to look at a reel and it handles it". The chain is:
    already have a session -> else sign in with the account the user recorded
    -> save the resulting cookies. Every step can fail in a way that needs a
    person, and each says so rather than pretending.

    Signing in is Nova authenticating as itself to its own account. It is not
    automated interaction with the site: nothing is liked, followed or posted,
    and the session exists so a link the user handed Nova can be read.
    """
    from . import identity, signin

    if has_session_for(site):
        return {"ok": True, "state": "already_linked", "site": site}

    accounts = {a["service"].lower(): a for a in await identity.listing()}
    account = accounts.get(site)
    if account is None:
        return {
            "ok": False, "state": "no_account", "site": site,
            "message": (
                f"I don't have {an(site)} account to sign in with. Add one in "
                f"Settings → Accounts (service name '{site}', with its password) and I can "
                "do this myself next time."
            ),
        }
    if not account.get("has_password"):
        return {
            "ok": False, "state": "no_password", "site": site,
            "message": f"The {display_name(site)} account has no stored password, so I can't sign in to it.",
        }

    # Fall back to the site's own login page when the account row has none,
    # which is the common case for one added just to let Nova read links.
    if not account.get("url"):
        await identity.add(service=account["service"], username=account["username"],
                           url=KNOWN_SITES[site][0], email=account.get("email"),
                           notes=account.get("notes"))

    result = await signin.sign_in(account["service"])
    if result["state"] == "challenge":
        return {
            "ok": False, "state": "challenge", "site": site,
            "message": (
                f"{display_name(site)} put up a human-verification check on the sign-in. I don't work around "
                "those. It's open in Nova's browser window -- finish it there and I'll be able "
                "to read these links from then on."
            ),
        }
    if result["state"] == "needs_code":
        return {
            "ok": False, "state": "needs_code", "site": site,
            "message": (
                f"{display_name(site)} wants a verification code to finish signing in. If it went to Nova's "
                "email address, ask me to check and I'll read it out."
            ),
        }
    if not result["ok"]:
        return {"ok": False, "state": result["state"], "site": site,
                "message": result.get("message", f"Couldn't sign in to {display_name(site)}.")}

    saved = await save_session(site)
    return {"ok": True, "state": "signed_in_and_saved", "site": site,
            "cookies": saved["cookies"]}


def status() -> dict:
    path = cookies_path()
    configured = config.read_env_value(ENV_NAME)
    if not path.is_file():
        return {"linked": False, "reason": "No session has been saved yet."}
    try:
        lines = [l for l in path.read_text("utf-8").splitlines() if l and not l.startswith("#")]
    except OSError as exc:
        return {"linked": False, "reason": f"Couldn't read the saved session: {exc}"}
    domains = sorted({l.split("\t")[0].lstrip(".") for l in lines if "\t" in l})
    return {
        "linked": bool(lines) and bool(configured),
        "cookies": len(lines),
        "domains": domains[:12],
        "saved_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime)),
    }


def forget() -> dict:
    """Drop the exported jar. Does not sign the browser out -- that is the
    user's own session in their own profile, and removing Nova's copy of the
    cookies is a smaller action than ending it."""
    path = cookies_path()
    existed = path.is_file()
    if existed:
        path.unlink()
    config.write_env_value(ENV_NAME, "")
    return {"ok": True, "removed": existed}
