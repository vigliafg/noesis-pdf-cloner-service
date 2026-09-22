"""Streaming SSE del log di un job.

Il log è su file JSONL (durabile), quindi lo stream lo *tail*: funziona anche
se il client si ricollega o il server è ripartito. Supporta l'auth via cookie
(``EventSource`` non invia header personalizzati) e chiude il flusso quando il
job raggiunge uno stato terminale.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import Request

from .models import JobState
from .storage import Storage

_TERMINAL = {
    JobState.done,
    JobState.error,
    JobState.cancelled,
    JobState.interrupted,
}


def _read_new_lines(path, offset: int) -> tuple[list[str], int]:
    import os

    try:
        size = os.path.getsize(path)
    except OSError:
        return [], offset
    if size <= offset:
        return [], offset
    lines: list[str] = []
    with open(path, "r", encoding="utf-8") as handle:
        handle.seek(offset)
        for line in handle:
            line = line.strip()
            if line:
                lines.append(line)
        new_offset = handle.tell()
    return lines, new_offset


async def job_event_stream(
    storage: Storage, job_id: str, request: Request
) -> AsyncIterator[str]:
    """Generatore di eventi SSE per il job ``job_id``."""
    path = storage.job_log_path(job_id)
    offset = 0
    yield "retry: 2000\n\n"
    while True:
        if await request.is_disconnected():
            break
        lines, offset = await asyncio.to_thread(_read_new_lines, path, offset)
        for line in lines:
            yield f"data: {line}\n\n"
        job = storage.get_job(job_id)
        if job is None:
            break
        if job.state in _TERMINAL and not lines:
            break
        await asyncio.sleep(0.5)
    yield "event: end\ndata: " + json.dumps({"job_id": job_id}) + "\n\n"
