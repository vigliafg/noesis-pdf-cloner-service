"""Test della logica headless della TUI (niente Textual, niente rete)."""

from __future__ import annotations

import time

import pytest

from app.config import Settings
from app.models import JobRecord, JobState
from app.storage import Storage
from app.tui import jobs as headless

from helpers import FakeEngine, make_pdf


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


def test_suggest_output_name_is_safe(tmp_path):
    pdf = make_pdf(tmp_path / "Libro Strano (2024).pdf", 2)
    name = headless.suggest_output_name(pdf, "it")
    # sanitize_stem (condiviso con CLI e upload): niente spazi né caratteri
    # non ASCII, così il nome è sicuro su tutti i filesystem.
    assert name == "Libro_Strano_2024__it"
    assert "/" not in name and " " not in name


def test_preview_selection_first_and_last(tmp_path):
    pdf = make_pdf(tmp_path / "doc.pdf", 5)
    previews = headless.preview_selection(pdf, [1, 2, 3])
    assert [p.number for p in previews] == [2, 4]
    assert "page 2" in previews[0].text
    assert previews[0].caption == "fisica 2"


def test_preview_selection_single_page(tmp_path):
    pdf = make_pdf(tmp_path / "doc.pdf", 3)
    previews = headless.preview_selection(pdf, [2])
    assert len(previews) == 1
    assert previews[0].page == 2
    assert "page 3" in previews[0].text


def test_preview_blank_page_has_no_text(tmp_path):
    """Una pagina senza livello testuale (scansione) non deve far fallire."""
    import pymupdf

    pdf = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page().insert_text((72, 72), "ciao")
    doc.save(str(pdf))
    doc.close()

    previews = headless.preview_selection(pdf, [0])
    assert previews[0].text == ""
    assert "nessun testo" in headless.preview_lines(previews)[1]


def test_preview_non_ascii_text_is_truncated(tmp_path):
    import pymupdf

    pdf = tmp_path / "accenti.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "àèìòù " * 80)
    doc.save(str(pdf))
    doc.close()

    text = headless.preview_selection(pdf, [0], max_chars=50)[0].text
    assert text.endswith("…")
    assert len(text) <= 50


def test_copy_artifact_never_overwrites(tmp_path):
    src = tmp_path / "artifacts" / "doc_it.pdf"
    src.parent.mkdir(parents=True)
    src.write_text("primo")
    out = tmp_path / "out"

    first = headless.copy_artifact(str(src), out)
    assert first is not None and first.name == "doc_it.pdf"
    second = headless.copy_artifact(str(src), out)
    assert second is not None and second.name == "doc_it-2.pdf"
    assert (out / "doc_it.pdf").read_text() == "primo"


def test_copy_artifact_missing_source(tmp_path):
    assert headless.copy_artifact(None, tmp_path) is None
    assert headless.copy_artifact(str(tmp_path / "nope.pdf"), tmp_path) is None


def test_recover_stale_jobs_only_tui(tmp_path, settings):
    storage = Storage(settings)
    engine = FakeEngine(settings.cache_root, max_engine_procs=2)
    pdf = make_pdf(tmp_path / "doc.pdf", 2)

    def make_job(owner: str) -> JobRecord:
        from app.job_factory import create_document_and_job

        _doc, job = create_document_and_job(
            storage, engine, pdf, pages_spec="1",
            owner_id=owner, state=JobState.running,
        )
        return job

    mine = make_job(headless.OWNER_ID)
    server = make_job("api")

    assert headless.recover_stale_jobs(storage) == 1
    assert storage.get_job(mine.job_id).state is JobState.interrupted
    # finished valorizzato: senza, il janitor non ripulirebbe il job.
    assert storage.get_job(mine.job_id).finished is not None
    assert storage.get_job(server.job_id).state is JobState.running
    storage.close()


def test_state_labels_and_terminal_states():
    assert headless.state_label(JobState.done) == "completato"
    assert headless.state_label("running") == "in corso"
    assert headless.is_terminal(JobState.done)
    assert headless.is_terminal("interrupted")
    assert not headless.is_terminal(JobState.running)


def test_format_duration():
    assert headless.format_duration(None) == "—"
    assert headless.format_duration(1500) == "1.5 s"
    assert headless.format_duration(65_000) == "1 min 05 s"
    assert headless.format_duration(3_725_000) == "1 h 02 min"


def test_server_is_up_false_without_server(settings):
    settings.port = 1  # porta privilegiata: nessun listener
    started = time.monotonic()
    assert headless.server_is_up(settings, timeout=0.2) is False
    assert time.monotonic() - started < 3


def test_local_host_and_web_url(settings):
    settings.host = "0.0.0.0"
    settings.port = 18080
    assert headless.web_url(settings) == "http://127.0.0.1:18080"
    settings.host = "192.168.1.5"
    assert headless.web_url(settings) == "http://192.168.1.5:18080"


def test_health_symbol():
    from app.diagnostics import Status

    assert headless.health_symbol(Status.OK) == "OK"
    assert headless.health_symbol(Status.FAIL) == "XX"
