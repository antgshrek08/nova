"""What Ship claims about a project, and what it refuses to claim.

The panel's whole value is that its answers are true. It says "ready to ship"
or lists what is in the way, so a wrong answer here is worse than no panel --
particularly the two ways it can be confidently wrong: inheriting another
project's build result, and implying a deploy provider is available when
none is connected.
"""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import ship


def run(coro):
    return asyncio.run(coro)


class Detection(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)

    def test_a_vite_project_is_recognised_with_its_build_command(self):
        (self.root / "package.json").write_text(
            '{"name":"thing","devDependencies":{"vite":"5.0.0"},"scripts":{"build":"vite build"}}',
            encoding="utf-8",
        )
        found = ship.detect_project(self.root)
        self.assertEqual(found["framework"], "vite")
        self.assertEqual(found["build_command"], "npm run build")
        self.assertEqual(found["name"], "thing")

    def test_deploy_config_files_are_reported_as_facts(self):
        """Presence of vercel.json is a fact about the repo, not a guess."""
        (self.root / "vercel.json").write_text("{}", encoding="utf-8")
        (self.root / "Dockerfile").write_text("FROM scratch", encoding="utf-8")
        markers = ship.detect_project(self.root)["markers"]
        self.assertIn("Vercel", markers)
        self.assertIn("Docker", markers)

    def test_a_folder_with_nothing_in_it_claims_nothing(self):
        found = ship.detect_project(self.root)
        self.assertIsNone(found["framework"])
        self.assertIsNone(found["build_command"])
        self.assertEqual(found["markers"], [])


class BuildIsScopedToItsProject(unittest.TestCase):
    def setUp(self):
        ship._build.update({"running": False, "started": 0.0, "finished": 0.0,
                            "root": None, "ok": None, "code": None,
                            "output": [], "command": None})

    def test_another_projects_result_is_not_shown(self):
        """Seen live: an empty sandbox with no build command at all reported
        a passing npm build inherited from a different folder."""
        ship._build.update({"root": r"C:\projects\one", "ok": True, "code": 0,
                            "command": "npm run build", "output": ["built"]})
        elsewhere = ship.build_status(Path(r"C:\projects\two"))
        self.assertIsNone(elsewhere["ok"])
        self.assertIsNone(elsewhere["command"])
        self.assertEqual(elsewhere["output"], [])

    def test_its_own_result_is_shown(self):
        ship._build.update({"root": r"C:\projects\one", "ok": True, "code": 0,
                            "command": "npm run build", "output": ["built"]})
        mine = ship.build_status(Path(r"C:\projects\one"))
        self.assertTrue(mine["ok"])
        self.assertEqual(mine["command"], "npm run build")


class Blockers(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)
        ship._build.update({"root": None, "ok": None, "output": [], "command": None})

    async def _status(self, git_status, remote, providers):
        with mock.patch.object(ship.git_panel, "status", mock.AsyncMock(return_value=git_status)), \
             mock.patch.object(ship.git_panel, "_git", mock.AsyncMock(return_value=remote or "")), \
             mock.patch.object(ship, "_providers", mock.AsyncMock(return_value=providers)):
            return await ship.status(str(self.root))

    async def test_no_connected_provider_is_always_a_blocker(self):
        """The panel must never imply a deploy target that is not there."""
        result = await self._status(
            {"is_repo": True, "branch": "main", "ahead": 0, "entries": []},
            "https://example.com/repo.git",
            [{"name": "Vercel", "provider": "vercel", "enabled": False}],
        )
        self.assertFalse(result["ready"])
        self.assertTrue(any("No deploy provider connected" in b for b in result["blockers"]))

    async def test_uncommitted_and_unpushed_work_are_named_separately(self):
        result = await self._status(
            {"is_repo": True, "branch": "main", "ahead": 2, "entries": [{}, {}, {}]},
            "https://example.com/repo.git",
            [],
        )
        joined = " ".join(result["blockers"])
        self.assertIn("3 uncommitted changes", joined)
        # Unpushed is only worth saying once the work is committed; with a
        # dirty tree the commit step comes first.
        self.assertIn("2 commits not pushed", joined)

    async def test_a_missing_remote_is_reported_instead_of_unpushed_commits(self):
        """"2 commits not pushed" is misleading when there is nowhere to push."""
        result = await self._status(
            {"is_repo": True, "branch": "main", "ahead": 2, "entries": []}, "", [],
        )
        joined = " ".join(result["blockers"])
        self.assertIn("No git remote", joined)
        self.assertNotIn("not pushed", joined)

    async def test_a_clean_repo_with_a_provider_is_ready(self):
        (self.root / "package.json").write_text(
            '{"name":"x","scripts":{"build":"vite build"},"devDependencies":{"vite":"5"}}',
            encoding="utf-8",
        )
        result = await self._status(
            {"is_repo": True, "branch": "main", "ahead": 0, "entries": []},
            "https://example.com/repo.git",
            [{"name": "Vercel", "provider": "vercel", "enabled": True}],
        )
        self.assertEqual(result["blockers"], [])
        self.assertTrue(result["ready"])


class Output(unittest.TestCase):
    def test_colour_codes_are_stripped(self):
        """The panel is not a terminal; raw codes render as "[2mdist/[22m"."""
        raw = "\x1b[2mdist/\x1b[22m\x1b[32mindex.html\x1b[39m  0.49 kB"
        self.assertEqual(ship._ANSI.sub("", raw), "dist/index.html  0.49 kB")


if __name__ == "__main__":
    unittest.main()
