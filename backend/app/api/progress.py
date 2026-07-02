"""Progress overview: skill thetas, CEFR position, vocab coverage, grammar mastery."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from ..db import get_db
from ..models import GrammarMastery, GrammarTopic, Placement
from ..services import learner

router = APIRouter(prefix="/api/progress", tags=["progress"])


@router.get("/overview")
def overview(db: Session = Depends(get_db)) -> dict:
    thetas = learner.get_all_thetas(db)
    overall = learner.overall_theta(thetas)
    mastery_rows = {m.topic_id: m for m in db.scalars(select(GrammarMastery))}
    topics = db.scalars(select(GrammarTopic).order_by(GrammarTopic.sort)).all()
    mastered = sum(1 for t in topics if learner.is_topic_mastered(db, t.id, mastery_rows.get(t.id)))
    has_placement = db.scalar(select(Placement).where(Placement.finished_at.is_not(None)).limit(1)) is not None

    return {
        "has_placement": has_placement,
        "thetas": {k: round(v, 1) for k, v in thetas.items()},
        "overall_theta": round(overall, 1),
        "cefr": learner.cefr_label(overall),
        "vocab_coverage": {k: round(v, 3) for k, v in learner.vocab_coverage(db).items()},
        "grammar_mastered": mastered,
        "grammar_total": len(topics),
    }
