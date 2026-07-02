"""Grammar topics, practice-set generation, and exercise attempts."""

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from ..db import get_db
from ..models import Exercise, ExerciseAttempt, GrammarTopic, utcnow
from ..services import errors, factory, grader, learner

router = APIRouter(prefix="/api", tags=["exercises"])


@router.get("/grammar/topics")
def list_topics(db: Session = Depends(get_db)) -> list[dict]:
    topics = db.scalars(select(GrammarTopic).order_by(GrammarTopic.sort)).all()
    return [
        {"id": t.id, "level": t.level, "week": t.syllabus_week, "title_de": t.title_de,
         "title_en": t.title_en, "prereq_ids": t.prereq_ids}
        for t in topics
    ]


def _public(ex: Exercise) -> dict:
    return {"id": ex.id, "type": ex.type, "level": ex.level, "topic_id": ex.topic_id, "payload": ex.payload}


@router.get("/lessons/practice-set")
async def practice_set(topic_id: str, level: str, count: int = 6, db: Session = Depends(get_db)) -> list[dict]:
    if not db.get(GrammarTopic, topic_id):
        raise HTTPException(404, "topic not found")
    exs = await factory.get_practice_set(db, level, topic_id, count)
    for ex in exs:
        ex.used_at = utcnow()
    db.commit()
    return [_public(ex) for ex in exs]


@router.get("/exercises/{exercise_id}")
def get_exercise(exercise_id: str, db: Session = Depends(get_db)) -> dict:
    ex = db.get(Exercise, exercise_id)
    if not ex:
        raise HTTPException(404, "exercise not found")
    return _public(ex)


class AttemptIn(BaseModel):
    response: dict
    block_id: str | None = None


@router.post("/exercises/{exercise_id}/attempt")
def attempt(exercise_id: str, body: AttemptIn, db: Session = Depends(get_db)) -> dict:
    ex = db.get(Exercise, exercise_id)
    if not ex:
        raise HTTPException(404, "exercise not found")

    result = grader.grade(ex.type, ex.answer_key, body.response)
    rec = ExerciseAttempt(
        exercise_id=ex.id, block_id=body.block_id, response=body.response,
        score=result["score"], detail=result["detail"], graded_by="auto", finished_at=utcnow(),
    )
    db.add(rec)
    db.commit()

    learner.update_from_exercise_attempt(db, ex.type, ex.level, result["score"])
    learner.update_grammar_mastery(db, ex.topic_id, result["score"])
    errors.maybe_create_from_exercise_attempt(db, ex, body.response, result)

    return {"score": result["score"], "correct": result["correct"], "detail": result["detail"]}
