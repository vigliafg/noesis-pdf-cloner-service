"""Motore di clonazione headless (adattato da ``noesis-pdf-cloner``).

Differenze rispetto alla versione desktop:

- stato **per documento** (niente variabili globali): più job in parallelo;
- ``doc_key`` = SHA-256 del contenuto (gli upload possono avere nomi uguali);
- cache **versionata** (schema + versione motore + modello) con scritture
  **atomiche** e **lock inter-processo** (CLI e server possono condividerla);
- subprocess in un **process group** così il cancel può terminarlo;
- ``render_thumb`` e ``page_labels`` per l'anteprima.

Motori disponibili (identici al desktop):

* ``google``  → catena gratuita ``gtranslate_cli.py`` via ``--clitranslator``
* ``bing``    → traduttore Bing built-in di pdf2zh_next
* ``llm``     → LLM via OpenRouter (flag pdf2zh ``--openai``; modello Mercury).
                 L'alias ``openai`` è accettato e normalizzato a ``llm``.
"""

from __future__ import annotations

import contextlib
import glob
import hashlib
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Iterator

from .metrics import ENGINE_PROCS, METRICS
from .models import normalize_engine
from .pagelabels import build_page_labels

log = logging.getLogger("noesis.engine")

ENGINES: tuple[str, ...] = ("google", "bing", "llm")
CACHE_SCHEMA_VERSION = "1"
DEFAULT_MODEL = "inception/mercury-2.5"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_PAGE_TIMEOUT = 900  # secondi per pagina densa (pdf2zh + BabelDOC)


# ── eccezioni ───────────────────────────────────────────────────────────────


class EngineError(RuntimeError):
    """Errore generico del motore."""


class EngineNotFoundError(EngineError):
    """pdf2zh_next non trovato."""


class TranslationCancelled(EngineError):
    """Traduzione annullata dall'utente."""


# ── localizzazione dell'eseguibile ──────────────────────────────────────────


def _is_windows() -> bool:
    return os.name == "nt"


def _bin_name(base: str) -> str:
    return f"{base}.exe" if _is_windows() else base


def _candidate_pdf2zh() -> list[Path]:
    here = Path(__file__).resolve().parent
    roots = [here.parent, Path.cwd()]
    roots.extend([here.parent.parent / "pdfcloner", here.parent.parent / "noesis-pdf-cloner"])
    exe = _bin_name("pdf2zh_next")
    candidates: list[Path] = []
    for root in roots:
        candidates.append(root / ".venv2" / "bin" / exe)
        candidates.append(root / ".venv2" / "Scripts" / exe)
    return candidates


def find_pdf2zh_bin(override: str | Path | None = None) -> Path | None:
    """Priorità: override → env ``PDF2ZH_BIN`` → ``.venv2`` accanto al repo."""
    seen: set[str] = set()
    ordered: list[Path] = []
    if override:
        ordered.append(Path(override).expanduser())
    env = os.environ.get("PDF2ZH_BIN")
    if env:
        ordered.append(Path(env).expanduser())
    ordered.extend(_candidate_pdf2zh())
    for cand in ordered:
        key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        if cand.is_file():
            return cand
    return None


def venv_python_for(pdf2zh_bin: Path) -> str:
    bin_dir = pdf2zh_bin.parent
    for name in (_bin_name("python"), _bin_name("python3")):
        candidate = bin_dir / name
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def _gtranslate_cli_path() -> Path:
    return Path(__file__).resolve().with_name("gtranslate_cli.py")


# ── semaforo globale sui processi motore ────────────────────────────────────

_SEM_LOCK = threading.Lock()
_SEMAPHORE: threading.BoundedSemaphore | None = None
_SEM_SIZE = 0


def get_engine_semaphore(max_procs: int) -> threading.BoundedSemaphore:
    """Semaforo condiviso (per processo) che limita i pdf2zh_next simultanei."""
    global _SEMAPHORE, _SEM_SIZE
    size = max(1, int(max_procs))
    with _SEM_LOCK:
        if _SEMAPHORE is None or _SEM_SIZE != size:
            _SEMAPHORE = threading.BoundedSemaphore(size)
            _SEM_SIZE = size
    return _SEMAPHORE


# ── lock inter-processo ─────────────────────────────────────────────────────

try:  # pragma: no cover - dipende dalla piattaforma
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]


@contextlib.contextmanager
def interprocess_lock(target: Path) -> Iterator[None]:
    """Lock esclusivo su file, per coordinare processi diversi sulla cache."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = open(target, "a+")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


# ── engine ──────────────────────────────────────────────────────────────────


class CloneEngine:
    """Pipeline split → pdf2zh_next → cache, per documento ed engine."""

    def __init__(
        self,
        cache_root: str | Path,
        *,
        pdf2zh_bin: str | Path | None = None,
        max_engine_procs: int = 4,
        page_timeout: int = DEFAULT_PAGE_TIMEOUT,
        cache_version: str = "1",
        llm_model: str = DEFAULT_MODEL,
        llm_base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
    ) -> None:
        self.cache_root = Path(cache_root)
        self.split_root = self.cache_root / "split"
        self.translated_root = self.cache_root / "translated"
        self._pdf2zh_override = str(pdf2zh_bin) if pdf2zh_bin else ""
        self._pdf2zh_bin: Path | None = None
        self.max_engine_procs = max(1, int(max_engine_procs))
        self.page_timeout = int(page_timeout)
        self.cache_version = cache_version
        self.llm_model = llm_model
        self.llm_base_url = llm_base_url
        self.api_key = api_key or ""
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._doc_key_cache: dict[tuple, str] = {}
        self.split_root.mkdir(parents=True, exist_ok=True)
        self.translated_root.mkdir(parents=True, exist_ok=True)

    # ── documento ────────────────────────────────────────────────────────
    @staticmethod
    def compute_doc_key(path: str | Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def doc_key(self, path: str | Path) -> str:
        p = Path(path)
        try:
            st = p.stat()
            key = (str(p), st.st_size, st.st_mtime_ns)
        except OSError:
            return self.compute_doc_key(p)
        cached = self._doc_key_cache.get(key)
        if cached:
            return cached
        value = self.compute_doc_key(p)
        self._doc_key_cache[key] = value
        return value

    def pdf2zh_bin(self) -> Path | None:
        if self._pdf2zh_bin is None or not self._pdf2zh_bin.is_file():
            self._pdf2zh_bin = find_pdf2zh_bin(self._pdf2zh_override)
        return self._pdf2zh_bin

    def available(self) -> bool:
        return self.pdf2zh_bin() is not None

    # ── percorsi cache ───────────────────────────────────────────────────
    def _version_tag(self) -> str:
        tag = f"cs{CACHE_SCHEMA_VERSION}-e{self.cache_version}"
        if self.api_key:  # il modello LLM incide sul risultato
            tag += "-" + hashlib.sha1(self.llm_model.encode()).hexdigest()[:8]
        return tag

    def split_path(self, doc_key: str, page: int) -> Path:
        return self.split_root / doc_key / f"page_{page:06d}.pdf"

    def translated_path_for(
        self,
        doc_key: str,
        page: int,
        engine: str,
        lang_in: str,
        lang_out: str,
    ) -> Path:
        return (
            self.translated_root
            / doc_key
            / engine
            / f"{lang_in}-{lang_out}"
            / self._version_tag()
            / f"page_{page:06d}.pdf"
        )

    def is_cached(self, doc_key, page, engine, lang_in, lang_out) -> bool:
        return self.translated_path_for(doc_key, page, engine, lang_in, lang_out).is_file()

    def cached_pages(
        self, doc_key, pages, engine, lang_in, lang_out
    ) -> list[int]:
        return [
            p
            for p in pages
            if self.is_cached(doc_key, p, engine, lang_in, lang_out)
        ]

    def _lock_for(self, key: str) -> threading.Lock:
        with self._locks_guard:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    # ── split ────────────────────────────────────────────────────────────
    def ensure_split(self, src: str | Path, doc_key: str, page: int) -> Path:
        """Estrae la singola pagina in un PDF leggero (cache). ``page`` 0-based."""
        path = self.split_path(doc_key, page)
        if path.is_file():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        import pymupdf  # import locale: l'app può girare senza la parte render

        tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            with pymupdf.open(str(src)) as document:
                new = pymupdf.open()
                try:
                    new.insert_pdf(document, from_page=page, to_page=page)
                    new.save(str(tmp), garbage=4, deflate=True)
                finally:
                    new.close()
            os.replace(tmp, path)
        except Exception as exc:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise EngineError(f"impossibile estrarre la pagina {page + 1}: {exc}") from exc
        return path

    # ── anteprima ────────────────────────────────────────────────────────
    @staticmethod
    def page_count(path: str | Path) -> int:
        import pymupdf

        with pymupdf.open(str(path)) as document:
            return document.page_count

    @staticmethod
    def page_labels(path: str | Path) -> list[str]:
        import pymupdf

        with pymupdf.open(str(path)) as document:
            count = document.page_count
            spec = []
            if hasattr(document, "get_page_labels"):
                with contextlib.suppress(Exception):
                    spec = document.get_page_labels()
        return build_page_labels(spec, count)

    @staticmethod
    def toc(path: str | Path) -> list:
        import pymupdf

        with pymupdf.open(str(path)) as document:
            with contextlib.suppress(Exception):
                return list(document.get_toc())
        return []

    @staticmethod
    def render_thumb(path: str | Path, page: int, width: int = 200) -> bytes:
        """Rende la pagina come PNG di larghezza ``width`` (per l'anteprima)."""
        import pymupdf

        with pymupdf.open(str(path)) as document:
            if page < 0 or page >= document.page_count:
                raise EngineError(f"pagina {page + 1} fuori intervallo")
            pdf_page = document[page]
            rect = pdf_page.rect
            zoom = max(0.05, float(width) / max(rect.width, 1.0))
            pixmap = pdf_page.get_pixmap(
                matrix=pymupdf.Matrix(zoom, zoom), alpha=False
            )
            return pixmap.tobytes("png")

    # ── esportazione ─────────────────────────────────────────────────────
    def export_pdf(
        self, doc_key, pages, engine, dest: str | Path, lang_in, lang_out
    ) -> int:
        """Unisce i mono-PDF tradotti delle ``pages`` (0-based) in ``dest``."""
        import pymupdf

        destination = Path(dest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        merged = 0
        with pymupdf.open() as out:
            for page in pages:
                src = self.translated_path_for(doc_key, page, engine, lang_in, lang_out)
                if not src.is_file():
                    continue
                with pymupdf.open(str(src)) as document:
                    out.insert_pdf(document)
                    merged += 1
            if merged == 0:
                raise EngineError("nessuna pagina tradotta da esportare")
            tmp = destination.with_suffix(destination.suffix + ".tmp")
            out.save(str(tmp), garbage=4, deflate=True)
            os.replace(tmp, destination)
        return merged

    def export_zip(
        self, doc_key, pages, engine, dest: str | Path, lang_in, lang_out, stem=None
    ) -> int:
        """Raccoglie i mono-PDF tradotti in un archivio ZIP."""
        destination = Path(dest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        prefix = stem or "page"
        written = 0
        tmp = destination.with_suffix(destination.suffix + ".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
            for page in pages:
                src = self.translated_path_for(doc_key, page, engine, lang_in, lang_out)
                if not src.is_file():
                    continue
                archive.write(src, arcname=f"{prefix}_p{page + 1:04d}.pdf")
                written += 1
        if written == 0:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise EngineError("nessuna pagina tradotta da esportare")
        os.replace(tmp, destination)
        return written

    # ── traduzione ───────────────────────────────────────────────────────
    def _translator_flags(self, engine: str) -> tuple[list[str], str]:
        if normalize_engine(engine) == "llm":
            return (
                [
                    "--openai",
                    "--openai-model", self.llm_model,
                    "--openai-base-url", self.llm_base_url,
                    "--openai-api-key", self.api_key or os.environ.get("OPENROUTER_API_KEY", ""),
                ],
                f"llm ({self.llm_model})",
            )
        if engine == "google":
            pdf2zh = self.pdf2zh_bin() or Path(sys.executable)
            py = venv_python_for(pdf2zh)
            cli = _gtranslate_cli_path()
            return (
                [
                    "--clitranslator",
                    "--clitranslator-command", f"{py} {cli}",
                    "--clitranslator-timeout", "120",
                    "--qps", "2",
                ],
                "google (gratuito, catena)",
            )
        return (["--bing", "--qps", "5"], "bing")

    def _run_engine(
        self,
        cmd: list[str],
        env: dict,
        cancel_event: threading.Event | None,
    ) -> subprocess.CompletedProcess:
        """Esegue pdf2zh_next limitando i processi e onorando il cancel."""
        semaphore = get_engine_semaphore(self.max_engine_procs)
        acquired = semaphore.acquire(timeout=self.page_timeout)
        if not acquired:
            raise EngineError("timeout in attesa di uno slot motore")
        METRICS.inc(ENGINE_PROCS, 1)
        process: subprocess.Popen | None = None
        try:
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                    start_new_session=not _is_windows(),
                )
            except OSError as exc:
                raise EngineNotFoundError(f"avvio pdf2zh_next fallito: {exc}") from exc

            deadline = time.monotonic() + self.page_timeout
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    self._kill(process)
                    raise TranslationCancelled("traduzione annullata")
                if time.monotonic() > deadline:
                    self._kill(process)
                    raise EngineError("timeout della traduzione")
                try:
                    stdout, stderr = process.communicate(timeout=1.0)
                    break
                except subprocess.TimeoutExpired:
                    continue
            return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
        finally:
            METRICS.inc(ENGINE_PROCS, -1)
            semaphore.release()

    @staticmethod
    def _kill(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            if not _is_windows():
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:  # pragma: no cover - Windows
                # Termina l'intero albero: pdf2zh_next può generare processi figli.
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            with contextlib.suppress(Exception):
                if not _is_windows():
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                else:
                    process.kill()

    def translate_page(
        self,
        src: str | Path,
        doc_key: str,
        page: int,
        engine: str,
        lang_in: str,
        lang_out: str,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        """Traduce una pagina (0-based) e ritorna il PDF tradotto in cache."""
        engine = normalize_engine(engine)
        if engine not in ENGINES:
            engine = "google"
        out = self.translated_path_for(doc_key, page, engine, lang_in, lang_out)
        if out.is_file():
            return out

        pdf2zh = self.pdf2zh_bin()
        if pdf2zh is None:
            raise EngineNotFoundError(
                "pdf2zh_next non trovato: installa il motore (.venv2) o imposta PDF2ZH_BIN"
            )
        if engine == "llm" and not (self.api_key or os.environ.get("OPENROUTER_API_KEY")):
            raise EngineError("OPENROUTER_API_KEY non impostata per il motore LLM")

        out.parent.mkdir(parents=True, exist_ok=True)
        lock_file = out.parent / f".page_{page:06d}.lock"
        with self._lock_for(str(out)):
            with interprocess_lock(lock_file):
                if out.is_file():
                    return out
                return self._translate_uncached(
                    src, doc_key, page, engine, lang_in, lang_out, out, pdf2zh, cancel_event
                )

    def _translate_uncached(
        self, src, doc_key, page, engine, lang_in, lang_out, out, pdf2zh, cancel_event
    ) -> Path:
        split = self.ensure_split(src, doc_key, page)
        t_flags, t_name = self._translator_flags(engine)
        work_dir = self.translated_root / "_tmp" / f"tmp_{doc_key[:12]}_{page:06d}_{engine}_{uuid.uuid4().hex[:8]}"
        shutil.rmtree(work_dir, ignore_errors=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(pdf2zh),
            str(split),
            "--lang-in", lang_in,
            "--lang-out", lang_out,
            "--output", str(work_dir) + os.sep,
            "--watermark-output-mode", "no_watermark",
            "--no-dual",
            "--only-include-translated-page",
            "--disable-config-auto-save",
            "--disable-gui-sensitive-input",
        ] + t_flags
        env = dict(os.environ)
        env["PDF_LANG_IN"] = lang_in
        env["PDF_LANG_OUT"] = lang_out
        env["CLONE_ENGINE_EVENTS"] = str(self.cache_root / "engine_events.jsonl")
        # Allinea il fallback LLM della catena gratuita (gtranslate_cli.py) alla
        # configurazione del servizio, anche se il modello è cambiato via codice.
        env["PDF_LLM_MODEL"] = self.llm_model
        env["PDF_LLM_BASE_URL"] = self.llm_base_url
        if self.api_key:
            env["OPENROUTER_API_KEY"] = self.api_key
        try:
            log.info("traduzione pagina %d via %s", page + 1, t_name)
            result = self._run_engine(cmd, env, cancel_event)
            if result.returncode != 0:
                raise EngineError(
                    f"pdf2zh_next exit {result.returncode}: {(result.stderr or '')[-400:]}"
                )
            monos = glob.glob(str(work_dir / "*.mono.pdf"))
            if not monos:
                # BabelDOC non produce output quando la pagina non ha testo da
                # tradurre (copertina, pagina di sole immagini/scansione). Non è
                # un errore: il clone della pagina è la pagina stessa.
                log.info(
                    "pagina %d (%s): nessun testo da tradurre, uso l'originale",
                    page + 1, t_name,
                )
                shutil.copyfile(split, out)
                return out
            os.replace(monos[0], out)
            return out
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
