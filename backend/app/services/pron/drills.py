"""LLM-generated pronunciation drills targeting a specific weak phoneme,
G2P-validated so a drill actually exercises the sound it claims to — an
LLM asked to "use the ç sound" has no reliable notion of raw IPA, so the
prompt is grounded in concrete example words (from the learner's own known
vocabulary) and the result is checked with real G2P, not trusted blind.
"""

import logging
import random

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import g2p
from .. import concurrency, content, llm
from ...models import VocabItem

logger = logging.getLogger(__name__)

MIN_TARGET_OCCURRENCES = 3
MAX_ATTEMPTS = 3
VOCAB_SAMPLE_SIZE = 60


class DrillSentence(BaseModel):
    text_de: str = Field(description="Ein natürlicher deutscher Übungssatz, 5-10 Wörter")
    translation_en: str


def phoneme_info(phoneme: str) -> dict:
    data = content.phoneme_map()
    label = next((g["name_de"] for g in data["groups"] if phoneme in g["phonemes"]), phoneme)
    tip = data["tips"].get(phoneme, {})
    return {"phoneme": phoneme, "label_de": label, "tip_de": tip.get("de"), "tip_en": tip.get("en")}


def _words_containing(db: Session, phoneme: str, level: str, limit: int = 6) -> list[str]:
    """Known-vocabulary words containing the target phoneme, sourced from
    VocabItem.ipa (lazily G2P'd and cached back onto the row on first use —
    that column exists for exactly this)."""
    rows = db.scalars(
        select(VocabItem).where(VocabItem.level.in_({"A1", "A2", "B1"} & _levels_up_to(level)))
    ).all()
    if not rows:
        return []
    sample = random.sample(rows, min(VOCAB_SAMPLE_SIZE, len(rows)))

    unphonemized = [r for r in sample if r.ipa is None]
    if unphonemized:
        phone_lists = g2p.phonemize_words([r.lemma for r in unphonemized])
        for row, phones in zip(unphonemized, phone_lists):
            row.ipa = " ".join(phones)
        db.commit()

    matches = [r.lemma for r in sample if r.ipa and phoneme in r.ipa.split()]
    return matches[:limit]


def _levels_up_to(level: str) -> set[str]:
    order = ["A1", "A2", "B1"]
    base = level[:2] if level[:2] in order else "A2"
    return set(order[:order.index(base) + 1])


def _count_target(text: str, phoneme: str) -> int:
    words = g2p.words_in(text)
    phone_lists = g2p.phonemize_words(words)
    return sum(pl.count(phoneme) for pl in phone_lists)


async def generate(db: Session, phoneme: str, level: str = "A2.1") -> dict:
    """Returns {"phoneme", "label_de", "tip_de", "tip_en", "text_de",
    "translation_en", "occurrences"}. Retries up to MAX_ATTEMPTS if the
    LLM's sentence doesn't actually contain the target phoneme enough
    times; falls back to a known-good example word if every attempt fails.
    """
    info = phoneme_info(phoneme)
    known_words = _words_containing(db, phoneme, level)

    system = (
        "Du erstellst kurze, natürliche deutsche Übungssätze für die Aussprache. "
        "Antworte NUR mit dem Satz und einer kurzen englischen Übersetzung."
    )
    words_hint = f' Beispiele für Wörter mit diesem Laut: {", ".join(known_words)}.' if known_words else ""
    user = (
        f'Erstelle einen natürlichen deutschen Satz (5-10 Wörter, Niveau {level}) mit dem "{info["label_de"]}"'
        f"-Laut (mehrfach vorkommend, wenn möglich).{words_hint}"
    )

    for attempt in range(MAX_ATTEMPTS):
        async with concurrency.gpu_lock:
            item = await llm.generate_structured("tutor", system, user, DrillSentence, "drill_sentence",
                                                    temperature=0.9)
        occurrences = _count_target(item.text_de, phoneme)
        if occurrences >= MIN_TARGET_OCCURRENCES:
            return {**info, "text_de": item.text_de, "translation_en": item.translation_en,
                    "occurrences": occurrences}
        logger.info("drill attempt %d for %s only hit %d occurrences, retrying", attempt, phoneme, occurrences)

    if known_words:
        fallback_word = known_words[0]
        return {**info, "text_de": fallback_word, "translation_en": "",
                "occurrences": _count_target(fallback_word, phoneme)}
    example = (content.phoneme_map()["tips"].get(phoneme, {}).get("de", "") or "").strip()
    return {**info, "text_de": example or info["label_de"], "translation_en": "", "occurrences": 0}
