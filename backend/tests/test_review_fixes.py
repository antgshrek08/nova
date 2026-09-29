"""Each of these pins a bug that was found by reading the code, not by
hitting it.

That is worth saying because none of them announce themselves at runtime. A
seen-list that drops what you just added re-watches a reel and notifies twice;
a login-wall matcher that is always true offers to sign in to fix a 404; a
model wrongly believed to have eyes describes a picture it never saw. They
look like the feature working until you compare the output to reality, which
is exactly the class of failure a test is for.
"""
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"
PKG = "review_checks"
package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules[PKG] = package
for name in ("browser_control", "config", "db", "site_session", "secrets_store",
             "identity", "classifier", "typesafe"):
    module = types.ModuleType(f"{PKG}.{name}")
    sys.modules[module.__name__] = module
    setattr(package, name, module)


def load(name):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


vision = load("vision")
dm = load("instagram_dm")
signin = load("signin")
session = load("site_session")


class AnEyelessModelIsNotGivenAPicture(unittest.TestCase):
    """The worst outcome available here is a confident description of an
    image the model never received."""

    def test_gemma3_1b_has_no_eyes(self):
        """Gemma 3 is a family: 4b and up carry a vision tower, 1b does not.
        Matching on the family name declared the blind one sighted."""
        self.assertFalse(vision.provider_can_see("ollama", "gemma3:1b"))

    def test_the_sighted_gemmas_still_count(self):
        for model in ("gemma3:4b", "gemma3:12b", "gemma3:27b"):
            self.assertTrue(vision.provider_can_see("ollama", model), model)

    def test_an_unknown_local_model_is_assumed_blind(self):
        for model in ("llama3.1:8b", "qwen2.5-coder:7b", "mistral", ""):
            self.assertFalse(vision.provider_can_see("ollama", model), model)

    def test_qwen35_images_retain_tools_but_gemma_does_not(self):
        self.assertTrue(vision.provider_can_see('ollama', 'qwen3.5:4b'))
        self.assertTrue(vision.image_tools_supported('ollama', 'qwen3.5:4b'))
        self.assertFalse(vision.image_tools_supported('ollama', 'gemma3:4b'))
        self.assertTrue(vision.has_images([{'role': 'user', 'content': vision.build_content('Inspect', [{'data': b'png', 'content_type': 'image/png'}])}]))
        self.assertFalse(vision.has_images([{'role': 'user', 'content': 'Inspect'}]))

    def test_a_cli_provider_is_never_handed_image_blocks(self):
        """They take a rendered prompt string, so a content-block list is
        flattened to text and the image vanishes without an error."""
        for provider in ("claude_cli", "codex", "gemini_cli", "copilot"):
            self.assertFalse(vision.provider_can_see(provider, "whatever"), provider)


class TheSeenListKeepsWhatWasJustAdded(unittest.TestCase):
    """`list(seen | set(new))[-LIMIT:]` reads as "keep the most recent" and
    is not: a set has no order, so past the cap the slice could drop the URLs
    being added in that very call -- and the reel is watched again, and
    announced again, on every poll forever."""

    def setUp(self):
        self.stored = {}

        async def get_app_settings():
            return dict(self.stored)

        async def set_app_settings(values):
            self.stored.update(values)

        dm.db.get_app_settings = get_app_settings
        dm.db.set_app_settings = set_app_settings

    def test_a_new_url_survives_a_full_list(self):
        old = [f"https://www.instagram.com/reel/old{i}/" for i in range(dm.SEEN_LIMIT)]
        asyncio.run(dm._remember(old))
        fresh = "https://www.instagram.com/reel/BRANDNEW/"
        asyncio.run(dm._remember([fresh]))
        self.assertIn(fresh, asyncio.run(dm._seen()))

    def test_the_cap_still_holds(self):
        asyncio.run(dm._remember([f"https://x/reel/{i}/" for i in range(dm.SEEN_LIMIT * 2)]))
        self.assertLessEqual(len(asyncio.run(dm._seen_list())), dm.SEEN_LIMIT)

    def test_the_oldest_is_what_gets_dropped(self):
        asyncio.run(dm._remember(["first"]))
        asyncio.run(dm._remember([f"u{i}" for i in range(dm.SEEN_LIMIT)]))
        self.assertNotIn("first", asyncio.run(dm._seen()))

    def test_re_remembering_does_not_duplicate_or_age_out_the_rest(self):
        asyncio.run(dm._remember(["a", "b", "c"]))
        asyncio.run(dm._remember(["b"]))
        self.assertEqual(asyncio.run(dm._seen_list()), ["a", "c", "b"])

    def test_corrupt_storage_reads_as_empty_rather_than_raising(self):
        self.stored[dm.SEEN_KEY] = "{not json"
        self.assertEqual(asyncio.run(dm._seen_list()), [])


class ALoginWallIsRecognisedByAWord(unittest.TestCase):
    """"age" as a bare substring lives inside "message", "page" and "usage",
    so the matcher was effectively always true and Nova offered to sign in to
    fix unrelated errors."""

    def test_ordinary_errors_are_not_login_walls(self):
        for error in (
            "Unable to download webpage: HTTP Error 404: Not Found",
            "ERROR: unable to parse the message from the server",
            "Postprocessing: ffmpeg usage error",
            "Connection reset by peer",
        ):
            self.assertFalse(session.looks_login_walled(error), error)

    def test_real_login_walls_still_match(self):
        for error in (
            "ERROR: login required. Use --cookies",
            "Sign in to confirm your age",
            "This video is age-restricted",
            "Requested content is not available, rate-limit reached",
            "ERROR: This post is private",
        ):
            self.assertTrue(session.looks_login_walled(error), error)

    def test_no_error_at_all_is_not_a_wall(self):
        self.assertFalse(session.looks_login_walled(""))
        self.assertFalse(session.looks_login_walled(None))


class TheAllowlistMeansTheDomain(unittest.TestCase):
    """An allowlist that accepts any string *ending* in instagram.com also
    accepts notinstagram.com -- and the whole reason it exists is that the
    first version exported cookies it should not have."""

    @staticmethod
    def allowed(domain, wanted):
        host = (domain or "").lstrip(".").lower()
        return any(host == d or host.endswith("." + d) for d in wanted)

    def test_the_site_and_its_subdomains_pass(self):
        for host in ("instagram.com", ".instagram.com", "www.instagram.com",
                     "i.instagram.com"):
            self.assertTrue(self.allowed(host, ["instagram.com"]), host)

    def test_a_lookalike_domain_does_not(self):
        for host in ("notinstagram.com", "evil-instagram.com", "myinstagram.com"):
            self.assertFalse(self.allowed(host, ["instagram.com"]), host)

    def test_the_shipped_matcher_agrees(self):
        """site_for_url already had this right; the point of the fix was that
        the two spellings of one rule disagreed."""
        source = (ROOT / "site_session.py").read_text("utf-8")
        self.assertNotIn('.endswith(d) for d in wanted', source)


class SignInNeverClaimsASessionItDoesNotHave(unittest.TestCase):
    def test_a_code_screen_is_not_being_signed_in(self):
        """A one-time-code page has no password field either, and "no
        password field" used to mean "already signed in"."""
        self.assertEqual(
            signin._classify("enter the code we sent to your email", "https://x/login"),
            "needs_code",
        )

    def test_a_challenge_url_counts_even_when_the_page_says_nothing(self):
        """The widget usually lives in a cross-origin iframe, whose text
        inner_text never sees."""
        self.assertEqual(
            signin._classify("", "https://www.instagram.com/challenge/?next=/"),
            "challenge",
        )

    def test_a_plain_page_is_still_unclassified(self):
        self.assertIsNone(signin._classify("welcome back, here is your feed",
                                           "https://www.instagram.com/"))

    def test_a_challenge_outranks_a_code_prompt(self):
        """Both can appear at once; the one that needs a human wins, because
        that is the one Nova must not attempt."""
        self.assertEqual(
            signin._classify("security check. enter the code we sent", "https://x/"),
            "challenge",
        )


class EveryKindHasAQuestion(unittest.TestCase):
    """look.py and watch.py each branch on a Jev category by indexing
    FOLLOW_UPS. typesafe.choose guarantees the category was offered, so the
    only way that raises is a KIND added without its question -- which would
    surface as a crash on whichever video happened to be classified that way,
    long after the edit."""

    def test_look_and_watch_both_answer_every_category_they_offer(self):
        for module in (load("look"), load("watch")):
            self.assertTrue(module.KINDS)
            self.assertEqual(set(module.KINDS), set(module.FOLLOW_UPS),
                             f"{module.__name__}: KINDS and FOLLOW_UPS disagree")


if __name__ == "__main__":
    unittest.main()
