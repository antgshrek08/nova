"""Local speech-to-text via faster-whisper -- replaces the Chat tab's mic
button, which previously used the browser's native Web Speech API
(webkitSpeechRecognition). That API needs a cloud recognition service
Google gates to official Chrome builds; Electron's bundled Chromium isn't
authorized for it, so every attempt in the real packaged/dev app failed
with a "network" error regardless of actual connectivity or mic
permission -- a structural platform limitation, not a fixable bug in how
it was called. This runs entirely locally instead, same "local-first"
approach as tts.py's Chatterbox synthesis.

Record-then-transcribe, not live streaming transcription (the Web Speech
API's old UX implied interim results as you spoke) -- simpler and more
reliable to build and verify in one pass; ChatWindow.jsx's mic button now
records via MediaRecorder, uploads the full clip on stop, and gets one
transcript back.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

# faster-whisper is part of the optional voice install; imported when first
# used so Nova starts without it.
_model = None
_model_lock = asyncio.Lock()


async def get_model():
    global _model
    if _model is not None:
        return _model
    async with _model_lock:
        if _model is not None:
            return _model
        # tiny.en / int8: fast enough to load and run on CPU for
        # command-length dictation (a chat message, not a lecture);
        # accuracy is good enough for this use case, confirmed live against
        # a real synthesized clip during development (one word substituted
        # out of ~25).
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("Speech-to-text isn't installed. Run install.sh (or pip install faster-whisper).") from exc
        _model = await asyncio.to_thread(WhisperModel, "tiny.en", device="cpu", compute_type="int8")
        return _model


async def transcribe(audio_bytes: bytes, suffix: str = ".webm") -> str:
    """Writes `audio_bytes` to a temp file (faster-whisper decodes via
    PyAV, so the exact container/codec the browser recorded in -- webm/
    opus by default from MediaRecorder -- doesn't need pre-conversion) and
    returns the transcribed text, stripped. Raises whatever faster-whisper
    itself raises on genuinely unreadable input; the caller (main.py's
    /stt/transcribe) is expected to surface that as a normal HTTP error."""
    model = await get_model()

    fd, path_str = tempfile.mkstemp(suffix=suffix)
    os.close(fd)  # written by path inside the worker thread below, not through this fd
    path = Path(path_str)
    try:
        # The temp-file write happens inside the worker thread alongside the
        # transcription, not on the event loop. /stt/transcribe accepts up to
        # _STT_UPLOAD_MAX_BYTES (15 MB), and writing that much from the loop
        # stalls every other in-flight request -- including the chat stream
        # the user is waiting on -- for the duration of the write. This is
        # the latency-critical voice path, so it gets the thread.
        def _run() -> str:
            path.write_bytes(audio_bytes)
            segments, _info = model.transcribe(str(path))
            return " ".join(seg.text for seg in segments).strip()

        return await asyncio.to_thread(_run)
    finally:
        path.unlink(missing_ok=True)
