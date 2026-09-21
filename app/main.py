"""Applicazione FastAPI: API v1, frontend e ciclo di vita di coda/janitor.

Nota importante: il servizio va eseguito con **un solo processo uvicorn**
(``--workers 1``): la coda è in memoria e i semafori del motore sono per
processo. Il parallelismo è interno (thread), non a livello di processo.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__
from .api.v1 import api_router
from .config import Settings, get_settings
from .context import AppContext
from .logging_setup import configure_logging

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def create_app(
    settings: Settings | None = None,
    context: AppContext | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    configure_logging()

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        active = context or AppContext.build(settings)
        app.state.ctx = active
        active.start()
        try:
            yield
        finally:
            active.shutdown()

    app = FastAPI(
        title="noesis-pdf-cloner-service",
        version=__version__,
        description="Traduzione PDF con layout preservato: server + coda + CLI.",
        lifespan=lifespan,
    )
    app.include_router(api_router)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "index.html", {"version": __version__}
        )

    return app


app = create_app()
