"""Janitor: retention e pulizia periodica (artefatti, log, documenti, thumb)."""

from __future__ import annotations

import contextlib
import logging
import shutil
import threading
import time

from .config import Settings
from .models import JobState
from .storage import Storage

log = logging.getLogger("noesis.janitor")

_ACTIVE_STATES = {JobState.queued, JobState.running}


class Janitor:
    """Thread di manutenzione: rimuove ciò che ha superato la retention."""

    def __init__(self, storage: Storage, settings: Settings) -> None:
        self.storage = storage
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name="noesis-janitor", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _loop(self) -> None:
        interval = max(30, self.settings.janitor_interval_seconds)
        while not self._stop.is_set():
            try:
                self.cleanup()
            except Exception:  # pragma: no cover - difensivo
                log.exception("errore nel janitor")
            self._stop.wait(interval)

    def cleanup(self) -> dict[str, int]:
        removed_jobs = self._cleanup_jobs()
        removed_docs = self._cleanup_documents()
        return {"jobs": removed_jobs, "documents": removed_docs}

    def _cleanup_jobs(self) -> int:
        count = 0
        for job in self.storage.old_jobs(self.settings.job_retention_hours):
            artifact_dir = self.storage.artifact_dir(job.job_id)
            if artifact_dir.exists():
                shutil.rmtree(artifact_dir, ignore_errors=True)
            log_path = self.storage.job_log_path(job.job_id)
            with contextlib.suppress(OSError):
                log_path.unlink()
            if job.artifact_path:
                self.storage.update_job(job.job_id, artifact_path=None)
            count += 1
        return count

    def _cleanup_documents(self) -> int:
        active_doc_ids = {
            job.doc_id
            for state in _ACTIVE_STATES
            for job in self.storage.jobs_by_state(state)
        }
        count = 0
        for document in self.storage.old_documents(
            self.settings.document_retention_hours
        ):
            if document.doc_id in active_doc_ids:
                continue
            with contextlib.suppress(OSError):
                self.storage.document_path(document.doc_id).unlink()
            shutil.rmtree(
                self.storage.thumb_dir(document.sha256), ignore_errors=True
            )
            self.storage.delete_document(document.doc_id)
            count += 1
        return count
