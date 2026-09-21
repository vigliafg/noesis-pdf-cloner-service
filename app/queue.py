"""Coda dei job: backend astratto + implementazione in-memory a priorità.

Oggi la coda vive in memoria (single-process), ma è dietro l'interfaccia
``QueueBackend`` così in futuro si potrà usare Redis/Celery senza toccare
pipeline o API. La fonte di verità resta SQLite: all'avvio si fa *recovery*.
"""

from __future__ import annotations

import abc
import heapq
import logging
import threading
from itertools import count

from .config import Settings
from .metrics import METRICS, QUEUE_LENGTH
from .models import JobState
from .storage import Storage

log = logging.getLogger("noesis.queue")


class QueueBackend(abc.ABC):
    """Interfaccia di una coda a priorità."""

    @abc.abstractmethod
    def put(self, job_id: str, priority: int = 0) -> None: ...

    @abc.abstractmethod
    def get(self, timeout: float | None = None) -> str | None: ...

    @abc.abstractmethod
    def remove(self, job_id: str) -> bool: ...

    @abc.abstractmethod
    def position(self, job_id: str) -> int | None: ...

    @abc.abstractmethod
    def qsize(self) -> int: ...


class InMemoryQueueBackend(QueueBackend):
    """Heap a priorità (più alto = prima) con condizione di blocco."""

    def __init__(self) -> None:
        self._heap: list[tuple[int, int, str]] = []
        self._removed: set[str] = set()
        self._counter = count()
        self._cond = threading.Condition()

    def put(self, job_id: str, priority: int = 0) -> None:
        with self._cond:
            if job_id in self._removed:
                self._removed.discard(job_id)
            heapq.heappush(self._heap, (-int(priority), next(self._counter), job_id))
            self._cond.notify()

    def get(self, timeout: float | None = None) -> str | None:
        with self._cond:
            deadline_reached = self._cond.wait_for(
                lambda: bool(self._heap), timeout=timeout
            )
            if not deadline_reached:
                return None
            while self._heap:
                _, _, job_id = heapq.heappop(self._heap)
                if job_id in self._removed:
                    self._removed.discard(job_id)
                    continue
                return job_id
            return None

    def remove(self, job_id: str) -> bool:
        with self._cond:
            if any(item[2] == job_id for item in self._heap):
                self._removed.add(job_id)
                self._cond.notify()
                return True
            return False

    def position(self, job_id: str) -> int | None:
        with self._cond:
            active = [
                item for item in sorted(self._heap)
                if item[2] not in self._removed
            ]
            for index, item in enumerate(active):
                if item[2] == job_id:
                    return index + 1
            return None

    def qsize(self) -> int:
        with self._cond:
            return sum(1 for item in self._heap if item[2] not in self._removed)


class JobQueue:
    """Coda + pool di worker thread che eseguono i job."""

    def __init__(
        self,
        storage: Storage,
        settings: Settings,
        runner,
        backend: QueueBackend | None = None,
    ) -> None:
        self.storage = storage
        self.settings = settings
        self.runner = runner
        self.backend = backend or InMemoryQueueBackend()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._cancelled: set[str] = set()
        self._cancel_lock = threading.Lock()
        self._cancel_events: dict[str, threading.Event] = {}

    # ── ciclo di vita ────────────────────────────────────────────────────
    def start(self) -> None:
        self._recover()
        for index in range(max(1, self.settings.workers)):
            thread = threading.Thread(
                target=self._loop, name=f"noesis-worker-{index}", daemon=True
            )
            thread.start()
            self._threads.append(thread)
        self._update_gauge()
        log.info("coda avviata con %d worker", len(self._threads))

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        # sveglia i worker bloccati in attesa
        for job_id, event in list(self._cancel_events.items()):
            event.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    def _recover(self) -> None:
        """Ripristina lo stato dopo un riavvio: source of truth = SQLite."""
        for job in self.storage.jobs_by_state(JobState.running):
            self.storage.update_job(
                job.job_id,
                state=JobState.interrupted,
                error="interrotto dal riavvio del servizio",
            )
            log.warning("job %s riportato a interrupted", job.job_id)
        for job in self.storage.jobs_by_state(JobState.queued):
            self.backend.put(job.job_id, job.priority)

    # ── API ──────────────────────────────────────────────────────────────
    def submit(self, job_id: str, priority: int = 0) -> None:
        if self.backend.qsize() >= self.settings.max_queue_size:
            raise RuntimeError("coda piena")
        self.backend.put(job_id, priority)
        self._update_gauge()

    def cancel(self, job_id: str) -> bool:
        with self._cancel_lock:
            self._cancelled.add(job_id)
            event = self._cancel_events.get(job_id)
        removed = self.backend.remove(job_id)
        if event is not None:
            event.set()
        if removed:
            self.storage.update_job(
                job_id, state=JobState.cancelled, error="annullato prima dell'esecuzione"
            )
        self._update_gauge()
        return removed or event is not None

    def position(self, job_id: str) -> int | None:
        return self.backend.position(job_id)

    def qsize(self) -> int:
        return self.backend.qsize()

    # ── worker ───────────────────────────────────────────────────────────
    def _loop(self) -> None:
        while not self._stop.is_set():
            job_id = self.backend.get(timeout=0.5)
            self._update_gauge()
            if not job_id:
                continue
            with self._cancel_lock:
                if job_id in self._cancelled:
                    self._cancelled.discard(job_id)
                    self.storage.update_job(
                        job_id,
                        state=JobState.cancelled,
                        error="annullato prima dell'esecuzione",
                    )
                    continue
                cancel_event = threading.Event()
                self._cancel_events[job_id] = cancel_event
            try:
                self._execute(job_id, cancel_event)
            finally:
                with self._cancel_lock:
                    self._cancel_events.pop(job_id, None)

    def _execute(self, job_id: str, cancel_event: threading.Event) -> None:
        job = self.storage.get_job(job_id)
        if job is None or job.state not in {JobState.queued, JobState.running}:
            return
        try:
            self.runner.run(job, cancel_event)
        except Exception:  # pragma: no cover - difensivo
            log.exception("errore imprevisto nel job %s", job_id)
            self.storage.update_job(
                job_id, state=JobState.error, error="errore interno del worker"
            )

    def _update_gauge(self) -> None:
        METRICS.set_gauge(QUEUE_LENGTH, self.backend.qsize())
