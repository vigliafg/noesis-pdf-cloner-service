"""Seam OCR.

Rileva se una pagina è priva di testo estraibile (scansione). Oggi non esegue
OCR: segnala soltanto la condizione, così la pipeline può mostrarla nel log e
in futuro attivare un backend OCR (Tesseract/cloud) dietro ``FEATURE_OCR``.
"""

from __future__ import annotations

from pathlib import Path

from .config import Settings


def is_enabled(settings: Settings) -> bool:
    return settings.feature_ocr


def page_needs_ocr(pdf_path: str | Path, page: int) -> bool:
    """True se la pagina non contiene testo estraibile.

    Import pigro di PyMuPDF: il modulo resta importabile anche senza dipendenze
    PDF (es. in test minimi).
    """
    try:
        import pymupdf  # noqa: PLC0415
    except Exception:  # pragma: no cover
        return False
    try:
        with pymupdf.open(str(pdf_path)) as doc:
            if page < 0 or page >= doc.page_count:
                return False
            text = doc[page].get_text("text").strip()
            return len(text) < 8
    except Exception:  # pragma: no cover
        return False
