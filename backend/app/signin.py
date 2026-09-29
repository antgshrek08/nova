"""Signing Nova in to an account it already has.

The account exists because the user made it. The password is in the vault
because the user put it there. This is the step in between: open the sign-in
page, fill the two fields, submit, and say honestly what happened.

That last part is most of the work. A login attempt has more outcomes than
"worked" and "didn't", and the useful ones are the awkward middle: already
signed in, waiting on a code, blocked by a challenge. A tool that collapses
those into a boolean makes Nova claim it signed in when it is sitting on a
verification screen.

**The password does not pass through the model.** It is read from
secrets_store inside this process, handed to Playwright's `fill`, and
discarded. It is never returned, never logged, never in a tool argument or
result -- the same boundary type_secret holds, for the same reason: anything
in a prompt reaches whichever provider answered that turn and is written into
the transcript and the memory index.

**A CAPTCHA ends the attempt.** Not retried, not worked around, not solved.
The whole point of one is to establish that a person is present, and a tool
that defeats it is a tool for pretending otherwise. Nova stops and hands the
browser back with the page open, which is the one response that is both
honest and actually useful -- the user finishes the challenge in the window
that is already there, and the session persists from that point on.
"""
from __future__ import annotations

import logging

from . import browser_control, identity, secrets_store

logger = logging.getLogger(__name__)

# Ordered most- to least-specific. Playwright takes the first match, and an
# autocomplete attribute is a far better signal than a guess at a field name.
USERNAME_SELECTORS = [
    "input[autocomplete='username']",
    "input[type='email']",
    "input[name='username']",
    "input[name='email']",
    "input[name='login']",
    "input[id*='user' i]",
    "input[id*='email' i]",
]

PASSWORD_SELECTORS = [
    "input[autocomplete='current-password']",
    "input[type='password']",
    "input[name='password']",
]

SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Sign in')",
    "button:has-text('Log in')",
    "button:has-text('Login')",
    "button:has-text('Continue')",
]

# A missing login form is not evidence of a session (it could be a blank
# page or an error). Require a visible authenticated control instead.
SIGNED_IN_SELECTORS = [
    "button:has-text('Log out')", "a:has-text('Log out')",
    "button:has-text('Sign out')", "a:has-text('Sign out')",
    "button:has-text('Logout')", "a:has-text('Logout')",
]

# Text that means a human is required. Checked before claiming success,
# because a challenge page returns HTTP 200 and looks like any other page.
CHALLENGE_MARKERS = (
    "captcha", "recaptcha", "hcaptcha", "cloudflare", "are you a robot",
    "verify you are human", "unusual activity", "security check",
)

# Text that means the site wants a one-time code. Separated from challenges
# because this one Nova can often finish by itself now that it has a mailbox.
CODE_MARKERS = (
    "verification code", "one-time", "6-digit", "enter the code",
    "two-factor", "2-step", "authentication code", "we sent",
)

FAILURE_MARKERS = (
    "incorrect password", "wrong password", "invalid password",
    "couldn't find your account", "user not found", "invalid login",
    "incorrect username", "try again",
)


class SignInError(Exception):
    """Something the user can act on. Never carries the password."""


async def _first_present(tab, selectors: list[str]):
    """The first selector that actually resolves to something visible."""
    for selector in selectors:
        try:
            locator = tab.locator(selector).first
            if await locator.count() and await locator.is_visible():
                return locator
        except Exception:  # noqa: BLE001 -- a bad selector is not an error here
            continue
    return None


async def _page_text(tab) -> str:
    try:
        return (await tab.locator("body").inner_text())[:8000].lower()
    except Exception:  # noqa: BLE001
        return ""


# The path a site puts a human in the way on. Worth reading as well as the
# body text: a challenge page sometimes renders as a near-empty shell with the
# actual widget in a cross-origin iframe, whose text inner_text never sees.
_CHALLENGE_PATHS = ("/challenge", "/checkpoint", "/verify", "/two_factor", "/2fa")


def _classify(text: str, url: str) -> str | None:
    lowered_url = (url or "").lower()
    if any(marker in text for marker in CHALLENGE_MARKERS):
        return "challenge"
    if any(marker in text for marker in CODE_MARKERS):
        return "needs_code"
    if any(path in lowered_url for path in _CHALLENGE_PATHS):
        # The page said nothing recognisable, but the address says a human is
        # being asked for. "unclear, and here is the browser" is the honest
        # answer; claiming a session that does not exist is not.
        return "challenge"
    if any(marker in text for marker in FAILURE_MARKERS):
        return "rejected"
    return None


async def sign_in(service: str) -> dict:
    """Open the account's sign-in page and log in.

    Returns a state rather than a boolean: signed_in, needs_code, challenge,
    rejected, or unclear. `unclear` is a real answer and is used when the page
    gives no evidence either way -- guessing "signed in" there is how a tool
    ends up lying.
    """
    accounts = {a["service"].lower(): a for a in await identity.listing()}
    account = accounts.get((service or "").strip().lower())
    if account is None:
        raise SignInError(
            f"No account recorded for '{service}'. Add it in Settings → Accounts first."
        )
    if not account.get("url"):
        raise SignInError(
            f"'{account['service']}' has no sign-in page saved. Add the URL in Settings → Accounts."
        )
    password = secrets_store.get(identity.secret_name(account["service"]))
    if not password:
        raise SignInError(
            f"No password is stored for '{account['service']}'. Add one in Settings → Accounts."
        )

    tab = await browser_control.page()
    await tab.goto(account["url"], wait_until="domcontentloaded", timeout=30000)
    await tab.wait_for_timeout(1200)

    async def blocked():
        # Check before entering credentials, including after a username-only
        # step. Challenges can coexist with password fields.
        text = await _page_text(tab)
        state = _classify(text, tab.url)
        if state == "challenge":
            return _result("challenge", account, tab,
                           "The site is showing a human-verification challenge. I've left the "
                           "browser open on it -- finish it there and the session will stick.")
        # "No password field" is not the same as "signed in", and every state
        # except challenge used to be collapsed into the latter. A code screen
        # has no password field either, so landing on one reported a session
        # Nova did not have -- the exact lie the states above exist to avoid.
        if state == "needs_code":
            return _result("needs_code", account, tab,
                           "It's asking for a verification code before letting Nova in. If it went "
                           "to Nova's address, ask me to check the email and I'll read it out.")
        if state == "rejected":
            return _result("rejected", account, tab,
                           "The site is showing a sign-in error rather than a form. The stored "
                           "password may be out of date.")
        return None

    async def session_result():
        if await _first_present(tab, SIGNED_IN_SELECTORS) is not None:
            return _result("signed_in", account, tab, f"Signed in to {account['service']}.")
        return _result("unclear", account, tab,
                       "I couldn't confirm a signed-in session. The browser is open there.")

    stopped = await blocked()
    if stopped:
        return stopped

    username_field = await _first_present(tab, USERNAME_SELECTORS)
    password_field = await _first_present(tab, PASSWORD_SELECTORS)
    if username_field is None and password_field is None:
        return await session_result()
    if username_field is not None:
        await username_field.fill(account["username"])
        await tab.wait_for_timeout(200)

    password_field = await _first_present(tab, PASSWORD_SELECTORS)
    if password_field is None:
        # Two-step forms ask for the username first. Submit and look again.
        submit = await _first_present(tab, SUBMIT_SELECTORS)
        if submit is not None:
            await submit.click()
            await tab.wait_for_timeout(2000)
        stopped = await blocked()
        if stopped:
            return stopped
        password_field = await _first_present(tab, PASSWORD_SELECTORS)
    if password_field is None:
        return _result("unclear", account, tab,
                       "I couldn't find a password field on that page. The browser is open "
                       "there if you want to look.")

    # The one place the secret is used. It is not returned, logged, or put in
    # a tool result; `password` goes out of scope with this function.
    await password_field.fill(password)
    submit = await _first_present(tab, SUBMIT_SELECTORS)
    if submit is not None:
        await submit.click()
    else:
        await password_field.press("Enter")
    await tab.wait_for_timeout(3500)

    text = await _page_text(tab)
    state = _classify(text, tab.url)

    if state == "challenge":
        return _result("challenge", account, tab,
                       "The site put up a human-verification challenge. I don't attempt those. "
                       "The browser is open on it -- finish it there and the session persists.")
    if state == "needs_code":
        return _result("needs_code", account, tab,
                       "It's asking for a verification code. If it was sent to Nova's address, "
                       "ask me to check the email and I'll read it out.")
    if state == "rejected":
        return _result("rejected", account, tab,
                       "The site rejected those details. The stored password may be out of date.")
    if await _first_present(tab, PASSWORD_SELECTORS) is not None:
        # Still on a password form after submitting: not signed in, whatever
        # the page says about itself.
        return _result("unclear", account, tab,
                       "Still on a sign-in form after submitting, so it didn't go through. "
                       "The browser is open there.")
    if await _first_present(tab, USERNAME_SELECTORS) is not None:
        return _result("unclear", account, tab,
                       "Still on a sign-in form after submitting. The browser is open there.")
    return await session_result()


def _result(state: str, account: dict, tab, message: str) -> dict:
    return {
        "ok": state == "signed_in",
        "state": state,
        "service": account["service"],
        "url": tab.url,
        "message": message,
    }
