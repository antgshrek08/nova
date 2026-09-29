"""Guardrail tests for app/file_access.py.

The point of most of these is not that the happy path works -- it is that the
refusals actually refuse. N.O.V.A. sends file content to cloud providers, so a
hole here leaks whatever it reads off the machine.
"""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "app"
pkg = types.ModuleType("fa_checks")
pkg.__path__ = [str(root)]
sys.modules[pkg.__name__] = pkg
pkg.config = types.ModuleType("fa_checks.config")
sys.modules[pkg.config.__name__] = pkg.config

spec = importlib.util.spec_from_file_location("fa_checks.file_access", root / "file_access.py")
fa = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fa
spec.loader.exec_module(fa)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name).resolve()
        # granted_roots() always includes the open project; point that at the
        # temp dir so tests never touch the real workspace.
        pkg.config.get_workspace_dir = lambda: self.dir
        self.roots = [self.dir]
        self.addCleanup(self._tmp.cleanup)

    def write(self, rel, text="hello"):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p


class ContainmentTests(Base):
    def test_reads_a_file_inside_a_granted_root(self):
        self.write("notes.txt", "chapter one")
        out = fa.read_text(str(self.dir / "notes.txt"), self.roots)
        self.assertEqual(out["content"], "chapter one")
        self.assertFalse(out["truncated"])

    def test_refuses_a_path_outside_every_granted_root(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other, "secret.txt")
            outside.write_text("nope", encoding="utf-8")
            with self.assertRaises(fa.FileAccessError) as caught:
                fa.read_text(str(outside), self.roots)
            self.assertIn("outside every granted folder", str(caught.exception))

    def test_refuses_dot_dot_traversal(self):
        with self.assertRaises(fa.FileAccessError):
            fa.read_text(str(self.dir / ".." / ".." / "etc" / "passwd"), self.roots)

    def test_refuses_a_symlink_that_escapes_a_granted_root(self):
        """Resolution happens before containment, so a link out of the root is
        refused rather than followed."""
        with tempfile.TemporaryDirectory() as other:
            target = Path(other, "outside.txt")
            target.write_text("secret", encoding="utf-8")
            link = self.dir / "link.txt"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation not permitted here")
            with self.assertRaises(fa.FileAccessError):
                fa.read_text(str(link), self.roots)

    def test_no_roots_means_no_access(self):
        self.write("a.txt")
        with self.assertRaises(fa.FileAccessError) as caught:
            fa.read_text(str(self.dir / "a.txt"), [])
        self.assertIn("No folders have been granted", str(caught.exception))


class CredentialTests(Base):
    def test_env_file_is_refused_even_inside_a_granted_root(self):
        """The whole point: granting a project folder must not hand over the
        API keys sitting in it."""
        self.write(".env", "OPENROUTER_API_KEY=sk-live-realkey")
        with self.assertRaises(fa.FileAccessError) as caught:
            fa.read_text(str(self.dir / ".env"), self.roots)
        message = str(caught.exception)
        self.assertIn("credential file", message)
        self.assertNotIn("sk-live-realkey", message)  # never echo the secret

    def test_private_keys_and_certificates_are_refused(self):
        for name in ("id_rsa", "server.pem", "cert.key", "store.p12", ".env.production"):
            self.write(name, "SENSITIVE")
            with self.assertRaises(fa.FileAccessError, msg=name):
                fa.read_text(str(self.dir / name), self.roots)

    def test_credentials_directory_is_refused_by_path(self):
        self.write(".ssh/config", "Host example")
        with self.assertRaises(fa.FileAccessError) as caught:
            fa.read_text(str(self.dir / ".ssh" / "config"), self.roots)
        self.assertIn("credentials or profile directory", str(caught.exception))

    def test_denied_files_are_reported_not_silently_dropped(self):
        """A skipped secret must be visible as skipped, so nobody concludes the
        file was empty."""
        self.write(".env", "KEY=1")
        result = fa.find_files(".env", self.roots)
        self.assertEqual(result.matches, [])
        self.assertTrue(any("credential" in s.reason for s in result.skipped))

    def test_writing_a_credential_file_is_refused(self):
        with self.assertRaises(fa.FileAccessError):
            fa.write_text(str(self.dir / ".env"), "KEY=2", self.roots)

    def test_credential_directories_match_whole_components_only(self):
        """A folder merely CONTAINING a deny word in its name is not a
        credential store. Substring matching on the joined path blocked
        innocent files like cookies-recipes/notes.md; whole-component
        matching is what actually distinguishes the two."""
        self.write("cookies-recipes/notes.md", "flour, butter")
        out = fa.read_text(str(self.dir / "cookies-recipes" / "notes.md"), self.roots)
        self.assertIn("flour", out["content"])

        self.write("my-credentials-course/lecture.md", "week 1")
        out = fa.read_text(str(self.dir / "my-credentials-course" / "lecture.md"), self.roots)
        self.assertIn("week 1", out["content"])

    def test_multi_component_credential_paths_are_still_refused(self):
        self.write(".config/gcloud/token.json", "{}")
        with self.assertRaises(fa.FileAccessError):
            fa.read_text(str(self.dir / ".config" / "gcloud" / "token.json"), self.roots)

    def test_ordinary_dotfiles_are_still_readable(self):
        """The deny-list must not swallow every dotfile -- .gitignore and
        .eslintrc are ordinary project files."""
        self.write(".gitignore", "node_modules/")
        out = fa.read_text(str(self.dir / ".gitignore"), self.roots)
        self.assertIn("node_modules", out["content"])


class BoundsTests(Base):
    def test_binary_files_are_refused(self):
        p = self.dir / "image.bin"
        p.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")
        with self.assertRaises(fa.FileAccessError) as caught:
            fa.read_text(str(p), self.roots)
        self.assertIn("binary", str(caught.exception))

    def test_large_files_are_truncated_not_refused(self):
        self.write("big.txt", "x" * 2000)
        out = fa.read_text(str(self.dir / "big.txt"), self.roots, max_bytes=100)
        self.assertTrue(out["truncated"])
        self.assertEqual(len(out["content"]), 100)
        self.assertEqual(out["bytes"], 2000)

    def test_dependency_directories_are_not_walked(self):
        self.write("node_modules/pkg/index.js", "needle here")
        self.write("src/app.js", "needle here")
        result = fa.search_contents("needle", self.roots)
        paths = [m["path"] for m in result.matches]
        self.assertTrue(any("app.js" in p for p in paths))
        self.assertFalse(any("node_modules" in p for p in paths))

    def test_search_requires_a_real_query(self):
        with self.assertRaises(fa.FileAccessError):
            fa.search_contents("a", self.roots)


class SearchTests(Base):
    def test_finds_files_by_name(self):
        self.write("essays/Key-Club-Essay.md", "# draft")
        result = fa.find_files("key club essay", self.roots)
        self.assertEqual(len(result.matches), 1)
        self.assertEqual(result.matches[0]["name"], "Key-Club-Essay.md")

    def test_content_search_returns_real_line_numbers(self):
        self.write("notes.md", "alpha\nbeta\nthe mitochondria is the powerhouse\ndelta")
        result = fa.search_contents("mitochondria", self.roots)
        self.assertEqual(len(result.matches), 1)
        hit = result.matches[0]["hits"][0]
        self.assertEqual(hit["line"], 3)
        self.assertIn("powerhouse", hit["text"])

    def test_listing_marks_restricted_files_without_reading_them(self):
        self.write("readme.md", "# hi")
        self.write(".env", "KEY=1")
        entries = {e["name"]: e for e in fa.list_directory(str(self.dir), self.roots)}
        self.assertFalse(entries["readme.md"]["restricted"])
        self.assertTrue(entries[".env"]["restricted"])


class WriteTests(Base):
    def test_writes_inside_a_granted_root(self):
        out = fa.write_text(str(self.dir / "out" / "answer.md"), "# worked example", self.roots)
        self.assertTrue(Path(out["path"]).is_file())
        self.assertEqual(Path(out["path"]).read_text(encoding="utf-8"), "# worked example")

    def test_refuses_to_write_outside_a_granted_root(self):
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(fa.FileAccessError):
                fa.write_text(str(Path(other, "x.txt")), "nope", self.roots)


if __name__ == "__main__":
    unittest.main()
