"""Test headless della TUI Textual (driver `run_test`, nessun terminale reale)."""

from __future__ import annotations

import asyncio
import sys

import pytest

from app.config import Settings
from app.storage import Storage
from app.tui.app import NoesisTUI
from app.tui.jobs import OWNER_ID
import app.tui.screens as screens

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


def _no_server(monkeypatch) -> None:
    monkeypatch.setattr(screens, "server_is_up", lambda settings, timeout=0.7: False)


def _fake_engine(monkeypatch) -> None:
    monkeypatch.setattr(
        screens,
        "build_engine",
        lambda settings, api_key=None: FakeEngine(
            settings.cache_root, max_engine_procs=2
        ),
    )


async def _wait(pilot, condition, *, tries: int = 200, delay: float = 0.05) -> bool:
    for _ in range(tries):
        await pilot.pause(delay)
        if condition():
            return True
    return False


def test_app_starts_on_home(tmp_path, settings):
    storage = Storage(settings)

    async def scenario() -> None:
        app = NoesisTUI(settings, storage)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert type(app.screen).__name__ == "HomeScreen"
            assert app.screen.query_one("#jobs") is not None
            await pilot.press("n")
            await pilot.pause()
            assert type(app.screen).__name__ == "WizardScreen"

    asyncio.run(scenario())
    storage.close()


def test_wizard_rejects_missing_file(tmp_path, settings):
    storage = Storage(settings)

    async def scenario() -> None:
        app = NoesisTUI(settings, storage)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            wizard = app.screen
            wizard.query_one("#pdf-path").value = str(tmp_path / "non-esiste.pdf")
            await pilot.pause()
            await pilot.click("#wiz-next")
            await pilot.pause()
            assert wizard.step == 0

    asyncio.run(scenario())
    storage.close()


def test_full_flow_writes_output(tmp_path, settings, monkeypatch):
    _no_server(monkeypatch)
    _fake_engine(monkeypatch)
    storage = Storage(settings)
    pdf = make_pdf(tmp_path / "doc.pdf", 4)
    out_dir = tmp_path / "out"

    async def scenario() -> None:
        app = NoesisTUI(settings, storage)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause(0.2)
            wizard = app.screen
            wizard.query_one("#pdf-path").value = str(pdf)
            await pilot.click("#wiz-next")
            await pilot.pause(0.2)
            wizard.query_one("#pages").value = "1-2"
            await pilot.pause(0.2)
            for _ in range(3):
                await pilot.click("#wiz-next")
                await pilot.pause(0.2)
            assert wizard.step == 4
            wizard.query_one("#out-dir").value = str(out_dir)
            await pilot.pause(0.2)
            await pilot.click("#wiz-next")
            await pilot.pause(0.2)
            assert await _wait(pilot, lambda: type(app.screen).__name__ == "RunScreen")

            run = app.screen
            assert await _wait(pilot, lambda: run._finished, tries=400)
            await pilot.pause(0.3)

            assert run.out_path is not None and run.out_path.is_file()
            assert run.out_path.parent == out_dir
            job = storage.list_jobs(limit=5, owner_id=OWNER_ID)[0]
            assert job.state.value == "done"
            assert job.pages_done == 2
            # La TUI punta al file copiato per l'utente, non alla cartella interna.
            assert job.artifact_path == str(run.out_path)

            # Torna alla Home senza lasciare job attivi.
            await pilot.press("q")
            await pilot.pause()
            assert type(app.screen).__name__ == "HomeScreen"

    asyncio.run(scenario())
    storage.close()


def test_wizard_refuses_when_server_is_up(tmp_path, settings, monkeypatch):
    monkeypatch.setattr(screens, "server_is_up", lambda settings, timeout=0.7: True)
    _fake_engine(monkeypatch)
    storage = Storage(settings)
    pdf = make_pdf(tmp_path / "doc.pdf", 2)

    async def scenario() -> None:
        app = NoesisTUI(settings, storage)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause(0.2)
            wizard = app.screen
            wizard.query_one("#pdf-path").value = str(pdf)
            await pilot.click("#wiz-next")
            await pilot.pause(0.2)
            for _ in range(3):
                await pilot.click("#wiz-next")
                await pilot.pause(0.2)
            await pilot.click("#wiz-next")
            await _wait(
                pilot,
                lambda: not wizard.query_one("#wiz-next").disabled,
                tries=100,
            )
            assert type(app.screen).__name__ == "WizardScreen"
            # Nessun job creato: la guardia anti co-esecuzione ha fermato tutto.
            assert storage.list_jobs(limit=5, owner_id=OWNER_ID) == []

    asyncio.run(scenario())
    storage.close()


def test_main_requires_tty(monkeypatch, capsys):
    from app.tui import __main__ as tui_main

    class _NotATty:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(sys, "stdin", _NotATty())
    monkeypatch.setattr(sys, "stdout", _NotATty())
    assert tui_main.main([]) == 2
    assert "terminale interattivo" in capsys.readouterr().err


def test_wizard_single_mode_produces_zip(tmp_path, settings, monkeypatch):
    _no_server(monkeypatch)
    _fake_engine(monkeypatch)
    storage = Storage(settings)
    pdf = make_pdf(tmp_path / "doc.pdf", 2)
    out_dir = tmp_path / "out"

    async def scenario() -> None:
        app = NoesisTUI(settings, storage)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause(0.2)
            wizard = app.screen
            wizard.query_one("#pdf-path").value = str(pdf)
            await pilot.click("#wiz-next")
            await pilot.pause(0.2)
            for _ in range(3):
                await pilot.click("#wiz-next")
                await pilot.pause(0.2)
            assert wizard.step == 4

            await pilot.click("#rm-single")
            await pilot.pause(0.2)
            assert wizard._range_mode().value == "single"

            wizard.query_one("#out-dir").value = str(out_dir)
            await pilot.pause(0.2)
            await pilot.click("#wiz-next")
            assert await _wait(pilot, lambda: type(app.screen).__name__ == "RunScreen")
            run = app.screen
            assert await _wait(pilot, lambda: run._finished, tries=400)
            await pilot.pause(0.3)
            assert run.out_path is not None
            assert run.out_path.suffix == ".zip"
            assert run.out_path.is_file()

    asyncio.run(scenario())
    storage.close()


def test_theme_toggle(tmp_path, settings):
    storage = Storage(settings)

    async def scenario() -> None:
        app = NoesisTUI(settings, storage, dark=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.theme == "textual-dark"
            await pilot.press("t")
            await pilot.pause()
            assert app.theme == "textual-light"
            await pilot.press("t")
            await pilot.pause()
            assert app.theme == "textual-dark"

    asyncio.run(scenario())
    storage.close()


def test_light_theme_and_ansi(tmp_path, settings):
    storage = Storage(settings)

    async def scenario() -> None:
        app = NoesisTUI(settings, storage, dark=False, ansi=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.theme == "ansi-light"

    asyncio.run(scenario())
    storage.close()


def test_file_picker_selects_pdf(tmp_path, settings):
    storage = Storage(settings)
    pdf = make_pdf(tmp_path / "doc.pdf", 2)

    async def scenario() -> None:
        app = NoesisTUI(settings, storage)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause(0.3)
            wizard = app.screen
            await pilot.click("#pdf-browse")
            await pilot.pause(0.3)
            picker = app.screen
            assert type(picker).__name__ == "FilePicker"
            picker._go(tmp_path)
            await pilot.pause(0.2)
            picker._accept(pdf)
            await pilot.pause(0.3)
            assert app.screen is wizard
            assert wizard.query_one("#pdf-path").value == str(pdf)
            assert wizard.page_count == 2

    asyncio.run(scenario())
    storage.close()


def test_file_picker_ignores_non_pdf(tmp_path, settings):
    storage = Storage(settings)
    other = tmp_path / "note.txt"
    other.write_text("x", encoding="utf-8")

    async def scenario() -> None:
        app = NoesisTUI(settings, storage)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause(0.3)
            wizard = app.screen
            await pilot.click("#pdf-browse")
            await pilot.pause(0.3)
            picker = app.screen
            picker._accept(other)
            await pilot.pause(0.2)
            assert app.screen is picker  # resta aperto
            picker.action_cancel()
            await pilot.pause(0.2)
            assert app.screen is wizard
            assert wizard.query_one("#pdf-path").value == ""

    asyncio.run(scenario())
    storage.close()
