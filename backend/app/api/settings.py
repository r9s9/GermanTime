"""Settings and LM Studio model-role assignment."""

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from .. import config
from ..db import get_db
from ..models import ModelRole, Setting

router = APIRouter(prefix="/api", tags=["settings"])

DEFAULT_SETTINGS = {
    "daily_stretch_minutes": 15,
    "voice_engine": "piper",  # piper|chatterbox — piper measured ~112ms p50 vs chatterbox's 2.2s p50 (see memory: project-chatterbox-latency); piper is the real-time default, chatterbox is an opt-in
    "goal_date_b1": None,  # computed on placement finish (today + 6 months)
    "scaffolding_override": None,  # null = automatic by level
}


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> dict:
    rows = {s.key: s.value for s in db.scalars(select(Setting))}
    return {**DEFAULT_SETTINGS, **rows}


class SettingUpdate(BaseModel):
    value: dict | list | str | int | float | bool | None


@router.put("/settings/{key}")
def put_setting(key: str, body: SettingUpdate, db: Session = Depends(get_db)) -> dict:
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=body.value)
        db.add(row)
    else:
        row.value = body.value
    db.commit()
    return {"key": key, "value": body.value}


class RolesUpdate(BaseModel):
    tutor: str | None = None
    fast: str | None = None
    embed: str | None = None


@router.get("/models/roles")
def get_roles(db: Session = Depends(get_db)) -> dict:
    return {r.role: r.model_id for r in db.scalars(select(ModelRole))}


@router.put("/models/roles")
def put_roles(body: RolesUpdate, db: Session = Depends(get_db)) -> dict:
    updates = body.model_dump(exclude_unset=True)
    for role, model_id in updates.items():
        if model_id is None:
            continue
        row = db.get(ModelRole, role)
        if row is None:
            row = ModelRole(role=role, model_id=model_id)
            db.add(row)
        else:
            row.model_id = model_id
    db.commit()

    if updates.get("tutor"):
        # start.ps1 reads this to `lms load` the tutor model ahead of time.
        config.ensure_dirs()
        (config.DATA_DIR / "tutor_model.txt").write_text(updates["tutor"], encoding="utf-8")

    return {r.role: r.model_id for r in db.scalars(select(ModelRole))}
