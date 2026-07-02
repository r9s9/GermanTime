"""Pronunciation: phoneme profile, drill generation, and scored drill
attempts (file upload — the one deliberate, known-reference recording
path; conversation-sourced scoring is the async pron_hook.py instead).
"""

import random

import numpy as np
import soxr
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from .. import config
from ..db import get_db
from ..models import PhonemeStat
from ..services import content, learner
from ..services.pron import drills, gop
from ..services.tts import cache as tts_cache

router = APIRouter(prefix="/api/pron", tags=["pron"])


def _pron_level(db: Session) -> str:
    thetas = learner.get_all_thetas(db)
    theta = thetas.get("pronunciation") or learner.overall_theta(thetas)
    return learner.cefr_label(theta)


@router.get("/profile")
def profile(db: Session = Depends(get_db)) -> dict:
    data = content.phoneme_map()
    stats = {row.phoneme: row for row in db.scalars(select(PhonemeStat)).all()}

    groups = []
    for g in data["groups"]:
        entries = []
        for p in g["phonemes"]:
            row = stats.get(p)
            tip = data["tips"].get(p, {})
            n = row.n if row else 0
            ema = round(row.ema, 1) if row else None
            weak = ema is not None and ema < config.PHONEME_WEAK_THRESHOLD and n >= config.PHONEME_WEAK_MIN_N
            entries.append({
                "phoneme": p, "ema": ema, "n": n, "weak": weak,
                "last10": row.last10 if row else [],
                "tip_de": tip.get("de"), "tip_en": tip.get("en"),
            })
        groups.append({"name_de": g["name_de"], "phonemes": entries})

    weak_phonemes = [
        e["phoneme"] for g in groups for e in g["phonemes"] if e["weak"]
    ]
    return {"groups": groups, "weak_phonemes": weak_phonemes}


class DrillIn(BaseModel):
    phoneme: str | None = None  # None = auto-pick the weakest tracked phoneme


@router.post("/drill")
async def make_drill(body: DrillIn, db: Session = Depends(get_db)) -> dict:
    phoneme = body.phoneme
    if not phoneme:
        weak = db.scalars(
            select(PhonemeStat).where(PhonemeStat.n >= config.PHONEME_WEAK_MIN_N,
                                       PhonemeStat.ema < config.PHONEME_WEAK_THRESHOLD)
            .order_by(PhonemeStat.ema)
        ).first()
        if weak:
            phoneme = weak.phoneme
        else:
            all_phonemes = [p for g in content.phoneme_map()["groups"] for p in g["phonemes"]]
            phoneme = random.choice(all_phonemes)

    level = _pron_level(db)
    drill = await drills.generate(db, phoneme, level)

    key, _latency_ms = tts_cache.synthesize_cached(db, drill["text_de"], "piper", "")
    drill["audio_url"] = f"/audio/tts/{key}.wav"
    return drill


@router.post("/attempt")
async def score_attempt(
    file: UploadFile, ref_text: str, db: Session = Depends(get_db)
) -> dict:
    if not ref_text.strip():
        raise HTTPException(422, "ref_text must not be empty")
    raw = await file.read()
    try:
        import io

        import soundfile as sf

        audio, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"could not decode audio: {e}")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != config.SAMPLE_RATE:
        audio = soxr.resample(audio, sr, config.SAMPLE_RATE).astype(np.float32)

    result = gop.score_utterance(audio.astype(np.float32), ref_text)
    if result is None:
        raise HTTPException(422, "could not score this recording — try again, closer to the microphone")

    words_json = gop.persist(db, ref_text, result, confidence=1.0)
    db.commit()
    return {"overall": round(result.overall, 1), "words": words_json}
