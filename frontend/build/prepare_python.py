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

# The oldest systems the installers support (see DEVICES.md). Without these,
# the installer picks each library's newest build for the machine it's built
# on -- and a build machine on the latest macOS quietly makes Nova need it.
# macOS 13.5 Ventura: every Mac from 2020 (and most from 2017-18) can run it.
# Not lower, because Playwright's bundled Node.js needs 13.5.
MACOS_TARGET = "13.5"
LINUX_GLIBC = "2_28"         # Ubuntu 20.04, Debian 10, Fedora 29, RHEL 8 and newer


COMPILED = ("av", "numpy", "onnxruntime", "orjson", "ctranslate2", "tokenizers", "grpcio", "protobuf",
            "pydantic-core", "cryptography", "pillow", "psutil", "chroma-hnswlib", "chromadb", "greenlet",
            "uvloop", "watchfiles", "httptools", "websockets", "yarl", "multidict", "frozenlist", "aiohttp",
            "tiktoken", "regex", "jiter", "rpds-py", "sympy", "soundfile", "cffi", "zstandard", "pyyaml")


def platform_args() -> tuple[list[str], dict]:
    """uv flags and environment that pin the library builds to those targets."""
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
        # Compiled libraries must come as ready-made builds for that macOS; if
        # the newest version has none, uv picks the newest version that does,
        # instead of compiling one for the build machine's macOS.
        no_build = [arg for pkg in COMPILED for arg in ("--only-binary", pkg)]
        overrides = []
        if arch == "x86_64":
            # cryptography stopped publishing Intel Mac builds after 48, but the
            # Gmail/Calendar helper asks for 50+. 48 is the newest an Intel Mac
            # can run; the release build checks the helper starts with it.
            path = Path(tempfile.gettempdir()) / "nova-intel-overrides.txt"
            path.write_text("cryptography==48.0.0\n", encoding="utf-8")
            overrides = ["--override", str(path)]
        return ["--python-platform", f"{arch}-apple-darwin", *no_build, *overrides], {"MACOSX_DEPLOYMENT_TARGET": MACOS_TARGET}
    if sys.platform.startswith("linux"):
        arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
        return ["--python-platform", f"{arch}-manylinux_{LINUX_GLIBC}"], {}
    return [], {}


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
    extra, extra_env = platform_args()
    env = {**os.environ, **extra_env}
    try:
        run(uv, "pip", "install", "--python", exe, "--system", *extra, "-r", req_file, env=env)
    finally:
        os.unlink(req_file)
    # Nova checks a fix to its own code by running its tests (app/selfcheck.py),
    # so the installed copy carries them and the tool that runs them.
    run(uv, "pip", "install", "--python", exe, "--system", *extra, "pytest", "pytest-asyncio", env=env)
    # Proof, not hope: every compiled file must run on the oldest supported system.
    run(exe, Path(__file__).with_name("check_min_os.py"), TARGET, MACOS_TARGET, LINUX_GLIBC.replace("_", "."))
    run(exe, BACKEND / "download_models.py", "--no-voice")
    run(exe, "-c", "import sys; sys.path.insert(0, 'backend'); from app import main; print('Nova imports on', sys.version)",
        cwd=ROOT)
    print(f"Ready: {TARGET} ({platform.system()} {platform.machine()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
