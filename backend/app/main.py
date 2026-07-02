"""GermanTime backend — FastAPI app serving the API, WebSockets, and built frontend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .api import all_routers
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    config.wire_dlls()
    init_db()
    yield


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
