"""Test del motore: chiave documento, cache versionata, anteprima, binario."""

import pytest

from app.engine import CloneEngine, find_pdf2zh_bin

from helpers import make_pdf


def test_doc_key_is_content_hash(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", 2)
    key1 = CloneEngine.compute_doc_key(pdf)
    key2 = CloneEngine.compute_doc_key(pdf)
    assert key1 == key2
    assert len(key1) == 64
    other = make_pdf(tmp_path / "b.pdf", 3)
    assert CloneEngine.compute_doc_key(other) != key1


def test_cache_paths_are_versioned(tmp_path):
    engine = CloneEngine(tmp_path / "cache", cache_version="1")
    google = engine.translated_path_for("k", 0, "google", "en", "it")
    bing = engine.translated_path_for("k", 0, "bing", "en", "it")
    french = engine.translated_path_for("k", 0, "google", "en", "fr")
    assert google != bing
    assert google != french
    assert "cs1-e1" in str(google)
    upgraded = CloneEngine(tmp_path / "cache", cache_version="2")
    assert upgraded.translated_path_for("k", 0, "google", "en", "it") != google


def test_page_metadata_and_thumbnail(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", 3)
    assert CloneEngine.page_count(pdf) == 3
    assert CloneEngine.page_labels(pdf) == ["1", "2", "3"]
    png = CloneEngine.render_thumb(pdf, 0, width=80)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(Exception):
        CloneEngine.render_thumb(pdf, 99)


def test_find_pdf2zh_override(tmp_path):
    fake = tmp_path / "pdf2zh_next"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    assert find_pdf2zh_bin(fake) == fake


def test_engine_injects_llm_env_into_subprocess(tmp_path, monkeypatch):
    """Il sottoprocesso della catena google riceve modello/base/key del servizio."""
    import subprocess

    import pymupdf

    pdf = make_pdf(tmp_path / "a.pdf", 1)
    engine = CloneEngine(
        tmp_path / "cache",
        llm_model="inception/mercury-2.5",
        llm_base_url="https://example.test/v1",
        api_key="segreta",
    )
    fake_bin = tmp_path / "pdf2zh_next"
    fake_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(engine, "pdf2zh_bin", lambda: fake_bin)

    captured: dict = {}

    def fake_run(cmd, env, cancel_event):
        captured.update(env)
        out_dir = cmd[cmd.index("--output") + 1]
        doc = pymupdf.open()
        doc.new_page()
        doc.save(str(tmp_path / "fake.mono.pdf"))
        doc.close()
        import shutil

        shutil.move(str(tmp_path / "fake.mono.pdf"), out_dir + "fake.mono.pdf")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(engine, "_run_engine", fake_run)
    out = engine.translate_page(pdf, engine.doc_key(pdf), 0, "google", "en", "it")
    assert out.is_file()
    assert captured["PDF_LANG_IN"] == "en"
    assert captured["PDF_LANG_OUT"] == "it"
    assert captured["PDF_LLM_MODEL"] == "inception/mercury-2.5"
    assert captured["PDF_LLM_BASE_URL"] == "https://example.test/v1"
    assert captured["OPENROUTER_API_KEY"] == "segreta"
