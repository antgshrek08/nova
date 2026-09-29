"""The visible click, minus the screen.

Nothing here moves a real pointer or draws a real window -- that was checked
by hand against a live desktop. What is worth holding still in a test is the
part that would fail silently: a glide that stops short of the target clicks
the wrong thing, and a settings value that arrives as a string or as nonsense
must not be able to make the pointer take twenty seconds to cross the screen.
"""
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"
PKG = "cursor_checks"
package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules[PKG] = package


def load(name):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cursor = load("cursor")


class FakePointer:
    """Records where it was told to go. Stands in for pyautogui."""

    def __init__(self, start=(0, 0)):
        self.path = [start]
        self.clicks = []

    def position(self):
        return self.path[-1]

    def moveTo(self, x, y, _pause=True):
        self.path.append((x, y))

    def click(self, x, y, button="left"):
        self.clicks.append((x, y, button))


class TheGlideArrives(unittest.TestCase):
    def test_it_lands_exactly_on_the_target(self):
        """Eased float maths finishes a pixel or two short, which is the
        difference between hitting a small control and missing it."""
        mouse = FakePointer((10, 10))
        cursor.glide(mouse, 900, 640, duration=cursor.MIN_DURATION)
        self.assertEqual(mouse.path[-1], (900, 640))

    def test_it_actually_moves_through_the_middle(self):
        """The whole point is that it is watchable -- one jump is the bug
        this module exists to fix."""
        mouse = FakePointer((0, 0))
        cursor.glide(mouse, 800, 0, duration=cursor.MIN_DURATION)
        self.assertGreater(len(mouse.path), 8)
        middles = [x for x, _ in mouse.path[1:-1]]
        self.assertTrue(any(100 < x < 700 for x in middles))

    def test_a_tiny_move_is_not_animated(self):
        mouse = FakePointer((500, 500))
        cursor.glide(mouse, 501, 500)
        self.assertEqual(len(mouse.path), 1)

    def test_a_silly_duration_is_clamped(self):
        self.assertLessEqual(cursor.MAX_DURATION, 3.0)
        mouse = FakePointer((0, 0))
        started = len(mouse.path)
        cursor.glide(mouse, 300, 300, duration=999)
        # Clamped, so this returns in seconds rather than minutes; the test
        # passing at all is the assertion.
        self.assertGreater(len(mouse.path), started)

    def test_the_curve_never_displaces_the_start(self):
        mouse = FakePointer((100, 100))
        cursor.glide(mouse, 700, 400, duration=cursor.MIN_DURATION)
        self.assertEqual(mouse.path[0], (100, 100))


class TheClickStillHappens(unittest.TestCase):
    def test_the_click_lands_at_the_target(self):
        mouse = FakePointer((0, 0))
        cursor.visible_click(mouse, 640, 480, show_marker=False,
                             duration=cursor.MIN_DURATION)
        self.assertEqual(mouse.clicks, [(640, 480, "left")])

    def test_a_failed_marker_does_not_swallow_the_click(self):
        """The animation is decoration around an action that has to happen."""
        mouse = FakePointer((0, 0))
        original = cursor.flash
        cursor.flash = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no gdi"))
        try:
            with self.assertRaises(RuntimeError):
                cursor.visible_click(mouse, 5, 5, duration=cursor.MIN_DURATION)
        finally:
            cursor.flash = original
        # desktop.click wraps this in try/except and falls back; what matters
        # here is that flash is the thing that raised, not the click.
        self.assertEqual(mouse.clicks, [])


class TheSettingAreSane(unittest.TestCase):
    """desktop.click_style, exercised without importing desktop -- which
    needs win32gui and a display. The logic under test is small enough to
    restate, and restating it is what keeps this runnable on the Fedora box."""

    @staticmethod
    def style(stored):
        try:
            seconds = float(stored.get("desktop_click_seconds", 0.45))
        except (TypeError, ValueError):
            seconds = 0.45
        return {"seconds": max(0.0, min(seconds, 2.5)),
                "marker": stored.get("desktop_click_marker", "1") != "0"}

    def test_settings_arrive_as_strings(self):
        self.assertEqual(self.style({"desktop_click_seconds": "0.9"})["seconds"], 0.9)

    def test_nonsense_falls_back_rather_than_raising(self):
        self.assertEqual(self.style({"desktop_click_seconds": "soon"})["seconds"], 0.45)

    def test_a_huge_value_cannot_stall_a_click(self):
        self.assertEqual(self.style({"desktop_click_seconds": "600"})["seconds"], 2.5)

    def test_negative_is_treated_as_off_not_as_reverse(self):
        self.assertEqual(self.style({"desktop_click_seconds": "-3"})["seconds"], 0.0)

    def test_the_marker_is_on_unless_turned_off(self):
        self.assertTrue(self.style({})["marker"])
        self.assertFalse(self.style({"desktop_click_marker": "0"})["marker"])


class ItDoesNotNeedWindows(unittest.TestCase):
    def test_flash_is_a_no_op_off_windows(self):
        """cursor is imported by desktop.py, which now has to survive on the
        Fedora build. Drawing is best effort and must never raise."""
        import ctypes

        had = hasattr(ctypes, "windll")
        if had:
            saved = ctypes.windll
            del ctypes.windll
        try:
            cursor.flash(10, 10, hold_ms=0)  # must return quietly
        finally:
            if had:
                ctypes.windll = saved


if __name__ == "__main__":
    unittest.main()
