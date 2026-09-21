"""Fixture condivise: settings temporanee, contesto e client API."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.context import AppContext
from app.emailer import Emailer
from app.janitor import Janitor
from app.queue import JobQueue
from app.security import RateLimiter
from app.storage import Storage

from helpers import FakeRunner


@pytest.fixture
def settings(tmp_path) -> Settings:
    config = Settings(
        data_dir=tmp_path / "data",
        workers=1,
        page_concurrency=2,
        max_engine_procs=2,
        page_timeout=30,
        janitor_interval_seconds=3600,
        max_upload_mb=50,
    )
    config.ensure_dirs()
    return config


@pytest.fixture
def ctx(settings) -> AppContext:
    storage = Storage(settings)
    runner = FakeRunner(storage, settings)
    return AppContext(
        settings=settings,
        storage=storage,
        runner=runner,
        queue=JobQueue(storage, settings, runner),
        janitor=Janitor(storage, settings),
        rate_limiter=RateLimiter(settings.rate_limit_per_minute),
        emailer=Emailer(storage),
    )


@pytest.fixture
def client(settings, ctx):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(settings, context=ctx)
    with TestClient(app) as test_client:
        yield test_client
