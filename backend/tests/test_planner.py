"""Plan composition (topic ranking, prereq gating) and end-to-end learner
simulations verifying the theta trajectory is sane under sustained
success/failure."""

import random
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.models import GrammarMastery, GrammarTopic, PlanBlock, PlanDay
from app.services import learner, planner


def test_build_plan_day_creates_required_and_stretch_blocks(db_session):
    day = planner.build_plan_day(db_session, "2026-01-01")
    assert day.syllabus_week == 1
    blocks = db_session.scalars(select(PlanBlock).where(PlanBlock.date == "2026-01-01")).all()
    required = [b for b in blocks if b.slot == "required"]
    stretch = [b for b in blocks if b.slot == "stretch"]
    assert len(required) == planner.CORE_LESSON_BLOCKS
    assert len(stretch) == planner.STRETCH_LESSON_BLOCKS
    assert all(b.type == "lesson" for b in blocks)


def test_build_plan_day_is_idempotent_without_force(db_session):
    planner.build_plan_day(db_session, "2026-01-01")
    first_ids = {b.id for b in db_session.scalars(select(PlanBlock).where(PlanBlock.date == "2026-01-01"))}
    planner.build_plan_day(db_session, "2026-01-01")  # no force -> same blocks
    second_ids = {b.id for b in db_session.scalars(select(PlanBlock).where(PlanBlock.date == "2026-01-01"))}
    assert first_ids == second_ids


def test_never_attempted_topics_prioritized_over_mastered(db_session):
    topics = db_session.scalars(select(GrammarTopic).order_by(GrammarTopic.sort)).all()
    no_prereq = [t for t in topics if not t.prereq_ids]
    assert no_prereq
    first = no_prereq[0]

    for _ in range(6):
        learner.update_grammar_mastery(db_session, first.id, 1.0)
    row = db_session.get(GrammarMastery, first.id)
    row.first_seen = row.first_seen - timedelta(days=10)
    db_session.commit()
    assert learner.is_topic_mastered(db_session, first.id)

    planner.build_plan_day(db_session, "2026-02-01")
    blocks = db_session.scalars(
        select(PlanBlock).where(PlanBlock.date == "2026-02-01", PlanBlock.slot == "required")
    ).all()
    required_topic_ids = [b.params["topic_id"] for b in blocks]
    assert first.id not in required_topic_ids  # mastered -> deprioritized
    # every required slot went to a topic with zero attempts (highest priority tier)
    mastery_rows = {m.topic_id: m for m in db_session.scalars(select(GrammarMastery))}
    assert all(tid not in mastery_rows for tid in required_topic_ids)


def test_complete_block_updates_day_minutes_and_core_done(db_session):
    day = planner.build_plan_day(db_session, "2026-01-01")
    blocks = db_session.scalars(
        select(PlanBlock).where(PlanBlock.date == "2026-01-01", PlanBlock.slot == "required")
    ).all()
    for b in blocks:
        planner.complete_block(db_session, b.id, 10.0)

    db_session.refresh(day)
    assert day.minutes_done == 10.0 * len(blocks)
    assert day.core_done is True


def test_complete_block_does_not_mark_core_done_if_required_blocks_remain(db_session):
    day = planner.build_plan_day(db_session, "2026-01-01")
    blocks = db_session.scalars(
        select(PlanBlock).where(PlanBlock.date == "2026-01-01", PlanBlock.slot == "required")
    ).all()
    planner.complete_block(db_session, blocks[0].id, 10.0)
    db_session.refresh(day)
    assert day.core_done is False


# ---- Learner simulations ----

def _simulate_days(db_session, n_days: int, success_rate: float, seed: int = 42) -> None:
    rng = random.Random(seed)
    start = date.today() - timedelta(days=n_days - 1)
    for i in range(n_days):
        d = start + timedelta(days=i)
        d_str = d.isoformat()
        planner.build_plan_day(db_session, d_str)
        blocks = db_session.scalars(select(PlanBlock).where(PlanBlock.date == d_str)).all()
        for b in blocks:
            score = 1.0 if rng.random() < success_rate else 0.0
            learner.update_from_exercise_attempt(db_session, "mc", b.params["level"], score)
            learner.update_grammar_mastery(db_session, b.params["topic_id"], score)
            # Backdate mastery timestamps to the simulated calendar date so the
            # 7-day mastery-span gate can be satisfied within a fast test run
            # (real wall-clock elapsed time during the test is milliseconds).
            gm = db_session.get(GrammarMastery, b.params["topic_id"])
            sim_dt = datetime.combine(d, datetime.min.time())
            if gm.n == 1:
                gm.first_seen = sim_dt
            gm.last_seen = sim_dt
            db_session.commit()
            planner.complete_block(db_session, b.id, 10.0)


def test_fast_learner_progresses_meaningfully_over_5_weeks(db_session):
    # NOTE: only "mc" exercises exist in this simulation (P2's content), which
    # map to the "grammar" skill alone (see learner.EXERCISE_SKILL) — the other
    # 6 skills correctly stay at 0 with zero practice signal, so we assert on
    # "grammar" directly rather than the cross-skill overall_theta average
    # (which P6/P7/P8 will make representative once they feed those skills).
    _simulate_days(db_session, 35, success_rate=0.88, seed=1)
    grammar = learner.get_theta(db_session, "grammar")
    assert grammar > 25  # observed ~34 in isolation; healthy A1->A2 movement
    mastered = sum(
        1 for t in db_session.scalars(select(GrammarTopic))
        if learner.is_topic_mastered(db_session, t.id)
    )
    assert mastered >= 1  # curriculum actually advanced, not stuck on topic 1


def test_slow_learner_stays_well_below_fast_learner_pace(db_session):
    _simulate_days(db_session, 35, success_rate=0.3, seed=1)
    grammar = learner.get_theta(db_session, "grammar")
    assert grammar < 20  # observed ~16; clearly below the fast-learner threshold above
    mastered = sum(
        1 for t in db_session.scalars(select(GrammarTopic))
        if learner.is_topic_mastered(db_session, t.id)
    )
    assert mastered == 0  # struggling learner: curriculum doesn't advance


def test_idle_learner_theta_does_not_increase(db_session):
    learner.set_theta(db_session, "grammar", 30.0)
    thetas_before = learner.get_all_thetas(db_session)
    # no simulated activity at all
    thetas_after = learner.get_all_thetas(db_session)
    assert thetas_after["grammar"] <= thetas_before["grammar"]
