"""Utility condivise dai test (PDF di esempio, engine fittizio)."""

from __future__ import annotations

import os
from pathlib import Path

from app.engine import CloneEngine
from app.worker import JobRunner


def make_pdf(path: Path, pages: int = 3) -> Path:
    import pymupdf

    doc = pymupdf.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Hello page {index + 1}")
    doc.save(str(path))
    doc.close()
    return path


def pdf_bytes(pages: int = 3) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for index in range(pages):
        doc.new_page().insert_text((72, 72), f"page {index + 1}")
    data = doc.tobytes()
    doc.close()
    return data


class FakeEngine(CloneEngine):
    """Engine senza pdf2zh: scrive una pagina tradotta fittizia."""

    def translate_page(
        self, src, doc_key, page, engine, lang_in, lang_out, cancel_event=None
    ):
        import pymupdf

        out = self.translated_path_for(doc_key, page, engine, lang_in, lang_out)
        if out.is_file():
            return out
        out.parent.mkdir(parents=True, exist_ok=True)
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), f"tradotto pagina {page + 1}")
        tmp = out.with_name(out.name + ".tmp")
        doc.save(str(tmp))
        doc.close()
        os.replace(tmp, out)
        return out


class FailingEngine(FakeEngine):
    """Fallisce sulla pagina indicata (0-based)."""

    def __init__(self, *args, fail_page: int = 1, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fail_page = fail_page

    def translate_page(
        self, src, doc_key, page, engine, lang_in, lang_out, cancel_event=None
    ):
        if page == self.fail_page:
            raise RuntimeError("errore simulato")
        return super().translate_page(
            src, doc_key, page, engine, lang_in, lang_out, cancel_event
        )


class FakeRunner(JobRunner):
    """Runner di test che usa :class:`FakeEngine`."""

    def engine_for(self, job) -> CloneEngine:
        return FakeEngine(self.settings.cache_root, max_engine_procs=2, page_timeout=30)
