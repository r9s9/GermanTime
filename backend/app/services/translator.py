"""Hover-translate resolution: vocab_items (instant) -> translation_cache -> LLM gloss (cached forever)."""

import hashlib

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import llm
from ..models import TranslationCache, VocabItem


def _hash(word: str, context: str) -> str:
    return hashlib.sha1(f"{word}|{context}".encode("utf-8")).hexdigest()


class WordGloss(BaseModel):
    lemma: str
    pos: str
    article: str  # "der"/"die"/"das", or "" when not applicable
    gloss_en: str
    note_de: str


async def translate_word(db: Session, word: str, sentence: str = "") -> dict:
    item = db.scalar(select(VocabItem).where(VocabItem.lemma == word))
    if item:
        return {
            "lemma": item.lemma, "pos": item.pos, "article": item.article or "",
            "gloss_en": item.en_gloss, "level": item.level, "source": "vocab",
        }

    key = _hash(word, sentence)
    cached = db.get(TranslationCache, key)
    if cached:
        return {**cached.gloss, "source": "cache"}

    system = (
        "Du hilfst Deutschlernenden, ein einzelnes deutsches Wort im Kontext zu verstehen. "
        "Antworte ausschließlich mit dem geforderten JSON."
    )
    user = f'Wort: "{word}"' + (f'\nSatz: "{sentence}"' if sentence else "")
    result: WordGloss = await llm.generate_structured(
        "fast", system, user, WordGloss, "word_gloss", temperature=0.2
    )
    gloss = result.model_dump()
    db.add(TranslationCache(hash=key, word=word, context=sentence, gloss=gloss))
    db.commit()
    return {**gloss, "source": "llm"}


class SentenceTranslation(BaseModel):
    translation_en: str


async def translate_sentence(db: Session, text: str) -> dict:
    key = _hash("__sentence__", text)
    cached = db.get(TranslationCache, key)
    if cached:
        return {**cached.gloss, "source": "cache"}

    system = "Übersetze den folgenden deutschen Satz natürlich ins Englische. Antworte nur mit dem geforderten JSON."
    result: SentenceTranslation = await llm.generate_structured(
        "fast", system, text, SentenceTranslation, "sentence_translation", temperature=0.2
    )
    gloss = result.model_dump()
    db.add(TranslationCache(hash=key, word="__sentence__", context=text, gloss=gloss))
    db.commit()
    return {**gloss, "source": "llm"}
