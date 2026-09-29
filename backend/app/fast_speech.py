"""High-performance, ultra-natural Neural voice engine for N.O.V.A.
Features:
- Instant sub-second Edge Neural synthesis (Jenny, Guy, Aria, Christopher, Emma).
- Smart Speech Sanitizer integration (never reads code blocks, errors, tracebacks, or raw math aloud).
- Automatic seamless offline fallback to local Piper ONNX.
"""
from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
import wave

from .speech_sanitizer import clean_for_speech

logger = logging.getLogger(__name__)

_voice = None
_lock = asyncio.Lock()
MODEL_PATH = Path(__file__).resolve().parents[1] / "models/piper/en_US-ryan-medium.onnx"

# The online voices offered in Settings > Voice: (id, Edge voice, label).
# They need an internet connection; without one, speech falls back to the
# offline Ryan voice rather than going silent.
CATALOG = [
    ("ava", "en-US-AvaNeural", "Ava · warm, American"),
    ("andrew", "en-US-AndrewNeural", "Andrew · calm, American"),
    ("emma", "en-US-EmmaNeural", "Emma · bright, American"),
    ("brian", "en-US-BrianNeural", "Brian · easygoing, American"),
    ("jenny", "en-US-JennyNeural", "Jenny · clear, American"),
    ("aria", "en-US-AriaNeural", "Aria · expressive, American"),
    ("guy", "en-US-GuyNeural", "Guy · steady, American"),
    ("christopher", "en-US-ChristopherNeural", "Christopher · deep, American"),
    ("michelle", "en-US-MichelleNeural", "Michelle · friendly, American"),
    ("sonia", "en-GB-SoniaNeural", "Sonia · British"),
    ("thomas", "en-GB-ThomasNeural", "Thomas · British"),
    ("libby", "en-GB-LibbyNeural", "Libby · British"),
    ("natasha", "en-AU-NatashaNeural", "Natasha · Australian"),
    ("william", "en-AU-WilliamMultilingualNeural", "William · Australian"),
]
NEURAL_VOICES = {key: edge for key, edge, _ in CATALOG}


def neural_voice(voice: str | None) -> str | None:
    """The Edge voice for a Settings voice id (or a full Edge name), else None."""
    if not voice:
        return None
    if voice in NEURAL_VOICES:
        return NEURAL_VOICES[voice]
    if voice.endswith("Neural") and "-" in voice:
        return voice
    return None

DEFAULTS = {
    "voice": "en-US-JennyNeural",
    "rate": "+0%",
    "pitch": "+0Hz",
    "volume": "+0%",
    "length_scale": 0.75,
    "noise_scale": 0.72,
    "noise_w_scale": 0.85,
}
_config = dict(DEFAULTS)


def configure(**overrides) -> dict:
    """Set synthesis parameters."""
    for key, value in overrides.items():
        if key in _config and value is not None:
            _config[key] = value
    return dict(_config)


def settings() -> dict:
    return dict(_config)


def _synthesize_piper(text: str, overrides: dict | None = None) -> bytes:
    """Offline Piper fallback synthesis."""
    global _voice
    try:
        from piper import PiperVoice, SynthesisConfig
        if _voice is None and MODEL_PATH.exists():
            _voice = PiperVoice.load(str(MODEL_PATH), use_cuda=False)
        if _voice is None:
            return b""
        values = {
            "length_scale": _config.get("length_scale", 0.75),
            "noise_scale": _config.get("noise_scale", 0.72),
            "noise_w_scale": _config.get("noise_w_scale", 0.85),
            **(overrides or {}),
        }
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            _voice.synthesize_wav(text, output, syn_config=SynthesisConfig(**values))
        return buffer.getvalue()
    except Exception as exc:
        logger.warning("Piper fallback failed: %s", exc)
        return b""


async def _synthesize_edge(text: str, voice: str | None = None) -> bytes:
    """Synthesizes high-fidelity speech using Edge Neural."""
    import edge_tts

    selected_voice = neural_voice(voice) or _config.get("voice", "en-US-JennyNeural")

    rate = _config.get("rate", "+0%")
    pitch = _config.get("pitch", "+0Hz")
    volume = _config.get("volume", "+0%")

    communicate = edge_tts.Communicate(
        text=text,
        voice=selected_voice,
        rate=rate,
        volume=volume,
        pitch=pitch,
    )

    audio_bytes = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_bytes.extend(chunk["data"])

    return bytes(audio_bytes)


def offline_ready() -> bool:
    """The offline Ryan voice is an optional download (download_models.py):
    its engine and model are here."""
    import importlib.util
    return MODEL_PATH.exists() and importlib.util.find_spec("piper") is not None


async def synthesize(text: str, voice: str | None = None) -> bytes:
    """Main speech entrypoint. Sanitizes text, then speaks it in the chosen
    online voice, or in the offline Ryan voice when none was chosen (or the
    online service can't be reached)."""
    cleaned = clean_for_speech(text)
    if not cleaned or not cleaned.strip():
        return b""

    if not neural_voice(voice) and not offline_ready():
        voice = CATALOG[0][0]  # no offline voice installed: speak online instead of not at all

    if neural_voice(voice):
        try:
            audio = await _synthesize_edge(cleaned, voice=voice)
            if audio and len(audio) > 100:
                return audio
        except Exception as exc:
            logger.info("Online voice unavailable (%s), falling back to offline Ryan", exc)

    # 2. Seamless offline fallback to Piper ONNX
    async with _lock:
        return await asyncio.to_thread(_synthesize_piper, cleaned)
