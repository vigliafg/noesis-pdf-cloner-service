"""API di configurazione: accesso locale, validazione, segreti, persistenza."""

from __future__ import annotations

from app.diagnostics import CheckResult, Status
from app.envfile import config_path, load_env_file


# ── accesso ─────────────────────────────────────────────────────────────────


def test_config_solo_da_locale(client):
    """Il client di test non è locale: 403 su API e pagina."""
    assert client.get("/api/v1/settings").status_code == 403
    assert client.put("/api/v1/settings", json={"values": {}}).status_code == 403
    assert client.get("/settings").status_code == 403


def test_config_da_locale_ok(admin_client):
    response = admin_client.get("/api/v1/settings")
    assert response.status_code == 200
    assert admin_client.get("/settings").status_code == 200


def test_proxy_rifiutato(admin_client):
    """Un reverse proxy sullo stesso host non deve valere come locale."""
    headers = {"X-Forwarded-For": "203.0.113.7"}
    assert admin_client.get("/api/v1/settings", headers=headers).status_code == 403


def test_home_mostra_l_ingranaggio_solo_da_locale(client, admin_client):
    assert "⚙ Impostazioni" not in client.get("/").text
    assert "⚙ Impostazioni" in admin_client.get("/").text


def test_pagina_settings_da_locale(admin_client):
    body = admin_client.get("/settings").text
    assert "Impostazioni del server" in body
    assert "/static/settings.js" in body


# ── lettura ─────────────────────────────────────────────────────────────────


def test_get_non_espone_segreti(admin_client, settings):
    settings.openrouter_api_key = "sk-or-server-segreto"
    body = admin_client.get("/api/v1/settings").json()
    assert body["key_present"] is True
    assert "sk-or-server-segreto" not in admin_client.get("/api/v1/settings").text

    key_row = next(
        s for g in body["groups"] for s in g["settings"]
        if s["name"] == "OPENROUTER_API_KEY"
    )
    assert key_row["secret"] is True
    assert key_row["value"] is None
    assert key_row["present"] is True


def test_get_esclude_le_chiavi_di_deploy(admin_client):
    names = {
        s["name"]
        for g in admin_client.get("/api/v1/settings").json()["groups"]
        for s in g["settings"]
    }
    assert "HOST" not in names and "ROLE" not in names and "DATA_DIR" not in names
    assert "MAX_UPLOAD_MB" in names


# ── scrittura ───────────────────────────────────────────────────────────────


def test_put_salva_e_rende_effettivo_al_riavvio(admin_client, settings):
    response = admin_client.put(
        "/api/v1/settings",
        json={"values": {"MAX_UPLOAD_MB": "250", "REQUIRE_TERMS_ACCEPTANCE": "true"}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["restart_required"] is True
    assert set(body["saved"]) == {"MAX_UPLOAD_MB", "REQUIRE_TERMS_ACCEPTANCE"}

    values = load_env_file(config_path(settings.data_dir))
    assert values["MAX_UPLOAD_MB"] == "250"
    assert values["REQUIRE_TERMS_ACCEPTANCE"] == "true"

    # Il file è la fonte: la GET lo segnala come "in_file".
    again = admin_client.get("/api/v1/settings").json()
    row = next(
        s for g in again["groups"] for s in g["settings"] if s["name"] == "MAX_UPLOAD_MB"
    )
    assert row["in_file"] is True


def test_put_valore_invalido_422(admin_client):
    response = admin_client.put(
        "/api/v1/settings", json={"values": {"MAX_UPLOAD_MB": "zero"}}
    )
    assert response.status_code == 422


def test_put_chiave_sconosciuta_422(admin_client):
    response = admin_client.put(
        "/api/v1/settings", json={"values": {"NON_ESISTE": "1"}}
    )
    assert response.status_code == 422


def test_put_chiave_di_deploy_403(admin_client):
    response = admin_client.put("/api/v1/settings", json={"values": {"HOST": "0.0.0.0"}})
    assert response.status_code == 403


def test_put_segreto_scrive_e_svuota(admin_client, settings):
    path = config_path(settings.data_dir)
    admin_client.put(
        "/api/v1/settings", json={"values": {"OPENROUTER_API_KEY": "sk-or-nuova"}}
    )
    assert load_env_file(path)["OPENROUTER_API_KEY"] == "sk-or-nuova"

    # Svuotare il segreto lo rimuove dal file.
    admin_client.put(
        "/api/v1/settings", json={"values": {"OPENROUTER_API_KEY": ""}}
    )
    assert "OPENROUTER_API_KEY" not in load_env_file(path)


def test_reset_riporta_al_default(admin_client, settings):
    path = config_path(settings.data_dir)
    admin_client.put("/api/v1/settings", json={"values": {"MAX_UPLOAD_MB": "250"}})
    assert "MAX_UPLOAD_MB" in load_env_file(path)

    response = admin_client.put("/api/v1/settings", json={"reset": ["MAX_UPLOAD_MB"]})
    assert response.status_code == 200
    assert "MAX_UPLOAD_MB" not in load_env_file(path)


# ── verifica chiave ─────────────────────────────────────────────────────────


def test_verify_key_senza_chiave_400(admin_client, settings):
    settings.openrouter_api_key = ""
    assert admin_client.post("/api/v1/settings/verify-key").status_code == 400


def test_verify_key_usa_la_chiave_del_server(admin_client, settings, monkeypatch):
    import app.api.v1.settings as settings_api

    settings.openrouter_api_key = "sk-or-server"
    monkeypatch.setattr(
        settings_api, "check_key_valid",
        lambda *a, **k: CheckResult("key.valid", Status.OK, code="key_valid"),
    )
    monkeypatch.setattr(
        settings_api, "check_key_credits",
        lambda *a, **k: CheckResult("key.credits", Status.OK, code="ok"),
    )
    monkeypatch.setattr(
        settings_api, "check_llm_model",
        lambda *a, **k: CheckResult("llm.model", Status.OK, code="model_ok"),
    )
    response = admin_client.post("/api/v1/settings/verify-key")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "sk-or-server" not in response.text
