"""Wizard a righe: la TUI funziona anche senza Textual o su terminali minimi.

Usa le stesse funzioni headless della TUI (selezione, nomi, copia) e lo stesso
runner, quindi il risultato è identico: cambia solo la resa.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

from ..config import Settings
from ..engine import CloneEngine
from ..job_factory import build_engine, create_document_and_job
from ..models import ENGINES, LANGUAGES, JobState, RangeMode, normalize_engine
from ..pages import format_pages_label, parse_pages
from ..storage import Storage
from .i18n import T
from .jobs import OWNER_ID, copy_artifact, server_is_up, suggest_output_name
from .runner import TuiJobRunner


def _ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{label}{suffix}: ").strip()
    except EOFError:
        raise SystemExit(2) from None
    return answer or default


def _ask_yes(label: str, default: bool = True) -> bool:
    hint = "S/n" if default else "s/N"
    answer = _ask(f"{label} ({hint})", "s" if default else "n").lower()
    return answer.startswith("s") or answer.startswith("y")


def _ask_pdf() -> Path:
    while True:
        raw = _ask(T("fallback.pdf"))
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_file() or path.suffix.lower() != ".pdf":
            print(T("wizard.err.not_found", path=path))
            continue
        try:
            CloneEngine.page_count(path)
        except Exception as exc:  # noqa: BLE001
            print(T("wizard.err.unreadable", error=exc))
            continue
        return path


def _ask_pages(pdf: Path) -> list[int]:
    total = CloneEngine.page_count(pdf)
    while True:
        spec = _ask(T("fallback.pages"), "all")
        try:
            pages = parse_pages(spec, total)
        except ValueError as exc:
            print(T("wizard.err.bad_spec", error=exc))
            continue
        print(T("wizard.info.pages", count=len(pages), label=format_pages_label(pages)))
        return pages


def _ask_language(label: str, default: str, *, allow_auto: bool) -> str:
    codes = [c for c in LANGUAGES if allow_auto or c != "auto"]
    while True:
        code = _ask(label, default).strip().lower()
        if code in codes:
            return code
        print(f"{T('fallback.bad_choice')}: {', '.join(codes)}")


def _ask_engine() -> str:
    while True:
        code = normalize_engine(_ask(T("fallback.engine"), "google"))
        if code in ENGINES:
            return code
        print(f"{T('fallback.bad_choice')}: {', '.join(ENGINES)}")


def run(settings: Settings, storage: Storage) -> int:
    """Esegue il wizard a righe. Exit code: 0 ok, 1 parziale, 2 fatale."""
    print(T("fallback.intro"))
    pdf = _ask_pdf()
    pages = _ask_pages(pdf)
    src = _ask_language(T("fallback.src"), "auto", allow_auto=True)
    dst = _ask_language(T("fallback.dst"), "it", allow_auto=False)
    engine_name = _ask_engine()
    key = ""
    if engine_name == "llm" and not settings.openrouter_api_key:
        key = getpass.getpass(f"{T('fallback.key')}: ").strip()

    out_name = _ask(
        T("fallback.outname"), suggest_output_name(pdf, dst)
    ).strip()
    out_dir = Path(_ask(T("fallback.outdir"), str(Path.cwd()))).expanduser()
    while True:
        mode = _ask(T("fallback.mode"), "merged").strip().lower()
        if mode in {"merged", "single"}:
            break
        print(T("fallback.bad_choice"))

    summary = (
        f"{pdf.name} · {format_pages_label(pages)} · "
        f"{src} → {dst} · {engine_name} · {out_dir}"
    )
    if not _ask_yes(T("fallback.confirm", summary=summary)):
        print(T("fallback.aborted"))
        return 1

    if settings.require_terms_acceptance:
        print(T("wizard.err.terms"))
        return 2
    if server_is_up(settings):
        print(T("wizard.err.server_busy"))
        return 2

    engine = build_engine(settings, api_key=key or None)
    try:
        _document, job = create_document_and_job(
            storage,
            engine,
            pdf,
            pages_spec=format_pages_label(pages),
            src_lang=src,
            dst_lang=dst,
            engine_name=engine_name,
            output_name=out_name or None,
            range_mode=RangeMode(mode),
            owner_id=OWNER_ID,
            state=JobState.running,
            max_pages=settings.max_pages_total,
        )
    except ValueError as exc:
        print(T("fallback.failed", error=exc))
        engine.close()
        return 2

    def on_page(done, total, page, ok):
        status = "ok" if ok else "KO"
        print(T("fallback.page", page=page + 1, status=status), flush=True)

    runner = TuiJobRunner(
        storage=storage,
        engine=engine,
        job=job,
        settings=settings,
        on_page=on_page,
    )
    try:
        runner.start()
        while not runner.join(0.5):
            pass
        if runner.error:
            print(T("fallback.failed", error=runner.error), file=sys.stderr)
            return 1
        result = runner.result
        if result is None or result.cancelled or not result.artifact_path:
            print(T("fallback.failed", error=T("fallback.aborted")), file=sys.stderr)
            return 1
        dest = copy_artifact(result.artifact_path, out_dir)
        print(T("fallback.done", path=dest))
        return 1 if result.pages_failed else 0
    finally:
        engine.close()
