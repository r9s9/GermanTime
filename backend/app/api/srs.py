"""Spaced-repetition review: due cards, rating submission, and adding a
vocab word from the hover-translate popover."""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from ..db import get_db
from ..models import VocabItem
from ..services import srs

router = APIRouter(prefix="/api/srs", tags=["srs"])


def _public_card(db: Session, card) -> dict:
    return {"id": card.id, "kind": card.kind, "direction": card.direction, **srs.card_content(db, card)}


@router.get("/due")
def get_due(limit: int = 20, db: Session = Depends(get_db)) -> list[dict]:
    return [_public_card(db, c) for c in srs.due_cards(db, limit)]


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict:
    return {"due": srs.due_count(db)}


class ReviewIn(BaseModel):
    card_id: str
    rating: int  # 1=Again 2=Hard 3=Good 4=Easy
    elapsed_ms: int = 0


@router.post("/review")
def review(body: ReviewIn, db: Session = Depends(get_db)) -> dict:
    if body.rating not in (1, 2, 3, 4):
        raise HTTPException(422, "rating must be 1-4")
    try:
        card = srs.review_card(db, body.card_id, body.rating, body.elapsed_ms)
    except ValueError:
        raise HTTPException(404, "card not found")
    return {"id": card.id, "due": card.due.isoformat(), "reps": card.reps, "lapses": card.lapses}


class AddVocabIn(BaseModel):
    vocab_id: int
    direction: str = "de_en"


@router.post("/add-vocab")
def add_vocab(body: AddVocabIn, db: Session = Depends(get_db)) -> dict:
    if not db.get(VocabItem, body.vocab_id):
        raise HTTPException(404, "vocab item not found")
    card = srs.create_vocab_card(db, body.vocab_id, body.direction)
    return {"id": card.id, "kind": card.kind, "direction": card.direction}
