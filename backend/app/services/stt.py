"""faster-whisper STT — singleton model, float16 only (int8 is broken on
Blackwell/sm_120, see install.ps1 and the smoke test)."""

import time
from dataclasses import dataclass

import numpy as np

from .. import config

_model = None


def _get_model():
    global _model
    if _model is None:
        config.wire_dlls()
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            config.WHISPER_MODEL, device="cuda", compute_type=config.WHISPER_COMPUTE,
            download_root=str(config.WHISPER_DIR),
        )
    return _model


@dataclass
class TranscriptResult:
    text: str
    language: str
    duration_s: float
    latency_ms: float


def transcribe(audio: np.ndarray, language: str = "de", initial_prompt: str | None = None,
                beam_size: int = 1) -> TranscriptResult:
    """audio: mono float32 PCM at 16 kHz, range [-1, 1]."""
    model = _get_model()
    t0 = time.perf_counter()
    segments, info = model.transcribe(
        audio, language=language, beam_size=beam_size, initial_prompt=initial_prompt,
        condition_on_previous_text=False, vad_filter=False,
    )
    text = "".join(seg.text for seg in segments).strip()
    latency_ms = (time.perf_counter() - t0) * 1000
    return TranscriptResult(text=text, language=info.language, duration_s=info.duration, latency_ms=latency_ms)


def warmup() -> None:
    transcribe(np.zeros(16000, dtype=np.float32))
