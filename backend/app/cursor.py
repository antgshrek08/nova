"""Nova's mouse, moving where you can see it.

Every click Nova made teleported: `pyautogui.click(x=..., y=...)` sets the
pointer and fires in the same instant, so the only evidence anything happened
was the result afterwards. The user asked to watch it work, which is a
reasonable thing to want from software that drives your desktop -- being able
to see what it is about to do is most of what makes handing it the mouse
acceptable, and it is the difference between noticing a wrong click and
finding out later.

There is a second reason beyond watching. A pointer that appears at its
destination never generates the enter/hover events a real mouse does, and
plenty of interfaces -- menus that open on hover, buttons that only arm once
the cursor is inside them, drag handles that appear on approach -- are built
around those. Moving there properly makes the click land on something that
has had a chance to notice the pointer.

Three pieces:

**The glide** interpolates with an ease-in-out curve and a slight arc, so the
path is neither instant nor a suspiciously straight line at constant speed.

**The ring** is a borderless click-through window drawn at the target. Click-
through matters more than it looks: an overlay that accepts input would eat
the very click it was drawn to illustrate, so it is marked WS_EX_TRANSPARENT
and the click passes through it into whatever is underneath.

**Fail-safe.** Every part of this is decoration around an action that has to
happen. If the overlay cannot be created, or tkinter is missing, or the arc
maths goes wrong, the click still gets made -- degraded to the old teleport
rather than lost.
"""
from __future__ import annotations

import logging
import math
import time
import threading

logger = logging.getLogger(__name__)

# Long enough to follow with your eyes, short enough not to make Nova feel
# slow. A full-screen traverse at this duration reads as deliberate rather
# than sluggish; anything under ~150ms is back to teleporting.
DEFAULT_DURATION = 0.45
MIN_DURATION = 0.12
MAX_DURATION = 2.5

# Steps per second of travel. Above this the movement is smooth and the extra
# calls are wasted; below it the pointer visibly stutters.
STEPS_PER_SECOND = 90

RING_RADIUS = 26
RING_COLOR = "#34d399"     # Nova's emerald, so the marker reads as Nova's
RING_MS = 280


def _ease(t: float) -> float:
    """Ease-in-out. Slow at both ends, quickest in the middle -- which is how
    a hand moves, and makes the destination readable before arrival."""
    return 3 * t * t - 2 * t * t * t


def glide(pyautogui, x: int, y: int, duration: float = DEFAULT_DURATION) -> None:
    """Move the pointer to (x, y) along a visible, slightly curved path."""
    duration = max(MIN_DURATION, min(float(duration), MAX_DURATION))
    try:
        start_x, start_y = pyautogui.position()
    except Exception:  # noqa: BLE001
        pyautogui.moveTo(x, y)
        return

    dx, dy = x - start_x, y - start_y
    distance = math.hypot(dx, dy)
    if distance < 2:
        return

    # A perpendicular bow, proportional to the distance and capped, so a long
    # traverse curves and a short nudge stays effectively straight.
    bow = min(distance * 0.08, 60.0)
    steps = max(8, int(duration * STEPS_PER_SECOND))

    for step in range(1, steps + 1):
        t = _ease(step / steps)
        # sin(pi*t) peaks mid-path and is zero at both ends, so the curve
        # never displaces the start or the target.
        offset = math.sin(math.pi * (step / steps)) * bow
        px = start_x + dx * t - (dy / distance) * offset
        py = start_y + dy * t + (dx / distance) * offset
        try:
            pyautogui.moveTo(round(px), round(py), _pause=False)
        except TypeError:
            pyautogui.moveTo(round(px), round(py))
        time.sleep(duration / steps)

    # Land exactly on target: the eased path is float maths and can finish a
    # pixel or two short, which matters for a small control.
    try:
        pyautogui.moveTo(x, y, _pause=False)
    except TypeError:
        pyautogui.moveTo(x, y)


# The ring is drawn with raw Win32 rather than tkinter.
#
# tkinter was the obvious choice and does not work here: it imports fine and
# then Tk() dies with "Can't find a usable init.tcl", because this Python's
# Tcl runtime is not installed properly. Rather than make a visible-click
# feature depend on repairing an unrelated interpreter, this uses the window
# manager directly -- which is present by definition on the only platform
# that has a pointer to move.
#
# The trick that avoids any painting code: the window *is* the ring. An
# elliptical region minus a smaller elliptical region leaves a ring-shaped
# window, and the class background brush fills it. No WM_PAINT handler, no
# message loop, nothing to go stale.
_RING_CLASS = "NovaClickRing"
_ring_class_registered = False
_ring_registration_lock = threading.Lock()


def _register_ring_class(ctypes, wintypes):
    """Register the overlay's window class once per process."""
    # Worker threads may reach the first click together. A second attempt
    # must not replace keep_alive with a different callback while Windows
    # still holds the callback from the first successful registration.
    with _ring_registration_lock:
        return _register_ring_class_locked(ctypes, wintypes)


def _register_ring_class_locked(ctypes, wintypes):
    global _ring_class_registered
    if _ring_class_registered:
        return True

    # LRESULT/WPARAM/LPARAM are pointer-sized, not int-sized. Left to guess,
    # ctypes converts them as C int and a perfectly ordinary message arrives
    # as "argument 4: OverflowError: int too long to convert" on 64-bit --
    # which surfaces as a stream of errors from the window proc while the
    # window itself looks fine.
    LRESULT = ctypes.c_ssize_t
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    gdi32 = ctypes.windll.gdi32
    # ctypes otherwise assumes C int return values and arguments. That
    # truncates HINSTANCE/HWND/GDI handles on 64-bit Windows, sometimes
    # producing an access violation inside RegisterClassW/CreateWindowExW.
    signatures = [
        (kernel32.GetModuleHandleW, wintypes.HMODULE, [wintypes.LPCWSTR]),
        (gdi32.CreateSolidBrush, wintypes.HBRUSH, [wintypes.DWORD]),
        (gdi32.CreateEllipticRgn, wintypes.HRGN, [ctypes.c_int] * 4),
        (gdi32.CombineRgn, ctypes.c_int,
         [wintypes.HRGN, wintypes.HRGN, wintypes.HRGN, ctypes.c_int]),
        (gdi32.DeleteObject, wintypes.BOOL, [wintypes.HANDLE]),
        (user32.CreateWindowExW, wintypes.HWND,
         [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
          ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
          wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]),
        (user32.SetWindowRgn, ctypes.c_int,
         [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]),
        (user32.SetLayeredWindowAttributes, wintypes.BOOL,
         [wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD]),
        (user32.ShowWindow, wintypes.BOOL, [wintypes.HWND, ctypes.c_int]),
        (user32.UpdateWindow, wintypes.BOOL, [wintypes.HWND]),
        (user32.DestroyWindow, wintypes.BOOL, [wintypes.HWND]),
    ]
    for function, result, arguments in signatures:
        function.restype = result
        function.argtypes = arguments
    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                      ctypes.c_size_t, ctypes.c_ssize_t]

    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint,
                                 ctypes.c_size_t, ctypes.c_ssize_t)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
        ]

    user32.RegisterClassW.restype = wintypes.ATOM
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]

    # Emerald, as 0x00BBGGRR -- Win32 colour order is the reverse of hex CSS.
    brush = ctypes.windll.gdi32.CreateSolidBrush(0x0099D334)
    proc = WNDPROC(lambda h, m, w, l: ctypes.windll.user32.DefWindowProcW(h, m, w, l))

    cls = WNDCLASS()
    cls.style = 0
    cls.lpfnWndProc = proc
    cls.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
    cls.hbrBackground = brush
    cls.lpszClassName = _RING_CLASS
    # Kept alive on the module: a WNDPROC that gets garbage collected while
    # Windows still holds the pointer is a crash waiting for the next message.
    _register_ring_class.keep_alive = (proc, cls, brush)

    if not ctypes.windll.user32.RegisterClassW(ctypes.byref(cls)):
        # 1410 is "class already exists", which is success for our purposes.
        if ctypes.windll.kernel32.GetLastError() != 1410:
            return False
    _ring_class_registered = True
    return True


def flash(x: int, y: int, hold_ms: int = RING_MS) -> None:
    """Draw a ring at (x, y) for a moment. Best effort, never raises.

    Blocks the calling thread for `hold_ms`, which is fine: the caller is
    already a worker thread doing a slow physical action.
    """
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # noqa: BLE001
        return
    if not hasattr(ctypes, "windll"):
        # macOS and Linux: the desktop app's overlay draws the same ring.
        try:
            from . import nova_pointer
            nova_pointer.pointer.flash(x, y)
        except Exception:  # noqa: BLE001
            pass
        return

    WS_POPUP = 0x80000000
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020   # clicks pass straight through
    WS_EX_TOOLWINDOW = 0x00000080    # keep it out of alt-tab
    WS_EX_TOPMOST = 0x00000008
    WS_EX_NOACTIVATE = 0x08000000    # never steal focus from what is being clicked
    SW_SHOWNOACTIVATE = 4
    RGN_DIFF = 4

    hwnd = None
    try:
        if not _register_ring_class(ctypes, wintypes):
            return
        size = RING_RADIUS * 2
        left, top = int(x) - RING_RADIUS, int(y) - RING_RADIUS

        hwnd = ctypes.windll.user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
            | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
            _RING_CLASS, None, WS_POPUP,
            left, top, size, size,
            None, None, ctypes.windll.kernel32.GetModuleHandleW(None), None,
        )
        if not hwnd:
            return

        # Ring = outer ellipse minus inner ellipse. The window takes that
        # shape, so the background brush is the only "drawing" needed.
        outer = ctypes.windll.gdi32.CreateEllipticRgn(0, 0, size, size)
        inner = ctypes.windll.gdi32.CreateEllipticRgn(4, 4, size - 4, size - 4)
        ctypes.windll.gdi32.CombineRgn(outer, outer, inner, RGN_DIFF)
        ctypes.windll.gdi32.DeleteObject(inner)
        ctypes.windll.user32.SetWindowRgn(hwnd, outer, True)

        ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 200, 0x02)  # LWA_ALPHA
        ctypes.windll.user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        ctypes.windll.user32.UpdateWindow(hwnd)
        time.sleep(max(0, hold_ms) / 1000)
    except Exception:  # noqa: BLE001
        logger.debug("Could not draw the click marker", exc_info=True)
    finally:
        if hwnd:
            try:
                ctypes.windll.user32.DestroyWindow(hwnd)
            except Exception:  # noqa: BLE001
                pass


def visible_click(pyautogui, x: int, y: int, button: str = "left",
                  duration: float = DEFAULT_DURATION, show_marker: bool = True) -> None:
    """Move there where it can be seen, mark the spot, then click.

    The marker is drawn *before* the click rather than after. Feedback after
    the fact says what happened; a marker beforehand says what is about to,
    which is the half that gives a watching user time to intervene.
    """
    glide(pyautogui, x, y, duration)
    if show_marker:
        flash(x, y)
    pyautogui.click(x=x, y=y, button=button)
