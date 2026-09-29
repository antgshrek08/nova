PROCTOR_KEYWORDS = ('honorlock', 'lockdown', 'respondus', 'proctorio', 'proctortrack', 'examity')
"""Nova-owned browser session; never attaches to the user's existing tabs.

Two backends behind one `perform()`:

- **Onyx** (the default when it is installed): the user's own browser, driven
  over its local agent port with a visible cursor. Nova works only in tabs it
  opened itself -- Onyx is also where the user browses, and their tabs are not
  Nova's to touch. See app/onyx.py.
- **Edge** (Playwright, persistent profile): one window Nova drives itself.
  Still what coursework, Instagram and the cookie export use -- they were
  tuned against it -- and the fallback when Onyx is missing.

Page contents are untrusted data, never instructions -- callers fold them
into the model's context labelled as such.
"""
import asyncio
import os
import sys
import base64
from pathlib import Path
from urllib.parse import urlparse

_driver = _browser = _page = None
_current_channel = None
_current_headless = None
# Set when the requested browser could not be launched and another was used,
# so the result can say so instead of silently switching browsers.
_launch_note = None
_lock = asyncio.Lock()

# Every browser Nova can drive, and how. Chromium-family browsers other than
# Chrome and Edge are launched from their own executable; Firefox and WebKit
# use Playwright's own builds of those engines (Playwright cannot drive a
# stock Firefox install, and WebKit is Safari's engine, not Safari).
BROWSERS = {
    "onyx": {"name": "Onyx", "engine": "chromium", "how": "Onyx's agent port, with Nova's in-page cursor"},
    "chrome": {"name": "Google Chrome", "engine": "chromium", "how": "Playwright, Chrome channel"},
    "msedge": {"name": "Microsoft Edge", "engine": "chromium", "how": "Playwright, Edge channel"},
    "brave": {"name": "Brave", "engine": "chromium", "how": "Playwright, installed Brave executable"},
    "vivaldi": {"name": "Vivaldi", "engine": "chromium", "how": "Playwright, installed Vivaldi executable"},
    "opera": {"name": "Opera", "engine": "chromium", "how": "Playwright, installed Opera executable"},
    "operagx": {"name": "Opera GX", "engine": "chromium", "how": "Playwright, installed Opera GX executable"},
    "arc": {"name": "Arc", "engine": "chromium", "how": "Playwright, installed Arc executable"},
    "chromium": {"name": "Chromium", "engine": "chromium", "how": "Playwright's bundled Chromium"},
    "firefox": {"name": "Firefox", "engine": "firefox", "how": "Playwright's Firefox build (not your installed Firefox profile)"},
    "webkit": {"name": "WebKit (Safari's engine)", "engine": "webkit", "how": "Playwright's WebKit build; real Safari cannot be automated this way"},
}
_EXECUTABLE_CHANNELS = ("brave", "vivaldi", "opera", "operagx", "arc")
# Tried in this order when the requested browser cannot be launched.
_FALLBACK_ORDER = ("chrome", "msedge", "brave", "vivaldi", "opera", "operagx", "arc", "chromium")


def normalize_browser(name: str | None) -> str | None:
    """A browser id from anything a user or model might call it; None if unrecognized."""
    c = (name or "").lower().strip()
    if not c:
        return None
    if "gx" in c:
        return "operagx"
    for key, ids in (("opera", "opera"), ("firefox", "firefox"), ("vivaldi", "vivaldi"),
                     ("brave", "brave"), ("onyx", "onyx"), ("chromium", "chromium")):
        if key in c:
            return ids
    if "webkit" in c or "safari" in c:
        return "webkit"
    if c == "arc" or c.startswith("arc "):
        return "arc"
    if "chrome" in c:
        return "chrome"
    if "edge" in c:
        return "msedge"
    return None


async def visibility() -> str:
    """"visible" or "hidden": whether Nova works in a browser window the user
    can see, or out of sight (a headless browser, or Nova's own hidden Onyx
    window). The setting's older values "silent" and "headless" mean hidden."""
    if os.environ.get('NOVA_BROWSER_HEADLESS') == '1':
        return "hidden"
    try:
        from . import db
        mode = (await db.get_app_settings()).get("browser_visibility_mode", "")
    except Exception:  # noqa: BLE001 -- no settings table yet: use the default
        mode = ""
    return "visible" if mode == "visible" else "hidden"

# A persistent profile, so a signed-in session survives Nova restarting.
def _profile_dir(channel=None):
    from . import config
    sub = f"browser-profile-{channel}" if channel else "browser-profile"
    path = Path(config.DB_PATH).parent / sub
    path.mkdir(parents=True, exist_ok=True)
    return path

ACTIONS = (
    "navigate", "inspect", "click", "hover", "fill", "scroll", "press", "text",
    "back", "new_tab", "screenshot", "drag",
)


def _alive(context) -> bool:
    if context is None:
        return False
    try:
        browser = context.browser
        if browser is not None:
            return browser.is_connected()
        context.pages
        return True
    except Exception:  # noqa: BLE001 -- any failure here means "relaunch it"
        return False


def _find_browser_exe(name: str) -> str | None:
    import shutil
    import sys
    from pathlib import Path

    home = str(Path.home())
    name = (name or "").lower().strip()

    # 1. Direct which lookup across all platforms
    which_map = {
        "operagx": ["opera-gx", "opera", "launcher"],
        "brave": ["brave-browser", "brave"],
        "arc": ["arc"],
        "vivaldi": ["vivaldi", "vivaldi-stable"],
        "opera": ["opera"],
        "chrome": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"],
        "msedge": ["microsoft-edge", "microsoft-edge-stable", "msedge", "edge"],
        "firefox": ["firefox", "firefox-esr"],
        "chromium": ["chromium", "chromium-browser"],
    }
    for bin_name in which_map.get(name, [name]):
        found = shutil.which(bin_name)
        if found:
            return found

    # 2. Windows paths
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

        candidates_win = {
            "operagx": [
                os.path.join(local_appdata, r"Programs\Opera GX\opera.exe"),
                os.path.join(local_appdata, r"Programs\Opera\launcher.exe"),
                os.path.join(program_files, r"Opera GX\opera.exe"),
            ],
            "brave": [
                os.path.join(program_files, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
                os.path.join(local_appdata, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
                os.path.join(program_files_x86, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
            ],
            "vivaldi": [
                os.path.join(local_appdata, r"Vivaldi\Application\vivaldi.exe"),
                os.path.join(program_files, r"Vivaldi\Application\vivaldi.exe"),
            ],
            "opera": [
                os.path.join(local_appdata, r"Programs\Opera\opera.exe"),
                os.path.join(local_appdata, r"Programs\Opera\launcher.exe"),
                os.path.join(program_files, r"Opera\opera.exe"),
            ],
            "arc": [
                os.path.join(local_appdata, r"Programs\Arc\Arc.exe"),
                os.path.join(local_appdata, r"Microsoft\WindowsApps\Arc.exe"),
            ],
            "chrome": [
                os.path.join(program_files, r"Google\Chrome\Application\chrome.exe"),
                os.path.join(program_files_x86, r"Google\Chrome\Application\chrome.exe"),
                os.path.join(local_appdata, r"Google\Chrome\Application\chrome.exe"),
            ],
            "msedge": [
                os.path.join(program_files_x86, r"Microsoft\Edge\Application\msedge.exe"),
                os.path.join(program_files, r"Microsoft\Edge\Application\msedge.exe"),
            ],
            "firefox": [
                os.path.join(program_files, r"Mozilla Firefox\firefox.exe"),
                os.path.join(program_files_x86, r"Mozilla Firefox\firefox.exe"),
            ]
        }
        for p in candidates_win.get(name, []):
            if os.path.isfile(p):
                return p

    # 3. macOS paths
    elif sys.platform == "darwin":
        candidates_mac = {
            "chrome": [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                f"{home}/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            ],
            "brave": [
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                f"{home}/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            ],
            "vivaldi": [
                "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",
                f"{home}/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",
            ],
            "opera": [
                "/Applications/Opera.app/Contents/MacOS/Opera",
                f"{home}/Applications/Opera.app/Contents/MacOS/Opera",
            ],
            "arc": [
                "/Applications/Arc.app/Contents/MacOS/Arc",
                f"{home}/Applications/Arc.app/Contents/MacOS/Arc",
            ],
            "msedge": [
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                f"{home}/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            ],
            "operagx": [
                "/Applications/Opera GX.app/Contents/MacOS/Opera GX",
                "/Applications/Opera.app/Contents/MacOS/Opera",
                f"{home}/Applications/Opera GX.app/Contents/MacOS/Opera GX",
            ],
            "firefox": [
                "/Applications/Firefox.app/Contents/MacOS/Firefox",
                f"{home}/Applications/Firefox.app/Contents/MacOS/Firefox",
            ]
        }
        for p in candidates_mac.get(name, []):
            if os.path.isfile(p):
                return p

    # 4. Linux paths
    else:
        candidates_linux = {
            "chrome": [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/snap/bin/chromium",
                "/var/lib/flatpak/exports/bin/org.chromium.Chromium",
            ],
            "brave": [
                "/usr/bin/brave-browser",
                "/usr/bin/brave",
                "/snap/bin/brave",
                "/var/lib/flatpak/exports/bin/com.brave.Browser",
            ],
            "vivaldi": [
                "/usr/bin/vivaldi",
                "/usr/bin/vivaldi-stable",
                "/var/lib/flatpak/exports/bin/com.vivaldi.Vivaldi",
            ],
            "opera": [
                "/usr/bin/opera",
                "/snap/bin/opera",
            ],
            "operagx": [
                "/usr/bin/opera-gx",
                "/usr/bin/opera",
                "/snap/bin/opera",
            ],
            "msedge": [
                "/usr/bin/microsoft-edge",
                "/usr/bin/microsoft-edge-stable",
                "/usr/bin/microsoft-edge-dev",
            ],
            "firefox": [
                "/usr/bin/firefox",
                "/usr/bin/firefox-esr",
                "/snap/bin/firefox",
                "/var/lib/flatpak/exports/bin/org.mozilla.firefox",
            ]
        }
        for p in candidates_linux.get(name, []):
            if os.path.isfile(p):
                return p

    return None


async def page(channel: str | None = None, visible: bool | None = None):
    """Nova's Playwright page. visible=True shows the window whatever the
    hidden/visible setting says -- for a sign-in the user has to see."""
    global _driver, _browser, _page, _current_channel, _current_headless, _launch_note
    req_channel = normalize_browser(channel)
    if req_channel == 'onyx':
        req_channel = None  # Onyx is driven through perform(), not Playwright
    if not req_channel:
        try:
            from . import db
            settings = await db.get_app_settings()
            req_channel = normalize_browser(settings.get("preferred_browser") or settings.get("browser_backend"))
        except Exception:  # noqa: BLE001
            pass
    if not req_channel or req_channel == 'onyx':
        req_channel = 'chrome'  # Default to Chrome, with the fallbacks below
    headless = False if visible else (await visibility()) == "hidden"

    # Switching browser or visibility needs a relaunch; a headless browser
    # cannot be made visible in place.
    if _browser and _current_channel and (_current_channel != req_channel or _current_headless != headless):
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = _page = None

    if _page is None or _page.is_closed() or not _alive(_browser):
        from playwright.async_api import async_playwright
        if _driver is None:
            _driver = await async_playwright().start()
        if not _alive(_browser):
            _browser = None
            failures = []
            channels_to_try = [req_channel] + [ch for ch in _FALLBACK_ORDER if ch != req_channel]
            for ch in channels_to_try:
                ch_profile = str(_profile_dir(ch))
                try:
                    if ch == 'firefox':
                        _browser = await _driver.firefox.launch_persistent_context(ch_profile, headless=headless)
                    elif ch == 'webkit':
                        _browser = await _driver.webkit.launch_persistent_context(ch_profile, headless=headless)
                    elif ch in _EXECUTABLE_CHANNELS:
                        exe = _find_browser_exe(ch)
                        if not exe:
                            failures.append(ch)
                            continue
                        _browser = await _driver.chromium.launch_persistent_context(
                            ch_profile, executable_path=exe, headless=headless,
                            args=['--no-first-run', '--no-default-browser-check'])
                    elif ch in ('chrome', 'msedge'):
                        _browser = await _driver.chromium.launch_persistent_context(
                            ch_profile, channel=ch, headless=headless)
                    else:
                        _browser = await _driver.chromium.launch_persistent_context(ch_profile, headless=headless)
                    _current_channel = ch
                    break
                except Exception:  # noqa: BLE001 -- not installed or would not start: try the next
                    failures.append(ch)
                    continue

            if not _browser:
                raise RuntimeError(
                    f"No browser could be started for Nova (tried {', '.join(channels_to_try)}). "
                    "Install Chrome or Edge, or run `playwright install chromium`.")
            _current_headless = headless
            _launch_note = None if _current_channel == req_channel else (
                f"{BROWSERS[req_channel]['name']} could not be started here, so Nova used "
                f"{BROWSERS[_current_channel]['name']} instead.")

        existing = [p for p in _browser.pages if not p.is_closed()]
        _page = existing[0] if existing else await _browser.new_page()
        _page.set_default_timeout(15000)
    return _page


def _check_url(url: str) -> str:
    parsed = urlparse(url or '')
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Browser navigation requires an HTTP(S) URL without embedded credentials.')
    return url


async def _snapshot(tab, include_text: bool = False) -> dict:
    # The accessibility snapshot exposes labels and controls without executing
    # model-supplied JavaScript or echoing back the values typed into inputs.
    state = {'url': tab.url, 'title': await tab.title()}
    if include_text:
        try:
            body = await tab.locator('body').inner_text()
        except Exception:  # noqa: BLE001 - some pages have no body yet
            body = ''
        state['text'] = body[:14000]
    else:
        state['page'] = (await tab.locator('body').aria_snapshot())[:12000]
    return state


async def _backend() -> tuple[str, str]:
    """(backend, onyx_path) from app settings. Onyx unless told otherwise."""
    try:
        from . import db
        stored = await db.get_app_settings()
    except Exception:  # noqa: BLE001 -- no settings table yet: use defaults
        stored = {}
    return stored.get('browser_backend', 'onyx') or 'onyx', stored.get('onyx_path', '')


# How much page text rides along with an Onyx inspect.
INSPECT_TEXT_CHARS = 3000

# The Onyx tabs Nova opened, newest last. Nova acts only in these: Onyx is
# also the user's own browser, and whatever they have open there is not Nova's.
_onyx_tabs: list[str] = []
_onyx_lock = asyncio.Lock()


async def _onyx_tab(onyx_path: str, fresh: bool = False, url: str | None = None) -> tuple[str, bool]:
    """Nova's current Onyx tab, opening one if it has none left (or `fresh`).
    Returns (tab id, whether it was just opened -- at `url` if one was given)."""
    from . import onyx
    if not fresh and _onyx_tabs:
        live_tabs = await onyx.call('tabs_list', onyx_path)
        live = {t['id'] for t in live_tabs}
        # The user may have closed Nova's tab; forget any that are gone.
        while _onyx_tabs and _onyx_tabs[-1] not in live:
            _onyx_tabs.pop()
        if _onyx_tabs:
            return _onyx_tabs[-1], False
    opened = await onyx.call('tab_open', onyx_path, url=url)
    _onyx_tabs.append(opened['id'])
    return opened['id'], True


async def _onyx_state(onyx_path: str, tab: str, include_text: bool = False) -> dict:
    from . import onyx
    snap = await onyx.call('page_read', onyx_path, tabId=tab,
                           maxText=14000 if include_text else INSPECT_TEXT_CHARS,
                           maxElements=0 if include_text else 300)
    state = {'url': snap.get('url', ''), 'title': snap.get('title', ''), 'browser': 'onyx'}
    if include_text:
        state['text'] = snap.get('text', '')
    else:
        # The controls, plus the start of the page's text: after a click the
        # evidence that it worked ("Saved", "Hello Nova") is usually text, and
        # an inspect that only listed buttons would hide it -- the Edge path's
        # accessibility snapshot always carried both.
        excerpt = (snap.get('text') or '').strip()
        controls = onyx.describe_elements(snap.get('elements') or [])
        state['page'] = f"Text:\n{excerpt}\n\nControls:\n{controls}" if excerpt else controls
        state['how_to_target'] = ('Use the number in brackets as the selector (e.g. "12"), '
                                  'or text=Label, or a CSS selector.')
    return state


async def _perform_onyx(action, url, selector, text, keys, pixels, onyx_path, toggle=False, to=None):
    from . import onyx
    if action not in ACTIONS:
        raise ValueError(f'Unknown browser action. Use one of: {", ".join(ACTIONS)}.')
    async with _onyx_lock:
        if action == 'new_tab':
            tab, _ = await _onyx_tab(onyx_path, fresh=True, url=_check_url(url) if url else None)
            return await _onyx_state(onyx_path, tab)

        destination = _check_url(url) if action == 'navigate' else None
        tab, created = await _onyx_tab(onyx_path, url=destination)
        extra: dict = {}

        if action == 'navigate':
            if not created:
                await onyx.call('navigate', onyx_path, url=destination, tabId=tab)
        elif action == 'back':
            await onyx.call('back', onyx_path, tabId=tab)
        if action in ('click', 'fill', 'drag', 'press'):
            tab_list = await onyx.call('tabs_list', onyx_path)
            tab_info = next((t for t in tab_list if t.get('id') == tab), {})
            tab_meta = f"{tab_info.get('url', '')} {tab_info.get('title', '')}".lower()
            for kw in PROCTOR_KEYWORDS:
                if kw in tab_meta:
                    raise PermissionError(
                        f"Proctored test environment detected ({kw.capitalize()}). "
                        "Automated browser actions are paused to protect your academic standing."
                    )

        if action == 'click':
            if not selector:
                raise ValueError('click needs a selector. Run inspect first and use a ref you actually saw.')
            before_tabs = {t['id'] for t in await onyx.call('tabs_list', onyx_path)}
            result = await onyx.call('click', onyx_path, tabId=tab, **({'toggle': True} if toggle else {}), **onyx.target(selector))
            extra['clicked'] = result.get('clicked')
            if result.get('obscuredBy'):
                extra['warning'] = (f"{result['obscuredBy']} was drawn over the target -- "
                                    'check the click did what you meant.')
            await asyncio.sleep(0.5)
            after_tabs = await onyx.call('tabs_list', onyx_path)
            new_tabs = [t for t in after_tabs if t['id'] not in before_tabs]
            if new_tabs:
                tab = new_tabs[-1]['id']
                _onyx_tabs.append(tab)
                await onyx.call('tab_activate', onyx_path, tabId=tab)
        elif action == 'hover':
            if not selector:
                raise ValueError('hover needs a selector.')
            result = await onyx.call('hover', onyx_path, tabId=tab, **onyx.target(selector))
            extra['hovering'] = result.get('describe') or selector
        elif action == 'fill':
            if not selector:
                raise ValueError('fill needs a selector.')
            field = onyx.target(selector)
            if 'text' in field:  # Onyx's type tool names the field label `into`
                field['into'] = field.pop('text')
            result = await onyx.call('type', onyx_path, tabId=tab, text=text or '', clear=True, **field)
            extra['filled'] = result.get('into') or selector
            if 'mathShows' in result:
                # A math answer box: what it displays now, to check against the answer.
                extra['math_box_shows'] = result['mathShows']
        elif action == 'drag':
            if not selector or not to:
                raise ValueError('drag needs a selector (from) and to (both: a ref, text=Label, a CSS selector, '
                                  'or x=<px>,y=<py> -- see the "graph" note from inspect for the pixel math).')
            drag_args = {'from': onyx.target(selector), 'to': onyx.target(to)}
            result = await onyx.call('drag', onyx_path, tabId=tab, **drag_args)
            extra['dragged'] = {'from': result.get('from'), 'to': result.get('to')}
        elif action == 'press':
            if selector:
                await onyx.call('click', onyx_path, tabId=tab, **onyx.target(selector))
            await onyx.call('press', onyx_path, tabId=tab, key=keys or 'Enter')
        elif action == 'scroll':
            await onyx.call('scroll', onyx_path, tabId=tab, dy=max(-6000, min(6000, int(pixels or 600))))
        elif action == 'screenshot':
            shot = await onyx.call('page_screenshot', onyx_path, tabId=tab)
            state = await _onyx_state(onyx_path, tab, include_text=True)
            return {'url': state['url'], 'title': state['title'], 'captured': True,
                    'browser': 'onyx', '_image': shot.get('_image', '')}

        state = await _onyx_state(onyx_path, tab, include_text=action == 'text')
        state.update(extra)
        return state


async def perform(action, url=None, selector=None, text=None, keys=None, pixels=600, toggle=False, to=None, channel=None, browser=None):
    chosen_channel = channel or browser
    if normalize_browser(chosen_channel) == 'onyx':
        chosen_channel = None
    backend, onyx_path = await _backend()
    mode = await visibility()
    if backend == 'onyx' and not chosen_channel:
        from . import onyx
        onyx.set_visibility(mode)
        try:
            result = await _perform_onyx(action, url, selector, text, keys, pixels, onyx_path, toggle, to=to)
            if isinstance(result, dict):
                result.setdefault('browser', 'onyx')
                result.setdefault('visibility', mode)
            return result
        except (onyx.OnyxUnavailable, onyx.OnyxError) as exc:
            if not isinstance(exc, onyx.OnyxUnavailable) and 'paused' not in str(exc).lower():
                raise
            result = await _perform_edge(action, url, selector, text, keys, pixels, toggle, to=to, channel=chosen_channel or 'msedge')
            result['browser'] = _current_channel or 'edge'
            result['visibility'] = 'hidden' if _current_headless else 'visible'
            result['note'] = f"Onyx was left alone ({exc}), so this ran in Nova's {(_current_channel or 'edge').capitalize()} window."
            return result
    result = await _perform_edge(action, url, selector, text, keys, pixels, toggle, to=to, channel=chosen_channel)
    if isinstance(result, dict):
        result['browser'] = _current_channel
        result['visibility'] = 'hidden' if _current_headless else 'visible'
        if _launch_note:
            result['note'] = _launch_note
    return result


def _playwright_bundle(prefix: str) -> bool:
    """Whether `playwright install` has put that engine's build on this machine."""
    root = os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
    if not root or root == '0':
        if os.name == 'nt':
            root = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ms-playwright')
        elif sys.platform == 'darwin':
            root = os.path.expanduser('~/Library/Caches/ms-playwright')
        else:
            root = os.path.expanduser('~/.cache/ms-playwright')
    try:
        return any(entry.startswith(prefix + '-') for entry in os.listdir(root))
    except OSError:
        return False


async def browser_support() -> dict:
    """What Nova can drive on this machine, and the current choice.

    `available` is detection, not a live test: an installed browser can still
    fail to start (a profile locked by the user's own open window, a policy).
    When that happens Nova falls back and says so in the result."""
    try:
        from . import db
        settings = await db.get_app_settings()
    except Exception:  # noqa: BLE001
        settings = {}
    from . import onyx
    rows = []
    for key, info in BROWSERS.items():
        if key == 'onyx':
            path = onyx.find_exe(settings.get('onyx_path', ''))
            available = path is not None
        elif key in ('firefox', 'webkit', 'chromium'):
            path = None
            available = _playwright_bundle(key)
        else:
            path = _find_browser_exe(key)
            available = path is not None
        rows.append({'id': key, 'name': info['name'], 'engine': info['engine'], 'how': info['how'],
                     'available': available, 'path': str(path) if path else None,
                     'visibility': ['visible', 'hidden']})
    return {
        'backend': settings.get('browser_backend', 'onyx') or 'onyx',
        'preferred_browser': normalize_browser(settings.get('preferred_browser')) or 'chrome',
        'visibility': await visibility(),
        'current': {'browser': _current_channel, 'visibility': None if _current_headless is None
                    else ('hidden' if _current_headless else 'visible')} if _alive(_browser) else None,
        'browsers': rows,
        'notes': ["Nova signs in once per browser: each has its own Nova profile, separate from your everyday one.",
                  "Onyx 'visible' drives your open Onyx window (taking over the mouse pauses Nova); "
                  "'hidden' drives Nova's own hidden Onyx window."],
    }


# On/off controls change things. Found live: on Canvas the "mark as done"
# checkbox beside an assignment carries the assignment's own name, so a
# click meant to open the assignment landed on it. Onyx enforces this rule
# itself; this is the same rule for the Edge fallback.
# Radio buttons are options in a quiz, so allow them freely.
TOGGLE_JS = ("e => e.matches('input[type=checkbox],[role=checkbox],[role=switch],[role=menuitemcheckbox]')"
             " || (e instanceof HTMLLabelElement && !!e.control && e.control.matches('input[type=checkbox]'))")


def toggle_refusal(label: str) -> str:
    return (f"Not clicked: {label} is a checkbox or switch -- clicking it would change it, like marking an "
            "assignment done. To open the item, click its link instead (inspect and pick the role-link entry). "
            "Only if the user asked to change it, click again with toggle=true.")


async def _perform_edge(action, url=None, selector=None, text=None, keys=None, pixels=600, toggle=False, to=None, channel=None):
    async with _lock:
        tab = await page(channel=channel) if channel else await page()
        if action == 'navigate':
            await tab.goto(_check_url(url), wait_until='domcontentloaded', timeout=30000)
        elif action == 'new_tab':
            global _page
            _page = await _browser.new_page()
            _page.set_default_timeout(15000)
            tab = _page
            if url:
                await tab.goto(_check_url(url), wait_until='domcontentloaded', timeout=30000)
        elif action == 'back':
            await tab.go_back(wait_until='domcontentloaded')

        if action in ('click', 'fill', 'drag', 'press'):
            tab_meta = f"{tab.url} {await tab.title()}".lower()
            for kw in PROCTOR_KEYWORDS:
                if kw in tab_meta:
                    raise PermissionError(
                        f"Proctored test environment detected ({kw.capitalize()}). "
                        "Automated browser actions are paused to protect your academic standing."
                    )

        if action == 'click':
            if not selector:
                raise ValueError('click needs a selector. Run inspect first and use a label you actually saw.')
            from . import onyx, browser_cursor
            point_target = onyx.target(selector)
            if "x" in point_target and "y" in point_target:
                await browser_cursor.click_at(tab, point_target["x"], point_target["y"])
            else:
                target = tab.locator(selector).first
                if not toggle and await target.evaluate(TOGGLE_JS):
                    raise ValueError(toggle_refusal(selector))
                await browser_cursor.click_element(tab, target)
            await tab.wait_for_timeout(400)
        elif action == 'hover':
            if not selector:
                raise ValueError('hover needs a selector.')
            from . import onyx, browser_cursor
            point_target = onyx.target(selector)
            if "x" in point_target and "y" in point_target:
                await browser_cursor.glide_to(tab, point_target["x"], point_target["y"])
            else:
                target = tab.locator(selector).first
                box = await target.bounding_box()
                if box:
                    await browser_cursor.glide_to(tab, box["x"] + box["width"] / 2.0, box["y"] + box["height"] / 2.0)
                else:
                    await target.hover()
            await tab.wait_for_timeout(300)
        elif action == 'fill':
            if not selector:
                raise ValueError('fill needs a selector.')
            from . import browser_cursor
            target = tab.locator(selector).first
            await browser_cursor.click_element(tab, target)
            await target.fill(text or '')
        elif action == 'drag':
            if not selector or not to:
                raise ValueError('drag needs a selector (from) and to.')
            from . import onyx, browser_cursor
            from_pt = onyx.target(selector)
            to_pt = onyx.target(to)

            if "x" in from_pt and "y" in from_pt:
                fx, fy = from_pt["x"], from_pt["y"]
            else:
                fbox = await tab.locator(selector).first.bounding_box()
                if not fbox:
                    raise ValueError(f"Could not locate bounding box for drag start: {selector}")
                fx, fy = fbox["x"] + fbox["width"] / 2.0, fbox["y"] + fbox["height"] / 2.0

            if "x" in to_pt and "y" in to_pt:
                tx, ty = to_pt["x"], to_pt["y"]
            else:
                tbox = await tab.locator(to).first.bounding_box()
                if not tbox:
                    raise ValueError(f"Could not locate bounding box for drag target: {to}")
                tx, ty = tbox["x"] + tbox["width"] / 2.0, tbox["y"] + tbox["height"] / 2.0

            await browser_cursor.drag_and_drop(tab, fx, fy, tx, ty)
            await tab.wait_for_timeout(400)
        elif action == 'press':
            target = tab.locator(selector).first if selector else tab
            await target.press(keys or 'Enter')
            await tab.wait_for_timeout(400)
        elif action == 'scroll':
            await tab.mouse.wheel(0, max(-6000, min(6000, int(pixels or 600))))
        elif action == 'screenshot':
            shot = await tab.screenshot(type='png')
            return {'url': tab.url, 'title': await tab.title(), 'captured': True,
                    '_image': base64.b64encode(shot).decode()}
        elif action not in ('navigate', 'new_tab', 'back', 'inspect', 'text'):
            raise ValueError(f'Unknown browser action. Use one of: {", ".join(ACTIONS)}.')
        return await _snapshot(tab, include_text=action == 'text')


async def stop():
    global _driver, _browser, _page
    async with _lock:
        if _browser:
            await _browser.close()
        if _driver:
            await _driver.stop()
        _driver = _browser = _page = None
