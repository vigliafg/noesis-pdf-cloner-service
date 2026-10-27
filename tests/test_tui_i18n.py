"""Test di i18n e rilevamento terminale della TUI."""

from __future__ import annotations

import sys

import app.tui.i18n as i18n


def teardown_function():
    i18n.set_language("it")
    i18n.set_ascii(False)


def test_default_is_italian():
    assert i18n.get_language() == "it"
    assert i18n.T("home.title") == "Lavori"


def test_set_language_en():
    assert i18n.set_language("en") == "en"
    assert i18n.T("home.title") == "Jobs"
    assert i18n.T("wizard.btn.start") == "Start translation"


def test_unknown_language_falls_back_to_italian():
    assert i18n.set_language("de") == "it"
    assert i18n.set_language(None) == "it"


def test_format_kwargs_and_missing_key():
    i18n.set_language("it")
    assert i18n.T("home.open_failed", path="/tmp/x") == "non riesco ad aprire /tmp/x"
    assert i18n.T("chiave.inesistente") == "chiave.inesistente"


def test_format_with_missing_kwarg_returns_raw():
    # Una stringa con placeholder ma senza il parametro non deve esplodere.
    assert "{path}" in i18n.T("home.open_failed")


def test_ascii_flag():
    i18n.set_ascii(True)
    assert i18n.ascii_mode() is True
    i18n.set_ascii(False)
    assert i18n.ascii_mode() is False


def test_detect_dark_from_colorfgbg(monkeypatch):
    monkeypatch.setenv("COLORFGBG", "15;0")
    assert i18n._detect_dark() is True
    monkeypatch.setenv("COLORFGBG", "0;15")
    assert i18n._detect_dark() is False
    monkeypatch.delenv("COLORFGBG", raising=False)
    assert i18n._detect_dark() is True


class _Tty:
    def __init__(self, tty: bool) -> None:
        self._tty = tty
        self.encoding = "utf-8"

    def isatty(self) -> bool:
        return self._tty


def test_probe_terminal_minimal_and_no_color(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Tty(True))
    monkeypatch.setattr(sys, "stdout", _Tty(True))
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("COLORFGBG", "15;0")
    profile = i18n.probe_terminal()
    assert profile.isatty is True
    assert profile.minimal is True
    assert profile.no_color is True
    assert profile.dark is True


def test_probe_terminal_normal(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Tty(False))
    monkeypatch.setattr(sys, "stdout", _Tty(False))
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    profile = i18n.probe_terminal()
    assert profile.isatty is False
    assert profile.minimal is False
    assert profile.utf8 is True
