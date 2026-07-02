"""Chatterbox Multilingual TTS — GPU, natural voice, no streaming API (see
install.ps1 for the --no-deps pin rationale). Optional: the app falls back
to Piper-only if this fails to load."""

import time

import numpy as np

from .base import TtsResult

_model = None
_load_failed = False


def available() -> bool:
    return not _load_failed


def _get_model():
    global _model, _load_failed
    if _model is None and not _load_failed:
        try:
            import torch
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS

            _model = ChatterboxMultilingualTTS.from_pretrained(
                device="cuda" if torch.cuda.is_available() else "cpu"
            )
        except Exception:
            _load_failed = True
            raise
    if _model is None:
        raise RuntimeError("Chatterbox failed to load — use Piper instead")
    return _model


def synthesize(text: str, language_id: str = "de") -> TtsResult:
    model = _get_model()
    t0 = time.perf_counter()
    wav = model.generate(text, language_id=language_id)
    latency_ms = (time.perf_counter() - t0) * 1000

    samples = wav.detach().cpu().numpy().reshape(-1)
    pcm16 = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
    return TtsResult(pcm16=pcm16, sample_rate=model.sr, latency_ms=latency_ms)


def warmup() -> None:
    synthesize("Hallo.")


def unload() -> None:
    """Frees VRAM — called when the user disables the natural voice in Settings."""
    global _model
    if _model is not None:
        import torch

        del _model
        _model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
