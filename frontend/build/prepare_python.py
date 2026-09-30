"""Give the installer its own Python.

    python frontend/build/prepare_python.py

Puts a self-contained CPython (python-build-standalone, via uv) at
backend/python with Nova's packages installed into it, plus the wake-word
model. The installers ship that folder, so Nova runs on a computer with no
Python at all -- the same way on Windows, macOS and Linux. (A virtualenv
can't be shipped: it points back at the Python it was made from.)

Needs uv (https://docs.astral.sh/uv/). Build on the system you package for.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
TARGET = BACKEND / "python"
VERSION = os.environ.get("NOVA_PYTHON", "3.12")
# Left out of the installers: PyTorch-based voice cloning (~2 GB) and the
# GPL / non-commercial offline voice (see THIRD_PARTY_NOTICES.md).
SKIP = ("chatterbox-tts", "setuptools")


def run(*cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def main() -> int:
    uv = shutil.which("uv")
    if not uv:
        print("uv is required: https://docs.astral.sh/uv/getting-started/installation/")
        return 1
    if TARGET.exists():
        shutil.rmtree(TARGET)
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "UV_PYTHON_INSTALL_DIR": tmp}
        run(uv, "python", "install", VERSION, env=env)
        installed = [p for p in Path(tmp).iterdir() if p.is_dir() and p.name.startswith("cpython-")]
        if not installed:
            print("uv did not install a Python")
            return 1
        shutil.copytree(installed[0], TARGET, symlinks=True)
    exe = TARGET / ("python.exe" if os.name == "nt" else "bin/python3")
    # A standalone build may carry a marker telling pip to keep out; this copy
    # belongs to Nova alone, so it doesn't apply.
    for marker in TARGET.rglob("EXTERNALLY-MANAGED"):
        marker.unlink()

    reqs = [line for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith(SKIP)]
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("\n".join(reqs))
        req_file = f.name
    try:
        run(uv, "pip", "install", "--python", exe, "--system", "-r", req_file)
    finally:
        os.unlink(req_file)
    # Nova checks a fix to its own code by running its tests (app/selfcheck.py),
    # so the installed copy carries them and the tool that runs them.
    run(uv, "pip", "install", "--python", exe, "--system", "pytest", "pytest-asyncio")
    run(exe, BACKEND / "download_models.py", "--no-voice")
    run(exe, "-c", "import sys; sys.path.insert(0, 'backend'); from app import main; print('Nova imports on', sys.version)",
        cwd=ROOT)
    print(f"Ready: {TARGET} ({platform.system()} {platform.machine()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
