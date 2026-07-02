"""Placement staircase state machine — the LLM call is faked (always returns
the same MC item with correct_index=0) so answering {"index": 0} is always
correct and {"index": 1} is always wrong, making the staircase deterministic."""

import pytest

from app.services import exercise_types as et
from app.services import learner, placement, planner

_MC_ITEM = et.GeneratedMC(
    prompt_de="Q?", options=["a", "b", "c", "d"], correct_index=0,
    explanation_de="d", explanation_en="e",
)


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    async def fake_generate_structured(role, system, user, model_cls, schema_name, **kwargs):
        return _MC_ITEM
    monkeypatch.setattr(placement.factory.llm, "generate_structured", fake_generate_structured)


async def _answer_all(db, placement_id, index):
    state = placement.get_state(db, placement_id)
    result = None
    for item in state["items"]:
        result = await placement.answer(db, placement_id, item["id"], {"index": index})
    return result


@pytest.mark.asyncio
async def test_placement_starts_at_self_reported_rung(db_session):
    p = await placement.start(db_session, "a2")
    assert p.result["rung"] == 2


@pytest.mark.asyncio
async def test_default_self_report_starts_at_bottom(db_session):
    p = await placement.start(db_session, "none")
    assert p.result["rung"] == 0


@pytest.mark.asyncio
async def test_answering_correctly_advances_rung(db_session):
    p = await placement.start(db_session, "none")
    result = await _answer_all(db_session, p.id, 0)  # always correct
    assert result["finished"] is False
    assert result["next_rung"] == 1


@pytest.mark.asyncio
async def test_answering_wrong_at_bottom_rung_finishes(db_session):
    p = await placement.start(db_session, "none")
    result = await _answer_all(db_session, p.id, 1)  # always wrong
    assert result["finished"] is True
    assert result["summary"]["reason"] == "edge"


@pytest.mark.asyncio
async def test_passing_top_rung_finishes_with_high_theta(db_session):
    p = await placement.start(db_session, "b1")  # rung 4 (second-to-last)
    result = await _answer_all(db_session, p.id, 0)
    assert result["finished"] is False
    assert result["next_rung"] == 5  # advanced to top rung

    result = await _answer_all(db_session, p.id, 0)
    assert result["finished"] is True
    assert result["summary"]["reason"] == "top_rung_passed"
    assert learner.get_theta(db_session, "grammar") > 70


@pytest.mark.asyncio
async def test_three_consecutive_fails_stops_the_test(db_session):
    p = await placement.start(db_session, "b1")  # rung 4, room to fail downward
    fails = 0
    result = None
    for _ in range(10):
        result = await _answer_all(db_session, p.id, 1)  # always wrong
        if result["finished"]:
            break
    assert result["finished"] is True
    assert result["summary"]["reason"] in ("max_fails", "edge")


@pytest.mark.asyncio
async def test_finish_sets_all_seven_skills_with_untested_ones_discounted(db_session):
    p = await placement.start(db_session, "none")  # rung 0 -> one fail hits the bottom edge
    result = await _answer_all(db_session, p.id, 1)  # always wrong -> quick finish
    assert result["finished"] is True

    thetas = learner.get_all_thetas(db_session)
    assert set(thetas) == set(learner.SKILLS)
    # writing/speaking/listening/pronunciation are untested by a text-only
    # placement and must be seeded lower than the directly-measured skills
    assert thetas["speaking"] < thetas["grammar"] or thetas["grammar"] == 0
    assert thetas["grammar"] == thetas["vocab"] == thetas["reading"]


@pytest.mark.asyncio
async def test_finish_sets_six_month_goal_date_if_unset(db_session):
    from app.models import Setting

    assert db_session.get(Setting, "goal_date_b1") is None
    p = await placement.start(db_session, "none")
    await _answer_all(db_session, p.id, 1)
    goal = db_session.get(Setting, "goal_date_b1")
    assert goal is not None and goal.value


@pytest.mark.asyncio
async def test_finish_credits_prior_topics_so_planner_does_not_restart_at_week_1(db_session):
    # regression test: without crediting, an advanced-placed learner's
    # grammar_mastery table starts empty (same as a total beginner's), so the
    # planner would rank week-1 topics as "never attempted" and force them
    # through content the placement result says they already know.
    p = await placement.start(db_session, "b1")  # rung 4
    result = await _answer_all(db_session, p.id, 0)  # pass -> advances to rung 5 (top)
    assert result["finished"] is False
    result = await _answer_all(db_session, p.id, 0)  # pass top rung -> finished
    assert result["finished"] is True
    assert result["summary"]["reason"] == "top_rung_passed"

    week = result["summary"]["syllabus_week"]
    ranked = planner._ranked_topics(db_session)
    early_topics = [t for t in ranked if t.sort < 3]
    assert not any(t.id in {rt.id for rt in ranked[:planner.CORE_LESSON_BLOCKS]} for t in early_topics), (
        "an advanced placement should not leave week-1 topics as top planner priority"
    )
    assert week > 1


@pytest.mark.asyncio
async def test_progress_overview_reports_placement_status(db_session):
    from app.api.progress import overview

    assert overview(db=db_session)["has_placement"] is False

    p = await placement.start(db_session, "none")
    await _answer_all(db_session, p.id, 1)

    assert overview(db=db_session)["has_placement"] is True
