"""Hidden/visible browser toggle and which browsers Nova can drive."""
import asyncio
import json
import types

import pytest

from app import browser_control as bc, coursework_queue, onyx


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    for name, value in (("_driver", None), ("_browser", None), ("_page", None), ("_current_channel", None),
                        ("_current_headless", None), ("_launch_note", None)):
        monkeypatch.setattr(bc, name, value)


def settings(monkeypatch, **values):
    from app import db

    async def get_app_settings():
        return dict(values)
    monkeypatch.setattr(db, "get_app_settings", get_app_settings)


@pytest.mark.parametrize("name,expected", [
    ("Chrome", "chrome"), ("google chrome", "chrome"), ("edge", "msedge"), ("msedge", "msedge"),
    ("Opera GX", "operagx"), ("operagx", "operagx"), ("opera", "opera"), ("Brave", "brave"),
    ("vivaldi", "vivaldi"), ("firefox", "firefox"), ("safari", "webkit"), ("arc", "arc"),
    ("chromium", "chromium"), ("onyx", "onyx"), ("", None), ("netscape", None),
])
def test_browser_names_are_normalized(name, expected):
    assert bc.normalize_browser(name) == expected


@pytest.mark.parametrize("mode,expected", [
    ("visible", "visible"), ("hidden", "hidden"), ("silent", "hidden"), ("headless", "hidden"), (None, "hidden"),
])
def test_visibility_setting(monkeypatch, mode, expected):
    monkeypatch.delenv("NOVA_BROWSER_HEADLESS", raising=False)
    settings(monkeypatch, **({"browser_visibility_mode": mode} if mode else {}))
    assert asyncio.run(bc.visibility()) == expected


def _endpoints(tmp_path, monkeypatch, main_alive):
    root = tmp_path / "onyx"
    root.mkdir()
    (root / "agent-endpoint.json").write_text(json.dumps({"pid": 111}))
    (root / "agent-endpoint-nova.json").write_text(json.dumps({"pid": 222}))
    monkeypatch.setattr(onyx, "_appdata", lambda: tmp_path)
    monkeypatch.setattr(onyx, "_pid_alive", lambda pid: main_alive and pid == 111)


def test_hidden_drives_novas_own_onyx_window_even_when_the_users_is_open(tmp_path, monkeypatch):
    _endpoints(tmp_path, monkeypatch, main_alive=True)
    onyx.set_visibility("hidden")
    assert onyx.endpoint_path().name == "agent-endpoint-nova.json"


def test_visible_drives_the_users_open_onyx_window(tmp_path, monkeypatch):
    _endpoints(tmp_path, monkeypatch, main_alive=True)
    onyx.set_visibility("visible")
    try:
        assert onyx.endpoint_path().name == "agent-endpoint.json"
    finally:
        onyx.set_visibility("hidden")


def test_visible_uses_novas_window_when_the_users_is_closed(tmp_path, monkeypatch):
    _endpoints(tmp_path, monkeypatch, main_alive=False)
    assert onyx.endpoint_path("visible").name == "agent-endpoint-nova.json"


def test_perform_passes_the_toggle_to_onyx_and_labels_the_result(monkeypatch):
    seen = {}

    async def backend():
        return "onyx", ""

    async def visible():
        return "visible"

    async def fake_onyx(*a, **k):
        seen["mode"] = onyx._visibility
        return {"url": "https://a.test/"}
    monkeypatch.setattr(bc, "_backend", backend)
    monkeypatch.setattr(bc, "visibility", visible)
    monkeypatch.setattr(bc, "_perform_onyx", fake_onyx)
    try:
        result = asyncio.run(bc.perform("navigate", url="https://a.test/"))
    finally:
        onyx.set_visibility("hidden")
    assert seen["mode"] == "visible"
    assert result["browser"] == "onyx" and result["visibility"] == "visible"


class FakeContext:
    def __init__(self, label):
        self.label = label
        self.pages = []
        self.browser = None
        self.closed = False

    async def new_page(self):
        return types.SimpleNamespace(set_default_timeout=lambda _: None, is_closed=lambda: False)

    async def close(self):
        self.closed = True


class FakeDriver:
    """Records launches; `installed` is what would actually start."""
    def __init__(self, installed):
        self.installed = installed
        self.launches = []
        driver = self

        class Engine:
            def __init__(self, engine):
                self.engine = engine

            async def launch_persistent_context(self, profile, **kw):
                label = kw.get("channel") or kw.get("executable_path") or self.engine
                driver.launches.append((label, kw.get("headless")))
                if label not in driver.installed:
                    raise RuntimeError(f"{label} not installed")
                return FakeContext(label)
        self.chromium, self.firefox, self.webkit = Engine("chromium"), Engine("firefox"), Engine("webkit")


def _fake_playwright(monkeypatch, installed, mode="hidden", exes=None):
    driver = FakeDriver(installed)
    monkeypatch.setattr(bc, "_driver", driver)
    monkeypatch.setattr(bc, "_alive", lambda ctx: isinstance(ctx, FakeContext) and not ctx.closed)
    monkeypatch.setattr(bc, "_profile_dir", lambda ch=None: f"profile-{ch}")
    monkeypatch.setattr(bc, "_find_browser_exe", lambda name: (exes or {}).get(name))

    async def vis():
        return mode
    monkeypatch.setattr(bc, "visibility", vis)
    return driver


def test_requested_browser_launches_with_the_toggle(monkeypatch):
    driver = _fake_playwright(monkeypatch, {"msedge"}, mode="visible")
    asyncio.run(bc.page(channel="edge"))
    assert driver.launches == [("msedge", False)]
    assert bc._current_channel == "msedge" and bc._launch_note is None


def test_missing_browser_falls_back_and_says_so(monkeypatch):
    driver = _fake_playwright(monkeypatch, {"chrome"})
    asyncio.run(bc.page(channel="brave"))
    assert bc._current_channel == "chrome"
    assert "Brave could not be started" in bc._launch_note and "Google Chrome" in bc._launch_note


def test_chromium_family_browsers_launch_from_their_executable(monkeypatch):
    driver = _fake_playwright(monkeypatch, {"C:/Vivaldi/vivaldi.exe"}, exes={"vivaldi": "C:/Vivaldi/vivaldi.exe"})
    asyncio.run(bc.page(channel="vivaldi"))
    assert driver.launches == [("C:/Vivaldi/vivaldi.exe", True)]


def test_firefox_uses_playwrights_build_not_the_installed_exe(monkeypatch):
    driver = _fake_playwright(monkeypatch, {"firefox"}, exes={"firefox": "C:/Mozilla/firefox.exe"})
    asyncio.run(bc.page(channel="firefox"))
    assert driver.launches == [("firefox", True)]


def test_changing_the_toggle_relaunches_the_open_browser(monkeypatch):
    driver = _fake_playwright(monkeypatch, {"chrome"}, mode="hidden")
    asyncio.run(bc.page(channel="chrome"))
    first = bc._browser

    async def visible():
        return "visible"
    monkeypatch.setattr(bc, "visibility", visible)
    asyncio.run(bc.page(channel="chrome"))
    assert first.closed and driver.launches == [("chrome", True), ("chrome", False)]


def test_nothing_launchable_is_a_clear_error(monkeypatch):
    _fake_playwright(monkeypatch, set())
    with pytest.raises(RuntimeError, match="No browser could be started"):
        asyncio.run(bc.page(channel="chrome"))


def test_support_listing_reports_every_browser_and_the_choice(monkeypatch):
    settings(monkeypatch, browser_backend="onyx", preferred_browser="Brave", browser_visibility_mode="visible")
    monkeypatch.setattr(bc, "_find_browser_exe", lambda name: "C:/x.exe" if name == "brave" else None)
    monkeypatch.setattr(bc, "_playwright_bundle", lambda prefix: prefix == "firefox")
    monkeypatch.setattr(onyx, "find_exe", lambda configured="": None)
    info = asyncio.run(bc.browser_support())
    rows = {r["id"]: r for r in info["browsers"]}
    assert set(rows) == set(bc.BROWSERS)
    assert rows["brave"]["available"] and not rows["chrome"]["available"]
    assert rows["firefox"]["available"] and not rows["webkit"]["available"] and not rows["onyx"]["available"]
    assert info["preferred_browser"] == "brave" and info["visibility"] == "visible"


def test_queues_accept_any_playwright_browser_and_default_to_settings(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "nova.db")
    url = "https://fixture.test/courses/1/assignments/1"
    assert coursework_queue.create_queue([{"url": url}], account_id="7", authorize_submission=True)["browser"] is None
    assert coursework_queue.create_queue([{"url": url}], account_id="7", authorize_submission=True,
                                         browser="Brave")["browser"] == "brave"
    for bad in ("onyx", "netscape"):
        with pytest.raises(ValueError, match="Choose a browser"):
            coursework_queue.create_queue([{"url": url}], account_id="7", authorize_submission=True, browser=bad)


def test_autopilot_defaults_to_the_settings_browser():
    import inspect
    from app import coursework_autopilot as pilot
    assert inspect.signature(pilot.run_autopilot_assignment).parameters["browser_channel"].default is None
    assert inspect.signature(pilot.run_autopilot_queue).parameters["browser"].default is None


def test_appearance_mode_setting_accepts_day_night_auto_only():
    from pydantic import ValidationError
    from app.schemas import AppSettingsUpdateRequest
    for mode in ("day", "night", "auto"):
        assert AppSettingsUpdateRequest(appearance_mode=mode).appearance_mode == mode
    with pytest.raises(ValidationError):
        AppSettingsUpdateRequest(appearance_mode="sepia")


def test_color_palette_presets_and_custom_colors():
    from pydantic import ValidationError
    from app.schemas import AppSettingsUpdateRequest
    for name in ("grove", "fern", "moss", "dusk", "ember", "glacier", "custom"):
        assert AppSettingsUpdateRequest(color_palette=name).color_palette == name
    ok = AppSettingsUpdateRequest(custom_palette="#7FD1A8,#D4E7A1,#1E5B45")
    assert ok.custom_palette == "#7FD1A8,#D4E7A1,#1E5B45"
    for bad in ("neon", ):
        with pytest.raises(ValidationError):
            AppSettingsUpdateRequest(color_palette=bad)
    for bad in ("#7FD1A8,#D4E7A1", "red,green,blue", "#7FD1A8,#D4E7A1,#1E5B45,#000000", "#7FD1A8,#D4E7A1,#1E5B4Z"):
        with pytest.raises(ValidationError):
            AppSettingsUpdateRequest(custom_palette=bad)
