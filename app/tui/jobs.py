"""Logica headless della TUI.

Niente import di Textual: qui stanno le funzioni pure (selezione pagine,
anteprima testuale, nomi, riepiloghi, diagnostica) e le operazioni su disco.
Così i test restano veloci e le schermate possono cambiare senza toccarle.
"""

from __future__ import annotations

import logging
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import Settings
from ..engine import CloneEngine
from ..models import JobRecord, JobState, LANGUAGES, utcnow
from ..security import sanitize_stem
from ..storage import Storage
from .i18n import T

log = logging.getLogger("noesis.tui")

#: I job creati dalla TUI hanno questo proprietario: la Home mostra solo i
#: loro, e il recupero all'avvio tocca solo i loro (mai quelli del server).
OWNER_ID = "tui"

STATE_LABELS: dict[str, str] = {
    JobState.queued.value: "in coda",
    JobState.running.value: "in corso",
    JobState.done.value: "completato",
    JobState.error.value: "errore",
    JobState.cancelled.value: "annullato",
    JobState.interrupted.value: "interrotto",
}

#: Stati in cui il job non evolve più.
TERMINAL_STATES = frozenset(
    {JobState.done.value, JobState.error.value, JobState.cancelled.value,
     JobState.interrupted.value}
)


@dataclass(frozen=True)
class PagePreview:
    """Una pagina della selezione, come la vede l'utente."""

    page: int  # indice 0-based (motore)
    number: int  # numero fisico 1-based
    label: str  # etichetta /PageLabels, o il numero fisico
    text: str = ""

    @property
    def caption(self) -> str:
        if self.label and self.label != str(self.number):
            return T(
                "wizard.preview.physical_label",
                number=self.number,
                label=self.label,
            )
        return T("wizard.preview.physical", number=self.number)


def state_label(state: JobState | str) -> str:
    code = state.value if isinstance(state, JobState) else str(state)
    return STATE_LABELS.get(code, code)


def is_terminal(state: JobState | str) -> bool:
    code = state.value if isinstance(state, JobState) else str(state)
    return code in TERMINAL_STATES


def format_duration(ms: int | None) -> str:
    if not ms or ms < 0:
        return "—"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, secs = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes} min {secs:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


def format_when(moment: datetime | None) -> str:
    if moment is None:
        return "—"
    local = moment.astimezone() if moment.tzinfo else moment
    return local.strftime("%d/%m %H:%M")


def suggest_output_name(pdf: Path, dst_lang: str) -> str:
    """Nome proposto per l'output (senza estensione), come la CLI."""
    return sanitize_stem(f"{pdf.stem}_{dst_lang}", "output")


def language_name(code: str) -> str:
    return LANGUAGES.get(code, code)


def page_text(pdf: Path, page: int, *, max_chars: int = 200) -> str:
    """Prime righe di testo della pagina (best effort, mai un errore).

    Le pagine senza livello testuale (scansioni) ritornano stringa vuota: la
    UI lo dice, non fallisce.
    """
    try:
        import pymupdf
    except Exception:  # pragma: no cover - pymupdf è una dipendenza certa
        return ""
    try:
        with pymupdf.open(str(pdf)) as doc:
            if page < 0 or page >= doc.page_count:
                return ""
            raw = doc[page].get_text("text") or ""
    except Exception:  # noqa: BLE001 - anteprima accessoria
        return ""
    text = " ".join(raw.split())
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def preview_selection(
    pdf: Path, pages: list[int], *, max_chars: int = 200
) -> list[PagePreview]:
    """Prima e ultima pagina della selezione, con etichetta e prime righe."""
    if not pages:
        return []
    try:
        labels = CloneEngine.page_labels(pdf)
    except Exception:  # noqa: BLE001 - PDF illeggibile: la validazione lo dice
        labels = []
    chosen = [pages[0]] if len(pages) == 1 else [pages[0], pages[-1]]
    previews: list[PagePreview] = []
    for page in chosen:
        number = page + 1
        label = labels[page] if 0 <= page < len(labels) else str(number)
        previews.append(
            PagePreview(
                page=page,
                number=number,
                label=label,
                text=page_text(pdf, page, max_chars=max_chars),
            )
        )
    return previews


def preview_lines(previews: list[PagePreview]) -> list[str]:
    """Righe pronte per la UI (usate dal wizard)."""
    lines: list[str] = []
    for preview in previews:
        lines.append(preview.caption)
        lines.append(
            f"  {preview.text}" if preview.text
            else f"  {T('wizard.preview.none')}"
        )
    return lines


def summary_lines(
    *,
    job: JobRecord,
    pdf_name: str,
    out_dir: Path,
    pages_label: str,
) -> list[tuple[str, str]]:
    return [
        ("File", pdf_name),
        ("Pagine", f"{pages_label} ({job.pages_total})"),
        ("Lingue", f"{language_name(job.src_lang)} → {language_name(job.dst_lang)}"),
        ("Motore", job.engine),
        ("Uscita", f"{out_dir / job.output_name} · {'PDF unico' if job.range_mode.value == 'merged' else 'ZIP pagine singole'}"),
    ]


def unique_path(dest: Path) -> Path:
    """``dest`` se libero, altrimenti ``stem-2.ext``, ``stem-3.ext``…"""
    if not dest.exists():
        return dest
    for index in range(2, 1000):
        candidate = dest.with_name(f"{dest.stem}-{index}{dest.suffix}")
        if not candidate.exists():
            return candidate
    return dest.with_name(f"{dest.stem}-{int(time.time())}{dest.suffix}")


def copy_artifact(artifact_path: str | None, out_dir: Path) -> Path | None:
    """Copia l'artefatto nella cartella scelta dall'utente.

    Non sovrascrive mai un file esistente: aggiunge ``-2``, ``-3``… (la CLI
    sovrascrive, la TUI è usata da mani meno esperte).
    """
    if not artifact_path:
        return None
    src = Path(artifact_path)
    if not src.is_file():
        return None
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_path(out_dir / src.name)
    shutil.copy2(src, dest)
    return dest


def recover_stale_jobs(storage: Storage, *, owner_id: str = OWNER_ID) -> int:
    """Job della TUI rimasti ``running`` (processo morto) → ``interrupted``.

    Scrive anche ``finished`` e ``duration_ms``: senza, il janitor non li
    considererebbe perché ``Storage.old_jobs`` filtra su ``finished``.
    """
    count = 0
    for job in storage.jobs_by_state(JobState.running):
        if (job.owner_id or "") != owner_id:
            continue
        finished = utcnow()
        duration_ms = None
        if job.started is not None:
            try:
                duration_ms = max(0, int((finished - job.started).total_seconds() * 1000))
            except TypeError:  # pragma: no cover - naive/aware misti
                duration_ms = None
        storage.update_job(
            job.job_id,
            state=JobState.interrupted,
            error="interrotto: la TUI è stata chiusa",
            finished=finished,
            duration_ms=duration_ms,
        )
        count += 1
    return count


def cleanup_once(storage: Storage, settings: Settings) -> dict[str, int]:
    """Pulizia una tantum all'avvio (il server ha il suo janitor periodico)."""
    from ..janitor import Janitor

    try:
        return Janitor(storage, settings).cleanup()
    except Exception:  # noqa: BLE001 - mai bloccante per la UI
        log.warning("pulizia iniziale non riuscita", exc_info=True)
        return {"jobs": 0, "documents": 0}


def local_host(host: str) -> str:
    """Host raggiungibile dal browser quando il bind è su tutte le interfacce."""
    return "127.0.0.1" if host in {"", "0.0.0.0", "::", "[::]"} else host


def web_url(settings: Settings) -> str:
    return f"http://{local_host(settings.host)}:{settings.port}"


def server_is_up(settings: Settings, *, timeout: float = 0.7) -> bool:
    """Il server risponde su ``/api/v1/health``? (guardia anti co-esecuzione)."""
    url = f"{web_url(settings)}/api/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            return 200 <= int(getattr(response, "status", 0)) < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def doctor_rows(
    settings: Settings, *, engine_name: str = "llm"
) -> list[tuple[str, str, str]]:
    """Righe ``(stato, id, messaggio)`` della diagnostica runtime.

    ``want_free_checks=False``: i controlli sulla catena gratuita fanno rete e
    qui bastano motore, chiave, modello e ambiente.
    """
    from ..diagnostics import Status, build_context, run_all

    ctx = build_context(settings, engine_name=engine_name, want_free_checks=False)
    results = run_all(ctx)
    rows: list[tuple[str, str, str]] = []
    for result in results:
        detail = result.message or ""
        if result.fix:
            detail = f"{detail} — {result.fix}" if detail else result.fix
        rows.append((result.status, result.id, detail))
    if not rows:  # pragma: no cover - difensivo
        rows.append((Status.SKIP, "n/d", "nessun controllo eseguito"))
    return rows


def health_symbol(status: str) -> str:
    from ..diagnostics import Status

    return {
        Status.OK: "OK",
        Status.WARN: "!!",
        Status.FAIL: "XX",
        Status.SKIP: "--",
    }.get(status, "?")
