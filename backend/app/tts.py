"""Real text-to-speech via Chatterbox (Resemble AI, MIT-licensed), running
fully locally -- no API key, no external service, no per-call cost.

The model downloads once from Hugging Face on first use (cached in the
user's normal HF cache dir) and all inference runs on this machine's CPU
(no CUDA-capable GPU here; see config.CHATTERBOX_DEVICE). Loading and
inference are both synchronous, CPU-bound PyTorch work -- both are run in a
worker thread via asyncio.to_thread rather than on the event loop, since a
multi-second block there would stall every other in-flight request (chat
streams, the agents websocket) for as long as synthesis takes.

Voices (Settings > Voice, see db.tts_voices / main.py's /tts/voices routes):
Chatterbox ships exactly one built-in voice (downloaded as part of the model
itself, used when no reference audio is given) -- there is no library of
named preset voices to pick from, so "voice_id" here is either the sentinel
"default" (the shipped voice) or the integer id of a user-cloned voice, whose
reference clip lives on disk at config.VOICES_DIR/<audio_filename> and is
passed to Chatterbox as audio_prompt_path for real zero-shot voice cloning.

Turbo mode (config.CHATTERBOX_TURBO, off by default): resemble-ai's own
smaller/faster ChatterboxTurboTTS class, loaded instead of the base model --
see _load_model() and config.py's comment there for why this needed its own
flag rather than being a parameter on the base model.

Correctly verified live 2026-09-03 (an earlier same-day pass claimed this
was tested but had edited backend/.env, which config.py only ever copies
from on first run -- config.ENV_PATH is actually ~/.ai-council/.env, so
that pass was unknowingly comparing the base model against itself the
whole time; see RESEARCH.md's correction entry). With CHATTERBOX_TURBO
genuinely on this time:
- **Real speed win, not modest**: ~34.8s warm on the base model vs.
  ~20-23s warm on Turbo for the same ~160-char reply, default voice --
  roughly 35-40% faster, not the ~9% the invalid earlier test claimed.
- **A real incompatibility, not "verified working" as the earlier pass
  claimed**: ChatterboxTurboTTS enforces a hard minimum reference-clip
  length ("Audio prompt must be longer than 5 seconds!") that the base
  model doesn't -- both of this app's existing cloned voices (2.8s and
  3.8s clips) are too short and 503 outright under Turbo. Turbo only
  works with the "default" built-in voice, or a freshly-cloned reference
  clip recorded/sourced at over 5 seconds, until/unless a shorter clip is
  re-recorded specifically for it.
- **CHATTERBOX_TURBO_NANO is currently unusable, not "tested no faster"
  as the earlier pass claimed**: the installed 0.1.7 wheel's
  ChatterboxTurboTTS.from_pretrained() doesn't accept a nano= argument at
  all (see _load_model()'s inspect.signature guard) -- the earlier nano
  test never actually loaded Turbo either, so its "no faster than plain
  Turbo" conclusion was equally invalid, not just imprecise.

Left CHATTERBOX_TURBO=false in the real config (~/.ai-council/.env) given
the voice-length incompatibility would otherwise break the currently
configured cloned voice outright -- flip it on deliberately once either
using the default voice is acceptable, or a new >5s reference clip has
been cloned.
"""
from __future__ import annotations

import asyncio
import io
import logging

from . import config, db

logger = logging.getLogger(__name__)

_model = None
_model_lock = asyncio.Lock()
# Chatterbox's generate() mutates the shared model's conditioning state
# in-place when audio_prompt_path is given (self.conds), so two synthesis
# calls racing on different voices in different worker threads could each
# see the other's conditioning mid-generate. Serializing synthesis avoids
# that; it costs nothing extra in practice since this is a single-user app
# and one CPU synthesis already saturates the machine.
_synthesis_lock = asyncio.Lock()

DEFAULT_VOICE_ID = "default"


class TTSUnavailableError(RuntimeError):
    """Raised when speech synthesis can't be served (model load/inference failure)."""


def _load_model():
    # Integration-plan Phase 1b: Turbo is a genuinely separate model class
    # (ChatterboxTurboTTS), not a parameter on the base ChatterboxTTS -- see
    # config.CHATTERBOX_TURBO's comment for why. Gated behind that flag so
    # the default path (what's actually been running and verified so far)
    # is completely untouched when it's off.
    if config.CHATTERBOX_TURBO:
        try:
            from chatterbox.tts_turbo import ChatterboxTurboTTS  # heavy import, deferred to the worker thread
        except ImportError as exc:
            raise TTSUnavailableError(
                "CHATTERBOX_TURBO is on, but this Python environment's chatterbox-tts package "
                "doesn't have the tts_turbo module (the 0.1.7 pin in requirements.txt does have "
                "it, confirmed 2026-09-03 -- so this likely means a different/older install). Run "
                "`.venv\\Scripts\\pip install --upgrade chatterbox-tts` in backend/, or set "
                "CHATTERBOX_TURBO=false in .env to go back to the base model."
            ) from exc
        # Real bug found live 2026-09-03 (RESEARCH.md): the installed 0.1.7
        # wheel's ChatterboxTurboTTS.from_pretrained() only accepts `device`
        # -- no `nano` parameter at all, unlike resemble-ai's GitHub `master`
        # branch this was originally written against (a real version-drift
        # risk the earlier session flagged but, since CHATTERBOX_TURBO had
        # never actually loaded yet at that point -- see the .env location
        # bug this same research pass found -- never got to verify). Only
        # pass nano= when the installed signature actually supports it, so
        # the common case (nano off) works regardless of which installed
        # version is present, and turning nano on gives a clear error
        # instead of a confusing TypeError when it isn't supported.
        kwargs = {"device": config.CHATTERBOX_DEVICE}
        if config.CHATTERBOX_TURBO_NANO:
            import inspect

            if "nano" in inspect.signature(ChatterboxTurboTTS.from_pretrained).parameters:
                kwargs["nano"] = True
            else:
                raise TTSUnavailableError(
                    "CHATTERBOX_TURBO_NANO is on, but this installed chatterbox-tts version's "
                    "ChatterboxTurboTTS.from_pretrained() doesn't accept a nano= argument. Set "
                    "CHATTERBOX_TURBO_NANO=false, or upgrade chatterbox-tts if a version with "
                    "nano support becomes available."
                )
        return ChatterboxTurboTTS.from_pretrained(**kwargs)

    from chatterbox.tts import ChatterboxTTS  # heavy import, deferred to the worker thread

    return ChatterboxTTS.from_pretrained(device=config.CHATTERBOX_DEVICE)


async def _get_model():
    global _model
    if _model is not None:
        return _model
    async with _model_lock:
        if _model is None:  # re-check: another request may have loaded it while we waited
            try:
                _model = await asyncio.to_thread(_load_model)
            except ModuleNotFoundError as exc:
                # The packaged build drops torch from the main venv (3.4GB of
                # it, and the installer already carries a second torch for
                # image generation), so cloned voices are a dev-only feature
                # there. Say that, rather than let a bare "No module named
                # torch" look like a broken install.
                raise TTSUnavailableError(
                    f"Cloned voices need a package this build does not ship ({exc.name}). "
                    "The default voice works; cloned voices are available when running "
                    "Nova from source."
                ) from exc
            except Exception as exc:  # noqa: BLE001
                raise TTSUnavailableError(f"Failed to load the local Chatterbox TTS model: {exc}") from exc
    return _model


async def resolve_voice_prompt_path(voice_id: str | None) -> str | None:
    """None/"default" -> Chatterbox's built-in voice (no reference file).
    Otherwise looks up the cloned voice's reference clip on disk."""
    if not voice_id or voice_id == DEFAULT_VOICE_ID:
        return None
    try:
        row_id = int(voice_id)
    except ValueError:
        raise TTSUnavailableError(f"Unknown voice id '{voice_id}'.")
    voice = await db.get_tts_voice(row_id)
    if voice is None:
        raise TTSUnavailableError(f"Voice {voice_id} no longer exists -- pick another in Settings > Voice.")
    path = config.VOICES_DIR / voice["audio_filename"]
    if not path.exists():
        raise TTSUnavailableError(f"Reference clip for voice '{voice['name']}' is missing on disk.")
    return str(path)


def _synthesize_sync(model, text: str, audio_prompt_path: str | None) -> bytes:
    import soundfile as sf

    kwargs = {"audio_prompt_path": audio_prompt_path} if audio_prompt_path else {}
    wav = model.generate(text, **kwargs)
    audio = wav.squeeze(0).detach().cpu().numpy()
    buffer = io.BytesIO()
    sf.write(buffer, audio, samplerate=model.sr, format="WAV")
    return buffer.getvalue()


async def synthesize_speech(text: str, voice_id: str | None = None) -> bytes:
    text = text.strip()
    if not text:
        raise TTSUnavailableError("No text to speak.")
    
    # Which engine speaks: Chatterbox for its own voice and for cloned voices
    # (integer ids); fast_speech for everything else -- an online voice from
    # its catalog, or the offline Ryan voice ("default", or anything unknown).
    uses_chatterbox = voice_id == "chatterbox-default" or (voice_id or "").isdigit()
    if not uses_chatterbox:
        from . import fast_speech
        try:
            audio = await fast_speech.synthesize(text, voice=voice_id)
            if audio:
                return audio
        except Exception as exc:
            logger.warning(f"Fast speech synthesis failed: {exc}")
        # No online voice and no offline Ryan model: Chatterbox's own voice.
        voice_id = DEFAULT_VOICE_ID

    if voice_id == "chatterbox-default":
        voice_id = DEFAULT_VOICE_ID
    audio_prompt_path = await resolve_voice_prompt_path(voice_id)
    model = await _get_model()
    try:
        async with _synthesis_lock:
            return await asyncio.to_thread(_synthesize_sync, model, text, audio_prompt_path)
    except Exception as exc:  # noqa: BLE001
        raise TTSUnavailableError(f"Local speech synthesis failed: {exc}") from exc
