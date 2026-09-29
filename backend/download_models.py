"""Download the offline voice and wake-word models into backend/models.

    python backend/download_models.py

They are too large for the repository. Without them Nova still works: the
online voices speak instead of the offline one, and the wake word stays off
until the model is here. Safe to re-run; files already present are skipped.
"""
from __future__ import annotations

import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

MODELS = Path(__file__).resolve().parent / "models"
PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/ryan/medium/"
VOSK = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"


def fetch(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  have {dest.name}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  getting {dest.name} ...", flush=True)
    part = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as response, open(part, "wb") as out:  # noqa: S310 -- fixed https URLs
        shutil.copyfileobj(response, out)
    part.replace(dest)


def main() -> int:
    print("Offline voice (Ryan)")
    for name in ("en_US-ryan-medium.onnx", "en_US-ryan-medium.onnx.json"):
        fetch(PIPER + name, MODELS / "piper" / name)

    print("Wake word (\"Hey Nova\")")
    folder = MODELS / "vosk-model-small-en-us-0.15"
    if folder.is_dir():
        print(f"  have {folder.name}")
    else:
        archive = MODELS / "vosk-model-small-en-us-0.15.zip"
        fetch(VOSK, archive)
        with zipfile.ZipFile(archive) as z:
            z.extractall(MODELS)
        archive.unlink()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
