"""Copertine delle tessere di storico: miniatura della prima pagina del job.

Service-only: non esiste una controparte nel repo desktop (là non c'è una
griglia di storico con copertine). La copertina è accessoria: la sua
generazione non deve mai far fallire una richiesta né un job.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from .engine import CloneEngine
from .models import JobRecord
from .storage import Storage

COVER_WIDTH = 420


def ensure_cover(storage: Storage, job: JobRecord, *, width: int = COVER_WIDTH) -> Path | None:
    """Rende (una volta sola) la copertina in ``artifact_dir/cover.png``.

    Ritorna il percorso della copertina, oppure ``None`` se il documento
    sorgente non è (più) disponibile o il render fallisce. È idempotente:
    se il file esiste lo restituisce senza toccarlo.

    Pensata per due chiamanti:
    - l'endpoint ``GET /jobs/{id}/cover``, che la genera in modo lazy;
    - il worker a fine job, così la copertina sopravvive alla pulizia del
      documento (retention job > documento) anche se nessuno l'ha mai vista.
    """
    cover = storage.job_cover_path(job.job_id)
    if cover.is_file():
        return cover

    document = storage.get_document(job.doc_id)
    if document is None:
        return None

    page = job.pages[0] if job.pages else 0
    try:
        data = CloneEngine.render_thumb(document.path, page, width=width)
    except Exception:  # noqa: BLE001 - copertina accessoria
        return None

    try:
        cover.parent.mkdir(parents=True, exist_ok=True)
        tmp = cover.with_suffix(f".{uuid.uuid4().hex}.tmp")
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, cover)
    except OSError:
        return None
    return cover
