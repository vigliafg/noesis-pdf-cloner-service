#!/usr/bin/env python3
"""noesis — console unica di installazione e gestione del servizio.

Un solo punto di verità, **solo standard library**, multipiattaforma
(Linux · macOS · WSL · Windows nativo). I gusci ``install.sh`` / ``install.ps1``
e i launcher ``./noesis`` / ``noesis.cmd`` delegano qui.

Comandi principali::

    noesis install     crea venv + motore, config, servizio, pre-warm
    noesis start/stop/restart/status/logs
    noesis doctor      diagnosi (cosa manca e perché)
    noesis open        apre il frontend nel browser
    noesis service     install/uninstall/status del servizio
    noesis bundle      crea un pacchetto offline (wheel + modelli)
    noesis update      aggiorna il codice e le dipendenze
    noesis uninstall   rimuove il servizio e, su scelta, venv/motore/dati/cache

Il file di configurazione è ``<data_dir>/noesis.env``: sono le stesse
variabili d'ambiente che l'applicazione già legge (``Settings.from_env``).
"""

from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

# ── costanti ────────────────────────────────────────────────────────────────

APP_NAME = "noesis-pdf-cloner-service"
SERVICE_NAME = "noesis-pdf-cloner-service"
SERVICE_LABEL = "com.noesis.pdf-cloner-service"
DEFAULT_PORT = 18080
DEFAULT_HOST = "0.0.0.0"
REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = "requirements.txt"
REQUIREMENTS_ENGINE = "requirements-engine.txt"
REQUIREMENTS_ENGINE_LOCK = "requirements-engine.lock"
PYTHON_VERSION = "3.12"
UV_INSTALL_SH = "https://astral.sh/uv/install.sh"
UV_INSTALL_PS1 = "https://astral.sh/uv/install.ps1"
BABELDOC_CACHE_ENV = ("BABELDOC_CACHE_DIR", "BABELDOC_CACHE")
STOP_TIMEOUT = 20.0
UFW_CONF = Path("/etc/ufw/ufw.conf")

# Configurazione scritta di default (stesse chiavi lette da app/config.py).
DEFAULT_CONFIG: dict[str, str] = {
    "HOST": DEFAULT_HOST,
    "PORT": str(DEFAULT_PORT),
    "ROLE": "all",
    "QUEUE_BACKEND": "db",
    "AUTOSIZE": "true",
}

CONFIG_HEADER = """\
# Noesis PDF Cloner Service — configurazione
# Generato da `noesis install`. È un file .env: le variabili sono le stesse
# lette dall'applicazione (vedi README, "Configurazione").
#
# HOST=0.0.0.0 rende il servizio raggiungibile dalla LAN; in locale puoi usare
# anche 127.0.0.1. OPENROUTER_API_KEY serve solo per il motore `llm`.
"""


# ── ambiente / piattaforma ──────────────────────────────────────────────────


def is_windows() -> bool:
    return os.name == "nt"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def is_wsl() -> bool:
    """True se giriamo dentro Windows Subsystem for Linux."""
    if not is_linux():
        return False
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        text = Path("/proc/version").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "microsoft" in text.lower()


def has_display() -> bool:
    """True se c'è una sessione grafica (per l'auto-apertura del browser)."""
    if is_macos() or is_windows():
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def venv_python_in(venv: Path) -> Path:
    if is_windows():
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def venv_bin_dir(venv: Path) -> Path:
    return venv / ("Scripts" if is_windows() else "bin")


def invoking_user() -> str:
    """Utente effettivo dell'installazione, considerando ``sudo`` (``SUDO_USER``)."""
    return os.environ.get("SUDO_USER") or os.environ.get("USER") or os.environ.get("LOGNAME") or ""


def invoking_home() -> Path:
    """Home dell'utente effettivo.

    Con ``sudo`` l'ambiente viene riscritto (``HOME=/root``, ``USER=root``): per
    ``--mode system`` serve invece l'home dell'utente che ha invocato, così l'unit
    punta alla sua installazione (``EnvironmentFile`` e ``User``).
    """
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        try:
            import pwd

            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except (ImportError, KeyError):
            pass
    return Path.home()


def default_data_dir() -> Path:
    """Cartella dati standard dell'OS, dedicata a questa applicazione."""
    home = invoking_home()
    if is_windows():
        base = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
        return base / APP_NAME
    if is_macos():
        return home / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else (home / ".local" / "share")
    return base / APP_NAME


def platform_tag() -> str:
    system = platform.system().lower() or "unknown"
    machine = (platform.machine() or "unknown").lower()
    return f"{system}-{machine}"


def python_exe() -> str:
    """Interprete corrente (o quello del venv se disponibile)."""
    return sys.executable or "python3"


# ── UI ──────────────────────────────────────────────────────────────────────

_LEVEL_ICON = {"info": "·", "ok": "✔", "warn": "!", "error": "✗"}
_ASCII_ICON = {"info": "-", "ok": "+", "warn": "!", "error": "x"}


def _configure_stdio() -> None:
    """Su Windows il default è cp1252: forza UTF-8 (best effort)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError, OSError):
            pass


def _stream_supports_unicode() -> bool:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        "✔".encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


class UI:
    """Output leggibile (o JSON per l'automazione)."""

    def __init__(self, *, json_mode: bool = False, quiet: bool = False, color: bool | None = None) -> None:
        self.json_mode = json_mode
        self.quiet = quiet
        self.events: list[dict[str, str]] = []
        self.icons = _LEVEL_ICON if _stream_supports_unicode() else _ASCII_ICON
        if color is None:
            color = sys.stdout.isatty() and not json_mode and os.environ.get("NO_COLOR") is None
        self.color = bool(color)

    def _paint(self, level: str, message: str) -> str:
        icon = self.icons[level]
        if not self.color:
            return f"{icon} {message}"
        codes = {"info": "36", "ok": "32", "warn": "33", "error": "31"}
        return f"\033[{codes[level]}m{icon}\033[0m {message}"

    def emit(self, level: str, message: str) -> None:
        self.events.append({"level": level, "message": message})
        if self.json_mode or self.quiet:
            return
        print(self._paint(level, message))

    def info(self, message: str) -> None:
        self.emit("info", message)

    def ok(self, message: str) -> None:
        self.emit("ok", message)

    def warn(self, message: str) -> None:
        self.emit("warn", message)

    def error(self, message: str) -> None:
        self.emit("error", message)

    def section(self, title: str) -> None:
        if self.json_mode or self.quiet:
            return
        print(f"\n{title}" if self.color else f"\n== {title} ==")

    def is_interactive(self) -> bool:
        """True se possiamo chiedere input (TTY, non ``--json``/``--quiet``)."""
        return (
            not self.json_mode
            and not self.quiet
            and sys.stdin is not None
            and sys.stdout is not None
            and sys.stdin.isatty()
            and sys.stdout.isatty()
        )

    def ask(self, question: str, *, default: str = "") -> str:
        """Legge una riga da stdin (vuoto se non interattivo)."""
        if not self.is_interactive():
            return default
        try:
            return input(question).strip()
        except (EOFError, KeyboardInterrupt):  # pragma: no cover - TTY
            return default

    def ask_yes_no(self, question: str, *, default: bool = False) -> bool:
        if not self.is_interactive():
            return default
        suffix = " [S/n]" if default else " [s/N]"
        answer = self.ask(f"{question}{suffix} ").lower()
        if not answer:
            return default
        return answer in {"s", "si", "sì", "y", "yes"}

    def prompt_secret(self, question: str) -> str:
        """Legge un segreto **senza eco** (vuoto se non interattivo)."""
        if not self.is_interactive():
            return ""
        try:
            return getpass.getpass(question).strip()
        except (EOFError, KeyboardInterrupt):  # pragma: no cover - TTY
            return ""

    def link(self, url: str) -> str:
        """Rende ``url`` cliccabile (OSC 8) se il terminale lo supporta."""
        if not self.color:
            return url
        return f"\033]8;;{url}\033\\{url}\033]8;;\033\\"

    def finish(self) -> None:
        if self.json_mode:
            print(json.dumps({"events": self.events}, ensure_ascii=False, indent=2))


# ── esecuzione comandi ──────────────────────────────────────────────────────

Runner = Callable[..., "subprocess.CompletedProcess[str]"]

DRY_RUN = False


def run_command(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    capture: bool = False,
    ui: UI | None = None,
) -> subprocess.CompletedProcess[str]:
    """Esegue un comando, rispettando ``--dry-run``."""
    rendered = " ".join(str(c) for c in cmd)
    if DRY_RUN:
        if ui:
            ui.info(f"[dry-run] {rendered}")
        return subprocess.CompletedProcess(list(cmd), 0, "", "")
    kwargs: dict[str, Any] = {"cwd": str(cwd) if cwd else None, "env": env}
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        result = subprocess.run(list(cmd), check=False, **kwargs)  # noqa: S603
    except FileNotFoundError as exc:
        raise CommandError(f"comando non trovato: {cmd[0]}") from exc
    if check and result.returncode != 0:
        detail = ""
        if capture and result.stdout:
            detail = f": {result.stdout.strip()[-400:]}"
        raise CommandError(f"comando fallito ({result.returncode}): {rendered}{detail}")
    return result


class CommandError(RuntimeError):
    """Errore di esecuzione di un comando esterno."""


# ── configurazione (noesis.env) ─────────────────────────────────────────────

_ENV_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")


def parse_env_file(text: str) -> dict[str, str]:
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


def config_path(data_dir: Path) -> Path:
    return Path(data_dir) / "noesis.env"


def load_config(data_dir: Path) -> dict[str, str]:
    path = config_path(data_dir)
    if not path.is_file():
        return dict(DEFAULT_CONFIG)
    values = dict(DEFAULT_CONFIG)
    values.update(parse_env_file(path.read_text(encoding="utf-8")))
    return values


def render_config(values: dict[str, str]) -> str:
    lines = [CONFIG_HEADER]
    for key, value in values.items():
        lines.append(f"{key}={value}")
    lines.append("")
    lines.append("# ── Segreti (solo da qui, mai nel codice) ───────────────────────")
    if "OPENROUTER_API_KEY" not in values:
        lines.append("# OPENROUTER_API_KEY=")
    return "\n".join(lines) + "\n"


def save_config(data_dir: Path, values: dict[str, str], *, overwrite: bool = False) -> Path:
    path = config_path(data_dir)
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    if path.is_file() and not overwrite:
        merged = load_config(data_dir)
        merged.update({k: v for k, v in values.items()})
        path.write_text(render_config(merged), encoding="utf-8")
    else:
        path.write_text(render_config(values), encoding="utf-8")
    # Il file può contenere segreti (OPENROUTER_API_KEY): su POSIX accesso solo
    # all'utente. Su Windows si affida alla protezione per-utente del profilo.
    if not is_windows():
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - filesystem senza chmod
            pass
    return path


def ensure_openrouter_key(data_dir: Path, ui: UI) -> None:
    """Chiede (una volta) la chiave OpenRouter e la salva in ``noesis.env``.

    Opzionale: serve solo al motore ``llm``. Se è già nell'ambiente o nella
    config non chiede nulla; in non interattivo lascia un suggerimento.
    """
    if os.environ.get("OPENROUTER_API_KEY", "").strip():
        ui.ok("chiave OpenRouter: presente nell'ambiente")
        return
    if load_config(data_dir).get("OPENROUTER_API_KEY", "").strip():
        ui.ok("chiave OpenRouter: già in noesis.env")
        return
    if not ui.is_interactive():
        ui.info(
            "chiave OpenRouter assente (opzionale, motore `llm`): aggiungila in "
            f"{config_path(data_dir)} come OPENROUTER_API_KEY=…"
        )
        return
    ui.section("Chiave OpenRouter (opzionale, per il motore LLM)")
    ui.info("La trovi su https://openrouter.ai/keys — premi Invio per saltare.")
    key = ui.prompt_secret("Chiave: ")
    if not key:
        ui.info(
            "nessuna chiave inserita: potrai aggiungerla in "
            f"{config_path(data_dir)} (OPENROUTER_API_KEY=…) e riavviare con `noesis restart`"
        )
        return
    save_config(data_dir, {"OPENROUTER_API_KEY": key})
    ui.ok(
        f"chiave OpenRouter salvata in {config_path(data_dir)} "
        f"(0600, lunghezza {len(key)})"
    )


def print_health_report(data_dir: Path, ui: UI) -> None:
    """Stampa il **report completo** di salute/preflight riusando ``app.diagnostics``.

    Esegue nella venv ``run_all`` (ambiente, uv, motore, rete, chiave, modello,
    catena gratuita): gli stessi check di ``noesis-cloner --doctor`` e di
    ``GET /api/v1/health?deep=1``. Salta se la venv non è pronta o in dry-run.
    """
    if DRY_RUN:
        return
    venv = venv_python_in(service_venv())
    if not venv.is_file():
        return
    script = (
        "import json\n"
        "from app.config import Settings\n"
        "from app.diagnostics import build_context, run_all, health_status\n"
        "results = run_all(build_context(Settings.from_env()))\n"
        "print(json.dumps({'status': health_status(results), 'checks': [\n"
        "    {'id': c.id, 'status': c.status, 'code': c.code,\n"
        "     'message': c.message, 'fix': c.fix, 'data': c.data} for c in results]}))\n"
    )
    result = run_command(
        [str(venv), "-c", script],
        check=False, capture=True, ui=ui, env=build_env(data_dir), cwd=REPO_ROOT,
    )
    lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
    try:
        payload = json.loads(lines[-1]) if lines else {}
    except ValueError:
        payload = {}
    checks = payload.get("checks") or []
    if not checks:
        ui.warn("report di salute non disponibile (diagnostica non eseguibile)")
        return
    levels = {"ok": "ok", "warn": "warn", "fail": "error", "skip": "info"}
    ui.section("Salute e preflight")
    for check in checks:
        extra = ""
        data = check.get("data") or {}
        if check.get("id") == "engine.bin" and check.get("status") == "ok":
            extra = f" {data.get('path', '')}"
        elif check.get("id") == "key.present" and data.get("masked"):
            extra = f" {data['masked']} [{data.get('source', '')}]"
        elif check.get("message"):
            extra = f" {check['message']}"
        if check.get("fix"):
            extra += f" [fix: {check['fix']}]"
        ui.emit(levels.get(check.get("status", "info"), "info"),
                f"{check.get('id', '?')}{extra}")
    ui.info(f"→ esito: {payload.get('status', '?')}")


def verify_openrouter_key(data_dir: Path, ui: UI) -> bool:
    """Verifica **chiave e modello** OpenRouter riusando ``app.diagnostics``.

    Esegue nella venv del servizio gli stessi check di ``/api/v1/health?deep=1``
    e di ``noesis doctor`` (``key.valid``, ``key.credits``, ``llm.model``):
    nessuna duplicazione. Salta se non c'è chiave, se la venv non è pronta o in
    ``--dry-run``. Ritorna ``True`` se tutti i check sono ok.
    """
    if DRY_RUN:
        return False
    key = (
        os.environ.get("OPENROUTER_API_KEY")
        or load_config(data_dir).get("OPENROUTER_API_KEY", "")
    ).strip()
    if not key:
        return False
    venv = venv_python_in(service_venv())
    if not venv.is_file():
        return False
    script = (
        "import json\n"
        "from app.config import Settings\n"
        "from app.diagnostics import build_context, check_key_valid, check_key_credits, check_llm_model\n"
        "ctx = build_context(Settings.from_env())\n"
        "checks = [check_key_valid(ctx.key, ctx.base_url),\n"
        "          check_key_credits(ctx.key, ctx.base_url),\n"
        "          check_llm_model(ctx.key, ctx.model, ctx.base_url)]\n"
        "print(json.dumps([{'id': c.id, 'status': c.status, 'code': c.code,\n"
        "                   'message': c.message, 'data': c.data} for c in checks]))\n"
    )
    result = run_command(
        [str(venv), "-c", script],
        check=False, capture=True, ui=ui, env=build_env(data_dir), cwd=REPO_ROOT,
    )
    lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
    try:
        checks = json.loads(lines[-1]) if lines else []
    except ValueError:
        checks = []
    if not checks:
        ui.warn("verifica chiave/modello non riuscita (diagnostica non disponibile)")
        return False
    labels = {
        "key.valid": "chiave OpenRouter",
        "key.credits": "credito OpenRouter",
        "llm.model": "modello LLM",
    }
    ok = True
    for check in checks:
        label = labels.get(check.get("id"), check.get("id", "check"))
        status = check.get("status", "warn")
        detail = check.get("message") or ""
        if check.get("id") == "key.credits" and status == "ok":
            remaining = (check.get("data") or {}).get("limit_remaining")
            if isinstance(remaining, (int, float)):
                detail = f"residuo {remaining}"
        if status == "ok":
            ui.ok(f"{label}: ok" + (f" — {detail}" if detail else ""))
        elif status == "skip":
            ui.info(f"{label}: saltato" + (f" — {detail}" if detail else ""))
        else:
            ok = False
            ui.warn(f"{label}: {check.get('code', status)}" + (f" — {detail}" if detail else ""))
    return ok


def resolve_host_port(args: argparse.Namespace, data_dir: Path) -> tuple[str, int]:
    """Host/porta: opzione CLI > variabile d'ambiente > config > default."""
    config = load_config(data_dir)
    host = getattr(args, "host", None) or os.environ.get("HOST") or config.get("HOST", DEFAULT_HOST)
    raw_port = getattr(args, "port", None) or os.environ.get("PORT") or config.get("PORT", DEFAULT_PORT)
    return host, int(raw_port)


def build_env(data_dir: Path, *, base: dict[str, str] | None = None, host: str | None = None, port: int | None = None) -> dict[str, str]:
    """Ambiente per i processi figli: shell > config > default.

    Le variabili già presenti nella shell vincono (utili per override puntuali,
    es. ``ROLE=api ./noesis run``); il file di config fornisce i default.
    """
    env = dict(base if base is not None else os.environ)
    for key, value in load_config(data_dir).items():
        env.setdefault(key, value)
    env.setdefault("DATA_DIR", str(data_dir))
    if host:
        env["HOST"] = host
    if port:
        env["PORT"] = str(port)
    return env


# ── percorsi ────────────────────────────────────────────────────────────────


def service_venv() -> Path:
    return REPO_ROOT / ".venv"


def engine_venv() -> Path:
    return REPO_ROOT / ".venv2"


def engine_binary() -> Path | None:
    """Trova ``pdf2zh_next``: env ``PDF2ZH_BIN`` → ``.venv2`` accanto al repo."""
    override = os.environ.get("PDF2ZH_BIN")
    if override and Path(override).expanduser().is_file():
        return Path(override).expanduser()
    exe = "pdf2zh_next.exe" if is_windows() else "pdf2zh_next"
    for sub in ("bin", "Scripts"):
        candidate = engine_venv() / sub / exe
        if candidate.is_file():
            return candidate
    return None


def logs_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "logs"


def service_log(data_dir: Path) -> Path:
    return logs_dir(data_dir) / "noesis.out"


def pid_path(data_dir: Path) -> Path:
    return Path(data_dir) / "noesis.pid"


def cache_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "cache"


def babeldoc_cache_dir() -> Path:
    for key in BABELDOC_CACHE_ENV:
        value = os.environ.get(key)
        if value:
            return Path(value)
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".cache")
    return base / "babeldoc"


def ensure_data_dirs(data_dir: Path) -> None:
    for path in (data_dir, cache_dir(data_dir), logs_dir(data_dir), Path(data_dir) / "documents"):
        path.mkdir(parents=True, exist_ok=True)


# ── uv ──────────────────────────────────────────────────────────────────────


def find_uv() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    candidates = [Path.home() / ".local" / "bin" / "uv", Path.home() / ".cargo" / "bin" / "uv"]
    if is_windows():
        candidates.append(Path.home() / ".local" / "bin" / "uv.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def ensure_uv(ui: UI) -> str:
    existing = find_uv()
    if existing:
        return existing
    ui.info("uv non trovato: lo installo…")
    if is_windows():
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"irm {UV_INSTALL_PS1} | iex"]
    else:
        cmd = ["sh", "-c", f"curl -LsSf {UV_INSTALL_SH} | sh"]
    run_command(cmd, check=True, ui=ui)
    found = find_uv()
    if not found:
        raise CommandError(
            "uv installato ma non trovato nel PATH: riapri il terminale o aggiungi ~/.local/bin al PATH"
        )
    ui.ok(f"uv installato: {found}")
    return found


# ── installazione venv e dipendenze ─────────────────────────────────────────


def ensure_venv(uv: str, venv: Path, ui: UI) -> None:
    if venv_python_in(venv).is_file():
        return
    ui.info(f"creo {venv.name} (Python {PYTHON_VERSION})…")
    run_command([uv, "venv", "--python", PYTHON_VERSION, str(venv)], ui=ui)


def install_requirements(uv: str, venv: Path, requirements: Iterable[str], ui: UI, *, offline: Path | None = None) -> None:
    reqs = [str(REPO_ROOT / name) for name in requirements if (REPO_ROOT / name).is_file()]
    if not reqs:
        return
    cmd = [uv, "pip", "install", "--python", str(venv_python_in(venv)), "-q"]
    if offline is not None:
        cmd += ["--no-index", "--find-links", str(offline)]
    for req in reqs:
        cmd += ["-r", req]
    run_command(cmd, ui=ui)


def ensure_service_venv(uv: str, ui: UI, *, offline: Path | None = None) -> None:
    venv = service_venv()
    ensure_venv(uv, venv, ui)
    ui.info("installo le dipendenze del servizio…")
    install_requirements(uv, venv, [REQUIREMENTS], ui, offline=offline)


def ensure_engine_venv(uv: str, ui: UI, *, offline: Path | None = None) -> None:
    venv = engine_venv()
    ensure_venv(uv, venv, ui)
    ui.info("installo il motore pdf2zh_next (può richiedere qualche minuto)…")
    install_requirements(uv, venv, [engine_requirement()], ui, offline=offline)


def engine_requirement() -> str:
    """Manifest del motore: il lockfile (solo Linux) se presente, altrimenti il txt.

    Il lock è risolto per Linux (dove gira anche il container); su macOS/Windows
    si usa il manifest per non vincolare a versioni pensate per Linux.
    """
    if sys.platform.startswith("linux") and (REPO_ROOT / REQUIREMENTS_ENGINE_LOCK).is_file():
        return REQUIREMENTS_ENGINE_LOCK
    return REQUIREMENTS_ENGINE


def warm_engine(ui: UI) -> bool:
    """Pre-warm best effort dei modelli BabelDOC (scarica al primo uso)."""
    binary = engine_binary()
    if binary is None:
        ui.warn("motore non trovato: salto il pre-warm")
        return False
    ui.info("pre-warm dei modelli del motore (best effort)…")
    try:
        run_command([str(binary), "--version"], check=False, capture=True, ui=ui)
    except CommandError:
        return False
    ui.ok("pre-warm completato")
    return True


# ── rete: IP e URL ──────────────────────────────────────────────────────────


def local_ip() -> str | None:
    """IP primario della macchina (per l'URL in LAN)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def server_urls(host: str, port: int) -> list[str]:
    urls: list[str] = []
    local = f"http://127.0.0.1:{port}"
    urls.append(local)
    if host in {"0.0.0.0", "::"}:
        ip = local_ip()
        if ip and f"http://{ip}:{port}" != local:
            urls.append(f"http://{ip}:{port}")
    elif host not in {"127.0.0.1", "localhost"}:
        urls.append(f"http://{host}:{port}")
    return urls


def health_check(host: str, port: int, timeout: float = 2.0) -> bool:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    try:
        with urllib.request.urlopen(f"http://{probe_host}:{port}/api/v1/health", timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError):
        return False


def port_listening(host: str, port: int, *, timeout: float = 1.0) -> bool:
    """True se qualcosa è già in ascolto sulla porta (prova di connessione TCP)."""
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    try:
        with socket.create_connection((probe_host, port), timeout=timeout):
            return True
    except OSError:
        return False


def warn_if_port_busy(host: str, port: int, ui: UI) -> bool:
    """Avvisa se la porta è occupata da un processo che **non** è il nostro servizio."""
    if port_listening(host, port) and not health_check(host, port):
        ui.warn(f"porta {port} già in ascolto da un altro processo: il servizio potrebbe non avviarsi")
        return True
    return False


def wait_for_health(host: str, port: int, *, timeout: float = 30.0, interval: float = 1.0) -> bool:
    """Attende che il server risponda su ``/api/v1/health`` (fino a ``timeout`` secondi)."""
    deadline = time.monotonic() + timeout
    while True:
        if health_check(host, port):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


# ── gestione processo (background) ──────────────────────────────────────────


def read_pid(data_dir: Path) -> int | None:
    path = pid_path(data_dir)
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def write_pid(data_dir: Path, pid: int) -> None:
    pid_path(data_dir).write_text(str(pid), encoding="utf-8")


def remove_pid(data_dir: Path) -> None:
    try:
        pid_path(data_dir).unlink()
    except FileNotFoundError:
        pass


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if is_windows():
        result = run_command(["tasklist", "/FI", f"PID eq {pid}"], check=False, capture=True)
        return str(pid) in (result.stdout or "")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def uvicorn_command(venv: Path, host: str, port: int) -> list[str]:
    return [
        str(venv_python_in(venv)),
        "-m",
        "uvicorn",
        "app.main:app",
        "--workers",
        "1",
        "--host",
        host,
        "--port",
        str(port),
    ]


def start_background(data_dir: Path, ui: UI, *, host: str, port: int) -> int:
    """Avvia il server in background, log su file, PID su file."""
    if read_pid(data_dir) and process_alive(read_pid(data_dir) or 0):
        ui.info("servizio già attivo")
        return 0
    ensure_data_dirs(data_dir)
    env = build_env(data_dir, host=host, port=port)
    log = service_log(data_dir)
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = uvicorn_command(service_venv(), host, port)
    if DRY_RUN:
        ui.info(f"[dry-run] {' '.join(cmd)} > {log}")
        return 0
    with open(log, "ab") as handle:
        kwargs: dict[str, Any] = {"cwd": str(REPO_ROOT), "env": env, "stdout": handle, "stderr": subprocess.STDOUT}
        if is_windows():
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(cmd, **kwargs)  # noqa: S603
    write_pid(data_dir, process.pid)
    ui.ok(f"servizio avviato (pid {process.pid})")
    return process.pid


def stop_background(data_dir: Path, ui: UI, *, timeout: float = STOP_TIMEOUT) -> bool:
    pid = read_pid(data_dir)
    if not pid:
        ui.info("nessun PID registrato: niente da fermare")
        return False
    if not process_alive(pid):
        remove_pid(data_dir)
        ui.info("processo non attivo: pulisco il PID")
        return False
    if DRY_RUN:
        ui.info(f"[dry-run] stop pid {pid}")
        return True
    if is_windows():
        run_command(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, ui=ui)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            remove_pid(data_dir)
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not process_alive(pid):
                break
            time.sleep(0.3)
        else:
            with _suppress():
                os.kill(pid, signal.SIGKILL)
    remove_pid(data_dir)
    ui.ok("servizio fermato")
    return True


class _suppress:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: Any) -> bool:
        return True


# ── servizio di sistema (systemd / launchd / Task Scheduler) ────────────────


@dataclass
class ServiceSpec:
    repo_root: Path
    venv_python: Path
    host: str
    port: int
    env_file: Path
    data_dir: Path
    role: str = "all"
    user: str = ""
    uv_bin: str = ""


def systemd_unit_text(spec: ServiceSpec, *, system: bool = False) -> str:
    target = "multi-user.target" if system else "default.target"
    user_line = f"User={spec.user}\n" if (system and spec.user) else ""
    # Il servizio non passa dalle shell di login: esponi il percorso di ``uv``
    # trovato in fase di install, così la diagnostica non lo segnala assente.
    uv_line = f"Environment=UV={spec.uv_bin}\n" if spec.uv_bin else ""
    return (
        "[Unit]\n"
        f"Description=Noesis PDF Cloner Service\n"
        "After=network.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={spec.repo_root}\n"
        f"{user_line}"
        f"EnvironmentFile={spec.env_file}\n"
        f"Environment=ROLE={spec.role}\n"
        f"{uv_line}"
        f"ExecStart={spec.venv_python} -m uvicorn app.main:app --workers 1 "
        f"--host {spec.host} --port {spec.port}\n"
        "Restart=always\n"
        "RestartSec=3\n"
        "NoNewPrivileges=true\n\n"
        "[Install]\n"
        f"WantedBy={target}\n"
    )


def launchd_plist_text(spec: ServiceSpec, env: dict[str, str]) -> str:
    def args() -> str:
        values = [
            str(spec.venv_python), "-m", "uvicorn", "app.main:app",
            "--workers", "1", "--host", spec.host, "--port", str(spec.port),
        ]
        return "".join(f"        <string>{v}</string>\n" for v in values)

    env_items = "".join(
        f"        <key>{key}</key>\n        <string>{value}</string>\n"
        for key, value in sorted(env.items())
    )
    log = spec.data_dir / "logs" / "noesis.out"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f"    <key>Label</key>\n    <string>{SERVICE_LABEL}</string>\n"
        "    <key>ProgramArguments</key>\n    <array>\n"
        f"{args()}"
        "    </array>\n"
        f"    <key>WorkingDirectory</key>\n    <string>{spec.repo_root}</string>\n"
        "    <key>EnvironmentVariables</key>\n    <dict>\n"
        f"{env_items}"
        "    </dict>\n"
        "    <key>RunAtLoad</key>\n    <true/>\n"
        "    <key>KeepAlive</key>\n    <true/>\n"
        f"    <key>StandardOutPath</key>\n    <string>{log}</string>\n"
        f"    <key>StandardErrorPath</key>\n    <string>{log}</string>\n"
        "</dict>\n</plist>\n"
    )


def windows_runner_text(spec: ServiceSpec, env: dict[str, str]) -> str:
    log = spec.data_dir / "logs" / "noesis.out"
    lines = ["@echo off", "setlocal"]
    for key, value in sorted(env.items()):
        lines.append(f"set {key}={value}")
    args = " ".join(
        f'"{v}"' for v in [
            str(spec.venv_python), "-m", "uvicorn", "app.main:app",
            "--workers", "1", "--host", spec.host, "--port", str(spec.port),
        ]
    )
    lines.append(f'cd /d "{spec.repo_root}"')
    lines.append(f'if not exist "{log.parent}" mkdir "{log.parent}"')
    lines.append(f'{args} >> "{log}" 2>&1')
    return "\r\n".join(lines) + "\r\n"


class ServiceController:
    """Astrazione del servizio: systemd (user/system), launchd, Task Scheduler."""

    def __init__(self, data_dir: Path, ui: UI, *, system: bool = False, spec: ServiceSpec | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.ui = ui
        self.system = system
        self.spec = spec

    # -- rilevamento --------------------------------------------------------
    def kind(self) -> str:
        if is_macos():
            return "launchd"
        if is_windows():
            return "schtasks"
        if shutil.which("systemctl"):
            if self.system:
                return "systemd-system"
            if self._user_systemd_available():
                return "systemd-user"
        return "none"

    @staticmethod
    def _user_systemd_available() -> bool:
        if not shutil.which("systemctl"):
            return False
        if os.environ.get("XDG_RUNTIME_DIR"):
            return True
        try:
            return Path(f"/run/user/{os.getuid()}/systemd").exists()
        except (AttributeError, OSError):  # pragma: no cover - non unix
            return False

    # -- percorsi -----------------------------------------------------------
    def systemd_unit_path(self) -> Path:
        if self.system:
            return Path("/etc/systemd/system") / f"{SERVICE_NAME}.service"
        return Path.home() / ".config" / "systemd" / "user" / f"{SERVICE_NAME}.service"

    def plist_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"

    def windows_runner_path(self) -> Path:
        return self.data_dir / "service" / "run.cmd"

    # -- installazione ------------------------------------------------------
    def install(self) -> None:
        assert self.spec is not None, "ServiceSpec richiesto"
        kind = self.kind()
        if DRY_RUN:
            self.ui.info(f"[dry-run] installerei il servizio ({kind})")
            return
        if kind == "systemd-user":
            path = self.systemd_unit_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(systemd_unit_text(self.spec, system=False), encoding="utf-8")
            self._run(["systemctl", "--user", "daemon-reload"])
            self._run(["systemctl", "--user", "enable", "--now", SERVICE_NAME])
            self._enable_linger()
            self.ui.ok(f"servizio systemd (user) installato: {path}")
        elif kind == "systemd-system":
            path = self.systemd_unit_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(systemd_unit_text(self.spec, system=True), encoding="utf-8")
            self._run(["systemctl", "daemon-reload"])
            self._run(["systemctl", "enable", "--now", SERVICE_NAME])
            self.ui.ok(f"servizio systemd (system) installato: {path}")
        elif kind == "launchd":
            path = self.plist_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(launchd_plist_text(self.spec, self._env()), encoding="utf-8")
            self._run(["launchctl", "unload", str(path)], check=False)
            self._run(["launchctl", "load", "-w", str(path)])
            self.ui.ok(f"agente launchd installato: {path}")
        elif kind == "schtasks":
            path = self.windows_runner_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(windows_runner_text(self.spec, self._env()), encoding="utf-8")
            create = ["schtasks", "/Create", "/TN", SERVICE_NAME, "/TR", str(path), "/F"]
            if self.system:
                # All'accensione, anche senza login: richiede amministratore.
                create += ["/SC", "ONSTART", "/RU", "SYSTEM", "/RL", "HIGHEST"]
            else:
                create += ["/SC", "ONLOGON", "/RL", "LIMITED"]
            self._run(create)
            self._run(["schtasks", "/Run", "/TN", SERVICE_NAME], check=False)
            mode = "system" if self.system else "user"
            self.ui.ok(f"attività pianificata installata ({mode}): {path}")
        else:
            self.ui.warn(
                "nessun gestore di servizi disponibile (systemd/launchd/Task Scheduler): "
                "avvio il server in background. Per l'autostart abilita systemd in WSL "
                "(systemd=true in /etc/wsl.conf) o usa `noesis start`."
            )
            start_background(self.data_dir, self.ui, host=self.spec.host, port=self.spec.port)

    def uninstall(self) -> None:
        kind = self.kind()
        if DRY_RUN:
            self.ui.info(f"[dry-run] rimuoverei il servizio ({kind})")
            return
        if kind == "systemd-user":
            self._run(["systemctl", "--user", "disable", "--now", SERVICE_NAME], check=False)
            _unlink(self.systemd_unit_path())
            self._run(["systemctl", "--user", "daemon-reload"], check=False)
        elif kind == "systemd-system":
            self._run(["systemctl", "disable", "--now", SERVICE_NAME], check=False)
            _unlink(self.systemd_unit_path())
            self._run(["systemctl", "daemon-reload"], check=False)
        elif kind == "launchd":
            self._run(["launchctl", "unload", "-w", str(self.plist_path())], check=False)
            _unlink(self.plist_path())
        elif kind == "schtasks":
            self._run(["schtasks", "/End", "/TN", SERVICE_NAME], check=False)
            self._run(["schtasks", "/Delete", "/TN", SERVICE_NAME, "/F"], check=False)
            _unlink(self.windows_runner_path())
        self.ui.ok("servizio rimosso")

    def status(self) -> str:
        kind = self.kind()
        if kind == "systemd-user":
            result = self._run(["systemctl", "--user", "is-active", SERVICE_NAME], check=False, capture=True)
            return (result.stdout or "").strip() or "unknown"
        if kind == "systemd-system":
            result = self._run(["systemctl", "is-active", SERVICE_NAME], check=False, capture=True)
            return (result.stdout or "").strip() or "unknown"
        if kind == "launchd":
            result = self._run(["launchctl", "list"], check=False, capture=True)
            return "loaded" if SERVICE_LABEL in (result.stdout or "") else "not-loaded"
        if kind == "schtasks":
            result = self._run(["schtasks", "/Query", "/TN", SERVICE_NAME], check=False, capture=True)
            return "registered" if result.returncode == 0 else "not-registered"
        return "none"

    def _env(self) -> dict[str, str]:
        return build_env(self.data_dir)

    def _enable_linger(self) -> None:
        user = os.environ.get("USER") or os.environ.get("LOGNAME")
        if user:
            self._run(["loginctl", "enable-linger", user], check=False)

    def _run(self, cmd: Sequence[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
        return run_command(cmd, check=check, capture=capture, ui=self.ui)


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


# ── firewall ────────────────────────────────────────────────────────────────


def detect_firewall() -> str | None:
    if is_windows():
        return "windows"
    if is_macos():
        return "macos"
    if shutil.which("ufw"):
        return "ufw"
    if shutil.which("firewall-cmd"):
        return "firewalld"
    return None


def firewall_open_command(fw: str, port: int, subnet: str | None = None) -> list[str] | None:
    if fw == "ufw":
        if subnet:
            return ["sudo", "ufw", "allow", "from", subnet, "to", "any", "port", str(port), "proto", "tcp"]
        return ["sudo", "ufw", "allow", f"{port}/tcp"]
    if fw == "firewalld":
        if subnet:
            return ["sudo", "firewall-cmd", "--permanent", "--add-rich-rule",
                    f"rule family=ipv4 source address={subnet} port port={port} protocol=tcp accept"]
        return ["sudo", "firewall-cmd", "--permanent", "--add-port", f"{port}/tcp"]
    if fw == "windows":
        return ["netsh", "advfirewall", "firewall", "add", "rule",
                f"name=Noesis PDF Cloner {port}", "dir=in", "action=allow",
                "protocol=TCP", f"localport={port}", "remoteip=localsubnet"]
    return None


def local_subnet() -> str | None:
    """Sottorete IPv4 dell'interfaccia di default in CIDR (es. ``192.168.1.0/24``)."""
    ip_bin = shutil.which("ip")
    if not ip_bin:
        return None
    route = run_command([ip_bin, "-4", "route", "show", "default"], check=False, capture=True).stdout or ""
    tokens = route.split()
    if "dev" not in tokens:
        return None
    dev = tokens[tokens.index("dev") + 1]
    addr = run_command([ip_bin, "-o", "-4", "addr", "show", "dev", dev], check=False, capture=True).stdout or ""
    match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)", addr)
    if not match:
        return None
    try:
        return str(ipaddress.ip_network(f"{match.group(1)}/{match.group(2)}", strict=False))
    except ValueError:
        return None


def ufw_enabled() -> bool | None:
    """True/False se ufw è abilitato (da ``/etc/ufw/ufw.conf``); None se ignoto."""
    try:
        text = UFW_CONF.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("ENABLED="):
            return stripped.split("=", 1)[1].strip().lower() in {"yes", "true", "1"}
    out = (run_command(["sudo", "-n", "ufw", "status"], check=False, capture=True).stdout or "").lower()
    if "inactive" in out or "inattiv" in out:
        return False
    if "active" in out or "attiv" in out:
        return True
    return None


def firewall_active(fw: str) -> bool | None:
    """True/False se il firewall è attivo; None se non determinabile."""
    if fw == "ufw":
        return ufw_enabled()
    if fw == "firewalld":
        out = (run_command(["firewall-cmd", "--state"], check=False, capture=True).stdout or "").strip().lower()
        if out == "running":
            return True
        if out == "not running":
            return False
    if fw == "windows":
        # Get-NetFirewallProfile espone la proprietà Enabled (True/False), non
        # dipendente dalla lingua dell'output.
        cmd = ["powershell", "-NoProfile", "-Command",
               "(Get-NetFirewallProfile | Where-Object { $_.Enabled -eq $true }).Count"]
        out = (run_command(cmd, check=False, capture=True).stdout or "").strip()
        if out.isdigit():
            return int(out) > 0
    return None


def firewall_rule_present(fw: str, port: int, subnet: str | None) -> bool | None:
    """True/False se la regola per ``port`` è presente; None se non verificabile.

    Usa solo token **numerici** (porta e CIDR), così è indipendente dalla lingua
    dell'output di ``ufw``/``firewall-cmd``.
    """
    if fw == "ufw":
        out = run_command(["sudo", "-n", "ufw", "status"], check=False, capture=True).stdout or ""
        if not out.strip():
            return None
        if str(port) not in out:
            return False
        if subnet and subnet not in out:
            return False
        return True
    if fw == "firewalld":
        out = run_command(
            ["sudo", "-n", "firewall-cmd", "--permanent", "--list-rich-rules"],
            check=False, capture=True,
        ).stdout or ""
        if not out.strip():
            return None
        return str(port) in out and (subnet is None or subnet in out)
    if fw == "windows":
        out = run_command(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             f"name=Noesis PDF Cloner {port}"],
            check=False, capture=True,
        ).stdout or ""
        if not out.strip():
            return None
        # Il messaggio "nessuna regola" è localizzato; il numero di porta no.
        return str(port) in out
    return None


# ── doctor ──────────────────────────────────────────────────────────────────


@dataclass
class Check:
    level: str  # ok | warn | error
    message: str


def doctor_checks(data_dir: Path) -> list[Check]:
    checks: list[Check] = []
    config = load_config(data_dir)
    host = os.environ.get("HOST", config.get("HOST", DEFAULT_HOST))
    port = int(os.environ.get("PORT", config.get("PORT", DEFAULT_PORT)))

    checks.append(Check("ok", f"piattaforma: {platform.system()} {platform.machine()}"
                             + (" (WSL)" if is_wsl() else "")))

    uv = find_uv()
    checks.append(Check("ok" if uv else "warn", f"uv: {uv or 'non trovato (verrà installato da `noesis install`)'}"))

    if venv_python_in(service_venv()).is_file():
        result = run_command([str(venv_python_in(service_venv())), "-c",
                              "import fastapi, uvicorn, fitz"], check=False, capture=True)
        checks.append(Check("ok" if result.returncode == 0 else "error",
                            "venv servizio: dipendenze presenti" if result.returncode == 0
                            else "venv servizio: dipendenze mancanti (esegui `noesis install`)"))
    else:
        checks.append(Check("warn", "venv servizio assente (esegui `noesis install`)"))

    if venv_python_in(engine_venv()).is_file():
        binary = engine_binary()
        checks.append(Check("ok" if binary else "warn",
                            f"motore: {binary}" if binary else "venv motore presente ma pdf2zh_next assente"))
    else:
        checks.append(Check("warn", "venv motore assente (esegui `noesis install`)"))

    checks.append(Check("ok" if config_path(data_dir).is_file() else "warn",
                        f"config: {config_path(data_dir)}" if config_path(data_dir).is_file()
                        else "config assente (verrà creata da `noesis install`)"))

    try:
        ensure_data_dirs(data_dir)
        probe = data_dir / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(Check("ok", f"cartella dati scrivibile: {data_dir}"))
    except OSError as exc:
        checks.append(Check("error", f"cartella dati non scrivibile ({data_dir}): {exc}"))

    usage = shutil.disk_usage(str(data_dir))
    free_gb = usage.free / (1024 ** 3)
    checks.append(Check("ok" if free_gb >= 2 else "warn", f"spazio libero: {free_gb:.1f} GB"))

    if health_check(host, port):
        checks.append(Check("ok", f"server raggiungibile su {host}:{port}"))
    elif read_pid(data_dir) and process_alive(read_pid(data_dir) or 0):
        checks.append(Check("warn", "processo attivo ma /api/v1/health non risponde ancora"))
    else:
        checks.append(Check("warn", "server non in esecuzione (`noesis start`)"))

    fw = detect_firewall()
    if fw in {"ufw", "firewalld"}:
        checks.append(Check("info" if fw == "ufw" else "warn",
                            f"firewall rilevato: {fw} — apri la porta con `noesis install --open-firewall`"))
    if is_wsl():
        checks.append(Check("warn",
                            "WSL: dalla LAN la porta non è visibile senza networkingMode=mirrored "
                            "(Windows 11) o un portproxy; in locale funziona."))

    fonts = _font_count()
    if fonts is not None:
        checks.append(Check("ok" if fonts >= 50 else "warn",
                            f"font di sistema: {fonts}" + ("" if fonts >= 50 else " (pochi: il typesetting potrebbe degradare)")))

    for url in server_urls(host, port):
        checks.append(Check("ok", f"URL: {url}"))
    return checks


def _font_count() -> int | None:
    if is_windows():
        return None
    if shutil.which("fc-list") is None:
        return None
    result = run_command(["fc-list"], check=False, capture=True)
    if result.returncode != 0:
        return None
    return len([line for line in (result.stdout or "").splitlines() if line.strip()])


# ── bundle offline ──────────────────────────────────────────────────────────


def bundle_manifest(data_dir: Path, wheelhouse: Path, models: Path | None) -> dict[str, Any]:
    wheels = sorted(p.name for p in wheelhouse.glob("*")) if wheelhouse.is_dir() else []
    return {
        "app": APP_NAME,
        "platform": platform_tag(),
        "python": PYTHON_VERSION,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "wheels": len(wheels),
        "models": bool(models and models.is_dir()),
    }


def download_wheels(uv: str, dest: Path, ui: UI) -> None:
    """Scarica tutti i wheel necessari (servizio + motore) in ``dest``."""
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="noesis-wheels-") as tmp:
        helper = Path(tmp) / "helper"
        ensure_venv(uv, helper, ui)
        run_command([uv, "pip", "install", "--python", str(venv_python_in(helper)), "-q", "pip"], ui=ui)
        cmd = [str(venv_python_in(helper)), "-m", "pip", "download", "-d", str(dest)]
        for name in (REQUIREMENTS, engine_requirement()):
            if (REPO_ROOT / name).is_file():
                cmd += ["-r", str(REPO_ROOT / name)]
        run_command(cmd, ui=ui)


def create_bundle(uv: str, data_dir: Path, output: Path, ui: UI) -> Path:
    if DRY_RUN:
        ui.info(f"[dry-run] creerei il bundle in {output}")
        return Path(output)
    with tempfile.TemporaryDirectory(prefix="noesis-bundle-") as tmp:
        staging = Path(tmp) / "noesis-bundle"
        staging.mkdir(parents=True, exist_ok=True)
        ui.info("scarico i wheel (servizio + motore)…")
        download_wheels(uv, staging / "wheelhouse", ui)

        models = babeldoc_cache_dir()
        models_present = models.is_dir()
        if models_present:
            ui.info("includo i modelli del motore…")
            shutil.copytree(models, staging / "models" / "babeldoc")

        manifest = bundle_manifest(data_dir, staging / "wheelhouse", models if models_present else None)
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output, "w:gz") as archive:
            archive.add(staging, arcname="noesis-bundle")
    ui.ok(f"bundle creato: {output}")
    return output


def install_from_bundle(uv: str, data_dir: Path, archive_path: Path, ui: UI) -> None:
    archive_path = Path(archive_path)
    if not archive_path.is_file():
        raise CommandError(f"bundle non trovato: {archive_path}")
    with tempfile.TemporaryDirectory(prefix="noesis-bundle-") as tmp:
        with tarfile.open(archive_path, "r:*") as archive:
            try:
                archive.extractall(tmp, filter="data")
            except TypeError:  # Python < 3.12
                archive.extractall(tmp)
        root = Path(tmp) / "noesis-bundle"
        wheelhouse = root / "wheelhouse"
        ui.info("installo offline dal bundle…")
        ensure_service_venv(uv, ui, offline=wheelhouse)
        ensure_engine_venv(uv, ui, offline=wheelhouse)
        models = root / "models" / "babeldoc"
        if models.is_dir():
            target = babeldoc_cache_dir()
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(models, target)
            ui.ok(f"modelli ripristinati in {target}")
    ui.ok("installazione da bundle completata")


# ── comandi ─────────────────────────────────────────────────────────────────


def cmd_install(args: argparse.Namespace, ui: UI) -> int:
    data_dir = Path(args.data_dir).expanduser()
    host, port = resolve_host_port(args, data_dir)
    if DRY_RUN:
        ui.info(f"[dry-run] cartella dati: {data_dir}")
    else:
        ensure_data_dirs(data_dir)
        save_config(data_dir, {
            "HOST": host,
            "PORT": str(port),
        })
        if not args.ci:
            ensure_openrouter_key(data_dir, ui)
    uv = ensure_uv(ui)
    if args.bundle:
        install_from_bundle(uv, data_dir, Path(args.bundle), ui)
    else:
        ensure_service_venv(uv, ui)
        if not args.no_engine:
            ensure_engine_venv(uv, ui)
    if not args.no_engine and not args.skip_warm and not args.bundle:
        warm_engine(ui)
    if not args.ci:
        verify_openrouter_key(data_dir, ui)
    _maybe_open_firewall(args, ui, port=port)
    if not args.no_service:
        if not DRY_RUN:
            warn_if_port_busy(host, port, ui)
        spec = _service_spec(data_dir, host=host, port=port)
        ServiceController(data_dir, ui, system=args.mode == "system", spec=spec).install()
    _print_summary(data_dir, ui, host=host, port=port, started=not args.no_service, report=not args.ci)
    if not args.no_browser and not args.ci and has_display():
        _open_browser(host, port, ui)
    return 0


def _service_spec(data_dir: Path, *, host: str, port: int) -> ServiceSpec:
    role = os.environ.get("ROLE") or load_config(data_dir).get("ROLE", "all")
    return ServiceSpec(
        repo_root=REPO_ROOT,
        venv_python=venv_python_in(service_venv()),
        host=host,
        port=port,
        env_file=config_path(data_dir),
        data_dir=data_dir,
        role=role,
        user=invoking_user(),
        uv_bin=find_uv() or "",
    )


def _maybe_open_firewall(args: argparse.Namespace, ui: UI, *, port: int) -> None:
    fw = detect_firewall()
    if fw in {"ufw", "firewalld"}:
        subnet = local_subnet()
        scope = f" (solo sottorete {subnet})" if subnet else ""
        active = firewall_active(fw)
        if not args.open_firewall:
            if active is False:
                ui.info(f"firewall {fw} inattivo: la porta {port} è già raggiungibile in LAN")
            else:
                ui.warn(
                    f"firewall {fw} attivo: per la LAN apri la porta con "
                    f"`noesis install --open-firewall`{scope}"
                )
            return
        if active is False:
            ui.info(
                f"firewall {fw} inattivo: nessuna regola necessaria "
                f"(la porta {port} è già raggiungibile in LAN)"
            )
            return
        command = firewall_open_command(fw, port, subnet)
        if not command:
            return
        result = run_command(command, check=False, capture=True, ui=ui)
        if DRY_RUN:
            return
        if result.returncode != 0:
            ui.error(
                f"apertura porta {port}/tcp non riuscita ({fw}): "
                f"{(result.stdout or '').strip()[:200]}"
            )
            ui.info(f"comando manuale: {' '.join(command)}")
            return
        if fw == "firewalld":
            run_command(["sudo", "firewall-cmd", "--reload"], check=False, ui=ui)
        present = firewall_rule_present(fw, port, subnet)
        if present is False:
            ui.warn(
                f"porta {port}/tcp: regola non confermata in {fw}; "
                f"verifica con `sudo {fw} status`"
            )
        else:
            ui.ok(f"porta {port}/tcp aperta{scope} ({fw})")
    elif fw == "windows":
        _open_firewall_windows(args, ui, port=port)


def _run_elevated_windows(command: Sequence[str], ui: UI) -> bool:
    """Rilancia ``command`` con UAC (``Start-Process -Verb RunAs``). True se ok."""
    if DRY_RUN or not is_windows():
        return False
    exe = command[0]
    arg_list = ", ".join("'" + str(a).replace("'", "''") + "'" for a in command[1:])
    script = (
        f"$p = Start-Process -Verb RunAs -Wait -PassThru -FilePath '{exe}' "
        f"-ArgumentList {arg_list}; exit $p.ExitCode"
    )
    result = run_command(
        ["powershell", "-NoProfile", "-Command", script],
        check=False, capture=True, ui=ui,
    )
    return result.returncode == 0


def _open_firewall_windows(args: argparse.Namespace, ui: UI, *, port: int) -> None:
    command = firewall_open_command("windows", port)
    if not command:
        return
    pretty = " ".join(command)
    active = firewall_active("windows")
    if not args.open_firewall:
        if active is False:
            ui.info(f"firewall Windows inattivo: la porta {port} è già raggiungibile in LAN")
        else:
            ui.warn("firewall Windows attivo: per la LAN apri la porta con "
                    "`noesis install --open-firewall` (PowerShell amministratore)")
        return
    if active is False:
        ui.info(f"firewall Windows inattivo: nessuna regola necessaria "
                f"(la porta {port} è già raggiungibile in LAN)")
        return
    if DRY_RUN:
        ui.info(f"[dry-run] {pretty}")
        return
    result = run_command(command, check=False, capture=True, ui=ui)
    if result.returncode != 0:
        # Serve l'elevazione: prova con UAC, altrimenti istruzioni.
        if not _run_elevated_windows(command, ui):
            ui.error(f"apertura porta {port}/tcp non riuscita (serve amministratore)")
            ui.info(f"comando manuale (PowerShell amministratore): {pretty}")
            return
    present = firewall_rule_present("windows", port, None)
    if present is False:
        ui.warn(f"porta {port}/tcp: regola non confermata nel firewall Windows")
    else:
        ui.ok(f"porta {port}/tcp aperta (solo sottorete locale) (windows firewall)")


def _print_summary(data_dir: Path, ui: UI, *, host: str, port: int, started: bool = True, report: bool = True) -> None:
    ui.section("Riepilogo")
    ui.info(f"cartella dati: {data_dir}")
    ui.info(f"config: {config_path(data_dir)}")
    ui.info(f"log: {service_log(data_dir)}")

    if report:
        print_health_report(data_dir, ui)

    ui.section("Avvia")
    for url in server_urls(host, port):
        label = "locale" if "127.0.0.1" in url else "LAN"
        ui.ok(f"{label}: {ui.link(url)}")
    if DRY_RUN:
        return
    if not started:
        ui.info("avvia con `noesis start` (o `noesis service status`)")
        return
    if wait_for_health(host, port, timeout=30.0):
        ui.ok(f"porta {port} raggiungibile (health ok)")
    else:
        ui.warn(f"porta {port} non risponde dopo 30 s: controlla `./noesis logs`")
    ui.info("gestione: ./noesis status · logs · restart · open")


def cmd_start(args: argparse.Namespace, ui: UI) -> int:
    data_dir = Path(args.data_dir).expanduser()
    ensure_data_dirs(data_dir)
    host, port = resolve_host_port(args, data_dir)
    if not venv_python_in(service_venv()).is_file():
        ui.error("venv assente: esegui prima `noesis install`")
        return 2
    warn_if_port_busy(host, port, ui)
    start_background(data_dir, ui, host=host, port=port)
    return 0


def cmd_stop(args: argparse.Namespace, ui: UI) -> int:
    stop_background(Path(args.data_dir).expanduser(), ui)
    return 0


def cmd_restart(args: argparse.Namespace, ui: UI) -> int:
    cmd_stop(args, ui)
    return cmd_start(args, ui)


def cmd_status(args: argparse.Namespace, ui: UI) -> int:
    data_dir = Path(args.data_dir).expanduser()
    host, port = resolve_host_port(args, data_dir)
    pid = read_pid(data_dir)
    pid_running = bool(pid and process_alive(pid))
    healthy = health_check(host, port)
    controller = ServiceController(data_dir, ui)
    kind = controller.kind()
    svc_status = controller.status() if kind != "none" else "none"
    svc_active = svc_status in {"active", "loaded", "registered"}
    # Il servizio può essere gestito da systemd/launchd/schtasks (senza PID file):
    # "attivo" o il solo /api/v1/health valgono come server in funzione.
    running = pid_running or svc_active or healthy
    suffix = ", /api/v1/health ok" if healthy else ", /api/v1/health non risponde"
    if pid_running:
        ui.ok(f"processo attivo (pid {pid}){suffix}")
    elif svc_active:
        ui.ok(f"servizio attivo ({kind}){suffix}")
    elif healthy:
        ui.ok(f"server raggiungibile su {host}:{port}")
    else:
        ui.info("processo non attivo")
    if kind != "none":
        ui.info(f"servizio {kind}: {svc_status}")
    return 0 if running else 1


def cmd_logs(args: argparse.Namespace, ui: UI) -> int:
    data_dir = Path(args.data_dir).expanduser()
    log = service_log(data_dir)
    if not log.is_file():
        # Il servizio systemd scrive su journald, non su file.
        if not is_windows() and not is_macos() and shutil.which("journalctl"):
            try:
                result = run_command(
                    ["journalctl", "--user", "-u", SERVICE_NAME,
                     "-n", str(args.lines), "--no-pager"],
                    check=False, capture=True,
                )
            except CommandError:
                result = None
            if result is not None and result.returncode == 0 and (result.stdout or "").strip():
                print(result.stdout.strip())
                return 0
        ui.warn(f"nessun log: {log}")
        return 1
    text = log.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in text[-args.lines:]:
        print(line)
    return 0


def cmd_doctor(args: argparse.Namespace, ui: UI) -> int:
    data_dir = Path(args.data_dir).expanduser()
    checks = doctor_checks(data_dir)
    for check in checks:
        ui.emit(check.level if check.level in _LEVEL_ICON else "info", check.message)
    errors = sum(1 for c in checks if c.level == "error")
    warns = sum(1 for c in checks if c.level == "warn")
    if errors or (args.strict and warns):
        ui.error(f"doctor: {errors} errori, {warns} avvisi")
        return 1
    ui.ok(f"doctor: tutto ok ({warns} avvisi)")
    return 0


def cmd_open(args: argparse.Namespace, ui: UI) -> int:
    data_dir = Path(args.data_dir).expanduser()
    host, port = resolve_host_port(args, data_dir)
    urls = server_urls(host, port)
    target = urls[-1]
    ui.info(f"apro {target}")
    if not DRY_RUN:
        webbrowser.open(target)
    return 0


def cmd_service(args: argparse.Namespace, ui: UI) -> int:
    data_dir = Path(args.data_dir).expanduser()
    ensure_data_dirs(data_dir)
    host, port = resolve_host_port(args, data_dir)
    spec = _service_spec(data_dir, host=host, port=port)
    controller = ServiceController(data_dir, ui, system=args.mode == "system", spec=spec)
    action = args.action or "status"
    if action == "install":
        controller.install()
    elif action == "uninstall":
        controller.uninstall()
    elif action == "status":
        ui.info(f"tipo: {controller.kind()}")
        ui.info(f"stato: {controller.status()}")
    else:
        ui.error(f"azione sconosciuta: {action}")
        return 2
    return 0


def cmd_bundle(args: argparse.Namespace, ui: UI) -> int:
    uv = ensure_uv(ui)
    output = Path(args.output or (REPO_ROOT / "dist" / f"noesis-bundle-{platform_tag()}.tar.gz"))
    create_bundle(uv, Path(args.data_dir).expanduser(), output, ui)
    return 0


def cmd_update(args: argparse.Namespace, ui: UI) -> int:
    if (REPO_ROOT / ".git").is_dir() and shutil.which("git"):
        ui.info("aggiorno il codice (git pull)…")
        run_command(["git", "-C", str(REPO_ROOT), "pull", "--ff-only"], check=False, ui=ui)
    uv = ensure_uv(ui)
    ensure_service_venv(uv, ui)
    if not args.no_engine:
        ensure_engine_venv(uv, ui)
    ui.ok("aggiornamento completato; riavvia con `noesis restart`")
    return 0


# ── disinstallazione ────────────────────────────────────────────────────────


@dataclass
class RemovalItem:
    """Voce rimovibile dalla disinstallazione (con dimensione, se calcolata)."""

    key: str
    label: str
    path: Path | None
    size: int = 0
    selected: bool = False


def _fmt_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _path_size(path: Path | None) -> int:
    """Dimensione (byte) di file o cartella; 0 se assente/non leggibile."""
    if path is None or not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _is_venv(path: Path) -> bool:
    return path.is_dir() and (path / "pyvenv.cfg").is_file()


def _external_cache_dir(data_dir: Path) -> Path | None:
    """``CACHE_ROOT`` configurato, se è **fuori** dalla cartella dati."""
    configured = os.environ.get("CACHE_ROOT") or load_config(data_dir).get("CACHE_ROOT", "")
    if not configured:
        return None
    candidate = Path(configured).expanduser()
    try:
        candidate.resolve().relative_to(data_dir.resolve())
        return None  # dentro data_dir: già coperto da --data
    except (ValueError, OSError):
        return candidate


def _parse_selection(answer: str, count: int) -> set[int]:
    """Interpreta ``2,3`` · ``a``/``tutto`` · vuoto → indici 1-based scelti."""
    answer = (answer or "").strip().lower()
    if not answer:
        return set()
    if answer in {"a", "all", "tutto", "*"}:
        return set(range(1, count + 1))
    chosen: set[int] = set()
    for token in re.split(r"[,\s]+", answer):
        if token.isdigit():
            value = int(token)
            if 1 <= value <= count:
                chosen.add(value)
    return chosen


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def cmd_uninstall(args: argparse.Namespace, ui: UI) -> int:
    """Rimuove il servizio e, su scelta, venv/motore/dati/cache.

    Senza flag e su TTY mostra il menu "Cosa rimuovere" (dimensioni incluse);
    in non-TTY o con ``--json``/``--yes`` è **conservativo**: rimuove solo il
    servizio. ``--all`` = nessuna traccia del servizio (mai la cache condivisa
    di ``uv``/Python gestiti, che non sono nostri).
    """
    data_dir = Path(args.data_dir).expanduser()
    host, port = resolve_host_port(args, data_dir)

    remove_all = bool(getattr(args, "all_", False))
    engine_flag = bool(getattr(args, "engine", False)) or remove_all
    flags = {
        "venv": bool(getattr(args, "venv", False)) or remove_all,
        "engine": engine_flag,
        "data": bool(getattr(args, "data", False)) or remove_all,
        "cache": bool(getattr(args, "cache", False)) or remove_all,
        "babeldoc": bool(getattr(args, "babeldoc", False)) or engine_flag,
    }

    items: list[RemovalItem] = [
        RemovalItem("venv", "Venv del servizio (.venv)", service_venv()),
        RemovalItem("engine", "Motore (.venv2)", engine_venv()),
        RemovalItem("babeldoc", "Cache BabelDOC (condivisa)", babeldoc_cache_dir()),
        RemovalItem("data", "Dati dell'app (upload, DB, log, cache)", data_dir),
    ]
    external_cache = _external_cache_dir(data_dir)
    if external_cache is not None:
        items.append(RemovalItem("cache", "Cache esterna (CACHE_ROOT)", external_cache))

    explicit = any(
        getattr(args, name, False)
        for name in ("venv", "engine", "data", "cache", "babeldoc", "all_", "service")
    )
    interactive = bool(getattr(args, "interactive", False)) or (
        not explicit and not getattr(args, "yes", False) and ui.is_interactive()
    )
    want_sizes = interactive or ui.json_mode

    for item in items:
        item.selected = flags.get(item.key, False)
        if want_sizes:
            item.size = _path_size(item.path)

    if interactive:
        ui.section("Cosa rimuovere")
        ui.info("  Il servizio di avvio automatico viene sempre rimosso.")
        for index, item in enumerate(items, start=1):
            size = f"  {_fmt_size(item.size)}" if item.size else ""
            ui.info(f"  {index}. {item.label}{size}")
        ui.info("  [a] tutto (nessuna traccia) · [invio] solo il servizio")
        chosen = _parse_selection(ui.ask("Selezione (es. 2,3): "), len(items))
        for index, item in enumerate(items, start=1):
            item.selected = index in chosen

    ui.section("Piano di disinstallazione")
    ui.info("Rimosso: Servizio di avvio automatico")
    for item in items:
        size = f" ({_fmt_size(item.size)})" if item.size else ""
        if item.selected:
            absent = " (assente)" if (item.path is not None and not item.path.exists()) else ""
            ui.info(f"Rimuovo: {item.label} → {item.path}{size}{absent}")
        else:
            ui.info(f"Conservo: {item.label} → {item.path}")

    if DRY_RUN:
        ui.info("[dry-run] nessuna modifica effettuata")
        return 0

    if interactive and not getattr(args, "yes", False):
        if not ui.ask_yes_no("Procedo con la rimozione?", default=True):
            ui.info("annullato")
            return 0

    stop_background(data_dir, ui)
    ServiceController(
        data_dir, ui, system=args.mode == "system",
        spec=_service_spec(data_dir, host=host, port=port),
    ).uninstall()

    for item in items:
        if not item.selected or item.path is None:
            continue
        if not item.path.exists():
            continue
        if item.key in {"venv", "engine"} and not _is_venv(item.path):
            ui.warn(f"{item.label}: non sembra un venv, salto ({item.path})")
            continue
        _remove_path(item.path)
        if item.path.exists():
            ui.warn(f"non rimosso del tutto: {item.path}")
        else:
            ui.ok(f"rimosso {item.label}: {item.path}")

    if flags["data"]:
        ui.ok(f"dati rimossi: {data_dir}")
    else:
        ui.info(f"dati conservati in {data_dir} (usa --data per rimuoverli)")
    return 0


def cmd_run(args: argparse.Namespace, ui: UI) -> int:
    """Avvia il server in primo piano (usato dai wrapper e per il debug)."""
    data_dir = Path(args.data_dir).expanduser()
    ensure_data_dirs(data_dir)
    uv = ensure_uv(ui)
    ensure_service_venv(uv, ui)
    host, port = resolve_host_port(args, data_dir)
    env = build_env(data_dir, host=host, port=port)
    cmd = uvicorn_command(service_venv(), host, port)
    if DRY_RUN:
        ui.info(f"[dry-run] {' '.join(cmd)}")
        return 0
    os.execvpe(cmd[0], cmd, env)
    return 0  # pragma: no cover


def cmd_worker(args: argparse.Namespace, ui: UI) -> int:
    """Avvia un processo worker in primo piano (coda condivisa su DB)."""
    data_dir = Path(args.data_dir).expanduser()
    ensure_data_dirs(data_dir)
    uv = ensure_uv(ui)
    ensure_service_venv(uv, ui)
    env = build_env(data_dir)
    cmd = [str(venv_python_in(service_venv())), "-m", "app.worker_main"]
    if DRY_RUN:
        ui.info(f"[dry-run] {' '.join(cmd)}")
        return 0
    os.execvpe(cmd[0], cmd, env)
    return 0  # pragma: no cover


def cmd_cli(args: argparse.Namespace, ui: UI) -> int:
    """Delega alla CLI headless (app.cli), passando gli argomenti."""
    data_dir = Path(args.data_dir).expanduser()
    uv = ensure_uv(ui)
    ensure_service_venv(uv, ui)
    env = build_env(data_dir)
    cmd = [str(venv_python_in(service_venv())), "-m", "app.cli", *args.extra]
    if DRY_RUN:
        ui.info(f"[dry-run] {' '.join(cmd)}")
        return 0
    os.execvpe(cmd[0], cmd, env)
    return 0  # pragma: no cover


def _open_browser(host: str, port: int, ui: UI) -> None:
    target = server_urls(host, port)[-1]
    try:
        webbrowser.open(target)
    except Exception:  # pragma: no cover - best effort
        ui.warn(f"non riesco ad aprire il browser: {target}")


# ── CLI ─────────────────────────────────────────────────────────────────────


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-dir", default=str(default_data_dir()), help="cartella dati (default: standard OS)")
    parser.add_argument("--host", default=None, help="bind (default da config: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help=f"porta (default da config: {DEFAULT_PORT})")
    parser.add_argument("--mode", choices=["user", "system"], default="user", help="servizio utente o di sistema")
    parser.add_argument("--json", action="store_true", help="output JSON")
    parser.add_argument("--quiet", action="store_true", help="output minimo")
    parser.add_argument("--dry-run", action="store_true", help="mostra i comandi senza eseguirli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="noesis", description="Console di installazione e gestione di noesis-pdf-cloner-service")
    parser.add_argument("--version", action="version", version="noesis console")
    sub = parser.add_subparsers(dest="command")

    install = sub.add_parser("install", help="installa venv, motore, config e servizio")
    _common(install)
    install.add_argument("--no-service", action="store_true", help="non installare il servizio")
    install.add_argument("--no-engine", action="store_true", help="non installare il motore pdf2zh_next")
    install.add_argument("--skip-warm", action="store_true", help="non scaricare i modelli ora")
    install.add_argument("--no-browser", action="store_true", help="non aprire il browser")
    install.add_argument("--open-firewall", action="store_true", help="apri la porta nel firewall (sudo)")
    install.add_argument("--bundle", default="", help="installa offline da un bundle")
    install.add_argument("--ci", action="store_true", help="modalità non interattiva (nessun prompt/browser)")

    for name, help_text in (("start", "avvia in background"), ("stop", "ferma"), ("restart", "riavvia")):
        p = sub.add_parser(name, help=help_text)
        _common(p)

    status = sub.add_parser("status", help="stato del servizio")
    _common(status)

    logs = sub.add_parser("logs", help="mostra gli ultimi log")
    _common(logs)
    logs.add_argument("-n", "--lines", type=int, default=80)

    doctor = sub.add_parser("doctor", help="diagnosi dell'installazione")
    _common(doctor)
    doctor.add_argument("--strict", action="store_true", help="esci con errore anche sugli avvisi")

    openp = sub.add_parser("open", help="apri il frontend nel browser")
    _common(openp)

    service = sub.add_parser("service", help="gestisci il servizio di sistema")
    _common(service)
    service.add_argument("action", nargs="?", choices=["install", "uninstall", "status"], default="status")

    bundle = sub.add_parser("bundle", help="crea un pacchetto offline")
    _common(bundle)
    bundle.add_argument("-o", "--output", default="")

    update = sub.add_parser("update", help="aggiorna codice e dipendenze")
    _common(update)
    update.add_argument("--no-engine", action="store_true")

    uninstall = sub.add_parser(
        "uninstall", help="rimuovi il servizio (scelta interattiva di cosa rimuovere)"
    )
    _common(uninstall)
    uninstall.add_argument("--service", action="store_true", help="solo il servizio (nessun altro elemento)")
    uninstall.add_argument("--venv", action="store_true", help="rimuovi anche il venv del servizio (.venv)")
    uninstall.add_argument("--engine", action="store_true", help="rimuovi anche il motore (.venv2) e la cache BabelDOC")
    uninstall.add_argument("--data", "--purge", dest="data", action="store_true", help="rimuovi anche la cartella dati")
    uninstall.add_argument("--cache", action="store_true", help="rimuovi anche la cache esterna (CACHE_ROOT)")
    uninstall.add_argument("--babeldoc", action="store_true", help="rimuovi la cache BabelDOC condivisa")
    uninstall.add_argument("--all", dest="all_", action="store_true", help="rimuovi tutto (nessuna traccia del servizio)")
    uninstall.add_argument("--interactive", action="store_true", help="forza la scelta interattiva")
    uninstall.add_argument("-y", "--yes", action="store_true", help="non chiedere conferma")

    runp = sub.add_parser("run", help="server in primo piano (debug/wrapper)")
    _common(runp)

    workerp = sub.add_parser("worker", help="worker in primo piano (coda condivisa)")
    _common(workerp)

    clip = sub.add_parser("cli", help="CLI headless (app.cli)")
    clip.add_argument("--data-dir", default=str(default_data_dir()))
    clip.add_argument("extra", nargs=argparse.REMAINDER)

    return parser


_HANDLERS: dict[str, Callable[[argparse.Namespace, UI], int]] = {
    "install": cmd_install,
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "status": cmd_status,
    "logs": cmd_logs,
    "doctor": cmd_doctor,
    "open": cmd_open,
    "service": cmd_service,
    "bundle": cmd_bundle,
    "update": cmd_update,
    "uninstall": cmd_uninstall,
    "run": cmd_run,
    "worker": cmd_worker,
    "cli": cmd_cli,
}


def main(argv: Sequence[str] | None = None) -> int:
    global DRY_RUN
    _configure_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    # `cli` è passthrough puro verso app.cli: non passa da argparse.
    if argv and argv[0] == "cli":
        ui = UI()
        try:
            code = cmd_cli(argparse.Namespace(data_dir=str(default_data_dir()), extra=argv[1:]), ui)
        except CommandError as exc:
            ui.error(str(exc))
            code = 1
        ui.finish()
        return code
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    DRY_RUN = bool(getattr(args, "dry_run", False))
    ui = UI(json_mode=bool(getattr(args, "json", False)), quiet=bool(getattr(args, "quiet", False)))
    try:
        code = _HANDLERS[args.command](args, ui)
    except CommandError as exc:
        ui.error(str(exc))
        code = 1
    except PermissionError as exc:
        ui.error(f"permessi insufficienti: {exc} (prova con sudo o --mode user)")
        code = 1
    except OSError as exc:
        ui.error(f"errore di sistema: {exc}")
        code = 1
    except KeyboardInterrupt:  # pragma: no cover
        ui.error("interrotto")
        code = 130
    ui.finish()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
