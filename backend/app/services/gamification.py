"""XP, levels, streaks (with auto-freeze), and badge evaluation.

Streak day boundary is 03:00, not midnight (plan.md: late-night study
shouldn't cost you the day). "Today" for streak/XP-bucketing purposes is
always computed via today_str(), never date.today() directly.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import learner
from ..models import (
    Badge, BadgeAward, Conversation, DailyActivity, GrammarMastery, GrammarTopic,
    MockExam, PhonemeStat, PlanBlock, Setting, UtteranceScore, VocabItem, XpEvent, utcnow,
)

DAY_BOUNDARY_HOUR = 3

XP_SRS_REVIEW = 2
XP_CORE_DONE = 25
XP_MOCK_MODULE = 40
XP_MOCK_MODULE_PASS_BONUS = 40
XP_MOCK_FULL_PASS = 250
CONVERSATION_XP_PER_MINUTE = 5
CONVERSATION_LONG_BONUS = 15
CONVERSATION_LONG_TURNS = 8
EXERCISE_XP_BASE = 10
DRILL_XP_MAX = 8
LEVEL_XP_MULTIPLIER = {"A1": 1.0, "A2": 1.3, "B1": 1.6}

LEVEL_BASE_COST = 500
LEVEL_COST_STEP = 250

FREEZE_EARN_EVERY_DAYS = 7
FREEZE_BANK_MAX = 2
FREEZE_BANK_SETTING_KEY = "streak_freeze_bank"


def today_str(now: datetime | None = None) -> str:
    now = now or utcnow()
    return (now - timedelta(hours=DAY_BOUNDARY_HOUR)).date().isoformat()


def _get_or_create_activity(db: Session, date_str: str) -> DailyActivity:
    row = db.get(DailyActivity, date_str)
    if row is None:
        row = DailyActivity(date=date_str, minutes=0.0, xp=0, core_done=False, streak_after=0, freeze_used=False)
        db.add(row)
        db.flush()
    return row


def award_xp(db: Session, kind: str, amount: int, ref: dict | None = None, date_str: str | None = None) -> int:
    if amount <= 0:
        return 0
    date_str = date_str or today_str()
    db.add(XpEvent(amount=amount, kind=kind, ref=ref or {}))
    activity = _get_or_create_activity(db, date_str)
    activity.xp += amount
    db.commit()
    return amount


def xp_for_exercise(score: float, difficulty: float = 1.0) -> int:
    """score: 0..1. difficulty: level-relative multiplier (see
    learner.LEVEL_MIDPOINT-style scaling; callers pass 1.0 for A1-ish,
    higher for harder levels)."""
    return round(EXERCISE_XP_BASE * difficulty * (0.4 + 0.6 * max(0.0, min(1.0, score))))


def xp_for_conversation(minutes: float, turns: int) -> int:
    xp = round(CONVERSATION_XP_PER_MINUTE * max(0.0, minutes))
    if turns >= CONVERSATION_LONG_TURNS:
        xp += CONVERSATION_LONG_BONUS
    return xp


def xp_for_drill(score_0_100: float) -> int:
    return round(DRILL_XP_MAX * max(0.0, min(100.0, score_0_100)) / 100)


def total_xp(db: Session) -> int:
    return db.scalar(select(func.sum(XpEvent.amount))) or 0


def level_info(db: Session) -> dict:
    """cost to go from level n-1 to n is 500 + 250*(n-2) for n>=2 (level 1
    is the free starting level). Levels never gate content — display only.
    """
    xp = total_xp(db)
    remaining = xp
    level = 1
    cost = LEVEL_BASE_COST
    while remaining >= cost:
        remaining -= cost
        level += 1
        cost = LEVEL_BASE_COST + LEVEL_COST_STEP * (level - 1)
    return {"level": level, "total_xp": xp, "xp_into_level": remaining, "xp_for_next_level": cost}


# ---- streaks ----

def _last_activity_before(db: Session, date_str: str) -> DailyActivity | None:
    return db.scalar(
        select(DailyActivity).where(DailyActivity.date < date_str).order_by(DailyActivity.date.desc()).limit(1)
    )


def freeze_bank(db: Session) -> int:
    row = db.get(Setting, FREEZE_BANK_SETTING_KEY)
    return int(row.value) if row and row.value is not None else 0


def _set_freeze_bank(db: Session, n: int) -> None:
    n = max(0, min(FREEZE_BANK_MAX, n))
    row = db.get(Setting, FREEZE_BANK_SETTING_KEY)
    if row is None:
        db.add(Setting(key=FREEZE_BANK_SETTING_KEY, value=n))
    else:
        row.value = n


def mark_core_done(db: Session, date_str: str | None = None) -> DailyActivity:
    """Called once a day's required blocks are all done (planner.complete_block).
    Idempotent — calling again for the same day is a no-op past the first time.
    """
    date_str = date_str or today_str()
    activity = _get_or_create_activity(db, date_str)
    if activity.core_done:
        return activity
    activity.core_done = True

    prev = _last_activity_before(db, date_str)
    bank = freeze_bank(db)

    if prev is None:
        streak = 1
    else:
        gap_days = (date.fromisoformat(date_str) - date.fromisoformat(prev.date)).days - 1
        if gap_days <= 0:
            streak = prev.streak_after + 1
        elif gap_days <= bank and prev.streak_after > 0:
            _set_freeze_bank(db, bank - gap_days)
            activity.freeze_used = True
            streak = prev.streak_after + 1
        else:
            streak = 1

    activity.streak_after = streak
    if streak > 0 and streak % FREEZE_EARN_EVERY_DAYS == 0:
        _set_freeze_bank(db, freeze_bank(db) + 1)

    db.commit()
    award_xp(db, "core_done", XP_CORE_DONE, date_str=date_str)
    evaluate_badges(db, as_of=date_str)
    return activity


def current_streak(db: Session, as_of: str | None = None) -> int:
    """as_of: date string to treat as "today" — defaults to the real
    current date. mark_core_done() passes its own date_str through here
    (via evaluate_badges) so a backfilled/test day evaluates the streak as
    of that day, not whatever the wall clock says right now.
    """
    latest = db.scalar(select(DailyActivity).order_by(DailyActivity.date.desc()).limit(1))
    if latest is None:
        return 0
    # a streak "counts" through today even if today isn't done yet, but a
    # gap of >=2 days since the last recorded activity means it's already broken.
    gap = (date.fromisoformat(as_of or today_str()) - date.fromisoformat(latest.date)).days
    return latest.streak_after if gap <= 1 else 0


# ---- badges ----

def _awarded_ids(db: Session) -> set[str]:
    return {a.badge_id for a in db.scalars(select(BadgeAward))}


def _check_criterion(db: Session, criteria: dict, as_of: str | None = None) -> bool:
    kind = criteria.get("type")

    if kind == "lessons_done":
        n = db.scalar(select(func.count()).select_from(PlanBlock)
                       .where(PlanBlock.type == "lesson", PlanBlock.status == "done")) or 0
        return n >= criteria["n"]

    if kind == "conversations_done":
        n = db.scalar(select(func.count()).select_from(Conversation)
                       .where(Conversation.ended_at.is_not(None))) or 0
        return n >= criteria["n"]

    if kind == "streak":
        return current_streak(db, as_of) >= criteria["n"]

    if kind == "words_known":
        coverage = learner.vocab_coverage(db)
        totals = db.scalar(select(func.count()).select_from(VocabItem)) or 0
        # vocab_coverage returns fractions per level; reconstitute an
        # absolute count across all levels for the "n words known" badges.
        by_level_total: dict[str, int] = {}
        for v_level, cnt in db.execute(select(VocabItem.level, func.count()).group_by(VocabItem.level)).all():
            by_level_total[v_level] = cnt
        known_total = sum(coverage.get(lvl, 0.0) * by_level_total.get(lvl, 0) for lvl in ("A1", "A2", "B1"))
        return known_total >= criteria["n"]

    if kind == "grammar_mastered":
        topics = db.scalars(select(GrammarTopic)).all()
        mastery = {m.topic_id: m for m in db.scalars(select(GrammarMastery))}
        n = sum(1 for t in topics if learner.is_topic_mastered(db, t.id, mastery.get(t.id)))
        return n >= criteria["n"]

    if kind == "phoneme_improved":
        for stat in db.scalars(select(PhonemeStat).where(PhonemeStat.n >= 5)):
            if stat.ema >= criteria["to"] and stat.last10 and min(stat.last10) < criteria["from"]:
                return True
        return False

    if kind == "drills_above":
        n = db.scalar(select(func.count()).select_from(UtteranceScore)
                       .where(UtteranceScore.confidence >= 1.0, UtteranceScore.overall >= criteria["score"])) or 0
        return n >= criteria["n"]

    if kind == "conversation_minutes":
        total = db.scalar(select(func.sum(Conversation.minutes))) or 0.0
        return total >= criteria["n"]

    if kind == "mock_passed":
        exams = db.scalars(
            select(MockExam).where(MockExam.level == criteria["level"], MockExam.finished_at.is_not(None))
        ).all()
        return any(e.results.get("passed") for e in exams)

    if kind == "mock_score_above":
        exams = db.scalars(select(MockExam).where(MockExam.finished_at.is_not(None))).all()
        return any(e.results.get("total_pct", 0) >= criteria["pct"] for e in exams)

    if kind == "comeback":
        return _check_comeback(db, criteria["gap"], criteria["streak"])

    return False


def _check_comeback(db: Session, min_gap: int, min_streak: int) -> bool:
    """True if the current unbroken streak (a) has reached min_streak, and
    (b) began after a gap of >= min_gap days since the previous core-done
    day (i.e. streak_after reset to 1 following a real break, not just the
    very first day ever recorded)."""
    rows = list(db.scalars(select(DailyActivity).where(DailyActivity.core_done.is_(True)).order_by(DailyActivity.date)))
    if not rows:
        return False
    if rows[-1].streak_after < min_streak:
        return False

    # walk back from the end to find where the current run started
    run_start_idx = len(rows) - 1
    while run_start_idx > 0 and rows[run_start_idx - 1].streak_after == rows[run_start_idx].streak_after - 1:
        run_start_idx -= 1
    if run_start_idx == 0:
        return False  # no prior day to have a gap from

    prev_date = date.fromisoformat(rows[run_start_idx - 1].date)
    run_start_date = date.fromisoformat(rows[run_start_idx].date)
    gap = (run_start_date - prev_date).days - 1
    return gap >= min_gap


def evaluate_badges(db: Session, as_of: str | None = None) -> list[Badge]:
    """Checks every badge's criteria against current state and awards any
    newly-unlocked ones. Cheap enough to call after any XP-earning event —
    at most ~20 badges, each a handful of aggregate queries. as_of lets
    mark_core_done() evaluate streak-based criteria relative to the day
    being backfilled/marked, not the real wall-clock date.
    """
    awarded_ids = _awarded_ids(db)
    newly_awarded = []
    for badge in db.scalars(select(Badge).order_by(Badge.sort)):
        if badge.id in awarded_ids:
            continue
        if _check_criterion(db, badge.criteria, as_of):
            db.add(BadgeAward(badge_id=badge.id, context={}))
            newly_awarded.append(badge)
    if newly_awarded:
        db.commit()
    return newly_awarded
