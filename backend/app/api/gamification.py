"""Gamification summary: XP/level, streak, and badge showcase."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from ..db import get_db
from ..models import Badge, BadgeAward
from ..services import gamification

router = APIRouter(prefix="/api/gamify", tags=["gamification"])


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict:
    level = gamification.level_info(db)
    streak = gamification.current_streak(db)
    freeze_bank = gamification.freeze_bank(db)

    awarded = {a.badge_id: a for a in db.scalars(select(BadgeAward))}
    badges = [
        {
            "id": b.id, "name_de": b.name_de, "name_en": b.name_en,
            "desc_de": b.desc_de, "desc_en": b.desc_en, "icon": b.icon,
            "awarded": b.id in awarded,
            "awarded_at": awarded[b.id].awarded_at.isoformat() if b.id in awarded else None,
        }
        for b in db.scalars(select(Badge).order_by(Badge.sort))
    ]

    return {
        "level": level["level"], "total_xp": level["total_xp"],
        "xp_into_level": level["xp_into_level"], "xp_for_next_level": level["xp_for_next_level"],
        "streak": streak, "freeze_bank": freeze_bank,
        "badges": badges, "badges_earned": sum(1 for b in badges if b["awarded"]),
    }
