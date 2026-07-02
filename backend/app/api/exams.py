"""Goethe mock exam endpoints. The Sprechen module's live interaction
happens over the existing /ws/voice/{conv_id} pipeline (state carries the
conv_id — see GET .../state) rather than a bespoke WS route; /finish-speaking
is called once the candidate is done talking, to grade the transcript.
"""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from ..db import get_db
from ..models import MockExam
from ..services import content, examflow

router = APIRouter(prefix="/api/exams", tags=["exams"])


@router.get("/blueprints")
def blueprints() -> dict:
    return content.exam_blueprints()


class StartIn(BaseModel):
    level: str  # A1|A2|B1
    mode: str = "full"


@router.post("/start")
def start_exam(body: StartIn, db: Session = Depends(get_db)) -> dict:
    if body.level not in ("A1", "A2", "B1"):
        raise HTTPException(422, "level must be A1, A2, or B1")
    exam = examflow.start(db, body.level, body.mode)
    return examflow.get_state(db, exam.id)


def _require_exam(db: Session, exam_id: str) -> MockExam:
    exam = db.get(MockExam, exam_id)
    if exam is None:
        raise HTTPException(404, "exam not found")
    return exam


@router.get("/{exam_id}/state")
def state(exam_id: str, db: Session = Depends(get_db)) -> dict:
    _require_exam(db, exam_id)
    return examflow.get_state(db, exam_id)


@router.post("/{exam_id}/modules/{module_name}/start")
async def start_module(exam_id: str, module_name: str, db: Session = Depends(get_db)) -> dict:
    _require_exam(db, exam_id)
    try:
        return await examflow.start_module(db, exam_id, module_name)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


class AnswerIn(BaseModel):
    response: dict


@router.post("/{exam_id}/sections/{section_id}/answer")
async def submit_answer(exam_id: str, section_id: str, body: AnswerIn, db: Session = Depends(get_db)) -> dict:
    _require_exam(db, exam_id)
    return await examflow.submit_section(db, exam_id, section_id, body.response)


@router.post("/{exam_id}/finish-speaking")
async def finish_speaking(exam_id: str, db: Session = Depends(get_db)) -> dict:
    _require_exam(db, exam_id)
    return await examflow.finish_speaking(db, exam_id)
