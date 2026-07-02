"""Goethe mock exam content generation.

The blueprints (data/exam_blueprints/*.json) use 15 distinct `kind` values
across their parts (mc3, truefalse, match2, match, yesno, mixed_tf_mc,
speaker_match, form, text, monolog, qa_cards, requests, planning,
presentation, feedback_qa) — but they reduce to 4 underlying interaction
shapes, so 4 schemas cover all of them instead of 15 bespoke ones:

  comprehension — a passage/dialogue + questions, each with options and one
    correct index. Covers mc3/truefalse/yesno/mixed_tf_mc (a truefalse
    question is just a 2-option comprehension question; mc3 is 3-option;
    mixed_tf_mc parts freely mix both within one list of questions).
  matching — situations matched against a shared option pool. Covers
    match2/match/speaker_match (a speaker_match's "options" are speaker
    names instead of lettered ads, but the shape is identical).
  writing — a scenario + content points to address. Covers form (blanks,
    graded by similarity like a cloze) and text (free prose, LLM-graded).
  speaking — instructions + cue prompts, conducted live over the existing
    voice pipeline (a real Conversation, not a bespoke WS endpoint — see
    services/examflow.py) and graded afterward from the transcript + the
    same GOP pronunciation scoring conversations already get.

Each part's payload (what the learner sees) and answer_key (what grading
needs) are split before storage, same convention as exercise_types.py.
"""

from pydantic import BaseModel, Field

from . import content, llm
from .concurrency import gpu_lock

_MATCH_KINDS = {"match2", "match", "speaker_match"}
_WRITING_KINDS = {"form", "text"}
_SPEAKING_KINDS = {"monolog", "qa_cards", "requests", "planning", "presentation", "feedback_qa"}


def shape_for(kind: str) -> str:
    if kind in _MATCH_KINDS:
        return "matching"
    if kind in _WRITING_KINDS:
        return "writing"
    if kind in _SPEAKING_KINDS:
        return "speaking"
    return "comprehension"  # mc3, truefalse, yesno, mixed_tf_mc


class ComprehensionQuestion(BaseModel):
    prompt_de: str = Field(description="Die Frage oder Aussage an den Lernenden")
    options: list[str] = Field(min_length=2, max_length=3, description="2 Optionen für richtig/falsch, 3 für Multiple-Choice")
    correct_index: int


class ComprehensionPart(BaseModel):
    passage_de: str = Field(description="Der Lese- oder Hörtext (Dialog, Durchsage, Artikel, je nach Vorgabe)")
    questions: list[ComprehensionQuestion]


class MatchSituation(BaseModel):
    situation_de: str
    correct_option: str = Field(description="Der Buchstabe oder Name aus der Optionsliste, der passt")


class MatchingPart(BaseModel):
    options: list[str] = Field(description="Die Auswahlliste (z. B. 'a: ...', 'b: ...' oder Sprechernamen)")
    situations: list[MatchSituation]


class WritingBlank(BaseModel):
    label_de: str = Field(description="Kurzes Label für dieses Formularfeld, z. B. 'Name' oder 'Datum'")
    expected_answer: str = Field(description="Eine plausible richtige Antwort für dieses Feld")


class WritingPart(BaseModel):
    scenario_de: str = Field(description="Die Situationsbeschreibung für die Schreibaufgabe")
    # No defaults: Field(default_factory=list) makes these OPTIONAL in the
    # generated json_schema, and under strict grammar-constrained decoding
    # a model will happily skip an optional field entirely (confirmed
    # empirically — both came back consistently empty). Required forces the
    # model to emit *something*, even an explicit empty list.
    content_points_de: list[str] = Field(description="Bei einer Textaufgabe: die Inhaltspunkte, die die Antwort ansprechen soll. Bei einem Formular: leere Liste []")
    blanks: list[WritingBlank] = Field(description="Bei einem Formular: die auszufüllenden Felder. Bei einer Textaufgabe: leere Liste []")


class SpeakingPart(BaseModel):
    instructions_de: str = Field(description="Kurze Anweisung an den Lernenden, was er tun/sagen soll")
    prompts_de: list[str] = Field(description="Konkrete Stichwortkarten/Fragen/Themen für diesen Teil")


_SCHEMA_FOR_SHAPE = {
    "comprehension": ComprehensionPart, "matching": MatchingPart,
    "writing": WritingPart, "speaking": SpeakingPart,
}


def _system_prompt(level: str) -> str:
    return (
        f"Du erstellst Inhalte für eine offizielle Goethe-Prüfungssimulation, Niveau {level} (GER). "
        "Die Inhalte müssen zum Prüfungsformat passen: realistisch, alltagsnah, ohne Fangfragen. "
        "Antworte NUR mit den angeforderten Prüfungsinhalten, keine Erklärungen oder Meta-Kommentare."
    )


_WRITING_WORKED_EXAMPLE = {
    "form": (
        '{"scenario_de": "Sie melden sich fuer einen Deutschkurs an.", "content_points_de": [], '
        '"blanks": [{"label_de": "Name", "expected_answer": "Anna Keller"}, '
        '{"label_de": "Geburtsdatum", "expected_answer": "03.07.1995"}]} '
        "- content_points_de ist IMMER leer [] bei einem Formular; blanks enthaelt die echten Felder."
    ),
    "text": (
        '{"scenario_de": "Schreiben Sie eine Nachricht an einen Freund.", '
        '"content_points_de": ["Grund fuer die Nachricht nennen", "Vorschlag machen", "Nach seiner Meinung fragen"], '
        '"blanks": []} '
        "- blanks ist IMMER leer [] bei einer Textaufgabe; content_points_de enthaelt die echten Punkte."
    ),
}


def _user_prompt(shape: str, level: str, spec: str, items: int, kind: str = "") -> str:
    base = f'Aufgabentyp: "{spec}" Anzahl Elemente: {items}. Niveau: {level}.'
    if shape == "comprehension":
        return base + (
            " Erstelle einen passenden Text/Dialog (passage_de) und genau "
            f"{items} Fragen dazu. Bei richtig/falsch-Fragen: options=[\"richtig\", \"falsch\"]. "
            "Bei Multiple-Choice: genau 3 plausible Optionen, nur eine richtig."
        )
    if shape == "matching":
        return base + (
            f" Erstelle {items} kurze Situationen und eine Optionsliste (mit einer Distraktor-Option mehr als "
            "Situationen, falls das Format das vorsieht). Jede Situation bekommt genau eine passende Option."
        )
    if shape == "writing":
        example = _WRITING_WORKED_EXAMPLE.get(kind, _WRITING_WORKED_EXAMPLE["text"])
        return base + (
            " Erstelle eine realistische Situationsbeschreibung. WICHTIG: Fülle IMMER BEIDE Felder "
            "content_points_de und blanks — das jeweils nicht passende Feld bekommt eine leere Liste [], "
            "niemals beide leer lassen. Beispiel (Inhalt anpassen, Aufbau beibehalten): " + example
        )
    return base + (  # speaking
        " Erstelle eine kurze Anweisung an den Lernenden und die konkreten Stichwortkarten/Fragen/Themen "
        "für diesen Prüfungsteil."
    )


async def generate_part(level: str, kind: str, spec: str, items: int) -> tuple[str, BaseModel]:
    shape = shape_for(kind)
    schema_cls = _SCHEMA_FOR_SHAPE[shape]
    system = _system_prompt(level)
    user = _user_prompt(shape, level, spec, items, kind)
    async with gpu_lock:
        item = await llm.generate_structured("tutor", system, user, schema_cls, f"exam_{shape}")
    return shape, item


def split_part(shape: str, kind: str, item: BaseModel) -> tuple[dict, dict]:
    """Returns (payload, answer_key)."""
    if shape == "comprehension":
        item: ComprehensionPart
        return (
            {"kind": kind, "passage_de": item.passage_de,
             "questions": [{"prompt_de": q.prompt_de, "options": q.options} for q in item.questions]},
            {"correct_indices": [q.correct_index for q in item.questions]},
        )
    if shape == "matching":
        item: MatchingPart
        return (
            {"kind": kind, "options": item.options,
             "situations": [{"situation_de": s.situation_de} for s in item.situations]},
            {"correct_options": [s.correct_option for s in item.situations]},
        )
    if shape == "writing":
        item: WritingPart
        return (
            {"kind": kind, "scenario_de": item.scenario_de, "content_points_de": item.content_points_de,
             "blank_labels": [b.label_de for b in item.blanks]},
            {"expected_answers": [b.expected_answer for b in item.blanks],
             "content_points_de": item.content_points_de},
        )
    item: SpeakingPart  # speaking
    return (
        {"kind": kind, "instructions_de": item.instructions_de, "prompts_de": item.prompts_de},
        {},
    )


async def generate_module(level: str, module_name: str) -> list[dict]:
    """Returns one dict per blueprint part: {teil, kind, points, time_min,
    payload, answer_key}, ready to become MockSection rows.
    """
    blueprint = content.exam_blueprint(level)
    module = blueprint["modules"][module_name]
    sections = []
    for part in module["parts"]:
        shape, item = await generate_part(level, part["kind"], part["spec"], part["items"])
        payload, answer_key = split_part(shape, part["kind"], item)
        payload["teil"] = answer_key["teil"] = part["teil"]
        payload["spec_de"] = part["spec"]
        if "plays" in part:
            payload["plays"] = part["plays"]
        if "words" in part:
            payload["words"] = part["words"]
        sections.append({
            "teil": part["teil"], "kind": part["kind"], "shape": shape,
            "points": part.get("points"), "items": part["items"],
            "payload": payload, "answer_key": answer_key,
        })
    return sections
