"""Auto-grading for the 6 exercise types, plus the exam engine's
objectively-gradable shapes (comprehension/matching/form — see
examgen.py's docstring for how the 15 blueprint `kind`s map to these).
LLM-graded rubric scoring for exam writing/speaking lives in
exam_grading.py instead, since it needs an LLM call and error-notebook
wiring that don't belong in this no-LLM module.
"""

import difflib
import re


def _normalize(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[.,!?;:\"'()]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def grade(type_: str, answer_key: dict, response: dict) -> dict:
    """Returns {score: 0..1, correct: bool, detail: {...}}. Never raises on
    malformed client input — treats it as simply wrong.
    """
    try:
        if type_ == "mc":
            return _grade_choice(answer_key["correct_index"], response.get("index"),
                                  extra={"explanation_de": answer_key["explanation_de"],
                                         "explanation_en": answer_key["explanation_en"]})

        if type_ == "cloze":
            return _grade_text(answer_key["correct_answer"], response.get("answer", ""),
                                extra={"explanation_de": answer_key["explanation_de"],
                                       "explanation_en": answer_key["explanation_en"]})

        if type_ == "ordering":
            correct = answer_key["correct_tokens"]
            submitted = response.get("order", [])
            score = 1.0 if submitted == correct else 0.0
            return {"score": score, "correct": score == 1.0,
                    "detail": {"correct_tokens": correct}}

        if type_ == "matching":
            pairs = {(p["left"], p["right"]) for p in answer_key["pairs"]}
            submitted = response.get("pairs", [])
            submitted_pairs = {(p.get("left"), p.get("right")) for p in submitted}
            n_correct = len(pairs & submitted_pairs)
            score = n_correct / len(pairs) if pairs else 0.0
            return {"score": score, "correct": score == 1.0,
                    "detail": {"n_correct": n_correct, "n_total": len(pairs), "correct_pairs": answer_key["pairs"]}}

        if type_ == "translation":
            accepted = answer_key["accepted_answers"]
            submitted = response.get("text", "")
            return _grade_text_multi(accepted, submitted)

        if type_ == "dialogue_gap":
            return _grade_choice(answer_key["correct_index"], response.get("index"),
                                  extra={"correct_text_de": answer_key["correct_text_de"]})

        return {"score": 0.0, "correct": False, "detail": {"error": f"unknown type {type_}"}}
    except Exception as e:  # noqa: BLE001 — malformed response is a grading outcome, not a crash
        return {"score": 0.0, "correct": False, "detail": {"error": str(e)}}


def _grade_choice(correct_index: int, submitted_index, extra: dict) -> dict:
    correct = submitted_index == correct_index
    return {"score": 1.0 if correct else 0.0, "correct": correct,
            "detail": {"correct_index": correct_index, **extra}}


def _grade_text(correct: str, submitted: str, extra: dict) -> dict:
    ratio = _similarity(correct, submitted)
    is_correct = ratio >= 0.97  # allow trivial whitespace/punctuation drift only
    return {"score": 1.0 if is_correct else round(ratio, 2), "correct": is_correct,
            "detail": {"correct_answer": correct, **extra}}


def _grade_text_multi(accepted: list[str], submitted: str) -> dict:
    best = max((_similarity(a, submitted) for a in accepted), default=0.0)
    is_correct = best >= 0.9  # translations tolerate more phrasing variance than a single word
    close = 0.75 <= best < 0.9
    return {"score": 1.0 if is_correct else round(best, 2), "correct": is_correct,
            "detail": {"accepted_answers": accepted, "close": close}}


def grade_comprehension(answer_key: dict, response: dict) -> dict:
    """response: {"indices": [int, ...]}, one per question, same order as
    the payload's questions list."""
    correct = answer_key["correct_indices"]
    submitted = response.get("indices", [])
    n_correct = sum(1 for i, c in enumerate(correct) if i < len(submitted) and submitted[i] == c)
    score = n_correct / len(correct) if correct else 0.0
    return {"score": score, "detail": {"n_correct": n_correct, "n_total": len(correct), "correct_indices": correct}}


def grade_matching(answer_key: dict, response: dict) -> dict:
    """response: {"options": [str, ...]}, one per situation, same order."""
    correct = answer_key["correct_options"]
    submitted = response.get("options", [])
    n_correct = sum(1 for i, c in enumerate(correct) if i < len(submitted) and submitted[i] == c)
    score = n_correct / len(correct) if correct else 0.0
    return {"score": score, "detail": {"n_correct": n_correct, "n_total": len(correct), "correct_options": correct}}


def grade_form(answer_key: dict, response: dict) -> dict:
    """response: {"answers": [str, ...]}, one per blank. Form answers are
    short factual fills (names, dates, numbers) so this is more lenient
    than cloze's near-exact match."""
    expected = answer_key["expected_answers"]
    submitted = response.get("answers", [])
    per_blank = []
    for i, exp in enumerate(expected):
        sub = submitted[i] if i < len(submitted) else ""
        ratio = _similarity(exp, sub) if sub.strip() else 0.0
        per_blank.append(1.0 if ratio >= 0.6 else round(ratio, 2))
    score = sum(per_blank) / len(per_blank) if per_blank else 0.0
    return {"score": score, "detail": {"per_blank": per_blank, "expected_answers": expected}}
