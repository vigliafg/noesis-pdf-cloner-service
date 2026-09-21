"""Seam quota/entitlement.

Oggi ``check_quota`` è un no-op (servizio senza pagamenti). Quando si
attiveranno i piani, basterà leggere ``entitlements``/``plans`` e sollevare
HTTP 402 con i crediti residui. ``record_usage`` è invece già attivo: alimenta
la tabella ``usage`` (statistiche e base della fatturazione futura).
"""

from __future__ import annotations

from fastapi import HTTPException

from .auth import Actor
from .config import Settings
from .storage import Storage


def check_quota(
    actor: Actor, pages: int, settings: Settings, storage: Storage
) -> None:
    """Verifica la quota dell'attore. No-op finché ``QUOTA_ENABLED`` è falso."""
    if not settings.quota_enabled:
        return
    # Seam: qui si leggerà l'entitlement dell'attore e si confronteranno i
    # crediti residui con ``pages``; con i pagamenti attivi, decremento atomico.
    if settings.quota_default_pages and pages > settings.quota_default_pages:
        raise HTTPException(
            status_code=402,
            detail="Quota pagine insufficiente per questo job",
        )


def record_usage(
    storage: Storage,
    *,
    actor: Actor,
    job_id: str,
    doc_id: str,
    engine: str,
    pages: int,
    chars: int = 0,
    tokens: int = 0,
    duration_ms: int | None = None,
) -> None:
    storage.add_usage(
        job_id=job_id,
        doc_id=doc_id,
        actor_id=actor.id,
        engine=engine,
        pages=pages,
        chars=chars,
        tokens=tokens,
        duration_ms=duration_ms,
    )
