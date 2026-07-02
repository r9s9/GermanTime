"""Hover-translate endpoints backing the German-first UI's word/sentence lookups."""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from ..db import get_db
from ..services import translator

router = APIRouter(prefix="/api/translate", tags=["translate"])


class WordIn(BaseModel):
    word: str
    sentence: str = ""


@router.post("/word")
async def translate_word(body: WordIn, db: Session = Depends(get_db)) -> dict:
    return await translator.translate_word(db, body.word, body.sentence)


class SentenceIn(BaseModel):
    text: str


@router.post("/sentence")
async def translate_sentence(body: SentenceIn, db: Session = Depends(get_db)) -> dict:
    return await translator.translate_sentence(db, body.text)
