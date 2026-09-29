import io
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from fastapi import HTTPException, UploadFile
from app import ide, config

class IdeChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch.object(config, "get_workspace_dir", return_value=self.root)
        self.patch.start()

    async def asyncTearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    async def test_import_conflict_does_not_partially_write(self):
        (self.root / "keep.py").write_text("original")
        with self.assertRaises(HTTPException) as raised:
            await ide.import_files([UploadFile(filename="new.py", file=io.BytesIO(b"new")), UploadFile(filename="keep.py", file=io.BytesIO(b"replace"))], "")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertFalse((self.root / "new.py").exists())
        self.assertEqual((self.root / "keep.py").read_text(), "original")

    async def test_folder_rename_and_import(self):
        await ide.create_folder({"path": "src/nested"})
        result = await ide.import_files([UploadFile(filename="app.py", file=io.BytesIO(b"print('ok')"))], "src/nested")
        self.assertEqual(result["paths"], ["src/nested/app.py"])
        await ide.rename_path({"path": "src", "new_path": "source"})
        self.assertTrue((self.root / "source/nested/app.py").exists())

    async def test_paths_cannot_escape_or_mutate_git(self):
        for path in ("../outside", ".git/config", ""):
            with self.assertRaises(HTTPException):
                await ide.create_folder({"path": path})

    async def test_rename_does_not_overwrite(self):
        (self.root / "a").write_text("a")
        (self.root / "b").write_text("b")
        with self.assertRaises(HTTPException):
            await ide.rename_path({"path": "a", "new_path": "b"})
        self.assertEqual((self.root / "a").read_text(), "a")
        self.assertEqual((self.root / "b").read_text(), "b")

    # Git used to live in ide.py and was tested here. It moved to git_panel.py,
    # which replaced it with history, branches, per-file discard and
    # NUL-delimited parsing; those tests moved with it to test_git_panel.py.

if __name__ == "__main__":
    unittest.main()
