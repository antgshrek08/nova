"""Download the wake-word model and, if you want it, the offline voice.

    python backend/download_models.py          # asks about the offline voice
    python backend/download_models.py --voice  # yes to the offline voice
    python backend/download_models.py --no-voice

Neither is part of Nova's repository or installers. Without them Nova still
works: the online voices speak, and the wake word stays off until its model
is here. Safe to re-run; files already present are skipped.

The offline "Ryan" voice is someone else's work under its own terms: the
Piper engine is GPL-3.0 and the voice was trained on data licensed
CC BY-NC-SA 4.0 (non-commercial). Installing it is your choice, for your own
computer.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

MODELS = Path(__file__).resolve().parent / "models"
PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/ryan/medium/"
VOSK = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
VOICE_TERMS = """
The offline voice ("Ryan") lets Nova speak without internet.
  - Engine: Piper (piper-tts), GPL-3.0
  - Voice: trained on the RyanSpeech dataset, CC BY-NC-SA 4.0 (non-commercial use only)
It is optional: without it Nova uses the online voices.
"""


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


def want_voice(argv: list[str]) -> bool:
    if "--voice" in argv:
        return True
    if "--no-voice" in argv or not sys.stdin.isatty():
        return False
    print(VOICE_TERMS)
    return input("Install the offline voice? [y/N] ").strip().lower().startswith("y")


def main(argv: list[str]) -> int:
    print('Wake word ("Hey Nova") -- Vosk small English model, Apache-2.0')
    folder = MODELS / "vosk-model-small-en-us-0.15"
    if folder.is_dir():
        print(f"  have {folder.name}")
    else:
        archive = MODELS / "vosk-model-small-en-us-0.15.zip"
        fetch(VOSK, archive)
        with zipfile.ZipFile(archive) as z:
            z.extractall(MODELS)
        archive.unlink()

    if want_voice(argv):
        print("Offline voice (Ryan)")
        if importlib.util.find_spec("piper") is None:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "piper-tts==1.8.0"])
        for name in ("en_US-ryan-medium.onnx", "en_US-ryan-medium.onnx.json"):
            fetch(PIPER + name, MODELS / "piper" / name)
    else:
        print("Skipped the offline voice. Run this again with --voice to add it.")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
