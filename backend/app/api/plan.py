"""Daily plan: today's blocks, completion, rebuild, and readiness projection."""

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from ..db import get_db
from ..models import PlanBlock, PlanDay, Setting
from ..services import planner, projection

router = APIRouter(prefix="/api/plan", tags=["plan"])


def _public_day(db: Session, day: PlanDay) -> dict:
    blocks = db.scalars(
        select(PlanBlock).where(PlanBlock.date == day.date).order_by(PlanBlock.slot, PlanBlock.sort)
    ).all()
    return {
        "date": day.date, "syllabus_week": day.syllabus_week, "status": day.status,
        "core_done": day.core_done, "minutes_done": day.minutes_done,
        "blocks": [
            {"id": b.id, "slot": b.slot, "type": b.type, "params": b.params, "status": b.status,
             "minutes_est": b.minutes_est, "minutes_actual": b.minutes_actual}
            for b in blocks
        ],
    }


@router.get("/today")
def plan_today(db: Session = Depends(get_db)) -> dict:
    day = planner.build_plan_day(db, planner.today_str())
    return _public_day(db, day)


@router.post("/rebuild")
def rebuild(db: Session = Depends(get_db)) -> dict:
    day = planner.build_plan_day(db, planner.today_str(), force=True)
    return _public_day(db, day)


class CompleteIn(BaseModel):
    minutes_actual: float


@router.post("/blocks/{block_id}/start")
def start_block(block_id: str, db: Session = Depends(get_db)) -> dict:
    block = db.get(PlanBlock, block_id)
    if not block:
        raise HTTPException(404, "block not found")
    block.status = "active"
    db.commit()
    return {"id": block.id, "status": block.status}


@router.post("/blocks/{block_id}/complete")
def complete_block_endpoint(block_id: str, body: CompleteIn, db: Session = Depends(get_db)) -> dict:
    try:
        block = planner.complete_block(db, block_id, body.minutes_actual)
    except ValueError:
        raise HTTPException(404, "block not found")
    return {"id": block.id, "status": block.status, "minutes_actual": block.minutes_actual}


@router.get("/projection")
def plan_projection(db: Session = Depends(get_db)) -> dict:
    goal = db.get(Setting, "goal_date_b1")
    goal_date = goal.value if goal and goal.value else projection.default_goal_date()
    return projection.compute_projection(db, goal_date)
