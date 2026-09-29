"""Scoped desktop interaction on Windows, macOS and Linux: win32 on Windows,
desktop_os (Quartz / Xlib) on the other two; mss for screenshots, pyautogui
for the real mouse and keyboard.

Two trust tiers, matching the app's actual policy:
  - read-only (capture_screenshot, list_windows, get_active_window):
    real, live data, safe to execute immediately with no confirmation.
  - mutating (click, type_text, press_keys, scroll, open_app): this module
    *executes* these for real -- it does not itself enforce approval. That is
    the agent loop's job, driven by the autonomy setting (see
    nova_tools.autonomy_level / desktop_registry.py). This module is the
    mechanism, not the policy.

type_text/press_keys will type whatever they are given into whatever has
focus, including credential and payment fields. The window-title heuristic
that used to refuse those was removed at the owner's request. The thing worth
knowing is that it was never the real protection anyway: for Nova to type a
secret, that secret has to be in the model's prompt, which means it reaches
whichever provider answered that turn and is persisted in the chat transcript
and the memory index. A value Nova should type but never see belongs in a
credential store read at type time, not in a message.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
import time

import psutil

# Screen and window control is the one genuinely platform-bound part of Nova.
# Everything else here -- chat, school, memory, the tool loop, the phone
# bridge -- is portable, and on Linux it should all still run. So these
# imports are allowed to fail and are reported honestly at the point of use,
# rather than taken at import time where a missing win32gui takes the whole
# backend down before it can serve a single request.
#
# Three separate reasons an import can fail, kept separate because they need
# different answers: win32* is Windows-only and never coming to Linux;
# pyautogui and mss are cross-platform but need a display, so they fail on a
# headless box or a Wayland session without XWayland.
logger = logging.getLogger(__name__)

# How Nova's pointer behaves when it clicks. Read from app settings per click
# rather than held in a global, so a change takes effect on the next action
# instead of the next restart -- and so the choice survives one.
CLICK_SPEED_KEY = "desktop_click_seconds"
CLICK_MARKER_KEY = "desktop_click_marker"
# "own": Nova's own drawn pointer, clicks through UI Automation or a window
# message, never the real mouse (see nova_pointer.py). "real": the old way --
# Nova moves the user's mouse.
POINTER_KEY = "desktop_pointer"
# What Nova may do when an app ignores everything but the real mouse: "ask"
# (say so, and retry only with borrow_mouse=true after the user agrees) or
# "never". There is deliberately no "just do it" setting.
BORROW_KEY = "desktop_borrow_mouse"

DEFAULT_CLICK_SECONDS = 0.45


async def click_style() -> dict:
    """The current visible-click settings, with sane values enforced.

    Zero is allowed and means "go back to teleporting" -- worth keeping for
    anyone who finds the movement slow once the novelty wears off, and for
    scripted runs nobody is watching.
    """
    from . import db

    settings = await db.get_app_settings()
    try:
        seconds = float(settings.get(CLICK_SPEED_KEY, DEFAULT_CLICK_SECONDS))
    except (TypeError, ValueError):
        seconds = DEFAULT_CLICK_SECONDS
    pointer = settings.get(POINTER_KEY, "own")
    borrow = settings.get(BORROW_KEY, "ask")
    autonomy = settings.get("autonomy_level", "guarded")
    if autonomy == "full" or borrow in ("always", "auto"):
        borrow = "always"
    return {
        "seconds": max(0.0, min(seconds, 2.5)),
        "marker": settings.get(CLICK_MARKER_KEY, "1") != "0",
        "pointer": pointer if pointer in ("own", "real") else "own",
        "borrow": borrow if borrow in ("ask", "never", "always") else "ask",
    }


_UNAVAILABLE: dict[str, str] = {}

try:
    import mss
    import mss.tools
except Exception as exc:  # noqa: BLE001 -- any import failure means no screen
    mss = None
    _UNAVAILABLE["screen"] = f"screen capture is unavailable here ({exc})"

try:
    import pyautogui

    # pyautogui's fail-safe (abort if the cursor gets thrown into a screen
    # corner) is a real human-in-the-loop kill switch -- keep it on. Its
    # default inter-action pause is disabled: every gated call here is already
    # individually approved, no need to also throttle it.
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0
except Exception as exc:  # noqa: BLE001
    pyautogui = None
    _UNAVAILABLE["input"] = f"keyboard and mouse control is unavailable here ({exc})"

if sys.platform == "win32":
    try:
        import win32gui
        import win32process
    except Exception as exc:  # noqa: BLE001
        win32gui = win32process = None
        _UNAVAILABLE["windows"] = f"the Windows APIs did not load ({exc})"
else:
    # macOS and Linux: desktop_os answers the same questions (see its docstring).
    win32gui = win32process = None

_WIN = sys.platform == "win32"


def _os():
    from . import desktop_os
    return desktop_os


def _title(hwnd: int) -> str:
    if _WIN:
        return win32gui.GetWindowText(hwnd)
    return (_os().window(hwnd) or {}).get("title") or ""


def _foreground() -> int:
    if _WIN:
        return win32gui.GetForegroundWindow()
    w = _os().active_window()
    return w["hwnd"] if w else 0


def _cursor() -> tuple[int, int]:
    if _WIN:
        import win32api
        return win32api.GetCursorPos()
    return _os().cursor_pos()


def _set_cursor(pos: tuple[int, int]) -> None:
    if _WIN:
        import win32api
        win32api.SetCursorPos(pos)
    else:
        _os().set_cursor(*pos)


def unavailable() -> dict[str, str]:
    """What this machine cannot do, and why. Used by self-check and by the
    Linux build's startup banner so the limitation is stated once, up front,
    instead of discovered as a stack trace mid-conversation."""
    return dict(_UNAVAILABLE)


def _require(*features: str) -> None:
    """Fail with the honest reason rather than an AttributeError on None."""
    for feature in features:
        reason = _UNAVAILABLE.get(feature)
        if reason:
            raise DesktopActionError(reason[0].upper() + reason[1:] + ".")


class DesktopActionError(Exception):
    """Real failure executing a desktop action. Message is safe to show
    directly to the user/model -- never includes captured screen content or
    typed text."""


async def capture_screenshot() -> bytes:
    """Full virtual-screen (all monitors) screenshot, PNG bytes. Read-only."""
    _require("screen")

    def _capture() -> bytes:
        from PIL import Image  # deferred: heavy import, only needed here

        with mss.mss() as sct:
            monitor = sct.monitors[0]  # index 0 = union of all monitors
            shot = sct.grab(monitor)
            # mss.tools.to_png only accepts a filesystem path for `output`
            # in the version pinned here, not a file-like object -- PIL
            # encodes straight to an in-memory buffer instead.
            image = Image.frombytes("RGB", shot.size, shot.rgb)
            if sys.platform == "darwin" and (monitor["width"], monitor["height"]) != image.size:
                # Retina: pixels are 2x the points macOS clicks in. Handing the
                # model an image in points keeps screenshot and click
                # coordinates the same, as they are on Windows and Linux.
                image = image.resize((monitor["width"], monitor["height"]))
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return buf.getvalue()

    try:
        return await asyncio.to_thread(_capture)
    except Exception as exc:  # noqa: BLE001
        raise DesktopActionError(f"Screenshot failed: {exc}") from exc


def screen_origin() -> tuple[int, int]:
    """Screen coordinate of the top-left pixel of `capture_screenshot`'s image.

    On a single-monitor machine this is (0, 0) and everything below is a no-op.
    It stops being (0, 0) as soon as a monitor sits above or to the left of the
    primary one: the virtual desktop then starts at a negative coordinate --
    (-1920, -1080) on the three-monitor machine this was found on -- while the
    screenshot's own pixels still start at (0, 0).
    """
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[0]
            return int(monitor["left"]), int(monitor["top"])
    except Exception:  # noqa: BLE001
        # Never let a geometry lookup break a click; the common case is (0, 0)
        # and being wrong here is no worse than the untranslated behaviour.
        return 0, 0


def to_screen(x: int, y: int) -> tuple[int, int]:
    """Translate a coordinate read off a screenshot into a real screen one.

    Every coordinate that reaches click/scroll comes from an image: either a
    model reading `capture_screenshot`, or the vision model behind
    desktop_click_on, which is given that same image. So the translation
    belongs here, once, rather than in each caller -- doing it per caller is
    how it came to be missing from all of them.

    Only the offset is corrected. If a display ran at a different DPI scale the
    image would also be scaled relative to pyautogui's logical coordinates,
    which this does not attempt to undo.
    """
    left, top = screen_origin()
    return x + left, y + top


async def list_windows() -> list[dict]:
    """Every visible, titled top-level window with its owning process name.
    Read-only."""
    _require("windows")

    try:
        return await asyncio.to_thread(_enum_windows)
    except Exception as exc:  # noqa: BLE001
        raise DesktopActionError(f"Listing windows failed: {exc}") from exc


def _enum_windows() -> list[dict]:
    """Synchronous window enumeration across Windows, macOS, and Linux."""
    results: list[dict] = []

    if sys.platform == "win32":
        if not win32gui:
            return results
        foreground = win32gui.GetForegroundWindow()

        def callback(hwnd, _extra):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title.strip():
                return
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc_name = psutil.Process(pid).name()
            except Exception:  # noqa: BLE001
                proc_name = None
            results.append({
                "hwnd": hwnd, "title": title, "process": proc_name,
                "active": hwnd == foreground,
                "maybe_unsaved": title.startswith("*") or title.startswith("●") or " - Notepad" in title and title.startswith("*"),
            })

        win32gui.EnumWindows(callback, None)
        return results

    return _os().list_windows()


async def get_active_window() -> dict | None:
    windows = await list_windows()
    return next((w for w in windows if w["active"]), None)


BORROW_ASK_MESSAGE = (
    "Nova's own pointer could not click this: the app did not respond to UI Automation or to a "
    "click message, which usually means it only listens to the real mouse. Ask the user whether "
    "you may borrow their mouse for a split second -- it jumps there, clicks, and goes straight "
    "back. Only if they say yes, call desktop_click again with borrow_mouse=true."
)


async def click(x: int, y: int, button: str = "left", double: bool = False,
                borrow_mouse: bool = False, allow_focus_change: bool = False) -> dict:
    """Click at a point read off `capture_screenshot` (see `to_screen`).

    With the default "own" pointer, Nova's drawn pointer glides there and the
    click is delivered without touching the real mouse, trying in order:
    UI Automation on the control at that point, then a click message posted
    to the window under it (checked by comparing the window before and after).
    Only if both fail, and only with the user's explicit OK (borrow_mouse),
    does it borrow the real mouse -- and puts it straight back.

    Gated -- see module docstring; trusts the caller already secured explicit
    per-action approval."""
    _require("screen")
    if button not in ("left", "right", "middle"):
        raise DesktopActionError(f"Unknown click button '{button}'.")
    sx, sy = to_screen(x, y)
    style = await click_style()
    if style["pointer"] == "own":
        return await _own_click(x, y, sx, sy, button, double, borrow_mouse, style, allow_focus_change)
    _require("input")

    def _click():
        # Visibly, by default. A teleported pointer is unwatchable and also
        # generates none of the enter/hover events that menus, arming buttons
        # and drag handles are built around -- see cursor.py. Falls back to
        # the old instant click if anything in the visible path fails, since
        # the click is the point and the animation is not.
        if style["seconds"] <= 0:
            pyautogui.click(x=sx, y=sy, button=button)
            return
        try:
            from . import cursor
            cursor.visible_click(pyautogui, sx, sy, button,
                                 duration=style["seconds"], show_marker=style["marker"])
        except pyautogui.FailSafeException:
            # Not a failure to route around. Throwing the pointer into a screen
            # corner is the one gesture that stops Nova mid-action, and it can
            # only fire now that the pointer travels far enough to be caught.
            # The fallback below would move to the target first, so the corner
            # would no longer be a corner and the click would land -- the abort
            # would be swallowed by the code meant to make clicking reliable.
            raise
        except Exception:  # noqa: BLE001
            logger.debug("Visible click failed; clicking directly", exc_info=True)
            pyautogui.click(x=sx, y=sy, button=button)

    try:
        await asyncio.to_thread(_click)
    except pyautogui.FailSafeException as exc:
        # Said as what it is, so the model reports "you stopped me" rather than
        # a malfunction it should retry around.
        raise DesktopActionError(
            "Stopped: the mouse was thrown into a screen corner, which is the "
            "abort gesture. Nothing was clicked."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise DesktopActionError(f"Click failed: {exc}") from exc
    # Both are reported: the model asked in image coordinates and should be
    # able to see what that actually became on screen.
    return {"x": x, "y": y, "screen_x": sx, "screen_y": sy, "button": button}


def _focus_report() -> dict:
    """Which window is about to receive keystrokes.

    Queries the foreground window directly rather than searching the filtered
    list from _enum_windows. That filter drops untitled and invisible windows,
    so a focused window it happens to exclude came back as "no window has
    focus" -- which silently turned expect_window into a refuse-everything
    gate. Asking the OS straight out avoids inventing that failure.

    Retries briefly because focus is genuinely absent for a moment while an app
    is starting or a window is closing, and a momentary gap should not read as
    "nothing is focused".
    """
    if not _WIN:
        for attempt in range(6):
            w = _os().active_window()
            if w:
                return {"into_window": w["title"] or None, "into_process": w["process"],
                        "into_unsaved_document": w["maybe_unsaved"]}
            time.sleep(0.15)
        return {"into_window": None, "into_process": None, "into_unsaved_document": False}
    for attempt in range(6):
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            title = win32gui.GetWindowText(hwnd) or ""
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc_name = psutil.Process(pid).name()
            except Exception:  # noqa: BLE001
                proc_name = None
            if title.strip() or proc_name:
                return {
                    "into_window": title or None,
                    "into_process": proc_name,
                    "into_unsaved_document": title.startswith(("*", "●")),
                }
        if attempt < 5:
            time.sleep(0.15)
    return {"into_window": None, "into_process": None, "into_unsaved_document": False}


async def type_text(text: str, expect_window: str | None = None) -> dict:
    """Types into whatever currently has keyboard focus.

    Always reports the window it typed into. That is the whole safety story for
    this tool: it cannot choose a target, so the only protection against typing
    into the wrong place is that the result says where the text went, loudly
    enough that the next step can notice and undo it.

    `expect_window` turns that from a report into a check -- a caller that knows
    what it is aiming at passes a substring of the expected title and the call
    is refused if focus is somewhere else. Cheap, and the difference between a
    typo and overwriting an open document.
    """
    refuse_if_fullscreen_focused(expect_window, "type")
    target = await asyncio.to_thread(_focus_report)
    if expect_window:
        title = target.get("into_window") or ""
        if expect_window.lower() not in title.lower():
            raise DesktopActionError(
                f"Refusing to type: expected a window matching {expect_window!r} but "
                f"{title or 'no window'} has focus. Focus the right window first, or call "
                f"again without expect_window to type here deliberately."
            )

    def _type():
        from .operator_workflows import require_running
        def check_abort():
            if pyautogui is not None:
                pyautogui.failSafeCheck()
            require_running()
        if os.name == 'nt':
            from .unicode_input import type_unicode
            type_unicode(text, check_abort, pyautogui.press)
        else:
            _os().type_unicode(text, check_abort)

    try:
        await asyncio.to_thread(_type)
    except Exception as exc:  # noqa: BLE001
        raise DesktopActionError(f"Typing failed: {exc}") from exc
    return {"chars": len(text), **target}


# How long to wait for a launched app to put a window on screen before deciding
# nothing new appeared. Generous: a cold start of a heavy app is slow, and
# guessing "reused" when it was merely slow is the more misleading error.
OPEN_APP_SETTLE_SECONDS = 6.0
OPEN_APP_POLL_SECONDS = 0.25


async def open_app(path: str, background: bool | None = None) -> dict:
    """Launches an application/file via the OS's own "open" association --
    equivalent to double-clicking it in Explorer. Gated.

    Reports whether a *new* window actually appeared, because on Windows many
    apps are single-instance: Notepad, Explorer, Office and most browsers will
    quietly focus an existing window instead of opening a blank one. Nova then
    types into whatever document happened to already be there.

    That is not hypothetical -- it happened during testing: opening Notepad
    focused a window holding the user's own config file, which then received
    keystrokes and a Ctrl+A. Nothing was lost, but only by luck. So this now
    answers "did I get a fresh window, or land in someone's work?" rather than
    returning the path back unchanged, which told the caller nothing.
    """
    before = {w["hwnd"] for w in await asyncio.to_thread(_enum_windows)}
    from . import nova_pointer
    in_front = nova_pointer.fullscreen_app()
    # With a game or fullscreen video in front, open quietly (minimised, not
    # activated) unless told otherwise -- starting an app must not yank
    # the user out of what they are doing.
    quietly = in_front is not None if background is None else background

    target_path = path
    if not os.path.exists(target_path):
        import shutil
        found = shutil.which(target_path)
        if not found and not target_path.lower().endswith(".exe"):
            found = shutil.which(target_path + ".exe")
        if not found and target_path.lower() in ("onyx", "onyx.exe"):
            try:
                from . import onyx
                exe = onyx.find_exe()
                if exe:
                    found = str(exe)
            except Exception:
                pass
        if found:
            target_path = found

    def _open():
        if quietly and os.name == "nt":
            import ctypes
            # SW_SHOWMINNOACTIVE: open minimised, without taking focus.
            result = ctypes.windll.shell32.ShellExecuteW(None, "open", target_path, None, None, 7)
            if result <= 32:
                raise OSError(f"ShellExecute returned {result}")
            return
        if os.name == "nt":
            os.startfile(target_path)
            return
        import shutil
        import subprocess
        is_file = os.path.exists(target_path)
        if sys.platform == "darwin":
            # "-g" opens without bringing it forward, like the minimised open on Windows.
            quiet = ["-g"] if quietly else []
            if is_file or target_path.endswith(".app"):
                subprocess.run(["open", *quiet, target_path], check=True, timeout=15)
            else:  # an app by name: "Calculator", "Safari"
                subprocess.run(["open", *quiet, "-a", target_path], check=True, timeout=15, capture_output=True)
            return
        if is_file:
            subprocess.Popen(["xdg-open", target_path])
        elif shutil.which(target_path):
            subprocess.Popen([shutil.which(target_path)], start_new_session=True)
        elif shutil.which("gtk-launch"):  # an app by its desktop entry: "org.gnome.Calculator"
            subprocess.run(["gtk-launch", target_path], check=True, timeout=15, capture_output=True)
        else:
            raise OSError(f"no app called {target_path!r} was found")

    try:
        await asyncio.to_thread(_open)
    except Exception as exc:  # noqa: BLE001
        raise DesktopActionError(f"Couldn't open '{path}': {exc}") from exc

    deadline = asyncio.get_running_loop().time() + OPEN_APP_SETTLE_SECONDS
    new_windows: list[dict] = []
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(OPEN_APP_POLL_SECONDS)
        current = await asyncio.to_thread(_enum_windows)
        new_windows = [w for w in current if w["hwnd"] not in before]
        if new_windows:
            break

    active = next((w for w in await asyncio.to_thread(_enum_windows) if w["active"]), None)
    result = {
        "path": path,
        "opened_in_background": bool(quietly),
        "opened_new_window": bool(new_windows),
        "focused_window": (active or {}).get("title"),
        "focused_process": (active or {}).get("process"),
    }
    if not new_windows:
        result["reused_existing_window"] = True
        where = (active or {}).get("title")
        result["warning"] = (
            "No new window appeared: this app is single-instance, so it focused a window that "
            "was already open rather than giving you a blank one. It may already contain the "
            "user's work. Do NOT type into it assuming it is empty — read what it holds first "
            "(desktop_read_screen), or make a new document explicitly with ctrl+n."
        )
        # Naming the window is most of the value, so say plainly when it can't
        # be named rather than leaving a confident-sounding but vague warning.
        result["warning"] += (
            f" Focus is on: {where}." if where else
            " The focused window could not be identified — call list_windows before typing."
        )
        if (active or {}).get("maybe_unsaved"):
            result["warning"] += " Its title suggests unsaved changes."
    else:
        # A new window is not the same as a blank one. Launched with no file,
        # an editor that restores its last session (Windows 11 Notepad does)
        # opens straight onto the user's own documents. Found live: a
        # "new" Notepad window came up on a real document and app_type
        # replaced its text.
        opened = new_windows[0].get("title") or ""
        # An app (notepad.exe, "calc"), not a file: opening a file is supposed
        # to show that file.
        launched_bare = os.path.splitext(os.path.basename(path))[1].lower() in (".exe", "")
        blankish = opened.lower().startswith(("untitled", "new ", "document")) or not opened.strip()
        if launched_bare and not blankish:
            result["restored_document"] = opened
            result["warning"] = (
                f"The new window opened on {opened!r} -- the app restored a document from its last "
                "session. That is the user's work, not a blank page. Read it before changing "
                "anything, and make a new document (desktop_key 'ctrl+n') if you need an empty one."
            )
    return result


async def scroll(clicks: int, x: int | None = None, y: int | None = None,
                 borrow_mouse: bool = False) -> dict:
    """Scrolls, optionally at a point. x/y are screenshot coordinates,
    translated the same way clicks are.

    On Nova's own pointer with a point given, the wheel goes to the window
    under that point as a message, and counts only if the window visibly
    moved -- the same ladder as a click, and the same rule about borrowing
    the real mouse."""
    target = to_screen(x, y) if x is not None and y is not None else None
    style = await click_style()
    if target is not None and style["pointer"] == "own":
        return await _own_scroll(clicks, x, y, target, borrow_mouse, style)
    _require("input")

    def _scroll():
        if target is not None:
            pyautogui.moveTo(*target)
        pyautogui.scroll(clicks)
    try:
        await asyncio.to_thread(_scroll)
    except Exception as exc:
        raise DesktopActionError(f"Scroll failed: {exc}") from exc
    return {"clicks": clicks, "x": x, "y": y}


_KEY_ALIASES = {
    "esc": "escape", "return": "enter", "del": "delete", "ins": "insert",
    "pgup": "pageup", "pgdn": "pagedown", "cmd": "win", "meta": "win",
    "control": "ctrl", "option": "alt",
}


async def press_keys(keys: str, expect_window: str | None = None) -> dict:
    """A key or chord: "enter", "ctrl+s", "alt+tab", or a space-separated
    sequence of either.

    Reports and can check its target for the same reason type_text does, and
    with more at stake: `ctrl+a delete` in the wrong window destroys a document
    in two keystrokes, and unlike typing it leaves nothing behind to recognise.
    """
    _require("input")
    sequence = [chunk for chunk in str(keys).strip().split() if chunk]
    if not sequence:
        raise DesktopActionError("No keys given.")

    refuse_if_fullscreen_focused(expect_window, "send keys")
    target = await asyncio.to_thread(_focus_report)
    if expect_window:
        title = target.get("into_window") or ""
        if expect_window.lower() not in title.lower():
            raise DesktopActionError(
                f"Refusing to send keys: expected a window matching {expect_window!r} but "
                f"{title or 'no window'} has focus."
            )

    def _press():
        for chord in sequence:
            parts = [_KEY_ALIASES.get(p.strip().lower(), p.strip().lower())
                     for p in chord.split("+") if p.strip()]
            if len(parts) == 1:
                pyautogui.press(parts[0])
            else:
                pyautogui.hotkey(*parts)

    try:
        await asyncio.to_thread(_press)
    except Exception as exc:  # noqa: BLE001
        raise DesktopActionError(f"Key press failed: {exc}") from exc
    return {"keys": sequence, **target}


# ---------------------------------------------------------------------------
# Nova's own pointer: clicking without the real mouse
#
# The ladder, cheapest and least intrusive first. Each rung either lands the
# click and says how, or hands down to the next; nothing reports success
# without evidence of it.


def _deepest_window(hwnd: int, sx: int, sy: int) -> int:
    """The child window actually under the point -- where a click message has
    to go for a classic Win32 app to see it."""
    import win32con
    current = hwnd
    for _ in range(8):
        cx, cy = win32gui.ScreenToClient(current, (sx, sy))
        child = win32gui.ChildWindowFromPointEx(
            current, (cx, cy), win32con.CWP_SKIPINVISIBLE | win32con.CWP_SKIPTRANSPARENT)
        if not child or child == current:
            return current
        current = child
    return current


def capture_window(hwnd: int):
    """What a window shows, even with something on top of it (PrintWindow
    with PW_RENDERFULLCONTENT asks the window to paint itself, rather than
    copying the screen). A PIL image, or None if it cannot be captured --
    a minimised window has nothing to paint."""
    if not _WIN:
        return _os().capture(hwnd)
    try:
        import ctypes
        import win32ui
        from PIL import Image
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0 or win32gui.IsIconic(hwnd):
            return None
        window_dc = win32gui.GetWindowDC(hwnd)
        source = win32ui.CreateDCFromHandle(window_dc)
        memory = source.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(source, width, height)
        memory.SelectObject(bitmap)
        ok = ctypes.windll.user32.PrintWindow(hwnd, memory.GetSafeHdc(), 2)  # PW_RENDERFULLCONTENT
        info = bitmap.GetInfo()
        image = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]),
                                 bitmap.GetBitmapBits(True), "raw", "BGRX", 0, 1)
        win32gui.DeleteObject(bitmap.GetHandle())
        memory.DeleteDC()
        source.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)
        return image if ok else None
    except Exception:  # noqa: BLE001
        logger.debug("capture_window failed", exc_info=True)
        return None


def images_differ(before, after, threshold: float = 0.001) -> bool:
    """Did anything visibly change? Compared on a downscaled copy so a
    blinking caret alone does not count as the click having worked."""
    if before is None or after is None:
        return False
    if before.size != after.size:
        return True
    from PIL import ImageChops
    small = (max(1, before.width // 4), max(1, before.height // 4))
    diff = ImageChops.difference(before.resize(small), after.resize(small)).convert("L")
    changed = sum(diff.histogram()[25:])
    return changed / (small[0] * small[1]) > threshold


def _post_click(hwnd: int, sx: int, sy: int, button: str, double: bool) -> None:
    if not _WIN:
        _os().send_click(hwnd, sx, sy, button, double)
        return
    import win32api
    import win32con
    target = _deepest_window(hwnd, sx, sy)
    cx, cy = win32gui.ScreenToClient(target, (sx, sy))
    lparam = win32api.MAKELONG(cx & 0xFFFF, cy & 0xFFFF)
    down, up, dbl, flag = {
        "left": (win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP, win32con.WM_LBUTTONDBLCLK, win32con.MK_LBUTTON),
        "right": (win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP, win32con.WM_RBUTTONDBLCLK, win32con.MK_RBUTTON),
        "middle": (win32con.WM_MBUTTONDOWN, win32con.WM_MBUTTONUP, win32con.WM_MBUTTONDBLCLK, win32con.MK_MBUTTON),
    }[button]
    win32gui.PostMessage(target, win32con.WM_MOUSEMOVE, 0, lparam)
    win32gui.PostMessage(target, down, flag, lparam)
    win32gui.PostMessage(target, up, 0, lparam)
    if double:
        win32gui.PostMessage(target, dbl, flag, lparam)
        win32gui.PostMessage(target, up, 0, lparam)


def _top_window_at(sx: int, sy: int) -> int:
    if not _WIN:
        w = _os().window_at(sx, sy)
        return w["hwnd"] if w else 0
    hwnd = win32gui.WindowFromPoint((sx, sy))
    return win32gui.GetAncestor(hwnd, 2) if hwnd else 0  # GA_ROOT


async def _own_click(x: int, y: int, sx: int, sy: int, button: str, double: bool,
                     borrow_mouse: bool, style: dict, allow_focus_change: bool = False) -> dict:
    from . import nova_pointer, uia

    _require("windows")
    covering = nova_pointer.point_under_fullscreen(sx, sy)
    if covering:
        raise DesktopActionError(
            f"{covering['title'] or covering['process'] or 'A fullscreen app'} is fullscreen on that monitor, "
            "so whatever is at that point is it -- Nova does not click into a game or video you are "
            "using. To work in a window underneath, use app_controls and app_click with its title.")

    in_front = nova_pointer.fullscreen_app()
    if in_front:
        guard_focus(await asyncio.to_thread(_top_window_at, sx, sy), in_front, allow_focus_change)

    def _ladder() -> dict:
        result = _ladder_inner()
        note = keep_fullscreen_in_front(in_front)
        if note:
            result["focus"] = note
        return result

    def _ladder_inner() -> dict:
        watch = nova_pointer.Watch()
        nova_pointer.pointer.glide(sx, sy, style["seconds"], watch.check)
        watch.check()
        if style["marker"]:
            from . import cursor
            cursor.flash(sx, sy)
        base = {"x": x, "y": y, "screen_x": sx, "screen_y": sy, "button": button,
                "pointer": "Nova's own -- your mouse was not moved"}

        # Rung 1: UI Automation presses the control itself.
        if button == "left" and not double:
            try:
                hit = uia.act_at_blocking(sx, sy)
            except Exception:  # noqa: BLE001 -- fall to the next rung
                hit = None
            if hit:
                return {**base, "how": f"UI Automation {hit['how']}", "clicked": hit["control"]}

        # Rung 2: a click message to the window under the point, verified by
        # whether the window visibly changed.
        top = _top_window_at(sx, sy)
        if top:
            before = capture_window(top)
            _post_click(top, sx, sy, button, double)
            time.sleep(0.35)
            if images_differ(before, capture_window(top)):
                return {**base, "how": "click message to the window (it changed)",
                        "window": _title(top)}

        # Rung 3: the real mouse, only with the user's say-so.
        if style["borrow"] == "never":
            raise DesktopActionError(
                "Nova's own pointer could not click this, and borrowing your mouse is switched off "
                "in Settings > Autonomy. Nothing was clicked.")
        if not borrow_mouse and style["borrow"] != "always":
            raise DesktopActionError(BORROW_ASK_MESSAGE + " Nothing was clicked.")
        _require("input")
        home = _cursor()
        try:
            pyautogui.click(x=sx, y=sy, button=button, clicks=2 if double else 1)
        finally:
            _set_cursor(home)
        return {**base, "how": "borrowed your mouse for a moment, then put it back",
                "pointer": "your mouse, borrowed with permission and returned"}

    try:
        return await asyncio.to_thread(_ladder)
    except nova_pointer.Stopped as exc:
        raise DesktopActionError(str(exc)) from exc
    except DesktopActionError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DesktopActionError(f"Click failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Windows by title, and apps by their controls -- works when covered

def find_window(title_contains: str) -> int:
    """The visible top-level window whose title contains the text, preferring
    an exact match, then the shortest title (so "Calculator" does not pick
    "Calculator - Documentation")."""
    _require("windows")
    needle = title_contains.strip().lower()
    if not needle:
        raise DesktopActionError("Name the window by part of its title.")
    matches = [w for w in _enum_windows() if needle in w["title"].lower()]
    if not matches:
        raise DesktopActionError(f"No visible window whose title contains {title_contains!r}.")
    matches.sort(key=lambda w: (w["title"].lower() != needle, len(w["title"])))
    return matches[0]["hwnd"]


async def window_screenshot(title_contains: str) -> bytes:
    """A PNG of one window as it paints itself -- including when it is behind
    a game or another window."""
    hwnd = find_window(title_contains)
    image = await asyncio.to_thread(capture_window, hwnd)
    if image is None:
        raise DesktopActionError("That window could not be captured (it may be minimised). "
                                 "app_controls can still read it.")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


async def app_controls(title_contains: str) -> dict:
    from . import uia
    hwnd = find_window(title_contains)
    try:
        entries = await uia.controls(hwnd)
    except uia.UiaError as exc:
        raise DesktopActionError(str(exc)) from exc
    return {"window": _title(hwnd), "controls": uia.describe(entries),
            "how_to_use": "app_click / app_type with the number in brackets, or the control's name."}


def _control_ref(control: str) -> tuple[int | None, str | None]:
    text = str(control or "").strip().strip("[]")
    return (int(text), None) if text.isdigit() else (None, text or None)


async def app_click(title_contains: str, control: str, action: str = "press",
                    allow_focus_change: bool = False) -> dict:
    """Press (or toggle / select / expand) a control in a window by its ref or
    name, through UI Automation. Nova's pointer glides to it when it is on a
    visible part of the screen; the action itself never uses the mouse, so it
    works on a covered window too."""
    from . import nova_pointer, uia
    hwnd = find_window(title_contains)
    ref, name = _control_ref(control)
    style = await click_style()
    in_front = nova_pointer.fullscreen_app()
    guard_focus(hwnd, in_front, allow_focus_change)
    try:
        result = await uia.act(hwnd, ref=ref, name=name, action=action)
    except uia.UiaError as exc:
        raise DesktopActionError(str(exc)) from exc
    note = await asyncio.to_thread(keep_fullscreen_in_front, in_front)
    if note:
        result["focus"] = note
    left, top, right, bottom = result.pop("rect", [0, 0, 0, 0])
    if right > left and bottom > top:
        cx, cy = (left + right) // 2, (top + bottom) // 2
        await asyncio.to_thread(nova_pointer.pointer.glide, cx, cy, min(style["seconds"], 0.45))
    return {"window": _title(hwnd), **result,
            "pointer": "Nova's own -- your mouse was not moved"}


async def app_type(title_contains: str, control: str, text: str,
                   allow_focus_change: bool = False, replace: bool = False) -> dict:
    """Put text into a field by its ref or name, through UI Automation's value
    interface -- no keyboard focus needed, so it cannot land in whatever
    the user is typing into."""
    from . import nova_pointer, uia
    hwnd = find_window(title_contains)
    ref, name = _control_ref(control)
    in_front = nova_pointer.fullscreen_app()
    guard_focus(hwnd, in_front, allow_focus_change)
    try:
        result = await uia.act(hwnd, ref=ref, name=name, action="type", text=text, replace=replace)
    except uia.UiaError as exc:
        raise DesktopActionError(str(exc)) from exc
    note = await asyncio.to_thread(keep_fullscreen_in_front, in_front)
    if note:
        result["focus"] = note
    result.pop("rect", None)
    return {"window": _title(hwnd), **result, "chars": len(text)}


def refuse_if_fullscreen_focused(expect_window: str | None, verb: str) -> None:
    """Keystrokes go to whatever has focus. With a fullscreen app in front
    that is the user's game or video, and Nova typing into it is never what
    was meant -- unless the call named that window on purpose."""
    from . import nova_pointer
    app_in_front = nova_pointer.fullscreen_app()
    if not app_in_front:
        return
    title = app_in_front.get("title") or ""
    if expect_window and expect_window.lower() in title.lower():
        return
    raise DesktopActionError(
        f"Refusing to {verb}: {title or app_in_front.get('process') or 'a fullscreen app'} is fullscreen "
        "and has the keyboard, so the keys would go into it. Use app_type to fill a field in "
        "another window without touching focus.")


async def _own_scroll(clicks: int, x: int, y: int, target: tuple[int, int],
                      borrow_mouse: bool, style: dict) -> dict:
    from . import nova_pointer
    _require("windows")
    sx, sy = target
    covering = nova_pointer.point_under_fullscreen(sx, sy)
    if covering:
        raise DesktopActionError(
            f"{covering['title'] or 'A fullscreen app'} is fullscreen there; Nova does not scroll it.")

    def _do() -> dict:
        watch = nova_pointer.Watch()
        nova_pointer.pointer.glide(sx, sy, style["seconds"], watch.check)
        watch.check()
        base = {"clicks": clicks, "x": x, "y": y, "pointer": "Nova's own -- your mouse was not moved"}
        top = _top_window_at(sx, sy)
        if top:
            before = capture_window(top)
            if _WIN:
                import win32api
                import win32con
                inner = _deepest_window(top, sx, sy)
                wparam = (int(clicks) * 120 & 0xFFFF) << 16
                win32gui.PostMessage(inner, win32con.WM_MOUSEWHEEL, wparam, win32api.MAKELONG(sx & 0xFFFF, sy & 0xFFFF))
            else:
                _os().send_scroll(top, sx, sy, clicks)
            time.sleep(0.35)
            if images_differ(before, capture_window(top)):
                return {**base, "how": "wheel message to the window (it moved)"}
        if style["borrow"] == "never":
            raise DesktopActionError("That window did not scroll for Nova's own pointer, and borrowing "
                                     "your mouse is switched off. Nothing was scrolled.")
        if not borrow_mouse and style["borrow"] != "always":
            raise DesktopActionError(BORROW_ASK_MESSAGE.replace("desktop_click", "desktop_scroll")
                                     + " Nothing was scrolled.")
        _require("input")
        home = _cursor()
        try:
            pyautogui.moveTo(sx, sy)
            pyautogui.scroll(clicks)
        finally:
            _set_cursor(home)
        return {**base, "how": "borrowed your mouse for a moment, then put it back"}

    try:
        return await asyncio.to_thread(_do)
    except nova_pointer.Stopped as exc:
        raise DesktopActionError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Not pulling the user out of a game
#
# Pressing a button through UI Automation is not supposed to move focus, but
# some apps activate themselves when they are invoked -- UWP apps like
# Calculator do it every time. Found live: Nova pressed "Nine" in a covered
# Calculator and pulled a fullscreen window out from under the user.
#
# It cannot be undone from here: Windows' foreground lock refuses a
# background process that tries to take the foreground back (tested:
# AttachThreadInput, SwitchToThisWindow, minimising the thief -- all refused,
# and rightly, since that lock is what stops any app yanking focus). So the
# answer is prevention: while a fullscreen app is in front, Nova asks before
# acting in an app known to jump forward -- every UWP app, plus any app it has
# watched do it -- and learns a new one the first time it happens.

UWP_FRAME = "ApplicationFrameWindow"
FOCUS_ASK = (
    "{app} jumps to the front when its controls are pressed, and {game} is fullscreen in front "
    "right now -- doing it would pull the user out of it. Ask them first; only if they say yes, "
    "call again with allow_focus_change=true. Nothing was done."
)


def _process_of(hwnd: int) -> str:
    if not _WIN:
        return ((_os().window(hwnd) or {}).get("process") or "").lower()
    try:
        return psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1]).name().lower()
    except Exception:  # noqa: BLE001
        return ""


def _learned_activators() -> set[str]:
    from . import operator_store
    return set((operator_store.get("control", "self_activating_apps") or {}).get("processes", []))


def _learn_activator(process: str) -> None:
    from . import operator_store
    known = _learned_activators()
    if process and process not in known:
        operator_store.put("control", "self_activating_apps", {"processes": sorted(known | {process})})


def jumps_forward(hwnd: int) -> bool:
    """Will pressing a control in this window bring it to the front?"""
    if _WIN:
        try:
            if win32gui.GetClassName(hwnd) == UWP_FRAME:
                return True
        except Exception:  # noqa: BLE001
            pass
    return _process_of(hwnd) in _learned_activators()


def guard_focus(hwnd: int, in_front: dict | None, allow_focus_change: bool) -> None:
    """Refuse, before acting, to do something that would pull the user out of a
    fullscreen app -- unless they have said it is fine."""
    if not in_front or allow_focus_change or hwnd == in_front["hwnd"]:
        return
    if jumps_forward(hwnd):
        raise DesktopActionError(FOCUS_ASK.format(
            app=_title(hwnd) or "That app",
            game=in_front.get("title") or in_front.get("process") or "a fullscreen app"))


def _force_foreground(hwnd: int) -> bool:
    """SetForegroundWindow from a background process, via the documented
    route: briefly join the current foreground thread's input queue."""
    if not _WIN:
        try:
            return _os().activate(hwnd) and _foreground() == hwnd
        except Exception:  # noqa: BLE001
            return False
    import ctypes
    import win32api
    try:
        current = win32gui.GetForegroundWindow()
        if current == hwnd:
            return True
        mine = win32api.GetCurrentThreadId()
        theirs = win32process.GetWindowThreadProcessId(current)[0] if current else 0
        attached = bool(theirs and theirs != mine and ctypes.windll.user32.AttachThreadInput(mine, theirs, True))
        try:
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if attached:
                ctypes.windll.user32.AttachThreadInput(mine, theirs, False)
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:  # noqa: BLE001
        return False


def keep_fullscreen_in_front(before: dict | None) -> str | None:
    """Call after an action. If `before` (a fullscreen_app() snapshot) lost the
    foreground, give it back. Returns a note for the result, or None."""
    if not before:
        return None
    try:
        now = _foreground()
    except Exception:  # noqa: BLE001
        return None
    if now == before["hwnd"]:
        return None
    thief = _title(now) or "another window"
    # Remember it, so next time Nova asks first instead of finding out after.
    _learn_activator(_process_of(now))
    if _force_foreground(before["hwnd"]):
        return (f"{thief} grabbed focus when its control was pressed; Nova handed focus straight "
                f"back to {before.get('title') or 'the fullscreen app'}.")
    return (f"{thief} took focus when its control was pressed, and the system would not let Nova hand it "
            f"back to {before.get('title') or 'the fullscreen app'}. Tell the user. Nova will ask before "
            f"doing that in {thief} again while something is fullscreen.")
