"""Windows, the pointer and the keyboard on macOS and Linux.

desktop.py's Windows side talks to win32 directly. This is the same set of
operations for the other two systems, so everything above it -- the click
ladder, typing, reading a window, the fullscreen guard -- works the same way
on every computer:

- macOS: Quartz (window list, window images even when covered, events sent to
  one app without moving the mouse, typing any character) and AppKit
  (bringing an app forward). Needs the Accessibility and Screen Recording
  permissions, which `permissions()` reports and onboarding asks for.
- Linux (X11, and X apps under Wayland through XWayland): Xlib and the EWMH
  properties every window manager publishes, XTest for input.

A window is identified by an int id: the CGWindowID on macOS, the X window id
on Linux (and the HWND on Windows, handled in desktop.py).
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time

logger = logging.getLogger(__name__)

MAC = sys.platform == "darwin"
LINUX = sys.platform.startswith("linux")


class Unavailable(Exception):
    """This system can't do it, and why (safe to show the user)."""


def _window(wid: int, title: str, process: str | None, pid: int | None, rect, active: bool) -> dict:
    return {"hwnd": int(wid), "title": title or "", "process": process, "pid": pid, "rect": tuple(int(v) for v in rect),
            "active": active, "maybe_unsaved": (title or "").startswith(("*", "●"))}


def _process_name(pid: int | None) -> str | None:
    if not pid:
        return None
    try:
        import psutil
        return psutil.Process(pid).name()
    except Exception:  # noqa: BLE001
        return None


# ============================================================== macOS

if MAC:
    def _quartz():
        try:
            import Quartz
            return Quartz
        except Exception as exc:  # noqa: BLE001
            raise Unavailable(f"macOS window control needs pyobjc-framework-Quartz ({exc}). Run install.sh again.") from exc

    def _front_pid() -> int | None:
        try:
            from AppKit import NSWorkspace
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            return int(app.processIdentifier()) if app else None
        except Exception:  # noqa: BLE001
            return None

    def _ax_title(pid: int, bounds) -> str:
        """Window titles need Screen Recording permission through Quartz; the
        accessibility tree has them too, so ask there when Quartz won't say."""
        try:
            from . import ax_mac
            return ax_mac.window_title(pid, bounds) or ""
        except Exception:  # noqa: BLE001
            return ""

    def list_windows() -> list[dict]:
        Q = _quartz()
        options = Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements
        info = Q.CGWindowListCopyWindowInfo(options, Q.kCGNullWindowID) or []
        front = _front_pid()
        out, active_given = [], False
        for w in info:  # front to back
            if int(w.get("kCGWindowLayer", 0)) != 0:
                continue  # menu bar, Dock, overlays
            b = w.get("kCGWindowBounds") or {}
            rect = (b.get("X", 0), b.get("Y", 0), b.get("X", 0) + b.get("Width", 0), b.get("Y", 0) + b.get("Height", 0))
            if rect[2] - rect[0] < 40 or rect[3] - rect[1] < 30:
                continue
            pid = int(w.get("kCGWindowOwnerPID", 0)) or None
            title = w.get("kCGWindowName") or _ax_title(pid, rect)
            owner = w.get("kCGWindowOwnerName")
            if not title and not owner:
                continue
            active = bool(pid and pid == front and not active_given)
            active_given = active_given or active
            out.append(_window(w["kCGWindowNumber"], title or owner, owner or _process_name(pid), pid, rect, active))
        return out

    def monitors() -> list[tuple[int, int, int, int]]:
        Q = _quartz()
        err, ids, count = Q.CGGetActiveDisplayList(16, None, None)
        result = []
        for display in (ids or [])[:count]:
            r = Q.CGDisplayBounds(display)
            result.append((int(r.origin.x), int(r.origin.y), int(r.origin.x + r.size.width), int(r.origin.y + r.size.height)))
        return result

    def cursor_pos() -> tuple[int, int]:
        Q = _quartz()
        p = Q.CGEventGetLocation(Q.CGEventCreate(None))
        return int(p.x), int(p.y)

    def set_cursor(x: int, y: int) -> None:
        Q = _quartz()
        Q.CGWarpMouseCursorPosition((x, y))
        Q.CGAssociateMouseAndMouseCursorPosition(True)

    def activate(wid: int) -> bool:
        w = window(wid)
        if not w or not w["pid"]:
            return False
        try:
            from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(w["pid"])
            ok = bool(app and app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps))
            try:
                from . import ax_mac
                ax_mac.raise_window(w["pid"], w["rect"])
            except Exception:  # noqa: BLE001
                pass
            return ok
        except Exception:  # noqa: BLE001
            return False

    def capture(wid: int):
        """The window's own image, even when covered (Quartz composites it)."""
        Q = _quartz()
        try:
            from PIL import Image
            image = Q.CGWindowListCreateImage(Q.CGRectNull, Q.kCGWindowListOptionIncludingWindow, int(wid),
                                              Q.kCGWindowImageBoundsIgnoreFraming | Q.kCGWindowImageNominalResolution)
            if image is None:
                return None
            width, height = Q.CGImageGetWidth(image), Q.CGImageGetHeight(image)
            if not width or not height:
                return None
            data = Q.CGDataProviderCopyData(Q.CGImageGetDataProvider(image))
            return Image.frombuffer("RGBA", (width, height), bytes(data), "raw", "BGRA",
                                    Q.CGImageGetBytesPerRow(image), 1).convert("RGB")
        except Exception:  # noqa: BLE001
            logger.debug("window capture failed", exc_info=True)
            return None

    _BUTTONS = {"left": (1, 2, 0), "right": (3, 4, 1), "middle": (25, 26, 2)}  # down, up, CGMouseButton

    def send_click(wid: int, x: int, y: int, button: str, double: bool) -> bool:
        """Deliver a click to the app that owns the window, without moving the
        user's mouse (CGEventPostToPid). Some apps only listen to the real
        mouse; the caller checks whether the window changed."""
        Q = _quartz()
        w = window(wid)
        if not w or not w["pid"]:
            return False
        down, up, btn = _BUTTONS[button]
        if button == "middle":
            down, up = Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp
        for n in range(2 if double else 1):
            for kind in (down, up):
                event = Q.CGEventCreateMouseEvent(None, kind, (x, y), btn)
                Q.CGEventSetIntegerValueField(event, Q.kCGMouseEventClickState, n + 1)
                Q.CGEventPostToPid(w["pid"], event)
        return True

    def send_scroll(wid: int, x: int, y: int, clicks: int) -> bool:
        Q = _quartz()
        w = window(wid)
        if not w or not w["pid"]:
            return False
        event = Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitLine, 1, int(clicks) * 3)
        Q.CGEventSetLocation(event, (x, y))
        Q.CGEventPostToPid(w["pid"], event)
        return True

    def type_unicode(text: str, check) -> None:
        """Any character, emoji included: the key event carries the text itself."""
        Q = _quartz()
        for i in range(0, len(text), 16):
            check()
            chunk = text[i:i + 16]
            for down in (True, False):
                event = Q.CGEventCreateKeyboardEvent(None, 0, down)
                Q.CGEventKeyboardSetUnicodeString(event, len(chunk.encode("utf-16-le")) // 2, chunk)
                Q.CGEventPost(Q.kCGHIDEventTap, event)
            time.sleep(0.012)

    def close(wid: int) -> bool:
        """Press the window's own close button (so the app can ask about
        unsaved work, as it would for the user)."""
        w = window(wid)
        if not w or not w["pid"]:
            return False
        from . import ax_mac
        return ax_mac.close_window(w["pid"], w["rect"])

    def permissions() -> dict:
        """What macOS has allowed Nova to do."""
        out = {"accessibility": False, "screen": False}
        try:
            from ApplicationServices import AXIsProcessTrusted
            out["accessibility"] = bool(AXIsProcessTrusted())
        except Exception:  # noqa: BLE001
            pass
        try:
            Q = _quartz()
            out["screen"] = bool(Q.CGPreflightScreenCaptureAccess())
        except Exception:  # noqa: BLE001
            pass
        return out

    def request_permissions() -> dict:
        """Show macOS's own prompts (each appears once; after that the user
        switches Nova on in System Settings > Privacy & Security)."""
        try:
            from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
            AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
        except Exception:  # noqa: BLE001
            pass
        try:
            _quartz().CGRequestScreenCaptureAccess()
        except Exception:  # noqa: BLE001
            pass
        return permissions()


# ============================================================== Linux (X11)

elif LINUX:
    _local = threading.local()
    # A Wayland session: native apps are not X windows. Nova still sees them
    # through the accessibility bus (AT-SPI works the same under Wayland) and
    # takes screenshots through the desktop's screenshot portal.
    WAYLAND = os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))
    _AX_IDS: dict[tuple, int] = {}   # (bus name, path) -> window id
    _AX_BY_ID: dict[int, tuple] = {}
    _AX_BASE = 0x7F000000

    def _display():
        """One X connection per thread (Xlib connections are not thread-safe)."""
        d = getattr(_local, "display", None)
        if d is None:
            if not os.environ.get("DISPLAY"):
                raise Unavailable("No X display. On a Wayland desktop, Nova controls apps through XWayland; "
                                  "start Nova from the desktop session so DISPLAY is set.")
            try:
                from Xlib import display as xdisplay
                d = xdisplay.Display()
            except Exception as exc:  # noqa: BLE001
                raise Unavailable(f"Couldn't connect to the X display ({exc}).") from exc
            _local.display = d
        return d

    def _atom(name: str) -> int:
        return _display().intern_atom(name)

    def _prop(win, name: str, kind=None):
        from Xlib import X
        try:
            p = win.get_full_property(_atom(name), kind if kind is not None else X.AnyPropertyType)
            return p.value if p else None
        except Exception:  # noqa: BLE001
            return None

    def _xwin(wid: int):
        return _display().create_resource_object("window", int(wid))

    def _title(win) -> str:
        v = _prop(win, "_NET_WM_NAME", _atom("UTF8_STRING"))
        if v is None:
            v = _prop(win, "WM_NAME")
        if isinstance(v, bytes):
            return v.decode("utf-8", "replace")
        return v or ""

    def _pid(win) -> int | None:
        v = _prop(win, "_NET_WM_PID")
        return int(v[0]) if v is not None and len(v) else None

    def _rect(win) -> tuple[int, int, int, int]:
        d = _display()
        g = win.get_geometry()
        pos = win.translate_coords(d.screen().root, 0, 0)
        x, y = -pos.x, -pos.y
        return (x, y, x + g.width, y + g.height)

    def _states(win) -> set[int]:
        v = _prop(win, "_NET_WM_STATE")
        return set(v) if v is not None else set()

    def _client_ids(stacking: bool = False) -> list[int]:
        root = _display().screen().root
        v = _prop(root, "_NET_CLIENT_LIST_STACKING" if stacking else "_NET_CLIENT_LIST")
        return [int(x) for x in (v if v is not None else [])]

    def _active_id() -> int | None:
        v = _prop(_display().screen().root, "_NET_ACTIVE_WINDOW")
        return int(v[0]) if v is not None and len(v) and v[0] else None

    def _ax_id(ref: tuple) -> int:
        if ref not in _AX_IDS:
            _AX_IDS[ref] = _AX_BASE + len(_AX_IDS)
            _AX_BY_ID[_AX_IDS[ref]] = ref
        return _AX_IDS[ref]

    def ax_window_ref(wid: int):
        """The accessibility node of a window Nova found through AT-SPI."""
        return _AX_BY_ID.get(int(wid))

    def _ax_windows(known: list[dict]) -> list[dict]:
        """Native Wayland windows, from the accessibility bus: every app's
        top-level frames that X doesn't already list. Their position on
        screen isn't something Wayland tells other apps, so they carry no
        rect and are worked with by their controls (app_controls & co)."""
        try:
            from . import ax_linux
            seen = {(w["pid"], w["title"]) for w in known}
            out = []
            for app_ref, pid, frames in ax_linux.top_level_windows():
                for ref, title, active in frames:
                    if not title or (pid, title) in seen:
                        continue
                    out.append({**_window(_ax_id(ref), title, _process_name(pid), pid, (0, 0, 0, 0), active),
                                "via": "accessibility"})
            return out
        except Exception:  # noqa: BLE001
            logger.debug("accessibility window list failed", exc_info=True)
            return []

    def list_windows() -> list[dict]:
        x_windows = _x_windows() if os.environ.get("DISPLAY") else []
        if not WAYLAND:
            return x_windows
        extra = _ax_windows(x_windows)
        if any(w["active"] for w in extra):
            for w in x_windows:
                w["active"] = False
        return extra + x_windows

    def _x_windows() -> list[dict]:
        hidden = _atom("_NET_WM_STATE_HIDDEN")
        active = _active_id()
        out = []
        for wid in reversed(_client_ids(stacking=True)):  # front to back
            try:
                win = _xwin(wid)
                if hidden in _states(win):
                    continue
                title = _title(win)
                if not title.strip():
                    continue
                pid = _pid(win)
                out.append(_window(wid, title, _process_name(pid), pid, _rect(win), wid == active))
            except Exception:  # noqa: BLE001 -- closed while we looked
                continue
        return out

    def monitors() -> list[tuple[int, int, int, int]]:
        try:
            import mss
            with mss.mss() as sct:
                return [(m["left"], m["top"], m["left"] + m["width"], m["top"] + m["height"]) for m in sct.monitors[1:]]
        except Exception:  # noqa: BLE001
            s = _display().screen()
            return [(0, 0, s.width_in_pixels, s.height_in_pixels)]

    def cursor_pos() -> tuple[int, int]:
        p = _display().screen().root.query_pointer()
        return int(p.root_x), int(p.root_y)

    def set_cursor(x: int, y: int) -> None:
        d = _display()
        d.screen().root.warp_pointer(int(x), int(y))
        d.sync()

    def activate(wid: int) -> bool:
        if ax_window_ref(wid):
            return False  # Wayland lets no app raise another's window
        from Xlib import X
        from Xlib.protocol import event as xevent
        d = _display()
        root = d.screen().root
        msg = xevent.ClientMessage(window=_xwin(wid), client_type=_atom("_NET_ACTIVE_WINDOW"),
                                   data=(32, [2, X.CurrentTime, 0, 0, 0]))
        root.send_event(msg, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        d.sync()
        return True

    def capture(wid: int):
        """What the window shows on screen (its visible part)."""
        if ax_window_ref(wid):
            return None
        try:
            import mss
            from PIL import Image
            left, top, right, bottom = _rect(_xwin(wid))
            if right <= left or bottom <= top:
                return None
            with mss.mss() as sct:
                shot = sct.grab({"left": left, "top": top, "width": right - left, "height": bottom - top})
                return Image.frombytes("RGB", shot.size, shot.rgb)
        except Exception:  # noqa: BLE001
            logger.debug("window capture failed", exc_info=True)
            return None

    def _deepest(wid: int, x: int, y: int):
        """The innermost X window under a screen point, and the point in it."""
        d = _display()
        root = d.screen().root
        target = _xwin(wid)
        for _ in range(10):
            t = target.translate_coords(root, x, y)  # the point in target's coordinates
            child = t.child
            if not child or child.id == 0:
                return target, t.x, t.y
            target = child
        t = target.translate_coords(root, x, y)
        return target, t.x, t.y

    def send_click(wid: int, x: int, y: int, button: str, double: bool) -> bool:
        """A click event sent to the window under the point, not through the
        real mouse. Many toolkits ignore synthetic events; the caller checks
        whether the window changed."""
        from Xlib import X
        from Xlib.protocol import event as xevent
        d = _display()
        root = d.screen().root
        target, lx, ly = _deepest(wid, x, y)
        number = {"left": 1, "middle": 2, "right": 3}[button]
        for _ in range(2 if double else 1):
            for kind, cls, mask in ((X.ButtonPress, xevent.ButtonPress, X.ButtonPressMask),
                                    (X.ButtonRelease, xevent.ButtonRelease, X.ButtonReleaseMask)):
                ev = cls(time=X.CurrentTime, root=root, window=target, same_screen=1, child=X.NONE,
                         root_x=x, root_y=y, event_x=lx, event_y=ly, state=0, detail=number)
                target.send_event(ev, event_mask=mask, propagate=True)
        d.sync()
        return True

    def send_scroll(wid: int, x: int, y: int, clicks: int) -> bool:
        from Xlib import X
        from Xlib.protocol import event as xevent
        d = _display()
        root = d.screen().root
        target, lx, ly = _deepest(wid, x, y)
        number = 4 if clicks > 0 else 5
        for _ in range(abs(int(clicks))):
            for cls, mask in ((xevent.ButtonPress, X.ButtonPressMask), (xevent.ButtonRelease, X.ButtonReleaseMask)):
                ev = cls(time=X.CurrentTime, root=root, window=target, same_screen=1, child=X.NONE,
                         root_x=x, root_y=y, event_x=lx, event_y=ly, state=0, detail=number)
                target.send_event(ev, event_mask=mask, propagate=True)
        d.sync()
        return True

    def type_unicode(text: str, check) -> None:
        """Any character through XTest. A character the keyboard layout has no
        key for gets a spare keycode mapped to it for the moment it is typed
        (the same trick xdotool uses), then the mapping is put back."""
        from Xlib import X, XK
        from Xlib.ext import xtest
        d = _display()
        low, high = d.display.info.min_keycode, d.display.info.max_keycode
        mapping = d.get_keyboard_mapping(low, high - low + 1)
        spare = next((low + i for i, syms in enumerate(mapping) if not any(syms)), high)
        original = list(mapping[spare - low])
        shift = d.keysym_to_keycode(XK.XK_Shift_L)

        def tap(code: int, shifted: bool) -> None:
            if shifted:
                xtest.fake_input(d, X.KeyPress, shift)
            xtest.fake_input(d, X.KeyPress, code)
            xtest.fake_input(d, X.KeyRelease, code)
            if shifted:
                xtest.fake_input(d, X.KeyRelease, shift)
            d.sync()

        try:
            for ch in text:
                check()
                if ch == "\n":
                    keysym = XK.XK_Return
                elif ch == "\t":
                    keysym = XK.XK_Tab
                else:
                    keysym = XK.string_to_keysym(ch) if len(ch) == 1 and ch.isascii() and ch.isalnum() else 0
                    if not keysym:
                        cp = ord(ch)
                        keysym = cp if 0x20 <= cp <= 0x7E or 0xA0 <= cp <= 0xFF else 0x01000000 | cp
                code = d.keysym_to_keycode(keysym)
                if code:
                    tap(code, d.keycode_to_keysym(code, 0) != keysym)
                else:
                    d.change_keyboard_mapping(spare, [(keysym,) * max(1, len(original))])
                    d.sync()
                    time.sleep(0.01)
                    tap(spare, False)
                time.sleep(0.004)
        finally:
            d.change_keyboard_mapping(spare, [tuple(original) or (0,)])
            d.sync()

    def close(wid: int) -> bool:
        """Ask the window manager to close it (_NET_CLOSE_WINDOW), the same
        request the title bar's X button makes."""
        if ax_window_ref(wid):
            from . import ax_linux
            return ax_linux.close_frame(ax_window_ref(wid))
        from Xlib import X
        from Xlib.protocol import event as xevent
        d = _display()
        msg = xevent.ClientMessage(window=_xwin(wid), client_type=_atom("_NET_CLOSE_WINDOW"),
                                   data=(32, [X.CurrentTime, 2, 0, 0, 0]))
        d.screen().root.send_event(msg, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        d.sync()
        return True

    def screenshot_png() -> bytes | None:
        """The whole screen on Wayland, where X can only see X apps: the
        desktop's screenshot portal (GNOME asks once, then remembers), or the
        compositor's own tool (grim on Sway/Hyprland, spectacle on KDE)."""
        import shutil
        import subprocess
        import tempfile
        try:
            from . import portal
            data = portal.screenshot()
            if data:
                return data
        except Exception:  # noqa: BLE001
            logger.debug("screenshot portal failed", exc_info=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "shot.png")
            for cmd in (["grim", path], ["spectacle", "-b", "-n", "-f", "-o", path], ["gnome-screenshot", "-f", path]):
                if shutil.which(cmd[0]):
                    try:
                        subprocess.run(cmd, check=True, timeout=15, capture_output=True)
                        with open(path, "rb") as f:
                            return f.read()
                    except Exception:  # noqa: BLE001
                        continue
        return None

    def permissions() -> dict:
        return {"accessibility": True, "screen": bool(os.environ.get("DISPLAY") or WAYLAND)}

    def request_permissions() -> dict:
        return permissions()


if not LINUX:
    WAYLAND = False

    def screenshot_png() -> bytes | None:
        return None

    def ax_window_ref(wid: int):
        return None


if MAC or LINUX:
    pass
else:  # Windows is handled in desktop.py; these keep imports honest elsewhere.
    def list_windows() -> list[dict]:
        raise Unavailable("desktop_os is for macOS and Linux.")

    def permissions() -> dict:
        return {"accessibility": True, "screen": True}

    def request_permissions() -> dict:
        return permissions()


# ============================================================== shared (macOS and Linux)

def window(wid: int) -> dict | None:
    return next((w for w in list_windows() if w["hwnd"] == int(wid)), None)


def active_window() -> dict | None:
    return next((w for w in list_windows() if w["active"]), None)


def window_at(x: int, y: int) -> dict | None:
    """The frontmost window containing a screen point."""
    for w in list_windows():
        left, top, right, bottom = w["rect"]
        if right > left and left <= x < right and top <= y < bottom:
            return w
    return None


def fullscreen_app() -> dict | None:
    """The active window, if it covers its whole monitor (a game, a
    fullscreen video)."""
    try:
        w = active_window()
        if not w or w.get("via") == "accessibility":
            return None  # Wayland doesn't say where other apps' windows are
        wl, wt, wr, wb = w["rect"]
        for m in monitors():
            ml, mt, mr, mb = m
            if wl <= ml and wt <= mt and wr >= mr and wb >= mb:
                return {"hwnd": w["hwnd"], "title": w["title"], "process": w["process"], "monitor": m}
    except Exception:  # noqa: BLE001
        return None
    return None
