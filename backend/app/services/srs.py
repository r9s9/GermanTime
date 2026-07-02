"""FSRS-backed spaced repetition for vocab and error-notebook cards.

fsrs.Card requires timezone-aware UTC datetimes; the rest of this app
stores naive UTC (see models.utcnow()). `_aware`/`_naive` are the only
place that boundary is crossed.
"""

from datetime import datetime, timezone

from fsrs import Card as FsrsCard
from fsrs import Rating, Scheduler
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ErrorNote, ReviewLog, SrsCard, VocabItem, utcnow

_scheduler = Scheduler(desired_retention=0.9)

RATING_MAP = {1: Rating.Again, 2: Rating.Hard, 3: Rating.Good, 4: Rating.Easy}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _new_fsrs_card(now: datetime) -> FsrsCard:
    card = FsrsCard()
    card.due = _aware(now)
    return card


def create_vocab_card(db: Session, vocab_id: int, direction: str = "de_en") -> SrsCard:
    existing = db.scalar(
        select(SrsCard).where(SrsCard.kind == "vocab", SrsCard.ref_id == str(vocab_id), SrsCard.direction == direction)
    )
    if existing:
        return existing

    now = utcnow()
    fcard = _new_fsrs_card(now)
    row = SrsCard(kind="vocab", ref_id=str(vocab_id), direction=direction,
                   fsrs=fcard.to_dict(), due=_naive(fcard.due))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_error_card(db: Session, error_note_id: str) -> SrsCard:
    now = utcnow()
    fcard = _new_fsrs_card(now)
    row = SrsCard(kind="error", ref_id=error_note_id, direction="de_en",
                   fsrs=fcard.to_dict(), due=_naive(fcard.due))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def due_cards(db: Session, limit: int = 40) -> list[SrsCard]:
    return list(db.scalars(
        select(SrsCard).where(SrsCard.suspended.is_(False), SrsCard.due <= utcnow())
        .order_by(SrsCard.due).limit(limit)
    ))


def due_count(db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(SrsCard).where(SrsCard.suspended.is_(False), SrsCard.due <= utcnow())
    ) or 0


def card_content(db: Session, card: SrsCard) -> dict:
    if card.kind == "vocab":
        vocab = db.get(VocabItem, int(card.ref_id))
        if vocab is None:
            return {"front": "?", "back": "?", "front_is_de": False, "back_is_de": False}
        de_form = f"{vocab.article + ' ' if vocab.article else ''}{vocab.lemma}"
        if card.direction == "en_de":
            return {"front": vocab.en_gloss, "back": de_form, "front_is_de": False, "back_is_de": True}
        return {"front": de_form, "back": vocab.en_gloss, "front_is_de": True, "back_is_de": False}

    if card.kind == "error":
        note = db.get(ErrorNote, card.ref_id)
        if note is None:
            return {"front": "?", "back": "?", "front_is_de": False, "back_is_de": False}
        return {"front": note.wrong_de, "back": note.right_de, "note_de": note.note_de,
                "note_en": note.note_en, "front_is_de": True, "back_is_de": True}

    return {"front": "?", "back": "?", "front_is_de": False, "back_is_de": False}


def review_card(db: Session, card_id: str, rating: int, elapsed_ms: int = 0, now: datetime | None = None) -> SrsCard:
    row = db.get(SrsCard, card_id)
    if row is None:
        raise ValueError("card not found")

    now = now or utcnow()
    fcard = FsrsCard.from_dict(row.fsrs)
    new_card, log = _scheduler.review_card(fcard, RATING_MAP[rating], review_datetime=_aware(now))

    row.fsrs = new_card.to_dict()
    row.due = _naive(new_card.due)
    row.reps += 1
    if rating == Rating.Again.value:
        row.lapses += 1

    db.add(ReviewLog(card_id=row.id, rating=rating, reviewed_at=now, elapsed_ms=elapsed_ms,
                      fsrs_log=log.to_dict()))
    db.commit()
    db.refresh(row)
    return row
