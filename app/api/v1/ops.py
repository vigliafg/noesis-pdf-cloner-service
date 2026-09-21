"""Endpoint operativi: health e metriche."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from ... import __version__
from ...metrics import METRICS
from ...models import HealthOut
from .deps import get_ctx

log = logging.getLogger("noesis.api")
router = APIRouter(tags=["ops"])


@router.get("/health", response_model=HealthOut)
def health(request: Request) -> HealthOut:
    ctx = get_ctx(request)
    return HealthOut(
        status="ok",
        version=__version__,
        engine_available=ctx.engine_available(),
        queue_length=ctx.queue.qsize(),
        workers=ctx.settings.workers,
        role=ctx.settings.role,
    )


@router.get("/system")
def system(request: Request) -> dict:
    """Risorse della macchina, valori effettivi/consigliati e stato coda."""
    return get_ctx(request).system_info()


@router.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(METRICS.render(), media_type="text/plain; version=0.0.4")
