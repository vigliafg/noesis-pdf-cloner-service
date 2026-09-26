"""Test del motore: chiave documento, cache versionata, anteprima, binario."""

import pytest

from app.engine import CloneEngine, classify_engine_failure, find_pdf2zh_bin

from helpers import make_pdf


def test_classify_engine_failure_codes():
    cases = {
        "HTTP 401 Unauthorized": "invalid_key",
        "invalid_api_key": "invalid_key",
        "403 Forbidden": "forbidden",
        "402 Payment Required": "no_credits",
        "429 Too Many Requests": "rate_limited",
        "404 model not found": "model_not_found",
        "getaddrinfo failed": "network",
        "Connection timed out": "network",
        "qualcosa di strano": "unknown",
    }
    for text, code in cases.items():
        assert classify_engine_failure(text) == code, text


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


def test_kill_uses_taskkill_tree_on_windows(monkeypatch):
    """Su Windows il cancel termina l'intero albero di pdf2zh_next (taskkill /T)."""
    from app import engine as engine_module

    calls: list[list[str]] = []

    class FakeProc:
        pid = 4242

        def poll(self):  # noqa: ANN001
            return None

        def wait(self, timeout=None):  # noqa: ANN001
            return 0

        def kill(self):  # noqa: ANN001
            raise AssertionError("kill() non deve essere usato su Windows")

    monkeypatch.setattr(engine_module, "_is_windows", lambda: True)
    monkeypatch.setattr(
        engine_module.subprocess, "run", lambda cmd, **kw: calls.append(list(cmd))
    )
    CloneEngine._kill(FakeProc())
    assert calls, "taskkill non invocato"
    assert calls[0][:2] == ["taskkill", "/PID"]
    assert "/T" in calls[0] and "/F" in calls[0]


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
    captured_cmd: list = []

    def fake_run(cmd, env, cancel_event):
        captured.update(env)
        captured_cmd.extend(cmd)
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
    assert captured["PYTHONIOENCODING"] == "utf-8"
    assert captured["PDF_LLM_MODEL"] == "inception/mercury-2.5"
    assert captured["PDF_LLM_BASE_URL"] == "https://example.test/v1"
    assert captured["OPENROUTER_API_KEY"] == "segreta"
    # Versione attesa da pdf2zh_next (prefisso PDF2ZH_).
    assert captured["PDF2ZH_OPENAI_API_KEY"] == "segreta"
    # La chiave non deve MAI comparire nella riga di comando (argv).
    assert all("segreta" not in str(a) for a in captured_cmd)
    assert "--openai-api-key" not in captured_cmd


def test_google_clitranslator_command_roundtrips_windows_paths(tmp_path, monkeypatch):
    """Il comando è letto da pdf2zh con ``shlex.split``: deve reggere i percorsi
    Windows con backslash (altrimenti nessun ``.mono.pdf``)."""
    import shlex

    from app import engine as engine_module

    engine = CloneEngine(tmp_path / "cache")
    win_py = r"C:\Users\mario rossi\.venv2\Scripts\python.exe"
    win_cli = r"C:\Temp\_MEI1\gtranslate_cli.py"
    monkeypatch.setattr(engine_module, "venv_python_for", lambda *_: win_py)
    monkeypatch.setattr(engine_module, "_gtranslate_cli_path", lambda: win_cli)
    flags, _ = engine._translator_flags("google")
    command = flags[flags.index("--clitranslator-command") + 1]
    assert shlex.split(command) == [win_py, win_cli]


# ── Feature sperimentale "motore veloce" (default OFF, reversibile) ─────────


def _fast_engine(tmp_path, **kwargs):
    from app.engine import CloneEngine

    return CloneEngine(tmp_path / "cache", **kwargs)


def test_fast_engine_default_off_uses_binary(tmp_path):
    engine = _fast_engine(tmp_path)
    fake = tmp_path / "pdf2zh_next"
    fake.write_text("#!/bin/sh\n")
    assert engine._fast_engine_active() is False
    assert engine._engine_launch_prefix(fake) == [str(fake)]


def test_fast_engine_env_killswitch_overrides_setting(tmp_path, monkeypatch):
    engine = _fast_engine(tmp_path, fast_engine=True)
    fake = tmp_path / "pdf2zh_next"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("NOESIS_FAST_ENGINE", "0")
    assert engine._fast_engine_active() is False
    assert engine._engine_launch_prefix(fake) == [str(fake)]


def test_fast_engine_env_enables_without_setting(tmp_path, monkeypatch):
    engine = _fast_engine(tmp_path)
    monkeypatch.setenv("NOESIS_FAST_ENGINE", "1")
    assert engine._fast_engine_active() is True


def test_fast_engine_uses_wrapper_when_present(tmp_path, monkeypatch):
    from app import engine as engine_module

    engine = _fast_engine(tmp_path, fast_engine=True)
    fake = tmp_path / "pdf2zh_next"
    fake.write_text("#!/bin/sh\n")
    wrapper = tmp_path / "engine_wrapper.py"
    wrapper.write_text("")
    monkeypatch.setattr(
        engine_module, "_engine_wrapper_path", lambda: wrapper
    )
    monkeypatch.setattr(engine_module, "venv_python_for", lambda *_: "/venv/python")
    assert engine._engine_launch_prefix(fake) == ["/venv/python", str(wrapper)]


def test_fast_engine_missing_wrapper_falls_back(tmp_path, monkeypatch):
    from app import engine as engine_module

    engine = _fast_engine(tmp_path, fast_engine=True)
    fake = tmp_path / "pdf2zh_next"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setattr(
        engine_module, "_engine_wrapper_path", lambda: tmp_path / "missing.py"
    )
    assert engine._engine_launch_prefix(fake) == [str(fake)]


def test_fast_engine_pool_explicit_only_when_fast(tmp_path):
    engine = _fast_engine(tmp_path, llm_pool_workers=6)
    flags, _ = engine._translator_flags("llm")
    assert "--pool-max-workers" not in flags  # comportamento storico
    engine.fast_engine = True
    flags, _ = engine._translator_flags("llm")
    assert flags[flags.index("--pool-max-workers") + 1] == "6"
    assert flags[flags.index("--qps") + 1] == "6"


def test_fast_engine_quality_flags_gated(tmp_path, monkeypatch):
    from app import engine as engine_module

    engine = _fast_engine(tmp_path, fast_engine=True, fast_flags=False)
    fake = tmp_path / "pdf2zh_next"
    fake.write_text("#!/bin/sh\n")
    assert engine._quality_flags(fake) == []
    engine.fast_flags = True
    monkeypatch.setattr(engine_module, "page_has_text", lambda *_: True)
    flags = engine._quality_flags(fake)
    assert "--skip-scanned-detection" in flags
    assert "--skip-formula-offset-calculation" in flags


def test_fast_engine_skip_scanned_omitted_for_textless_page(tmp_path, monkeypatch):
    from app import engine as engine_module

    engine = _fast_engine(tmp_path, fast_engine=True, fast_flags=True)
    fake = tmp_path / "pdf2zh_next"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setattr(engine_module, "page_has_text", lambda *_: False)
    assert "--skip-scanned-detection" not in engine._quality_flags(fake)


def test_fast_engine_version_tag_marker(tmp_path):
    from app.engine import FAST_ENGINE_TAG

    engine = _fast_engine(tmp_path)
    off = engine._version_tag()
    assert FAST_ENGINE_TAG not in off
    engine.fast_engine = True
    assert FAST_ENGINE_TAG in engine._version_tag()


# ── Fase 2/3: worker persistente e opzioni LLM avanzate ─────────────────────


def test_llm_reasoning_and_json_flags_only_when_fast(tmp_path):
    from app.engine import CloneEngine

    engine = CloneEngine(
        tmp_path / "cache",
        fast_engine=True,
        llm_reasoning_effort="minimal",
        llm_json_mode=True,
    )
    flags, _ = engine._translator_flags("llm")
    assert flags[flags.index("--openai-reasoning-effort") + 1] == "minimal"
    assert "--openai-enable-json-mode" in flags

    slow = CloneEngine(
        tmp_path / "cache2",
        llm_reasoning_effort="minimal",
        llm_json_mode=True,
    )
    flags, _ = slow._translator_flags("llm")
    assert "--openai-reasoning-effort" not in flags  # feature OFF
    assert "--openai-enable-json-mode" not in flags


def test_persistent_engine_requires_flags(tmp_path, monkeypatch):
    from app import engine as engine_module
    from app.engine import CloneEngine

    worker = tmp_path / "engine_worker.py"
    worker.write_text("")
    monkeypatch.setattr(engine_module, "_engine_worker_path", lambda: worker)

    engine = CloneEngine(tmp_path / "cache", fast_engine=True, fast_worker=True)
    assert engine._persistent_active() is True
    engine.fast_engine = False
    assert engine._persistent_active() is False
    engine.fast_engine = True
    engine.fast_worker = False
    assert engine._persistent_active() is False


def test_persistent_engine_env_fingerprint_changes(tmp_path):
    from app.engine import CloneEngine

    engine = CloneEngine(tmp_path / "cache", api_key="k1")
    env1 = engine._engine_env("en", "it")
    assert env1["PDF2ZH_OPENAI_API_KEY"] == "k1"
    engine.api_key = "k2"
    env2 = engine._engine_env("en", "it")
    assert env1 != env2


def test_worker_client_module_exposes_api():
    from app import engine_client

    assert hasattr(engine_client, "EngineWorkerClient")
    assert hasattr(engine_client.EngineWorkerClient, "ensure_started")
    assert hasattr(engine_client.EngineWorkerClient, "run")
