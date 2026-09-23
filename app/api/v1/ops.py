"""Endpoint operativi: health e metriche."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from ... import __version__
from ...metrics import METRICS
from ...models import HealthOut
from .deps import get_ctx

log = logging.getLogger("noesis.api")
router = APIRouter(tags=["ops"])


@router.get("/health", response_model=HealthOut)
def health(request: Request, deep: bool = False) -> HealthOut:
    """Stato del servizio.

    Di default è **economico** (nessuna rete): disponibilità del motore e
    presenza della chiave, con ``status`` ``ok``/``degraded``. Con ``?deep=1``
    esegue la diagnostica completa (rete, chiave, modello, catena gratuita) e
    mette i risultati in ``checks``: usalo dai monitor, non dai probe frequenti.
    """
    ctx = get_ctx(request)
    engine_available = ctx.engine_available()
    key = (
        ctx.settings.openrouter_api_key
        or os.environ.get("OPENROUTER_API_KEY")
        or ""
    ).strip()

    checks = None
    status = "ok" if engine_available else "degraded"
    if deep:
        from ...diagnostics import build_context, health_status, run_all

        results = run_all(build_context(ctx.settings))
        checks = [r.__dict__ for r in results]
        status = health_status(results)

    return HealthOut(
        status=status,
        version=__version__,
        engine_available=engine_available,
        queue_length=ctx.queue.qsize(),
        workers=ctx.settings.workers,
        role=ctx.settings.role,
        engine_runnable=engine_available,
        key_present=bool(key),
        checks=checks,
    )


@router.get("/system")
def system(request: Request) -> dict:
    """Risorse della macchina, valori effettivi/consigliati e stato coda."""
    return get_ctx(request).system_info()


@router.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(METRICS.render(), media_type="text/plain; version=0.0.4")
