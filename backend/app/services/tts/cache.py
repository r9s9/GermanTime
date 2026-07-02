"""Content-addressed TTS cache: the same (engine, voice, text) is never
resynthesized. Backs word-pronunciation playback, drills, and exam audio."""

import hashlib
from pathlib import Path

import numpy as np
import soundfile as sf
from sqlalchemy.orm import Session

from . import chatterbox_engine, piper_engine
from ... import config
from ...models import TtsCache


def _hash(engine: str, voice: str, text: str) -> str:
    return hashlib.sha1(f"{engine}|{voice}|{text}".encode("utf-8")).hexdigest()


def synthesize_cached(db: Session, text: str, engine: str = "piper", voice: str = "") -> tuple[str, float]:
    """Returns (cache_key, latency_ms). latency_ms is 0.0 on a cache hit."""
    key = _hash(engine, voice, text)
    row = db.get(TtsCache, key)
    if row and Path(row.path).exists():
        return key, 0.0

    if engine == "chatterbox":
        result = chatterbox_engine.synthesize(text)
    else:
        result = piper_engine.synthesize(text, voice or config.PIPER_VOICE_MAIN)

    config.TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = config.TTS_CACHE_DIR / f"{key}.wav"
    pcm16 = np.frombuffer(result.pcm16, dtype=np.int16)
    sf.write(str(path), pcm16, result.sample_rate)

    if row is None:
        row = TtsCache(hash=key, path=str(path), engine=engine, voice=voice)
        db.add(row)
    else:
        row.path = str(path)
    db.commit()
    return key, result.latency_ms


def cache_path(db: Session, key: str) -> Path | None:
    row = db.get(TtsCache, key)
    if row is None:
        return None
    path = Path(row.path)
    return path if path.exists() else None
