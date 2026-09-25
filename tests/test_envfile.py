"""Configurazione su file: schema, validazione e I/O atomico (``app/envfile.py``)."""

from __future__ import annotations

import os
import stat

import pytest

from app.config import Settings
from app.envfile import (
    SETTINGS_SCHEMA,
    InvalidValue,
    config_path,
    group_specs,
    load_env_file,
    parse_env_file,
    render_env_file,
    save_env_file,
    spec_by_name,
    specs_for_web,
    validate_value,
)


# ── schema ──────────────────────────────────────────────────────────────────


def test_nomi_unici_e_formato():
    names = [spec.name for spec in SETTINGS_SCHEMA]
    assert len(names) == len(set(names))
    for name in names:
        assert name.isupper()
        assert name.replace("_", "").isalnum()


def test_ogni_campo_esiste_in_settings():
    """Coerenza schema ↔ Settings: non scriviamo variabili che l'app ignora."""
    from dataclasses import fields as dataclass_fields

    field_names = {f.name for f in dataclass_fields(Settings)}
    settings = Settings()
    for spec in SETTINGS_SCHEMA:
        if spec.field is None:
            continue
        assert spec.field in field_names, f"{spec.name} → campo mancante {spec.field}"
        if spec.index is not None:
            value = getattr(settings, spec.field)
            assert isinstance(value, dict) and spec.index in value


def test_web_esclude_le_chiavi_di_deploy():
    web = {spec.name for spec in specs_for_web()}
    for name in ("HOST", "PORT", "ROLE", "QUEUE_BACKEND", "DATA_DIR", "CACHE_ROOT"):
        assert name not in web
    # La chiave è modificabile dal web (write-only) ma resta un segreto.
    key = spec_by_name("OPENROUTER_API_KEY")
    assert key is not None and key.secret and key.web_editable


def test_group_specs_copre_le_web_editable():
    seen = {spec.name for _g, _it, _en, specs in group_specs(web_only=True) for spec in specs}
    assert seen == {spec.name for spec in specs_for_web()}


def test_spec_by_name_case_insensitive():
    assert spec_by_name("max_upload_mb") is spec_by_name("MAX_UPLOAD_MB")
    assert spec_by_name("NON_ESISTE") is None


# ── I/O ─────────────────────────────────────────────────────────────────────


def test_parse_ignora_commenti_e_strizza_le_virgolette():
    values = parse_env_file(
        "# commento\nHOST=0.0.0.0\nKEY=\"sk-abc\"\nVUOTO=\nnon una riga\n"
    )
    assert values == {"HOST": "0.0.0.0", "KEY": "sk-abc", "VUOTO": ""}


def test_render_aggiunge_il_segnaposto_del_segreto():
    text = render_env_file({"HOST": "0.0.0.0"}, secret_placeholder="OPENROUTER_API_KEY")
    assert "HOST=0.0.0.0" in text
    assert "# OPENROUTER_API_KEY=" in text

    text2 = render_env_file(
        {"HOST": "0.0.0.0", "OPENROUTER_API_KEY": "sk-or-x"},
        secret_placeholder="OPENROUTER_API_KEY",
    )
    assert "OPENROUTER_API_KEY=sk-or-x" in text2
    assert "# OPENROUTER_API_KEY=" not in text2


def test_save_fonde_e_rimuove(tmp_path):
    path = config_path(tmp_path)
    save_env_file(path, {"MAX_UPLOAD_MB": "100", "TERMS_VERSION": "2.0"})
    save_env_file(path, {"MAX_UPLOAD_MB": "250"})
    values = load_env_file(path)
    assert values["MAX_UPLOAD_MB"] == "250"
    assert values["TERMS_VERSION"] == "2.0"  # non persa

    save_env_file(path, remove=["TERMS_VERSION"])
    assert "TERMS_VERSION" not in load_env_file(path)


def test_save_e_atomico_e_privato(tmp_path):
    path = config_path(tmp_path)
    save_env_file(path, {"HOST": "0.0.0.0"})
    assert not list(tmp_path.glob("*.tmp"))  # nessun file temporaneo lasciato
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_overwrite_azzera(tmp_path):
    path = config_path(tmp_path)
    save_env_file(path, {"A_KEY": "1", "B_KEY": "2"})
    save_env_file(path, {"C_KEY": "3"}, overwrite=True)
    assert load_env_file(path) == {"C_KEY": "3"}


def test_load_con_defaults(tmp_path):
    values = load_env_file(config_path(tmp_path), defaults={"ROLE": "all"})
    assert values == {"ROLE": "all"}


# ── validazione ─────────────────────────────────────────────────────────────


def test_validate_int_e_limiti():
    spec = spec_by_name("MAX_UPLOAD_MB")
    assert validate_value(spec, " 42 ") == "42"
    with pytest.raises(InvalidValue):
        validate_value(spec, "0")  # sotto il minimo
    with pytest.raises(InvalidValue):
        validate_value(spec, "abc")


def test_validate_bool_normalizza():
    spec = spec_by_name("AUTOSIZE")
    assert validate_value(spec, "yes") == "true"
    assert validate_value(spec, "0") == "false"
    assert validate_value(spec, "sì") == "true"
    with pytest.raises(InvalidValue):
        validate_value(spec, "forse")


def test_validate_choice():
    spec = spec_by_name("ROLE")
    assert validate_value(spec, "api") == "api"
    with pytest.raises(InvalidValue):
        validate_value(spec, "root")


def test_validate_porta_con_massimo():
    spec = spec_by_name("PORT")
    assert validate_value(spec, "18080") == "18080"
    with pytest.raises(InvalidValue):
        validate_value(spec, "70000")


# ── caricamento nell'app (app.config) ───────────────────────────────────────


def _with_clean_env():
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        before = dict(os.environ)
        try:
            yield
        finally:
            os.environ.clear()
            os.environ.update(before)

    return _ctx()


def test_loader_file_vale_e_ambiente_vince(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    save_env_file(config_path(data), {"MAX_UPLOAD_MB": "111", "TERMS_VERSION": "9.9"})
    with _with_clean_env():
        monkeypatch.setenv("DATA_DIR", str(data))
        monkeypatch.setenv("TERMS_VERSION", "1.1")  # l'ambiente vince
        monkeypatch.delenv("MAX_UPLOAD_MB", raising=False)
        settings = Settings.from_env()
    assert settings.max_upload_mb == 111
    assert settings.terms_version == "1.1"


def test_loader_ignora_ambiente_vuoto(tmp_path, monkeypatch):
    """Docker passa la chiave vuota: non deve bloccare il valore del file."""
    data = tmp_path / "data"
    data.mkdir()
    save_env_file(config_path(data), {"OPENROUTER_API_KEY": "sk-or-file"})
    with _with_clean_env():
        monkeypatch.setenv("DATA_DIR", str(data))
        monkeypatch.setenv("OPENROUTER_API_KEY", "")
        settings = Settings.from_env()
    assert settings.openrouter_api_key == "sk-or-file"
