"""Builds the conversation system prompt: persona/scenario framing,
level-appropriate scaffolding, and weak vocab/phoneme reinforcement hints.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import content
from ..models import PhonemeStat, SrsCard, VocabItem

_LEVEL_GUIDANCE = {
    "Pre-A1": "Nur die einfachsten Wörter (ich, du, ja, nein, Zahlen, Farben). Ein Wort oder ein sehr kurzer Satz (max. 4 Wörter). Nur Präsens.",
    "A1.1": "Sehr einfache, kurze Sätze (max. 6 Wörter). Nur Präsens. Häufige Alltagswörter.",
    "A1.2": "Kurze, einfache Sätze (max. 8 Wörter). Präsens, einfaches Perfekt möglich. Alltagswortschatz.",
    "A2.1": "Ein bis zwei einfache Sätze. Präsens und Perfekt. Etwas mehr Wortschatz, noch keine komplexen Nebensätze.",
    "A2.2": "Ein bis zwei Sätze, natürlicher Sprachfluss. Einfache Nebensätze mit weil/dass/wenn sind ok.",
    "B1.1": "Zwei bis drei Sätze, natürliches Tempo. Nebensätze, Perfekt und Präteritum gemischt.",
    "B1.2": "Zwei bis drei Sätze, natürlich und variiert. Komplexere Strukturen sind ok.",
    "B1.2+": "Sprich natürlich wie mit einem fortgeschrittenen Lernenden. Variierte Sätze und Strukturen.",
}


def weak_vocab_hint(db: Session, n: int = 4) -> str:
    cards = db.scalars(
        select(SrsCard).where(SrsCard.kind == "vocab", SrsCard.lapses > 0)
        .order_by(SrsCard.lapses.desc()).limit(n)
    ).all()
    words = []
    for c in cards:
        item = db.get(VocabItem, int(c.ref_id))
        if item:
            words.append(item.lemma)
    if not words:
        return ""
    return f" Baue, wenn es natürlich passt, diese Wörter ins Gespräch ein: {', '.join(words)}."


def weak_phoneme_hint(db: Session, n: int = 2) -> str:
    """Empty until P7 populates phoneme_stats — this naturally starts
    producing hints once that table has data, no code change needed here."""
    stats = db.scalars(
        select(PhonemeStat).where(PhonemeStat.n >= 5, PhonemeStat.ema < 70)
        .order_by(PhonemeStat.ema).limit(n)
    ).all()
    if not stats:
        return ""
    sounds = ", ".join(s.phoneme for s in stats)
    return f" Verwende gelegentlich Wörter mit den Lauten [{sounds}], damit der Lernende sie üben kann."


def build_system_prompt(db: Session, scenario_id: str, level: str) -> str:
    scenario = content.scenario_by_id(scenario_id) or content.scenario_by_id("frei")
    guidance = _LEVEL_GUIDANCE.get(level, _LEVEL_GUIDANCE["A2.1"])

    prompt = (
        f"Du bist {scenario['role_de']} in einem Deutsch-Übungsgespräch. {scenario['setting_de']} "
        f"Der Lernende hat Niveau {level} (GER). "
        f"WICHTIG für deine Antworten: {guidance} "
        "Bleibe in deiner Rolle, stelle Rückfragen, sei freundlich und geduldig. "
        "Antworte NUR mit dem, was du in der Rolle sagen würdest — keine Erklärungen, keine Meta-Kommentare. "
        "Antworte AUSSCHLIESSLICH auf Deutsch — niemals auf Englisch, Chinesisch oder einer anderen Sprache."
    )
    prompt += weak_vocab_hint(db)
    prompt += weak_phoneme_hint(db)
    return prompt


def opening_line_prompt(scenario_id: str) -> str:
    scenario = content.scenario_by_id(scenario_id) or content.scenario_by_id("frei")
    return f"Beginne das Gespräch jetzt als {scenario['role_de']} mit einer kurzen, natürlichen Begrüßung."
