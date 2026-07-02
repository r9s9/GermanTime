"""Silero VAD — a simple VADIterator wrapper for foundation/bench use, plus
raw per-frame model access for P6's custom dual-threshold endpointing state
machine (VADIterator only exposes a single threshold, not the separate
speech-start/speech-end probabilities the full pipeline design calls for).
"""

import numpy as np
import torch

from .. import config

_model = None


def _get_model():
    global _model
    if _model is None:
        from silero_vad import load_silero_vad

        _model = load_silero_vad()
    return _model


def frame_prob(frame: np.ndarray, sample_rate: int = config.SAMPLE_RATE) -> float:
    """frame: exactly VAD_WINDOW (512) mono float32 samples at 16 kHz."""
    model = _get_model()
    with torch.no_grad():
        return float(model(torch.from_numpy(frame), sample_rate).item())


class SimpleVadSession:
    """Thin VADIterator wrapper: one threshold, built-in silence debouncing.
    Good enough for the P5 bench; P6 uses frame_prob() directly for the
    adaptive dual-threshold + pre-roll design.
    """

    def __init__(self, threshold: float = config.VAD_SPEECH_PROB, min_silence_ms: int = config.ENDPOINT_MS):
        from silero_vad import VADIterator

        self._it = VADIterator(
            _get_model(), threshold=threshold, sampling_rate=config.SAMPLE_RATE,
            min_silence_duration_ms=min_silence_ms,
        )

    def process(self, frame: np.ndarray) -> dict | None:
        return self._it(frame, return_seconds=True)

    def reset(self) -> None:
        self._it.reset_states()


def warmup() -> None:
    frame_prob(np.zeros(config.VAD_WINDOW, dtype=np.float32))
