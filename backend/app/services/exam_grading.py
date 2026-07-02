"""LLM-graded exam shapes: writing (free text against content points) and
speaking (a live conversation transcript). Kept separate from grader.py
since both need an LLM call and, for writing, error-notebook wiring —
grader.py stays purely deterministic/no-LLM.

Writing is graded twice at low temperature (Goethe's real criteria:
content coverage, "Kommunikative Gestaltung" / task fulfillment, and
"Formale Richtigkeit" / grammar-vocab correctness) and averaged; a >15%
split between the two passes is flagged rather than silently averaged
away, since that usually means the task itself was ambiguous or the
writing sits right on a rubric boundary.
"""

import logging
import statistics

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import errors, llm
from .concurrency import gpu_lock

logger = logging.getLogger(__name__)

WRITING_GRADE_TEMPERATURE = 0.2
DIVERGENCE_FLAG_PCT = 0.15


class WritingErrorItem(BaseModel):
    wrong_de: str
    right_de: str
    note_de: str = Field(description="Kurze Erklärung des Fehlers auf Deutsch, 1 Satz")


class WritingGrade(BaseModel):
    score_pct: int = Field(ge=0, le=100, description="Gesamtpunktzahl in Prozent des Maximums")
    content_covered: bool = Field(description="Wurden alle geforderten Inhaltspunkte angesprochen?")
    corrected_text_de: str = Field(description="Der Text, mit korrigierten Fehlern")
    feedback_de: str = Field(description="Kurzes, konstruktives Feedback auf Deutsch, 2-3 Sätze")
    errors: list[WritingErrorItem] = Field(max_length=5, description="Bis zu 5 wichtigste Fehler mit Korrektur")


def _writing_system(level: str) -> str:
    return (
        f"Du bewertest eine Schreibaufgabe einer Goethe-Prüfung, Niveau {level} (GER), nach den offiziellen "
        "Kriterien: Inhaltliche Angemessenheit (alle Punkte angesprochen?), Kommunikative Gestaltung "
        "(Textsorte, Register, Aufbau) und Formale Richtigkeit (Grammatik, Wortschatz, Rechtschreibung). "
        "Sei fair aber genau — das ist Niveau {level}, keine Muttersprachler-Prüfung. "
        "Antworte NUR mit der Bewertung im geforderten Format."
    )


def _writing_user(scenario_de: str, content_points: list[str], target_words: int, submitted_text: str) -> str:
    points = "\n".join(f"- {p}" for p in content_points) if content_points else "(keine spezifischen Punkte)"
    return (
        f"Aufgabe: {scenario_de}\nGeforderte Inhaltspunkte:\n{points}\nZielwortzahl: ~{target_words}\n\n"
        f"Eingereichter Text:\n{submitted_text}"
    )


async def _grade_writing_once(level: str, scenario_de: str, content_points: list[str],
                               target_words: int, submitted_text: str) -> WritingGrade:
    system = _writing_system(level)
    user = _writing_user(scenario_de, content_points, target_words, submitted_text)
    async with gpu_lock:
        return await llm.generate_structured(
            "tutor", system, user, WritingGrade, "exam_writing_grade",
            temperature=WRITING_GRADE_TEMPERATURE,
        )


async def grade_writing(db: Session, level: str, scenario_de: str, content_points: list[str],
                         target_words: int, submitted_text: str) -> dict:
    """Double-graded and averaged; each found error becomes an error-notebook
    entry (source="exam") so it resurfaces in SRS review, same pipeline P4's
    exercise-attempt errors use.
    """
    if not submitted_text.strip():
        return {"score": 0.0, "detail": {"empty": True}}

    g1 = await _grade_writing_once(level, scenario_de, content_points, target_words, submitted_text)
    g2 = await _grade_writing_once(level, scenario_de, content_points, target_words, submitted_text)

    scores = [g1.score_pct, g2.score_pct]
    avg = statistics.mean(scores) / 100
    divergence = abs(g1.score_pct - g2.score_pct) / 100
    flagged = divergence > DIVERGENCE_FLAG_PCT
    if flagged:
        logger.info("writing grade divergence %.0f%% (scores=%s) for: %.60s", divergence * 100, scores, scenario_de)

    chosen = g1 if g1.score_pct <= g2.score_pct else g2  # keep the more conservative feedback/corrections
    for err in chosen.errors:
        if err.wrong_de.strip() and err.right_de.strip() and err.wrong_de.strip() != err.right_de.strip():
            errors.create_error_note(
                db, kind="grammar", source="exam", wrong_de=err.wrong_de, right_de=err.right_de,
                note_de=err.note_de,
            )

    return {
        "score": avg,
        "detail": {
            "scores_pct": scores, "divergence_flagged": flagged,
            "content_covered": chosen.content_covered, "corrected_text_de": chosen.corrected_text_de,
            "feedback_de": chosen.feedback_de, "errors": [e.model_dump() for e in chosen.errors],
        },
    }


class SpeakingGrade(BaseModel):
    score_pct: int = Field(ge=0, le=100, description="Punktzahl in Prozent für Aufgabenerfüllung + Sprache")
    task_fulfilled: bool
    feedback_de: str = Field(description="Kurzes, konstruktives Feedback auf Deutsch, 2-3 Sätze")


def _speaking_system(level: str) -> str:
    return (
        f"Du bewertest den Sprechteil einer Goethe-Prüfung, Niveau {level} (GER), anhand eines Transkripts. "
        "Kriterien: Aufgabenerfüllung (wurde die Anweisung umgesetzt?), Interaktionsfähigkeit, "
        "Wortschatz- und Strukturrepertoire. Aussprache wird separat aus echten Audio-Messungen bewertet, "
        "NICHT von dir — ignoriere Tippfehler oder ungewöhnliche Schreibweisen im Transkript. "
        "Antworte NUR mit der Bewertung im geforderten Format."
    )


async def grade_speaking(instructions_de: str, prompts_de: list[str], transcript: list[dict], level: str) -> dict:
    """transcript: [{"role": "user"|"assistant", "text": str}, ...]."""
    lines = "\n".join(f"{t['role']}: {t['text']}" for t in transcript if t.get("text"))
    if not lines.strip():
        return {"score": 0.0, "detail": {"empty": True}}

    system = _speaking_system(level)
    user = (
        f"Anweisung an den Lernenden: {instructions_de}\nStichworte: {', '.join(prompts_de)}\n\n"
        f"Transkript (user = Lernender):\n{lines}"
    )
    async with gpu_lock:
        grade = await llm.generate_structured("tutor", system, user, SpeakingGrade, "exam_speaking_grade")
    return {
        "score": grade.score_pct / 100,
        "detail": {"task_fulfilled": grade.task_fulfilled, "feedback_de": grade.feedback_de},
    }
