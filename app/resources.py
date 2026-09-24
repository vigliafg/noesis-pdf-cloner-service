"""Rilevamento risorse e autosizing.

Il servizio **si adatta alla macchina**: alla partenza calcola worker, concorrenza
per pagina e processi motore massimi in base a CPU, RAM disponibile e disco.
I valori espliciti via variabili d'ambiente hanno sempre la precedenza.

In deployment multi-processo (``ROLE=worker WORKER_COUNT=N``) le risorse sono
divise per N, così il totale dei processi motore resta limitato.

Nei **container** i limiti dei cgroup (memoria/CPU) hanno la precedenza sui
valori dell'host letti da ``/proc``: così l'autosizing non sovra-alloca.
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


# Percorsi dei cgroup (Linux). Moduli a livello di modulo per i test.
_CGROUP_V2 = Path("/sys/fs/cgroup")
_CGROUP_V1 = Path("/sys/fs/cgroup/memory")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except Exception:  # pragma: no cover - file assente/non leggibile
        return None


def _read_int(path: Path) -> int | None:
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _cgroup_memory() -> tuple[int, int]:
    """(total_mb, available_mb) dai limiti cgroup; ``(0, 0)`` se illimitati.

    Dentro un container ``/proc/meminfo`` riporta la RAM dell'**host**: per
    l'autosizing valgono i limiti del cgroup. Supporta cgroup v2
    (``memory.max``/``memory.current``) e, come fallback, cgroup v1.
    """
    raw = _read_text(_CGROUP_V2 / "memory.max")
    if raw and raw != "max":
        try:
            limit = int(raw)
        except ValueError:
            limit = 0
        if limit > 0:
            current = _read_int(_CGROUP_V2 / "memory.current") or 0
            return limit // (1024 * 1024), max(0, limit - current) // (1024 * 1024)
    # cgroup v1
    limit = _read_int(_CGROUP_V1 / "memory.limit_in_bytes")
    if limit and 0 < limit < (1 << 62):  # "illimitato" è un valore enorme
        usage = _read_int(_CGROUP_V1 / "memory.usage_in_bytes") or 0
        return limit // (1024 * 1024), max(0, limit - usage) // (1024 * 1024)
    return 0, 0


def _cgroup_cpu() -> int:
    """CPU effettive dal limite cgroup v2 (``cpu.max``); 0 se non limitate."""
    raw = _read_text(_CGROUP_V2 / "cpu.max")
    if not raw:
        return 0
    parts = raw.split()
    if len(parts) != 2 or parts[0] == "max":
        return 0
    try:
        quota, period = int(parts[0]), int(parts[1])
    except ValueError:
        return 0
    if quota <= 0 or period <= 0:
        return 0
    return max(1, (quota + period - 1) // period)


def detect(data_dir: str | Path | None = None) -> Resources:
    """Fotografia delle risorse (consapevole dei limiti cgroup dei container)."""
    cpu = os.cpu_count() or 2
    cgroup_cpu = _cgroup_cpu()
    if cgroup_cpu:
        cpu = min(cpu, cgroup_cpu)

    mem = _meminfo()
    ram_total = mem.get("MemTotal", 0)
    ram_avail = mem.get("MemAvailable", 0)
    cg_total, cg_avail = _cgroup_memory()
    if cg_total:
        # In un container /proc riporta l'host: prevalgono i limiti del cgroup.
        ram_total = cg_total if not ram_total else min(ram_total, cg_total)
        ram_avail = cg_avail if not ram_avail else min(ram_avail, cg_avail)

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
    """Riempe i valori automatici e registra le risorse su ``settings``.

    Con ``AUTOSIZE=false`` non si deduce nulla dalla macchina: i parametri
    lasciati a zero diventano ``1`` (nessun parallelismo automatico).
    """
    res = detect(settings.data_dir)
    limits = compute_limits(res, settings)

    divisor = 1
    if settings.role == "worker" and settings.worker_count > 1:
        divisor = settings.worker_count

    if not settings.autosize:
        if not settings.max_engine_procs:
            settings.max_engine_procs = 1
        if not settings.page_concurrency:
            settings.page_concurrency = 1
        if not settings.workers:
            settings.workers = 1
    else:
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
