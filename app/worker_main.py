"""Processo worker: consuma la coda condivisa (nessun server HTTP).

Pensato per il deployment scalabile: avvia **1 processo API** (``ROLE=api``) e
**N processi worker** (``ROLE=worker WORKER_COUNT=N``) che condividono la coda
su SQLite (``DATA_DIR`` comune). Ogni worker ridimensiona le proprie risorse in
base alla macchina e alla divisione per ``WORKER_COUNT``.

    ROLE=worker WORKER_COUNT=4 python -m app.worker_main
"""

from __future__ import annotations

import logging
import signal
import threading

from .config import get_settings
from .logging_setup import configure_logging
from .queue import JobQueue
from .storage import Storage
from .worker import JobRunner

log = logging.getLogger("noesis.worker_main")


def run(stop_event: threading.Event) -> None:
    settings = get_settings()
    configure_logging()
    if settings.role != "worker":
        log.warning(
            "ROLE=%s: per i processi worker usa ROLE=worker (WORKER_COUNT=N)",
            settings.role,
        )
    storage = Storage(settings)
    runner = JobRunner(storage, settings)
    queue = JobQueue(storage, settings, runner)
    queue.start(serve_workers=True)
    log.info(
        "worker attivo: role=%s worker_count=%s · %s thread · %s processi motore",
        settings.role, settings.worker_count, settings.workers,
        settings.max_engine_procs,
    )
    try:
        while not stop_event.is_set():
            stop_event.wait(1.0)
    finally:
        queue.stop()
        storage.close()
        log.info("worker terminato")


def main(argv: list[str] | None = None) -> int:
    stop = threading.Event()

    def handler(signum, frame):  # noqa: ANN001
        log.info("segnale %s: arresto in corso…", signum)
        stop.set()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
    run(stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
