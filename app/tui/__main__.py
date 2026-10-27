"""``python -m app.tui``: avvio della TUI con la configurazione del service."""

from __future__ import annotations

import sys

from ..config import Settings
from ..storage import Storage
from .jobs import cleanup_once, recover_stale_jobs, server_is_up


def _interactive() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):  # pragma: no cover - stdin chiuso
        return False


def main(argv: list[str] | None = None) -> int:
    """Avvia la TUI. Exit code: 0 = ok, 2 = ambiente non adatto."""
    if argv:
        print("la TUI non accetta argomenti: usa `./noesis tui`", file=sys.stderr)
        return 2
    if not _interactive():
        print(
            "la TUI richiede un terminale interattivo.\n"
            "Per l'uso da script o in pipe: ./run-cli.sh --help",
            file=sys.stderr,
        )
        return 2
    try:
        from .app import NoesisTUI
    except ImportError as exc:  # Textual non installato
        print(
            f"Textual non disponibile ({exc}).\n"
            "Installa le dipendenze della TUI: "
            "uv pip install --python .venv/bin/python -r requirements-tui.txt",
            file=sys.stderr,
        )
        return 2

    settings = Settings.from_env()
    settings.ensure_dirs()
    storage = Storage(settings)
    try:
        # Job della TUI rimasti appesi (processo morto) → interrupted.
        recover_stale_jobs(storage)
        # Pulizia una tantum: senza server, il janitor periodico non esiste.
        cleanup_once(storage, settings)
        if server_is_up(settings):
            print(
                "attenzione: il server risponde su "
                f"{settings.host}:{settings.port}. La TUI non avvierà job "
                "finché è attivo (evita la doppia esecuzione sulla stessa "
                "cartella dati).",
                file=sys.stderr,
            )
        NoesisTUI(settings, storage).run()
    finally:
        storage.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
