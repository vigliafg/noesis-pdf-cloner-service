"""Test dello streaming SSE (chiusura anche quando il job non esiste)."""

from __future__ import annotations

import asyncio

from app.sse import job_event_stream
from app.storage import Storage


class _FakeRequest:
    async def is_disconnected(self) -> bool:
        return False


def test_stream_ends_when_job_missing(settings):
    """Regressione: se il job non esiste lo stream termina invece di restare appeso."""
    storage = Storage(settings)

    async def collect() -> list[str]:
        events: list[str] = []
        async for event in job_event_stream(storage, "missing", _FakeRequest()):
            events.append(event)
        return events

    events = asyncio.run(asyncio.wait_for(collect(), timeout=5))
    assert any("event: end" in event for event in events)
    storage.close()
