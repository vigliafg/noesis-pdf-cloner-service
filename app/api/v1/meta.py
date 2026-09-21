"""Endpoint meta: capacità del servizio (motori, lingue, limiti, feature)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ...models import ENGINES, LANGUAGES, MetaOut
from .deps import get_ctx

router = APIRouter(tags=["meta"])


@router.get("/meta", response_model=MetaOut)
def get_meta(request: Request) -> MetaOut:
    ctx = get_ctx(request)
    settings = ctx.settings
    return MetaOut(
        engines=list(ENGINES),
        languages=LANGUAGES,
        limits={
            "max_upload_mb": settings.max_upload_mb,
            "max_pages_per_block": settings.max_pages_per_block,
            "max_pages_total": settings.max_pages_total,
            "max_queue_size": settings.max_queue_size,
            "page_concurrency": settings.page_concurrency,
            "max_engine_procs": settings.max_engine_procs,
            "workers": settings.workers,
        },
        features={
            "ocr": settings.feature_ocr,
            "payments": settings.feature_payments,
            "auth_mode": settings.auth_mode,
        },
    )
