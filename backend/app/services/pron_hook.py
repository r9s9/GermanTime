"""Async post-turn pronunciation scoring.

session.py fires this after every finalized user utterance with the raw
audio + transcript, as a detached asyncio task (created, never awaited) —
so this never adds latency to the conversation turn it scores, and a
failure here can never break the conversation. The transcript is
STT-derived, not a known-correct reference, so results are lower
confidence than a drill attempt (see PHONEME_EMA_ALPHA weighting below).
"""

import asyncio
import functools
import logging

import numpy as np

from . import concurrency
from .pron import gop
from .. import config
from ..db import SessionLocal
from ..models import ConvTurn

logger = logging.getLogger(__name__)

CONVERSATION_CONFIDENCE = 0.5


def _pcm16_to_float(pcm16: bytes, sample_rate: int) -> np.ndarray:
    audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    if sample_rate != config.SAMPLE_RATE:
        import soxr

        audio = soxr.resample(audio, sample_rate, config.SAMPLE_RATE).astype(np.float32)
    return audio


def _score_and_persist(conv_id: str, turn_id: str, pcm16: bytes, sample_rate: int, transcript: str) -> dict | None:
    audio = _pcm16_to_float(pcm16, sample_rate)
    result = gop.score_utterance(audio, transcript)
    if result is None:
        return None

    with SessionLocal() as db:
        words_json = gop.persist(db, transcript, result, CONVERSATION_CONFIDENCE, turn_id=turn_id)
        row = db.get(ConvTurn, turn_id)
        if row is not None:
            row.score_id = turn_id
        db.commit()
    return {"turn_id": turn_id, "words": words_json}


async def maybe_score_utterance(conv_id: str, turn_id: str, pcm16: bytes, sample_rate: int, transcript: str) -> None:
    try:
        loop = asyncio.get_event_loop()
        async with concurrency.gpu_lock:
            payload = await loop.run_in_executor(
                None, functools.partial(_score_and_persist, conv_id, turn_id, pcm16, sample_rate, transcript)
            )
        if payload is None:
            return
        from ..api.ws_voice import active_sessions
        from ..voice import protocol

        session = active_sessions.get(conv_id)
        if session is not None:
            await session.push_event(protocol.pron_result(payload["turn_id"], payload["words"]))
    except Exception:  # noqa: BLE001
        logger.exception("pronunciation scoring failed (conv_id=%s turn_id=%s)", conv_id, turn_id)
