"""Worker del server: costruisce l'engine per il job ed esegue la pipeline."""

from __future__ import annotations

import logging
import threading

from .config import Settings
from .covers import ensure_cover
from .engine import CloneEngine
from .logging_setup import JobLogger
from .metrics import (
    JOBS_CANCELLED,
    JOBS_DONE,
    JOBS_FAILED,
    METRICS,
    PAGES_FAILED,
    PAGES_TRANSLATED,
)
from .models import JobRecord
from .pipeline import run_job
from .storage import Storage

log = logging.getLogger("noesis.worker")


class JobRunner:
    """Esegue un singolo job tramite la pipeline condivisa."""

    def __init__(self, storage: Storage, settings: Settings) -> None:
        self.storage = storage
        self.settings = settings
        # Chiavi BYOK per job, tenute SOLO in memoria e rimosse all'uso. Non
        # vengono mai scritte su DB/log. Funzionano quando API e worker sono lo
        # stesso processo (ROLE=all): per worker separati l'API rifiuta il BYOK.
        self._llm_keys: dict[str, str] = {}
        self._llm_keys_lock = threading.Lock()

    def set_job_key(self, job_id: str, api_key: str) -> None:
        with self._llm_keys_lock:
            self._llm_keys[job_id] = api_key

    def take_job_key(self, job_id: str) -> str:
        with self._llm_keys_lock:
            return self._llm_keys.pop(job_id, "")

    def drop_job_key(self, job_id: str) -> None:
        with self._llm_keys_lock:
            self._llm_keys.pop(job_id, None)

    def engine_for(self, job: JobRecord) -> CloneEngine:
        # Chiave BYOK del job (se presente) oppure chiave del server.
        api_key = self.take_job_key(job.job_id) or self.settings.openrouter_api_key
        return CloneEngine(
            self.settings.cache_root,
            pdf2zh_bin=self.settings.pdf2zh_bin,
            max_engine_procs=self.settings.max_engine_procs,
            page_timeout=self.settings.page_timeout,
            cache_version=self.settings.engine_cache_version,
            llm_model=self.settings.llm_model,
            llm_base_url=self.settings.llm_base_url,
            api_key=api_key,
        )

    def run(self, job: JobRecord, cancel_event: threading.Event):
        logger = JobLogger(self.storage, job.job_id)
        engine = self.engine_for(job)

        def on_page_done(done: int, total: int, page: int, ok: bool) -> None:
            if ok:
                METRICS.inc(PAGES_TRANSLATED)
            else:
                METRICS.inc(PAGES_FAILED)

        result = run_job(
            storage=self.storage,
            engine=engine,
            job=job,
            settings=self.settings,
            logger=logger,
            on_page_done=on_page_done,
            cancel_event=cancel_event,
        )
        if result.cancelled:
            METRICS.inc(JOBS_CANCELLED)
        elif result.artifact_path:
            METRICS.inc(JOBS_DONE)
        else:
            METRICS.inc(JOBS_FAILED)
        if result.artifact_path:
            # Copertina di storico: generata subito a fine job così sopravvive
            # alla pulizia del documento (retention job > documento) anche se
            # nessuno ha mai aperto la tessera. Accessoria: non fa fallire nulla.
            try:
                ensure_cover(self.storage, job)
            except Exception:  # noqa: BLE001
                log.warning("copertina non generata per %s", job.job_id, exc_info=True)
        log.info(
            "job %s concluso: %d ok / %d fallite",
            job.job_id, result.pages_done, result.pages_failed,
        )
        return result
