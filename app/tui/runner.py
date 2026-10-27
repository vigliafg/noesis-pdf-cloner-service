"""Esecuzione di un job in un thread, con eventi verso la UI.

Avvolge :func:`app.pipeline.run_job` (la pipeline unica del service) e
garantisce sempre uno stato terminale sul database, anche quando la pipeline
esce prima di aggiornarlo (documento mancante, preflight, eccezione).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from ..config import Settings
from ..engine import CloneEngine
from ..logging_setup import JobLogger
from ..models import JobRecord, JobState, utcnow
from ..pipeline import JobResult, run_job
from ..storage import Storage
from .jobs import is_terminal

log = logging.getLogger("noesis.tui")

EventCallback = Callable[[dict], None]
PageCallback = Callable[[int, int, int, bool], None]
DoneCallback = Callable[[JobResult | None, str | None], None]


class _EventLogger:
    """``JobLogger`` + inoltro di ogni evento alla UI (stessa firma)."""

    def __init__(self, logger: JobLogger, callback: EventCallback | None) -> None:
        self._logger = logger
        self._callback = callback

    def event(self, stage, message, *, page=None, level="info", **extra) -> dict:
        record = self._logger.event(
            stage, message, page=page, level=level, **extra
        )
        if self._callback is not None:
            try:
                self._callback(record)
            except Exception:  # noqa: BLE001 - la UI non deve fermare il job
                log.debug("callback evento non riuscita", exc_info=True)
        return record


class TuiJobRunner:
    """Un job, un thread, un ``threading.Event`` per l'annullamento."""

    def __init__(
        self,
        *,
        storage: Storage,
        engine: CloneEngine,
        job: JobRecord,
        settings: Settings,
        on_event: EventCallback | None = None,
        on_page: PageCallback | None = None,
        on_done: DoneCallback | None = None,
    ) -> None:
        self.storage = storage
        self.engine = engine
        self.job = job
        self.settings = settings
        self.on_event = on_event
        self.on_page = on_page
        self.on_done = on_done
        self.cancel_event = threading.Event()
        self.done = threading.Event()
        self.result: JobResult | None = None
        self.error: str | None = None
        self._started_monotonic = 0.0
        self._thread: threading.Thread | None = None

    # ── controllo ────────────────────────────────────────────────────────
    def start(self) -> None:
        self._started_monotonic = time.monotonic()
        self._thread = threading.Thread(
            target=self._run,
            name=f"tui-job-{self.job.job_id[:8]}",
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        """Chiede l'annullamento: la pipeline lo onora entro pochi secondi."""
        self.cancel_event.set()

    def join(self, timeout: float | None = None) -> bool:
        return self.done.wait(timeout)

    @property
    def running(self) -> bool:
        return not self.done.is_set()

    # ── esecuzione ───────────────────────────────────────────────────────
    def _run(self) -> None:  # pragma: no cover - coperto dai test sul runner
        logger = _EventLogger(
            JobLogger(self.storage, self.job.job_id), self.on_event
        )

        def on_page_done(done: int, total: int, page: int, ok: bool) -> None:
            if self.on_page is not None:
                try:
                    self.on_page(done, total, page, ok)
                except Exception:  # noqa: BLE001
                    log.debug("callback pagina non riuscita", exc_info=True)

        try:
            self.result = run_job(
                storage=self.storage,
                engine=self.engine,
                job=self.job,
                settings=self.settings,
                logger=logger,
                on_page_done=on_page_done,
                cancel_event=self.cancel_event,
            )
        except Exception as exc:  # noqa: BLE001 - riportato nel job
            self.error = str(exc) or exc.__class__.__name__
            log.warning("job %s fallito: %s", self.job.job_id, self.error)
            self._mark_failed()
        finally:
            self.done.set()
            if self.on_done is not None:
                try:
                    self.on_done(self.result, self.error)
                except Exception:  # noqa: BLE001
                    log.debug("callback finale non riuscita", exc_info=True)

    def _mark_failed(self) -> None:
        """Stato terminale garantito se la pipeline è uscita in anticipo."""
        try:
            stored = self.storage.get_job(self.job.job_id)
        except Exception:  # noqa: BLE001
            return
        if stored is None or is_terminal(stored.state):
            return
        duration_ms = int((time.monotonic() - self._started_monotonic) * 1000)
        self.storage.update_job(
            self.job.job_id,
            state=JobState.error,
            error=self.error or "errore sconosciuto",
            finished=utcnow(),
            duration_ms=duration_ms,
        )
