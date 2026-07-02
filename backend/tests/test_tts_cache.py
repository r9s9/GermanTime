"""TTS cache: hashing + hit/miss behavior. The actual engines are faked —
this doesn't load any real model."""

import numpy as np
import pytest

from app.services.tts import cache, piper_engine
from app.services.tts.base import TtsResult


@pytest.fixture(autouse=True)
def fake_piper(monkeypatch):
    calls = {"n": 0}

    def fake_synthesize(text, voice=""):
        calls["n"] += 1
        silence = np.zeros(100, dtype=np.int16)
        return TtsResult(pcm16=silence.tobytes(), sample_rate=22050, latency_ms=42.0)

    monkeypatch.setattr(piper_engine, "synthesize", fake_synthesize)
    return calls


def test_synthesize_cached_creates_file_and_db_row(db_session, fake_piper, tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "TTS_CACHE_DIR", tmp_path)

    key, latency = cache.synthesize_cached(db_session, "Hallo!", "piper", "")
    assert latency == 42.0
    assert fake_piper["n"] == 1
    path = cache.cache_path(db_session, key)
    assert path is not None and path.exists()


def test_synthesize_cached_hits_cache_on_repeat(db_session, fake_piper, tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "TTS_CACHE_DIR", tmp_path)

    key1, _ = cache.synthesize_cached(db_session, "Hallo!", "piper", "")
    key2, latency2 = cache.synthesize_cached(db_session, "Hallo!", "piper", "")
    assert key1 == key2
    assert latency2 == 0.0  # cache hit, no synth
    assert fake_piper["n"] == 1  # engine only called once


def test_different_text_or_voice_produces_different_keys(db_session, fake_piper, tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "TTS_CACHE_DIR", tmp_path)

    key_a, _ = cache.synthesize_cached(db_session, "Hallo!", "piper", "")
    key_b, _ = cache.synthesize_cached(db_session, "Tschüss!", "piper", "")
    key_c, _ = cache.synthesize_cached(db_session, "Hallo!", "piper", "eva_k")
    assert len({key_a, key_b, key_c}) == 3


def test_cache_path_returns_none_for_unknown_key(db_session):
    assert cache.cache_path(db_session, "nonexistent") is None
