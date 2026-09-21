"""Test della persistenza (SQLite + percorsi)."""

from datetime import timedelta

from app.models import DocumentRecord, JobRecord, JobState, RangeMode, utcnow
from app.storage import Storage


def _document(doc_id: str = "d1") -> DocumentRecord:
    return DocumentRecord(
        doc_id=doc_id,
        filename="a.pdf",
        sha256="deadbeef",
        page_count=3,
        path="/tmp/a.pdf",
        page_labels=["i", "1", "2"],
        owner_id="anonymous:x",
        size_bytes=42,
    )


def _job(job_id: str = "j1", doc_id: str = "d1") -> JobRecord:
    return JobRecord(
        job_id=job_id,
        doc_id=doc_id,
        pages=[0, 1],
        engine="bing",
        output_name="out",
        range_mode=RangeMode.single,
        pages_total=2,
        owner_id="anonymous:x",
    )


def test_document_roundtrip(settings):
    storage = Storage(settings)
    storage.create_document(_document())
    loaded = storage.get_document("d1")
    assert loaded is not None
    assert loaded.page_labels == ["i", "1", "2"]
    assert loaded.size_bytes == 42
    assert len(storage.list_documents()) == 1
    storage.delete_document("d1")
    assert storage.get_document("d1") is None
    storage.close()


def test_job_update_and_states(settings):
    storage = Storage(settings)
    storage.create_document(_document())
    storage.create_job(_job())
    storage.update_job(
        "j1", state=JobState.running, pages_done=1, range_mode=RangeMode.merged
    )
    job = storage.get_job("j1")
    assert job.state is JobState.running
    assert job.pages_done == 1
    assert job.range_mode is RangeMode.merged
    assert len(storage.jobs_by_state(JobState.running)) == 1
    assert storage.count_jobs_by_state() == {"running": 1}
    storage.close()


def test_usage_and_audit(settings):
    storage = Storage(settings)
    storage.add_usage(
        job_id="j1", doc_id="d1", actor_id="anonymous:x", engine="bing", pages=2
    )
    assert storage.usage_totals()["pages"] == 2
    assert storage.usage_totals("anonymous:x")["pages"] == 2
    storage.add_audit(actor_id="anonymous:x", action="job.create", resource="j1")
    storage.add_email("a@b.c", "ciao", "corpo")
    storage.close()


def test_claim_next_job_respects_priority(settings):
    storage = Storage(settings)
    storage.create_document(_document())
    storage.create_job(JobRecord(job_id="low", doc_id="d1", pages=[0], priority=0))
    storage.create_job(JobRecord(job_id="high", doc_id="d1", pages=[0], priority=5))
    first = storage.claim_next_job()
    assert first is not None and first.job_id == "high"
    assert first.state is JobState.running
    assert storage.claim_next_job().job_id == "low"
    assert storage.claim_next_job() is None
    storage.close()


def test_pending_count_and_queue_position(settings):
    storage = Storage(settings)
    storage.create_document(_document())
    storage.create_job(JobRecord(job_id="a", doc_id="d1", pages=[0]))
    storage.create_job(JobRecord(job_id="b", doc_id="d1", pages=[0]))
    assert storage.pending_count() == 2
    assert storage.queue_position("a") == 1
    assert storage.queue_position("b") == 2
    storage.close()


def test_request_cancel_marks_queued(settings):
    storage = Storage(settings)
    storage.create_document(_document())
    storage.create_job(JobRecord(job_id="x", doc_id="d1", pages=[0]))
    assert storage.is_cancel_requested("x") is False
    storage.request_cancel("x")
    assert storage.is_cancel_requested("x") is True
    assert storage.get_job("x").state is JobState.cancelled
    storage.clear_cancel("x")
    assert storage.is_cancel_requested("x") is False
    storage.close()


def test_retention_queries(settings):
    storage = Storage(settings)
    document = _document()
    document.created = utcnow() - timedelta(hours=100)
    storage.create_document(document)
    job = _job()
    job.finished = utcnow() - timedelta(hours=100)
    storage.create_job(job)
    storage.update_job("j1", finished=utcnow() - timedelta(hours=100))
    assert len(storage.old_documents(24)) == 1
    assert len(storage.old_jobs(24)) == 1
    storage.close()
