"""Nova using a real app on a real desktop, end to end.

Runs only where a desktop is there to use: set NOVA_LIVE_DESKTOP=1. CI does
this on Linux (Xvfb, a window manager and the accessibility bus; see
.github/workflows/ci.yml) and on macOS. On Windows the same paths are covered
by the win32 tests.

Linux: a zenity dialog -- find its window, read its controls through AT-SPI,
fill the field, type into it with XTest, press OK, and check the app got
exactly that text back.
"""
import asyncio
import os
import shutil
import subprocess
import sys
import time

import pytest

LIVE = os.environ.get("NOVA_LIVE_DESKTOP") == "1"
pytestmark = pytest.mark.skipif(not LIVE, reason="needs a real desktop (NOVA_LIVE_DESKTOP=1)")


def _wait_for(predicate, seconds=15.0, step=0.25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return None


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux desktop")
def test_linux_nova_uses_a_real_app():
    from app import desktop, desktop_os, uia

    assert shutil.which("zenity"), "CI installs zenity"
    dialog = subprocess.Popen(["zenity", "--entry", "--title", "Nova live test", "--text", "Your name"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        window = _wait_for(lambda: next((w for w in desktop_os.list_windows() if w["title"] == "Nova live test"), None))
        assert window, f"window never appeared: {desktop_os.list_windows()}"
        assert window["pid"] == dialog.pid and window["process"]

        # Screen and window pictures.
        shot = asyncio.run(desktop.capture_screenshot())
        assert shot[:8] == b"\x89PNG\r\n\x1a\n"
        image = desktop.capture_window(window["hwnd"])
        assert image is not None and image.width > 50

        # The window under a point inside it is this one.
        left, top, right, bottom = window["rect"]
        assert desktop_os.window_at((left + right) // 2, (top + bottom) // 2)["hwnd"] == window["hwnd"]

        # Its controls, through AT-SPI.
        controls = _wait_for(lambda: [c for c in asyncio.run(uia.controls(window["hwnd"])) if c["type"] in ("edit", "button")])
        assert controls, "no controls read"
        kinds = {c["type"] for c in controls}
        assert "edit" in kinds and "button" in kinds, controls
        print(uia.describe(controls))

        # Fill the field by name, with characters no keyboard layout has.
        field = next(c for c in controls if c["type"] == "edit")
        result = asyncio.run(uia.act(window["hwnd"], ref=field["ref"], action="type", text="Zoë ✓"))
        assert result["how"] == "set its value"
        again = asyncio.run(uia.controls(window["hwnd"]))
        assert next(c for c in again if c["type"] == "edit").get("value") == "Zoë ✓"

        # Refuses to overwrite what's there unless told to.
        with pytest.raises(uia.UiaError):
            asyncio.run(uia.act(window["hwnd"], ref=field["ref"], action="type", text="x"))

        # Real keystrokes into the focused field (XTest, including a remapped key).
        asyncio.run(uia.act(window["hwnd"], ref=field["ref"], action="type", text="", replace=True))
        desktop_os.activate(window["hwnd"])
        time.sleep(0.4)
        desktop_os.type_unicode("Ana ñ", lambda: None)
        typed = _wait_for(lambda: next((c.get("value") for c in asyncio.run(uia.controls(window["hwnd"]))
                                        if c["type"] == "edit" and c.get("value")), None), seconds=5)
        assert typed == "Ana ñ", typed

        # Press OK by name: the app answers with the text it held.
        asyncio.run(uia.act(window["hwnd"], name="OK", action="press"))
        out, _err = dialog.communicate(timeout=10)
        assert out.strip() == "Ana ñ"
    finally:
        if dialog.poll() is None:
            dialog.kill()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux desktop")
def test_linux_close_and_open_by_name():
    from app import desktop, desktop_os

    dialog = subprocess.Popen(["zenity", "--info", "--title", "Nova close test", "--text", "Close me"])
    try:
        window = _wait_for(lambda: next((w for w in desktop_os.list_windows() if w["title"] == "Nova close test"), None))
        assert window
        assert desktop_os.close(window["hwnd"])
        assert dialog.wait(timeout=10) is not None
    finally:
        if dialog.poll() is None:
            dialog.kill()
    result = asyncio.run(desktop.open_app("zenity"))
    assert result["path"] == "zenity"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS desktop")
def test_macos_windows_screen_and_permissions():
    from app import desktop, desktop_os, uia

    subprocess.run(["open", "-a", "TextEdit"], check=True)
    try:
        windows = _wait_for(lambda: [w for w in desktop_os.list_windows() if w["process"] == "TextEdit"], seconds=20)
        print("windows:", desktop_os.list_windows())
        print("permissions:", desktop_os.permissions())
        assert desktop_os.monitors()
        assert isinstance(desktop_os.cursor_pos(), tuple)
        shot = asyncio.run(desktop.capture_screenshot())
        assert shot[:8] == b"\x89PNG\r\n\x1a\n"
        if not windows:
            pytest.skip("TextEdit's window is not listed on this runner")
        image = desktop_os.capture(windows[0]["hwnd"])
        print("window image:", image and image.size)
        if desktop_os.permissions()["accessibility"]:
            controls = asyncio.run(uia.controls(windows[0]["hwnd"]))
            print(uia.describe(controls))
            assert controls
        else:
            with pytest.raises(uia.UiaError, match="Accessibility"):
                asyncio.run(uia.controls(windows[0]["hwnd"]))
    finally:
        subprocess.run(["osascript", "-e", 'tell application "TextEdit" to quit saving no'], check=False)
