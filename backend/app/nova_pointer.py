"""Nova's own pointer: a second cursor on the desktop that is Nova's, not yours.

The user's ask: Nova should have a cursor of its own, working while they watch
a show or plays a game, instead of taking over their mouse. So this draws one --
an emerald arrow tagged "Nova" -- in a click-through, never-focusable,
always-on-top window, and glides it to wherever Nova is acting. It is purely
visual. The action itself goes through UI Automation or a window message (see
desktop.click), so the real mouse is left where the user put it.

It also owns the two ways to stop Nova, because both need a thread that is
always listening:

- **Ctrl+Alt+Esc**, registered as a system-wide hotkey on this thread. It
  works while a game has focus, which the old corner gesture does not: a
  game that captures the mouse never lets the pointer reach a corner.
- **The corner.** Throwing *your* mouse into a screen corner still stops
  Nova. It works better than before: the real pointer is now only ever
  yours, so the gesture can never be confused with Nova's own movement.

**Quiet mode.** On a monitor where a fullscreen app is in front, the pointer
is not drawn at all -- a topmost overlay would paint over a borderless game.
"""
from __future__ import annotations

import logging
import math
import queue
import sys
import threading
import time

logger = logging.getLogger(__name__)

# The stop key. On Windows this thread registers it; on macOS and Linux the
# desktop app registers it (Electron globalShortcut) and reports which one it
# got, since a desktop may already own the first choice (KDE: Ctrl+Alt+Esc).
HOTKEY_LABEL = "Control+Option+Esc" if sys.platform == "darwin" else "Ctrl+Alt+Esc"
IDLE_HIDE_S = 4.0
CORNER_MARGIN = 2
STEPS_PER_SECOND = 90
EMERALD = (52, 211, 153)

# ---------------------------------------------------------------- pure geometry


def ease(t: float) -> float:
    return t * t * (3 - 2 * t)


def glide_points(start: tuple[int, int], end: tuple[int, int], seconds: float) -> list[tuple[int, int]]:
    """Points from start to end, one per frame, ending exactly on `end`. Same
    shape as the old real-mouse glide: eased, with a small perpendicular bow."""
    (x0, y0), (x1, y1) = start, end
    dx, dy = x1 - x0, y1 - y0
    distance = math.hypot(dx, dy)
    if seconds <= 0 or distance < 1:
        return [(x1, y1)]
    steps = max(2, int(seconds * STEPS_PER_SECOND))
    bow = min(distance * 0.08, 60.0)
    nx, ny = -dy / distance, dx / distance
    points = []
    for i in range(1, steps):
        t = i / steps
        e = ease(t)
        off = bow * math.sin(math.pi * t)
        points.append((round(x0 + dx * e + nx * off), round(y0 + dy * e + ny * off)))
    points.append((x1, y1))
    return points


def in_corner(point: tuple[int, int], monitors: list[tuple[int, int, int, int]], margin: int = CORNER_MARGIN) -> bool:
    """Is the point in a corner of any monitor? Monitors are (left, top, right, bottom)."""
    x, y = point
    for left, top, right, bottom in monitors:
        near_x = x <= left + margin or x >= right - 1 - margin
        near_y = y <= top + margin or y >= bottom - 1 - margin
        if near_x and near_y and left <= x < right and top <= y < bottom:
            return True
    return False


SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


def covers_monitor(window: tuple[int, int, int, int], monitor: tuple[int, int, int, int], class_name: str) -> bool:
    """Does this window fill its monitor the way a fullscreen game or video does?
    The desktop and taskbar also span a monitor and are not fullscreen apps."""
    if class_name in SHELL_CLASSES:
        return False
    wl, wt, wr, wb = window
    ml, mt, mr, mb = monitor
    return wl <= ml and wt <= mt and wr >= mr and wb >= mb


# ---------------------------------------------------------------- Win32 side

_WINDOWS = sys.platform == "win32"


def _monitors() -> list[tuple[int, int, int, int]]:
    if not _WINDOWS:
        try:
            from . import desktop_os
            return desktop_os.monitors()
        except Exception:  # noqa: BLE001
            return []
    try:
        import win32api
        return [tuple(rect) for _h, _dc, rect in win32api.EnumDisplayMonitors()]
    except Exception:  # noqa: BLE001
        return []


def fullscreen_app() -> dict | None:
    """The foreground window, if it is a fullscreen app (a game, a fullscreen
    video). None otherwise. Nova must not take focus from it, type into it,
    or draw over it."""
    if not _WINDOWS:
        try:
            from . import desktop_os
            return desktop_os.fullscreen_app()
        except Exception:  # noqa: BLE001
            return None
    try:
        import win32api
        import win32gui
        import win32process
        import psutil
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        rect = win32gui.GetWindowRect(hwnd)
        monitor = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, 2))["Monitor"]
        if not covers_monitor(rect, monitor, win32gui.GetClassName(hwnd)):
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            process = psutil.Process(pid).name()
        except Exception:  # noqa: BLE001
            process = None
        return {"hwnd": hwnd, "title": win32gui.GetWindowText(hwnd), "process": process,
                "monitor": tuple(monitor)}
    except Exception:  # noqa: BLE001
        return None


def point_under_fullscreen(x: int, y: int) -> dict | None:
    app = fullscreen_app()
    if not app:
        return None
    left, top, right, bottom = app["monitor"]
    return app if left <= x < right and top <= y < bottom else None


class Stopped(Exception):
    """The user stopped Nova (hotkey, corner, or the Stop button)."""


class _Pointer:
    """The overlay window and its thread. One per process."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._hwnd = 0
        self._ready = threading.Event()
        self._commands: queue.Queue = queue.Queue()
        self._position: tuple[int, int] | None = None
        self._hide_timer: threading.Timer | None = None
        self._size = (0, 0)
        self._hotspot = (0, 0)
        self.hotkey_registered = False
        self._stop_listeners: list = []
        self._lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------

    def start(self) -> bool:
        if not _WINDOWS:
            return False
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            self._ready.clear()
            self._thread = threading.Thread(target=self._run, name="nova-pointer", daemon=True)
            self._thread.start()
        self._ready.wait(5)
        return bool(self._hwnd)

    def on_stop(self, listener) -> None:
        """Called (on the pointer thread) when Ctrl+Alt+Esc is pressed."""
        self._stop_listeners.append(listener)

    # -- drawing API (any thread) --------------------------------------------

    def move(self, x: int, y: int, *, quiet_checked: bool = False) -> None:
        if not self.start() or (not quiet_checked and point_under_fullscreen(x, y)):
            self.hide()
            return
        import ctypes
        hx, hy = self._hotspot
        user32 = ctypes.windll.user32
        # HWND_TOPMOST, no size change, never activate, show.
        user32.SetWindowPos(self._hwnd, -1, int(x) - hx, int(y) - hy, 0, 0, 0x0001 | 0x0010 | 0x0040)
        self._position = (x, y)
        self._schedule_hide()

    def glide(self, x: int, y: int, seconds: float, check=None) -> None:
        """Glide from where Nova's pointer last was. `check` runs every step and
        may raise Stopped -- that is how the corner and the hotkey interrupt a
        glide in flight rather than after it."""
        start = self._position or self._entry_point(x, y)
        # Checked once per glide, not per frame: it costs several window
        # queries, and a glide is over in half a second.
        quiet = point_under_fullscreen(x, y) is not None
        if quiet:
            self.hide()
        frame = 1.0 / STEPS_PER_SECOND
        for px, py in glide_points(start, (x, y), seconds):
            if check:
                check()
            if quiet:
                self._position = (px, py)
            else:
                self.move(px, py, quiet_checked=True)
            if seconds > 0:
                time.sleep(frame)

    def hide(self) -> None:
        if self._hwnd:
            import ctypes
            ctypes.windll.user32.ShowWindow(self._hwnd, 0)

    @property
    def position(self) -> tuple[int, int] | None:
        return self._position

    # -- internals -------------------------------------------------------

    def _entry_point(self, x: int, y: int) -> tuple[int, int]:
        # First appearance: come in from a little below and to the right of
        # the target, so there is a visible approach rather than a pop-in.
        return (x + 140, y + 110)

    def _schedule_hide(self) -> None:
        if self._hide_timer:
            self._hide_timer.cancel()
        self._hide_timer = threading.Timer(IDLE_HIDE_S, self.hide)
        self._hide_timer.daemon = True
        self._hide_timer.start()

    def _image(self):
        """The arrow and its tag, as premultiplied BGRA bytes."""
        from PIL import Image, ImageDraw, ImageFont
        width, height = 92, 40
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        arrow = [(2, 2), (2, 25), (8, 19), (12.5, 29), (16.5, 27.5), (12, 18), (20, 18)]
        # Soft shadow, then the emerald arrow with a white rim.
        draw.polygon([(px + 1.5, py + 1.5) for px, py in arrow], fill=(0, 0, 0, 90))
        draw.polygon(arrow, fill=(*EMERALD, 255), outline=(255, 255, 255, 255))
        try:
            font = ImageFont.truetype("segoeuib.ttf", 11)
        except Exception:  # noqa: BLE001
            font = ImageFont.load_default()
        draw.rounded_rectangle((22, 20, 64, 36), radius=8, fill=(*EMERALD, 245))
        draw.text((30, 21), "Nova", fill=(6, 32, 24, 255), font=font)
        # UpdateLayeredWindow wants premultiplied alpha, in BGRA order.
        pixels = bytearray()
        for r, g, b, a in image.getdata():
            pixels += bytes((b * a // 255, g * a // 255, r * a // 255, a))
        return width, height, bytes(pixels)

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes
        try:
            user32, gdi32, kernel32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
            LRESULT = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
            user32.DefWindowProcW.restype = LRESULT
            user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            gdi32.CreateCompatibleDC.restype = wintypes.HDC
            gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
            gdi32.CreateDIBSection.restype = wintypes.HBITMAP
            gdi32.SelectObject.restype = wintypes.HGDIOBJ
            gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
            user32.GetDC.restype = wintypes.HDC
            user32.GetDC.argtypes = [wintypes.HWND]
            user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
            # Every handle-typed argument declared: left to guess, ctypes packs
            # an HDC as a C int and 64-bit handles overflow it (the same trap
            # cursor.py's ring code documents).
            user32.UpdateLayeredWindow.argtypes = [
                wintypes.HWND, wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p, wintypes.HDC,
                ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
            user32.UpdateLayeredWindow.restype = wintypes.BOOL
            user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
            user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint]
            user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.DispatchMessageW.restype = LRESULT

            proc = WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))

            class WNDCLASS(ctypes.Structure):
                _fields_ = [
                    ("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
                ]

            instance = kernel32.GetModuleHandleW(None)
            cls = WNDCLASS()
            cls.lpfnWndProc = proc
            cls.hInstance = instance
            cls.lpszClassName = "NovaPointer"
            user32.RegisterClassW(ctypes.byref(cls))
            self._keep_alive = (proc, cls)

            width, height, pixels = self._image()
            self._size = (width, height)
            self._hotspot = (2, 2)  # the arrow's tip

            WS_POPUP = 0x80000000
            ex = (0x00080000 | 0x00000020 | 0x00000080 | 0x00000008 | 0x08000000)
            # LAYERED | TRANSPARENT (click-through) | TOOLWINDOW | TOPMOST | NOACTIVATE
            hwnd = user32.CreateWindowExW(ex, "NovaPointer", "Nova pointer", WS_POPUP,
                                          0, 0, width, height, None, None, instance, None)
            if not hwnd:
                raise OSError("CreateWindowExW failed")

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                            ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                            ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                            ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                            ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

            header = BITMAPINFOHEADER()
            header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            header.biWidth, header.biHeight = width, -height  # top-down rows
            header.biPlanes, header.biBitCount = 1, 32
            bits = ctypes.c_void_p()
            screen = user32.GetDC(None)
            memory = gdi32.CreateCompatibleDC(screen)
            gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, ctypes.c_uint,
                                               ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
            bitmap = gdi32.CreateDIBSection(memory, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
            ctypes.memmove(bits, pixels, len(pixels))
            gdi32.SelectObject(memory, bitmap)

            class SIZE(ctypes.Structure):
                _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

            class BLEND(ctypes.Structure):
                _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                            ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_byte)]

            size = SIZE(width, height)
            origin = wintypes.POINT(0, 0)
            blend = BLEND(0, 0, 255, 1)  # AC_SRC_OVER, per-pixel AC_SRC_ALPHA
            user32.UpdateLayeredWindow(hwnd, screen, None, ctypes.byref(size), memory,
                                       ctypes.byref(origin), 0, ctypes.byref(blend), 2)  # ULW_ALPHA
            user32.ReleaseDC(None, screen)

            # Ctrl+Alt+Esc, thread-level (no window), no auto-repeat.
            self.hotkey_registered = bool(user32.RegisterHotKey(None, 0x4E4F, 0x0002 | 0x0001 | 0x4000, 0x1B))
            if not self.hotkey_registered:
                logger.warning("Could not register %s as Nova's stop key -- another app owns it.", HOTKEY_LABEL)

            self._thread_id = kernel32.GetCurrentThreadId()
            self._hwnd = hwnd
        except Exception:  # noqa: BLE001 -- the pointer is decoration; say so and carry on
            logger.exception("Nova's pointer could not be created")
            self._ready.set()
            return
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312 and msg.wParam == 0x4E4F:  # WM_HOTKEY
                for listener in list(self._stop_listeners):
                    try:
                        listener()
                    except Exception:  # noqa: BLE001
                        logger.exception("Stop listener failed")
                continue
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


class _OverlayPointer(_Pointer):
    """macOS and Linux: the same pointer, drawn by the desktop app.

    The glide, quiet mode and stop checks are _Pointer's own; only drawing
    differs. Each move is published as an event, and Electron's overlay window
    (frontend/electron/pointer-overlay) draws the arrow and its "Nova" tag
    click-through and on top, exactly as the Win32 window does."""

    def __init__(self) -> None:
        super().__init__()
        self._subscribers: list[queue.Queue] = []
        self._sub_lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=512)
        with self._sub_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._sub_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    @property
    def watched(self) -> bool:
        return bool(self._subscribers)

    def _publish(self, event: dict) -> None:
        with self._sub_lock:
            targets = list(self._subscribers)
        for q in targets:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass

    def start(self) -> bool:
        return True

    def move(self, x: int, y: int, *, quiet_checked: bool = False) -> None:
        if not quiet_checked and point_under_fullscreen(x, y):
            self.hide()
            return
        self._position = (x, y)
        self._publish({"t": "move", "x": int(x), "y": int(y)})
        self._schedule_hide()

    def hide(self) -> None:
        self._publish({"t": "hide"})

    def flash(self, x: int, y: int) -> None:
        """The click ring (cursor.flash on Windows)."""
        self._publish({"t": "flash", "x": int(x), "y": int(y)})


pointer = _Pointer() if _WINDOWS else _OverlayPointer()


# ---------------------------------------------------------------- stopping

_hotkey_pressed_at = 0.0


def _on_hotkey() -> None:
    global _hotkey_pressed_at
    _hotkey_pressed_at = time.monotonic()
    try:
        from . import operator_workflows
        operator_workflows.stop(f"Stopped with {HOTKEY_LABEL}. Resume from the operator controls.")
    except Exception:  # noqa: BLE001
        logger.exception("Could not record the stop")


pointer.on_stop(_on_hotkey)


class Watch:
    """Armed for one action. `check()` raises Stopped if, since arming, the
    hotkey was pressed, the user's real mouse reached a corner, or Nova was
    stopped from the UI. Cheap enough to call on every glide step."""

    def __init__(self) -> None:
        self.armed_at = time.monotonic()
        self._monitors = _monitors()
        self._n = 0

    def check(self) -> None:
        if _hotkey_pressed_at >= self.armed_at:
            raise Stopped(f"Stopped: you pressed {HOTKEY_LABEL}. Nothing more was done.")
        try:
            if _WINDOWS:
                import win32api
                where = win32api.GetCursorPos()
            else:
                from . import desktop_os
                where = desktop_os.cursor_pos()
            if in_corner(where, self._monitors):
                try:
                    from . import operator_workflows
                    operator_workflows.stop("Stopped: your mouse went into a screen corner.")
                except Exception:  # noqa: BLE001
                    pass
                raise Stopped("Stopped: your mouse went into a screen corner, which is the abort gesture. "
                              "Nothing more was done.")
        except Stopped:
            raise
        except Exception:  # noqa: BLE001 -- no win32api: the hotkey and Stop button still work
            pass
        self._n += 1
        if self._n % 15 == 0:
            from . import operator_workflows
            if operator_workflows.stopped():
                raise Stopped("Stopped from the operator controls. Nothing more was done.")


def press_stop_key(label: str | None = None) -> None:
    """The desktop app's global shortcut was pressed (macOS and Linux)."""
    global HOTKEY_LABEL
    if label:
        HOTKEY_LABEL = label
    _on_hotkey()


def set_hotkey_label(label: str) -> None:
    """Which stop key the desktop app managed to register."""
    global HOTKEY_LABEL
    if label:
        HOTKEY_LABEL = label
