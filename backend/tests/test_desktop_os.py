"""The macOS/Linux desktop layer's logic that doesn't need a real screen, and
the shape every system's pieces agree on."""
import sys

import pytest

from app import desktop_os, nova_pointer, uia

WINDOWS = [
    {"hwnd": 1, "title": "Game", "process": "game", "pid": 10, "rect": (0, 0, 1920, 1080), "active": True, "maybe_unsaved": False},
    {"hwnd": 2, "title": "Notes", "process": "notes", "pid": 11, "rect": (100, 100, 700, 600), "active": False, "maybe_unsaved": False},
]


@pytest.fixture()
def fake_screen(monkeypatch):
    monkeypatch.setattr(desktop_os, "list_windows", lambda: [dict(w) for w in WINDOWS], raising=False)
    monkeypatch.setattr(desktop_os, "monitors", lambda: [(0, 0, 1920, 1080), (1920, 0, 3840, 1080)], raising=False)


def test_fullscreen_app_is_the_active_window_covering_its_monitor(fake_screen):
    app = desktop_os.fullscreen_app()
    assert app["title"] == "Game" and app["monitor"] == (0, 0, 1920, 1080)


def test_no_fullscreen_when_the_active_window_is_smaller(fake_screen, monkeypatch):
    windows = [dict(WINDOWS[1], active=True), dict(WINDOWS[0], active=False)]
    monkeypatch.setattr(desktop_os, "list_windows", lambda: windows, raising=False)
    assert desktop_os.fullscreen_app() is None


def test_window_at_picks_the_frontmost_window_containing_the_point(fake_screen):
    assert desktop_os.window_at(150, 150)["title"] == "Game"  # front to back: the game covers it
    assert desktop_os.window_at(3000, 500) is None
    assert desktop_os.window(2)["title"] == "Notes"
    assert desktop_os.active_window()["hwnd"] == 1


def test_overlay_pointer_publishes_moves_flashes_and_hides(monkeypatch):
    monkeypatch.setattr(nova_pointer, "point_under_fullscreen", lambda x, y: None)
    p = nova_pointer._OverlayPointer()
    q = p.subscribe()
    p.glide(300, 200, 0.05)
    p.flash(300, 200)
    p.hide()
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert events[-1] == {"t": "hide"} and events[-2] == {"t": "flash", "x": 300, "y": 200}
    moves = [e for e in events if e["t"] == "move"]
    assert moves[-1] == {"t": "move", "x": 300, "y": 200}
    p.unsubscribe(q)
    assert not p.watched


def test_overlay_pointer_stays_off_a_fullscreen_monitor(monkeypatch):
    monkeypatch.setattr(nova_pointer, "point_under_fullscreen", lambda x, y: {"title": "Game"})
    p = nova_pointer._OverlayPointer()
    q = p.subscribe()
    p.move(10, 10)
    assert q.get_nowait() == {"t": "hide"} and q.empty()


def test_stop_key_from_the_desktop_app_stops_an_action_in_flight(monkeypatch):
    monkeypatch.setattr(nova_pointer, "_monitors", lambda: [])
    stopped = []
    import app.operator_workflows as ow
    monkeypatch.setattr(ow, "stop", lambda reason: stopped.append(reason))
    watch = nova_pointer.Watch()
    nova_pointer.press_stop_key("Ctrl+Alt+Shift+Esc")
    with pytest.raises(nova_pointer.Stopped) as info:
        watch.check()
    assert "Ctrl+Alt+Shift+Esc" in str(info.value) and stopped
    nova_pointer.set_hotkey_label("Ctrl+Alt+Esc")


def test_accessibility_entries_match_across_systems():
    """ax_mac and ax_linux hand back the same verbs uia.py does."""
    import importlib
    for name in ("app.ax_mac", "app.ax_linux"):
        module = importlib.import_module(name)
        for fn in ("controls_sync", "act_sync", "act_at_sync", "act_on"):
            assert callable(getattr(module, fn)), (name, fn)
        assert set(module.ROLES.values()) <= uia.ACTIONABLE | uia.READABLE | {"element"}


@pytest.mark.skipif(sys.platform == "win32", reason="uia.py is UI Automation itself on Windows")
def test_uia_answers_through_the_platform_module_elsewhere():
    assert uia.AVAILABLE and uia._platform().__name__ in ("app.ax_mac", "app.ax_linux")
