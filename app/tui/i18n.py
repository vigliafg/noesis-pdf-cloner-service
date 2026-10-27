"""Stringhe della TUI (it/en) e rilevamento delle capacità del terminale.

Le stringhe del *motore* (pipeline, engine) restano in italiano: sono condivise
con CLI e server. Qui sta solo ciò che scrive la TUI.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

__all__ = [
    "LANGUAGES",
    "T",
    "TerminalProfile",
    "ascii_mode",
    "get_language",
    "probe_terminal",
    "set_ascii",
    "set_language",
]

LANGUAGES = ("it", "en")
_language = "it"
_ascii = False

_STRINGS: dict[str, dict[str, str]] = {
    # ── app / comune ────────────────────────────────────────────────────
    "app.subtitle": {
        "it": "TUI · traduzione PDF con layout preservato",
        "en": "TUI · layout-preserving PDF translation",
    },
    "app.exit": {"it": "Esci", "en": "Quit"},
    "app.quit_hint": {"it": "Ctrl+Q per uscire", "en": "Ctrl+Q to quit"},
    # ── home ────────────────────────────────────────────────────────────
    "home.title": {"it": "Lavori", "en": "Jobs"},
    "home.hint": {
        "it": "Premi n per un nuovo lavoro.",
        "en": "Press n for a new job.",
    },
    "home.empty": {
        "it": "Nessun lavoro: premi n per iniziare.",
        "en": "No jobs yet: press n to start.",
    },
    "home.actions": {
        "it": "n nuovo · o cartella output · d diagnostica · w web · q esci",
        "en": "n new · o output folder · d diagnostics · w web · q quit",
    },
    "home.col.when": {"it": "Quando", "en": "When"},
    "home.col.file": {"it": "File", "en": "File"},
    "home.col.pages": {"it": "Pagine", "en": "Pages"},
    "home.col.engine": {"it": "Motore", "en": "Engine"},
    "home.col.state": {"it": "Stato", "en": "State"},
    "home.col.duration": {"it": "Durata", "en": "Duration"},
    "home.new": {"it": "Nuovo", "en": "New"},
    "home.folder": {"it": "Cartella", "en": "Folder"},
    "home.doctor": {"it": "Diagnostica", "en": "Diagnostics"},
    "home.web": {"it": "Web", "en": "Web"},
    "home.refresh": {"it": "Aggiorna", "en": "Refresh"},
    "home.refreshed": {"it": "elenco aggiornato", "en": "list refreshed"},
    "home.no_selection": {
        "it": "nessun lavoro selezionato",
        "en": "no job selected",
    },
    "home.output_gone": {
        "it": "output non più disponibile",
        "en": "output no longer available",
    },
    "home.server_down": {
        "it": "server non attivo: avvialo con ./noesis start",
        "en": "server not running: start it with ./noesis start",
    },
    "home.open_failed": {
        "it": "non riesco ad aprire {path}",
        "en": "cannot open {path}",
    },
    # ── wizard ──────────────────────────────────────────────────────────
    "wizard.step.file": {"it": "1/5 · File", "en": "1/5 · File"},
    "wizard.step.pages": {"it": "2/5 · Pagine", "en": "2/5 · Pages"},
    "wizard.step.langs": {"it": "3/5 · Lingue", "en": "3/5 · Languages"},
    "wizard.step.engine": {"it": "4/5 · Motore", "en": "4/5 · Engine"},
    "wizard.step.output": {"it": "5/5 · Output", "en": "5/5 · Output"},
    "wizard.file.label": {
        "it": "Percorso del PDF",
        "en": "PDF path",
    },
    "wizard.file.placeholder": {
        "it": "es. pdfs/ha22.pdf (invio per confermare)",
        "en": "e.g. pdfs/ha22.pdf (Enter to confirm)",
    },
    "wizard.file.browse": {"it": "Sfoglia…", "en": "Browse…"},
    "wizard.pages.label": {
        "it": "Pagine da tradurre",
        "en": "Pages to translate",
    },
    "wizard.pages.placeholder": {
        "it": "all · 7 · 100-103 · 3,5,10-12",
        "en": "all · 7 · 100-103 · 3,5,10-12",
    },
    "wizard.src.label": {"it": "Lingua di partenza", "en": "Source language"},
    "wizard.dst.label": {"it": "Lingua di arrivo", "en": "Target language"},
    "wizard.engine.label": {"it": "Motore", "en": "Engine"},
    "wizard.key.label": {
        "it": "Chiave OpenRouter (solo per questo lavoro)",
        "en": "OpenRouter key (this job only)",
    },
    "wizard.key.placeholder": {
        "it": "sk-or-… (vuoto = variabile d'ambiente)",
        "en": "sk-or-… (empty = environment variable)",
    },
    "wizard.key.hint": {
        "it": "La chiave non viene salvata: vale solo per il job.",
        "en": "The key is not stored: it applies to this job only.",
    },
    "wizard.outname.label": {
        "it": "Nome del file di uscita (senza estensione)",
        "en": "Output file name (without extension)",
    },
    "wizard.outname.placeholder": {
        "it": "automatico: <nome>_<lingua>",
        "en": "automatic: <name>_<language>",
    },
    "wizard.outdir.label": {"it": "Cartella di uscita", "en": "Output folder"},
    "wizard.format.label": {"it": "Formato", "en": "Format"},
    "wizard.format.merged": {"it": "Un unico PDF", "en": "Single PDF"},
    "wizard.format.single": {
        "it": "ZIP con le pagine singole",
        "en": "ZIP with single pages",
    },
    "wizard.btn.cancel": {"it": "Annulla", "en": "Cancel"},
    "wizard.btn.back": {"it": "Indietro", "en": "Back"},
    "wizard.btn.next": {"it": "Avanti", "en": "Next"},
    "wizard.btn.start": {"it": "Avvia la traduzione", "en": "Start translation"},
    "wizard.err.no_file": {
        "it": "indica il percorso di un PDF",
        "en": "enter a PDF path",
    },
    "wizard.err.not_found": {"it": "file non trovato: {path}", "en": "file not found: {path}"},
    "wizard.err.not_pdf": {"it": "il file non è un PDF", "en": "the file is not a PDF"},
    "wizard.err.unreadable": {
        "it": "PDF illeggibile: {error}",
        "en": "unreadable PDF: {error}",
    },
    "wizard.err.too_many": {
        "it": "troppe pagine (max {max})",
        "en": "too many pages (max {max})",
    },
    "wizard.err.bad_spec": {
        "it": "specifica non valida: {error}",
        "en": "invalid page selection: {error}",
    },
    "wizard.err.dst": {
        "it": "scegli la lingua di arrivo",
        "en": "choose the target language",
    },
    "wizard.err.llm_key": {
        "it": "il motore LLM richiede la chiave OpenRouter (o OPENROUTER_API_KEY)",
        "en": "the LLM engine needs the OpenRouter key (or OPENROUTER_API_KEY)",
    },
    "wizard.err.no_pdf": {"it": "scegli prima un PDF", "en": "choose a PDF first"},
    "wizard.err.terms": {
        "it": "i Termini d'uso sono richiesti: usa l'interfaccia web "
              "(./noesis start, poi w dalla Home)",
        "en": "Terms of use are required: use the web UI "
              "(./noesis start, then w from Home)",
    },
    "wizard.err.outdir": {
        "it": "indica la cartella di uscita",
        "en": "enter the output folder",
    },
    "wizard.err.server_busy": {
        "it": "il server è attivo sulla stessa cartella dati: usa l'interfaccia "
              "web (w) oppure fermalo con ./noesis stop",
        "en": "the server is running on the same data folder: use the web UI "
              "(w) or stop it with ./noesis stop",
    },
    "wizard.info.file": {
        "it": "{name} · {pages} pagine · {size:.1f} MB",
        "en": "{name} · {pages} pages · {size:.1f} MB",
    },
    "wizard.info.pages": {"it": "{count} pagine · {label}", "en": "{count} pages · {label}"},
    "wizard.preview.physical": {"it": "fisica {number}", "en": "physical {number}"},
    "wizard.preview.physical_label": {
        "it": "fisica {number} · «{label}»",
        "en": "physical {number} · “{label}”",
    },
    "wizard.preview.none": {
        "it": "(nessun testo estratto)",
        "en": "(no text extracted)",
    },
    "wizard.summary.pages": {
        "it": "{count} pagine · motore {engine} · {src} → {dst}",
        "en": "{count} pages · engine {engine} · {src} → {dst}",
    },
    "wizard.summary.output": {"it": "output: {path}", "en": "output: {path}"},
    # ── esecuzione ──────────────────────────────────────────────────────
    "run.title": {
        "it": "{name} · {pages} pagine{cache} · {src} → {dst} · motore {engine}",
        "en": "{name} · {pages} pages{cache} · {src} → {dst} · engine {engine}",
    },
    "run.title.cache": {"it": " · {count} in cache", "en": " · {count} cached"},
    "run.btn.cancel": {"it": "Annulla", "en": "Cancel"},
    "run.btn.open": {"it": "Apri cartella", "en": "Open folder"},
    "run.btn.new": {"it": "Nuovo lavoro", "en": "New job"},
    "run.menu.open": {"it": "Cartella", "en": "Folder"},
    "run.menu.new": {"it": "Nuovo", "en": "New"},
    "run.menu.home": {"it": "Home", "en": "Home"},
    "run.preparing": {"it": "preparazione…", "en": "preparing…"},
    "run.progress": {
        "it": "{done}/{total} pagine · errori {failed} · trascorsi {elapsed}",
        "en": "{done}/{total} pages · errors {failed} · elapsed {elapsed}",
    },
    "run.cancelling": {"it": "annullamento in corso…", "en": "cancelling…"},
    "run.cancelled": {
        "it": "annullato · {done} pagine tradotte (restano in cache)",
        "en": "cancelled · {done} pages translated (kept in cache)",
    },
    "run.copying": {"it": "copio l'output…", "en": "copying the output…"},
    "run.completed": {
        "it": "completato · {done}/{total} pagine{errors} · {duration}",
        "en": "done · {done}/{total} pages{errors} · {duration}",
    },
    "run.completed.errors": {"it": " · {count} errori", "en": " · {count} errors"},
    "run.error": {"it": "errore: {error}", "en": "error: {error}"},
    "run.no_output": {
        "it": "nessun output: {error}",
        "en": "no output: {error}",
    },
    "run.legend": {
        "it": "✓ tradotta · ✗ errore · · in attesa",
        "en": "✓ translated · ✗ error · · pending",
    },
    "run.log.cancel": {"it": "annullamento richiesto", "en": "cancellation requested"},
    "run.msg.ready": {"it": "file pronto: {path}", "en": "file ready: {path}"},
    "run.msg.done": {"it": "job completato", "en": "job completed"},
    "run.msg.failed": {"it": "job fallito: {error}", "en": "job failed: {error}"},
    "run.msg.nothing": {
        "it": "nessun output da aprire",
        "en": "nothing to open",
    },
    "run.msg.busy": {
        "it": "job in corso: Esc per annullarlo, poi q per uscire",
        "en": "job running: Esc to cancel it, then q to exit",
    },
    "run.msg.busy_new": {
        "it": "job in corso: Esc per annullarlo prima di iniziarne un altro",
        "en": "job running: Esc to cancel it before starting another",
    },
    # ── diagnostica ─────────────────────────────────────────────────────
    "doctor.title": {"it": "Diagnostica", "en": "Diagnostics"},
    "doctor.running": {"it": "eseguo i controlli…", "en": "running checks…"},
    "doctor.close": {"it": "Chiudi", "en": "Close"},
    "doctor.error": {"it": "errore", "en": "error"},
    # ── file picker ─────────────────────────────────────────────────────
    "picker.title": {"it": "Scegli il PDF", "en": "Choose the PDF"},
    "picker.up": {"it": "Su", "en": "Up"},
    "picker.home": {"it": "Home", "en": "Home"},
    "picker.cwd": {"it": "Cartella corrente", "en": "Current folder"},
    "picker.hidden": {"it": "Nascosti", "en": "Hidden"},
    "picker.cancel": {"it": "Annulla", "en": "Cancel"},
    "picker.select": {"it": "Seleziona", "en": "Select"},
    "picker.hint": {
        "it": "doppio clic su un file per sceglierlo · Esc per annullare",
        "en": "double-click a file to pick it · Esc to cancel",
    },
    "picker.not_a_pdf": {
        "it": "scegli un file .pdf",
        "en": "choose a .pdf file",
    },
    # ── main / errori ───────────────────────────────────────────────────
    "main.err.tty": {
        "it": "la TUI richiede un terminale interattivo.\n"
              "Per l'uso da script o in pipe: ./run-cli.sh --help",
        "en": "the TUI needs an interactive terminal.\n"
              "For scripts or pipes: ./run-cli.sh --help",
    },
    "main.warn.no_textual": {
        "it": "Textual non disponibile: uso il wizard a righe.",
        "en": "Textual not available: using the line wizard.",
    },
    "main.err.args": {
        "it": "argomenti non riconosciuti: usa ./noesis tui [--theme …] [--lang …] [--line]",
        "en": "unknown arguments: use ./noesis tui [--theme …] [--lang …] [--line]",
    },
    "main.warn.server": {
        "it": "attenzione: il server risponde su {host}:{port}. La TUI non "
              "avvierà job finché è attivo.",
        "en": "warning: the server answers on {host}:{port}. The TUI will not "
              "start jobs while it is running.",
    },
    # ── fallback a righe ────────────────────────────────────────────────
    "fallback.intro": {
        "it": "Noesis PDF Cloner — wizard a righe (Invio = valore predefinito)",
        "en": "Noesis PDF Cloner — line wizard (Enter = default)",
    },
    "fallback.pdf": {"it": "Percorso del PDF", "en": "PDF path"},
    "fallback.pages": {"it": "Pagine (all · 7 · 100-103 · 3,5,10-12)", "en": "Pages (all · 7 · 100-103 · 3,5,10-12)"},
    "fallback.src": {"it": "Lingua di partenza", "en": "Source language"},
    "fallback.dst": {"it": "Lingua di arrivo", "en": "Target language"},
    "fallback.engine": {"it": "Motore (google/bing/llm)", "en": "Engine (google/bing/llm)"},
    "fallback.key": {"it": "Chiave OpenRouter (vuoto = ambiente)", "en": "OpenRouter key (empty = environment)"},
    "fallback.outname": {"it": "Nome output (vuoto = automatico)", "en": "Output name (empty = automatic)"},
    "fallback.outdir": {"it": "Cartella di uscita", "en": "Output folder"},
    "fallback.mode": {"it": "Formato (merged/single)", "en": "Format (merged/single)"},
    "fallback.confirm": {"it": "Avvio: {summary}. Procedo?", "en": "Start: {summary}. Proceed?"},
    "fallback.aborted": {"it": "annullato", "en": "cancelled"},
    "fallback.bad_choice": {"it": "scelta non valida", "en": "invalid choice"},
    "fallback.page": {"it": "  pagina {page}: {status}", "en": "  page {page}: {status}"},
    "fallback.done": {"it": "completato: {path}", "en": "done: {path}"},
    "fallback.failed": {"it": "errore: {error}", "en": "error: {error}"},
    "fallback.retry": {"it": "riprova", "en": "try again"},
}


def set_language(lang: str | None) -> str:
    global _language
    code = (lang or "").strip().lower()[:2]
    _language = code if code in LANGUAGES else "it"
    return _language


def get_language() -> str:
    return _language


def set_ascii(enabled: bool) -> None:
    global _ascii
    _ascii = bool(enabled)


def ascii_mode() -> bool:
    return _ascii


def T(key: str, **kwargs) -> str:
    """Stringa nella lingua corrente (fallback: italiano, poi la chiave)."""
    entry = _STRINGS.get(key)
    if entry is None:  # pragma: no cover - chiave sbagliata: visibile in test
        return key
    text = entry.get(_language) or entry.get("it") or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):  # pragma: no cover
            return text
    return text


@dataclass(frozen=True)
class TerminalProfile:
    isatty: bool
    minimal: bool  # TERM=dumb o assente: niente Textual
    utf8: bool
    no_color: bool
    dark: bool


def probe_terminal() -> TerminalProfile:
    """Rilevamento best-effort del terminale (per Textual vs wizard a righe)."""
    try:
        isatty = bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):  # pragma: no cover - stream chiusi
        isatty = False

    term = (os.environ.get("TERM") or "").strip().lower()
    minimal = term == "dumb" or (not term and os.name != "nt")

    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    utf8 = any(
        "utf" in value.lower()
        for value in (
            encoding,
            os.environ.get("LC_ALL", ""),
            os.environ.get("LC_CTYPE", ""),
            os.environ.get("LANG", ""),
        )
    ) or bool(getattr(sys.flags, "utf8_mode", 0))

    no_color = "NO_COLOR" in os.environ
    dark = _detect_dark()
    return TerminalProfile(
        isatty=isatty, minimal=minimal, utf8=utf8, no_color=no_color, dark=dark
    )


def _detect_dark() -> bool:
    """Sfondo scuro? ``COLORFGBG`` (es. ``15;0``) è l'unico indizio portabile."""
    value = (os.environ.get("COLORFGBG") or "").strip()
    if ";" in value:
        try:
            background = int(value.rsplit(";", 1)[-1])
            return background < 8
        except ValueError:
            pass
    return True
