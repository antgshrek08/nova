"""The parts of DM reading that can be tested without an Instagram account.

Not the browser driving -- that needs a real session and a real inbox. What
is testable here is everything that decides *whether* Nova acts: which links
count as a shared reel, when two links are the same reel, and whether a page
is a challenge. Those are where a quiet bug costs the most: a missed link
looks like "they didn't send anything", a failed dedupe watches the same clip
every fifteen minutes forever, and a missed challenge keeps hammering an
account that is already being looked at.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"
PKG = "ig_dm_checks"
package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules[PKG] = package
for name in ("browser_control", "db", "site_session"):
    module = types.ModuleType(f"{PKG}.{name}")
    sys.modules[module.__name__] = module
    setattr(package, name, module)


def load(name):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dm = load("instagram_dm")


class OneReelIsOneReel(unittest.TestCase):
    def test_reel_and_reels_are_the_same_thing(self):
        """Instagram serves both spellings depending on where the share came
        from. Treating them as different watches the clip twice and notifies
        twice."""
        a = dm.canonical("https://www.instagram.com/reel/C8xAbC1dEf/")
        b = dm.canonical("https://instagram.com/reels/C8xAbC1dEf/")
        self.assertEqual(a, b)

    def test_tracking_parameters_do_not_create_a_new_reel(self):
        plain = dm.canonical("https://www.instagram.com/reel/C8xAbC1dEf/")
        tagged = dm.canonical("https://www.instagram.com/reel/C8xAbC1dEf/?igsh=abc123&utm_source=x")
        self.assertEqual(plain, tagged)

    def test_a_post_is_not_a_reel_with_the_same_code(self):
        """Different surfaces, genuinely different content."""
        self.assertNotEqual(
            dm.canonical("https://www.instagram.com/p/C8xAbC1dEf/"),
            dm.canonical("https://www.instagram.com/reel/C8xAbC1dEf/"),
        )

    def test_canonical_is_idempotent(self):
        once = dm.canonical("https://www.instagram.com/reels/C8xAbC1dEf/?x=1")
        self.assertEqual(once, dm.canonical(once))


class WhatCountsAsAShare(unittest.TestCase):
    def test_reels_posts_and_tv_are_collected(self):
        for path in ("/reel/C8xAbC1dEf/", "/reels/C8xAbC1dEf/",
                     "/p/C8xAbC1dEf/", "/tv/C8xAbC1dEf/"):
            self.assertIsNotNone(dm._SHARE_RE.search(path), path)

    def test_profiles_and_stories_are_not_shares(self):
        """A profile is not a thing to watch, and a story expires before the
        next poll -- collecting either means watching something that is not
        what they sent."""
        for path in ("/someuser/", "/stories/someone/123456/",
                     "/direct/inbox/", "/explore/", "/accounts/login/"):
            self.assertIsNone(dm._SHARE_RE.search(path), path)

    def test_a_shortcode_must_be_long_enough_to_be_real(self):
        self.assertIsNone(dm._SHARE_RE.search("/p/ab/"))


class AChallengeIsRecognised(unittest.TestCase):
    def test_the_usual_wordings_are_caught(self):
        for text in (
            "we detected an unusual login attempt",
            "help us confirm it's you",
            "suspicious login attempt blocked",
            "please complete the captcha",
        ):
            self.assertTrue(
                any(m in text for m in dm.CHALLENGE_MARKERS),
                f"not recognised as a challenge: {text}",
            )

    def test_an_ordinary_inbox_is_not_a_challenge(self):
        text = "messages  primary  general  requests  send a message to start a chat"
        self.assertFalse(any(m in text for m in dm.CHALLENGE_MARKERS))


class ThePollIsDeliberatelySlow(unittest.TestCase):
    def test_the_default_interval_is_minutes_not_seconds(self):
        """A fast fixed poll is the most machine-looking signal this feature
        can emit, and a reel is not urgent."""
        self.assertGreaterEqual(dm.DEFAULT_INTERVAL_MINUTES, 10)

    def test_the_seen_list_is_bounded(self):
        self.assertLessEqual(dm.SEEN_LIMIT, 1000)


class ItNeverWritesToInstagram(unittest.TestCase):
    def test_no_interaction_verbs_appear_in_the_module(self):
        """The guarantee this feature rests on: it reads and leaves. If a
        like, follow, or send ever appears here, that is a different feature
        with a different risk, and it should not arrive quietly."""
        source = (ROOT / "instagram_dm.py").read_text("utf-8").lower()
        for forbidden in ("click_like", "follow_user", "send_message",
                          "post_comment", "unfollow"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
