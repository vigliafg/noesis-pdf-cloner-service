"""Test del runner della TUI (thread, cancel, stato terminale garantito)."""

from __future__ import annotations

import threading
import time

import pytest

from app.config import Settings
from app.engine import TranslationCancelled
from app.job_factory import create_document_and_job
from app.models import JobState
from app.storage import Storage
from app.tui.jobs import OWNER_ID
from app.tui.runner import TuiJobRunner

from helpers import FailingEngine, FakeEngine, make_pdf


@pytest.fixture
def settings(tmp_path) -> Settings:
    config = Settings(
        data_dir=tmp_path / "data",
        page_concurrency=2,
        max_engine_procs=2,
        page_timeout=10,
        janitor_interval_seconds=3600,
    )
    config.ensure_dirs()
    return config


def _job(storage, engine, pdf, pages="1-2"):
    _doc, job = create_document_and_job(
        storage,
        engine,
        pdf,
        pages_spec=pages,
        owner_id=OWNER_ID,
        state=JobState.running,
        max_pages=100,
    )
    return job


def _runner(storage, settings, engine, job, *, events, pages, done):
    return TuiJobRunner(
        storage=storage,
        engine=engine,
        job=job,
        settings=settings,
        on_event=events.append,
        on_page=lambda *args: pages.append(args),
        on_done=lambda result, error: done.append((result, error)),
    )


def test_runner_completes_job(tmp_path, settings):
    storage = Storage(settings)
    engine = FakeEngine(settings.cache_root, max_engine_procs=1)
    pdf = make_pdf(tmp_path / "doc.pdf", 3)
    job = _job(storage, engine, pdf, "1-3")

    events, pages, done = [], [], []
    runner = _runner(storage, settings, engine, job, events=events, pages=pages, done=done)
    runner.start()
    assert runner.join(15)

    assert done and done[0][1] is None
    result = done[0][0]
    assert result is not None and result.pages_done == 3
    stored = storage.get_job(job.job_id)
    assert stored.state is JobState.done
    assert stored.artifact_path and stored.artifact_path.endswith(".pdf")
    assert len(pages) == 3 and all(item[3] for item in pages)
    assert any(event.get("stage") == "done" for event in events)
    storage.close()


def test_runner_reports_partial_failures(tmp_path, settings):
    storage = Storage(settings)
    engine = FailingEngine(settings.cache_root, fail_page=1, max_engine_procs=1)
    pdf = make_pdf(tmp_path / "doc.pdf", 3)
    job = _job(storage, engine, pdf, "1-3")

    events, pages, done = [], [], []
    runner = _runner(storage, settings, engine, job, events=events, pages=pages, done=done)
    runner.start()
    assert runner.join(15)

    result = done[0][0]
    assert result is not None
    assert result.pages_done == 2 and result.pages_failed == 1
    assert storage.get_job(job.job_id).state is JobState.done
    assert any(not item[3] for item in pages)
    storage.close()


def test_runner_all_pages_failed_is_error_state(tmp_path, settings):
    storage = Storage(settings)
    engine = FailingEngine(settings.cache_root, fail_page=0, max_engine_procs=1)
    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    job = _job(storage, engine, pdf, "1")

    events, pages, done = [], [], []
    runner = _runner(storage, settings, engine, job, events=events, pages=pages, done=done)
    runner.start()
    assert runner.join(15)

    # Il runner non ha eccezioni: è la pipeline a chiudere il job in errore.
    assert done[0][1] is None
    assert storage.get_job(job.job_id).state is JobState.error
    storage.close()


class _BlockingEngine(FakeEngine):
    """Traduce solo quando arriva il cancel: simula una pagina in corso."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.started = threading.Event()

    def translate_page(self, src, doc_key, page, engine, lang_in, lang_out, cancel_event=None):
        self.started.set()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise TranslationCancelled("annullato")
            time.sleep(0.01)
        raise AssertionError("il cancel non è arrivato")


def test_runner_cancel(tmp_path, settings):
    storage = Storage(settings)
    engine = _BlockingEngine(settings.cache_root, max_engine_procs=1)
    pdf = make_pdf(tmp_path / "doc.pdf", 2)
    job = _job(storage, engine, pdf, "1-2")

    events, pages, done = [], [], []
    runner = _runner(storage, settings, engine, job, events=events, pages=pages, done=done)
    runner.start()
    assert engine.started.wait(10)
    runner.cancel()
    assert runner.join(10)

    result = done[0][0]
    assert result is not None and result.cancelled is True
    assert storage.get_job(job.job_id).state is JobState.cancelled
    storage.close()


def test_runner_guarantees_terminal_state_on_pipeline_error(tmp_path, settings):
    storage = Storage(settings)
    engine = FakeEngine(settings.cache_root, max_engine_procs=1)
    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    job = _job(storage, engine, pdf, "1")
    pdf.unlink()  # la pipeline esce prima di aggiornare il job

    events, pages, done = [], [], []
    runner = _runner(storage, settings, engine, job, events=events, pages=pages, done=done)
    runner.start()
    assert runner.join(10)

    result, error = done[0]
    assert result is None
    assert error and "mancante" in error
    stored = storage.get_job(job.job_id)
    assert stored.state is JobState.error
    assert stored.finished is not None
    storage.close()
