"""Test della coda: priorità, posizione, rimozione e recovery."""

import time
from datetime import timedelta

from app.models import DocumentRecord, JobRecord, JobState, utcnow
from app.queue import InMemoryQueueBackend, JobQueue
from app.storage import Storage


def test_backend_priority_and_position():
    backend = InMemoryQueueBackend()
    backend.put("low", priority=0)
    backend.put("high", priority=5)
    backend.put("mid", priority=1)
    assert backend.qsize() == 3
    assert backend.position("high") == 1
    assert backend.get(timeout=0) == "high"
    assert backend.get(timeout=0) == "mid"
    assert backend.get(timeout=0) == "low"
    assert backend.get(timeout=0.01) is None


def test_backend_remove():
    backend = InMemoryQueueBackend()
    backend.put("a")
    backend.put("b")
    assert backend.remove("a") is True
    assert backend.position("a") is None
    assert backend.get(timeout=0) == "b"


class _RecordingRunner:
    def __init__(self, storage):
        self.storage = storage
        self.seen: list[str] = []

    def run(self, job, cancel_event):
        self.seen.append(job.job_id)
        self.storage.update_job(job.job_id, state=JobState.done)


def _seed(storage, state: JobState, job_id: str, doc_id: str = "d"):
    storage.create_job(
        JobRecord(job_id=job_id, doc_id=doc_id, pages=[0], state=state)
    )


def test_scheduled_jobs_promotion(settings):
    storage = Storage(settings)
    storage.create_document(
        DocumentRecord(
            doc_id="d", filename="a.pdf", sha256="x", page_count=1, path="/tmp/a.pdf"
        )
    )
    storage.create_job(
        JobRecord(
            job_id="past", doc_id="d", pages=[0], state=JobState.scheduled,
            scheduled_at=utcnow() - timedelta(minutes=1),
        )
    )
    storage.create_job(
        JobRecord(
            job_id="future", doc_id="d", pages=[0], state=JobState.scheduled,
            scheduled_at=utcnow() + timedelta(hours=1),
        )
    )
    runner = _RecordingRunner(storage)
    queue = JobQueue(storage, settings, runner)
    queue.start()
    deadline = time.time() + 5
    while time.time() < deadline and "past" not in runner.seen:
        time.sleep(0.05)
    queue.stop()

    assert "past" in runner.seen
    assert storage.get_job("past").state is JobState.done
    assert storage.get_job("future").state is JobState.scheduled
    storage.close()


def test_recovery_and_processing(settings):
    storage = Storage(settings)
    storage.create_document(
        DocumentRecord(
            doc_id="d", filename="a.pdf", sha256="x", page_count=1, path="/tmp/a.pdf"
        )
    )
    _seed(storage, JobState.queued, "queued-1")
    _seed(storage, JobState.running, "running-1")

    runner = _RecordingRunner(storage)
    queue = JobQueue(storage, settings, runner)
    queue.start()
    deadline = time.time() + 5
    while time.time() < deadline and len(runner.seen) < 1:
        time.sleep(0.05)
    queue.stop()

    assert "queued-1" in runner.seen
    assert storage.get_job("running-1").state is JobState.interrupted
    assert storage.get_job("queued-1").state is JobState.done
    storage.close()
