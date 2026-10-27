"""Preset prestazioni allineati al desktop ``noesis-pdf-cloner`` 0.2.0.

Il preset governa i *default* dei flag e dei campi LLM; una variabile
d'ambiente esplicita deve sempre vincere.
"""

from __future__ import annotations

import pytest

from app.config import PRESETS, Settings

_ENGINE_KEYS = (
    "PERFORMANCE_PRESET", "FAST_ENGINE", "FAST_FLAGS", "FAST_WORKER",
    "PDF_LLM_MODEL", "PDF_LLM_BASE_URL", "PDF_LLM_TIMEOUT",
    "PDF_LLM_POOL_WORKERS", "PDF_LLM_REASONING_EFFORT",
    "PDF_LLM_JSON_MODE", "PDF_LLM_SYSTEM_PROMPT",
    "QPS_GOOGLE", "QPS_BING", "NUMERIC_LISTS",
)


def _settings(monkeypatch, tmp_path, preset: str | None = None, **env: str):
    for key in _ENGINE_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    if preset is not None:
        monkeypatch.setenv("PERFORMANCE_PRESET", preset)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings.from_env()


def test_presets_are_the_desktop_ones():
    assert set(PRESETS) == {"normal", "fast", "fastest"}
    assert PRESETS["fastest"]["model"] == "openai/gpt-oss-120b"
    assert PRESETS["fastest"]["reasoning"] == "minimal"
    assert PRESETS["fastest"]["pool"] == 8
    assert PRESETS["fast"]["model"] == "inception/mercury-2.5"


def test_fastest_applies_model_reasoning_and_pool(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path, "fastest")
    assert settings.fast_engine is True
    assert settings.fast_worker is True
    assert settings.llm_model == "openai/gpt-oss-120b"
    assert settings.llm_reasoning_effort == "minimal"
    assert settings.llm_pool_workers == 8
    assert settings.llm_system_prompt.startswith("Sei un traduttore medico")
    # Il proxy locale del desktop non parte qui: base URL resta OpenRouter.
    assert settings.llm_base_url == "https://openrouter.ai/api/v1"


def test_fast_and_normal_keep_mercury(monkeypatch, tmp_path):
    fast = _settings(monkeypatch, tmp_path, "fast")
    assert fast.fast_engine is True
    assert fast.fast_worker is True
    assert fast.llm_model == "inception/mercury-2.5"
    assert fast.llm_pool_workers == 4

    normal = _settings(monkeypatch, tmp_path, "normal")
    assert normal.fast_engine is False
    assert normal.fast_worker is False
    assert normal.llm_model == "inception/mercury-2.5"


def test_explicit_env_wins_over_preset(monkeypatch, tmp_path):
    settings = _settings(
        monkeypatch, tmp_path, "fastest",
        PDF_LLM_MODEL="vendor/custom-model",
        PDF_LLM_POOL_WORKERS="2",
    )
    assert settings.llm_model == "vendor/custom-model"
    assert settings.llm_pool_workers == 2


def test_unknown_preset_falls_back_to_fast(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path, "turbo")
    assert settings.performance_preset == "fast"


def test_engine_timeout_and_qps_defaults(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path)
    assert settings.llm_timeout == 90
    assert settings.qps_google == 2
    assert settings.qps_bing == 5


def test_engine_timeout_and_qps_are_configurable(monkeypatch, tmp_path):
    settings = _settings(
        monkeypatch, tmp_path,
        PDF_LLM_TIMEOUT="45", QPS_GOOGLE="1", QPS_BING="3",
    )
    assert settings.llm_timeout == 45
    assert settings.qps_google == 1
    assert settings.qps_bing == 3
