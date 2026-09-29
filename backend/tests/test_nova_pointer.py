"""Nova's own pointer: the geometry that decides where it goes, when it
hides, and when the user has asked it to stop. The window itself is checked
live (see the desktop cursor section of docs/plans)."""
from app import nova_pointer as np, uia


def test_glide_lands_exactly_on_the_target():
    points = np.glide_points((0, 0), (400, 300), 0.45)
    assert points[-1] == (400, 300)
    assert len(points) == int(0.45 * np.STEPS_PER_SECOND)


def test_glide_is_a_single_jump_when_instant_or_already_there():
    assert np.glide_points((0, 0), (5, 5), 0) == [(5, 5)]
    assert np.glide_points((5, 5), (5, 5), 0.5) == [(5, 5)]


def test_glide_bows_but_not_wildly():
    points = np.glide_points((0, 0), (2000, 0), 0.5)
    worst = max(abs(y) for _, y in points)
    assert 0 < worst <= 61


MONITORS = [(0, 0, 1920, 1080), (-1920, -1080, 0, 0)]


def test_corners_of_every_monitor_count():
    assert np.in_corner((0, 0), MONITORS)
    assert np.in_corner((1919, 1079), MONITORS)
    assert np.in_corner((-1920, -1080), MONITORS)
    assert np.in_corner((-1, -1), MONITORS)


def test_edges_and_middles_do_not():
    assert not np.in_corner((960, 0), MONITORS)
    assert not np.in_corner((0, 540), MONITORS)
    assert not np.in_corner((960, 540), MONITORS)


def test_a_fullscreen_game_covers_its_monitor():
    assert np.covers_monitor((0, 0, 1920, 1080), (0, 0, 1920, 1080), "UnityWndClass")
    assert np.covers_monitor((-8, -8, 1928, 1088), (0, 0, 1920, 1080), "Chrome_WidgetWin_1")


def test_a_maximised_window_leaves_the_taskbar_and_does_not():
    assert not np.covers_monitor((0, 0, 1920, 1040), (0, 0, 1920, 1080), "Notepad")


def test_the_desktop_and_taskbar_are_not_fullscreen_apps():
    assert not np.covers_monitor((0, 0, 1920, 1080), (0, 0, 1920, 1080), "Progman")
    assert not np.covers_monitor((0, 0, 1920, 1080), (0, 0, 1920, 1080), "WorkerW")


# ---------------------------------------------------------------- uia matching

CONTROLS = [
    {"ref": 0, "type": "text", "name": "Save", "can": []},
    {"ref": 1, "type": "button", "name": "Save As...", "can": ["press"]},
    {"ref": 2, "type": "button", "name": "Save", "can": ["press"]},
    {"ref": 3, "type": "button", "name": "Don't save", "can": ["press"], "offscreen": True},
]


def test_names_match_the_actionable_control_before_a_label():
    assert uia.match_by_name(CONTROLS, "save")["ref"] == 2


def test_a_partial_name_picks_the_shortest_containing_it():
    assert uia.match_by_name(CONTROLS, "save as")["ref"] == 1


def test_no_match_is_none_not_a_guess():
    assert uia.match_by_name(CONTROLS, "Delete everything") is None
    assert uia.match_by_name(CONTROLS, "   ") is None


def test_describe_lists_what_each_control_can_do_and_never_a_secret():
    text = uia.describe([
        {"ref": 0, "type": "button", "name": "OK", "can": ["press"]},
        {"ref": 1, "type": "edit", "name": "Password", "can": ["type"], "secret": True},
        {"ref": 2, "type": "checkbox", "name": "Remember", "can": ["toggle"], "toggled": True},
    ])
    assert '[0] button "OK" (press)' in text
    assert '[2] checkbox "Remember" [on] (toggle)' in text
    assert "value" not in text.split("\n")[1]


# ---------------------------------------------------------------- the click ladder
#
# desktop._own_click with every Windows touchpoint mocked: nothing here may
# reach the real screen, the real accessibility tree or the real mouse.

import asyncio
from unittest import mock

from app import cursor, desktop, nova_pointer

OWN = {"seconds": 0.0, "marker": False, "pointer": "own", "borrow": "ask"}


class _NoWatch:
    def check(self):
        pass


def _run_own(**over):
    """Run desktop.click on Nova's own pointer with the environment faked.
    `over` sets what UIA returns, whether the window changes, etc."""
    style = {**OWN, **over.pop("style", {})}

    async def fake_style():
        return style

    calls = {"posted": 0, "real_click": 0, "restored": None}

    def fake_post(*a, **k):
        calls["posted"] += 1

    def fake_real_click(**k):
        calls["real_click"] += 1

    patches = [
        mock.patch.object(desktop, "click_style", fake_style),
        mock.patch.object(desktop, "screen_origin", return_value=(0, 0)),
        mock.patch.object(nova_pointer, "point_under_fullscreen", return_value=over.pop("fullscreen", None)),
        mock.patch.object(nova_pointer, "Watch", _NoWatch),
        mock.patch.object(nova_pointer, "fullscreen_app", return_value=None),
        mock.patch.object(nova_pointer.pointer, "glide"),
        mock.patch.object(cursor, "flash"),
        mock.patch.object(uia, "act_at_blocking", return_value=over.pop("uia", None)),
        mock.patch.object(desktop, "_top_window_at", return_value=over.pop("window", 1234)),
        mock.patch.object(desktop, "capture_window", return_value=None),
        mock.patch.object(desktop, "images_differ", return_value=over.pop("changed", False)),
        mock.patch.object(desktop, "_post_click", side_effect=fake_post),
        mock.patch.object(desktop.time, "sleep"),
    ]
    if desktop.pyautogui is not None:
        patches.append(mock.patch.object(desktop.pyautogui, "click", side_effect=fake_real_click))
    import win32api
    patches += [
        mock.patch.object(win32api, "GetCursorPos", return_value=(7, 7)),
        mock.patch.object(win32api, "SetCursorPos", side_effect=lambda p: calls.__setitem__("restored", p)),
        mock.patch.object(desktop.win32gui, "GetWindowText", return_value="Some App"),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(desktop.click(100, 200, borrow_mouse=over.pop("borrow_mouse", False)))
        return result, calls
    finally:
        for p in reversed(patches):
            p.stop()


def test_ui_automation_lands_it_without_the_real_mouse():
    result, calls = _run_own(uia={"control": 'button "Save"', "how": "pressed it"})
    assert result["how"] == "UI Automation pressed it"
    assert result["clicked"] == 'button "Save"'
    assert calls["posted"] == 0 and calls["real_click"] == 0


def test_a_click_message_counts_only_when_the_window_changed():
    result, calls = _run_own(changed=True)
    assert "click message" in result["how"]
    assert calls["real_click"] == 0


def test_an_unverified_message_asks_to_borrow_rather_than_claiming_success():
    import pytest
    with pytest.raises(desktop.DesktopActionError, match="borrow their mouse.*Nothing was clicked"):
        _run_own(changed=False)


def test_borrowing_happens_only_with_permission_and_puts_the_mouse_back():
    result, calls = _run_own(changed=False, borrow_mouse=True)
    assert calls["real_click"] == 1
    assert calls["restored"] == (7, 7)
    assert "borrowed" in result["how"]


def test_never_means_never_even_with_permission():
    import pytest
    with pytest.raises(desktop.DesktopActionError, match="switched off"):
        _run_own(changed=False, borrow_mouse=True, style={"borrow": "never"})


def test_it_refuses_to_click_into_a_fullscreen_game():
    import pytest
    game = {"title": "Elden Ring", "process": "eldenring.exe", "hwnd": 1, "monitor": (0, 0, 1920, 1080)}
    with pytest.raises(desktop.DesktopActionError, match="Elden Ring is fullscreen"):
        _run_own(fullscreen=game)


def test_keys_are_refused_while_a_game_has_focus_unless_named():
    import pytest
    game = {"title": "Elden Ring", "process": "eldenring.exe"}
    with mock.patch.object(nova_pointer, "fullscreen_app", return_value=game):
        with pytest.raises(desktop.DesktopActionError, match="fullscreen and has the keyboard"):
            desktop.refuse_if_fullscreen_focused(None, "type")
        desktop.refuse_if_fullscreen_focused("elden", "type")  # named on purpose: allowed
    with mock.patch.object(nova_pointer, "fullscreen_app", return_value=None):
        desktop.refuse_if_fullscreen_focused(None, "type")


def test_control_refs_and_names_are_told_apart():
    assert desktop._control_ref("12") == (12, None)
    assert desktop._control_ref("[3]") == (3, None)
    assert desktop._control_ref("Save") == (None, "Save")


def test_images_differ_ignores_a_blinking_caret_but_sees_a_real_change():
    from PIL import Image, ImageDraw
    before = Image.new("RGB", (400, 300), "white")
    caret = before.copy()
    ImageDraw.Draw(caret).line((10, 10, 10, 22), fill="black")
    dialog = before.copy()
    ImageDraw.Draw(dialog).rectangle((50, 50, 350, 250), fill="gray")
    assert not desktop.images_differ(before, caret)
    assert desktop.images_differ(before, dialog)
    assert not desktop.images_differ(None, dialog)


def test_focus_stolen_from_a_fullscreen_app_is_handed_back():
    """Found live: pressing a UWP app's button through UI Automation activates
    it, which pulled a fullscreen window out from under the user."""
    game = {"hwnd": 1, "title": "Elden Ring"}
    with mock.patch.object(desktop.win32gui, "GetForegroundWindow", return_value=2), \
         mock.patch.object(desktop.win32gui, "GetWindowText", return_value="Calculator"), \
         mock.patch.object(desktop, "_force_foreground", return_value=True) as restore:
        note = desktop.keep_fullscreen_in_front(game)
    restore.assert_called_once_with(1)
    assert "handed focus straight back to Elden Ring" in note


def test_nothing_to_hand_back_when_focus_never_moved():
    with mock.patch.object(desktop.win32gui, "GetForegroundWindow", return_value=1), \
         mock.patch.object(desktop, "_force_foreground") as restore:
        assert desktop.keep_fullscreen_in_front({"hwnd": 1, "title": "x"}) is None
        assert desktop.keep_fullscreen_in_front(None) is None
    restore.assert_not_called()



def test_it_asks_before_pressing_in_an_app_that_jumps_forward_during_a_game():
    import pytest
    game = {"hwnd": 1, "title": "Elden Ring", "process": "eldenring.exe"}
    with mock.patch.object(desktop, "jumps_forward", return_value=True), \
         mock.patch.object(desktop.win32gui, "GetWindowText", return_value="Calculator"):
        with pytest.raises(desktop.DesktopActionError, match="pull the user out of it.*allow_focus_change"):
            desktop.guard_focus(2, game, allow_focus_change=False)
        desktop.guard_focus(2, game, allow_focus_change=True)   # they said yes
        desktop.guard_focus(2, None, allow_focus_change=False)  # nothing fullscreen: no question


def test_uwp_windows_are_known_to_jump_forward():
    with mock.patch.object(desktop.win32gui, "GetClassName", return_value="ApplicationFrameWindow"):
        assert desktop.jumps_forward(5)


def test_an_app_seen_stealing_focus_is_remembered():
    saved = {}
    with mock.patch("app.operator_store.get", side_effect=lambda k, i: saved.get(i)), \
         mock.patch("app.operator_store.put", side_effect=lambda k, i, v: saved.__setitem__(i, v)):
        desktop._learn_activator("sneaky.exe")
        with mock.patch.object(desktop.win32gui, "GetClassName", return_value="Win32Class"), \
             mock.patch.object(desktop, "_process_of", return_value="sneaky.exe"):
            assert desktop.jumps_forward(7)



def test_typing_refuses_to_replace_existing_text_unless_asked():
    """Found live: a test opened Notepad, which restored one of the user's own
    documents, and app_type replaced its text wholesale."""
    import pytest

    class Value:
        CurrentValue = "the user's real notes"
        CurrentIsReadOnly = False

        def SetValue(self, text):
            raise AssertionError("must not write")

    class Element:
        CurrentIsPassword = False

    entry = {"ref": 0, "type": "document", "name": "Text editor", "enabled": True, "rect": [0, 0, 1, 1]}
    with mock.patch.object(uia, "_refs", {9: [Element()]}), \
         mock.patch.object(uia, "_entry", return_value=entry), \
         mock.patch.object(uia, "_pattern", return_value=Value()):
        with pytest.raises(uia.UiaError, match="already holds 21 characters.*Nothing was changed.*replace=true"):
            uia._act_sync(9, 0, None, "type", "new text")


def test_an_empty_field_is_filled_without_ceremony():
    written = []

    class Value:
        CurrentValue = ""
        CurrentIsReadOnly = False

        def SetValue(self, text):
            written.append(text)

    class Element:
        CurrentIsPassword = False

    entry = {"ref": 0, "type": "edit", "name": "Search", "enabled": True, "rect": [0, 0, 1, 1]}
    with mock.patch.object(uia, "_refs", {9: [Element()]}), \
         mock.patch.object(uia, "_entry", return_value=entry), \
         mock.patch.object(uia, "_pattern", return_value=Value()):
        uia._act_sync(9, 0, None, "type", "cats")
    assert written == ["cats"]


def _open_with(new_title, path="notepad.exe"):
    windows = [[], [{"hwnd": 5, "title": new_title, "active": True, "process": "Notepad.exe", "maybe_unsaved": False}]]
    calls = {"n": 0}

    def enum():
        calls["n"] += 1
        return windows[0] if calls["n"] == 1 else windows[1]

    with mock.patch.object(desktop, "_enum_windows", side_effect=enum), \
         mock.patch.object(nova_pointer, "fullscreen_app", return_value=None), \
         mock.patch.object(desktop.os, "startfile", create=True), \
         mock.patch.object(desktop, "OPEN_APP_POLL_SECONDS", 0):
        return asyncio.run(desktop.open_app(path))


def test_a_new_window_on_a_restored_document_is_called_out():
    result = _open_with("API Keys.md - Notepad")
    assert result["opened_new_window"] is True
    assert result["restored_document"] == "API Keys.md - Notepad"
    assert "the user's work, not a blank page" in result["warning"]


def test_a_genuinely_blank_window_raises_no_alarm():
    assert "warning" not in _open_with("Untitled - Notepad")


def test_opening_a_named_file_is_expected_to_show_it():
    assert "warning" not in _open_with("report.md - Notepad", path=r"C:\notes\report.md")
