"""Test dell'autosizing basato sulle risorse della macchina."""

from app.config import Settings
from app.resources import Resources, apply_autosize, compute_limits


def test_compute_limits_from_cpu_and_ram():
    settings = Settings(engine_memory_mb=1000)
    res = Resources(
        cpu=8, ram_total_mb=16000, ram_available_mb=8000,
        disk_free_mb=10000, disk_total_mb=50000,
    )
    limits = compute_limits(res, settings)
    # budget RAM = 0.7 * 8000 = 5600 → 5600 // 1000 = 5 processi
    assert limits["max_engine_procs"] == 5
    assert limits["page_concurrency"] == 3
    assert limits["workers"] == 8


def test_compute_limits_limited_by_ram():
    settings = Settings(engine_memory_mb=1000)
    res = Resources(
        cpu=16, ram_total_mb=2000, ram_available_mb=1000,
        disk_free_mb=100, disk_total_mb=1000,
    )
    limits = compute_limits(res, settings)
    assert limits["max_engine_procs"] == 1
    assert limits["page_concurrency"] == 1


def test_apply_autosize_fills_zeros(tmp_path):
    settings = Settings(
        data_dir=tmp_path, workers=0, page_concurrency=0, max_engine_procs=0
    )
    apply_autosize(settings)
    assert settings.workers >= 1
    assert settings.page_concurrency >= 1
    assert settings.max_engine_procs >= 1
    assert "cpu" in settings.resources


def test_apply_autosize_respects_explicit_values(tmp_path):
    settings = Settings(
        data_dir=tmp_path, workers=7, page_concurrency=2, max_engine_procs=3
    )
    apply_autosize(settings)
    assert (settings.workers, settings.page_concurrency, settings.max_engine_procs) == (
        7, 2, 3,
    )


def test_worker_count_divides_resources(tmp_path, monkeypatch):
    import app.resources as resources

    fixed = Resources(
        cpu=8, ram_total_mb=16000, ram_available_mb=8000,
        disk_free_mb=10000, disk_total_mb=50000,
    )
    monkeypatch.setattr(resources, "detect", lambda data_dir=None: fixed)
    settings = Settings(
        data_dir=tmp_path, role="worker", worker_count=4,
        workers=0, page_concurrency=0, max_engine_procs=0, engine_memory_mb=1000,
    )
    resources.apply_autosize(settings)
    # base: max_procs = min(8, 5) = 5 → /4 = 1 ; workers = 8 /4 = 2
    assert settings.max_engine_procs == 1
    assert settings.workers == 2


def test_detect_reads_cgroup_limits(tmp_path, monkeypatch):
    """In un container valgono i limiti cgroup, non le risorse dell'host."""
    import app.resources as resources

    cg = tmp_path / "cgroup"
    cg.mkdir()
    (cg / "memory.max").write_text(str(4 * 1024**3))      # 4 GiB
    (cg / "memory.current").write_text(str(1 * 1024**3))  # 1 GiB usati
    (cg / "cpu.max").write_text("200000 100000")          # 2 CPU
    monkeypatch.setattr(resources, "_CGROUP_V2", cg)
    monkeypatch.setattr(
        resources, "_meminfo",
        lambda: {"MemTotal": 64000, "MemAvailable": 50000},  # valori host
    )
    monkeypatch.setattr(resources.os, "cpu_count", lambda: 32)

    res = resources.detect(tmp_path)
    assert res.cpu == 2
    assert res.ram_total_mb == 4096
    assert res.ram_available_mb == 3072  # (4 - 1) GiB


def test_detect_ignores_unlimited_cgroup(tmp_path, monkeypatch):
    """Senza limiti cgroup si ricade su /proc e sulle CPU dell'host."""
    import app.resources as resources

    cg = tmp_path / "cgroup"
    cg.mkdir()
    (cg / "memory.max").write_text("max")
    (cg / "cpu.max").write_text("max 100000")
    monkeypatch.setattr(resources, "_CGROUP_V2", cg)
    monkeypatch.setattr(resources, "_CGROUP_V1", tmp_path / "assente")
    monkeypatch.setattr(
        resources, "_meminfo",
        lambda: {"MemTotal": 8000, "MemAvailable": 4000},
    )
    monkeypatch.setattr(resources.os, "cpu_count", lambda: 4)

    res = resources.detect(tmp_path)
    assert res.cpu == 4
    assert res.ram_total_mb == 8000
    assert res.ram_available_mb == 4000


def test_autosize_disabled_uses_minimums(tmp_path, monkeypatch):
    import app.resources as resources

    fixed = Resources(
        cpu=8, ram_total_mb=16000, ram_available_mb=8000,
        disk_free_mb=10000, disk_total_mb=50000,
    )
    monkeypatch.setattr(resources, "detect", lambda data_dir=None: fixed)
    settings = Settings(data_dir=tmp_path, autosize=False, engine_memory_mb=1000)
    resources.apply_autosize(settings)
    assert (
        settings.workers,
        settings.page_concurrency,
        settings.max_engine_procs,
    ) == (1, 1, 1)
