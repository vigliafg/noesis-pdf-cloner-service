"""Modelli dati: richieste/risposte API e record persistenti.

I record di database sono dataclass semplici (facili da mappare dalle righe
SQLite); le strutture esposte dall'API sono modelli pydantic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# Motori di traduzione disponibili.
# ``llm`` è il traduttore LLM: usa il percorso "OpenAI-compatibile" di
# pdf2zh_next (flag ``--openai``) puntato a OpenRouter (modello Mercury), NON
# OpenAI. L'alias storico ``openai`` è accettato e normalizzato a ``llm``.
ENGINES: tuple[str, ...] = ("google", "bing", "llm")
ENGINE_ALIASES: dict[str, str] = {"openai": "llm"}
ENGINE_LABELS: dict[str, str] = {
    "google": "Google",
    "bing": "Bing",
    "llm": "LLM (OpenRouter)",
}


def normalize_engine(engine: str) -> str:
    """Normalizza un id motore, accettando gli alias storici (``openai`` → ``llm``)."""
    code = (engine or "").strip().lower()
    return ENGINE_ALIASES.get(code, code)

# Lingue di traduzione: codice → endonimo mostrato nella UI.
LANGUAGES: dict[str, str] = {
    "auto": "Auto",
    "en": "English",
    "it": "Italiano",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
    "pt": "Português",
    "nl": "Nederlands",
    "pl": "Polski",
    "ru": "Русский",
    "zh": "中文",
    "ja": "日本語",
    "ko": "한국어",
    "ar": "العربية",
    "tr": "Türkçe",
}

# Stati del ciclo di vita di un job.
class JobState(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    error = "error"
    cancelled = "cancelled"
    interrupted = "interrupted"


# Modalità di emissione per un intervallo di pagine.
class RangeMode(str, Enum):
    merged = "merged"  # un unico PDF con tutte le pagine tradotte
    single = "single"  # pagine singole in un archivio ZIP


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════
#  API — richieste
# ═══════════════════════════════════════════════════════════════════════════


class JobRequest(BaseModel):
    """Richiesta di traduzione per un documento già caricato."""

    doc_id: str = Field(min_length=1)
    pages: str = "all"
    src_lang: str = "auto"
    dst_lang: str = "it"
    engine: str = "google"
    output_name: str | None = None
    range_mode: RangeMode = RangeMode.merged
    priority: int = 0
    # Versione dei Termini accettata dall'utente (per il gate di accettazione).
    terms_version: str | None = None
    # Chiave OpenRouter dell'utente (BYOK). Usata solo per questo job, mai
    # salvata su DB/log. Supportata con ROLE=all (API e worker nello stesso processo).
    llm_api_key: str | None = None


class EstimateRequest(BaseModel):
    """Richiesta di stima (tempo/costo) per una selezione di pagine."""

    doc_id: str = Field(min_length=1)
    pages: str = "all"
    src_lang: str = "auto"
    dst_lang: str = "it"
    engine: str = "google"


# ═══════════════════════════════════════════════════════════════════════════
#  API — risposte
# ═══════════════════════════════════════════════════════════════════════════


class PageRef(BaseModel):
    index: int  # indice fisico 0-based (usato dal motore)
    number: int  # numero fisico 1-based (mostrato all'utente)
    label: str  # etichetta stampata (/PageLabels), o numero fisico


class DocumentOut(BaseModel):
    doc_id: str
    filename: str
    page_count: int
    size_bytes: int
    page_labels: list[str]
    pages: list[PageRef]
    created: datetime


class JobOut(BaseModel):
    job_id: str
    doc_id: str
    state: JobState
    engine: str
    src_lang: str
    dst_lang: str
    output_name: str
    range_mode: RangeMode
    pages: list[int]  # 0-based
    pages_total: int
    pages_done: int
    pages_failed: int
    queue_position: int | None
    error: str | None
    download_url: str | None
    created: datetime
    started: datetime | None = None
    finished: datetime | None = None
    duration_ms: int | None = None


class JobSummary(BaseModel):
    job_id: str
    doc_id: str
    state: JobState
    engine: str
    dst_lang: str
    output_name: str
    pages_total: int
    pages_done: int
    pages_failed: int = 0
    # intervallo selezionato, in numerazione 1-based (per il chip di storico)
    page_first: int | None = None
    page_last: int | None = None
    pages_contiguous: bool = True
    range_mode: RangeMode = RangeMode.merged
    queue_position: int | None = None
    duration_ms: int | None = None
    created: datetime


class MetaOut(BaseModel):
    engines: list[str]
    engine_labels: dict[str, str]
    languages: dict[str, str]
    limits: dict[str, Any]
    features: dict[str, Any]
    terms_version: str = ""
    help_url: str = ""
    byok_supported: bool = True
    llm_model: str = ""
    terms_required: bool = False


class EstimateOut(BaseModel):
    doc_id: str
    engine: str
    src_lang: str
    dst_lang: str
    pages_total: int
    pages_cached: int
    pages_to_translate: int
    ms_per_page: int
    estimated_seconds: int
    cost_cents: float
    currency: str = "EUR"
    note: str | None = None


class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    engine_available: bool
    queue_length: int
    workers: int
    role: str = "all"
    engine_runnable: bool = True
    key_present: bool = False
    checks: list[dict] | None = None


# ═══════════════════════════════════════════════════════════════════════════
#  Record persistenti (SQLite)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class DocumentRecord:
    doc_id: str
    filename: str
    sha256: str
    page_count: int
    path: str
    page_labels: list[str] = field(default_factory=list)
    toc: list = field(default_factory=list)
    owner_id: str | None = None
    size_bytes: int = 0
    created: datetime = field(default_factory=utcnow)
    updated: datetime = field(default_factory=utcnow)


@dataclass
class JobRecord:
    job_id: str
    doc_id: str
    pages: list[int]
    src_lang: str = "auto"
    dst_lang: str = "it"
    engine: str = "google"
    output_name: str = ""
    range_mode: RangeMode = RangeMode.merged
    state: JobState = JobState.queued
    priority: int = 0
    pages_total: int = 0
    pages_done: int = 0
    pages_failed: int = 0
    queue_position: int | None = None
    error: str | None = None
    artifact_path: str | None = None
    owner_id: str | None = None
    created: datetime = field(default_factory=utcnow)
    started: datetime | None = None
    finished: datetime | None = None
    duration_ms: int | None = None

    def to_out(self, download_url: str | None = None) -> JobOut:
        return JobOut(
            job_id=self.job_id,
            doc_id=self.doc_id,
            state=self.state,
            engine=self.engine,
            src_lang=self.src_lang,
            dst_lang=self.dst_lang,
            output_name=self.output_name,
            range_mode=self.range_mode,
            pages=self.pages,
            pages_total=self.pages_total,
            pages_done=self.pages_done,
            pages_failed=self.pages_failed,
            queue_position=self.queue_position,
            error=self.error,
            download_url=download_url,
            created=self.created,
            started=self.started,
            finished=self.finished,
            duration_ms=self.duration_ms,
        )
