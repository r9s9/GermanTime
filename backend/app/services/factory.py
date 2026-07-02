"""Content factory: generates exercises on demand, caches them, and runs a
background queue that tops up upcoming grammar topics so practice sessions
feel instant rather than waiting on an LLM call.
"""

import logging
import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import content, exercise_types, llm
from .concurrency import gpu_lock
from ..db import SessionLocal
from ..models import ContentJob, Exercise, GrammarTopic, VocabItem, utcnow

logger = logging.getLogger(__name__)

EXERCISES_PER_TOPIC = 2  # per type, kept in cache unused


def pick_vocab_words(db: Session, level: str, topic_id: str | None, n: int = 5) -> list[str]:
    tags: set[str] = set()
    if topic_id:
        topic = db.get(GrammarTopic, topic_id)
        if topic:
            week = next((w for w in content.syllabus() if w["week"] == topic.syllabus_week), None)
            if week:
                tags = set(week.get("vocab_tags", []))

    items = db.scalars(select(VocabItem).where(VocabItem.level == level)).all()
    if tags:
        tagged = [v for v in items if set(v.tags) & tags]
        if tagged:
            items = tagged
    return [v.lemma for v in random.sample(items, min(n, len(items)))] if items else []


async def generate_one(db: Session, type_: str, level: str, topic_id: str | None = None) -> Exercise:
    schema_cls = exercise_types.SCHEMAS[type_]
    topic_title = None
    if topic_id:
        topic = db.get(GrammarTopic, topic_id)
        topic_title = topic.title_de if topic else None
    vocab = pick_vocab_words(db, level, topic_id)

    system = exercise_types.system_prompt(level)
    user = exercise_types.user_prompt(type_, level, topic_title, vocab)
    async with gpu_lock:
        item = await llm.generate_structured("tutor", system, user, schema_cls, f"exercise_{type_}")

    valid = exercise_types.structurally_valid(type_, item)
    payload, answer_key = exercise_types.split(type_, item)
    ex = Exercise(
        type=type_, level=level, topic_id=topic_id, vocab_ids=vocab,
        payload=payload, answer_key=answer_key, validated=valid,
    )
    db.add(ex)
    db.commit()
    db.refresh(ex)
    if not valid:
        logger.warning("generated %s exercise failed structural check: %s", type_, payload)
    return ex


def _unused_cached(db: Session, type_: str, level: str, topic_id: str | None) -> list[Exercise]:
    return list(db.scalars(
        select(Exercise).where(
            Exercise.type == type_, Exercise.level == level, Exercise.topic_id == topic_id,
            Exercise.used_at.is_(None), Exercise.validated == True,  # noqa: E712
        )
    ).all())


async def ensure_cache(
    db: Session, level: str, topic_id: str | None,
    types: list[str] | None = None, count_per_type: int = EXERCISES_PER_TOPIC,
) -> list[Exercise]:
    created = []
    for t in types or exercise_types.EXERCISE_TYPES:
        have = len(_unused_cached(db, t, level, topic_id))
        for _ in range(max(0, count_per_type - have)):
            ex = await generate_one(db, t, level, topic_id)
            if ex.validated:
                created.append(ex)
    return created


async def get_practice_set(db: Session, level: str, topic_id: str | None, count: int) -> list[Exercise]:
    pool: list[Exercise] = []
    for t in exercise_types.EXERCISE_TYPES:
        pool.extend(_unused_cached(db, t, level, topic_id))

    types_cycle = (exercise_types.EXERCISE_TYPES * ((count // len(exercise_types.EXERCISE_TYPES)) + 1))
    i = 0
    while len(pool) < count and i < count * 2:
        t = types_cycle[i]
        ex = await generate_one(db, t, level, topic_id)
        if ex.validated:
            pool.append(ex)
        i += 1

    random.shuffle(pool)
    return pool[:count]


def enqueue(db: Session, kind: str, params: dict, priority: int = 5) -> ContentJob:
    job = ContentJob(kind=kind, params=params, priority=priority)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def enqueue_upcoming(db: Session, from_topic_id: str | None = None, n_topics: int = 3) -> list[ContentJob]:
    """Queue `topic_exercises` jobs for the next N grammar topics after
    `from_topic_id` (or from the start if omitted) — the P2-scoped stand-in
    for "pre-fill upcoming days"; P3's planner will call this with the
    learner's actual position instead of a manual topic pointer.
    """
    topics = db.scalars(select(GrammarTopic).order_by(GrammarTopic.sort)).all()
    start = 0
    if from_topic_id:
        for i, t in enumerate(topics):
            if t.id == from_topic_id:
                start = i + 1
                break
    jobs = []
    for topic in topics[start:start + n_topics]:
        jobs.append(enqueue(db, "topic_exercises", {
            "level": topic.level, "topic_id": topic.id,
            "types": exercise_types.EXERCISE_TYPES, "count_per_type": EXERCISES_PER_TOPIC,
        }))
    return jobs


async def process_job(db: Session, job: ContentJob) -> None:
    job.status = "running"
    db.commit()
    try:
        if job.kind == "topic_exercises":
            p = job.params
            await ensure_cache(db, p["level"], p.get("topic_id"), p.get("types"),
                                p.get("count_per_type", EXERCISES_PER_TOPIC))
        else:
            raise ValueError(f"unknown job kind: {job.kind}")
        job.status = "done"
    except Exception as e:  # noqa: BLE001
        job.status = "failed"
        job.error = str(e)
        logger.exception("content job %s failed", job.id)
    job.finished_at = utcnow()
    db.commit()


async def run_queue(limit: int = 10) -> dict:
    processed = 0
    with SessionLocal() as db:
        jobs = db.scalars(
            select(ContentJob).where(ContentJob.status == "queued")
            .order_by(ContentJob.priority, ContentJob.created_at).limit(limit)
        ).all()
        for job in jobs:
            await process_job(db, job)
            processed += 1
    return {"processed": processed}


def queue_status() -> dict:
    with SessionLocal() as db:
        rows = db.execute(select(ContentJob.status, func.count()).group_by(ContentJob.status)).all()
        return {status: n for status, n in rows}
