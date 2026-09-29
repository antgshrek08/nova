"""Screenshot coordinates must reach the mouse as screen coordinates.

`capture_screenshot` grabs the union of every monitor through mss, so image
pixel (0,0) is the top-left of the *virtual desktop*, which is only (0,0) when
the primary monitor is also the top-left one. pyautogui, meanwhile, takes real
screen coordinates. On a machine where a monitor sits above or to the left of
the primary, every coordinate a model reads off a screenshot is therefore
offset from the one a click needs.

That went unnoticed through two debugging sessions -- clicks simply landed
somewhere else, silently, and on a single-monitor machine nothing is wrong at
all -- so the translation is asserted here rather than left to be rediscovered.
"""
import asyncio
import unittest
from unittest import mock

from app import cursor, desktop


class ScreenOriginTranslation(unittest.TestCase):
    def test_single_monitor_is_untouched(self):
        with mock.patch.object(desktop, "screen_origin", return_value=(0, 0)):
            self.assertEqual(desktop.to_screen(452, 837), (452, 837))

    def test_negative_virtual_origin_is_added(self):
        # The real geometry this was found on: three 1920x1080 monitors with
        # the primary in the middle-right, so the virtual desktop starts at
        # (-1920, -1080). Image (2372,1917) clicked nothing; (452,837) hit the
        # intended target first try, and that is exactly this arithmetic.
        with mock.patch.object(desktop, "screen_origin", return_value=(-1920, -1080)):
            self.assertEqual(desktop.to_screen(2372, 1917), (452, 837))

    def test_origin_matches_the_captured_image(self):
        """The origin must come from the same monitor mss screenshots."""
        monitors = [{"left": -1920, "top": -1080, "width": 3840, "height": 2160}]
        fake = mock.MagicMock()
        fake.__enter__.return_value.monitors = monitors
        with mock.patch.object(desktop.mss, "mss", return_value=fake):
            self.assertEqual(desktop.screen_origin(), (-1920, -1080))

    def test_origin_failure_does_not_break_clicking(self):
        """A geometry lookup must never be the reason a click raises."""
        with mock.patch.object(desktop.mss, "mss", side_effect=OSError("no display")):
            self.assertEqual(desktop.screen_origin(), (0, 0))


REAL_POINTER = {"seconds": 0.45, "marker": True, "pointer": "real", "borrow": "ask"}


async def _real_pointer_style():
    return dict(REAL_POINTER)


@unittest.skipIf(desktop.pyautogui is None, "mouse control is Windows-only (pyautogui)")
class ClickTranslation(unittest.TestCase):
    def test_click_moves_the_mouse_to_the_translated_point(self):
        # Pinned to the "real" pointer: with Nova's own pointer (the default)
        # the click would go through UI Automation at that point on whatever
        # screen runs the test -- which once meant a test pressing a real
        # button on the developer's desktop.
        with mock.patch.object(desktop, "click_style", _real_pointer_style), \
             mock.patch.object(desktop, "screen_origin", return_value=(-1920, -1080)), \
             mock.patch.object(cursor, "flash"), \
             mock.patch.object(desktop.pyautogui, "position", return_value=(100, 100)), \
             mock.patch.object(desktop.pyautogui, "moveTo"), \
             mock.patch.object(desktop.pyautogui, "click") as clicked:
            result = asyncio.run(desktop.click(2372, 1917))
        clicked.assert_called_once_with(x=452, y=837, button="left")
        # The caller asked in image coordinates and is told both, so a model
        # can see where its click actually went.
        self.assertEqual((result["x"], result["y"]), (2372, 1917))
        self.assertEqual((result["screen_x"], result["screen_y"]), (452, 837))

    def test_scroll_target_is_translated_too(self):
        with mock.patch.object(desktop, "click_style", _real_pointer_style), \
             mock.patch.object(desktop, "screen_origin", return_value=(-1920, -1080)), \
             mock.patch.object(desktop.pyautogui, "moveTo") as moved, \
             mock.patch.object(desktop.pyautogui, "scroll"):
            asyncio.run(desktop.scroll(-3, 2372, 1917))
        moved.assert_called_once_with(452, 837)

    def test_scroll_without_a_point_does_not_move_the_mouse(self):
        with mock.patch.object(desktop, "click_style", _real_pointer_style), \
             mock.patch.object(desktop.pyautogui, "moveTo") as moved, \
             mock.patch.object(desktop.pyautogui, "scroll") as scrolled:
            asyncio.run(desktop.scroll(-3))
        moved.assert_not_called()
        scrolled.assert_called_once_with(-3)


if __name__ == "__main__":
    unittest.main()
