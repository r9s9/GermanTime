"""Per-skill learner model: Elo-flavored EWMA theta updates, idle decay,
CEFR mapping, and grammar-topic mastery/unlocking.
"""

import math
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import content
from ..models import GrammarMastery, GrammarTopic, LearnerSkill, utcnow

SKILLS = ["listening", "reading", "writing", "speaking", "grammar", "vocab", "pronunciation"]

# Exercise type -> skill it primarily trains. P2 ships 6 text-exercise types;
# P6 (conversation) feeds speaking/listening, P7 (pronunciation) feeds
# pronunciation, P8 (exams) feeds all four exam skills via mock results.
EXERCISE_SKILL = {
    "mc": "grammar", "cloze": "grammar", "ordering": "grammar",
    "matching": "vocab", "translation": "vocab", "dialogue_gap": "reading",
}

TASK_WEIGHT = {
    "mc": 0.6, "cloze": 0.8, "ordering": 0.8, "matching": 0.6,
    "translation": 1.0, "dialogue_gap": 0.8,
}

LEVEL_MIDPOINT = {"A1": 20.0, "A2": 45.0, "B1": 72.0}

# (label, lo, hi) — also used as placement-test rungs, in this exact order
CEFR_BANDS = [
    ("A1.1", 10, 20), ("A1.2", 20, 30), ("A2.1", 30, 45), ("A2.2", 45, 58),
    ("B1.1", 58, 72), ("B1.2", 72, 85),
]
EXAM_READY_THETA = {"A1": 26, "A2": 52, "B1": 70}

IDLE_DAYS_BEFORE_DECAY = 4
DECAY_PER_DAY = 0.3
DECAY_CAP = 6.0

MASTERY_M_THRESHOLD = 0.85
MASTERY_MIN_N = 6
MASTERY_MIN_SPAN_DAYS = 7


def cefr_label(theta: float) -> str:
    if theta < 10:
        return "Pre-A1"
    for label, lo, hi in CEFR_BANDS:
        if theta < hi:
            return label
    return "B1.2+"


def week_for_theta(theta: float) -> int:
    label = cefr_label(theta)
    weeks = content.syllabus()
    matches = [w["week"] for w in weeks if w["cefr"] == label]
    if matches:
        return matches[0]
    return 1 if theta < 10 else weeks[-1]["week"]


def _get_or_create(db: Session, skill: str) -> LearnerSkill:
    row = db.get(LearnerSkill, skill)
    if row is None:
        row = LearnerSkill(skill=skill, theta=0.0, n_attempts=0, updated_at=utcnow(), history=[])
        db.add(row)
        db.flush()
    return row


def _apply_idle_decay(row: LearnerSkill) -> None:
    idle_days = (utcnow() - row.updated_at).days
    if idle_days <= IDLE_DAYS_BEFORE_DECAY:
        return
    decay = min((idle_days - IDLE_DAYS_BEFORE_DECAY) * DECAY_PER_DAY, DECAY_CAP)
    if decay <= 0:
        return
    row.theta = max(0.0, row.theta - decay)
    row.updated_at = utcnow()


def _record_history(row: LearnerSkill) -> None:
    today = utcnow().date().isoformat()
    hist = row.history or []
    if hist and hist[-1]["d"] == today:
        hist[-1]["theta"] = round(row.theta, 2)
    else:
        hist.append({"d": today, "theta": round(row.theta, 2)})
    row.history = hist[-120:]


def get_theta(db: Session, skill: str) -> float:
    row = _get_or_create(db, skill)
    _apply_idle_decay(row)
    db.commit()
    return row.theta


def get_all_thetas(db: Session) -> dict[str, float]:
    return {s: get_theta(db, s) for s in SKILLS}


def overall_theta(thetas: dict[str, float]) -> float:
    return sum(thetas.values()) / len(thetas) if thetas else 0.0


def set_theta(db: Session, skill: str, theta: float, min_attempts: int = 1) -> None:
    """Direct-set entry point for the placement test (bypasses the EWMA
    update rule since it's initializing from a fresh assessment, not
    revising an existing estimate)."""
    row = _get_or_create(db, skill)
    row.theta = max(0.0, min(100.0, theta))
    row.n_attempts = max(row.n_attempts, min_attempts)
    row.updated_at = utcnow()
    _record_history(row)
    db.commit()


def update_skill(db: Session, skill: str, score: float, difficulty: float, weight: float = 1.0) -> float:
    """score in 0..1, difficulty on the same 0..100 scale as theta."""
    row = _get_or_create(db, skill)
    _apply_idle_decay(row)

    expected = 1.0 / (1.0 + math.exp(-(row.theta - difficulty) / 8.0))
    k = max(0.8, min(3.0, 24.0 / (8.0 + row.n_attempts)))
    row.theta = max(0.0, min(100.0, row.theta + k * weight * (score - expected)))
    row.n_attempts += 1
    row.updated_at = utcnow()
    _record_history(row)
    db.commit()
    return row.theta


def update_from_exercise_attempt(db: Session, exercise_type: str, exercise_level: str, score: float) -> None:
    skill = EXERCISE_SKILL.get(exercise_type)
    if not skill:
        return
    difficulty = LEVEL_MIDPOINT.get(exercise_level, 45.0)
    weight = TASK_WEIGHT.get(exercise_type, 0.7)
    update_skill(db, skill, score, difficulty, weight)


def update_grammar_mastery(db: Session, topic_id: str | None, score: float) -> GrammarMastery | None:
    if not topic_id:
        return None
    row = db.get(GrammarMastery, topic_id)
    if row is None:
        row = GrammarMastery(topic_id=topic_id, m=0.0, n=0)
        db.add(row)
        db.flush()
    row.m = 0.7 * row.m + 0.3 * score
    row.n += 1
    now = utcnow()
    if row.first_seen is None:
        row.first_seen = now
    row.last_seen = now
    db.commit()
    return row


def is_topic_mastered(db: Session, topic_id: str, mastery_row: GrammarMastery | None = None) -> bool:
    row = mastery_row if mastery_row is not None else db.get(GrammarMastery, topic_id)
    if row is None or row.n < MASTERY_MIN_N or row.m < MASTERY_M_THRESHOLD:
        return False
    if row.first_seen and row.last_seen:
        return (row.last_seen - row.first_seen).days >= MASTERY_MIN_SPAN_DAYS
    return False


def credit_prior_topics(db: Session, before_week: int) -> int:
    """Mark grammar topics from syllabus weeks before `before_week` as
    mastered. Without this, a new user's placement result would only ever
    set their displayed "Woche N" — topic *selection* falls back to grammar
    mastery, which starts empty for everyone, so an A2-placed learner would
    still be forced to grind through week-1 topics they already know. This
    is the placement test's entire point: skip content already demonstrated.
    """
    topics = db.scalars(select(GrammarTopic).where(GrammarTopic.syllabus_week < before_week)).all()
    now = utcnow()
    backdated = now - timedelta(days=MASTERY_MIN_SPAN_DAYS)
    for t in topics:
        row = db.get(GrammarMastery, t.id)
        if row is None:
            row = GrammarMastery(topic_id=t.id, m=0.0, n=0)
            db.add(row)
        row.m = 1.0
        row.n = max(row.n, MASTERY_MIN_N)
        row.first_seen = backdated
        row.last_seen = now
    db.commit()
    return len(topics)


def unlocked_topics(db: Session) -> list[GrammarTopic]:
    """Topics whose prerequisites are all mastered (topics with no prereqs are always unlocked)."""
    topics = db.scalars(select(GrammarTopic).order_by(GrammarTopic.sort)).all()
    mastery = {m.topic_id: m for m in db.scalars(select(GrammarMastery))}
    mastered_ids = {t.id for t in topics if is_topic_mastered(db, t.id, mastery.get(t.id))}
    return [t for t in topics if all(p in mastered_ids for p in t.prereq_ids)]


def vocab_coverage(db: Session) -> dict[str, float]:
    """Share of each Goethe wordlist level considered "known": has SRS reps
    and isn't struggling. Wired up fully once P4 (SRS) exists; for now,
    approximated from vocab used correctly in exercise attempts.
    """
    from ..models import Exercise, ExerciseAttempt, VocabItem

    totals = {lvl: 0 for lvl in ("A1", "A2", "B1")}
    for v in db.scalars(select(VocabItem)):
        if v.level in totals:
            totals[v.level] += 1

    known: dict[str, set[str]] = {"A1": set(), "A2": set(), "B1": set()}
    rows = db.execute(
        select(Exercise.level, Exercise.vocab_ids, ExerciseAttempt.score)
        .join(ExerciseAttempt, ExerciseAttempt.exercise_id == Exercise.id)
        .where(ExerciseAttempt.score >= 0.8)
    ).all()
    for level, vocab_ids, _score in rows:
        if level in known:
            known[level].update(vocab_ids or [])

    return {lvl: (len(known[lvl]) / totals[lvl] if totals[lvl] else 0.0) for lvl in totals}
