"""Content factory: cache top-up, practice-set assembly, and upcoming-topic
pre-fill. The LLM call is faked with deterministic fixtures per exercise type
so these run with no server and no network."""

import pytest
from sqlalchemy import select

from app.models import GrammarTopic
from app.services import exercise_types as et
from app.services import factory

_FAKES = {
    "mc": et.GeneratedMC(prompt_de="Q?", options=["a", "b", "c", "d"], correct_index=0,
                          explanation_de="d", explanation_en="e"),
    "cloze": et.GeneratedCloze(text_de="x ___ y", correct_answer="a", distractors=["b", "c"],
                                explanation_de="d", explanation_en="e"),
    "ordering": et.GeneratedOrdering(correct_sentence="Ich lerne Deutsch", translation_en="I learn German"),
    "matching": et.GeneratedMatching(prompt_de="p", pairs=[
        et.MatchPair(left=f"l{i}", right=f"r{i}") for i in range(4)
    ]),
    "translation": et.GeneratedTranslation(direction="de_en", source_text="s", accepted_answers=["a"], hint_de="h"),
    "dialogue_gap": et.GeneratedDialogueGap(
        turns=[et.DialogueTurn(speaker="A", text_de=f"t{i}") for i in range(4)],
        gap_turn_index=1, options=["o1", "o2", "o3", "o4"], correct_index=0,
    ),
}


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    async def fake_generate_structured(role, system, user, model_cls, schema_name, **kwargs):
        for type_, schema_cls in et.SCHEMAS.items():
            if model_cls is schema_cls:
                return _FAKES[type_]
        raise AssertionError(f"unexpected schema class {model_cls}")

    monkeypatch.setattr(factory.llm, "generate_structured", fake_generate_structured)


@pytest.mark.asyncio
async def test_ensure_cache_fills_all_types_then_is_idempotent(db_session):
    topic = db_session.scalars(select(GrammarTopic)).first()

    created = await factory.ensure_cache(db_session, topic.level, topic.id, count_per_type=1)
    assert len(created) == len(et.EXERCISE_TYPES)
    assert {c.type for c in created} == set(et.EXERCISE_TYPES)

    created_again = await factory.ensure_cache(db_session, topic.level, topic.id, count_per_type=1)
    assert created_again == []  # already satisfied, no duplicate generation


@pytest.mark.asyncio
async def test_get_practice_set_generates_on_demand_and_marks_used(db_session):
    topic = db_session.scalars(select(GrammarTopic)).first()

    exs = await factory.get_practice_set(db_session, topic.level, topic.id, count=3)
    assert len(exs) == 3
    assert all(ex.validated for ex in exs)


@pytest.mark.asyncio
async def test_get_practice_set_prefers_cached_exercises(db_session):
    topic = db_session.scalars(select(GrammarTopic)).first()
    await factory.ensure_cache(db_session, topic.level, topic.id, count_per_type=1)
    cached_ids = {
        ex.id for ex in db_session.scalars(select(factory.Exercise).where(factory.Exercise.topic_id == topic.id))
    }

    exs = await factory.get_practice_set(db_session, topic.level, topic.id, count=2)
    assert all(ex.id in cached_ids for ex in exs)


def test_enqueue_upcoming_orders_by_syllabus_sort(db_session):
    topics = db_session.scalars(select(GrammarTopic).order_by(GrammarTopic.sort)).all()
    jobs = factory.enqueue_upcoming(db_session, from_topic_id=None, n_topics=3)
    assert [j.params["topic_id"] for j in jobs] == [t.id for t in topics[:3]]
    assert all(j.status == "queued" for j in jobs)


def test_enqueue_upcoming_starts_after_given_topic(db_session):
    topics = db_session.scalars(select(GrammarTopic).order_by(GrammarTopic.sort)).all()
    jobs = factory.enqueue_upcoming(db_session, from_topic_id=topics[0].id, n_topics=2)
    assert [j.params["topic_id"] for j in jobs] == [t.id for t in topics[1:3]]


@pytest.mark.asyncio
async def test_process_job_fills_cache_and_marks_done(db_session):
    topics = db_session.scalars(select(GrammarTopic).order_by(GrammarTopic.sort)).all()
    job = factory.enqueue(db_session, "topic_exercises", {
        "level": topics[0].level, "topic_id": topics[0].id,
        "types": et.EXERCISE_TYPES, "count_per_type": 1,
    })

    await factory.process_job(db_session, job)

    assert job.status == "done"
    assert job.finished_at is not None
    cached = db_session.scalars(
        select(factory.Exercise).where(factory.Exercise.topic_id == topics[0].id)
    ).all()
    assert len(cached) == len(et.EXERCISE_TYPES)


@pytest.mark.asyncio
async def test_process_job_records_failure_without_raising(db_session):
    job = factory.enqueue(db_session, "not_a_real_kind", {})
    await factory.process_job(db_session, job)
    assert job.status == "failed"
    assert job.error is not None
