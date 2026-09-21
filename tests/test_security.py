"""Test di sicurezza: sanitizzazione nomi, validazione upload, rate limit."""

import pytest

from app.security import RateLimiter, safe_join, sanitize_stem, validate_pdf_upload


def test_sanitize_stem_removes_traversal():
    assert sanitize_stem("../../etc/passwd") == "etc_passwd"
    assert sanitize_stem("report finale") == "report_finale"
    assert sanitize_stem("my.doc.pdf") == "my.doc"
    assert sanitize_stem("..") == "output"
    assert sanitize_stem("") == "output"


def test_validate_pdf_upload():
    validate_pdf_upload("a.pdf", 10, 200)
    with pytest.raises(ValueError):
        validate_pdf_upload("a.txt", 10, 200)
    with pytest.raises(ValueError):
        validate_pdf_upload("a.pdf", 0, 200)
    with pytest.raises(ValueError):
        validate_pdf_upload("a.pdf", 500 * 1024 * 1024, 200)


def test_rate_limiter_window():
    limiter = RateLimiter(per_minute=2)
    assert limiter.allow("ip", now=1.0)
    assert limiter.allow("ip", now=2.0)
    assert not limiter.allow("ip", now=3.0)
    assert limiter.allow("ip", now=62.0)  # finestra scorsa


def test_safe_join_blocks_escape(tmp_path):
    ok = safe_join(tmp_path, "a", "b.pdf")
    assert str(ok).startswith(str(tmp_path.resolve()))
    with pytest.raises(ValueError):
        safe_join(tmp_path, "..", "outside")
