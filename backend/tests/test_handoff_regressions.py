"""Offline reproductions of false-success paths identified from the handoff."""
import importlib.util
import sys
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1] / "app"
PKG = "handoff_checks"
package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules[PKG] = package
for name in ("browser_control", "identity", "secrets_store", "config", "db",
             "site_session", "classifier", "typesafe", "video"):
    module = types.ModuleType(f"{PKG}.{name}")
    sys.modules[module.__name__] = module
    setattr(package, name, module)


def load(name):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


signin = load("signin")
dm = load("instagram_dm")
watch = load("watch")
session = load("site_session")
package.config.DB_PATH = Path(tempfile.gettempdir()) / "nova-test.db"
push = load("push")


class SignInEvidence(unittest.IsolatedAsyncioTestCase):
    async def run_login(self, stages):
        # Each stage is a browser page; submitting advances to the next one.
        current = [0]
        filled = []
        tab = types.SimpleNamespace(url="https://example.com/login",
                                    goto=AsyncMock(), wait_for_timeout=AsyncMock())

        def locator(selector):
            stage = stages[current[0]]
            present = selector in stage.get("fields", [])
            field = MagicMock()
            field.first = field
            field.count = AsyncMock(return_value=int(present))
            field.is_visible = AsyncMock(return_value=present)
            field.inner_text = AsyncMock(return_value=stage.get("text", ""))

            async def fill(value):
                filled.append((selector, value))

            async def submit(*args, **kwargs):
                current[0] = min(current[0] + 1, len(stages) - 1)

            field.fill = fill
            field.click = submit
            field.press = submit
            return field

        tab.locator = locator
        account = {"service": "example", "username": "nova", "url": tab.url}
        with patch.object(signin.identity, "listing", AsyncMock(return_value=[account]), create=True), \
             patch.object(signin.identity, "secret_name", lambda _: "account.example", create=True), \
             patch.object(signin.secrets_store, "get", lambda _: "test-password", create=True), \
             patch.object(signin.browser_control, "page", AsyncMock(return_value=tab), create=True):
            result = await signin.sign_in("example")
        self.assertNotIn("test-password", str(result))
        return result, filled

    async def test_blank_page_is_not_signed_in(self):
        result, _ = await self.run_login([{}])
        self.assertEqual(result["state"], "unclear")
        self.assertFalse(result["ok"])

    async def test_disappearing_form_is_not_proof_of_success(self):
        result, _ = await self.run_login([
            {"fields": ["input[type='password']", "button[type='submit']"]}, {}])
        self.assertEqual(result["state"], "unclear")

    async def test_visible_logout_control_is_evidence(self):
        result, _ = await self.run_login([{"fields": ["button:has-text('Log out')"]}])
        self.assertTrue(result["ok"])

    async def test_username_first_form_reaches_password(self):
        result, filled = await self.run_login([
            {"fields": ["input[autocomplete='username']", "button[type='submit']"]},
            {"fields": ["input[type='password']", "button[type='submit']"]},
            {"fields": ["button:has-text('Log out')"]},
        ])
        self.assertIn(("input[type='password']", "test-password"), filled)
        self.assertTrue(result["ok"])

    async def test_challenge_with_password_field_stops_before_filling(self):
        result, filled = await self.run_login([{
            "fields": ["input[type='password']"], "text": "verify you are human"}])
        self.assertEqual(result["state"], "challenge")
        self.assertEqual(filled, [])

    async def test_code_after_username_stops_before_password(self):
        result, filled = await self.run_login([
            {"fields": ["input[autocomplete='username']", "button[type='submit']"]},
            {"text": "enter the verification code", "fields": ["input[type='password']"]},
        ])
        self.assertEqual(result["state"], "needs_code")
        self.assertNotIn(("input[type='password']", "test-password"), filled)


class InboxFailures(unittest.IsolatedAsyncioTestCase):
    async def test_navigation_failure_is_not_an_empty_success(self):
        with patch.object(dm.site_session, "status", lambda: {"linked": True}, create=True), \
             patch.object(dm.site_session, "ensure_session", AsyncMock(return_value={"ok": True}), create=True), \
             patch.object(dm, "_fresh_tab", AsyncMock(side_effect=TimeoutError())), \
             patch.object(dm, "_seen", AsyncMock(return_value=set())):
            with self.assertRaises(dm.DMError):
                await dm.check()

    async def test_unreadable_links_are_not_an_empty_list(self):
        tab = types.SimpleNamespace(eval_on_selector_all=AsyncMock(side_effect=TimeoutError()))
        with self.assertRaises(dm.DMError):
            await dm._links_on_page(tab)

    async def test_unreadable_thread_list_is_not_empty(self):
        rows = types.SimpleNamespace(count=AsyncMock(side_effect=TimeoutError()))
        with patch.object(dm, "_conversation_rows", return_value=rows):
            with self.assertRaises(dm.DMError):
                await dm._harvest_threads(object(), 5)

    async def test_unreadable_card_list_is_not_empty(self):
        cards = types.SimpleNamespace(count=AsyncMock(side_effect=TimeoutError()))
        tab = types.SimpleNamespace(locator=lambda _: cards)
        with self.assertRaises(dm.DMError):
            await dm._reels_in_thread(tab)


class DownloadSelection(unittest.TestCase):
    def grab(self, folder, info):
        downloader = MagicMock()
        downloader.__enter__.return_value = downloader
        downloader.extract_info.return_value = info
        downloader.prepare_filename.return_value = str(folder / "clip.mp4")
        dependency = types.SimpleNamespace(YoutubeDL=MagicMock(return_value=downloader))
        with patch.dict(sys.modules, {"yt_dlp": dependency}), \
             patch.object(package.video, "_ydl_options", return_value={}, create=True):
            return watch._grab("https://example.com/video", folder, "best", "clip")

    def test_partial_file_cannot_beat_completed_download(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "clip.mp4").write_bytes(b"video")
            (folder / "clip.mp4.part").write_bytes(b"partial" * 100)
            self.assertEqual(self.grab(folder, {"ext": "mp4"}), folder / "clip.mp4")

    def test_only_partial_download_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "clip.mp4.part").write_bytes(b"partial")
            self.assertIsNone(self.grab(folder, {"ext": "mp4"}))

    def test_no_extracted_media_does_not_reuse_leftovers(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "clip.mp4").write_bytes(b"leftover")
            self.assertIsNone(self.grab(folder, None))


@unittest.skipUnless(sys.platform == "win32", "Win32 window class")
class RingHandles(unittest.TestCase):
    def test_window_class_preserves_the_full_module_handle(self):
        # Isolate registration from other tests; no window or mouse is used.
        script = """
import ctypes
from ctypes import wintypes
from app import cursor
kernel = ctypes.WinDLL('kernel32')
kernel.GetModuleHandleW.restype = wintypes.HMODULE
kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
expected = kernel.GetModuleHandleW(None)
assert cursor._register_ring_class(ctypes, wintypes)
assert cursor._register_ring_class.keep_alive[1].hInstance == expected
"""
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT.parent,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


class SessionBoundaries(unittest.IsolatedAsyncioTestCase):
    def test_lookalike_domains_do_not_count_as_linked(self):
        for domain in ("notinstagram.com", "evil-instagram.com"):
            with self.subTest(domain=domain), patch.object(
                    session, "status", return_value={"linked": True, "domains": [domain]}):
                self.assertFalse(session.has_session_for("instagram"))

    def test_real_domain_and_subdomain_count_as_linked(self):
        for domain in ("instagram.com", ".instagram.com", "WWW.INSTAGRAM.COM"):
            with self.subTest(domain=domain), patch.object(
                    session, "status", return_value={"linked": True, "domains": [domain]}):
                self.assertTrue(session.has_session_for("instagram"))

    async def test_failed_navigation_closes_the_new_tab(self):
        tab = types.SimpleNamespace(set_default_timeout=lambda _: None,
                                    goto=AsyncMock(side_effect=TimeoutError()), close=AsyncMock())
        context = types.SimpleNamespace(new_page=AsyncMock(return_value=tab))
        with patch.object(dm.browser_control, "_browser", context, create=True), \
             patch.object(dm.browser_control, "_alive", return_value=True, create=True):
            with self.assertRaises(TimeoutError):
                await dm._fresh_tab(dm.INBOX_URL)
        tab.close.assert_awaited_once()


class VideoSampling(unittest.TestCase):
    def sample(self, *, duration=20, reported_frames=200, actual_frames=200, seek_error=False,
               time_offset=0):
        # A clip with one keyframe: every backward seek lands at time zero.
        frames = [types.SimpleNamespace(time=time_offset + i / 10, to_image=lambda i=i: i)
                  for i in range(actual_frames)]

        class Container:
            def __init__(self):
                self.duration = duration * 1_000_000
                self.streams = [types.SimpleNamespace(type="video", frames=reported_frames,
                                                     average_rate=10, start_time=time_offset * 10,
                                                     time_base=0.1)]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def seek(self, *args, **kwargs):
                if seek_error:
                    raise RuntimeError("seeking unavailable")

            def decode(self, **kwargs):
                return iter(frames)

        dependency = types.SimpleNamespace(open=lambda _: Container(), time_base=1_000_000,
                                           error=types.SimpleNamespace(FFmpegError=RuntimeError))
        with patch.dict(sys.modules, {"av": dependency}):
            return watch._sample_frames(Path("clip.mp4"))

    def test_sparse_keyframes_do_not_repeat_the_start(self):
        frames, _ = self.sample()
        self.assertEqual(len(frames), 9)
        self.assertGreater(frames[-1], 175)
        self.assertEqual(len(set(frames)), 9)

    def test_unknown_frame_count_still_covers_the_whole_clip(self):
        frames, _ = self.sample(reported_frames=0)
        self.assertGreater(frames[-1], 175)

    def test_unknown_duration_still_covers_the_whole_clip(self):
        frames, _ = self.sample(duration=0, reported_frames=0)
        self.assertGreater(frames[-1], 175)

    def test_failed_seeking_still_samples_the_end_of_longer_clips(self):
        frames, _ = self.sample(duration=120, reported_frames=1200,
                                actual_frames=1200, seek_error=True)
        self.assertEqual(len(frames), 9)
        self.assertGreater(frames[-1], 1080)

    def test_missing_metadata_cannot_hide_an_overlong_clip(self):
        with self.assertRaises(watch.WatchError):
            self.sample(duration=0, reported_frames=0, actual_frames=3700)

    def test_cleanup_keeps_paragraphs_and_bullets_separate(self):
        cleaned = watch.deframe("First paragraph.\n\n* Frame 1: A cat sits.\n* Frame 2: It stands.")
        self.assertIn("\n\n", cleaned)
        self.assertEqual(len(cleaned.splitlines()), 4)

    def test_timestamp_offsets_are_not_clip_duration(self):
        for metadata in ({}, {"duration": 0, "reported_frames": 0}):
            with self.subTest(metadata=metadata):
                frames, duration = self.sample(time_offset=600, **metadata)
                self.assertGreater(frames[-1], 175)
                self.assertLessEqual(duration, 20)

    def test_sampling_a_real_encoded_clip(self):
        try:
            import av
            from PIL import Image
        except ImportError:
            self.skipTest("PyAV and Pillow are required for the codec integration test")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clip.mp4"
            with av.open(str(path), mode="w") as output:
                stream = output.add_stream("mpeg4", rate=10)
                stream.width = stream.height = 64
                stream.pix_fmt = "yuv420p"
                stream.codec_context.gop_size = 200
                for level in range(200):
                    frame = av.VideoFrame.from_image(Image.new("RGB", (64, 64), (level,) * 3))
                    for packet in stream.encode(frame):
                        output.mux(packet)
                for packet in stream.encode():
                    output.mux(packet)
            frames, _ = watch._sample_frames(path)
            levels = [frame.getpixel((32, 32))[0] for frame in frames]
            self.assertEqual(len(frames), 9)
            self.assertEqual(levels, sorted(levels))
            self.assertGreater(levels[-1], 170)
            self.assertLess(levels[0], 25)


class NavigationEvidence(unittest.IsolatedAsyncioTestCase):
    async def test_overlay_links_are_read_before_closing_and_scoped_to_dialog(self):
        opened = [False]
        card = MagicMock()
        card.nth.return_value = card
        card.count = AsyncMock(return_value=1)
        card.bounding_box = AsyncMock(return_value={"width": 200, "height": 200})

        async def click(**kwargs):
            opened[0] = True

        async def escape(key):
            opened[0] = False

        async def links(selector, script):
            if opened[0] and "[role='dialog']" in selector:
                return ["/reel/SHARED123/"]
            return ["/reel/UNRELATED123/"]

        card.click = click
        tab = types.SimpleNamespace(url="https://www.instagram.com/direct/t/123/",
                                    locator=lambda _: card, wait_for_timeout=AsyncMock(),
                                    eval_on_selector_all=links,
                                    keyboard=types.SimpleNamespace(press=escape))
        with patch.object(dm, "_page_text", AsyncMock(return_value="A shared reel")):
            found = await dm._reels_in_thread(tab)
        self.assertEqual(found, ["https://www.instagram.com/reel/SHARED123/"])
        self.assertFalse(opened[0])

    def hidden_tab(self, *, navigate=False, present=True):
        tab = types.SimpleNamespace(url=dm.REQUESTS_URL, wait_for_timeout=AsyncMock(),
                                    wait_for_selector=AsyncMock())
        control = MagicMock()
        control.first = control
        control.count = AsyncMock(return_value=int(present))
        control.is_visible = AsyncMock(return_value=True)
        heading = MagicMock()
        heading.first = heading
        heading.count = AsyncMock(return_value=0)
        heading.is_visible = AsyncMock(return_value=False)

        async def click(**kwargs):
            if navigate:
                tab.url = "https://www.instagram.com/direct/requests/hidden/"
                heading.count.return_value = 1
                heading.is_visible.return_value = True

        control.click = click
        control.inner_text = AsyncMock(return_value="Requests Hidden requests")
        tab.get_by_role = lambda role, **kw: heading if role == "heading" else control
        tab.get_by_text = lambda *a, **kw: control
        tab.locator = lambda *a, **kw: control
        return tab

    async def test_hidden_requests_label_is_not_navigation_evidence(self):
        with self.assertRaises(dm.DMError):
            await dm._open_hidden_requests(self.hidden_tab())

    async def test_hidden_requests_navigation_is_recognised(self):
        self.assertTrue((await dm._open_hidden_requests(self.hidden_tab(navigate=True)))["opened"])

    async def test_absent_hidden_requests_is_optional(self):
        self.assertFalse((await dm._open_hidden_requests(self.hidden_tab(present=False)))["opened"])

    async def test_thread_challenge_redirect_stops_and_disables_poll(self):
        tab = types.SimpleNamespace(url=dm.INBOX_URL, wait_for_timeout=AsyncMock())
        rows = MagicMock()
        rows.count = AsyncMock(return_value=1)
        rows.nth.return_value = rows

        async def click(**kwargs):
            tab.url = "https://www.instagram.com/challenge/"

        rows.click = click
        settings = {}

        async def save(values):
            settings.update(values)

        with patch.object(dm, "_conversation_rows", return_value=rows), \
             patch.object(dm, "_page_text", AsyncMock(return_value="")), \
             patch.object(dm, "_links_on_page", AsyncMock(return_value=[])), \
             patch.object(dm, "_reels_in_thread", AsyncMock(return_value=[])), \
             patch.object(dm.db, "set_app_settings", save, create=True):
            with self.assertRaises(dm.DMError):
                await dm._harvest_threads(tab, 5)
        self.assertEqual(settings.get(dm.ENABLED_KEY), "0")


class PushRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_failed_backup_preserves_corrupt_key_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vapid-keys.json"
            path.write_text('{"private_pem": "recoverable', encoding="utf-8")
            original = path.read_bytes()
            with patch.object(push, "KEY_PATH", path), \
                 patch.object(Path, "replace", side_effect=PermissionError("locked backup")), \
                 patch.object(push, "_generate", return_value={"private_pem": "new", "public_key": "new"}):
                with self.assertRaises(RuntimeError):
                    await push.keys()
            self.assertEqual(path.read_bytes(), original)


class SeenStorage(unittest.IsolatedAsyncioTestCase):
    async def test_valid_json_with_wrong_shape_is_not_a_seen_list(self):
        for raw in ('null', '42', '"some-url"', '{"some-url": true}'):
            with self.subTest(raw=raw), patch.object(
                    dm.db, "get_app_settings", AsyncMock(return_value={dm.SEEN_KEY: raw}), create=True):
                self.assertEqual(await dm._seen_list(), [])

    async def test_duplicate_additions_do_not_evict_unique_history(self):
        stored = {dm.SEEN_KEY: '["older"]'}

        async def save(values):
            stored.update(values)

        with patch.object(dm.db, "get_app_settings", AsyncMock(side_effect=lambda: dict(stored)), create=True), \
             patch.object(dm.db, "set_app_settings", save, create=True):
            await dm._remember(["newer"] * dm.SEEN_LIMIT)
            self.assertEqual(await dm._seen_list(), ["older", "newer"])
