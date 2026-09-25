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

import markdown as _markdown
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__
from .api.v1 import api_router
from .config import Settings, get_settings
from .context import AppContext
from .logging_setup import configure_logging

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
LEGAL_DIR = REPO_ROOT / "legal"

# Pagine legali servite: slug URL → file (relativo alla radice del repo).
_LEGAL_PAGES = {
    "terms": ("legal", "TERMS"),
    "privacy": ("legal", "PRIVACY"),
    "disclaimer": ("legal", "DISCLAIMER"),
    "acceptable-use": ("legal", "ACCEPTABLE_USE"),
    "additional-terms": ("root", "ADDITIONAL_TERMS"),
    "trademark": ("root", "TRADEMARK"),
    "security": ("root", "SECURITY"),
    "contributing": ("root", "CONTRIBUTING"),
    "cla": ("root", "CLA"),
}

_LEGAL_TITLES = {
    "terms": "Termini d'uso · Terms of Use",
    "privacy": "Privacy",
    "disclaimer": "Esclusione di garanzia · Disclaimer",
    "acceptable-use": "Uso accettabile · Acceptable Use",
    "additional-terms": "Termini aggiuntivi · Additional Terms",
    "trademark": "Marchio · Trademark",
    "security": "Sicurezza · Security",
    "contributing": "Contribuire · Contributing",
    "cla": "CLA",
}


def _render_legal_page(slug: str, lang: str) -> str:
    """Rende in HTML una pagina legale (Markdown) dalla fonte unica."""
    entry = _LEGAL_PAGES.get(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="pagina non trovata")
    base = LEGAL_DIR if entry[0] == "legal" else REPO_ROOT
    path = base / f"{entry[1]}.{lang}.md"
    if not path.is_file():
        path = base / f"{entry[1]}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="documento non trovato")
    text = path.read_text(encoding="utf-8")
    return _markdown.markdown(
        text,
        extensions=["extra", "toc", "sane_lists"],
    )



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
            request,
            "index.html",
            {
                "version": __version__,
                "help_url": settings.help_url,
                "terms_version": settings.terms_version,
            },
        )

    def _legal_response(request: Request, slug: str) -> HTMLResponse:
        lang = request.query_params.get("lang", "it").lower()
        if lang not in {"it", "en"}:
            lang = "it"
        body = _render_legal_page(slug, lang)
        return templates.TemplateResponse(
            request,
            "legal.html",
            {
                "version": __version__,
                "title": _LEGAL_TITLES.get(slug, slug),
                "body": body,
                "lang": lang,
                "help_url": settings.help_url,
                "terms_version": settings.terms_version,
            },
        )

    @app.get("/terms", response_class=HTMLResponse)
    def terms(request: Request) -> HTMLResponse:
        return _legal_response(request, "terms")

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy(request: Request) -> HTMLResponse:
        return _legal_response(request, "privacy")

    @app.get("/disclaimer", response_class=HTMLResponse)
    def disclaimer(request: Request) -> HTMLResponse:
        return _legal_response(request, "disclaimer")

    @app.get("/acceptable-use", response_class=HTMLResponse)
    def acceptable_use(request: Request) -> HTMLResponse:
        return _legal_response(request, "acceptable-use")

    @app.get("/legal/{slug}", response_class=HTMLResponse)
    def legal_page(request: Request, slug: str) -> HTMLResponse:
        return _legal_response(request, slug)

    return app


app = create_app()
