"""Offline CPU recognition of Nova's actual wake phrases, per audio session."""
import asyncio
import json
from pathlib import Path
import time
import re

MODEL_PATH = Path(__file__).resolve().parents[1] / "models/vosk-model-small-en-us-0.15"
WAKEWORD_SAMPLE_RATE = 16000
WAKEWORD_FRAME_SAMPLES = 1280
WAKEWORD_THRESHOLD = 0.8
PHRASES = {"hey nova", "hi nova", "what's up nova"}
_model = None
_lock = asyncio.Lock()

def matches_phrase(text):
    return re.sub(r"[^a-z' ]", "", text.lower()).strip() in PHRASES

async def get_model():
    global _model
    async with _lock:
        if _model is None:
            if not MODEL_PATH.is_dir():
                raise RuntimeError("Nova wake model is missing. Run: python backend/download_models.py")
            try:
                from vosk import Model, SetLogLevel
            except ImportError as exc:
                raise RuntimeError("Wake word isn't installed. Run install.sh (or pip install vosk).") from exc
            SetLogLevel(-1)
            _model = await asyncio.to_thread(Model, str(MODEL_PATH))
        return _model

class Detector:
    def __init__(self, model):
        from vosk import KaldiRecognizer
        # Unknown-word alternative avoids forcing ordinary speech into a wake phrase.
        self.recognizer = KaldiRecognizer(model, WAKEWORD_SAMPLE_RATE, json.dumps(sorted(PHRASES) + ["[unk]"]))
        self.recognizer.SetWords(True)
        self.last_wake = -10

    def accept(self, pcm):
        if not self.recognizer.AcceptWaveform(pcm):
            return None
        result = json.loads(self.recognizer.Result())
        words = result.get("result", [])
        score = min((w.get("conf", 0) for w in words), default=0)
        now = time.monotonic()
        if matches_phrase(result.get("text", "")) and score >= WAKEWORD_THRESHOLD and now - self.last_wake >= 3:
            self.last_wake = now
            return {"type": "wake", "model": "hey_nova", "score": score}
        return None
