"""Conversation lifecycle: create (with scenario), fetch transcript, end."""

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from ..db import get_db
from ..models import Conversation, ConvTurn, utcnow
from ..services import content, learner, planner

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("/scenarios")
def list_scenarios() -> list[dict]:
    return content.scenarios()


class StartIn(BaseModel):
    scenario_id: str | None = None  # None = auto-pick like the daily plan does


@router.post("")
def start_conversation(body: StartIn, db: Session = Depends(get_db)) -> dict:
    thetas = learner.get_all_thetas(db)
    level = learner.cefr_label(thetas.get("speaking") or learner.overall_theta(thetas))

    scenario_id = body.scenario_id or planner.pick_scenario_for_day(level, planner.today_str())
    scenario = content.scenario_by_id(scenario_id)
    if scenario is None:
        raise HTTPException(404, "scenario not found")

    conv = Conversation(scenario={"id": scenario["id"], "title_de": scenario["title_de"]}, persona="tutor", level=level)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return {"conv_id": conv.id, "scenario": scenario, "level": level}


@router.get("/{conv_id}/transcript")
def get_transcript(conv_id: str, db: Session = Depends(get_db)) -> dict:
    conv = db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    turns = db.scalars(select(ConvTurn).where(ConvTurn.conv_id == conv_id).order_by(ConvTurn.idx)).all()
    return {
        "id": conv.id, "scenario": conv.scenario, "level": conv.level,
        "started_at": conv.started_at.isoformat(), "ended_at": conv.ended_at.isoformat() if conv.ended_at else None,
        "turns": [
            {"id": t.id, "idx": t.idx, "role": t.role, "text_de": t.text_de,
             "latency": t.latency, "interrupted": t.interrupted}
            for t in turns
        ],
    }


class EndIn(BaseModel):
    block_id: str | None = None


@router.post("/{conv_id}/end")
def end_conversation(conv_id: str, body: EndIn, db: Session = Depends(get_db)) -> dict:
    conv = db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    if conv.ended_at is None:
        conv.ended_at = utcnow()
        conv.minutes = round((conv.ended_at - conv.started_at).total_seconds() / 60, 1)
        db.commit()

    if body.block_id:
        planner.complete_block(db, body.block_id, max(conv.minutes, 1.0))

    return {"id": conv.id, "minutes": conv.minutes}
