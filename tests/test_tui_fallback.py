"""Test del wizard a righe (fallback senza Textual)."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.storage import Storage
from app.tui import fallback
from app.tui.jobs import OWNER_ID

from helpers import FakeEngine, make_pdf


@pytest.fixture
def settings(tmp_path) -> Settings:
    config = Settings(
        data_dir=tmp_path / "data",
        page_concurrency=1,
        max_engine_procs=1,
        page_timeout=10,
        janitor_interval_seconds=3600,
    )
    config.ensure_dirs()
    return config


def _script(monkeypatch, answers: list[str]) -> None:
    iterator = iter(answers)

    def fake_input(prompt: str = "") -> str:
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", fake_input)


def _patch_engine(monkeypatch, **kwargs) -> None:
    monkeypatch.setattr(
        fallback,
        "build_engine",
        lambda settings, api_key=None: FakeEngine(
            settings.cache_root, max_engine_procs=1, **kwargs
        ),
    )
    monkeypatch.setattr(
        fallback, "server_is_up", lambda settings, timeout=0.7: False
    )


def test_fallback_produces_output(tmp_path, settings, monkeypatch, capsys):
    pdf = make_pdf(tmp_path / "doc.pdf", 3)
    out_dir = tmp_path / "out"
    _patch_engine(monkeypatch)
    _script(
        monkeypatch,
        [
            str(pdf),       # PDF
            "1-2",          # pagine
            "auto",         # lingua sorgente
            "it",           # lingua destinazione
            "google",       # motore
            "",             # nome output (automatico)
            str(out_dir),   # cartella
            "merged",       # formato
            "s",            # conferma
        ],
    )
    storage = Storage(settings)
    assert fallback.run(settings, storage) == 0

    files = list(out_dir.glob("*.pdf"))
    assert len(files) == 1
    job = storage.list_jobs(limit=1, owner_id=OWNER_ID)[0]
    assert job.state.value == "done"
    assert job.pages_done == 2
    printed = capsys.readouterr().out
    assert "pagina 1: ok" in printed
    assert "completato" in printed
    storage.close()


def test_fallback_retries_invalid_pdf(tmp_path, settings, monkeypatch, capsys):
    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    _patch_engine(monkeypatch)
    _script(
        monkeypatch,
        [
            str(tmp_path / "non-esiste.pdf"),  # primo tentativo: errore
            str(pdf),                          # secondo: valido
            "all",
            "auto",
            "it",
            "google",
            "",
            str(tmp_path / "out"),
            "merged",
            "s",
        ],
    )
    storage = Storage(settings)
    assert fallback.run(settings, storage) == 0
    assert "file non trovato" in capsys.readouterr().out
    storage.close()


def test_fallback_refuses_when_server_is_up(tmp_path, settings, monkeypatch):
    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    _patch_engine(monkeypatch)
    monkeypatch.setattr(
        fallback, "server_is_up", lambda settings, timeout=0.7: True
    )
    _script(
        monkeypatch,
        [
            str(pdf), "all", "auto", "it", "google", "",
            str(tmp_path / "out"), "merged", "s",
        ],
    )
    storage = Storage(settings)
    assert fallback.run(settings, storage) == 2
    assert storage.list_jobs(limit=5, owner_id=OWNER_ID) == []
    storage.close()


def test_fallback_aborts_at_confirmation(tmp_path, settings, monkeypatch):
    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    _patch_engine(monkeypatch)
    _script(
        monkeypatch,
        [
            str(pdf), "all", "auto", "it", "google", "",
            str(tmp_path / "out"), "merged", "n",
        ],
    )
    storage = Storage(settings)
    assert fallback.run(settings, storage) == 1
    assert storage.list_jobs(limit=5, owner_id=OWNER_ID) == []
    storage.close()
