"""Creazione condivisa di motore, documento e job.

La costruzione di :class:`CloneEngine` ha molti parametri che devono restare
allineati a :class:`Settings`; la registrazione di documento + job è identica
per CLI e TUI. Tenere queste due cose in un solo posto evita che una nuova
impostazione venga replicata (e dimenticata) in ogni client della pipeline.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from .config import Settings
from .engine import CloneEngine
from .models import DocumentRecord, JobRecord, JobState, RangeMode
from .pages import parse_pages
from .security import sanitize_stem
from .storage import Storage

__all__ = [
    "PageSelectionError",
    "build_engine",
    "create_document_and_job",
    "register_document",
]


class PageSelectionError(ValueError):
    """Selezione pagine non valida per il documento (messaggio già leggibile)."""


def build_engine(settings: Settings, *, api_key: str | None = None) -> CloneEngine:
    """Costruisce il motore con i parametri dei ``Settings``.

    ``api_key`` serve al BYOK: la chiave del job (mai salvata) ha la precedenza
    su quella del servizio.
    """
    return CloneEngine(
        settings.cache_root,
        pdf2zh_bin=settings.pdf2zh_bin,
        max_engine_procs=settings.max_engine_procs,
        page_timeout=settings.page_timeout,
        cache_version=settings.engine_cache_version,
        llm_model=settings.llm_model,
        llm_base_url=settings.llm_base_url,
        llm_timeout=settings.llm_timeout,
        qps_google=settings.qps_google,
        qps_bing=settings.qps_bing,
        api_key=api_key or settings.openrouter_api_key,
        llm_pool_workers=settings.llm_pool_workers,
        fast_engine=settings.fast_engine,
        fast_flags=settings.fast_flags,
        fast_worker=settings.fast_worker,
        llm_reasoning_effort=settings.llm_reasoning_effort,
        llm_json_mode=settings.llm_json_mode,
        numeric_lists=settings.numeric_lists,
        llm_system_prompt=settings.llm_system_prompt,
    )


def register_document(
    storage: Storage,
    engine: CloneEngine,
    pdf: Path,
    *,
    owner_id: str = "cli",
) -> DocumentRecord:
    """Registra il PDF originale (senza copiarlo) e ne estrae i metadati."""
    document = DocumentRecord(
        doc_id=uuid.uuid4().hex,
        filename=pdf.name,
        sha256=engine.doc_key(pdf),
        page_count=CloneEngine.page_count(pdf),
        path=str(pdf),
        page_labels=CloneEngine.page_labels(pdf),
        owner_id=owner_id,
        size_bytes=pdf.stat().st_size,
    )
    storage.create_document(document)
    return document


def create_document_and_job(
    storage: Storage,
    engine: CloneEngine,
    pdf: Path,
    *,
    pages_spec: str = "all",
    src_lang: str = "auto",
    dst_lang: str = "it",
    engine_name: str = "google",
    output_name: str | None = None,
    range_mode: RangeMode = RangeMode.merged,
    owner_id: str = "cli",
    state: JobState = JobState.queued,
    max_pages: int | None = None,
) -> tuple[DocumentRecord, JobRecord]:
    """Registra documento e job. Solleva :class:`PageSelectionError` se la
    selezione non è valida (le pagine sono indici 0-based, come il motore)."""
    document = register_document(storage, engine, pdf, owner_id=owner_id)
    try:
        pages = parse_pages(pages_spec, document.page_count)
    except ValueError as exc:
        raise PageSelectionError(str(exc)) from exc
    if max_pages and len(pages) > max_pages:
        raise PageSelectionError(f"troppe pagine (max {max_pages})")

    stem = sanitize_stem(output_name or f"{pdf.stem}_{dst_lang}", "output")
    job = JobRecord(
        job_id=uuid.uuid4().hex,
        doc_id=document.doc_id,
        pages=pages,
        src_lang=src_lang,
        dst_lang=dst_lang,
        engine=engine_name,
        output_name=stem,
        range_mode=range_mode,
        state=state,
        pages_total=len(pages),
        owner_id=owner_id,
    )
    storage.create_job(job)
    return document, job
