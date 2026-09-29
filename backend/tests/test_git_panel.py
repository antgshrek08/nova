"""git_panel against a real repository in a temp directory.

Ported from test_ide, which tested an earlier git implementation inside ide.py
that has since been deleted -- git_panel replaced it with history, branches,
per-file discard and NUL-delimited parsing. Tests run against real `git`
rather than mocking it: every bug this code has actually had came from
misreading git's output format, which a mock would have cheerfully agreed with.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from app import git_panel


def _has_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True, timeout=30)
        return True
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_has_git(), "git is not installed")
class GitPanelChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for args in (["init", "-b", "main"],
                     ["config", "user.email", "test@example.com"],
                     ["config", "user.name", "Test"],
                     ["config", "commit.gpgsign", "false"]):
            subprocess.run(["git", *args], cwd=self.root, capture_output=True, check=True)
        self.path = str(self.root)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_a_directory_that_is_not_a_repo_says_so_instead_of_failing(self):
        with tempfile.TemporaryDirectory() as plain:
            result = await git_panel.status(plain)
            self.assertFalse(result["is_repo"])
            self.assertIn("root", result)

    async def test_stage_diff_and_unstage_without_committing(self):
        (self.root / "example.py").write_text("print('new')\n", encoding="utf-8")

        untracked = await git_panel.status(self.path)
        self.assertTrue(untracked["files"][0]["untracked"])

        staged = await git_panel.stage(["example.py"], self.path)
        entry = next(f for f in staged["files"] if f["path"] == "example.py")
        self.assertTrue(entry["staged"], "file should be reported as staged")

        diff = await git_panel.diff(self.path, "example.py", staged=True)
        self.assertIn("+print('new')", diff["diff"])

        await git_panel.unstage(["example.py"], self.path)
        self.assertTrue((self.root / "example.py").exists(),
                        "unstaging must never delete the working copy")

    async def test_commit_then_history_shows_it(self):
        (self.root / "a.txt").write_text("one\n", encoding="utf-8")
        await git_panel.commit("first commit", self.path, stage_all=True)

        history = await git_panel.log(self.path, limit=5)
        self.assertEqual(history["commits"][0]["subject"], "first commit")
        self.assertTrue(history["commits"][0]["short"])

        after = await git_panel.status(self.path)
        self.assertTrue(after["clean"], "working tree should be clean after committing everything")

    async def test_a_commit_message_is_never_parsed_as_arguments(self):
        """Messages go in on stdin via -F -, so a message that looks like flags
        is stored verbatim rather than changing what git does."""
        (self.root / "b.txt").write_text("two\n", encoding="utf-8")
        hostile = "--amend --author=someone <e@x> -m injected"
        await git_panel.commit(hostile, self.path, stage_all=True)

        history = await git_panel.log(self.path, limit=5)
        self.assertEqual(history["commits"][0]["subject"], hostile)
        self.assertEqual(len(history["commits"]), 1, "must not have amended anything away")

    async def test_awkward_filenames_survive_parsing(self):
        """--porcelain=v1 -z is used precisely so these do not need escaping;
        the older line-based parser mangled them. (No double quotes here -- NTFS
        forbids them in filenames, so git's own quoting path can't be reached
        that way on Windows; spaces, an apostrophe and non-ASCII are what a
        real user actually produces.)"""
        awkward = "a file with spaces, an apostrophe' and é.txt"
        (self.root / awkward).write_text("x\n", encoding="utf-8")

        result = await git_panel.status(self.path)
        self.assertIn(awkward, [f["path"] for f in result["files"]])

        staged = await git_panel.stage([awkward], self.path)
        self.assertTrue(next(f for f in staged["files"] if f["path"] == awkward)["staged"])

    async def test_discard_restores_a_tracked_file(self):
        target = self.root / "c.txt"
        target.write_text("original\n", encoding="utf-8")
        await git_panel.commit("add c", self.path, stage_all=True)

        target.write_text("ruined\n", encoding="utf-8")
        await git_panel.discard(["c.txt"], self.path)
        self.assertEqual(target.read_text(encoding="utf-8"), "original\n")

    async def test_branches_can_be_created_and_switched(self):
        (self.root / "d.txt").write_text("d\n", encoding="utf-8")
        await git_panel.commit("base", self.path, stage_all=True)

        await git_panel.create_branch("feature", self.path)
        listed = await git_panel.branches(self.path)
        names = [b["name"] for b in listed["branches"]]
        self.assertIn("feature", names)
        self.assertEqual(next(b for b in listed["branches"] if b["current"])["name"], "feature")

        await git_panel.switch_branch("main", self.path)
        back = await git_panel.branches(self.path)
        self.assertEqual(next(b for b in back["branches"] if b["current"])["name"], "main")

    async def test_the_panel_offers_no_way_to_push_or_hard_reset(self):
        """Deliberate: those either lose work or touch a shared remote, and a
        button is the wrong affordance. The Terminal tab exists for meaning it."""
        for forbidden in ("push", "force_push", "hard_reset", "delete_branch", "reset"):
            self.assertFalse(hasattr(git_panel, forbidden),
                             f"git_panel should not expose {forbidden}")


if __name__ == "__main__":
    unittest.main()
