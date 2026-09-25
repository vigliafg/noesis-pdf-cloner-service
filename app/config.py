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

from .envfile import config_path, parse_env_file

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(data_dir: Path) -> None:
    """Carica ``<data_dir>/noesis.env`` nell'ambiente, **senza** sovrascrivere.

    L'ambiente esplicito (shell, systemd ``Environment=``, Docker ``-e``) ha la
    precedenza. Un valore **vuoto** però conta come "non impostato": alcuni
    compose passano ``OPENROUTER_API_KEY=""`` quando la variabile non è definita,
    e non deve impedire al file di valere. Così il file di configurazione vale
    allo stesso modo per console, systemd, Docker e ``uvicorn`` diretto.
    """
    try:
        text = config_path(data_dir).read_text(encoding="utf-8")
    except OSError:
        return
    for key, value in parse_env_file(text).items():
        if not os.environ.get(key, "").strip():
            os.environ[key] = value


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


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    """Impostazioni del servizio (immutabili per processo)."""

    # ── server ──────────────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 18080

    # ── percorsi ────────────────────────────────────────────────────────
    data_dir: Path = field(default_factory=lambda: _REPO_ROOT / "data")
    cache_root: Path | None = None  # None → data_dir/cache

    # ── esecuzione job (0 = autosizing) ─────────────────────────────────
    workers: int = 0  # 0 → calcolato dalla macchina
    page_concurrency: int = 0
    max_engine_procs: int = 0
    page_timeout: int = 900  # secondi per pagina
    autosize: bool = True
    role: str = "all"  # all | api | worker
    worker_count: int = 1  # numero di processi worker (per la divisione risorse)
    queue_backend: str = "db"  # db | memory
    engine_memory_mb: int = 800  # stima RAM per processo pdf2zh_next
    min_free_disk_mb: int = 1024
    min_free_ram_mb: int = 512
    resources: dict = field(default_factory=dict)  # rilevate all'avvio
    max_queue_size: int = 100
    max_pages_per_block: int = 100  # blocco di pagine elaborato per volta
    max_pages_total: int = 5000  # limite complessivo di pagine per job

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
    # Rifiuta a monte un job LLM senza chiave (evita che fallisca in coda).
    preflight_guard: bool = True

    # ── stima tempo/costo (0 = usa i default interni) ───────────────────
    estimate_ms_per_page: dict = field(
        default_factory=lambda: {"google": 0, "bing": 0, "llm": 0}
    )  # engine → ms (0 = default interno)
    # Prezzo commerciale per pagina (centesimi). Default 0 = servizio gratuito:
    # per il motore LLM la stima mostra il costo *stimato* che l'utente paga sul
    # proprio account OpenRouter (BYOK). Imposta >0 solo per un'offerta a
    # pagamento (il codice commerciale resta disponibile).
    cost_cents_per_page: dict = field(
        default_factory=lambda: {"google": 0, "bing": 0, "llm": 0}
    )

    # Modello di costo LLM (Mercury/OpenRouter), prezzi USD per milione di token.
    # Il fattore di overhead cattura i prompt ripetuti per chunk da pdf2zh_next
    # (calibrato empiricamente: vedi README "Stima del costo").
    llm_price_prompt_per_mtok: float = 0.04
    llm_price_completion_per_mtok: float = 0.15
    llm_overhead_factor: float = 13.3
    llm_output_ratio: float = 1.09  # caratteri tradotti / caratteri sorgente
    chars_per_token: float = 4.0
    estimate_sample_pages: int = 12

    # ── seam commerciali (no-op ora) ────────────────────────────────────
    auth_mode: str = "none"  # none | proxy | jwt
    trusted_proxy_headers: bool = False
    quota_enabled: bool = False
    quota_default_pages: int = 0  # 0 = illimitato
    feature_ocr: bool = False
    feature_payments: bool = False
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # ── frontend / documenti legali ─────────────────────────────────────
    help_url: str = "https://vigliafg.github.io/noesis-pdf-cloner-service/"
    terms_version: str = "1.0"
    # Richiede l'accettazione dei Termini (versione corrente) per creare un job.
    require_terms_acceptance: bool = False

    # Chiavi presenti nell'ambiente **prima** di leggere ``noesis.env``: la
    # pagina di configurazione le usa per dire se un valore arriva dalla shell,
    # da systemd o da Docker invece che dal file.
    shell_env_keys: frozenset = field(default_factory=frozenset)

    # ── derivati ────────────────────────────────────────────────────────
    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        if self.cache_root is None:
            self.cache_root = self.data_dir / "cache"
        else:
            self.cache_root = Path(self.cache_root)

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
        data_dir = Path(_env_str("DATA_DIR", str(_REPO_ROOT / "data")))
        # Il file di configurazione vale per tutti i modi di avvio; l'ambiente
        # esplicito resta più forte (vedi ``_load_env_file``).
        shell_before = frozenset(os.environ)
        _load_env_file(data_dir)
        cache_root = _env_str("CACHE_ROOT") or None
        settings = cls(
            host=_env_str("HOST", "127.0.0.1"),
            port=_env_int("PORT", 18080),
            data_dir=data_dir,
            cache_root=Path(cache_root) if cache_root else None,
            workers=_env_int("WORKERS", 0),
            page_concurrency=_env_int("PAGE_CONCURRENCY", 0),
            max_engine_procs=_env_int("MAX_ENGINE_PROCS", 0),
            page_timeout=_env_int("PAGE_TIMEOUT", 900),
            autosize=_env_bool("AUTOSIZE", True),
            role=_env_str("ROLE", "all"),
            worker_count=_env_int("WORKER_COUNT", 1),
            queue_backend=_env_str("QUEUE_BACKEND", "db"),
            engine_memory_mb=_env_int("ENGINE_MEMORY_MB", 800),
            min_free_disk_mb=_env_int("MIN_FREE_DISK_MB", 1024),
            min_free_ram_mb=_env_int("MIN_FREE_RAM_MB", 512),
            max_queue_size=_env_int("MAX_QUEUE_SIZE", 100),
            max_pages_per_block=_env_int("MAX_PAGES_PER_BLOCK", 100),
            max_pages_total=_env_int("MAX_PAGES_TOTAL", 5000),
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
            preflight_guard=_env_bool("PREFLIGHT_GUARD", True),
            estimate_ms_per_page={
                "google": _env_int("ESTIMATE_MS_PER_PAGE_GOOGLE", 0),
                "bing": _env_int("ESTIMATE_MS_PER_PAGE_BING", 0),
                "llm": _env_int(
                    "ESTIMATE_MS_PER_PAGE_LLM",
                    _env_int("ESTIMATE_MS_PER_PAGE_OPENAI", 0),
                ),
            },
            cost_cents_per_page={
                "google": _env_int("COST_CENTS_PER_PAGE_GOOGLE", 0),
                "bing": _env_int("COST_CENTS_PER_PAGE_BING", 0),
                "llm": _env_int(
                    "COST_CENTS_PER_PAGE_LLM",
                    _env_int("COST_CENTS_PER_PAGE_OPENAI", 0),
                ),
            },
            llm_price_prompt_per_mtok=_env_float("LLM_PRICE_PROMPT_PER_MTOK", 0.04),
            llm_price_completion_per_mtok=_env_float("LLM_PRICE_COMPLETION_PER_MTOK", 0.15),
            llm_overhead_factor=_env_float("LLM_OVERHEAD_FACTOR", 13.3),
            llm_output_ratio=_env_float("LLM_OUTPUT_RATIO", 1.09),
            chars_per_token=_env_float("CHARS_PER_TOKEN", 4.0),
            estimate_sample_pages=_env_int("ESTIMATE_SAMPLE_PAGES", 12),
            auth_mode=_env_str("AUTH_MODE", "none"),
            trusted_proxy_headers=_env_bool("TRUSTED_PROXY_HEADERS", False),
            quota_enabled=_env_bool("QUOTA_ENABLED", False),
            quota_default_pages=_env_int("QUOTA_DEFAULT_PAGES", 0),
            feature_ocr=_env_bool("FEATURE_OCR", False),
            feature_payments=_env_bool("FEATURE_PAYMENTS", False),
            stripe_secret_key=_env_str("STRIPE_SECRET_KEY"),
            stripe_webhook_secret=_env_str("STRIPE_WEBHOOK_SECRET"),
            help_url=_env_str(
                "HELP_URL",
                "https://vigliafg.github.io/noesis-pdf-cloner-service/",
            ),
            terms_version=_env_str("TERMS_VERSION", "1.0"),
            require_terms_acceptance=_env_bool("REQUIRE_TERMS_ACCEPTANCE", False),
        )
        settings.shell_env_keys = shell_before
        from .resources import apply_autosize

        apply_autosize(settings)
        return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings del processo (cache). Usa :func:`reset_settings` nei test."""
    settings = Settings.from_env()
    settings.ensure_dirs()
    return settings


def reset_settings() -> None:
    """Svuota la cache di :func:`get_settings` (utile nei test)."""
    get_settings.cache_clear()
