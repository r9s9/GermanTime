"""Error-notebook creation from graded exercise attempts."""

from app.models import Exercise, SrsCard
from app.services import errors, grader


def _make_exercise(db, type_, payload, answer_key, topic_id=None, level="A1"):
    ex = Exercise(type=type_, level=level, topic_id=topic_id, payload=payload,
                   answer_key=answer_key, validated=True)
    db.add(ex)
    db.commit()
    db.refresh(ex)
    return ex


def test_create_error_note_links_srs_card(db_session):
    note = errors.create_error_note(db_session, "grammar", "exercise", "wrong", "right")
    assert note.card_id is not None
    card = db_session.get(SrsCard, note.card_id)
    assert card.kind == "error"
    assert card.ref_id == note.id


def test_mc_wrong_answer_creates_error_note(db_session):
    ex = _make_exercise(db_session, "mc", {"prompt_de": "?", "options": ["a", "b", "c", "d"]},
                         {"correct_index": 1, "explanation_de": "d", "explanation_en": "e"})
    result = grader.grade("mc", ex.answer_key, {"index": 0})
    note = errors.maybe_create_from_exercise_attempt(db_session, ex, {"index": 0}, result)
    assert note is not None
    assert note.wrong_de == "a"
    assert note.right_de == "b"
    assert note.note_de == "d"


def test_mc_correct_answer_creates_no_note(db_session):
    ex = _make_exercise(db_session, "mc", {"prompt_de": "?", "options": ["a", "b", "c", "d"]},
                         {"correct_index": 1, "explanation_de": "d", "explanation_en": "e"})
    result = grader.grade("mc", ex.answer_key, {"index": 1})
    note = errors.maybe_create_from_exercise_attempt(db_session, ex, {"index": 1}, result)
    assert note is None


def test_cloze_wrong_answer_creates_note_with_full_sentences(db_session):
    ex = _make_exercise(db_session, "cloze", {"text_de": "Ich ___ Fußball.", "choices": ["spiele", "spielst", "spielt"]},
                         {"correct_answer": "spiele", "explanation_de": "d", "explanation_en": "e"})
    result = grader.grade("cloze", ex.answer_key, {"answer": "spielt"})
    note = errors.maybe_create_from_exercise_attempt(db_session, ex, {"answer": "spielt"}, result)
    assert note.wrong_de == "Ich spielt Fußball."
    assert note.right_de == "Ich spiele Fußball."


def test_ordering_wrong_answer_creates_note(db_session):
    ex = _make_exercise(db_session, "ordering", {"tokens": ["b", "a"]}, {"correct_tokens": ["a", "b"]})
    result = grader.grade("ordering", ex.answer_key, {"order": ["b", "a"]})
    note = errors.maybe_create_from_exercise_attempt(db_session, ex, {"order": ["b", "a"]}, result)
    assert note.wrong_de == "b a"
    assert note.right_de == "a b"


def test_dialogue_gap_wrong_answer_creates_note(db_session):
    ex = _make_exercise(db_session, "dialogue_gap",
                         {"turns": [], "gap_turn_index": 0, "options": ["a", "b", "c", "d"]},
                         {"correct_index": 2, "correct_text_de": "c"})
    result = grader.grade("dialogue_gap", ex.answer_key, {"index": 0})
    note = errors.maybe_create_from_exercise_attempt(db_session, ex, {"index": 0}, result)
    assert note.wrong_de == "a"
    assert note.right_de == "c"


def test_matching_never_creates_error_note(db_session):
    ex = _make_exercise(db_session, "matching", {"prompt_de": "p", "left": ["a"], "right": ["1"]},
                         {"pairs": [{"left": "a", "right": "1"}]})
    result = grader.grade("matching", ex.answer_key, {"pairs": []})
    note = errors.maybe_create_from_exercise_attempt(db_session, ex, {"pairs": []}, result)
    assert note is None


def test_translation_en_de_wrong_creates_note(db_session):
    ex = _make_exercise(db_session, "translation",
                         {"direction": "en_de", "source_text": "I am learning.", "hint_de": ""},
                         {"accepted_answers": ["Ich lerne."]})
    result = grader.grade("translation", ex.answer_key, {"text": "Ich spiele."})
    note = errors.maybe_create_from_exercise_attempt(db_session, ex, {"text": "Ich spiele."}, result)
    assert note is not None
    assert note.wrong_de == "Ich spiele."
    assert note.right_de == "Ich lerne."


def test_translation_de_en_never_creates_note(db_session):
    # target language is English here — it doesn't belong in wrong_de/right_de
    ex = _make_exercise(db_session, "translation",
                         {"direction": "de_en", "source_text": "Ich lerne.", "hint_de": ""},
                         {"accepted_answers": ["I am learning."]})
    result = grader.grade("translation", ex.answer_key, {"text": "I play."})
    note = errors.maybe_create_from_exercise_attempt(db_session, ex, {"text": "I play."}, result)
    assert note is None


def test_close_call_does_not_create_a_note(db_session):
    # a "wrong" answer graded so close it's practically the same text shouldn't spawn noise
    ex = _make_exercise(db_session, "cloze", {"text_de": "Ich ___ Fußball.", "choices": ["spiele", "Spiele", "spielt"]},
                         {"correct_answer": "spiele", "explanation_de": "", "explanation_en": ""})
    result = grader.grade("cloze", ex.answer_key, {"answer": "Spiele"})  # only differs by capitalization
    assert result["correct"] is True  # grader normalizes this — sanity check the premise
    note = errors.maybe_create_from_exercise_attempt(db_session, ex, {"answer": "Spiele"}, result)
    assert note is None
