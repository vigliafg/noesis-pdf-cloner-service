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
