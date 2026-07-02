"""pron_hook.py: the conversation-triggered scoring path. gop.score_utterance
is faked (its own correctness is covered in test_gop.py) so these test the
wiring — DB persistence, ConvTurn linking, and the WS push-to-active-session
handoff — without needing the real acoustic model.
"""

import numpy as np
import pytest

from app.services import pron_hook
from app.services.pron import gop


def _fake_result():
    return gop.UtteranceScore(
        words=[gop.WordScore(word="ich", score=80.0, phones=[
            gop.PhoneScore(phone="ɪ", raw_gop=-0.5, score=80.0, t0=0.0, t1=0.1),
        ])],
        overall=80.0,
    )


@pytest.mark.asyncio
async def test_maybe_score_utterance_persists_and_links_turn(db_session, monkeypatch):
    from app.db import SessionLocal as fresh_session_local
    from app.models import Conversation, ConvTurn, UtteranceScore

    # flush between adds: Conversation<->ConvTurn has no ORM relationship(),
    # just a raw FK column, so unit-of-work doesn't auto-order the inserts.
    db_session.add(Conversation(id="conv-1"))
    db_session.flush()
    db_session.add(ConvTurn(id="turn-1", conv_id="conv-1", idx=0, role="user", text_de="ich"))
    db_session.commit()

    # pron_hook imported SessionLocal at collection time, before db_session's
    # sys.modules purge rebound app.db to this test's isolated DB — repoint
    # it, same fix as test_llm.py's resolve_model tests needed.
    monkeypatch.setattr(pron_hook, "SessionLocal", fresh_session_local)
    monkeypatch.setattr(gop, "score_utterance", lambda audio, text: _fake_result())

    pcm16 = np.zeros(1600, dtype=np.int16).tobytes()
    await pron_hook.maybe_score_utterance("conv-1", "turn-1", pcm16, 16000, "ich")

    row = db_session.query(UtteranceScore).filter_by(turn_id="turn-1").one()
    assert row.overall == 80.0
    turn = db_session.get(ConvTurn, "turn-1")
    assert turn.score_id == "turn-1"


@pytest.mark.asyncio
async def test_maybe_score_utterance_pushes_to_active_session(db_session, monkeypatch):
    from app.api import ws_voice
    from app.db import SessionLocal as fresh_session_local
    from app.models import Conversation, ConvTurn

    db_session.add(Conversation(id="conv-2"))
    db_session.flush()
    db_session.add(ConvTurn(id="turn-2", conv_id="conv-2", idx=0, role="user", text_de="ich"))
    db_session.commit()

    monkeypatch.setattr(pron_hook, "SessionLocal", fresh_session_local)
    monkeypatch.setattr(gop, "score_utterance", lambda audio, text: _fake_result())

    pushed = []

    class _FakeSession:
        async def push_event(self, msg):
            pushed.append(msg)

    ws_voice.active_sessions["conv-2"] = _FakeSession()
    try:
        pcm16 = np.zeros(1600, dtype=np.int16).tobytes()
        await pron_hook.maybe_score_utterance("conv-2", "turn-2", pcm16, 16000, "ich")
    finally:
        del ws_voice.active_sessions["conv-2"]

    assert len(pushed) == 1
    assert pushed[0]["t"] == "pron_result"
    assert pushed[0]["turn_id"] == "turn-2"


@pytest.mark.asyncio
async def test_maybe_score_utterance_is_a_silent_no_op_when_scoring_fails(db_session, monkeypatch):
    from app.db import SessionLocal as fresh_session_local
    from app.models import Conversation, ConvTurn, UtteranceScore

    db_session.add(Conversation(id="conv-3"))
    db_session.flush()
    db_session.add(ConvTurn(id="turn-3", conv_id="conv-3", idx=0, role="user", text_de="ich"))
    db_session.commit()

    monkeypatch.setattr(pron_hook, "SessionLocal", fresh_session_local)
    monkeypatch.setattr(gop, "score_utterance", lambda audio, text: None)

    pcm16 = np.zeros(1600, dtype=np.int16).tobytes()
    await pron_hook.maybe_score_utterance("conv-3", "turn-3", pcm16, 16000, "ich")  # must not raise

    assert db_session.query(UtteranceScore).count() == 0


@pytest.mark.asyncio
async def test_maybe_score_utterance_never_raises_on_unexpected_error(monkeypatch):
    def boom(audio, text):
        raise RuntimeError("acoustic model exploded")

    monkeypatch.setattr(gop, "score_utterance", boom)

    pcm16 = np.zeros(1600, dtype=np.int16).tobytes()
    await pron_hook.maybe_score_utterance("conv-x", "turn-x", pcm16, 16000, "ich")  # must not raise
