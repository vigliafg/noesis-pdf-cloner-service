"""Configurazione del servizio letta dall'ambiente.

Tutte le impostazioni sono centralizzate in :class:`Settings` e rilette da env
con :func:`get_settings`. I ``flag riservati`` (``AUTH_MODE``, ``QUOTA_*``,
``STRIPE_*``, ``FEATURE_*``) sono predisposti per le espansioni commerciali
future: oggi non alterano il comportamento.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _env_str(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None else value


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Impostazioni del servizio (immutabili per processo)."""

    # ── server ──────────────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 18080

    # ── percorsi ────────────────────────────────────────────────────────
    data_dir: Path = field(default_factory=lambda: _REPO_ROOT / "data")
    cache_root: Path | None = None  # None → data_dir/cache

    # ── esecuzione job ──────────────────────────────────────────────────
    workers: int = 0  # 0 → max(2, cpu)
    page_concurrency: int = 3
    max_engine_procs: int = 4
    page_timeout: int = 900  # secondi per pagina
    max_queue_size: int = 100
    max_pages_per_job: int = 200

    # ── upload / sicurezza ──────────────────────────────────────────────
    max_upload_mb: int = 500
    rate_limit_per_minute: int = 120
    rate_limit_jobs_per_hour: int = 60

    # ── retention ───────────────────────────────────────────────────────
    job_retention_hours: int = 72
    document_retention_hours: int = 24
    thumb_retention_hours: int = 168
    janitor_interval_seconds: int = 600

    # ── motore ──────────────────────────────────────────────────────────
    pdf2zh_bin: str = ""
    openrouter_api_key: str = ""
    llm_model: str = "inception/mercury-2.5"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    engine_cache_version: str = "1"

    # ── seam commerciali (no-op ora) ────────────────────────────────────
    auth_mode: str = "none"  # none | proxy | jwt
    trusted_proxy_headers: bool = False
    quota_enabled: bool = False
    quota_default_pages: int = 0  # 0 = illimitato
    feature_ocr: bool = False
    feature_payments: bool = False
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # ── derivati ────────────────────────────────────────────────────────
    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        if self.cache_root is None:
            self.cache_root = self.data_dir / "cache"
        else:
            self.cache_root = Path(self.cache_root)
        if not self.workers:
            self.workers = max(2, os.cpu_count() or 2)

    # ── percorsi derivati ───────────────────────────────────────────────
    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def jobs_log_dir(self) -> Path:
        return self.logs_dir / "jobs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobs.db"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.cache_root,
            self.documents_dir,
            self.thumbs_dir,
            self.artifacts_dir,
            self.logs_dir,
            self.jobs_log_dir,
        ):
            if path is not None:
                Path(path).mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "Settings":
        cache_root = _env_str("CACHE_ROOT") or None
        return cls(
            host=_env_str("HOST", "127.0.0.1"),
            port=_env_int("PORT", 18080),
            data_dir=Path(_env_str("DATA_DIR", str(_REPO_ROOT / "data"))),
            cache_root=Path(cache_root) if cache_root else None,
            workers=_env_int("WORKERS", 0),
            page_concurrency=_env_int("PAGE_CONCURRENCY", 3),
            max_engine_procs=_env_int("MAX_ENGINE_PROCS", 4),
            page_timeout=_env_int("PAGE_TIMEOUT", 900),
            max_queue_size=_env_int("MAX_QUEUE_SIZE", 100),
            max_pages_per_job=_env_int("MAX_PAGES_PER_JOB", 200),
            max_upload_mb=_env_int("MAX_UPLOAD_MB", 500),
            rate_limit_per_minute=_env_int("RATE_LIMIT_PER_MINUTE", 120),
            rate_limit_jobs_per_hour=_env_int("RATE_LIMIT_JOBS_PER_HOUR", 60),
            job_retention_hours=_env_int("JOB_RETENTION_HOURS", 72),
            document_retention_hours=_env_int("DOCUMENT_RETENTION_HOURS", 24),
            thumb_retention_hours=_env_int("THUMB_RETENTION_HOURS", 168),
            janitor_interval_seconds=_env_int("JANITOR_INTERVAL_SECONDS", 600),
            pdf2zh_bin=_env_str("PDF2ZH_BIN"),
            openrouter_api_key=_env_str("OPENROUTER_API_KEY"),
            llm_model=_env_str("PDF_LLM_MODEL", "inception/mercury-2.5"),
            llm_base_url=_env_str("PDF_LLM_BASE_URL", "https://openrouter.ai/api/v1"),
            engine_cache_version=_env_str("ENGINE_CACHE_VERSION", "1"),
            auth_mode=_env_str("AUTH_MODE", "none"),
            trusted_proxy_headers=_env_bool("TRUSTED_PROXY_HEADERS", False),
            quota_enabled=_env_bool("QUOTA_ENABLED", False),
            quota_default_pages=_env_int("QUOTA_DEFAULT_PAGES", 0),
            feature_ocr=_env_bool("FEATURE_OCR", False),
            feature_payments=_env_bool("FEATURE_PAYMENTS", False),
            stripe_secret_key=_env_str("STRIPE_SECRET_KEY"),
            stripe_webhook_secret=_env_str("STRIPE_WEBHOOK_SECRET"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings del processo (cache). Usa :func:`reset_settings` nei test."""
    settings = Settings.from_env()
    settings.ensure_dirs()
    return settings


def reset_settings() -> None:
    """Svuota la cache di :func:`get_settings` (utile nei test)."""
    get_settings.cache_clear()
