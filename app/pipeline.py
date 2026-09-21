"""CUORE condiviso: esecuzione di un job di traduzione.

Usato sia dal worker del server sia dalla CLI. Non dipende da FastAPI: riceve
``Storage``, un ``CloneEngine`` e un ``JobRecord``, esegue la traduzione delle
pagine in parallelo (``ThreadPoolExecutor``) e produce l'artefatto finale
(PDF unito o ZIP di pagine singole), aggiornando stato, progresso e log.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from . import ocr
from .config import Settings
from .engine import CloneEngine, EngineError, TranslationCancelled
from .logging_setup import JobLogger
from .models import JobRecord, JobState, RangeMode, utcnow
from .storage import Storage

log = logging.getLogger("noesis.pipeline")


@dataclass
class PageResult:
    page: int
    ok: bool
    error: str | None = None
    duration_ms: int = 0


@dataclass
class JobResult:
    job_id: str
    pages_total: int
    pages_done: int
    pages_failed: int
    cancelled: bool
    artifact_path: str | None
    duration_ms: int
    page_results: list[PageResult] = field(default_factory=list)
    error: str | None = None


def run_job(
    *,
    storage: Storage,
    engine: CloneEngine,
    job: JobRecord,
    settings: Settings,
    logger: JobLogger | None = None,
    on_page_done=None,
    cancel_event: threading.Event | None = None,
) -> JobResult:
    """Esegue il job dall'inizio alla fine e ritorna l'esito.

    ``on_page_done(done, total, page, ok)`` viene invocato a ogni pagina: il
    worker lo usa per persistere il progresso, la CLI per la barra tqdm.
    """
    document = storage.get_document(job.doc_id)
    if document is None:
        raise EngineError(f"documento {job.doc_id} non trovato")
    src = Path(document.path)
    if not src.is_file():
        raise EngineError("file del documento mancante su disco")
    doc_key = document.sha256  # hash del contenuto = chiave cache

    pages = list(job.pages)
    total = len(pages)
    started = utcnow()
    start_monotonic = time.monotonic()

    storage.update_job(
        job.job_id,
        state=JobState.running,
        started=started,
        pages_total=total,
        pages_done=0,
        pages_failed=0,
        queue_position=None,
    )
    if logger:
        logger.event(
            "started",
            f"avvio traduzione di {total} pagine con motore {job.engine}",
            pages=total,
            engine=job.engine,
            src_lang=job.src_lang,
            dst_lang=job.dst_lang,
        )

    done = 0
    failed = 0
    results: list[PageResult] = []

    def work(page: int) -> Path:
        if cancel_event is not None and cancel_event.is_set():
            raise TranslationCancelled("annullato")
        if ocr.is_enabled(settings) and ocr.page_needs_ocr(src, page):
            if logger:
                logger.event(
                    "ocr_required",
                    f"pagina {page + 1}: nessun testo estraibile (OCR richiesto)",
                    page=page,
                    level="warning",
                )
        return engine.translate_page(
            src,
            doc_key,
            page,
            job.engine,
            job.src_lang,
            job.dst_lang,
            cancel_event=cancel_event,
        )

    cancelled = False
    with ThreadPoolExecutor(max_workers=max(1, settings.page_concurrency)) as pool:
        futures = {pool.submit(work, page): page for page in pages}
        for future in as_completed(futures):
            page = futures[future]
            page_start = time.monotonic()
            try:
                future.result()
                page_ms = int((time.monotonic() - page_start) * 1000)
                done += 1
                results.append(PageResult(page=page, ok=True, duration_ms=page_ms))
                if logger:
                    logger.event(
                        "translate_page",
                        f"pagina {page + 1} tradotta",
                        page=page,
                        status="ok",
                        duration_ms=page_ms,
                    )
            except TranslationCancelled as exc:
                cancelled = True
                failed += 1
                results.append(
                    PageResult(page=page, ok=False, error=str(exc) or "annullato")
                )
                if logger:
                    logger.event(
                        "cancelled",
                        f"pagina {page + 1} annullata",
                        page=page,
                        level="warning",
                        status="cancelled",
                    )
            except Exception as exc:  # noqa: BLE001 - riportato nel job
                failed += 1
                reason = str(exc) or exc.__class__.__name__
                results.append(PageResult(page=page, ok=False, error=reason))
                if logger:
                    logger.event(
                        "translate_page",
                        f"pagina {page + 1} non riuscita: {reason}",
                        page=page,
                        level="error",
                        status="error",
                    )
            storage.update_job(
                job.job_id, pages_done=done, pages_failed=failed
            )
            if on_page_done:
                on_page_done(done, total, page, results[-1].ok)

    # ── artefatto finale ───────────────────────────────────────────────
    ok_pages = [r.page for r in results if r.ok]
    artifact_path: str | None = None
    final_error: str | None = None

    if cancelled:
        state = JobState.cancelled
        final_error = "job annullato"
        if logger:
            logger.event("cancelled", "job annullato", level="warning")
    elif not ok_pages:
        state = JobState.error
        final_error = results[0].error if results else "nessuna pagina tradotta"
        if logger:
            logger.event("error", f"nessuna pagina tradotta: {final_error}", level="error")
    else:
        try:
            artifact_path = _build_artifact(storage, engine, job, doc_key, ok_pages, logger)
            state = JobState.done
        except Exception as exc:  # noqa: BLE001
            state = JobState.error
            final_error = f"errore nella creazione dell'output: {exc}"
            if logger:
                logger.event("error", final_error, level="error")

    duration_ms = int((time.monotonic() - start_monotonic) * 1000)
    finished = utcnow()
    storage.update_job(
        job.job_id,
        state=state,
        pages_done=done,
        pages_failed=failed,
        artifact_path=artifact_path,
        error=final_error,
        finished=finished,
        duration_ms=duration_ms,
    )
    storage.add_usage(
        job_id=job.job_id,
        doc_id=job.doc_id,
        actor_id=job.owner_id,
        engine=job.engine,
        pages=done,
        duration_ms=duration_ms,
    )
    if logger:
        logger.event(
            "done" if state == JobState.done else state.value,
            f"job {state.value}: {done} tradotte, {failed} fallite in {duration_ms} ms",
            level="info" if state == JobState.done else "warning",
            pages_done=done,
            pages_failed=failed,
            duration_ms=duration_ms,
            artifact=artifact_path,
        )

    return JobResult(
        job_id=job.job_id,
        pages_total=total,
        pages_done=done,
        pages_failed=failed,
        cancelled=cancelled,
        artifact_path=artifact_path,
        duration_ms=duration_ms,
        page_results=results,
        error=final_error,
    )


def _build_artifact(
    storage: Storage,
    engine: CloneEngine,
    job: JobRecord,
    doc_key: str,
    ok_pages: list[int],
    logger: JobLogger | None,
) -> str:
    out_dir = storage.artifact_dir(job.job_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = job.output_name or "output"
    if job.range_mode == RangeMode.single:
        dest = out_dir / f"{stem}.zip"
        count = engine.export_zip(
            doc_key, ok_pages, job.engine, dest, job.src_lang, job.dst_lang, stem=stem
        )
        if logger:
            logger.event("zip", f"creato archivio ZIP con {count} pagine", path=str(dest))
    else:
        dest = out_dir / f"{stem}.pdf"
        count = engine.export_pdf(
            doc_key, ok_pages, job.engine, dest, job.src_lang, job.dst_lang
        )
        if logger:
            logger.event("merge", f"creato PDF unico con {count} pagine", path=str(dest))
    return str(dest)
