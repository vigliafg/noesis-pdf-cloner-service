"""Persistenza: repository SQLite + percorsi del filesystem.

``Storage`` è la fonte di verità dei job (la coda — su DB o in memoria — si
appoggia a questa) e gestisce anche le posizioni dei file (documenti, thumbnail,
artefatti, log). È pensato per essere sostituito in futuro da un repository
Postgres/S3 senza toccare il resto del codice.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .migrations import apply_migrations
from .models import DocumentRecord, JobRecord, JobState, RangeMode, utcnow


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class Storage:
    """Repository SQLite + layout su disco."""

    _JOB_COLUMNS = {
        "pages", "src_lang", "dst_lang", "engine", "output_name", "range_mode",
        "state", "priority", "pages_total", "pages_done", "pages_failed",
        "queue_position", "error", "artifact_path", "started",
        "finished", "duration_ms",
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_dirs()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(settings.db_path), check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(self._conn)

    # ── lifecycle ────────────────────────────────────────────────────────
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── documenti ────────────────────────────────────────────────────────
    def create_document(self, doc: DocumentRecord) -> DocumentRecord:
        with self._lock:
            self._conn.execute(
                """INSERT INTO documents
                   (doc_id, filename, sha256, page_count, path, page_labels,
                    toc, owner_id, size_bytes, created, updated)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    doc.doc_id, doc.filename, doc.sha256, doc.page_count,
                    doc.path, _json(doc.page_labels), _json(doc.toc),
                    doc.owner_id, doc.size_bytes, _iso(doc.created),
                    _iso(doc.updated),
                ),
            )
            self._conn.commit()
        return doc

    def get_document(self, doc_id: str) -> DocumentRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM documents WHERE doc_id=?", (doc_id,)
            ).fetchone()
        return self._row_to_document(row) if row else None

    def list_documents(self, owner_id: str | None = None) -> list[DocumentRecord]:
        query = "SELECT * FROM documents"
        params: tuple = ()
        if owner_id is not None:
            query += " WHERE owner_id=?"
            params = (owner_id,)
        query += " ORDER BY created DESC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_document(r) for r in rows]

    def delete_document(self, doc_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))
            self._conn.commit()

    def _row_to_document(self, row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            doc_id=row["doc_id"],
            filename=row["filename"],
            sha256=row["sha256"],
            page_count=row["page_count"],
            path=row["path"],
            page_labels=_loads(row["page_labels"], []),
            toc=_loads(row["toc"], []),
            owner_id=row["owner_id"],
            size_bytes=row["size_bytes"],
            created=_parse(row["created"]) or utcnow(),
            updated=_parse(row["updated"]) or utcnow(),
        )

    # ── job ──────────────────────────────────────────────────────────────
    def create_job(self, job: JobRecord) -> JobRecord:
        with self._lock:
            self._conn.execute(
                """INSERT INTO jobs
                   (job_id, doc_id, pages, src_lang, dst_lang, engine,
                    output_name, range_mode, state, priority, pages_total,
                    pages_done, pages_failed, queue_position, error,
                    artifact_path, owner_id, created, started,
                    finished, duration_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job.job_id, job.doc_id, _json(job.pages), job.src_lang,
                    job.dst_lang, job.engine, job.output_name,
                    job.range_mode.value, job.state.value, job.priority,
                    job.pages_total, job.pages_done, job.pages_failed,
                    job.queue_position, job.error, job.artifact_path,
                    job.owner_id, _iso(job.created),
                    _iso(job.started), _iso(job.finished), job.duration_ms,
                ),
            )
            self._conn.commit()
        return job

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(
        self, limit: int = 50, owner_id: str | None = None
    ) -> list[JobRecord]:
        query = "SELECT * FROM jobs"
        params: list[Any] = []
        if owner_id is not None:
            query += " WHERE owner_id=?"
            params.append(owner_id)
        query += " ORDER BY created DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_job(r) for r in rows]

    def update_job(self, job_id: str, **fields: Any) -> None:
        updates = {k: v for k, v in fields.items() if k in self._JOB_COLUMNS}
        if not updates:
            return
        encoded: dict[str, Any] = {}
        for key, value in updates.items():
            if key == "pages":
                encoded[key] = _json(value)
            elif key == "range_mode":
                encoded[key] = value.value if isinstance(value, RangeMode) else value
            elif key == "state":
                encoded[key] = value.value if isinstance(value, JobState) else value
            elif key in {"started", "finished"}:
                encoded[key] = _iso(value)
            else:
                encoded[key] = value
        assignments = ", ".join(f"{k}=?" for k in encoded)
        with self._lock:
            self._conn.execute(
                f"UPDATE jobs SET {assignments} WHERE job_id=?",
                (*encoded.values(), job_id),
            )
            self._conn.commit()

    def jobs_by_state(self, state: JobState) -> list[JobRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE state=? ORDER BY priority DESC, created",
                (state.value,),
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def count_jobs_by_state(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT state, COUNT(*) AS n FROM jobs GROUP BY state"
            ).fetchall()
        return {r["state"]: r["n"] for r in rows}

    # ── coda su database (multi-processo) ────────────────────────────────
    def claim_next_job(self) -> JobRecord | None:
        """Reclama atomicamente il prossimo job in coda (sicuro tra processi)."""
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError:  # un altro writer è attivo
                return None
            try:
                row = self._conn.execute(
                    "SELECT job_id FROM jobs WHERE state=? "
                    "ORDER BY priority DESC, created, job_id LIMIT 1",
                    (JobState.queued.value,),
                ).fetchone()
                if row is None:
                    self._conn.commit()
                    return None
                job_id = row["job_id"]
                updated = self._conn.execute(
                    "UPDATE jobs SET state=?, started=?, queue_position=NULL "
                    "WHERE job_id=? AND state=?",
                    (JobState.running.value, _iso(utcnow()), job_id, JobState.queued.value),
                )
                if updated.rowcount != 1:
                    self._conn.rollback()
                    return None
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            return self.get_job(job_id)

    def pending_count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE state=?",
                (JobState.queued.value,),
            ).fetchone()
        return int(row["n"] or 0)

    def queue_position(self, job_id: str) -> int | None:
        """Posizione (1-based) nella coda dei job in attesa."""
        with self._lock:
            job = self.get_job(job_id)
            if job is None or job.state is not JobState.queued:
                return None
            row = self._conn.execute(
                """SELECT COUNT(*) AS n FROM jobs
                   WHERE state=? AND (
                       priority > ? OR
                       (priority = ? AND (created < ? OR (created = ? AND job_id < ?)))
                   )""",
                (
                    JobState.queued.value, job.priority, job.priority,
                    _iso(job.created), _iso(job.created), job.job_id,
                ),
            ).fetchone()
        return int(row["n"] or 0) + 1

    def request_cancel(self, job_id: str) -> bool:
        """Segna il job come da annullare (funziona anche tra processi)."""
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET cancel_requested=1 WHERE job_id=?", (job_id,)
            )
            self._conn.execute(
                "UPDATE jobs SET state=?, error=? WHERE job_id=? AND state=?",
                (
                    JobState.cancelled.value,
                    "annullato prima dell'esecuzione",
                    job_id,
                    JobState.queued.value,
                ),
            )
            self._conn.commit()
        return True

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT cancel_requested FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return bool(row and row["cancel_requested"])

    def clear_cancel(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET cancel_requested=0 WHERE job_id=?", (job_id,)
            )
            self._conn.commit()

    def engine_speed(self, engine: str, min_pages: int = 3) -> tuple[int, int]:
        """Velocità media storica (ms/pagina, pagine campionate) per motore.

        Ritorna ``(ms_per_page, samples)``; ``ms_per_page`` è 0 se i dati sono
        insufficienti (in tal caso si usa una stima di default).
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(pages),0) AS p, "
                "COALESCE(SUM(duration_ms),0) AS d FROM usage "
                "WHERE engine=? AND duration_ms IS NOT NULL",
                (engine,),
            ).fetchone()
        pages = int(row["p"] or 0)
        duration = int(row["d"] or 0)
        if pages >= min_pages and duration > 0:
            return max(1, duration // pages), pages
        return 0, pages

    def _row_to_job(self, row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            doc_id=row["doc_id"],
            pages=_loads(row["pages"], []),
            src_lang=row["src_lang"],
            dst_lang=row["dst_lang"],
            engine=row["engine"],
            output_name=row["output_name"],
            range_mode=RangeMode(row["range_mode"]),
            state=JobState(row["state"]),
            priority=row["priority"],
            pages_total=row["pages_total"],
            pages_done=row["pages_done"],
            pages_failed=row["pages_failed"],
            queue_position=row["queue_position"],
            error=row["error"],
            artifact_path=row["artifact_path"],
            owner_id=row["owner_id"],
            created=_parse(row["created"]) or utcnow(),
            started=_parse(row["started"]),
            finished=_parse(row["finished"]),
            duration_ms=row["duration_ms"],
        )

    # ── usage / audit / email (seam) ─────────────────────────────────────
    def add_usage(
        self,
        *,
        job_id: str | None,
        doc_id: str | None,
        actor_id: str | None,
        engine: str | None,
        pages: int,
        chars: int = 0,
        tokens: int = 0,
        duration_ms: int | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO usage
                   (ts, job_id, doc_id, actor_id, engine, pages, chars,
                    tokens, duration_ms)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    _iso(utcnow()), job_id, doc_id, actor_id, engine, pages,
                    chars, tokens, duration_ms,
                ),
            )
            self._conn.commit()

    def usage_totals(self, actor_id: str | None = None) -> dict[str, int]:
        query = "SELECT COALESCE(SUM(pages),0) AS pages FROM usage"
        params: tuple = ()
        if actor_id is not None:
            query += " WHERE actor_id=?"
            params = (actor_id,)
        with self._lock:
            row = self._conn.execute(query, params).fetchone()
        return {"pages": int(row["pages"] or 0)}

    def add_audit(
        self,
        *,
        actor_id: str | None,
        action: str,
        resource: str | None = None,
        meta: dict | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit(ts, actor_id, action, resource, meta) "
                "VALUES (?,?,?,?,?)",
                (_iso(utcnow()), actor_id, action, resource, _json(meta or {})),
            )
            self._conn.commit()

    def add_email(
        self, recipient: str, subject: str, body: str, status: str = "logged"
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO emails(ts, recipient, subject, body, status) "
                "VALUES (?,?,?,?,?)",
                (_iso(utcnow()), recipient, subject, body, status),
            )
            self._conn.commit()

    # ── manutenzione / retention ─────────────────────────────────────────
    def old_jobs(self, hours: int) -> list[JobRecord]:
        threshold = _iso(utcnow() - timedelta(hours=hours))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE finished IS NOT NULL AND finished < ?",
                (threshold,),
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def old_documents(self, hours: int) -> list[DocumentRecord]:
        threshold = _iso(utcnow() - timedelta(hours=hours))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM documents WHERE created < ?", (threshold,)
            ).fetchall()
        return [self._row_to_document(r) for r in rows]

    # ── percorsi filesystem ──────────────────────────────────────────────
    def document_path(self, doc_id: str) -> Path:
        return self.settings.documents_dir / f"{doc_id}.pdf"

    def thumb_dir(self, doc_key: str) -> Path:
        return self.settings.thumbs_dir / doc_key

    def thumb_path(self, doc_key: str, page: int, width: int | None = None) -> Path:
        """Percorso della miniatura cachata.

        La larghezza fa parte della chiave: senza di essa una richiesta ``w=800``
        riceverebbe la miniatura da 180px già cachata (sfocata).
        """
        name = f"page_{page:06d}.png" if width is None else f"page_{page:06d}_w{int(width):04d}.png"
        return self.thumb_dir(doc_key) / name

    def artifact_dir(self, job_id: str) -> Path:
        return self.settings.artifacts_dir / job_id

    def job_cover_path(self, job_id: str) -> Path:
        """Copertina della tessera di storico: prima pagina del documento.

        Il nome porta la pagina sorgente: se in futuro cambia cosa mostriamo,
        il file vecchio resta orfano invece di essere servito a sproposito.
        """
        return self.artifact_dir(job_id) / "cover_page1.png"

    def job_log_path(self, job_id: str) -> Path:
        return self.settings.jobs_log_dir / f"{job_id}.jsonl"
