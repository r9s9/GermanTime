"""Goodness-of-Pronunciation: turns a forced alignment into calibrated
0-100 scores per phone/word/utterance.

raw GOP for a phone span = mean(log P(target|frame) - log max_q P(q|frame))
over its frames. Always <= 0; 0 means the target phone was the model's top
pick at every frame (excellent), very negative means something else was
much more likely (mispronounced or misaligned). Calibrated to 0-100 via a
sigmoid fit once by `python -m app.services.pron.calibrate` — see that
module's docstring for the fitting method.
"""

import math
from dataclasses import dataclass

import numpy as np

from . import aligner, g2p
from ... import config


@dataclass
class PhoneScore:
    phone: str
    raw_gop: float
    score: float  # 0..100
    t0: float  # seconds, for future waveform/playback UI
    t1: float


@dataclass
class WordScore:
    word: str
    phones: list[PhoneScore]
    score: float  # 0..100 = 0.7*min(phone scores) + 0.3*mean(phone scores)


@dataclass
class UtteranceScore:
    words: list[WordScore]
    overall: float  # 0..100, frame-count (duration) weighted across words


def calibrate(raw_gop: float, a: float | None = None, b: float | None = None) -> float:
    a = config.GOP_CALIBRATION_A if a is None else a
    b = config.GOP_CALIBRATION_B if b is None else b
    return 100.0 / (1.0 + math.exp(-a * (raw_gop - b)))


def _word_score(phone_scores: list[PhoneScore]) -> float:
    vals = [p.score for p in phone_scores]
    return 0.7 * min(vals) + 0.3 * (sum(vals) / len(vals))


def score_utterance(audio_f32_16k: np.ndarray, text: str, lang: str = "de") -> UtteranceScore | None:
    """Best-effort: returns None on any alignment failure rather than
    raising, since this is always a background/supplementary signal, never
    something the conversation pipeline or a drill attempt should block on.

    Words are filtered to phones the acoustic model actually has a vocab
    slot for before alignment (e.g. espeak's short "ʏ" — as in "München" —
    isn't in facebook/wav2vec2-xlsr-53-espeak-cv-ft's vocab; confirmed by
    dumping it directly, not assumed). A single unmapped phone anywhere in
    the utterance would otherwise fail the *entire* forced-align call, not
    just the word it belongs to — dropping the odd phone here means one
    tricky word costs a little precision instead of losing the whole turn's
    score.
    """
    words = g2p.words_in(text)
    if not words:
        return None
    raw_phone_lists = g2p.phonemize_words(words, lang)
    model_vocab = aligner.vocab()
    phone_lists = [[p for p in pl if p in model_vocab] for pl in raw_phone_lists]
    flat_phones = [p for pl in phone_lists for p in pl]
    if not flat_phones:
        return None

    result = aligner.align(audio_f32_16k, flat_phones)
    if result is None:
        return None

    word_scores: list[WordScore] = []
    total_frames = 0
    weighted_sum = 0.0
    idx = 0
    for word, phones in zip(words, phone_lists):
        span_slice = result.phones[idx:idx + len(phones)]
        idx += len(phones)
        if not span_slice:
            continue
        phone_scores = [
            PhoneScore(phone=s.phone, raw_gop=s.target_logprob - s.max_logprob,
                       score=calibrate(s.target_logprob - s.max_logprob),
                       t0=round(s.start_frame * result.frame_seconds, 3),
                       t1=round(s.end_frame * result.frame_seconds, 3))
            for s in span_slice
        ]
        w_score = _word_score(phone_scores)
        word_scores.append(WordScore(word=word, phones=phone_scores, score=w_score))
        frames = sum(max(s.end_frame - s.start_frame, 1) for s in span_slice)
        weighted_sum += w_score * frames
        total_frames += frames

    if not word_scores or total_frames == 0:
        return None
    return UtteranceScore(words=word_scores, overall=weighted_sum / total_frames)


def words_to_json(words: list[WordScore]) -> list[dict]:
    return [
        {"w": w.word, "score": round(w.score, 1),
         "phones": [{"p": p.phone, "score": round(p.score, 1), "t0": p.t0, "t1": p.t1} for p in w.phones]}
        for w in words
    ]


def update_phoneme_stats(db, words_json: list[dict], confidence: float) -> None:
    from ...models import PhonemeStat

    alpha = config.PHONEME_EMA_ALPHA * confidence
    for w in words_json:
        for p in w["phones"]:
            row = db.get(PhonemeStat, p["p"])
            if row is None:
                row = PhonemeStat(phoneme=p["p"], ema=p["score"], n=0, last10=[])
                db.add(row)
            else:
                row.ema = alpha * p["score"] + (1 - alpha) * row.ema
            row.n += 1
            row.last10 = (row.last10 + [round(p["score"], 1)])[-10:]


def persist(db, ref_text: str, result: UtteranceScore, confidence: float,
            turn_id: str | None = None, attempt_id: str | None = None) -> list[dict]:
    """Persists a scored utterance (UtteranceScore row + PhonemeStat EMA +
    pronunciation theta) and returns the words_json payload for the caller
    to hand back to a client. Shared by conversation-sourced scoring
    (pron_hook.py, confidence=0.5) and drill attempts (api/pron.py,
    confidence=1.0 — a known reference sentence, not an STT guess).
    """
    from .. import learner
    from ...models import UtteranceScore as UtteranceScoreRow

    words_json = words_to_json(result.words)
    db.add(UtteranceScoreRow(
        turn_id=turn_id, attempt_id=attempt_id, audio_path="", ref_text=ref_text,
        words=words_json, overall=round(result.overall, 1), confidence=confidence,
    ))
    update_phoneme_stats(db, words_json, confidence)
    current = learner.get_theta(db, "pronunciation")
    learner.update_skill(db, "pronunciation", result.overall / 100, current, weight=confidence)
    return words_json
