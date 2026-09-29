"""Standalone image-generation worker (task 9: real image generation wired
into Chat). Runs under its own isolated venv (backend/.venv-imagegen), NOT
the main backend venv -- the main venv's diffusers==0.29.0 can't import any
image pipeline at all under its installed transformers==5.2.0 (a hard
ImportError: FLAX_WEIGHTS_NAME was removed upstream). Upgrading diffusers in
the shared venv risked regressing Chatterbox TTS, which also depends on it
and was already verified working this session -- an isolated venv avoids
that risk entirely. This script is invoked as a subprocess from
image_gen.py in the main venv, so it deliberately has zero imports from the
rest of this app's package.

Usage: python image_gen_worker.py <prompt> <output_png_path>
"""
from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: image_gen_worker.py <prompt> <output_png_path>", file=sys.stderr)
        return 2
    prompt, output_path = sys.argv[1], sys.argv[2]

    import torch
    from diffusers import AutoPipelineForText2Image

    # SD-Turbo (real, published, Stability AI, Apache 2.0) -- distilled for
    # 1-4 step inference, chosen specifically so this stays fast enough on
    # CPU to be usable in a chat turnaround on this machine's AMD GPU (no
    # CUDA). guidance_scale=0.0 is SD-Turbo's documented setting: it was
    # distilled without classifier-free guidance, so a nonzero value just
    # wastes a redundant forward pass for no quality gain.
    pipe = AutoPipelineForText2Image.from_pretrained(
        "stabilityai/sd-turbo", torch_dtype=torch.float32
    )
    pipe.to("cpu")
    image = pipe(prompt=prompt, num_inference_steps=2, guidance_scale=0.0).images[0]
    image.save(output_path, format="PNG")
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
