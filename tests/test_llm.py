"""BYOK: chiave OpenRouter per-job e validazione chiave/modello."""

from types import SimpleNamespace

from app.diagnostics import CheckResult, Status
from app.worker import JobRunner
from helpers import pdf_bytes


def test_runner_usa_la_chiave_del_job_e_la_consuma(tmp_path, settings):
    runner = JobRunner(storage=None, settings=settings)
    runner.set_job_key("job1", "sk-or-utente")
    engine = runner.engine_for(SimpleNamespace(job_id="job1"))
    assert engine.api_key == "sk-or-utente"
    # La chiave è consumata: un secondo engine_for usa la chiave del server.
    engine2 = runner.engine_for(SimpleNamespace(job_id="job1"))
    assert engine2.api_key == settings.openrouter_api_key


def test_runner_senza_chiave_usa_quella_del_server(settings):
    settings.openrouter_api_key = "sk-or-server"
    runner = JobRunner(storage=None, settings=settings)
    engine = runner.engine_for(SimpleNamespace(job_id="job2"))
    assert engine.api_key == "sk-or-server"


def test_byok_rifiutato_con_worker_separati(client, settings):
    settings.role = "worker"
    upload = client.post(
        "/api/v1/documents",
        files={"file": ("t.pdf", pdf_bytes(1), "application/pdf")},
    )
    doc_id = upload.json()["doc_id"]
    response = client.post(
        "/api/v1/jobs",
        json={
            "doc_id": doc_id,
            "pages": "1",
            "engine": "llm",
            "dst_lang": "it",
            "llm_api_key": "sk-or-utente",
        },
    )
    assert response.status_code == 409
    assert "ROLE" in response.json()["detail"]


def test_preflight_accetta_la_chiave_utente(client, settings):
    """Senza chiave server, un job llm con chiave utente non è rifiutato a monte."""
    settings.role = "all"
    settings.openrouter_api_key = ""
    upload = client.post(
        "/api/v1/documents",
        files={"file": ("t.pdf", pdf_bytes(1), "application/pdf")},
    )
    doc_id = upload.json()["doc_id"]
    response = client.post(
        "/api/v1/jobs",
        json={
            "doc_id": doc_id,
            "pages": "1",
            "engine": "llm",
            "dst_lang": "it",
            "llm_api_key": "sk-or-utente",
        },
    )
    assert response.status_code == 201, response.text


def test_validate_endpoint(client, monkeypatch):
    import app.api.v1.llm as llm

    monkeypatch.setattr(
        llm, "check_key_valid",
        lambda *a, **k: CheckResult("key.valid", Status.OK, code="key_valid"),
    )
    monkeypatch.setattr(
        llm, "check_key_credits",
        lambda *a, **k: CheckResult("key.credits", Status.OK, code="ok"),
    )
    monkeypatch.setattr(
        llm, "check_llm_model",
        lambda *a, **k: CheckResult("llm.model", Status.OK, code="model_ok"),
    )
    response = client.post(
        "/api/v1/llm/validate", json={"api_key": "sk-or-test"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["key_valid"]["status"] == "ok"
    assert body["model"]["status"] == "ok"
    # La chiave non deve essere rimandata indietro nella risposta.
    assert "sk-or-test" not in response.text


def test_meta_espone_byok(client):
    meta = client.get("/api/v1/meta").json()
    assert meta["byok_supported"] is True
    assert meta["llm_model"]
