"""Reading a video without downloading it.

The point of this path is that Nova can be sent a link and then act on what
the video actually says. That makes an honest "no captions" answer more
valuable than a confident one: the next step is usually editing code, and
inferring content from a title is how you get plausible nonsense committed.

Network-free. The extractor and caption fetch are stubbed, because what is
worth pinning here is the parsing and the refusals, not YouTube's uptime.
"""
import asyncio
import json
import unittest
from unittest import mock

from app import video


def run(coro):
    return asyncio.run(coro)


class FindingLinks(unittest.TestCase):
    def test_video_links_are_recognised_in_a_sentence(self):
        found = video.find_urls("add this to your source code https://youtu.be/abc123 please")
        self.assertEqual(found, ["https://youtu.be/abc123"])

    def test_every_supported_host_is_matched(self):
        for url in (
            "https://www.youtube.com/watch?v=x", "https://youtu.be/x",
            "https://www.instagram.com/reel/x/", "https://www.tiktok.com/@a/video/1",
            "https://x.com/a/status/1", "https://vimeo.com/1",
        ):
            self.assertTrue(video.looks_like_video(url), url)

    def test_ordinary_links_are_not_treated_as_video(self):
        for url in ("https://github.com/a/b", "https://example.com/watch?v=1", "not a url"):
            self.assertFalse(video.looks_like_video(url), url)

    def test_a_link_is_only_listed_once(self):
        text = "https://youtu.be/x and again https://youtu.be/x"
        self.assertEqual(len(video.find_urls(text)), 1)


class CaptionParsing(unittest.TestCase):
    def test_json3_segments_become_lines(self):
        payload = {"events": [
            {"segs": [{"utf8": "hello "}, {"utf8": "there"}]},
            {"segs": [{"utf8": "\n"}]},
            {"segs": [{"utf8": "second line"}]},
        ]}
        self.assertEqual(video._text_from_json3(payload), "hello there\nsecond line")

    def test_vtt_timestamps_and_markup_are_dropped(self):
        raw = ("WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\n"
               "<c>Hello</c> world\n\n2\n00:00:03.000 --> 00:00:05.000\nsecond line\n")
        self.assertEqual(video._text_from_vtt(raw), "Hello world\nsecond line")

    def test_rolling_caption_repeats_are_collapsed(self):
        """Auto-captions repeat the previous line with a word added, which
        triples the length of a transcript without adding anything."""
        raw = "WEBVTT\n\n00:01.000 --> 00:02.000\nthe cat\n\n00:02.000 --> 00:03.000\nthe cat\n"
        self.assertEqual(video._text_from_vtt(raw), "the cat")


class Reading(unittest.TestCase):
    def _read(self, info, captions=None, raises=None):
        def fake_extract(self_, url, download=False):
            if raises:
                raise raises
            return info

        async def fake_get(self_, url, **kwargs):
            return mock.Mock(text=captions, raise_for_status=lambda: None)

        with mock.patch("yt_dlp.YoutubeDL.YoutubeDL.extract_info", fake_extract), \
             mock.patch("httpx.AsyncClient.get", fake_get):
            return run(video.read("https://youtu.be/x"))

    def test_a_video_with_captions_returns_the_transcript(self):
        info = {"title": "T", "uploader": "C", "duration": 60, "description": "d",
                "subtitles": {"en": [{"ext": "json3", "url": "http://c"}]}}
        captions = json.dumps({"events": [{"segs": [{"utf8": "spoken words"}]}]})
        result = self._read(info, captions)
        self.assertTrue(result["ok"])
        self.assertEqual(result["transcript"], "spoken words")
        self.assertEqual(result["transcript_source"], "captions")
        self.assertIsNone(result["note"])

    def test_no_captions_says_so_instead_of_guessing(self):
        """The whole value of this path is not inventing content."""
        result = self._read({"title": "T", "uploader": "C", "duration": 60, "description": "d"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["transcript"], "")
        self.assertIn("no captions", result["note"])

    def test_the_extractors_own_error_is_passed_through(self):
        """"Login required" and "video unavailable" need different things
        from the user, so they must not both become "couldn't read it"."""
        result = self._read(None, raises=RuntimeError(
            "ERROR: [Instagram] x: Instagram sent an empty media response. Check if..."))
        self.assertFalse(result["ok"])
        self.assertIn("Instagram", result["error"])
        self.assertNotIn("ERROR:", result["error"])

    def test_an_overlong_video_is_refused_with_its_length(self):
        info = {"title": "T", "duration": video.MAX_DURATION_SECONDS + 60}
        result = self._read(info)
        self.assertFalse(result["ok"])
        self.assertIn("long", result["error"])

    def test_a_huge_transcript_is_capped_and_flagged(self):
        info = {"title": "T", "duration": 60,
                "subtitles": {"en": [{"ext": "vtt", "url": "http://c"}]}}
        captions = "WEBVTT\n\n" + "\n\n".join(
            f"00:00:{i % 60:02d}.000 --> 00:00:59.000\nline number {i}" for i in range(6000)
        )
        result = self._read(info, captions)
        self.assertTrue(result["transcript_truncated"])
        self.assertLessEqual(len(result["transcript"]), video.MAX_TRANSCRIPT_CHARS)


class Cookies(unittest.TestCase):
    def test_cookies_are_not_read_unless_configured(self):
        """Reusing a browser session means reading the user's cookies. That
        is their data at their request, not a default."""
        self.assertNotIn("cookiesfrombrowser", video._ydl_options())

    def test_a_configured_browser_is_passed_through(self):
        self.assertEqual(video._ydl_options("chrome")["cookiesfrombrowser"], ("chrome",))


if __name__ == "__main__":
    unittest.main()
