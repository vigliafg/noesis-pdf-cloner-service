"""Pagine legali del servizio e pulsanti in home."""

DEFAULT_HELP = "https://vigliafg.github.io/noesis-pdf-cloner-service/"


def test_home_ha_pulsanti_termini_e_guida(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert 'href="/terms"' in body
    assert DEFAULT_HELP in body
    assert "Termini d'uso" in body
    assert "Guida" in body
    assert 'id="accept-terms"' in body


def test_pagina_termini_it_e_en(client):
    it = client.get("/terms")
    assert it.status_code == 200
    assert "Termini d&#x27;uso" in it.text or "Termini d'uso" in it.text
    assert "AGPL" in it.text

    en = client.get("/terms", params={"lang": "en"})
    assert en.status_code == 200
    assert "Terms of Use" in en.text


def test_pagine_legali_disponibili(client):
    for path, needle in (
        ("/privacy", "Privacy"),
        ("/disclaimer", "garanzia"),
        ("/acceptable-use", "accettabile"),
        ("/legal/security", "Sicurezza"),
        ("/legal/trademark", "Marchio"),
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert needle.lower() in response.text.lower(), path


def test_pagina_legale_sconosciuta_404(client):
    assert client.get("/legal/non-esiste").status_code == 404


def test_meta_espone_versione_termini_e_help(client):
    meta = client.get("/api/v1/meta").json()
    assert meta["terms_version"]
    assert meta["help_url"] == DEFAULT_HELP
    assert meta["terms_required"] is False


def test_gate_accettazione_termini(settings, ctx):
    """Con REQUIRE_TERMS_ACCEPTANCE attivo, un job senza terms_version è rifiutato."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from helpers import pdf_bytes

    settings.require_terms_acceptance = True
    app = create_app(settings, context=ctx)
    with TestClient(app) as local:
        upload = local.post(
            "/api/v1/documents",
            files={"file": ("t.pdf", pdf_bytes(1), "application/pdf")},
        )
        doc_id = upload.json()["doc_id"]
        payload = {"doc_id": doc_id, "pages": "1", "engine": "google", "dst_lang": "it"}

        missing = local.post("/api/v1/jobs", json=payload)
        assert missing.status_code == 428

        wrong = local.post(
            "/api/v1/jobs", json={**payload, "terms_version": "0.0"}
        )
        assert wrong.status_code == 428

        ok = local.post(
            "/api/v1/jobs", json={**payload, "terms_version": settings.terms_version}
        )
        assert ok.status_code == 201

