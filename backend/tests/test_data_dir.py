"""NOVA_DATA_DIR moves everything Nova keeps (the test copy relies on this)."""
import json
import os
import subprocess
import sys
from pathlib import Path


def test_everything_follows_nova_data_dir(tmp_path):
    env = {**os.environ, "NOVA_DATA_DIR": str(tmp_path / "data")}
    env.pop("DB_PATH", None)
    env.pop("CHROMA_DIR", None)
    env.pop("OBSIDIAN_VAULT_DIR", None)
    code = ("import json; from app import config, canvas_sync, calendar_sources;"
            "print(json.dumps([str(p) for p in (config.USER_DATA_DIR, config.ENV_PATH, config.DB_PATH, config.CHROMA_DIR,"
            " config.OBSIDIAN_VAULT_DIR, config.VOICES_DIR, config.CLI_WORKSPACE_DIR, canvas_sync.CALENDAR_PATH)]))")
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    paths = json.loads(out.stdout.strip().splitlines()[-1])
    root = str(tmp_path / "data")
    assert all(p.startswith(root) for p in paths), paths
