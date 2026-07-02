"""Text-to-speech: synthesize (cached) and serve the resulting audio file."""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import config
from ..db import get_db
from ..services.tts import cache

router = APIRouter(tags=["tts"])


class TtsIn(BaseModel):
    text: str
    engine: str = "piper"  # piper|chatterbox
    voice: str = ""


@router.post("/api/tts")
def synthesize(body: TtsIn, db: Session = Depends(get_db)) -> dict:
    if not body.text.strip():
        raise HTTPException(422, "text must not be empty")
    try:
        key, latency_ms = cache.synthesize_cached(db, body.text, body.engine, body.voice)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"TTS engine unavailable: {e}")
    return {"id": key, "url": f"/audio/tts/{key}.wav", "latency_ms": round(latency_ms, 1)}


@router.get("/audio/tts/{key}.wav")
def get_audio(key: str) -> FileResponse:
    path = config.TTS_CACHE_DIR / f"{key}.wav"
    if not path.exists():
        raise HTTPException(404, "audio not found")
    return FileResponse(path, media_type="audio/wav")
