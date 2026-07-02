"""GermanTime backend — FastAPI app serving the API, WebSockets, and built frontend."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .api import all_routers
from .db import SessionLocal, init_db
from .models import Setting
from .services import factory, stt, vad
from .services.pron import aligner as pron_aligner
from .services.tts import chatterbox_engine, piper_engine

logger = logging.getLogger(__name__)

FACTORY_POLL_S = 15


async def _factory_loop() -> None:
    while True:
        try:
            if factory.queue_status().get("queued"):
                await factory.run_queue(limit=3)
        except Exception:  # noqa: BLE001
            logger.exception("content factory loop error")
        await asyncio.sleep(FACTORY_POLL_S)


async def _warmup_voice_stack() -> None:
    """Pays the one-time CUDA/model-load cost (VAD+STT ~2-10s, TTS session
    init) at startup in the background instead of on the user's first
    conversation turn — without this, turn 1 of every fresh app launch eats
    several extra seconds waiting on cuDNN algo search / model weight
    transfer that every later turn gets for free.
    """
    loop = asyncio.get_event_loop()
    config.wire_espeak()
    with SessionLocal() as db:
        engine_row = db.get(Setting, "voice_engine")
    engine = engine_row.value if engine_row and engine_row.value else "piper"
    try:
        await loop.run_in_executor(None, vad.warmup)
        await loop.run_in_executor(None, stt.warmup)
        await loop.run_in_executor(None, piper_engine.warmup)
        if engine == "chatterbox":
            await loop.run_in_executor(None, chatterbox_engine.warmup)
        await loop.run_in_executor(None, pron_aligner.warmup)
        logger.info("voice stack warmup complete")
    except Exception:  # noqa: BLE001
        logger.exception("voice stack warmup failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    config.wire_dlls()
    config.wire_espeak()
    init_db()
    task = asyncio.create_task(_factory_loop())
    warmup_task = asyncio.create_task(_warmup_voice_stack())
    yield
    task.cancel()
    warmup_task.cancel()


app = FastAPI(title="GermanTime", lifespan=lifespan)

for r in all_routers:
    app.include_router(r)


# ---- Static frontend (built by Vite) with SPA fallback ----
if config.FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=config.FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        file = config.FRONTEND_DIST / path
        if path and file.is_file():
            return FileResponse(file)
        return FileResponse(config.FRONTEND_DIST / "index.html")
