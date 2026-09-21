"""Metriche minime (contatori + gauge) esposte in formato Prometheus.

Nessuna dipendenza esterna: sufficiente per osservare coda, job, processi
motore, uso e costi. In futuro potrà essere sostituito da un client dedicato.
"""

from __future__ import annotations

import threading
from collections import defaultdict

# Nomi dei contatori principali (usati anche nei test).
JOBS_SUBMITTED = "noesis_jobs_submitted_total"
JOBS_DONE = "noesis_jobs_done_total"
JOBS_FAILED = "noesis_jobs_failed_total"
JOBS_CANCELLED = "noesis_jobs_cancelled_total"
PAGES_TRANSLATED = "noesis_pages_translated_total"
PAGES_FAILED = "noesis_pages_failed_total"
QUEUE_LENGTH = "noesis_queue_length"
ENGINE_PROCS = "noesis_engine_procs_active"


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}

    def inc(self, name: str, value: float = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            merged = dict(self._counters)
            merged.update(self._gauges)
        return merged

    def render(self) -> str:
        lines: list[str] = []
        for name, value in sorted(self.snapshot().items()):
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value:g}")
        return "\n".join(lines) + "\n"


METRICS = Metrics()
