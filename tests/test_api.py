"""Test end-to-end dell'API (documenti, anteprima, job, SSE, download)."""

import time
from datetime import datetime, timedelta, timezone

from helpers import pdf_bytes


def _upload(client, pages=3):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("test.pdf", pdf_bytes(pages), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _poll(client, job_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["state"] in {"done", "error", "cancelled", "interrupted"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job non concluso entro il timeout")


def test_upload_metadata(client):
    document = _upload(client, pages=4)
    assert document["page_count"] == 4
    assert document["page_labels"] == ["1", "2", "3", "4"]
    assert document["pages"][0]["number"] == 1
    assert document["pages"][3]["label"] == "4"


def test_upload_rejects_non_pdf(client):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("note.txt", b"ciao", "text/plain")},
    )
    assert response.status_code == 400


def test_thumbnail(client):
    document = _upload(client, pages=2)
    response = client.get(
        f"/api/v1/documents/{document['doc_id']}/thumb",
        params={"page": 0, "w": 80},
    )
    assert response.status_code == 200
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert response.headers["content-type"] == "image/png"

    invalid = client.get(
        f"/api/v1/documents/{document['doc_id']}/thumb", params={"page": 9}
    )
    assert invalid.status_code == 400


def test_delete_document(client):
    document = _upload(client, pages=1)
    assert client.delete(f"/api/v1/documents/{document['doc_id']}").status_code == 204
    assert client.get(f"/api/v1/documents/{document['doc_id']}").status_code == 404


def test_job_merged_flow(client):
    document = _upload(client, pages=3)
    response = client.post(
        "/api/v1/jobs",
        json={
            "doc_id": document["doc_id"],
            "pages": "1-3",
            "dst_lang": "it",
            "engine": "google",
            "output_name": "out",
            "range_mode": "merged",
        },
    )
    assert response.status_code == 201, response.text
    job = _poll(client, response.json()["job_id"])
    assert job["state"] == "done"
    assert job["pages_done"] == 3
    assert job["download_url"]

    download = client.get(f"/api/v1/jobs/{job['job_id']}/download")
    assert download.status_code == 200
    assert download.content[:5] == b"%PDF-"


def test_job_single_zip_flow(client):
    document = _upload(client, pages=3)
    response = client.post(
        "/api/v1/jobs",
        json={
            "doc_id": document["doc_id"],
            "pages": "2,3",
            "dst_lang": "it",
            "engine": "bing",
            "output_name": "out",
            "range_mode": "single",
        },
    )
    assert response.status_code == 201
    job = _poll(client, response.json()["job_id"])
    assert job["state"] == "done"
    assert job["pages_total"] == 2
    download = client.get(f"/api/v1/jobs/{job['job_id']}/download")
    assert download.status_code == 200
    assert download.content[:2] == b"PK"


def test_job_validation(client):
    document = _upload(client, pages=2)
    bad_pages = client.post(
        "/api/v1/jobs",
        json={"doc_id": document["doc_id"], "pages": "9", "dst_lang": "it"},
    )
    assert bad_pages.status_code == 400

    bad_engine = client.post(
        "/api/v1/jobs",
        json={"doc_id": document["doc_id"], "pages": "1", "engine": "boh"},
    )
    assert bad_engine.status_code == 400

    missing = client.post(
        "/api/v1/jobs", json={"doc_id": "nope", "pages": "1"}
    )
    assert missing.status_code == 404


def test_events_stream(client):
    document = _upload(client, pages=2)
    response = client.post(
        "/api/v1/jobs",
        json={"doc_id": document["doc_id"], "pages": "1-2", "dst_lang": "it"},
    )
    job_id = response.json()["job_id"]
    _poll(client, job_id)
    stream = client.get(f"/api/v1/jobs/{job_id}/events")
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "started" in stream.text
    assert "done" in stream.text


def test_cancel_after_done_is_noop(client):
    document = _upload(client, pages=1)
    response = client.post(
        "/api/v1/jobs",
        json={"doc_id": document["doc_id"], "pages": "1", "dst_lang": "it"},
    )
    job_id = response.json()["job_id"]
    _poll(client, job_id)
    cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "done"


def test_job_rejects_over_total_limit(client, ctx):
    ctx.settings.max_pages_total = 1
    document = _upload(client, pages=2)
    response = client.post(
        "/api/v1/jobs",
        json={"doc_id": document["doc_id"], "pages": "1-2", "dst_lang": "it"},
    )
    assert response.status_code == 413


def test_estimate(client):
    document = _upload(client, pages=3)
    response = client.post(
        "/api/v1/jobs/estimate",
        json={
            "doc_id": document["doc_id"], "pages": "1-3",
            "dst_lang": "it", "engine": "google",
        },
    )
    assert response.status_code == 200, response.text
    estimate = response.json()
    assert estimate["pages_total"] == 3
    assert estimate["pages_cached"] == 0
    assert estimate["pages_to_translate"] == 3
    assert estimate["estimated_seconds"] > 0
    assert "cache" in estimate["note"]


def test_estimate_after_cache_hit(client):
    document = _upload(client, pages=2)
    response = client.post(
        "/api/v1/jobs",
        json={"doc_id": document["doc_id"], "pages": "1-2", "dst_lang": "it"},
    )
    _poll(client, response.json()["job_id"])
    estimate = client.post(
        "/api/v1/jobs/estimate",
        json={"doc_id": document["doc_id"], "pages": "1-2", "dst_lang": "it"},
    ).json()
    # doppio: due job con la stessa firma → tutte in cache. Il primo era vuoto,
    # quindi ci aspettiamo 0 da tradurre.
    assert estimate["pages_cached"] == 2
    assert estimate["pages_to_translate"] == 0


def test_scheduled_job_in_future(client):
    document = _upload(client, pages=1)
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    response = client.post(
        "/api/v1/jobs",
        json={
            "doc_id": document["doc_id"], "pages": "1",
            "dst_lang": "it", "start_at": future,
        },
    )
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["state"] == "scheduled"
    assert job["scheduled_at"] is not None
    cancelled = client.post(f"/api/v1/jobs/{job['job_id']}/cancel")
    assert cancelled.json()["state"] == "cancelled"


def test_scheduled_job_in_past_runs(client):
    document = _upload(client, pages=1)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    response = client.post(
        "/api/v1/jobs",
        json={
            "doc_id": document["doc_id"], "pages": "1",
            "dst_lang": "it", "start_at": past,
        },
    )
    job = _poll(client, response.json()["job_id"])
    assert job["state"] == "done"


def test_estimate_llm_commercial_price(client):
    document = _upload(client, pages=2)
    estimate = client.post(
        "/api/v1/jobs/estimate",
        json={
            "doc_id": document["doc_id"], "pages": "1-2",
            "dst_lang": "it", "engine": "openai",
        },
    ).json()
    # Prezzo commerciale di default: 1 centesimo/pagina (EUR).
    assert estimate["currency"] == "EUR"
    assert estimate["cost_cents"] == 2.0
    assert "configurato" in estimate["note"]


def test_estimate_llm_cost_model(client, ctx):
    # Senza prezzo configurato vale l'equazione calibrata (USD).
    ctx.settings.cost_cents_per_page = {}
    document = _upload(client, pages=2)
    estimate = client.post(
        "/api/v1/jobs/estimate",
        json={
            "doc_id": document["doc_id"], "pages": "1-2",
            "dst_lang": "it", "engine": "openai",
        },
    ).json()
    assert estimate["currency"] == "USD"
    assert estimate["cost_cents"] > 0
    assert "overhead" in estimate["note"]


def test_system_endpoint(client):
    data = client.get("/api/v1/system").json()
    assert "resources" in data and "effective" in data
    assert data["role"] == "all"
    assert data["effective"]["workers"] >= 1
    assert data["queue_backend"] in {"db", "memory"}


def test_meta_and_health(client):
    meta = client.get("/api/v1/meta").json()
    assert "google" in meta["engines"]
    assert meta["languages"]["it"] == "Italiano"
    health = client.get("/api/v1/health").json()
    assert health["status"] == "ok"
    assert "queue_length" in health
    assert "noesis_jobs_submitted_total" in client.get("/api/v1/metrics").text


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Noesis PDF Cloner" in response.text
