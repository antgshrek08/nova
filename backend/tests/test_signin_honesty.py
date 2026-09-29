"""A sign-in tool must not claim to have signed in.

The failure mode here is not a crash. It is Nova saying "signed in to your
bank" while the browser sits on a verification screen, because the code
treated "no exception" as success. Every assertion below is about the tool
refusing to overstate what happened.

The second thing locked down is the CAPTCHA rule. A challenge exists to
establish that a person is present; a tool that retries past one, or reports
success through one, is a tool for pretending otherwise. It must come back as
`challenge`, with ok False, every time.
"""
import unittest

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"
PKG = "signin_checks"
package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules[PKG] = package
for name in ("browser_control", "identity", "secrets_store"):
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


class ClassifyingThePage(unittest.TestCase):
    def test_a_captcha_is_a_challenge_not_a_success(self):
        for text in (
            "please complete the captcha to continue",
            "verify you are human",
            "checking your browser before accessing — cloudflare",
            "we detected unusual activity on this account",
        ):
            self.assertEqual(signin._classify(text, "https://x"), "challenge", text)

    def test_a_code_prompt_is_not_a_success(self):
        for text in (
            "enter the verification code we sent to your email",
            "two-factor authentication required",
            "type the 6-digit code",
        ):
            self.assertEqual(signin._classify(text, "https://x"), "needs_code", text)

    def test_a_rejection_is_recognised(self):
        for text in ("incorrect password", "we couldn't find your account"):
            self.assertEqual(signin._classify(text, "https://x"), "rejected", text)

    def test_an_ordinary_page_is_not_classified(self):
        """No marker means no verdict. The caller then looks for a password
        field rather than guessing, which is what keeps `unclear` honest."""
        self.assertIsNone(signin._classify("welcome back, here is your feed", "https://x"))

    def test_challenge_wins_over_code_when_a_page_has_both(self):
        """A challenge page that also mentions a code is still a challenge --
        the human step is the blocking one, and reporting `needs_code` would
        send Nova off to read an email that will not help."""
        text = "complete the captcha, then enter the verification code we sent"
        self.assertEqual(signin._classify(text, "https://x"), "challenge")


class ResultsDoNotOverstate(unittest.TestCase):
    def setUp(self):
        self.tab = types.SimpleNamespace(url="https://example.com/login")
        self.account = {"service": "example", "username": "nova"}

    def test_only_signed_in_reports_ok(self):
        for state in ("challenge", "needs_code", "rejected", "unclear"):
            result = signin._result(state, self.account, self.tab, "…")
            self.assertFalse(result["ok"], f"{state} must not report ok")
            self.assertEqual(result["state"], state)

    def test_signed_in_reports_ok(self):
        self.assertTrue(signin._result("signed_in", self.account, self.tab, "…")["ok"])

    def test_a_result_never_carries_a_password_field(self):
        """Nothing in the returned shape should ever be able to hold one."""
        result = signin._result("signed_in", self.account, self.tab, "…")
        self.assertEqual(set(result), {"ok", "state", "service", "url", "message"})


class TheCaptchaRuleIsStated(unittest.TestCase):
    def test_the_module_says_it_does_not_solve_challenges(self):
        """Intent belongs in the file, not only in a commit message: the next
        person to touch this should not have to infer the rule."""
        source = (ROOT / "signin.py").read_text("utf-8").lower()
        self.assertIn("captcha", source)
        self.assertIn("not retried", source)

    def test_there_is_no_captcha_solving_path(self):
        source = (ROOT / "signin.py").read_text("utf-8").lower()
        for forbidden in ("2captcha", "anticaptcha", "captcha_solver", "solve_captcha"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
