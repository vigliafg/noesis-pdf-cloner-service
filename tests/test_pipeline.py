"""Test della pipeline condivisa (con motore fittizio)."""

import zipfile

import pymupdf

from app.engine import CloneEngine
from app.logging_setup import JobLogger, read_events
from app.models import DocumentRecord, JobRecord, JobState, RangeMode
from app.pipeline import run_job
from app.storage import Storage

from helpers import FailingEngine, FakeEngine, SlowFirstEngine, make_pdf


def _setup(settings, pages=3, **kwargs):
    pdf = make_pdf(settings.data_dir / "src.pdf", pages)
    storage = Storage(settings)
    storage.create_document(
        DocumentRecord(
            doc_id="d",
            filename="src.pdf",
            sha256=CloneEngine.compute_doc_key(pdf),
            page_count=pages,
            path=str(pdf),
            page_labels=[str(i + 1) for i in range(pages)],
        )
    )
    job = JobRecord(
        job_id="j",
        doc_id="d",
        pages=list(range(pages)),
        engine="google",
        output_name="out",
        range_mode=kwargs.get("range_mode", RangeMode.merged),
        pages_total=pages,
    )
    storage.create_job(job)
    return storage, job


def test_merged_pdf(settings):
    storage, job = _setup(settings, pages=3)
    engine = FakeEngine(settings.cache_root)
    result = run_job(
        storage=storage, engine=engine, job=job, settings=settings,
        logger=JobLogger(storage, "j"),
    )
    assert result.pages_done == 3
    assert result.artifact_path.endswith(".pdf")
    with pymupdf.open(result.artifact_path) as doc:
        assert doc.page_count == 3
    assert storage.get_job("j").state is JobState.done
    assert storage.usage_totals()["pages"] == 3
    events = read_events(storage, "j")
    assert any(e["stage"] == "started" for e in events)
    assert any(e["stage"] == "merge" for e in events)
    storage.close()


def test_single_zip(settings):
    storage, job = _setup(settings, pages=3, range_mode=RangeMode.single)
    engine = FakeEngine(settings.cache_root)
    result = run_job(storage=storage, engine=engine, job=job, settings=settings)
    assert result.artifact_path.endswith(".zip")
    with zipfile.ZipFile(result.artifact_path) as archive:
        names = archive.namelist()
    assert len(names) == 3
    assert names[0].startswith("out_p")
    storage.close()


def test_merged_pdf_keeps_selection_order(settings):
    """Regressione: l'ordine non deve dipendere dal completamento in parallelo."""
    storage, job = _setup(settings, pages=3)
    engine = SlowFirstEngine(settings.cache_root, delay=0.4)
    result = run_job(storage=storage, engine=engine, job=job, settings=settings)
    assert result.pages_done == 3
    with pymupdf.open(result.artifact_path) as doc:
        assert "pagina 1" in doc[0].get_text("text")
        assert "pagina 2" in doc[1].get_text("text")
        assert "pagina 3" in doc[2].get_text("text")
    storage.close()


def test_partial_failure(settings):
    storage, job = _setup(settings, pages=3)
    engine = FailingEngine(settings.cache_root, fail_page=1)
    result = run_job(storage=storage, engine=engine, job=job, settings=settings)
    assert result.pages_done == 2
    assert result.pages_failed == 1
    assert storage.get_job("j").state is JobState.done
    with pymupdf.open(result.artifact_path) as doc:
        assert doc.page_count == 2
    storage.close()


def test_all_pages_fail(settings):
    storage, job = _setup(settings, pages=2)
    result = run_job(
        storage=storage, engine=_AllFail(settings.cache_root), job=job, settings=settings
    )
    assert result.pages_done == 0
    assert result.artifact_path is None
    assert storage.get_job("j").state is JobState.error
    storage.close()


class _AllFail(FakeEngine):
    def translate_page(self, *args, **kwargs):
        raise RuntimeError("sempre errore")
