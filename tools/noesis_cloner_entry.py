"""Entry point for the standalone (PyInstaller) ``noesis-cloner`` binary."""

from app.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
