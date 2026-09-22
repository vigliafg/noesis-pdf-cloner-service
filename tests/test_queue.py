"""Test della coda: priorità, posizione, rimozione e recovery."""

import threading
import time

from app.models import DocumentRecord, JobRecord, JobState
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


class _BlockingRunner:
    """Runner che si blocca finché non riceve l'annullamento (cancel in esecuzione)."""

    def __init__(self, storage):
        self.storage = storage
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def run(self, job, cancel_event):
        self.started.set()
        if cancel_event.wait(timeout=5):
            self.cancelled.set()
        self.storage.update_job(job.job_id, state=JobState.cancelled)


def test_cancel_queued_job_not_executed(settings):
    """Un job annullato prima dell'avvio non viene eseguito."""
    storage = Storage(settings)
    _seed(storage, JobState.queued, "q")
    runner = _RecordingRunner(storage)
    queue = JobQueue(storage, settings, runner)

    assert queue.cancel("q") is True
    assert storage.get_job("q").state is JobState.cancelled

    queue.start()
    time.sleep(0.3)
    queue.stop()

    assert "q" not in runner.seen
    storage.close()


def test_cancel_running_job_signals_event(settings):
    """Il cancel di un job in esecuzione attiva l'evento del worker."""
    storage = Storage(settings)
    _seed(storage, JobState.queued, "r")
    runner = _BlockingRunner(storage)
    queue = JobQueue(storage, settings, runner)
    queue.start()
    try:
        assert runner.started.wait(5)
        assert queue.cancel("r") is True
        assert runner.cancelled.wait(5)
    finally:
        queue.stop()
        storage.close()


def test_many_cancellations_leave_no_residual_state(settings):
    """Regressione: annullare molti job in coda non accumula stato in memoria."""
    storage = Storage(settings)
    queue = JobQueue(storage, settings, _RecordingRunner(storage))
    for index in range(10):
        job_id = f"q{index}"
        _seed(storage, JobState.queued, job_id)
        queue.cancel(job_id)

    assert queue._cancel_events == {}
    assert not hasattr(queue, "_cancelled")
    for index in range(10):
        assert storage.get_job(f"q{index}").state is JobState.cancelled
    storage.close()
