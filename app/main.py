"""Applicazione FastAPI: API v1, frontend e ciclo di vita di coda/janitor.

Il ruolo è scelto con ``ROLE``: ``all`` (API + worker nello stesso processo),
``api`` (solo API) o ``worker`` (solo consumo della coda). Con il backend di
coda su SQLite (``QUEUE_BACKEND=db``, predefinito) si possono eseguire 1
processo API + N worker; i semafori del motore restano per processo. Nel
processo con ``ROLE=all`` coda e semafori sono locali, quindi va eseguito con
**un solo processo uvicorn** (``--workers 1``, come in ``run.sh``).
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
