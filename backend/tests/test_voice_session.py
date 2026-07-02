"""VoiceSession interruption handling — the state machine's trickiest piece.

Regression coverage for a real bug found via live end-to-end testing: sustained
incoming speech while state="thinking" (LLM generating, nothing spoken yet)
was being treated identically to state="speaking" (assistant actively
talking), firing a client-facing barge_in and flagging an empty turn as
"interrupted". The two need different handling — "thinking" interruption is
almost always just the user pausing mid-utterance (common for hesitant
language learners), not barging in on anything.

vad.frame_prob is faked throughout — these tests don't load the real model.
"""

import asyncio
import time

import numpy as np
import pytest

from app import config
from app.voice import session as session_module
from app.voice.session import VoiceSession


class _Collector:
    def __init__(self):
        self.json_events = []
        self.audio_chunks = []

    async def send_json(self, msg):
        self.json_events.append(msg)

    async def send_bytes(self, data):
        self.audio_chunks.append(data)


def _make_session(collector) -> VoiceSession:
    return VoiceSession(
        conv_id="test-conv", send_json=collector.send_json, send_bytes=collector.send_bytes,
        system_prompt="test", opening_prompt="test", level="A1.1", tts_engine="piper",
    )


def _speech_frame() -> bytes:
    # exactly one VAD window (512 samples @ 16kHz) so each handle_frame() call
    # triggers exactly one _process_vad_frame() — a smaller frame would just
    # sit in the internal accumulation buffer without firing anything
    return np.zeros(config.VAD_WINDOW, dtype=np.int16).tobytes()


async def _never_finishes():
    await asyncio.sleep(100)


@pytest.mark.asyncio
async def test_sustained_speech_during_thinking_cancels_silently_without_barge_in(monkeypatch):
    collector = _Collector()
    s = _make_session(collector)
    s.state = "thinking"
    s._active_turn_task = asyncio.create_task(_never_finishes())
    monkeypatch.setattr(session_module.vad, "frame_prob", lambda frame: 0.9)

    frame = _speech_frame()
    for _ in range(3):  # config.BARGE_IN_WINDOWS
        await s.handle_frame(frame)
    await asyncio.sleep(0)  # let the cancellation propagate

    assert s.state == "listening"
    assert s._is_speech is True  # the interrupting speech becomes the next utterance
    types = [e["t"] for e in collector.json_events]
    assert "barge_in" not in types
    assert collector.json_events[-1] == {"t": "vad", "state": "speech_start"}


@pytest.mark.asyncio
async def test_sustained_speech_during_speaking_triggers_real_barge_in(monkeypatch):
    collector = _Collector()
    s = _make_session(collector)
    s.state = "speaking"
    s._active_turn_task = asyncio.create_task(_never_finishes())
    monkeypatch.setattr(session_module.vad, "frame_prob", lambda frame: 0.9)

    frame = _speech_frame()
    for _ in range(3):
        await s.handle_frame(frame)
    await asyncio.sleep(0)

    assert s.state == "listening"
    types = [e["t"] for e in collector.json_events]
    assert "barge_in" in types


@pytest.mark.asyncio
async def test_brief_speech_blip_during_thinking_does_not_cancel(monkeypatch):
    collector = _Collector()
    s = _make_session(collector)
    s.state = "thinking"
    task = asyncio.create_task(_never_finishes())
    s._active_turn_task = task
    monkeypatch.setattr(session_module.vad, "frame_prob", lambda frame: 0.9)

    await s.handle_frame(_speech_frame())  # only 1 window — below BARGE_IN_WINDOWS
    await asyncio.sleep(0)

    assert s.state == "thinking"
    assert not task.cancelled()
    task.cancel()


@pytest.mark.asyncio
async def test_silence_resets_the_interruption_speech_run(monkeypatch):
    collector = _Collector()
    s = _make_session(collector)
    s.state = "thinking"
    task = asyncio.create_task(_never_finishes())
    s._active_turn_task = task

    probs = iter([0.9, 0.9, 0.1, 0.9, 0.9])  # 2 speech, 1 silence (resets), 2 speech — never reaches 3 in a row
    monkeypatch.setattr(session_module.vad, "frame_prob", lambda frame: next(probs))

    for _ in range(5):
        await s.handle_frame(_speech_frame())
    await asyncio.sleep(0)

    assert s.state == "thinking"
    assert not task.cancelled()
    task.cancel()


@pytest.mark.asyncio
async def test_turn_cancelled_before_any_audio_is_a_silent_no_op(db_session, monkeypatch):
    """Reproduces a real desync: a "thinking"-phase cancel used to still
    publish tts_end/turn_stats and an empty assistant history entry for a
    turn that never spoke a word, making the client (and a scripted e2e
    test) believe a reply had completed when nothing was ever said.
    """
    from app.db import SessionLocal
    from app.models import Conversation, ConvTurn

    monkeypatch.setattr(session_module, "SessionLocal", SessionLocal)
    db_session.add(Conversation(id="test-conv"))
    db_session.commit()

    async def _hanging_stream(role, messages, temperature=0.8):
        await asyncio.sleep(100)
        yield "unreachable"  # pragma: no cover

    monkeypatch.setattr(session_module.llm, "stream_chat", _hanging_stream)

    collector = _Collector()
    s = _make_session(collector)
    s.conv_id = "test-conv"

    s._active_turn_task = asyncio.create_task(s._run_turn("Hallo!", time.perf_counter()))
    await asyncio.sleep(0.05)  # let it run past the DB writes into the hanging stream
    assert s.state == "thinking"

    await s._cancel_turn_and_resume_listening()
    await asyncio.sleep(0.05)  # let the cancellation propagate through the finally block

    types = [e["t"] for e in collector.json_events]
    assert "tts_end" not in types
    assert "turn_stats" not in types
    assert not any(h.get("role") == "assistant" for h in s._history)

    rows = db_session.query(ConvTurn).filter_by(conv_id="test-conv", role="assistant").all()
    assert rows == []


@pytest.mark.asyncio
async def test_speak_chunk_drops_non_german_script_without_calling_tts(monkeypatch):
    """Regression for a live model hiccup: qwen2.5-14b occasionally leaked a
    Chinese sentence mid-reply despite the persona prompt forbidding it. A
    German Piper/Chatterbox voice can't render that, so the chunk must be
    dropped before synthesis rather than sent to the engine or the client.
    """
    calls = []
    monkeypatch.setattr(
        session_module.piper_engine, "synthesize", lambda text, *a, **kw: calls.append(text)
    )

    collector = _Collector()
    s = _make_session(collector)

    await s._speak_chunk("Haben " + chr(20320) + chr(21916) + chr(27426), "turn-1", 0)

    assert calls == []
    assert collector.json_events == []
    assert collector.audio_chunks == []
