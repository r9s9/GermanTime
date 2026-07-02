"""GermanTime backend — FastAPI app serving the API, WebSockets, and built frontend."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .api import all_routers
from .db import init_db
from .services import factory

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    config.wire_dlls()
    init_db()
    task = asyncio.create_task(_factory_loop())
    yield
    task.cancel()


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
