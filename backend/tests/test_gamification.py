"""XP formulas, levels, streak/freeze bookkeeping, and badge evaluation.
Streak tests drive DailyActivity rows with explicit dates rather than
real "today" so they're deterministic — no clock mocking needed since
mark_core_done() takes date_str directly.
"""

import pytest

from app.services import gamification as gam


# -- XP formulas -----------------------------------------------------------

def test_xp_for_exercise_scales_with_score_and_difficulty():
    assert gam.xp_for_exercise(1.0, 1.0) == 10  # 10*1.0*(0.4+0.6*1.0)
    assert gam.xp_for_exercise(0.0, 1.0) == 4   # 10*1.0*(0.4+0)
    assert gam.xp_for_exercise(1.0, 1.6) == 16  # B1 multiplier


def test_xp_for_conversation_bonus_at_8_turns():
    assert gam.xp_for_conversation(5.0, 3) == 25          # 5*5, no bonus
    assert gam.xp_for_conversation(5.0, 8) == 25 + 15      # bonus at exactly 8
    assert gam.xp_for_conversation(5.0, 7) == 25           # no bonus at 7


def test_xp_for_drill_scales_0_to_8():
    assert gam.xp_for_drill(100) == 8
    assert gam.xp_for_drill(0) == 0
    assert gam.xp_for_drill(50) == 4


# -- levels ------------------------------------------------------------

def test_level_info_thresholds(db_session):
    gam.award_xp(db_session, "test", 499)
    assert gam.level_info(db_session)["level"] == 1
    gam.award_xp(db_session, "test", 1)  # crosses 500
    assert gam.level_info(db_session)["level"] == 2
    gam.award_xp(db_session, "test", 750)  # crosses 500+750=1250 (level 2->3 costs 750)
    assert gam.level_info(db_session)["level"] == 3


def test_level_never_blocks_negative_or_zero_xp(db_session):
    assert gam.award_xp(db_session, "test", 0) == 0
    assert gam.award_xp(db_session, "test", -5) == 0
    assert gam.total_xp(db_session) == 0


# -- streaks -------------------------------------------------------------

def test_first_core_done_starts_streak_at_1(db_session):
    activity = gam.mark_core_done(db_session, "2026-01-01")
    assert activity.streak_after == 1


def test_consecutive_days_extend_streak(db_session):
    gam.mark_core_done(db_session, "2026-01-01")
    gam.mark_core_done(db_session, "2026-01-02")
    activity = gam.mark_core_done(db_session, "2026-01-03")
    assert activity.streak_after == 3


def test_marking_the_same_day_twice_is_idempotent(db_session):
    gam.mark_core_done(db_session, "2026-01-01")
    xp_after_first = gam.total_xp(db_session)
    activity = gam.mark_core_done(db_session, "2026-01-01")
    assert activity.streak_after == 1
    assert gam.total_xp(db_session) == xp_after_first  # no double XP


def test_gap_without_freeze_resets_streak(db_session):
    gam.mark_core_done(db_session, "2026-01-01")
    gam.mark_core_done(db_session, "2026-01-02")
    # skip to the 10th — an 8-day gap, no freeze banked yet
    activity = gam.mark_core_done(db_session, "2026-01-10")
    assert activity.streak_after == 1
    assert activity.freeze_used is False


def test_one_day_gap_is_bridged_by_a_banked_freeze(db_session):
    from app.models import Setting

    db_session.add(Setting(key=gam.FREEZE_BANK_SETTING_KEY, value=1))
    db_session.commit()

    gam.mark_core_done(db_session, "2026-01-01")
    # skip the 2nd entirely, resume on the 3rd — a 1-day gap
    activity = gam.mark_core_done(db_session, "2026-01-03")
    assert activity.freeze_used is True
    assert activity.streak_after == 2  # continued, not reset
    assert gam.freeze_bank(db_session) == 0  # spent


def test_gap_exceeding_freeze_bank_resets(db_session):
    from app.models import Setting

    db_session.add(Setting(key=gam.FREEZE_BANK_SETTING_KEY, value=1))
    db_session.commit()

    gam.mark_core_done(db_session, "2026-01-01")
    # 3-day gap, only 1 freeze available -> resets
    activity = gam.mark_core_done(db_session, "2026-01-05")
    assert activity.streak_after == 1


def test_freeze_earned_every_7_day_streak(db_session):
    date_str = "2026-01-01"
    from datetime import date, timedelta
    d = date.fromisoformat(date_str)
    for _ in range(7):
        gam.mark_core_done(db_session, d.isoformat())
        d += timedelta(days=1)
    assert gam.freeze_bank(db_session) == 1


def test_current_streak_reads_latest_row(db_session):
    gam.mark_core_done(db_session, "2026-01-01")
    gam.mark_core_done(db_session, "2026-01-02")
    assert gam.current_streak(db_session, as_of="2026-01-02") == 2
    assert gam.current_streak(db_session, as_of="2026-01-03") == 2  # still alive, today not done yet
    assert gam.current_streak(db_session, as_of="2026-01-10") == 0  # long gone stale


# -- badges ------------------------------------------------------------

def test_evaluate_badges_awards_streak_7(db_session):
    from datetime import date, timedelta

    d = date.fromisoformat("2026-01-01")
    for _ in range(7):
        gam.mark_core_done(db_session, d.isoformat())
        d += timedelta(days=1)

    from app.models import BadgeAward
    awarded_ids = {a.badge_id for a in db_session.query(BadgeAward).all()}
    assert "flamme_7" in awarded_ids
    assert "flamme_30" not in awarded_ids  # not yet


def test_evaluate_badges_is_idempotent(db_session):
    from app.models import Conversation, utcnow

    db_session.add(Conversation(scenario={"id": "frei"}, level="A1.1", ended_at=utcnow()))
    db_session.commit()

    first = gam.evaluate_badges(db_session)
    second = gam.evaluate_badges(db_session)
    assert any(b.id == "stimme_gefunden" for b in first)
    assert len(second) == 0  # already awarded — nothing new the second time


def test_conversations_done_badge(db_session):
    from app.models import Conversation, utcnow

    conv = Conversation(scenario={"id": "frei"}, level="A1.1", ended_at=utcnow())
    db_session.add(conv)
    db_session.commit()

    gam.evaluate_badges(db_session)
    from app.models import BadgeAward
    awarded_ids = {a.badge_id for a in db_session.query(BadgeAward).all()}
    assert "stimme_gefunden" in awarded_ids


def test_mock_passed_badge(db_session):
    from app.models import MockExam, utcnow

    exam = MockExam(level="A1", finished_at=utcnow(), results={"passed": True})
    db_session.add(exam)
    db_session.commit()

    gam.evaluate_badges(db_session)
    from app.models import BadgeAward
    awarded_ids = {a.badge_id for a in db_session.query(BadgeAward).all()}
    assert "pruefungsreif_a1" in awarded_ids
    assert "pruefungsreif_a2" not in awarded_ids
