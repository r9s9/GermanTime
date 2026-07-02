"""Shared TTS engine result shape. Both engines return a complete WAV clip
for P5's foundation use; P6 adds sentence-chunked streaming on top."""

from dataclasses import dataclass


@dataclass
class TtsResult:
    pcm16: bytes         # mono PCM16LE
    sample_rate: int
    latency_ms: float    # wall-clock synth time (first-byte-equivalent for a single clip)
