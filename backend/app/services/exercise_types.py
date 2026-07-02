"""The 6 exercise types: generation schemas + prompts, and the payload/answer_key split.

Each generator produces one pydantic object (the full item, including the
answer). `split()` divides it into what the learner sees (`payload`) and what
grading needs (`answer_key`) so the answer never reaches the client until
after grading.
"""

import random
from typing import Literal

from pydantic import BaseModel, Field

EXERCISE_TYPES = ["mc", "cloze", "ordering", "matching", "translation", "dialogue_gap"]


_PROMPT_DE_DESC = (
    "Kurze Aufgabenstellung oder Frage AN DEN LERNER (z. B. 'Was passt hier?', "
    "'Wie heißt die richtige Form?'). NICHT die Erstellungsanweisung wiederholen "
    "oder erklären, was du gerade tust."
)


class GeneratedMC(BaseModel):
    prompt_de: str = Field(description=_PROMPT_DE_DESC)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int
    explanation_de: str
    explanation_en: str


class GeneratedCloze(BaseModel):
    text_de: str = Field(description="Sentence with exactly one blank shown as ___")
    correct_answer: str
    distractors: list[str] = Field(min_length=2, max_length=3)
    explanation_de: str
    explanation_en: str


class GeneratedOrdering(BaseModel):
    correct_sentence: str
    translation_en: str


class MatchPair(BaseModel):
    left: str
    right: str


class GeneratedMatching(BaseModel):
    prompt_de: str = Field(description=_PROMPT_DE_DESC)
    pairs: list[MatchPair] = Field(min_length=4, max_length=4)


class GeneratedTranslation(BaseModel):
    direction: Literal["de_en", "en_de"]
    source_text: str
    accepted_answers: list[str] = Field(min_length=1, max_length=3)
    hint_de: str


class DialogueTurn(BaseModel):
    speaker: str
    text_de: str


class GeneratedDialogueGap(BaseModel):
    turns: list[DialogueTurn] = Field(min_length=4, max_length=4)
    gap_turn_index: int
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int


SCHEMAS: dict[str, type[BaseModel]] = {
    "mc": GeneratedMC,
    "cloze": GeneratedCloze,
    "ordering": GeneratedOrdering,
    "matching": GeneratedMatching,
    "translation": GeneratedTranslation,
    "dialogue_gap": GeneratedDialogueGap,
}


def system_prompt(level: str) -> str:
    return (
        "Du bist ein Deutschlehrer, der Übungen für Deutschlernende auf Niveau "
        f"{level} (GER) erstellt. Verwende nur Wortschatz und Grammatik, die auf diesem "
        "Niveau oder darunter angemessen sind. Antworte ausschließlich mit dem geforderten JSON."
    )


# Concrete worked examples for the free-text fields ("prompt_de") where models
# reliably ignore JSON-schema `description` hints under grammar-constrained
# decoding and instead echo the instruction text verbatim. A full example
# object is a much stronger signal than an abstract rule for smaller/local
# models — confirmed empirically against LM Studio + Qwen3.5.
_WORKED_EXAMPLE = {
    "mc": (
        '{"prompt_de": "Welches Wort passt?", "options": ["bin", "bist", "ist", "sind"], '
        '"correct_index": 0, "explanation_de": "...", "explanation_en": "..."}'
    ),
    "matching": (
        '{"prompt_de": "Ordne die Wörter den passenden Übersetzungen zu.", '
        '"pairs": [{"left": "Hund", "right": "dog"}, {"left": "Katze", "right": "cat"}, ...]}'
    ),
    "dialogue_gap": (
        '{"turns": [{"speaker": "Anna", "text_de": "Hallo! Wie heißt du?"}, '
        '{"speaker": "Tom", "text_de": "Ich heiße Tom. Und du?"}, '
        '{"speaker": "Anna", "text_de": "Ich heiße Lisa. Woher kommst du?"}, '
        '{"speaker": "Tom", "text_de": "Ich komme aus Berlin."}], '
        '"gap_turn_index": 1, "options": ["Ich heiße Tom. Und du?", "Das Wetter ist schön.", '
        '"Ich habe Hunger.", "Tschüss!"], "correct_index": 0} - "speaker" ist ein kurzer '
        "Name (wie im Beispiel), text_de ist die tatsächliche Gesprächszeile, keine Anweisung."
    ),
}


def user_prompt(type_: str, level: str, topic_title: str | None, vocab: list[str]) -> str:
    focus = f" zum Grammatikthema \"{topic_title}\"" if topic_title else ""
    words = f" Verwende wenn möglich diese Wörter: {', '.join(vocab)}." if vocab else ""
    kind_de = {
        "mc": "eine Multiple-Choice-Aufgabe (4 Optionen, genau eine richtig)",
        "cloze": "eine Lückentext-Aufgabe (ein Satz mit einer Lücke ___, plus 2-3 falsche Alternativen)",
        "ordering": "einen Satz zum Umordnen (ein natürlicher, vollständiger deutscher Satz)",
        "matching": "eine Zuordnungsaufgabe mit 4 Paaren (z. B. Wort - Übersetzung, oder Frage - Antwort)",
        "translation": "eine Übersetzungsaufgabe (Deutsch->Englisch oder Englisch->Deutsch)",
        "dialogue_gap": "einen kurzen Dialog mit 4 Sprechbeiträgen, bei dem einer fehlt (4 Antwortoptionen)",
    }[type_]
    prompt = f"Erstelle {kind_de}{focus}, passend für Niveau {level}.{words}"
    if type_ in _WORKED_EXAMPLE:
        prompt += (
            '\n\nWICHTIG: "prompt_de" ist eine kurze Aufgabenstellung AN DEN LERNER, NICHT '
            f"dieser Auftragstext hier. Beispiel (Inhalt anpassen, Aufbau beibehalten): {_WORKED_EXAMPLE[type_]}"
        )
    return prompt


def split(type_: str, item: BaseModel) -> tuple[dict, dict]:
    """Returns (payload, answer_key)."""
    if type_ == "mc":
        item: GeneratedMC
        return (
            {"prompt_de": item.prompt_de, "options": item.options},
            {"correct_index": item.correct_index, "explanation_de": item.explanation_de,
             "explanation_en": item.explanation_en},
        )

    if type_ == "cloze":
        item: GeneratedCloze
        choices = [item.correct_answer, *item.distractors]
        random.shuffle(choices)
        return (
            {"text_de": item.text_de, "choices": choices},
            {"correct_answer": item.correct_answer, "explanation_de": item.explanation_de,
             "explanation_en": item.explanation_en},
        )

    if type_ == "ordering":
        item: GeneratedOrdering
        words = item.correct_sentence.split()
        shuffled = words[:]
        tries = 0
        while len(words) > 1 and shuffled == words and tries < 5:
            random.shuffle(shuffled)
            tries += 1
        return (
            {"tokens": shuffled, "translation_en": item.translation_en},
            {"correct_tokens": words},
        )

    if type_ == "matching":
        item: GeneratedMatching
        left = [p.left for p in item.pairs]
        right = [p.right for p in item.pairs]
        random.shuffle(right)
        return (
            {"prompt_de": item.prompt_de, "left": left, "right": right},
            {"pairs": [{"left": p.left, "right": p.right} for p in item.pairs]},
        )

    if type_ == "translation":
        item: GeneratedTranslation
        return (
            {"direction": item.direction, "source_text": item.source_text, "hint_de": item.hint_de},
            {"accepted_answers": item.accepted_answers},
        )

    if type_ == "dialogue_gap":
        item: GeneratedDialogueGap
        turns = [
            {"speaker": t.speaker, "text_de": None if i == item.gap_turn_index else t.text_de}
            for i, t in enumerate(item.turns)
        ]
        return (
            {"turns": turns, "gap_turn_index": item.gap_turn_index, "options": item.options},
            {"correct_index": item.correct_index,
             "correct_text_de": item.turns[item.gap_turn_index].text_de},
        )

    raise ValueError(f"unknown exercise type: {type_}")


_ECHO_MARKERS = ("erstelle", "aufgabenstellung", "niveau", "grammatikthema", "json", "auftragstext")


def _looks_like_echoed_instruction(prompt_de: str) -> bool:
    """Catches the case where the model pastes the generation instruction
    into a learner-facing field instead of writing an actual prompt — a
    concrete, observed failure mode, not a hypothetical one."""
    if len(prompt_de) > 120:
        return True
    lowered = prompt_de.lower()
    return any(marker in lowered for marker in _ECHO_MARKERS)


def structurally_valid(type_: str, item: BaseModel) -> bool:
    """Light sanity checks beyond pydantic's schema validation."""
    if type_ == "mc":
        return (0 <= item.correct_index < len(item.options)
                and not _looks_like_echoed_instruction(item.prompt_de))
    if type_ == "cloze":
        return "___" in item.text_de and item.correct_answer not in item.distractors
    if type_ == "ordering":
        return len(item.correct_sentence.split()) >= 3
    if type_ == "matching":
        lefts = {p.left for p in item.pairs}
        rights = {p.right for p in item.pairs}
        return (len(lefts) == len(item.pairs) and len(rights) == len(item.pairs)
                and not _looks_like_echoed_instruction(item.prompt_de))
    if type_ == "translation":
        return len(item.source_text.strip()) > 0 and all(a.strip() for a in item.accepted_answers)
    if type_ == "dialogue_gap":
        return (
            0 <= item.gap_turn_index < len(item.turns)
            and 0 <= item.correct_index < len(item.options)
            and all(len(t.speaker) <= 20 and not _looks_like_echoed_instruction(t.text_de)
                    for t in item.turns)
        )
    return False
