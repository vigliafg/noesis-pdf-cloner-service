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

# Motori di traduzione disponibili (identici alla versione desktop).
ENGINES: tuple[str, ...] = ("google", "bing", "openai")

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
    created: datetime


class MetaOut(BaseModel):
    engines: list[str]
    languages: dict[str, str]
    limits: dict[str, Any]
    features: dict[str, Any]


class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    engine_available: bool
    queue_length: int
    workers: int


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
