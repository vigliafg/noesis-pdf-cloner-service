"""Test del client del worker persistente (``engine_client``).

Worker fittizio che parla lo stesso protocollo JSON-lines: nessuna dipendenza
da ``pdf2zh_next``.
"""

from __future__ import annotations

import os
import sys
import threading

import pytest

from app.engine_client import EngineWorkerClient

_FAKE_WORKER = '''\
import json
import socket
import sys
import time
from pathlib import Path


def _arg(name):
    args = sys.argv[1:]
    return args[args.index(name) + 1]


ready = _arg("--ready-file")
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", 0))
server.listen(1)
Path(ready).write_text(str(server.getsockname()[1]))
conn, _ = server.accept()
buf = b""
while True:
    chunk = conn.recv(4096)
    if not chunk:
        break
    buf += chunk
    while b"\\n" in buf:
        line, buf = buf.split(b"\\n", 1)
        if not line.strip():
            continue
        req = json.loads(line)
        if req.get("cmd") == "shutdown":
            sys.exit(0)
        argv = req.get("argv") or []
        mode = argv[0] if argv else "ok"
        if mode == "slow":
            time.sleep(0.15)
        if mode == "sleep":
            time.sleep(60)
        conn.sendall((json.dumps({
            "id": req.get("id"), "rc": 0, "error": None, "log_tail": "log"
        }) + "\\n").encode())
'''


@pytest.fixture
def client(tmp_path):
    script = tmp_path / "fake_worker.py"
    script.write_text(_FAKE_WORKER, encoding="utf-8")
    worker = EngineWorkerClient(
        sys.executable,
        script,
        tmp_path / "wd",
        ready_timeout=20.0,
    )
    try:
        yield worker
    finally:
        worker.close()


def test_run_returns_completed_process(client):
    result = client.run(["ok"], dict(os.environ))
    assert result.returncode == 0
    assert result.stderr == "log"


def test_two_jobs_reuse_same_worker(client):
    client.run(["ok"], dict(os.environ))
    first = client._proc.pid
    client.run(["ok"], dict(os.environ))
    assert client._proc.pid == first


def test_concurrent_runs_do_not_steal_responses(client):
    """Il worker è single-threaded: più ``run()`` non devono rubarsi le risposte.

    Regressione: senza serializzazione due thread in ``recv`` sullo stesso
    socket potevano consumare la risposta dell'altro e scartarla (id diverso),
    lasciando il chiamante in attesa fino al ``page_timeout`` (900 s).
    """
    results: list = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def submit() -> None:
        barrier.wait()
        try:
            results.append(client.run(["slow"], dict(os.environ), timeout=20))
        except BaseException as exc:  # noqa: BLE001 - raccolto e asserto
            errors.append(exc)

    threads = [threading.Thread(target=submit) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(40)

    assert not errors, errors
    assert len(results) == 4
    assert all(result.returncode == 0 for result in results)


def test_cancel_stops_worker(client):
    cancel = threading.Event()
    timer = threading.Timer(0.3, cancel.set)
    timer.start()
    from app.engine_client import WorkerCancelled

    with pytest.raises(WorkerCancelled):
        client.run(["sleep"], dict(os.environ), cancel_event=cancel, timeout=20)
    timer.cancel()
