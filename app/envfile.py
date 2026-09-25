"""Configurazione su file (``noesis.env``): schema, validazione, I/O atomico.

Questo modulo è la **fonte unica** per:

* leggere/scrivere il file di configurazione (stesse variabili di ``Settings``);
* l'**elenco delle impostazioni** modificabili (nome, tipo, default, limiti,
  descrizione IT/EN, gruppo, se è un segreto, se è modificabile dal web);
* la **validazione** dei valori (tipo + intervallo + scelte).

Lo usano la pagina ``/settings`` e il comando ``noesis config``, così web e
console non possono divergere. È **solo standard library**: nessuna dipendenza
da FastAPI, così ``tools/noesis.py`` lo importa anche prima che i venv esistano.

Precedenza dei valori (come ``build_env`` della console): **ambiente > file >
default**. Qui ci limitiamo a leggere/scrivere il file: la fusione con
l'ambiente la fa :meth:`app.config.Settings.from_env`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "SettingSpec",
    "SETTINGS_SCHEMA",
    "GROUPS",
    "CONFIG_FILENAME",
    "CONFIG_HEADER",
    "parse_env_file",
    "render_env_file",
    "load_env_file",
    "save_env_file",
    "config_path",
    "spec_by_name",
    "specs_for_web",
    "specs_for_cli",
    "validate_value",
    "group_specs",
]

CONFIG_FILENAME = "noesis.env"

_ENV_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")

# Segnaposto commentato aggiunto in coda al file (per i segreti).
_SECRET_PLACEHOLDER = "OPENROUTER_API_KEY"

# Intestazione del file, condivisa da console e pagina web (unica fonte).
CONFIG_HEADER = """\
# Noesis PDF Cloner Service — configurazione
# Generato dalla console o dalla pagina /settings. È un file .env: le variabili
# sono le stesse lette dall'applicazione (vedi README, "Come si configura").
#
# HOST=0.0.0.0 rende il servizio raggiungibile dalla LAN; in locale puoi usare
# anche 127.0.0.1. OPENROUTER_API_KEY serve solo per il motore `llm`."""

_BOOL_TRUE = {"1", "true", "yes", "on", "sì", "si"}
_BOOL_FALSE = {"0", "false", "no", "off"}


# ── I/O del file ─────────────────────────────────────────────────────────────


def parse_env_file(text: str) -> dict[str, str]:
    """Estrae le coppie ``CHIAVE=valore`` (ignora commenti e righe vuote)."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def render_env_file(
    values: dict[str, str],
    *,
    header: str = "",
    secret_placeholder: str | None = None,
) -> str:
    """Serializza i valori in un file ``.env`` leggibile.

    Se ``secret_placeholder`` è indicato e la chiave non è presente, aggiunge in
    coda la riga commentata (così si vede *dove* andrebbe il segreto).
    """
    lines: list[str] = []
    if header:
        lines.append(header.rstrip("\n"))
    for key, value in values.items():
        lines.append(f"{key}={value}")
    if secret_placeholder and secret_placeholder not in values:
        lines.append("")
        lines.append(
            "# ── Segreti (solo da qui, mai nel codice) ───────────────────────"
        )
        lines.append(f"# {secret_placeholder}=")
    return "\n".join(lines).rstrip("\n") + "\n"


def config_path(data_dir: Path | str) -> Path:
    """Percorso del file di configurazione dentro la cartella dati."""
    return Path(data_dir) / CONFIG_FILENAME


def load_env_file(
    path: Path | str, *, defaults: dict[str, str] | None = None
) -> dict[str, str]:
    """Legge il file, sovrapponendolo ai ``defaults`` (se indicati)."""
    values = dict(defaults or {})
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    values.update(parse_env_file(text))
    return values


def save_env_file(
    path: Path | str,
    updates: dict[str, str] | None = None,
    *,
    remove: list[str] | tuple[str, ...] = (),
    defaults: dict[str, str] | None = None,
    overwrite: bool = False,
    header: str = CONFIG_HEADER,
) -> Path:
    """Scrive il file in modo **atomico** (``tmp`` + ``os.replace``).

    Di default **fonde** con il contenuto esistente (non perde chiavi non
    gestite); ``overwrite=True`` riscrive da zero. Su POSIX il file è ``0600``
    (può contenere segreti).
    """
    path = Path(path)
    existing: dict[str, str] = {}
    if not overwrite:
        if defaults:
            existing.update(defaults)
        existing.update(load_env_file(path))
    existing.update(updates or {})
    for key in remove:
        existing.pop(key, None)

    text = render_env_file(existing, header=header, secret_placeholder=_SECRET_PLACEHOLDER)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - filesystem senza chmod
            pass
    return path


# ── schema delle impostazioni ────────────────────────────────────────────────


@dataclass(frozen=True)
class SettingSpec:
    """Descrizione di una impostazione modificabile.

    ``field`` è l'attributo di :class:`app.config.Settings` che la contiene;
    ``index`` serve per i campi a dizionario (es. ``cost_cents_per_page["llm"]``).
    """

    name: str
    kind: str  # int | float | bool | str | path | choice
    default: str
    group: str
    desc_it: str = ""
    desc_en: str = ""
    field: str | None = None
    index: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    secret: bool = False
    web_editable: bool = True
    restart_required: bool = True


# Titoli dei gruppi (IT autoritativo, EN di cortesia).
GROUPS: tuple[tuple[str, str, str], ...] = (
    ("limits", "Limiti", "Limits"),
    ("performance", "Prestazioni", "Performance"),
    ("cleanup", "Pulizia", "Cleanup"),
    ("engine", "Motore", "Engine"),
    ("key", "Chiave OpenRouter", "OpenRouter key"),
    ("legal", "Legale e interfaccia", "Legal and interface"),
    ("costs", "Costi e stime", "Costs and estimates"),
    ("deploy", "Avanzate (riga di comando)", "Advanced (command line)"),
)


SETTINGS_SCHEMA: tuple[SettingSpec, ...] = (
    # ── Limiti ──────────────────────────────────────────────────────────────
    SettingSpec(
        "MAX_UPLOAD_MB", "int", "500", "limits",
        desc_it="Dimensione massima del PDF caricato (MB).",
        desc_en="Maximum size of the uploaded PDF (MB).",
        field="max_upload_mb", minimum=1,
    ),
    SettingSpec(
        "MAX_PAGES_PER_BLOCK", "int", "100", "limits",
        desc_it="Pagine per blocco di lavoro.",
        desc_en="Pages per work block.",
        field="max_pages_per_block", minimum=1,
    ),
    SettingSpec(
        "MAX_PAGES_TOTAL", "int", "5000", "limits",
        desc_it="Numero massimo di pagine per job.",
        desc_en="Maximum number of pages per job.",
        field="max_pages_total", minimum=1,
    ),
    SettingSpec(
        "MAX_QUEUE_SIZE", "int", "100", "limits",
        desc_it="Job in coda prima di rifiutarne di nuovi.",
        desc_en="Queued jobs before new ones are rejected.",
        field="max_queue_size", minimum=1,
    ),
    SettingSpec(
        "PAGE_TIMEOUT", "int", "900", "limits",
        desc_it="Tempo massimo per pagina (secondi).",
        desc_en="Maximum time per page (seconds).",
        field="page_timeout", minimum=1,
    ),
    SettingSpec(
        "RATE_LIMIT_PER_MINUTE", "int", "120", "limits",
        desc_it="Richieste API al minuto per client.",
        desc_en="API requests per minute per client.",
        field="rate_limit_per_minute", minimum=0,
    ),
    SettingSpec(
        "RATE_LIMIT_JOBS_PER_HOUR", "int", "60", "limits",
        desc_it="Job all'ora per client.",
        desc_en="Jobs per hour per client.",
        field="rate_limit_jobs_per_hour", minimum=0,
    ),
    # ── Prestazioni ─────────────────────────────────────────────────────────
    SettingSpec(
        "AUTOSIZE", "bool", "true", "performance",
        desc_it="Calcola da solo workers e concorrenza in base alla macchina.",
        desc_en="Automatically size workers and concurrency to the machine.",
        field="autosize",
    ),
    SettingSpec(
        "WORKERS", "int", "0", "performance",
        desc_it="Job in parallelo (0 = automatico).",
        desc_en="Parallel jobs (0 = automatic).",
        field="workers", minimum=0,
    ),
    SettingSpec(
        "PAGE_CONCURRENCY", "int", "0", "performance",
        desc_it="Pagine in parallelo per job (0 = automatico).",
        desc_en="Parallel pages per job (0 = automatic).",
        field="page_concurrency", minimum=0,
    ),
    SettingSpec(
        "MAX_ENGINE_PROCS", "int", "0", "performance",
        desc_it="Processi del motore simultanei (0 = automatico).",
        desc_en="Simultaneous engine processes (0 = automatic).",
        field="max_engine_procs", minimum=0,
    ),
    SettingSpec(
        "ENGINE_MEMORY_MB", "int", "800", "performance",
        desc_it="RAM stimata per processo del motore (MB).",
        desc_en="Estimated RAM per engine process (MB).",
        field="engine_memory_mb", minimum=100,
    ),
    SettingSpec(
        "MIN_FREE_DISK_MB", "int", "1024", "performance",
        desc_it="Disco libero minimo richiesto (MB).",
        desc_en="Minimum free disk required (MB).",
        field="min_free_disk_mb", minimum=0,
    ),
    SettingSpec(
        "MIN_FREE_RAM_MB", "int", "512", "performance",
        desc_it="RAM libera minima richiesta (MB).",
        desc_en="Minimum free RAM required (MB).",
        field="min_free_ram_mb", minimum=0,
    ),
    # ── Pulizia ─────────────────────────────────────────────────────────────
    SettingSpec(
        "JOB_RETENTION_HOURS", "int", "72", "cleanup",
        desc_it="Per quanto tenere i job conclusi (ore).",
        desc_en="How long to keep finished jobs (hours).",
        field="job_retention_hours", minimum=1,
    ),
    SettingSpec(
        "DOCUMENT_RETENTION_HOURS", "int", "24", "cleanup",
        desc_it="Per quanto tenere i PDF caricati (ore).",
        desc_en="How long to keep uploaded PDFs (hours).",
        field="document_retention_hours", minimum=1,
    ),
    SettingSpec(
        "THUMB_RETENTION_HOURS", "int", "168", "cleanup",
        desc_it="Per quanto tenere le anteprime (ore).",
        desc_en="How long to keep thumbnails (hours).",
        field="thumb_retention_hours", minimum=1,
    ),
    SettingSpec(
        "JANITOR_INTERVAL_SECONDS", "int", "600", "cleanup",
        desc_it="Ogni quanto fare pulizia (secondi).",
        desc_en="How often to clean up (seconds).",
        field="janitor_interval_seconds", minimum=30,
    ),
    # ── Motore ──────────────────────────────────────────────────────────────
    SettingSpec(
        "PDF2ZH_BIN", "path", "", "engine",
        desc_it="Percorso di pdf2zh_next (vuoto = rilevato da solo).",
        desc_en="Path to pdf2zh_next (empty = auto-detected).",
        field="pdf2zh_bin",
    ),
    SettingSpec(
        "PDF_LLM_MODEL", "str", "inception/mercury-2.5", "engine",
        desc_it="Modello LLM usato dal motore `llm` (OpenRouter).",
        desc_en="LLM model used by the `llm` engine (OpenRouter).",
        field="llm_model",
    ),
    SettingSpec(
        "PDF_LLM_BASE_URL", "str", "https://openrouter.ai/api/v1", "engine",
        desc_it="Endpoint del servizio LLM (OpenRouter).",
        desc_en="LLM service endpoint (OpenRouter).",
        field="llm_base_url",
    ),
    # ── Chiave (segreto) ────────────────────────────────────────────────────
    SettingSpec(
        "OPENROUTER_API_KEY", "str", "", "key",
        desc_it="Chiave del server per il motore LLM. Opzionale: gli utenti "
                "possono usare la propria (BYOK). Non viene mai mostrata.",
        desc_en="Server key for the LLM engine. Optional: users can bring their "
                "own (BYOK). It is never shown.",
        field="openrouter_api_key", secret=True,
    ),
    # ── Legale / interfaccia ────────────────────────────────────────────────
    SettingSpec(
        "HELP_URL", "str", "https://vigliafg.github.io/noesis-pdf-cloner-service/", "legal",
        desc_it="Indirizzo della guida aperta dal pulsante «Guida».",
        desc_en="Address of the guide opened by the “Guide” button.",
        field="help_url",
    ),
    SettingSpec(
        "TERMS_VERSION", "str", "1.0", "legal",
        desc_it="Versione dei Termini mostrata e richiesta all'utente.",
        desc_en="Terms version shown and required from the user.",
        field="terms_version",
    ),
    SettingSpec(
        "REQUIRE_TERMS_ACCEPTANCE", "bool", "false", "legal",
        desc_it="Chiedi di accettare i Termini prima di creare un job.",
        desc_en="Ask to accept the Terms before creating a job.",
        field="require_terms_acceptance",
    ),
    # ── Costi / stime (avanzate) ────────────────────────────────────────────
    SettingSpec(
        "COST_CENTS_PER_PAGE_GOOGLE", "int", "0", "costs",
        desc_it="Prezzo per pagina del motore google (centesimi; 0 = gratis).",
        desc_en="Price per page for the google engine (cents; 0 = free).",
        field="cost_cents_per_page", index="google", minimum=0,
    ),
    SettingSpec(
        "COST_CENTS_PER_PAGE_BING", "int", "0", "costs",
        desc_it="Prezzo per pagina del motore bing (centesimi; 0 = gratis).",
        desc_en="Price per page for the bing engine (cents; 0 = free).",
        field="cost_cents_per_page", index="bing", minimum=0,
    ),
    SettingSpec(
        "COST_CENTS_PER_PAGE_LLM", "int", "0", "costs",
        desc_it="Prezzo per pagina del motore llm (centesimi; 0 = gratis).",
        desc_en="Price per page for the llm engine (cents; 0 = free).",
        field="cost_cents_per_page", index="llm", minimum=0,
    ),
    SettingSpec(
        "ESTIMATE_MS_PER_PAGE_GOOGLE", "int", "0", "costs",
        desc_it="Stima dei millisecondi per pagina (google). 0 = default interno.",
        desc_en="Estimated milliseconds per page (google). 0 = internal default.",
        field="estimate_ms_per_page", index="google", minimum=0,
    ),
    SettingSpec(
        "ESTIMATE_MS_PER_PAGE_BING", "int", "0", "costs",
        desc_it="Stima dei millisecondi per pagina (bing). 0 = default interno.",
        desc_en="Estimated milliseconds per page (bing). 0 = internal default.",
        field="estimate_ms_per_page", index="bing", minimum=0,
    ),
    SettingSpec(
        "ESTIMATE_MS_PER_PAGE_LLM", "int", "0", "costs",
        desc_it="Stima dei millisecondi per pagina (llm). 0 = default interno.",
        desc_en="Estimated milliseconds per page (llm). 0 = internal default.",
        field="estimate_ms_per_page", index="llm", minimum=0,
    ),
    # ── Avanzate: solo riga di comando ──────────────────────────────────────
    SettingSpec(
        "HOST", "str", "0.0.0.0", "deploy",
        desc_it="Indirizzo di ascolto. Modificarlo può rendere il servizio "
                "irraggiungibile: solo da riga di comando.",
        desc_en="Listening address. Changing it may make the service "
                "unreachable: command line only.",
        field="host", web_editable=False,
    ),
    SettingSpec(
        "PORT", "int", "18080", "deploy",
        desc_it="Porta del servizio. Solo da riga di comando.",
        desc_en="Service port. Command line only.",
        field="port", minimum=1, maximum=65535, web_editable=False,
    ),
    SettingSpec(
        "ROLE", "choice", "all", "deploy",
        desc_it="Ruolo del processo: all, api o worker. Solo da riga di comando.",
        desc_en="Process role: all, api or worker. Command line only.",
        field="role", choices=("all", "api", "worker"), web_editable=False,
    ),
    SettingSpec(
        "QUEUE_BACKEND", "choice", "db", "deploy",
        desc_it="Backend della coda: db o memory. Solo da riga di comando.",
        desc_en="Queue backend: db or memory. Command line only.",
        field="queue_backend", choices=("db", "memory"), web_editable=False,
    ),
    SettingSpec(
        "DATA_DIR", "path", "", "deploy",
        desc_it="Cartella dati (upload, cache, log, database). Solo da riga di comando.",
        desc_en="Data folder (uploads, cache, logs, database). Command line only.",
        field="data_dir", web_editable=False,
    ),
    SettingSpec(
        "CACHE_ROOT", "path", "", "deploy",
        desc_it="Cartella cache esterna (vuoto = dentro la cartella dati). "
                "Solo da riga di comando.",
        desc_en="External cache folder (empty = inside the data folder). "
                "Command line only.",
        field="cache_root", web_editable=False,
    ),
)

_BY_NAME: dict[str, SettingSpec] = {spec.name: spec for spec in SETTINGS_SCHEMA}


def spec_by_name(name: str) -> SettingSpec | None:
    """Cerca una impostazione per nome (case-insensitive)."""
    if name in _BY_NAME:
        return _BY_NAME[name]
    upper = (name or "").strip().upper()
    return _BY_NAME.get(upper)


def specs_for_web() -> tuple[SettingSpec, ...]:
    """Impostazioni modificabili dalla pagina (inclusi i segreti write-only)."""
    return tuple(spec for spec in SETTINGS_SCHEMA if spec.web_editable)


def specs_for_cli() -> tuple[SettingSpec, ...]:
    """Tutte le impostazioni, comprese quelle avanzate/solo-console."""
    return SETTINGS_SCHEMA


def group_specs(web_only: bool = True) -> list[tuple[str, str, str, list[SettingSpec]]]:
    """Raggruppa lo schema per sezione, nell'ordine di :data:`GROUPS`."""
    source = specs_for_web() if web_only else SETTINGS_SCHEMA
    result: list[tuple[str, str, str, list[SettingSpec]]] = []
    for group_id, title_it, title_en in GROUPS:
        members = [spec for spec in source if spec.group == group_id]
        if members:
            result.append((group_id, title_it, title_en, members))
    return result


# ── validazione ──────────────────────────────────────────────────────────────


class InvalidValue(ValueError):
    """Valore non valido per una impostazione."""


def _bounds(spec: SettingSpec, value: float) -> float:
    if spec.minimum is not None and value < spec.minimum:
        raise InvalidValue(f"{spec.name}: minimo {spec.minimum:g}")
    if spec.maximum is not None and value > spec.maximum:
        raise InvalidValue(f"{spec.name}: massimo {spec.maximum:g}")
    return value


def validate_value(spec: SettingSpec, raw: str | None) -> str:
    """Normalizza e valida un valore; solleva :class:`InvalidValue` se invalido."""
    value = "" if raw is None else str(raw).strip()

    if spec.kind == "bool":
        low = value.lower()
        if low in _BOOL_TRUE:
            return "true"
        if low in _BOOL_FALSE:
            return "false"
        raise InvalidValue(f"{spec.name}: atteso true/false, ricevuto {value!r}")

    if spec.kind == "int":
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise InvalidValue(f"{spec.name}: atteso un numero intero, ricevuto {value!r}")
        _bounds(spec, number)
        return str(number)

    if spec.kind == "float":
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise InvalidValue(f"{spec.name}: atteso un numero, ricevuto {value!r}")
        _bounds(spec, number)
        return str(number)

    if spec.kind == "choice":
        if value not in spec.choices:
            raise InvalidValue(
                f"{spec.name}: scegli tra {', '.join(spec.choices)} (ricevuto {value!r})"
            )
        return value

    # str | path
    return value
