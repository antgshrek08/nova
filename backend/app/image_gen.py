"""Real image generation (task 9: "wire real image generation into Chat...
using the already-integrated Qwen-Image/FLUX pipeline" -- turned out nothing
was actually integrated; routing.py only had a scaffold chain naming those
two models, with the "diffusion" provider hardcoded permanently
unavailable, and no image model was ever downloaded. Built for real here,
using a small SD-Turbo model instead of Qwen-Image/FLUX -- see
image_gen_worker.py's docstring for why: this machine has no CUDA GPU, and
those two are 12-20B+ param models that would take minutes per image on
CPU, versus SD-Turbo's ~2-4 seconds.

Runs as a subprocess in a separate venv (backend/.venv-imagegen), not an
in-process import -- the main venv's diffusers==0.29.0 cannot import ANY
image pipeline under its installed transformers==5.2.0 (a real
ImportError), and upgrading diffusers in-place risked regressing Chatterbox
TTS, which also depends on it and was already verified working this
session. The subprocess boundary trades a small amount of per-call
overhead (~1-2s Python startup) for zero risk to the existing TTS pipeline.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_IMAGEGEN_PYTHON = _BACKEND_DIR / ".venv-imagegen" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
_WORKER_SCRIPT = Path(__file__).resolve().parent / "image_gen_worker.py"


class ImageGenUnavailable(Exception):
    pass


def is_available() -> bool:
    return _IMAGEGEN_PYTHON.exists()


async def generate_image(prompt: str, timeout: float = 300.0) -> bytes:
    """Runs the isolated-venv worker as a subprocess and returns real PNG
    bytes. Raises ImageGenUnavailable if the isolated venv wasn't set up, or
    RuntimeError with the worker's stderr on a genuine generation failure --
    callers should surface either as a real chat error, never silently fall
    back to describing an image in text instead of generating one."""
    if not is_available():
        raise ImageGenUnavailable(
            "Image generation isn't set up on this machine (backend/.venv-imagegen is missing)."
        )
    with tempfile.TemporaryDirectory() as tmp:
        output_path = Path(tmp) / "generated.png"
        proc = await asyncio.create_subprocess_exec(
            str(_IMAGEGEN_PYTHON),
            str(_WORKER_SCRIPT),
            prompt,
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"Image generation timed out after {timeout}s.")
        if proc.returncode != 0 or not output_path.exists():
            raise RuntimeError(
                f"Image generation failed (exit {proc.returncode}): {stderr.decode(errors='replace')[-2000:]}"
            )
        return output_path.read_bytes()
