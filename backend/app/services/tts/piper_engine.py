"""Piper TTS — CPU, instant, guaranteed-latency engine (drills, exam audio, UI, fallback voice)."""

import time

from .base import TtsResult
from ... import config

_voices: dict[str, object] = {}


def _get_voice(name: str = config.PIPER_VOICE_MAIN):
    if name not in _voices:
        from piper import PiperVoice

        path = config.PIPER_DIR / f"{name}.onnx"
        if not path.exists():
            raise FileNotFoundError(f"Piper voice not downloaded: {path}")
        _voices[name] = PiperVoice.load(str(path))
    return _voices[name]


def synthesize(text: str, voice: str = config.PIPER_VOICE_MAIN) -> TtsResult:
    v = _get_voice(voice)
    t0 = time.perf_counter()
    chunks = list(v.synthesize(text))
    pcm16 = b"".join(c.audio_int16_bytes for c in chunks)
    latency_ms = (time.perf_counter() - t0) * 1000
    sr = chunks[0].sample_rate if chunks else v.config.sample_rate
    return TtsResult(pcm16=pcm16, sample_rate=sr, latency_ms=latency_ms)


def warmup(voice: str = config.PIPER_VOICE_MAIN) -> None:
    synthesize("Hallo.", voice)
