"""Contesto applicativo: istanze condivise da API e worker."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .emailer import Emailer
from .engine import find_pdf2zh_bin
from .janitor import Janitor
from .queue import JobQueue
from .security import RateLimiter
from .storage import Storage
from .worker import JobRunner


@dataclass
class AppContext:
    """Contenitore delle dipendenze di processo (singleton)."""

    settings: Settings
    storage: Storage
    runner: JobRunner
    queue: JobQueue
    janitor: Janitor
    rate_limiter: RateLimiter
    emailer: Emailer

    @classmethod
    def build(cls, settings: Settings) -> "AppContext":
        storage = Storage(settings)
        runner = JobRunner(storage, settings)
        queue = JobQueue(storage, settings, runner)
        janitor = Janitor(storage, settings)
        return cls(
            settings=settings,
            storage=storage,
            runner=runner,
            queue=queue,
            janitor=janitor,
            rate_limiter=RateLimiter(settings.rate_limit_per_minute),
            emailer=Emailer(storage, enabled=False),
        )

    def engine_available(self) -> bool:
        return find_pdf2zh_bin(self.settings.pdf2zh_bin) is not None

    def start(self) -> None:
        """Avvia i componenti in base al ruolo (``all``/``api``/``worker``)."""
        serve_workers = self.settings.role in {"all", "worker"}
        self.queue.start(serve_workers=serve_workers)
        if serve_workers:
            self.janitor.start()

    def system_info(self) -> dict:
        """Risorse rilevate, valori effettivi e consigliati."""
        from .resources import compute_limits, detect

        resources = detect(self.settings.data_dir)
        return {
            "role": self.settings.role,
            "queue_backend": self.settings.queue_backend,
            "resources": resources.to_dict(),
            "recommended": compute_limits(resources, self.settings),
            "effective": {
                "workers": self.settings.workers,
                "page_concurrency": self.settings.page_concurrency,
                "max_engine_procs": self.settings.max_engine_procs,
                "worker_count": self.settings.worker_count,
            },
            "queue_length": self.queue.qsize(),
            "engine_available": self.engine_available(),
        }

    def queue_position(self, job_id: str) -> int | None:
        return self.queue.position(job_id)

    def shutdown(self) -> None:
        self.queue.stop()
        self.janitor.stop()
        self.storage.close()
