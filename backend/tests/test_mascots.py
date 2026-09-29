"""User-supplied mascot art: what gets stored, and what gets refused.

The art people want here belongs to other companies, so it has to arrive from
the user at runtime rather than ship with Nova. That makes this an upload path
reachable from the UI, so the interesting cases are the refusals and the
"looks like it worked but didn't" ones.
"""
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from PIL import Image

from app import mascots


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), (10, 200, 140, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 120, 10)).save(buffer, format="JPEG")
    return buffer.getvalue()


class MascotUploads(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        patch = mock.patch.object(mascots, "MASCOT_DIR", Path(self._dir.name))
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self._dir.cleanup)

    def test_double_width_image_is_reported_as_two_frames(self):
        saved = mascots.save("claude", _png(128, 64))
        self.assertEqual(saved["frames"], 2)
        self.assertEqual(saved["file"], "claude.png")
        self.assertTrue(mascots.status()["mascots"]["claude"]["custom"])

    def test_square_image_is_a_single_frame(self):
        # Not an error: a square crop is a perfectly good still mascot, and the
        # UI says so rather than leaving the user wondering why it is static.
        self.assertEqual(mascots.save("codex", _png(64, 64))["frames"], 1)

    def test_jpeg_is_stored_as_png(self):
        """The extension must describe the bytes, not the uploaded filename.

        path_for only looks for .png/.webp/.gif, so a JPEG written under a .png
        name would be served as a PNG the browser refuses to render."""
        saved = mascots.save("gemini", _jpeg(64, 64))
        self.assertEqual(saved["file"], "gemini.png")
        stored = (Path(self._dir.name) / "gemini.png").read_bytes()
        with Image.open(io.BytesIO(stored)) as image:
            self.assertEqual(image.format, "PNG")

    def test_replacing_art_removes_the_other_extensions(self):
        """Otherwise path_for keeps finding the older file first and the
        upload looks like it silently did nothing."""
        directory = Path(self._dir.name)
        (directory / "ollama.gif").write_bytes(_png(32, 32))  # stale prior drop
        mascots.save("ollama", _png(128, 64))
        self.assertFalse((directory / "ollama.gif").exists())
        self.assertEqual(mascots.path_for("ollama").name, "ollama.png")

    def test_unknown_name_is_refused(self):
        # The name reaches this from a URL path; it must not become a general
        # file writer for the user's home directory.
        for name in ("../../evil", "claude.png", "", "nova/../../x"):
            with self.assertRaises(ValueError):
                mascots.save(name, _png(64, 64))

    def test_non_image_is_refused(self):
        with self.assertRaises(ValueError):
            mascots.save("claude", b"MZ\x90\x00 this is an executable")

    def test_empty_upload_is_refused(self):
        with self.assertRaises(ValueError):
            mascots.save("claude", b"")

    def test_oversized_upload_is_refused(self):
        with mock.patch.object(mascots, "MAX_BYTES", 100):
            with self.assertRaises(ValueError):
                mascots.save("claude", _png(128, 64))

    def test_remove_reverts_to_the_bundled_art(self):
        mascots.save("claude", _png(128, 64))
        self.assertTrue(mascots.remove("claude"))
        self.assertIsNone(mascots.path_for("claude"))
        # Removing again is not an error -- the UI may be a click behind.
        self.assertFalse(mascots.remove("claude"))

    def test_uploaded_files_are_never_listed_as_ignored(self):
        mascots.save("claude", _png(128, 64))
        (Path(self._dir.name) / "clawd-pet.jpeg").write_bytes(_jpeg(32, 32))
        status = mascots.status()
        self.assertEqual(status["ignored"], ["clawd-pet.jpeg"])


if __name__ == "__main__":
    unittest.main()
