"""Two bugs that only appeared by running it, kept from coming back.

The first was over-collection. Exporting "the whole jar" looked reasonable --
the profile is Nova's own, so surely it only holds sites the user signed into
there. It does not: Edge arrives with bing.com and msn.com cookies from its
new-tab page, and the first real export wrote live Microsoft account tokens
into a plaintext file nobody had asked for. The fix is an allowlist, and the
test is that a domain nobody asked for cannot appear.

The second was line endings. On Windows, writing text translates \\n to \\r\\n;
yt-dlp's Netscape parser splits on \\n and keeps the \\r, which lands on the
end of every cookie's value. The jar loads without complaint and
authenticates nothing -- the worst shape a bug can take.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"
PKG = "site_session_checks"
package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules[PKG] = package
for name in ("browser_control", "config"):
    module = types.ModuleType(f"{PKG}.{name}")
    sys.modules[module.__name__] = module
    setattr(package, name, module)
package.config.DB_PATH = Path(__file__).parent / "_tmp_site_session"
package.config.write_env_value = lambda name, value: value
package.config.read_env_value = lambda name: None


def load(name):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


site_session = load("site_session")


class OnlyTheSitesWeAskedFor(unittest.TestCase):
    def test_no_site_means_every_known_site_not_every_domain(self):
        wanted = [d.lstrip(".") for d in site_session._wanted_domains(None)]
        self.assertIn("instagram.com", wanted)
        self.assertIn("tiktok.com", wanted)
        # The ones that caused the bug.
        self.assertNotIn("bing.com", wanted)
        self.assertNotIn("msn.com", wanted)

    def test_naming_a_site_narrows_to_it(self):
        wanted = [d.lstrip(".") for d in site_session._wanted_domains("instagram")]
        self.assertIn("instagram.com", wanted)
        self.assertNotIn("tiktok.com", wanted)

    def test_an_unknown_site_is_refused_rather_than_exporting_everything(self):
        with self.assertRaises(site_session.SiteSessionError):
            site_session._wanted_domains("some-other-site")


class TheJarIsValidNetscape(unittest.TestCase):
    def test_a_line_has_seven_tab_separated_fields(self):
        line = site_session._netscape_line({
            "domain": ".instagram.com", "name": "sessionid", "value": "abc",
            "path": "/", "secure": True, "expires": 1800000000,
        })
        self.assertEqual(len(line.split("\t")), 7)
        self.assertTrue(line.startswith(".instagram.com\tTRUE\t/\tTRUE\t1800000000\tsessionid\tabc"))

    def test_include_subdomains_follows_the_leading_dot(self):
        host_only = site_session._netscape_line({
            "domain": "instagram.com", "name": "a", "value": "b", "path": "/",
        })
        self.assertEqual(host_only.split("\t")[1], "FALSE")

    def test_a_session_cookie_gets_a_zero_expiry_not_minus_one(self):
        """Playwright uses -1 for session cookies; -1 in the expiry column is
        not something the format defines."""
        line = site_session._netscape_line({
            "domain": ".x.com", "name": "a", "value": "b", "path": "/", "expires": -1,
        })
        self.assertEqual(line.split("\t")[4], "0")

    def test_a_cookie_without_a_name_or_domain_is_skipped_not_written_broken(self):
        self.assertIsNone(site_session._netscape_line({"domain": "", "name": "a"}))
        self.assertIsNone(site_session._netscape_line({"domain": ".x.com", "name": ""}))

    def test_no_line_carries_a_carriage_return(self):
        line = site_session._netscape_line({
            "domain": ".instagram.com", "name": "sessionid", "value": "abc", "path": "/",
        })
        self.assertNotIn("\r", line)


if __name__ == "__main__":
    unittest.main()
