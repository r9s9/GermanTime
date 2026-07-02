"""Pure grading-logic tests — no DB, no LLM."""

from app.services import grader


def test_mc_grading():
    key = {"correct_index": 2, "explanation_de": "x", "explanation_en": "y"}
    assert grader.grade("mc", key, {"index": 2})["correct"] is True
    assert grader.grade("mc", key, {"index": 0})["correct"] is False


def test_cloze_grading_exact_and_normalized():
    key = {"correct_answer": "spielt", "explanation_de": "", "explanation_en": ""}
    assert grader.grade("cloze", key, {"answer": "spielt"})["correct"] is True
    assert grader.grade("cloze", key, {"answer": "Spielt."})["correct"] is True
    assert grader.grade("cloze", key, {"answer": "isst"})["correct"] is False


def test_ordering_grading_exact_sequence():
    key = {"correct_tokens": ["Ich", "spiele", "Fußball."]}
    assert grader.grade("ordering", key, {"order": ["Ich", "spiele", "Fußball."]})["correct"] is True
    assert grader.grade("ordering", key, {"order": ["Fußball.", "Ich", "spiele"]})["correct"] is False


def test_matching_grading_partial_credit():
    key = {"pairs": [{"left": "Hund", "right": "dog"}, {"left": "Katze", "right": "cat"}]}
    result = grader.grade("matching", key, {
        "pairs": [{"left": "Hund", "right": "dog"}, {"left": "Katze", "right": "fish"}]
    })
    assert result["score"] == 0.5
    assert result["correct"] is False


def test_translation_grading_tolerant_of_trivial_variation():
    key = {"accepted_answers": ["I am learning German."]}
    result = grader.grade("translation", key, {"text": "I am learning German"})  # no trailing period
    assert result["correct"] is True


def test_translation_grading_rejects_wrong_meaning():
    key = {"accepted_answers": ["I am learning German."]}
    result = grader.grade("translation", key, {"text": "I like pizza."})
    assert result["correct"] is False


def test_dialogue_gap_grading():
    key = {"correct_index": 1, "correct_text_de": "Guten Tag!"}
    assert grader.grade("dialogue_gap", key, {"index": 1})["correct"] is True
    assert grader.grade("dialogue_gap", key, {"index": 0})["correct"] is False


def test_grading_never_crashes_on_malformed_response():
    assert grader.grade("mc", {"correct_index": 0, "explanation_de": "", "explanation_en": ""}, {})["correct"] is False
    assert grader.grade("matching", {"pairs": []}, {"pairs": "not-a-list"})["correct"] is False
    assert grader.grade("ordering", {"correct_tokens": ["a"]}, {})["correct"] is False
    assert grader.grade("unknown_type", {}, {})["correct"] is False
