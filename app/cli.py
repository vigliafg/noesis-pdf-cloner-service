"""CLI headless: usa la stessa pipeline del server, senza avviare uvicorn.

Esempi::

    noesis-cloner ha22.pdf -p 100-103 --src en --dst it --engine google \\
        --output ha22_it --range-mode merged
    noesis-cloner report.pdf -p 3,5,10-12 --engine bing --range-mode single \\
        --out-dir ./out
    noesis-cloner *.pdf -p all --dst it --workers 2
    noesis-cloner ha22.pdf --list-pages

Exit code: 0 = tutto ok, 1 = fallimenti parziali, 2 = errore fatale.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

from . import __version__
from .config import Settings
from .engine import (
    ENGINES,
    CloneEngine,
    EngineError,
    TranslationCancelled,
    find_pdf2zh_bin,
)
from .logging_setup import configure_logging
from .models import (
    LANGUAGES,
    DocumentRecord,
    JobRecord,
    JobState,
    RangeMode,
    utcnow,
)
from .pages import format_pages_label, parse_pages
from .pipeline import run_job
from .security import sanitize_stem
from .storage import Storage

log = logging.getLogger("noesis.cli")


class CliLogger:
    """Logger di job per la CLI: stampa su stdout ed eventualmente su file."""

    def __init__(self, echo: bool = True, json_path: Path | None = None) -> None:
        self.echo = echo
        self.json_path = json_path
        self._lock = threading.Lock()
        if json_path is not None:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text("", encoding="utf-8")

    def event(self, stage, message, *, page=None, level="info", **extra):
        record = {"ts": time.time(), "level": level, "stage": stage, "message": message}
        if page is not None:
            record["page"] = page
        record.update(extra)
        with self._lock:
            if self.json_path is not None:
                with open(self.json_path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            if self.echo and level in {"warning", "error"}:
                tqdm.write(f"  ⚠ {message}")
        return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="noesis-cloner",
        description="Traduzione PDF con layout preservato (versione headless).",
    )
    parser.add_argument("files", nargs="*", type=Path, help="file PDF da tradurre")
    parser.add_argument(
        "-p", "--pages", default="all",
        help="pagine: 'all', '7', '100-103', '3,5,10-12' (default: all)",
    )
    parser.add_argument("--src", default="auto", help="lingua origine (default: auto)")
    parser.add_argument("--dst", default="it", help="lingua destinazione (default: it)")
    parser.add_argument("--engine", default="google", choices=list(ENGINES))
    parser.add_argument("-o", "--output", default=None, help="nome file di uscita (senza estensione)")
    parser.add_argument("--out-dir", type=Path, default=Path.cwd(), help="cartella di uscita")
    parser.add_argument(
        "--range-mode", choices=[m.value for m in RangeMode], default="merged",
        help="merged = unico PDF; single = ZIP di pagine singole",
    )
    parser.add_argument("--pages-concurrency", type=int, default=None, help="pagine in parallelo per job")
    parser.add_argument("--max-procs", type=int, default=None, help="processi pdf2zh_next simultanei")
    parser.add_argument("--workers", type=int, default=1, help="PDF processati in parallelo (batch)")
    parser.add_argument("--data-dir", type=Path, default=None, help="cartella dati (default: env DATA_DIR)")
    parser.add_argument("--cache-dir", type=Path, default=None, help="cartella cache (condivisa col server)")
    parser.add_argument("--force", action="store_true", help="ignora la cache e ritraduce le pagine")
    parser.add_argument("--log-json", type=Path, default=None, help="scrive il log degli eventi in JSONL")
    parser.add_argument("-v", "--verbose", action="store_true", help="log dettagliato")
    parser.add_argument("--check", action="store_true", help="verifica la presenza del motore ed esce")
    parser.add_argument("--list-langs", action="store_true", help="elenca le lingue disponibili")
    parser.add_argument("--list-engines", action="store_true", help="elenca i motori disponibili")
    parser.add_argument("--list-pages", action="store_true", help="stampa indice fisico → etichetta")
    # Seam: modalità remota (client dell'API), non ancora implementata.
    parser.add_argument("--server", default=None, help="[seam] URL del servizio remoto")
    parser.add_argument("--api-key", default=None, help="[seam] API key per il servizio remoto")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _settings_from_args(args) -> Settings:
    settings = Settings.from_env()
    if args.data_dir is not None:
        settings.data_dir = args.data_dir
        if args.cache_dir is None:
            settings.cache_root = settings.data_dir / "cache"
    if args.cache_dir is not None:
        settings.cache_root = args.cache_dir
    settings.__post_init__()
    if args.pages_concurrency is not None:
        settings.page_concurrency = max(1, args.pages_concurrency)
    if args.max_procs is not None:
        settings.max_engine_procs = max(1, args.max_procs)
    settings.ensure_dirs()
    return settings


def _make_engine(settings: Settings) -> CloneEngine:
    return CloneEngine(
        settings.cache_root,
        pdf2zh_bin=settings.pdf2zh_bin,
        max_engine_procs=settings.max_engine_procs,
        page_timeout=settings.page_timeout,
        cache_version=settings.engine_cache_version,
        llm_model=settings.llm_model,
        llm_base_url=settings.llm_base_url,
        api_key=settings.openrouter_api_key,
    )


def _register_document(storage: Storage, engine: CloneEngine, pdf: Path) -> DocumentRecord:
    doc_id = uuid.uuid4().hex
    doc_key = engine.doc_key(pdf)
    document = DocumentRecord(
        doc_id=doc_id,
        filename=pdf.name,
        sha256=doc_key,
        page_count=CloneEngine.page_count(pdf),
        path=str(pdf),
        page_labels=CloneEngine.page_labels(pdf),
        owner_id="cli",
        size_bytes=pdf.stat().st_size,
    )
    storage.create_document(document)
    return document


def _process_one(
    *,
    pdf: Path,
    args,
    settings: Settings,
    storage: Storage,
    logger: CliLogger,
    position: int,
) -> dict:
    """Traduce un PDF; ritorna un riepilogo."""
    engine = _make_engine(settings)
    document = _register_document(storage, engine, pdf)
    try:
        pages = parse_pages(args.pages, document.page_count)
    except ValueError as exc:
        raise EngineError(str(exc)) from exc
    if len(pages) > settings.max_pages_per_job:
        raise EngineError(f"troppe pagine (max {settings.max_pages_per_job})")

    stem = sanitize_stem(args.output or f"{pdf.stem}_{args.dst}", "output")
    job = JobRecord(
        job_id=uuid.uuid4().hex,
        doc_id=document.doc_id,
        pages=pages,
        src_lang=args.src,
        dst_lang=args.dst,
        engine=args.engine,
        output_name=stem,
        range_mode=RangeMode(args.range_mode),
        state=JobState.queued,
        pages_total=len(pages),
        owner_id="cli",
    )
    storage.create_job(job)

    if args.force:
        for page in pages:
            cached = engine.translated_path_for(
                document.sha256, page, job.engine, job.src_lang, job.dst_lang
            )
            cached.unlink(missing_ok=True)

    bar = tqdm(
        total=len(pages),
        desc=pdf.name[:30],
        unit="pag",
        position=position,
        leave=False,
        disable=not sys.stderr.isatty(),
    )

    def on_page_done(done, total, page, ok):
        bar.n = done + (0)
        bar.refresh()

    result = run_job(
        storage=storage,
        engine=engine,
        job=job,
        settings=settings,
        logger=logger,
        on_page_done=on_page_done,
        cancel_event=threading.Event(),
    )
    bar.close()

    out_path = None
    if result.artifact_path:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / Path(result.artifact_path).name
        shutil.copy2(result.artifact_path, out_path)

    return {
        "pdf": pdf,
        "pages_total": len(pages),
        "pages_done": result.pages_done,
        "pages_failed": result.pages_failed,
        "cancelled": result.cancelled,
        "output": out_path,
        "duration_ms": result.duration_ms,
    }


def _handle_utility(args, settings: Settings) -> int | None:
    if args.check:
        binary = find_pdf2zh_bin(settings.pdf2zh_bin)
        if binary:
            print(f"motore pdf2zh_next: {binary}")
            return 0
        print("motore pdf2zh_next NON trovato (installa .venv2 o imposta PDF2ZH_BIN)", file=sys.stderr)
        return 2
    if args.list_langs:
        for code, name in LANGUAGES.items():
            print(f"{code}\t{name}")
        return 0
    if args.list_engines:
        for engine in ENGINES:
            print(engine)
        return 0
    return None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(logging.DEBUG if args.verbose else logging.INFO)

    if args.server or args.api_key:
        print(
            "modalità remota (--server/--api-key) non ancora implementata: seam futuro",
            file=sys.stderr,
        )
        return 2

    settings = _settings_from_args(args)
    utility = _handle_utility(args, settings)
    if utility is not None:
        return utility

    if not args.files:
        parser.print_help()
        return 2

    files = [f for f in args.files]
    missing = [f for f in files if not f.is_file()]
    if missing:
        for f in missing:
            print(f"file non trovato: {f}", file=sys.stderr)
        return 2

    if args.list_pages:
        for pdf in files:
            engine = _make_engine(settings)
            count = CloneEngine.page_count(pdf)
            labels = CloneEngine.page_labels(pdf)
            print(f"# {pdf.name} ({count} pagine)")
            for index in range(count):
                print(f"{index + 1}\t{labels[index]}")
        return 0

    storage = Storage(settings)
    logger = CliLogger(echo=True, json_path=args.log_json)

    summaries: list[dict] = []
    fatal = False
    started = time.monotonic()
    workers = max(1, args.workers)
    overall = tqdm(total=len(files), desc="PDF", unit="file", disable=not sys.stderr.isatty())
    try:
        if workers == 1:
            for pdf in files:
                try:
                    summaries.append(
                        _process_one(
                            pdf=pdf, args=args, settings=settings,
                            storage=storage, logger=logger, position=1,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[{pdf.name}] errore: {exc}", file=sys.stderr)
                    fatal = True
                overall.update(1)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(
                        _process_one, pdf=pdf, args=args, settings=settings,
                        storage=storage, logger=logger, position=1,
                    ): pdf
                    for pdf in files
                }
                for future in as_completed(futures):
                    pdf = futures[future]
                    try:
                        summaries.append(future.result())
                    except Exception as exc:  # noqa: BLE001
                        print(f"[{pdf.name}] errore: {exc}", file=sys.stderr)
                        fatal = True
                    overall.update(1)
    finally:
        overall.close()
        storage.close()

    elapsed = time.monotonic() - started
    print("\n── Riepilogo ──")
    any_failed = fatal
    for summary in summaries:
        status = "OK" if summary["pages_failed"] == 0 and not summary["cancelled"] else "PARZIALE"
        if status != "OK":
            any_failed = True
        out = summary["output"] or "(nessun output)"
        print(
            f"[{status}] {summary['pdf'].name}: "
            f"{summary['pages_done']}/{summary['pages_total']} pagine "
            f"→ {out} ({summary['duration_ms'] / 1000:.1f}s)"
        )
    print(f"tempo totale: {elapsed:.1f}s")

    if fatal and not summaries:
        return 2
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
