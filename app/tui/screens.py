"""Schermate Textual della TUI (unico modulo che importa Textual).

Home dei lavori → wizard in 5 passi → esecuzione con annullamento; la
diagnostica è una modale. La logica che non dipende dal terminale sta in
``app/tui/jobs.py``, l'esecuzione in ``app/tui/runner.py``.
"""

from __future__ import annotations

import time
import webbrowser
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    RadioButton,
    RadioSet,
    RichLog,
    Select,
    Static,
)

from ..engine import CloneEngine
from ..job_factory import build_engine, create_document_and_job
from ..models import (
    ENGINE_LABELS,
    ENGINES,
    LANGUAGES,
    JobRecord,
    JobState,
    RangeMode,
)
from ..pages import format_pages_label, parse_pages
from .jobs import (
    OWNER_ID,
    format_duration,
    format_when,
    language_name,
    preview_lines,
    preview_selection,
    server_is_up,
    state_label,
    suggest_output_name,
    web_url,
)
from .runner import TuiJobRunner

STEP_TITLES = (
    "1/5 · File",
    "2/5 · Pagine",
    "3/5 · Lingue",
    "4/5 · Motore",
    "5/5 · Output",
)


class HomeScreen(Screen):
    """Elenco dei lavori fatti dalla TUI."""

    BINDINGS = [
        Binding("n", "new_job", "Nuovo"),
        Binding("o", "open_output", "Cartella"),
        Binding("d", "doctor", "Diagnostica"),
        Binding("w", "web", "Web"),
        Binding("r", "refresh", "Aggiorna"),
        Binding("q", "quit", "Esci"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="home"):
            yield Static("Lavori", id="home-title")
            yield Static(
                "Premi n per un nuovo lavoro.", id="home-hint"
            )
            yield DataTable(id="jobs", zebra_stripes=True, cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#jobs", DataTable)
        table.add_columns("Quando", "File", "Pagine", "Motore", "Stato", "Durata")
        self._jobs: list[JobRecord] = []
        self._names: dict[str, str] = {}
        self.refresh_jobs()
        self.set_interval(2.0, self.refresh_jobs)

    # ── dati ─────────────────────────────────────────────────────────────
    def refresh_jobs(self) -> None:
        jobs = self.app.storage.list_jobs(limit=50, owner_id=OWNER_ID)
        if jobs == self._jobs:
            return
        table = self.query_one("#jobs", DataTable)
        row = table.cursor_row
        table.clear()
        for job in jobs:
            table.add_row(
                format_when(job.created),
                self._document_name(job),
                str(job.pages_total),
                job.engine,
                state_label(job.state),
                format_duration(job.duration_ms),
                key=job.job_id,
            )
        self._jobs = jobs
        self.query_one("#home-hint", Static).update(
            "Nessun lavoro: premi n per iniziare."
            if not jobs
            else "n nuovo · o cartella output · d diagnostica · w web · q esci"
        )
        if jobs:
            table.move_cursor(row=min(row, len(jobs) - 1))

    def _document_name(self, job: JobRecord) -> str:
        name = self._names.get(job.doc_id)
        if name is None:
            document = self.app.storage.get_document(job.doc_id)
            name = document.filename if document else job.output_name
            self._names[job.doc_id] = name
        return name

    def _selected_job(self) -> JobRecord | None:
        table = self.query_one("#jobs", DataTable)
        if not self._jobs or table.cursor_row >= len(self._jobs):
            return None
        return self._jobs[table.cursor_row]

    # ── azioni ───────────────────────────────────────────────────────────
    def action_new_job(self) -> None:
        self.app.push_screen(WizardScreen())

    def action_refresh(self) -> None:
        self.refresh_jobs()
        self.notify("elenco aggiornato", timeout=2)

    def action_open_output(self) -> None:
        job = self._selected_job()
        if job is None:
            self.notify("nessun lavoro selezionato", severity="warning")
            return
        if not job.artifact_path or not Path(job.artifact_path).is_file():
            self.notify("output non più disponibile", severity="warning")
            return
        self._open_path(Path(job.artifact_path).parent)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_open_output()

    def action_doctor(self) -> None:
        self.app.push_screen(DoctorScreen())

    def action_web(self) -> None:
        settings = self.app.settings
        if not server_is_up(settings):
            self.notify(
                "server non attivo: avvialo con ./noesis start",
                severity="warning",
                timeout=6,
            )
            return
        webbrowser.open(web_url(settings))

    def action_quit(self) -> None:
        self.app.exit()

    def _open_path(self, path: Path) -> None:
        try:
            webbrowser.open(path.as_uri())
        except Exception:  # noqa: BLE001 - best effort
            self.notify(f"non riesco ad aprire {path}", severity="warning")


class WizardScreen(Screen):
    """Nuovo lavoro: file → pagine → lingue → motore → output."""

    BINDINGS = [
        Binding("escape", "cancel", "Annulla"),
        Binding("ctrl+enter", "next", "Avanti"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.step = 0
        self.pdf: Path | None = None
        self.page_count = 0
        self.pages: list[int] = []

    # ── struttura ────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        languages = [(name, code) for code, name in LANGUAGES.items()]
        destinations = [(name, code) for code, name in LANGUAGES.items() if code != "auto"]
        yield Header()
        with VerticalScroll(id="wizard"):
            yield Static(STEP_TITLES[0], id="wizard-title")

            with Vertical(id="step-0", classes="step"):
                yield Label("Percorso del PDF")
                yield Input(
                    placeholder="es. pdfs/ha22.pdf (invio per confermare)",
                    id="pdf-path",
                )
                yield Static("", id="pdf-info", classes="hint")

            with Vertical(id="step-1", classes="step"):
                yield Label("Pagine da tradurre")
                yield Input(value="all", id="pages")
                yield Static("", id="pages-info", classes="hint")

            with Vertical(id="step-2", classes="step"):
                yield Label("Lingua di partenza")
                yield Select(languages, value="auto", allow_blank=False, id="src")
                yield Label("Lingua di arrivo")
                yield Select(destinations, value="it", allow_blank=False, id="dst")

            with Vertical(id="step-3", classes="step"):
                yield Label("Motore")
                yield RadioSet(
                    *[
                        RadioButton(
                            ENGINE_LABELS.get(name, name),
                            id=f"eng-{name}",
                            value=(name == "google"),
                        )
                        for name in ENGINES
                    ],
                    id="engine",
                )
                with Vertical(id="llm-box"):
                    yield Label("Chiave OpenRouter (solo per questo lavoro)")
                    yield Input(
                        placeholder="sk-or-… (vuoto = variabile d'ambiente)",
                        password=True,
                        id="llm-key",
                    )
                    yield Static(
                        "La chiave non viene salvata: vale solo per il job.",
                        classes="hint",
                    )

            with Vertical(id="step-4", classes="step"):
                yield Label("Nome del file di uscita (senza estensione)")
                yield Input(placeholder="automatico: <nome>_<lingua>", id="out-name")
                yield Label("Cartella di uscita")
                yield Input(value=str(Path.cwd()), id="out-dir")
                yield Label("Formato")
                yield RadioSet(
                    RadioButton("Un unico PDF", id="rm-merged", value=True),
                    RadioButton("ZIP con le pagine singole", id="rm-single"),
                    id="range-mode",
                )
                yield Static("", id="summary", classes="hint")

            with Horizontal(id="wizard-nav"):
                yield Button("Annulla", id="wiz-cancel")
                yield Button("Indietro", id="wiz-back")
                yield Button("Avanti", id="wiz-next", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self._show_step(0)

    def _show_step(self, step: int) -> None:
        self.step = step
        for index in range(len(STEP_TITLES)):
            self.query_one(f"#step-{index}").display = index == step
        self.query_one("#wizard-title", Static).update(STEP_TITLES[step])
        self.query_one("#wiz-back", Button).disabled = step == 0
        self.query_one("#wiz-next", Button).label = (
            "Avvia la traduzione" if step == len(STEP_TITLES) - 1 else "Avanti"
        )
        if step == len(STEP_TITLES) - 1:
            self._refresh_summary()
        focus = {
            0: "#pdf-path",
            1: "#pages",
            2: "#src",
            3: "#engine",
            4: "#out-name",
        }[step]
        self.query_one(focus).focus()

    # ── input ────────────────────────────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "pdf-path" and self.step == 0:
            self.action_next()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "pages" and self.pdf is not None:
            # Solo conteggio mentre si digita: l'anteprima (che apre il PDF)
            # si calcola quando si conferma il passo.
            self.query_one("#pages-info", Static).update(self._pages_hint(preview=False))
        elif event.input.id in {"out-name", "out-dir"} and self.step == len(STEP_TITLES) - 1:
            self._refresh_summary()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "engine":
            self.query_one("#llm-box").display = self._engine() == "llm"

    def on_select_changed(self, event: Select.Changed) -> None:
        if self.step == len(STEP_TITLES) - 1:
            self._refresh_summary()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "wiz-cancel":
            self.action_cancel()
        elif event.button.id == "wiz-back":
            self._show_step(max(0, self.step - 1))
        elif event.button.id == "wiz-next":
            self.action_next()

    # ── passi ────────────────────────────────────────────────────────────
    def action_cancel(self) -> None:
        self.app.pop_screen()

    def action_next(self) -> None:
        if self.step == 0:
            if not self._validate_file():
                return
        elif self.step == 1:
            if not self._validate_pages():
                return
        elif self.step == 2:
            if not self._validate_languages():
                return
        elif self.step == 3:
            if not self._validate_engine():
                return
        else:
            self._submit()
            return
        self._show_step(self.step + 1)

    def _validate_file(self) -> bool:
        raw = self.query_one("#pdf-path", Input).value.strip()
        if not raw:
            self.notify("indica il percorso di un PDF", severity="error")
            return False
        pdf = Path(raw).expanduser()
        if not pdf.is_file():
            self.notify(f"file non trovato: {pdf}", severity="error")
            return False
        if pdf.suffix.lower() != ".pdf":
            self.notify("il file non è un PDF", severity="error")
            return False
        try:
            count = CloneEngine.page_count(pdf)
        except Exception as exc:  # noqa: BLE001
            self.notify(f"PDF illeggibile: {exc}", severity="error")
            return False
        self.pdf = pdf
        self.page_count = count
        self.query_one("#pdf-info", Static).update(
            f"{pdf.name} · {count} pagine · {pdf.stat().st_size / 1_048_576:.1f} MB"
        )
        return True

    def _pages_hint(self, *, preview: bool = True) -> str:
        try:
            pages = parse_pages(self.query_one("#pages", Input).value, self.page_count)
        except ValueError as exc:
            return f"specifica non valida: {exc}"
        if len(pages) > self.app.settings.max_pages_total:
            return f"troppe pagine (max {self.app.settings.max_pages_total})"
        lines = [f"{len(pages)} pagine · {format_pages_label(pages)}"]
        if preview and self.pdf is not None:
            lines += preview_lines(preview_selection(self.pdf, pages))
        return "\n".join(lines)

    def _validate_pages(self) -> bool:
        try:
            pages = parse_pages(self.query_one("#pages", Input).value, self.page_count)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return False
        if len(pages) > self.app.settings.max_pages_total:
            self.notify(
                f"troppe pagine (max {self.app.settings.max_pages_total})",
                severity="error",
            )
            return False
        self.pages = pages
        self.query_one("#pages-info", Static).update(self._pages_hint())
        return True

    def _validate_languages(self) -> bool:
        if self.query_one("#dst", Select).value in (Select.BLANK, None, "auto"):
            self.notify("scegli la lingua di arrivo", severity="error")
            return False
        return True

    def _engine(self) -> str:
        pressed = self.query_one("#engine", RadioSet).pressed_button
        if pressed is None or not pressed.id:
            return ENGINES[0]
        return pressed.id.split("-", 1)[1]

    def _validate_engine(self) -> bool:
        if self._engine() != "llm":
            return True
        if self._llm_key() or self.app.settings.openrouter_api_key:
            return True
        self.notify(
            "il motore LLM richiede la chiave OpenRouter (o OPENROUTER_API_KEY)",
            severity="error",
        )
        return False

    def _llm_key(self) -> str:
        return self.query_one("#llm-key", Input).value.strip()

    def _refresh_summary(self) -> None:
        pdf = self.pdf
        if pdf is None:
            self.query_one("#summary", Static).update("")
            return
        dst = str(self.query_one("#dst", Select).value or "it")
        src = str(self.query_one("#src", Select).value or "auto")
        out_name = self.query_one("#out-name", Input).value.strip()
        try:
            out_dir = Path(self.query_one("#out-dir", Input).value.strip() or ".")
        except (OSError, ValueError):
            out_dir = Path(".")
        name = out_name or suggest_output_name(pdf, dst)
        self.query_one("#summary", Static).update(
            f"{len(self.pages) or self.page_count} pagine · motore {self._engine()} · "
            f"{language_name(src)} → {language_name(dst)}\n"
            f"output: {out_dir / name}"
        )

    # ── avvio ────────────────────────────────────────────────────────────
    def _submit(self) -> None:
        if self.pdf is None:
            self.notify("scegli prima un PDF", severity="error")
            return
        if self.app.settings.require_terms_acceptance:
            self.notify(
                "i Termini d'uso sono richiesti: usa l'interfaccia web "
                "(./noesis start, poi w dalla Home)",
                severity="error",
                timeout=8,
            )
            return
        if not self._refresh_ready():
            return
        self.query_one("#wiz-next", Button).disabled = True
        self._start_job(
            pdf=self.pdf,
            pages_spec=self.query_one("#pages", Input).value,
            src=str(self.query_one("#src", Select).value),
            dst=str(self.query_one("#dst", Select).value),
            engine_name=self._engine(),
            key=self._llm_key(),
            out_name=self.query_one("#out-name", Input).value.strip(),
            out_dir=self.query_one("#out-dir", Input).value.strip(),
            range_mode=self._range_mode(),
        )

    def _range_mode(self) -> RangeMode:
        pressed = self.query_one("#range-mode", RadioSet).pressed_button
        if pressed is not None and pressed.id == "rm-single":
            return RangeMode.single
        return RangeMode.merged

    def _refresh_ready(self) -> bool:
        # Validazione finale dei campi liberi, senza uscire dal passo.
        try:
            parse_pages(self.query_one("#pages", Input).value, self.page_count)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return False
        if not self.query_one("#out-dir", Input).value.strip():
            self.notify("indica la cartella di uscita", severity="error")
            return False
        return True

    @work(thread=True, exclusive=True)
    def _start_job(
        self,
        *,
        pdf: Path,
        pages_spec: str,
        src: str,
        dst: str,
        engine_name: str,
        key: str,
        out_name: str,
        out_dir: str,
        range_mode: RangeMode,
    ) -> None:
        settings = self.app.settings
        if server_is_up(settings):
            self.app.call_from_thread(
                self._failed,
                "il server è attivo sulla stessa cartella dati: usa l'interfaccia "
                "web (w) oppure fermalo con ./noesis stop",
            )
            return
        try:
            engine = build_engine(settings, api_key=key or None)
            document, job = create_document_and_job(
                self.app.storage,
                engine,
                pdf,
                pages_spec=pages_spec,
                src_lang=src,
                dst_lang=dst,
                engine_name=engine_name,
                output_name=out_name or None,
                range_mode=range_mode,
                owner_id=OWNER_ID,
                state=JobState.running,
                max_pages=settings.max_pages_total,
            )
        except Exception as exc:  # noqa: BLE001 - mostrato all'utente
            self.app.call_from_thread(self._failed, str(exc) or exc.__class__.__name__)
            return
        try:
            cached = len(
                engine.cached_pages(
                    document.sha256, job.pages, job.engine, job.src_lang, job.dst_lang
                )
            )
        except Exception:  # noqa: BLE001 - informazione accessoria
            cached = 0
        self.app.call_from_thread(
            self._job_created, job, engine, Path(out_dir).expanduser(), cached
        )

    def _failed(self, message: str) -> None:
        self.query_one("#wiz-next", Button).disabled = False
        self.notify(message, severity="error", timeout=8)

    def _job_created(
        self, job: JobRecord, engine: CloneEngine, out_dir: Path, cached: int = 0
    ) -> None:
        self.app.switch_screen(
            RunScreen(job=job, engine=engine, out_dir=out_dir, cached=cached)
        )


class RunScreen(Screen):
    """Esecuzione del job: avanzamento, log e annullamento."""

    BINDINGS = [
        Binding("escape", "cancel", "Annulla"),
        Binding("o", "open_out", "Cartella"),
        Binding("n", "new_job", "Nuovo"),
        Binding("q", "home", "Home"),
    ]

    def __init__(
        self,
        *,
        job: JobRecord,
        engine: CloneEngine,
        out_dir: Path,
        cached: int = 0,
    ) -> None:
        super().__init__()
        self.job = job
        self.engine = engine
        self.out_dir = out_dir
        self.cached = cached
        self.out_path: Path | None = None
        self._marks: dict[int, bool] = {}
        self._started = time.monotonic()
        self._finished = False
        self._cancelling = False
        self.runner: TuiJobRunner | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="run"):
            yield Static("", id="run-title")
            yield ProgressBar(total=self.job.pages_total or 1, show_percentage=True, id="bar")
            yield Static("preparazione…", id="run-status")
            yield Static("", id="run-grid")
            yield RichLog(id="log", markup=True, max_lines=400)
            with Horizontal(id="run-nav"):
                yield Button("Annulla", id="btn-cancel", variant="error")
                yield Button("Apri cartella", id="btn-open", disabled=True)
                yield Button("Nuovo lavoro", id="btn-new", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        cache_note = f" · {self.cached} in cache" if self.cached else ""
        self.query_one("#run-title", Static).update(
            f"{self.job.output_name} · {self.job.pages_total} pagine{cache_note} · "
            f"{self.job.src_lang} → {self.job.dst_lang} · motore {self.job.engine}"
        )
        self.runner = TuiJobRunner(
            storage=self.app.storage,
            engine=self.engine,
            job=self.job,
            settings=self.app.settings,
            on_event=self._thread_event,
            on_page=self._thread_page,
            on_done=self._thread_done,
        )
        self.app.active_runner = self.runner
        self.runner.start()
        self.set_interval(1.0, self._tick)

    def on_unmount(self) -> None:
        if self.runner is not None and self.runner.running:
            self.runner.cancel()

    # ── callbacks dal thread del job ─────────────────────────────────────
    def _thread_event(self, record: dict) -> None:
        self.app.call_from_thread(self._on_event, record)

    def _thread_page(self, done: int, total: int, page: int, ok: bool) -> None:
        self.app.call_from_thread(self._on_page, done, total, page, ok)

    def _thread_done(self, result, error) -> None:
        self.app.call_from_thread(self._on_done, result, error)

    # ── aggiornamenti UI ─────────────────────────────────────────────────
    def _on_event(self, record: dict) -> None:
        level = record.get("level", "info")
        colour = {"error": "red", "warning": "yellow"}.get(level, "grey70")
        message = record.get("message", "")
        self.query_one("#log", RichLog).write(f"[{colour}]{message}[/{colour}]")

    def _on_page(self, done: int, total: int, page: int, ok: bool) -> None:
        self._marks[page] = ok
        self.query_one("#bar", ProgressBar).update(total=max(total, 1), progress=done)
        failures = sum(1 for value in self._marks.values() if not value)
        self.query_one("#run-status", Static).update(
            f"{done}/{total} pagine · errori {failures} · "
            f"trascorsi {format_duration(int((time.monotonic() - self._started) * 1000))}"
        )
        self._render_grid()

    def _render_grid(self) -> None:
        symbols = []
        for page in self.job.pages:
            if page in self._marks:
                symbols.append("✓" if self._marks[page] else "✗")
            else:
                symbols.append("·")
        lines = [
            "".join(symbols[index : index + 28])
            for index in range(0, len(symbols), 28)
        ]
        self.query_one("#run-grid", Static).update(
            "\n".join(lines) + "\n[dim]✓ tradotta · ✗ errore · · in attesa[/dim]"
            if lines
            else ""
        )

    def _tick(self) -> None:
        if self._finished or self._cancelling:
            return
        elapsed = int((time.monotonic() - self._started) * 1000)
        current = self._current_status()
        self.query_one("#run-status", Static).update(
            f"{current} · trascorsi {format_duration(elapsed)}"
        )

    def _current_status(self) -> str:
        done = len(self._marks)
        failures = sum(1 for value in self._marks.values() if not value)
        return (
            f"{done}/{self.job.pages_total} pagine · errori {failures}"
            if self.job.pages_total
            else "in corso"
        )

    def _on_done(self, result, error: str | None) -> None:
        self._finished = True
        self.query_one("#btn-cancel", Button).disabled = True
        if error is not None or result is None:
            self.query_one("#run-status", Static).update(f"errore: {error}")
            self.notify(f"job fallito: {error}", severity="error", timeout=10)
            return
        if result.cancelled:
            self.query_one("#run-status", Static).update(
                f"annullato · {result.pages_done} pagine tradotte (restano in cache)"
            )
            return
        if not result.artifact_path:
            self.query_one("#run-status", Static).update(
                f"nessun output: {result.error or 'errore sconosciuto'}"
            )
            return
        self.query_one("#run-status", Static).update("copio l'output…")
        self._finalize(result)

    @work(thread=True)
    def _finalize(self, result) -> None:
        from .jobs import copy_artifact

        dest = copy_artifact(result.artifact_path, self.out_dir)
        if dest is not None:
            try:
                self.app.storage.update_job(self.job.job_id, artifact_path=str(dest))
            except Exception:  # noqa: BLE001 - il file esiste comunque
                pass
        self.app.call_from_thread(self._show_final, result, dest)

    def _show_final(self, result, dest: Path | None) -> None:
        self.out_path = dest
        self.query_one("#btn-open", Button).disabled = dest is None
        failures = result.pages_failed
        text = (
            f"completato · {result.pages_done}/{result.pages_total} pagine"
            + (f" · {failures} errori" if failures else "")
            + f" · {format_duration(result.duration_ms)}"
        )
        if dest is not None:
            text += f"\n{self.out_dir / dest.name}"
        self.query_one("#run-status", Static).update(text)
        self.notify(
            f"file pronto: {dest}" if dest else "job completato",
            timeout=8,
        )

    # ── azioni ───────────────────────────────────────────────────────────
    def action_cancel(self) -> None:
        if self._finished or self.runner is None:
            return
        self._cancelling = True
        self.runner.cancel()
        self.query_one("#btn-cancel", Button).disabled = True
        self.query_one("#run-status", Static).update("annullamento in corso…")
        self.query_one("#log", RichLog).write("[yellow]annullamento richiesto[/yellow]")

    def action_open_out(self) -> None:
        target = self.out_path or (
            Path(self.job.artifact_path) if self.job.artifact_path else None
        )
        if target is None or not target.exists():
            self.notify("nessun output da aprire", severity="warning")
            return
        folder = target if target.is_dir() else target.parent
        try:
            webbrowser.open(folder.as_uri())
        except Exception:  # noqa: BLE001 - best effort
            self.notify(f"non riesco ad aprire {folder}", severity="warning")

    def action_new_job(self) -> None:
        if self.runner is not None and self.runner.running:
            self.notify(
                "job in corso: Esc per annullarlo prima di iniziarne un altro",
                severity="warning",
            )
            return
        self.app.switch_screen(WizardScreen())

    def action_home(self) -> None:
        if self.runner is not None and self.runner.running:
            self.notify(
                "job in corso: Esc per annullarlo, poi q per uscire",
                severity="warning",
            )
            return
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.action_cancel()
        elif event.button.id == "btn-open":
            self.action_open_out()
        elif event.button.id == "btn-new":
            self.action_new_job()


class DoctorScreen(ModalScreen):
    """Diagnostica runtime (motore, chiave, modello, ambiente)."""

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    def compose(self) -> ComposeResult:
        with Vertical(id="doctor"):
            yield Static("Diagnostica", id="doctor-title")
            yield Static("eseguo i controlli…", id="doctor-body")
            yield Button("Chiudi", id="doctor-close", variant="primary")

    def on_mount(self) -> None:
        self._collect()

    @work(thread=True, exclusive=True)
    def _collect(self) -> None:
        from .jobs import doctor_rows, health_symbol

        try:
            rows = doctor_rows(self.app.settings)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self._show, [("XX", "errore", str(exc) or exc.__class__.__name__)]
            )
            return
        self.app.call_from_thread(
            self._show, [(health_symbol(status), check, detail) for status, check, detail in rows]
        )

    def _show(self, rows: list[tuple[str, str, str]]) -> None:
        width = max((len(row[1]) for row in rows), default=8)
        body = "\n".join(
            f"{symbol:2s} {check:<{width}s}  {detail}".rstrip() for symbol, check, detail in rows
        )
        self.query_one("#doctor-body", Static).update(body)

    def action_close(self) -> None:
        self.dismiss()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "doctor-close":
            self.dismiss()
