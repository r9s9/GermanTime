"""gop.py: calibration math is pure and tested directly; score_utterance's
aggregation logic is tested against a mocked aligner (real G2P still runs —
it's fast/no-GPU — but the acoustic alignment is faked so this doesn't need
the Wav2Vec2 model loaded).
"""

import numpy as np
import pytest

from app.services.pron import aligner, g2p, gop


def test_calibrate_zero_raw_gop_scores_highest():
    # raw_gop=0 means the target phone was the model's top pick at every
    # frame — the best possible outcome, so its calibrated score should
    # be higher than a clearly-worse (more negative) raw_gop.
    assert gop.calibrate(0.0) > gop.calibrate(-2.0) > gop.calibrate(-6.0)


def test_calibrate_is_bounded_0_to_100():
    for raw in (0.0, -1.0, -5.0, -50.0, -1000.0):
        score = gop.calibrate(raw)
        assert 0.0 <= score <= 100.0


def test_calibrate_uses_explicit_ab_over_config_default(monkeypatch):
    default = gop.calibrate(-1.0)
    custom = gop.calibrate(-1.0, a=100.0, b=-1.0)
    assert custom != default
    assert custom == pytest.approx(50.0, abs=0.01)  # raw==b -> sigmoid midpoint


def _fake_span(phone, start, end, target_lp, max_lp):
    return aligner.PhoneAlign(phone=phone, start_frame=start, end_frame=end,
                               target_logprob=target_lp, max_logprob=max_lp)


def test_score_utterance_aggregates_words_and_weights_by_duration(monkeypatch):
    # "ich" (2 phones, perfect) + "da" (2 phones, bad) — utterance overall
    # must land between the two word scores, closer to whichever word has
    # more frames (duration-weighted, not a plain average).
    monkeypatch.setattr(aligner, "vocab", lambda: {p: i for i, p in enumerate(["ɪ", "ç", "d", "ɑː", "<unk>"])})

    def fake_align(audio, phones):
        return aligner.AlignResult(
            phones=[
                _fake_span("ɪ", 0, 5, 0.0, 0.0),      # perfect: raw_gop=0
                _fake_span("ç", 5, 10, 0.0, 0.0),      # perfect
                _fake_span("d", 10, 60, -6.0, 0.0),    # bad, but 10x the frames
                _fake_span("ɑː", 60, 110, -6.0, 0.0),  # bad, 10x the frames
            ],
            frame_seconds=0.02,
        )

    monkeypatch.setattr(aligner, "align", fake_align)
    monkeypatch.setattr(g2p, "phonemize_words", lambda words, lang="de": [["ɪ", "ç"], ["d", "ɑː"]])

    result = gop.score_utterance(np.zeros(1600, dtype=np.float32), "ich da")
    assert result is not None
    ich, da = result.words
    assert ich.score == pytest.approx(gop.calibrate(0.0))  # raw_gop=0 for every phone in "ich"
    assert da.score < ich.score
    # "da" has 10x "ich"'s frame count, so the duration-weighted overall
    # should sit much closer to "da"'s score than a plain 50/50 average would.
    plain_average = (ich.score + da.score) / 2
    assert abs(result.overall - da.score) < abs(result.overall - plain_average)


def test_score_utterance_drops_phones_missing_from_model_vocab(monkeypatch):
    # Regression: "ʏ" (short ü, as in "München") is real espeak output but
    # isn't in the acoustic model's vocab. One unmapped phone anywhere used
    # to fail the *entire* utterance's alignment; now it's just filtered
    # out of that word's phone list before alignment is even attempted.
    monkeypatch.setattr(aligner, "vocab", lambda: {p: i for i, p in enumerate(["m", "n", "ç", "ə", "<unk>"])})
    monkeypatch.setattr(g2p, "phonemize_words", lambda words, lang="de": [["m", "ʏ", "n", "ç", "ə", "n"]])

    captured_flat_phones = {}

    def fake_align(audio, phones):
        captured_flat_phones["phones"] = phones
        return aligner.AlignResult(
            phones=[_fake_span(p, i * 5, i * 5 + 5, 0.0, 0.0) for i, p in enumerate(phones)],
            frame_seconds=0.02,
        )

    monkeypatch.setattr(aligner, "align", fake_align)

    result = gop.score_utterance(np.zeros(1600, dtype=np.float32), "München")
    assert result is not None
    assert "ʏ" not in captured_flat_phones["phones"]
    assert captured_flat_phones["phones"] == ["m", "n", "ç", "ə", "n"]


def test_score_utterance_returns_none_when_alignment_fails(monkeypatch):
    monkeypatch.setattr(aligner, "vocab", lambda: {"ɪ": 0, "ç": 1})
    monkeypatch.setattr(g2p, "phonemize_words", lambda words, lang="de": [["ɪ", "ç"]])
    monkeypatch.setattr(aligner, "align", lambda audio, phones: None)

    assert gop.score_utterance(np.zeros(1600, dtype=np.float32), "ich") is None


def test_score_utterance_returns_none_for_text_with_no_words():
    assert gop.score_utterance(np.zeros(1600, dtype=np.float32), "... 123 !?") is None


def _make_result():
    return gop.UtteranceScore(
        words=[gop.WordScore(word="ich", score=90.0, phones=[
            gop.PhoneScore(phone="ɪ", raw_gop=0.0, score=90.0, t0=0.0, t1=0.1),
            gop.PhoneScore(phone="ç", raw_gop=0.0, score=90.0, t0=0.1, t1=0.2),
        ])],
        overall=90.0,
    )


def test_persist_creates_utterance_score_row_and_phoneme_stats(db_session):
    from app.models import PhonemeStat, UtteranceScore

    words_json = gop.persist(db_session, "ich", _make_result(), confidence=0.5, turn_id="turn-1")
    db_session.commit()

    row = db_session.query(UtteranceScore).filter_by(turn_id="turn-1").one()
    assert row.overall == 90.0
    assert row.confidence == 0.5
    assert row.words == words_json

    ç_stat = db_session.get(PhonemeStat, "ç")
    assert ç_stat.n == 1
    assert ç_stat.ema == pytest.approx(90.0)


def test_persist_ema_moves_toward_new_score_weighted_by_confidence(db_session):
    from app.models import PhonemeStat

    db_session.add(PhonemeStat(phoneme="ç", ema=50.0, n=1, last10=[50.0]))
    db_session.commit()

    gop.persist(db_session, "ich", _make_result(), confidence=1.0, turn_id="turn-2")
    db_session.commit()

    row = db_session.get(PhonemeStat, "ç")
    assert row.n == 2
    # full confidence -> alpha = PHONEME_EMA_ALPHA; ema should move from 50
    # toward the new 90.0, by exactly that alpha, not jump straight to it.
    from app import config
    expected = config.PHONEME_EMA_ALPHA * 90.0 + (1 - config.PHONEME_EMA_ALPHA) * 50.0
    assert row.ema == pytest.approx(expected)


def test_persist_lower_confidence_moves_ema_less(db_session):
    from app.models import PhonemeStat

    db_session.add(PhonemeStat(phoneme="ç", ema=50.0, n=1, last10=[50.0]))
    db_session.commit()
    gop.persist(db_session, "ich", _make_result(), confidence=0.5, turn_id="turn-3")
    db_session.commit()
    low_conf_ema = db_session.get(PhonemeStat, "ç").ema

    db_session.get(PhonemeStat, "ç").ema = 50.0  # reset
    db_session.commit()
    gop.persist(db_session, "ich", _make_result(), confidence=1.0, turn_id="turn-4")
    db_session.commit()
    full_conf_ema = db_session.get(PhonemeStat, "ç").ema

    # both move up from 50 toward 90, but the lower-confidence update
    # should move less than the full-confidence one.
    assert 50.0 < low_conf_ema < full_conf_ema < 90.0
