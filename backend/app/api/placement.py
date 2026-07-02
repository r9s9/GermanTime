"""Onboarding placement test endpoints."""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from ..db import get_db
from ..models import Placement
from ..services import placement

router = APIRouter(prefix="/api/placement", tags=["placement"])


class StartIn(BaseModel):
    self_report: str = "none"  # none|some|a1|a2|b1


@router.post("/start")
async def start_placement(body: StartIn, db: Session = Depends(get_db)) -> dict:
    p = await placement.start(db, body.self_report)
    return {"placement_id": p.id, **placement.get_state(db, p.id)}


@router.get("/{placement_id}/state")
def state(placement_id: str, db: Session = Depends(get_db)) -> dict:
    if not db.get(Placement, placement_id):
        raise HTTPException(404, "placement not found")
    return placement.get_state(db, placement_id)


class AnswerIn(BaseModel):
    exercise_id: str
    response: dict


@router.post("/{placement_id}/answer")
async def answer_placement(placement_id: str, body: AnswerIn, db: Session = Depends(get_db)) -> dict:
    if not db.get(Placement, placement_id):
        raise HTTPException(404, "placement not found")
    result = await placement.answer(db, placement_id, body.exercise_id, body.response)
    if not result["finished"]:
        result["state"] = placement.get_state(db, placement_id)
    return result
