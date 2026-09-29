"""Finding Obsidian vaults without asking (app/obsidian_detect.py)."""
import json
from pathlib import Path

from app import obsidian_detect


def _vault(root: Path, name: str, notes: int) -> Path:
    v = root / name
    (v / ".obsidian").mkdir(parents=True)
    for i in range(notes):
        (v / f"note{i}.md").write_text("x", encoding="utf-8")
    return v


def test_finds_obsidian_list_and_synced_vaults_and_skips_missing(tmp_path, monkeypatch):
    home = tmp_path / "home"
    appdata = home / "AppData" / "Roaming"
    listed = _vault(home / "Documents", "School", 3)
    synced = _vault(home / "OneDrive" / "Notes", "Synced", 2)
    (appdata / "obsidian").mkdir(parents=True)
    (appdata / "obsidian" / "obsidian.json").write_text(json.dumps({"vaults": {
        "a": {"path": str(listed), "ts": 5, "open": True},
        "b": {"path": str(home / "Gone"), "ts": 9},
    }}), encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("APPDATA", str(appdata))

    out = obsidian_detect.detect(connected_paths=[str(synced)])
    by_name = {v["name"]: v for v in out["vaults"]}
    assert set(by_name) == {"School", "Synced"}          # the missing one is skipped
    assert by_name["School"]["is_open"] and by_name["School"]["notes"] == 3
    assert by_name["Synced"]["source"] == "found" and by_name["Synced"]["connected"]
    assert out["vaults"][0]["name"] == "School"           # open in Obsidian comes first


def test_nothing_found_is_a_clean_empty_list(tmp_path, monkeypatch):
    home = tmp_path / "empty"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    assert obsidian_detect.detect() == {"detected": False, "vaults": []}


def test_create_vault_makes_an_openable_vault_without_clobbering(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    busy = tmp_path / "Documents" / "Nova Notes"
    busy.mkdir(parents=True)
    (busy / "someone-elses.txt").write_text("x", encoding="utf-8")
    made = obsidian_detect.create_vault()
    assert made["name"] == "Nova Notes 2"
    assert (Path(made["path"]) / ".obsidian").is_dir() and (Path(made["path"]) / "Welcome.md").exists()
    assert obsidian_detect.create_vault()["path"] == made["path"]  # an existing vault is reused
