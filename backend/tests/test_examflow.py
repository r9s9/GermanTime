"""Exam lifecycle: module unlocking, section grading, module/exam
completion. LLM calls (content generation, writing/speaking grading) are
faked (matching test_factory.py's pattern) so these run with no server —
the point is protecting the state-machine logic, not re-verifying LLM
content quality (that's what the live e2e run against the real stack is for).
"""

import pytest
from sqlalchemy import select

from app.models import GrammarTopic, VocabItem
from app.services import examflow, examgen, grader
from app.services.examgen import (
    ComprehensionPart, ComprehensionQuestion, MatchingPart, MatchSituation,
    SpeakingPart, WritingBlank, WritingPart,
)

# -- shape_for mapping -------------------------------------------------

def test_shape_for_covers_every_blueprint_kind():
    expected = {
        "mc3": "comprehension", "truefalse": "comprehension", "yesno": "comprehension",
        "mixed_tf_mc": "comprehension", "match2": "matching", "match": "matching",
        "speaker_match": "matching", "form": "writing", "text": "writing",
        "monolog": "speaking", "qa_cards": "speaking", "requests": "speaking",
        "planning": "speaking", "presentation": "speaking", "feedback_qa": "speaking",
    }
    for kind, shape in expected.items():
        assert examgen.shape_for(kind) == shape


# -- auto-grading --------------------------------------------------------

def test_grade_comprehension_counts_matches():
    key = {"correct_indices": [0, 1, 2]}
    result = grader.grade_comprehension(key, {"indices": [0, 1, 1]})
    assert result["score"] == pytest.approx(2 / 3)
    assert result["detail"]["n_correct"] == 2


def test_grade_comprehension_handles_short_response():
    key = {"correct_indices": [0, 1, 2]}
    result = grader.grade_comprehension(key, {"indices": [0]})
    assert result["score"] == pytest.approx(1 / 3)


def test_grade_matching_counts_matches():
    key = {"correct_options": ["a", "b", "c"]}
    result = grader.grade_matching(key, {"options": ["a", "x", "c"]})
    assert result["score"] == pytest.approx(2 / 3)


def test_grade_form_lenient_similarity_and_empty_key():
    key = {"expected_answers": ["Anna Keller", "12.03.1995"]}
    result = grader.grade_form(key, {"answers": ["Anna Keller", "12. Maerz 1995"]})
    assert result["detail"]["per_blank"][0] == 1.0  # exact match
    assert 0.0 <= result["detail"]["per_blank"][1] < 1.0  # close but not exact

    empty = grader.grade_form({"expected_answers": []}, {"answers": []})
    assert empty["score"] == 0.0  # regression: must not ZeroDivisionError


# -- fixtures: fake LLM content -------------------------------------------

def _fake_generate_part(shape, kind):
    if shape == "comprehension":
        return ComprehensionPart(passage_de="Ein Text.", questions=[
            ComprehensionQuestion(prompt_de="Frage?", options=["richtig", "falsch"], correct_index=0),
        ])
    if shape == "matching":
        return MatchingPart(options=["a: X", "b: Y"], situations=[MatchSituation(situation_de="S1", correct_option="a")])
    if shape == "writing":
        if kind == "form":
            return WritingPart(scenario_de="Formular.", content_points_de=[],
                                blanks=[WritingBlank(label_de="Name", expected_answer="Anna")])
        return WritingPart(scenario_de="Schreib etwas.", content_points_de=["Punkt 1"], blanks=[])
    return SpeakingPart(instructions_de="Stell dich vor.", prompts_de=["Wie heisst du?"])


@pytest.fixture(autouse=True)
def fake_llm_content(monkeypatch):
    async def fake_generate_part(level, kind, spec, items):
        shape = examgen.shape_for(kind)
        return shape, _fake_generate_part(shape, kind)

    monkeypatch.setattr(examgen, "generate_part", fake_generate_part)


@pytest.fixture(autouse=True)
def fake_writing_and_speaking_grading(monkeypatch):
    # Patch the exact module object examflow.py itself holds a reference to
    # (examflow.exam_grading), not a freshly-imported one — db_session's
    # sys.modules purge means a fresh `from app.services import
    # exam_grading` here isn't guaranteed to be the same object examflow.py
    # will actually call through.
    async def fake_grade_writing(db, level, scenario_de, content_points, target_words, submitted_text):
        return {"score": 0.8, "detail": {"scores_pct": [80, 80], "divergence_flagged": False,
                                          "content_covered": True, "corrected_text_de": submitted_text,
                                          "feedback_de": "Gut.", "errors": []}}

    async def fake_grade_speaking(instructions_de, prompts_de, transcript, level):
        return {"score": 0.7, "detail": {"task_fulfilled": True, "feedback_de": "Gut gemacht."}}

    monkeypatch.setattr(examflow.exam_grading, "grade_writing", fake_grade_writing)
    monkeypatch.setattr(examflow.exam_grading, "grade_speaking", fake_grade_speaking)


# -- state machine ---------------------------------------------------------

@pytest.mark.asyncio
async def test_start_creates_all_modules_locked_except_first(db_session):
    exam = examflow.start(db_session, "A1", "full")
    state = examflow.get_state(db_session, exam.id)
    assert state["module_order"][0] == "hoeren"
    assert state["modules"]["hoeren"]["status"] == "not_started"
    for name in state["module_order"][1:]:
        assert state["modules"][name]["status"] == "locked"


@pytest.mark.asyncio
async def test_start_module_persists_across_a_fresh_session(db_session):
    """Regression: exam.results is a JSON column mutated via a nested-dict
    reassignment pattern. Mutating a nested sub-dict in place before
    reassigning the parent attribute makes SQLAlchemy's change-tracking
    see no difference and silently drop the write — this only shows up
    when a *different* session reads the row back, not in the same
    session, so the assertion here specifically re-fetches fresh.
    """
    from app.db import SessionLocal

    exam = examflow.start(db_session, "A1", "full")
    await examflow.start_module(db_session, exam.id, "hoeren")
    db_session.commit()

    with SessionLocal() as fresh:
        from app.models import MockExam
        reloaded = fresh.get(MockExam, exam.id)
        assert reloaded.results["modules"]["hoeren"]["status"] == "active"
        assert len(reloaded.results["modules"]["hoeren"]["section_ids"]) == 3


@pytest.mark.asyncio
async def test_start_module_raises_if_previous_not_done(db_session):
    exam = examflow.start(db_session, "A1", "full")
    with pytest.raises(ValueError):
        await examflow.start_module(db_session, exam.id, "lesen")


@pytest.mark.asyncio
async def test_start_module_is_idempotent(db_session):
    exam = examflow.start(db_session, "A1", "full")
    state1 = await examflow.start_module(db_session, exam.id, "hoeren")
    state2 = await examflow.start_module(db_session, exam.id, "hoeren")
    ids1 = [s["id"] for s in state1["modules"]["hoeren"]["sections"]]
    ids2 = [s["id"] for s in state2["modules"]["hoeren"]["sections"]]
    assert ids1 == ids2  # second call must not regenerate content


@pytest.mark.asyncio
async def test_submitting_all_sections_completes_module_and_unlocks_next(db_session):
    exam = examflow.start(db_session, "A1", "full")
    state = await examflow.start_module(db_session, exam.id, "hoeren")
    sections = state["modules"]["hoeren"]["sections"]

    for i, sec in enumerate(sections):
        response = {"indices": [0]} if sec["shape"] == "comprehension" else {"options": ["a"]}
        result = await examflow.submit_section(db_session, exam.id, sec["id"], response)

    assert result["modules"]["hoeren"]["status"] == "done"
    assert result["modules"]["hoeren"]["score"] == result["modules"]["hoeren"]["max_score"]  # all answered correctly
    assert result["modules"]["lesen"]["status"] == "not_started"  # now unlocked, not locked


@pytest.mark.asyncio
async def test_full_a1_exam_completes_and_computes_pass(db_session, monkeypatch):
    from app.models import Conversation, ConvTurn

    exam = examflow.start(db_session, "A1", "full")
    for module_name in ["hoeren", "lesen", "schreiben"]:
        state = await examflow.start_module(db_session, exam.id, module_name)
        for sec in state["modules"][module_name]["sections"]:
            if sec["shape"] == "comprehension":
                response = {"indices": [0]}
            elif sec["shape"] == "matching":
                response = {"options": ["a"]}
            else:  # writing (form or text) - both auto/LLM paths exercised
                response = {"answers": ["Anna"]} if sec["kind"] == "form" else {"text": "Ein Text."}
            state = await examflow.submit_section(db_session, exam.id, sec["id"], response)

    state = await examflow.start_module(db_session, exam.id, "sprechen")
    conv_id = state["modules"]["sprechen"]["conv_id"]
    db_session.add(ConvTurn(conv_id=conv_id, idx=0, role="assistant", text_de="Hallo."))
    db_session.add(ConvTurn(conv_id=conv_id, idx=1, role="user", text_de="Hallo, ich heisse Anna."))
    db_session.commit()

    final = await examflow.finish_speaking(db_session, exam.id)

    assert final["status"] == "done"
    assert all(final["modules"][m]["status"] == "done" for m in final["module_order"])
    assert "passed" in final and isinstance(final["passed"], bool)
    assert final["total_pct"] > 0

    from app.models import MockExam
    reloaded = db_session.get(MockExam, exam.id)
    assert reloaded.finished_at is not None
    assert reloaded.readiness_snapshot.get("level") == "A1"
