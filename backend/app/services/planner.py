"""Daily plan composition.

"lesson" blocks (P2) and "srs" blocks (P4) exist today. P6/P7/P8 each extend
this module with their own block type as they land — the composition shape
(required core + ranked stretch queue) is already the final design; later
phases add generators, they don't restructure this.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import learner, srs
from ..models import GrammarMastery, GrammarTopic, PlanBlock, PlanDay

CORE_LESSON_BLOCKS = 2
STRETCH_LESSON_BLOCKS = 3
MINUTES_PER_LESSON = 10.0
SRS_BLOCK_MINUTES = 8.0
SRS_BLOCK_CARD_CAP = 20


def _topic_priority(mastery: dict[str, GrammarMastery], topic: GrammarTopic) -> tuple[int, float]:
    gm = mastery.get(topic.id)
    if gm is None:
        return (0, topic.sort)  # never attempted — follow curriculum order
    if gm.m < learner.MASTERY_M_THRESHOLD:
        return (1, -(1.0 - gm.m))  # weakest-first among in-progress topics
    return (2, topic.sort)  # mastered — lowest priority, occasional spaced review


def _ranked_topics(db: Session) -> list[GrammarTopic]:
    unlocked = learner.unlocked_topics(db)
    mastery = {m.topic_id: m for m in db.scalars(select(GrammarMastery))}
    return sorted(unlocked, key=lambda t: _topic_priority(mastery, t))


def _make_lesson_block(date_str: str, slot: str, topic: GrammarTopic, sort: int) -> PlanBlock:
    return PlanBlock(
        date=date_str, slot=slot, type="lesson",
        params={"topic_id": topic.id, "level": topic.level, "title_de": topic.title_de, "title_en": topic.title_en},
        minutes_est=MINUTES_PER_LESSON, sort=sort,
    )


def _compose_blocks(db: Session, date_str: str) -> list[PlanBlock]:
    blocks: list[PlanBlock] = []
    sort = 0
    lesson_slots = CORE_LESSON_BLOCKS

    due = srs.due_count(db)
    if due > 0:
        blocks.append(PlanBlock(
            date=date_str, slot="required", type="srs",
            params={"limit": min(due, SRS_BLOCK_CARD_CAP), "due": due},
            minutes_est=SRS_BLOCK_MINUTES, sort=sort,
        ))
        sort += 1
        lesson_slots = max(1, CORE_LESSON_BLOCKS - 1)  # trim a lesson slot so core stays ~20 min

    ranked = _ranked_topics(db)
    if not ranked:
        return blocks

    core_topics = ranked[:lesson_slots]
    stretch_topics = ranked[lesson_slots:lesson_slots + STRETCH_LESSON_BLOCKS]
    while ranked and len(stretch_topics) < STRETCH_LESSON_BLOCKS:
        stretch_topics.append(ranked[len(stretch_topics) % len(ranked)])

    for i, t in enumerate(core_topics):
        blocks.append(_make_lesson_block(date_str, "required", t, sort + i))
    blocks += [_make_lesson_block(date_str, "stretch", t, i) for i, t in enumerate(stretch_topics)]
    return blocks


def build_plan_day(db: Session, date_str: str, force: bool = False) -> PlanDay:
    existing = db.get(PlanDay, date_str)
    if existing and not force:
        return existing

    thetas = learner.get_all_thetas(db)
    week = learner.week_for_theta(learner.overall_theta(thetas))

    if existing:
        for b in db.scalars(select(PlanBlock).where(PlanBlock.date == date_str, PlanBlock.status == "open")):
            db.delete(b)
        existing.syllabus_week = week
        from ..models import utcnow
        existing.rebuilt_at = utcnow()
        day = existing
    else:
        day = PlanDay(date=date_str, syllabus_week=week, status="open", core_done=False, minutes_done=0.0)
        db.add(day)
    db.flush()

    for block in _compose_blocks(db, date_str):
        db.add(block)
    db.commit()
    db.refresh(day)
    return day


def complete_block(db: Session, block_id: str, minutes_actual: float) -> PlanBlock:
    block = db.get(PlanBlock, block_id)
    if block is None:
        raise ValueError("block not found")
    block.status = "done"
    block.minutes_actual = minutes_actual
    db.commit()

    day = db.get(PlanDay, block.date)
    if day:
        day.minutes_done += minutes_actual
        remaining_required = db.scalar(
            select(PlanBlock).where(PlanBlock.date == day.date, PlanBlock.slot == "required",
                                     PlanBlock.status != "done").limit(1)
        )
        if remaining_required is None:
            day.core_done = True
            day.status = "done" if day.core_done else day.status
        db.commit()
    return block


def today_str() -> str:
    return date.today().isoformat()


def days_ago_str(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()
