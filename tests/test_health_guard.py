"""Test di /health arricchito, guardia pre-job e comando --doctor."""

from __future__ import annotations

from helpers import pdf_bytes


def _upload(client, pages=2):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("t.pdf", pdf_bytes(pages), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health_cheap_reports_engine_and_key(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert "engine_available" in body
    assert "engine_runnable" in body
    assert "key_present" in body
    assert body["checks"] is None


def test_health_deep_runs_diagnostics(client, monkeypatch):
    from app import diagnostics
    from app.diagnostics import CheckResult, Status

    def fake_run_all(ctx, **kwargs):
        return [
            CheckResult("engine.bin", Status.OK),
            CheckResult("key.valid", Status.OK, code="key_valid"),
        ]

    monkeypatch.setattr(diagnostics, "run_all", fake_run_all)
    response = client.get("/api/v1/health", params={"deep": 1})
    body = response.json()
    assert body["status"] == "ok"
    assert [c["id"] for c in body["checks"]] == ["engine.bin", "key.valid"]


def test_health_deep_degraded(client, monkeypatch):
    from app import diagnostics
    from app.diagnostics import CheckResult, Status

    monkeypatch.setattr(
        diagnostics, "run_all",
        lambda ctx, **kw: [CheckResult("uv", Status.WARN, code="uv_missing")],
    )
    body = client.get("/api/v1/health", params={"deep": 1}).json()
    assert body["status"] == "degraded"


def test_job_llm_without_key_is_rejected(client, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    document = _upload(client)
    response = client.post(
        "/api/v1/jobs",
        json={"doc_id": document["doc_id"], "pages": "1", "engine": "llm"},
    )
    assert response.status_code == 409
    assert "OPENROUTER_API_KEY" in response.json()["detail"]


def test_job_llm_guard_can_be_disabled(client, settings, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings.preflight_guard = False
    document = _upload(client)
    response = client.post(
        "/api/v1/jobs",
        json={"doc_id": document["doc_id"], "pages": "1", "engine": "llm"},
    )
    assert response.status_code == 201


def test_doctor_cli_ok(tmp_path, monkeypatch, capsys):
    from app import diagnostics
    from app.cli import main
    from app.diagnostics import CheckResult, Status

    def fake_run_all(ctx, on_result=None, **kwargs):
        results = [CheckResult("engine.bin", Status.OK)]
        if on_result:
            for result in results:
                on_result(result)
        return results

    monkeypatch.setattr(diagnostics, "run_all", fake_run_all)
    code = main(["--doctor", "--data-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "engine.bin" in out


def test_doctor_cli_failure_exit_code(tmp_path, monkeypatch, capsys):
    from app import diagnostics
    from app.cli import main
    from app.diagnostics import CheckResult, Status

    monkeypatch.setattr(
        diagnostics, "run_all",
        lambda ctx, **kw: [
            CheckResult("engine.bin", Status.FAIL, code="engine_missing")
        ],
    )
    code = main(["--doctor", "--data-dir", str(tmp_path)])
    capsys.readouterr()
    assert code == 2
