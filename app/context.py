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

    def queue_position(self, job_id: str) -> int | None:
        return self.queue.position(job_id)

    def shutdown(self) -> None:
        self.queue.stop()
        self.janitor.stop()
        self.storage.close()
