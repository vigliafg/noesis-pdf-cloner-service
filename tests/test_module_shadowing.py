"""Guardia contro lo shadowing di moduli della standard library.

Il motore veloce lancia ``app/engine_wrapper.py`` e ``app/engine_worker.py``
come **script**: in quel contesto ``sys.path[0]`` è la cartella ``app/``.
Se in ``app/`` esiste un modulo con lo stesso nome di un modulo della standard
library (es. ``app/queue.py``), qualunque libreria che lo importa — ``pdf2zh_next``
importa ``logging.handlers``, che a sua volta fa ``import queue`` — carica il
**nostro** file al posto di quello standard e va in errore.

Regressione storica: ``app/queue.py`` oscurava ``queue`` e faceva fallire ogni
traduzione con i preset ``fast``/``fastest`` (ImportError nel wrapper/worker).

Questo test impedisce di reintrodurre il problema.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _app_module_names() -> list[str]:
    return sorted(p.stem for p in APP_DIR.glob("*.py") if p.stem != "__init__")


def test_no_app_module_shadows_stdlib() -> None:
    """Nessun modulo in ``app/`` deve coincidere con un modulo stdlib."""
    stdlib = set(sys.stdlib_module_names)
    clashes = [name for name in _app_module_names() if name in stdlib]
    assert not clashes, (
        "Moduli in app/ che oscurano la standard library (rompono i processi "
        f"figli del motore avviati come script): {clashes}"
    )


def test_queue_module_not_shadowed_with_app_on_syspath(tmp_path: Path) -> None:
    """Con ``app/`` in testa a ``sys.path``, ``import queue`` resta lo stdlib.

    Simula il contesto dei processi figli del motore (script con ``app/`` come
    prima voce di ``sys.path``).
    """
    import subprocess

    script = (
        "import sys; "
        f"sys.path.insert(0, {str(APP_DIR)!r}); "
        "import queue; "
        "print(queue.__file__)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    resolved = Path(proc.stdout.strip()).resolve()
    assert APP_DIR not in resolved.parents, (
        f"'import queue' ha risolto un modulo di app/ invece dello stdlib: {resolved}"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
