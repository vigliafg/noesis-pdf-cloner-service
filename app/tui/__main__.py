"""``python -m app.tui``: avvio della TUI con la configurazione del service.

Sceglie fra Textual e il wizard a righe (terminale minimo, Textual assente o
``--line``), come fanno le altre edizioni headless della famiglia.
"""

from __future__ import annotations

import argparse
import os
import sys

from ..config import Settings
from ..storage import Storage
from .i18n import T, probe_terminal, set_ascii, set_language
from .jobs import cleanup_once, recover_stale_jobs, server_is_up


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="noesis tui", add_help=True, description="TUI di Noesis PDF Cloner"
    )
    parser.add_argument(
        "--theme", choices=("auto", "dark", "light"), default="auto",
        help="tema della TUI (default: auto)",
    )
    parser.add_argument(
        "--lang", choices=("it", "en"), default=None,
        help="lingua dell'interfaccia (default: it)",
    )
    parser.add_argument(
        "--line", action="store_true",
        help="usa il wizard a righe invece di Textual",
    )
    parser.add_argument(
        "--ascii", action="store_true",
        help="caratteri ASCII (terminali senza UTF-8)",
    )
    return parser


def _fallback(settings: Settings, storage: Storage) -> int:
    from .fallback import run as run_fallback

    return run_fallback(settings, storage)


def main(argv: list[str] | None = None) -> int:
    """Avvia la TUI. Exit code: 0 = ok, 2 = ambiente non adatto."""
    args = _parser().parse_args(argv)

    profile = probe_terminal()
    set_language(args.lang or os.environ.get("NOESIS_TUI_LANG") or "it")
    set_ascii(bool(args.ascii or not profile.utf8))

    if not profile.isatty:
        print(T("main.err.tty"), file=sys.stderr)
        return 2

    if args.theme == "dark":
        dark = True
    elif args.theme == "light":
        dark = False
    else:
        dark = profile.dark
    ansi = bool(args.ascii or profile.no_color)

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
                T(
                    "main.warn.server",
                    host=settings.host,
                    port=settings.port,
                ),
                file=sys.stderr,
            )

        if args.line or profile.minimal:
            return _fallback(settings, storage)
        try:
            from .app import NoesisTUI
        except ImportError:  # Textual non installato
            print(T("main.warn.no_textual"), file=sys.stderr)
            return _fallback(settings, storage)
        NoesisTUI(settings, storage, dark=dark, ansi=ansi).run()
        return 0
    finally:
        storage.close()


if __name__ == "__main__":
    raise SystemExit(main())
