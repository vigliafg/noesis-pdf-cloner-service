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
