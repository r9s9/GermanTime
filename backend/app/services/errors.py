"""Turns a wrong exercise attempt into an error-notebook entry + linked SRS
card. P8 (exam writing feedback) will call `create_error_note` too, reusing
this same review pipeline instead of building a parallel one.
"""

from sqlalchemy.orm import Session

from . import srs
from ..models import Exercise, ErrorNote

# matching is skipped: a multi-pair result doesn't reduce to one wrong/right
# sentence. translation is only captured de_en->... no: only en_de (target
# German) - a de_en attempt's "wrong" text is English, which doesn't belong
# in wrong_de/right_de.
EXERCISE_KIND = {"mc": "grammar", "cloze": "grammar", "ordering": "grammar", "dialogue_gap": "grammar",
                  "translation": "vocab"}


def create_error_note(db: Session, kind: str, source: str, wrong_de: str, right_de: str,
                       topic_id: str | None = None, note_de: str = "", note_en: str = "") -> ErrorNote:
    note = ErrorNote(kind=kind, source=source, wrong_de=wrong_de, right_de=right_de,
                      topic_id=topic_id, note_de=note_de, note_en=note_en)
    db.add(note)
    db.commit()
    db.refresh(note)

    card = srs.create_error_card(db, note.id)
    note.card_id = card.id
    db.commit()
    return note


def maybe_create_from_exercise_attempt(
    db: Session, exercise: Exercise, response: dict, result: dict,
) -> ErrorNote | None:
    if result["correct"] or exercise.type not in EXERCISE_KIND:
        return None

    payload, answer_key, detail = exercise.payload, exercise.answer_key, result["detail"]
    wrong_de = right_de = None

    if exercise.type == "mc":
        idx = response.get("index")
        options = payload.get("options", [])
        if isinstance(idx, int) and 0 <= idx < len(options):
            wrong_de = options[idx]
        ci = answer_key.get("correct_index")
        if isinstance(ci, int) and 0 <= ci < len(options):
            right_de = options[ci]

    elif exercise.type == "cloze":
        text = payload.get("text_de", "")
        wrong_de = text.replace("___", response.get("answer", "___"))
        right_de = text.replace("___", answer_key.get("correct_answer", "___"))

    elif exercise.type == "ordering":
        wrong_de = " ".join(response.get("order", []))
        right_de = " ".join(answer_key.get("correct_tokens", []))

    elif exercise.type == "dialogue_gap":
        idx = response.get("index")
        options = payload.get("options", [])
        if isinstance(idx, int) and 0 <= idx < len(options):
            wrong_de = options[idx]
        right_de = answer_key.get("correct_text_de")

    elif exercise.type == "translation" and payload.get("direction") == "en_de":
        wrong_de = response.get("text", "")
        accepted = answer_key.get("accepted_answers", [])
        right_de = accepted[0] if accepted else None

    if not wrong_de or not right_de or wrong_de.strip() == right_de.strip():
        return None

    return create_error_note(
        db, kind=EXERCISE_KIND[exercise.type], source="exercise",
        wrong_de=wrong_de, right_de=right_de, topic_id=exercise.topic_id,
        note_de=detail.get("explanation_de", ""), note_en=detail.get("explanation_en", ""),
    )
