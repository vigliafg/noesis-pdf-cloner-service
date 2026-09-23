"""Test della CLI gratuita del servizio: stdio sempre UTF-8.

pdf2zh_next esegue lo script come subprocess con ``encoding="utf-8"``: se
scrivessimo in cp1252 (default su Windows) le accentate diventerebbero U+FFFD.
"""

from __future__ import annotations

import io
import sys

from app import gtranslate_cli as g

ACCENTED = "città è però già perché"


def _swap(monkeypatch, stdin_bytes: bytes):
    raw_out = io.BytesIO()
    stdout = io.TextIOWrapper(raw_out, encoding="cp1252")
    stdin = io.TextIOWrapper(io.BytesIO(stdin_bytes), encoding="cp1252")
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    return raw_out


def test_output_is_utf8_with_cp1252_stdout(monkeypatch):
    raw_out = _swap(monkeypatch, b"Hello world")
    monkeypatch.setattr(g, "translate", lambda text: ACCENTED)
    assert g.main() == 0
    text = raw_out.getvalue().decode("utf-8")
    assert text.strip() == ACCENTED
    assert "\ufffd" not in text


def test_input_is_decoded_as_utf8_with_cp1252_stdin(monkeypatch):
    raw_out = _swap(monkeypatch, ACCENTED.encode("utf-8"))
    seen: dict = {}

    def fake(text):
        seen["text"] = text
        return text

    monkeypatch.setattr(g, "translate", fake)
    assert g.main() == 0
    assert seen["text"] == ACCENTED
    assert raw_out.getvalue().decode("utf-8").strip() == ACCENTED


def test_force_utf8_reconfigures_streams(monkeypatch):
    class _Stream:
        encoding = None

        def reconfigure(self, **kwargs):
            self.encoding = kwargs.get("encoding")

    stream = _Stream()
    monkeypatch.setattr(sys, "stdin", stream)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", stream)
    g._force_utf8_stdio()
    assert stream.encoding == "utf-8"
