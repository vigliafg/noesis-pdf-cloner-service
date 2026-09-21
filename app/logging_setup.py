"""Logging: configurazione di base e log JSONL per singolo job.

Ogni job scrive un file ``data/logs/jobs/<job_id>.jsonl`` con un evento per
riga (``ts, level, stage, message, page, …``). È il log "di funzionamento ed
esecuzione" richiesto, ed è anche la sorgente dello streaming SSE al frontend.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from .storage import Storage

log = logging.getLogger("noesis")


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


class JobLogger:
    """Scrittore di eventi JSONL per un job (thread-safe)."""

    def __init__(
        self, storage: Storage, job_id: str, echo: bool = False
    ) -> None:
        self.storage = storage
        self.job_id = job_id
        self.echo = echo
        self.path: Path = storage.job_log_path(job_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def event(
        self,
        stage: str,
        message: str,
        *,
        page: int | None = None,
        level: str = "info",
        **extra,
    ) -> dict:
        record: dict = {
            "ts": time.time(),
            "level": level,
            "stage": stage,
            "message": message,
        }
        if page is not None:
            record["page"] = page
            record["page_number"] = page + 1
        record.update(extra)

        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")

        if self.echo:
            print(f"[{stage}] {message}", flush=True)
        log.debug("job %s %s: %s", self.job_id, stage, message)
        return record


def read_events(storage: Storage, job_id: str) -> list[dict]:
    """Rilegge il log di un job (usato da test e da client non-SSE)."""
    path = storage.job_log_path(job_id)
    events: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events
