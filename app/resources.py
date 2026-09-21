"""Rilevamento risorse e autosizing.

Il servizio **si adatta alla macchina**: alla partenza calcola worker, concorrenza
per pagina e processi motore massimi in base a CPU, RAM disponibile e disco.
I valori espliciti via variabili d'ambiente hanno sempre la precedenza.

In deployment multi-processo (``ROLE=worker WORKER_COUNT=N``) le risorse sono
divise per N, così il totale dei processi motore resta limitato.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .config import Settings

__all__ = [
    "Resources",
    "detect",
    "compute_limits",
    "apply_autosize",
    "resource_status",
]


@dataclass
class Resources:
    cpu: int
    ram_total_mb: int
    ram_available_mb: int
    disk_free_mb: int
    disk_total_mb: int

    def to_dict(self) -> dict:
        return asdict(self)


def _meminfo() -> dict[str, int]:
    """Valori di /proc/meminfo in MB (vuoto se non disponibile)."""
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            if key.strip() in {"MemTotal", "MemAvailable"}:
                values[key.strip()] = int(rest.strip().split()[0]) // 1024
    except Exception:  # pragma: no cover - non-Linux
        pass
    return values


def detect(data_dir: str | Path | None = None) -> Resources:
    """Fotografia delle risorse della macchina."""
    cpu = os.cpu_count() or 2
    mem = _meminfo()
    ram_total = mem.get("MemTotal", 0)
    ram_avail = mem.get("MemAvailable", 0)
    disk_total = disk_free = 0
    try:
        usage = shutil.disk_usage(str(data_dir or Path.cwd()))
        disk_total = usage.total // (1024 * 1024)
        disk_free = usage.free // (1024 * 1024)
    except Exception:  # pragma: no cover - filesystem senza stat
        pass
    return Resources(cpu, ram_total, ram_avail, disk_free, disk_total)


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def compute_limits(res: Resources, settings: "Settings") -> dict:
    """Valori consigliati (prima delle divisioni per ruolo/worker)."""
    per_proc = max(128, settings.engine_memory_mb)
    if res.ram_available_mb:
        ram_budget = int(res.ram_available_mb * 0.7)
    else:  # RAM sconosciuta: si assume spazio per due processi
        ram_budget = per_proc * 2
    by_ram = max(1, ram_budget // per_proc)
    max_procs = max(1, min(res.cpu, by_ram))
    page_concurrency = max(1, min(max_procs, 3))
    workers = max(2, min(res.cpu, 8))
    return {
        "by_ram": by_ram,
        "max_engine_procs": max_procs,
        "page_concurrency": page_concurrency,
        "workers": workers,
    }


def apply_autosize(settings: "Settings") -> Resources:
    """Riempe i valori automatici e registra le risorse su ``settings``."""
    res = detect(settings.data_dir)
    limits = compute_limits(res, settings)

    divisor = 1
    if settings.role == "worker" and settings.worker_count > 1:
        divisor = settings.worker_count

    if not settings.max_engine_procs:
        settings.max_engine_procs = max(1, limits["max_engine_procs"] // divisor)
    if not settings.page_concurrency:
        settings.page_concurrency = max(
            1, min(settings.max_engine_procs, limits["page_concurrency"])
        )
    if not settings.workers:
        settings.workers = max(1, limits["workers"] // divisor)

    settings.resources = res.to_dict()
    return res


def resource_status(settings: "Settings") -> tuple[bool, str | None, Resources]:
    """Guardia: ``(ok, motivo, risorse)``. False se RAM/disco sono sotto soglia."""
    res = detect(settings.data_dir)
    if res.disk_free_mb and res.disk_free_mb < settings.min_free_disk_mb:
        return False, f"disco quasi pieno ({res.disk_free_mb} MB liberi)", res
    if res.ram_available_mb and res.ram_available_mb < settings.min_free_ram_mb:
        return False, f"RAM insufficiente ({res.ram_available_mb} MB disponibili)", res
    return True, None, res
