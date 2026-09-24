"""Test della diagnostica di preflight del servizio (app/diagnostics.py).

Situazioni simulate: server HTTP locale che imita OpenRouter, binari finti per
``uv`` e ``pdf2zh_next``. Nessuna rete esterna, nessun motore reale.
"""

from __future__ import annotations

import json
import stat
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app import diagnostics as diag
from app.config import Settings


class _FakeOpenRouter(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _token(self) -> str:
        return self.headers.get("Authorization", "").replace("Bearer", "").strip()

    def _send(self, status: int, payload: dict | None = None):
        body = json.dumps(payload or {}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path != "/key":
            return self._send(404, {"error": "not found"})
        token = self._token()
        if token == "good":
            return self._send(200, {"data": {
                "limit": 10, "usage": 1.2, "limit_remaining": 8.8,
                "is_free_tier": False,
            }})
        if token == "low":
            return self._send(200, {"data": {"limit_remaining": 0}})
        if token == "slow":
            time.sleep(2.0)
            return self._send(200, {"data": {}})
        return self._send(401, {"error": {"message": "No auth credentials"}})

    def do_POST(self):  # noqa: N802
        if self.path != "/chat/completions":
            return self._send(404, {"error": "not found"})
        if self._token() != "good":
            return self._send(401, {"error": {"message": "Invalid API key"}})
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            model = json.loads(self.rfile.read(length) or b"{}").get("model", "")
        except Exception:
            model = ""
        if model == "model/ok":
            return self._send(200, {"choices": [{"message": {"content": "pong"}}]})
        if model == "model/paid":
            return self._send(402, {"error": {"message": "Insufficient credits"}})
        if model == "model/busy":
            return self._send(429, {"error": {"message": "Rate limit exceeded"}})
        if model == "model/slow":
            time.sleep(2.0)
            return self._send(200, {"choices": [{"message": {"content": "pong"}}]})
        return self._send(404, {"error": {"message": "model not found"}})


@pytest.fixture(scope="module")
def openrouter():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenRouter)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _exec(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _settings(tmp_path, **over) -> Settings:
    base = dict(data_dir=tmp_path / "data", workers=1, janitor_interval_seconds=3600)
    base.update(over)
    settings = Settings(**base)
    settings.ensure_dirs()
    return settings


# ── motore / ambiente ───────────────────────────────────────────────────────


def test_engine_missing(tmp_path):
    r = diag.check_engine_bin(None)
    assert r.status == diag.Status.FAIL
    assert r.code == "engine_missing" and r.fix == "install_engine"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="script /bin/sh non eseguibili su Windows")
def test_engine_present_and_running(tmp_path):
    fake = _exec(tmp_path / "pdf2zh_next", "#!/bin/sh\necho usage\n")
    assert diag.check_engine_bin(fake).status == diag.Status.OK
    assert diag.check_engine_run(fake).status == diag.Status.OK


def test_engine_broken(tmp_path):
    fake = _exec(tmp_path / "pdf2zh_next", "#!/bin/sh\nexit 3\n")
    r = diag.check_engine_run(fake)
    assert r.status == diag.Status.WARN and r.code == "engine_not_runnable"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="script /bin/sh non eseguibili su Windows")
def test_uv_ok_and_missing(tmp_path):
    fake = _exec(tmp_path / "uv", "#!/bin/sh\necho 'uv 0.12.17'\n")
    assert diag.check_uv(fake).status == diag.Status.OK
    missing = diag.check_uv(None)
    assert missing.status == diag.Status.WARN and missing.code == "uv_missing"


def test_data_dir_and_disk(tmp_path):
    assert diag.check_data_dir(tmp_path / "appdata").status == diag.Status.OK
    r = diag.check_disk(tmp_path, required_bytes=10**18)
    assert r.status == diag.Status.WARN and r.code == "disk_low"


# ── rete / chiave / modello ─────────────────────────────────────────────────


def test_reachable(openrouter):
    assert diag.check_openrouter_reachable(openrouter).status == diag.Status.OK


def test_unreachable():
    r = diag.check_openrouter_reachable("http://127.0.0.1:1")
    assert r.status == diag.Status.FAIL and r.code == "network"


def test_key_present_masked():
    r = diag.check_key_present("sk-or-abcdefgh1234", "env")
    assert r.status == diag.Status.OK and r.code == "key_env"
    assert "abcdefgh1234" not in r.data["masked"]
    assert diag.check_key_present("", "none").code == "key_missing"


def test_key_valid(openrouter):
    assert diag.check_key_valid("good", openrouter).status == diag.Status.OK
    bad = diag.check_key_valid("bad", openrouter)
    assert bad.status == diag.Status.FAIL and bad.code == "invalid_key"
    assert diag.check_key_valid("", openrouter).status == diag.Status.SKIP
    net = diag.check_key_valid("good", "http://127.0.0.1:1")
    assert net.status == diag.Status.WARN and net.code == "network"


def test_key_credits(openrouter):
    assert diag.check_key_credits("good", openrouter).data["limit_remaining"] == 8.8
    low = diag.check_key_credits("low", openrouter)
    assert low.status == diag.Status.WARN and low.code == "credits_low"


def test_model_probe(openrouter):
    assert diag.check_llm_model("good", "model/ok", openrouter).status == diag.Status.OK
    bad = diag.check_llm_model("bad", "model/ok", openrouter)
    assert bad.code == "invalid_key"
    paid = diag.check_llm_model("good", "model/paid", openrouter)
    assert paid.code == "no_credits" and paid.fix == "add_credits"
    busy = diag.check_llm_model("good", "model/busy", openrouter)
    assert busy.status == diag.Status.WARN and busy.code == "rate_limited"
    missing = diag.check_llm_model("good", "model/unknown", openrouter)
    assert missing.code == "model_not_found"
    slow = diag.check_llm_model("good", "model/slow", openrouter, timeout=0.5)
    assert slow.status == diag.Status.WARN and slow.code == "network"


def test_free_chain():
    assert diag.check_free_chain(translator=lambda t: "ciao").status == diag.Status.OK
    r = diag.check_free_chain(translator=lambda t: None)
    assert r.status == diag.Status.WARN and r.code == "free_unavailable"


# ── build_context + runner ──────────────────────────────────────────────────


def test_build_context_reads_settings(tmp_path, monkeypatch):
    settings = _settings(tmp_path, openrouter_api_key="sk-or-test-key", llm_model="m/x")
    monkeypatch.setenv("UV", "")
    ctx = diag.build_context(settings)
    assert ctx.key == "sk-or-test-key" and ctx.key_source == "env"
    assert ctx.model == "m/x"
    assert ctx.want_llm_checks is True


def test_build_context_without_key_skips_llm(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = _settings(tmp_path)
    ctx = diag.build_context(settings)
    assert ctx.key_source == "none"
    assert not ctx.key
    assert ctx.want_llm_checks is False


@pytest.mark.skipif(sys.platform.startswith("win"), reason="script /bin/sh non eseguibili su Windows")
def test_run_all_and_health_status(tmp_path, openrouter):
    engine = _exec(tmp_path / "pdf2zh_next", "#!/bin/sh\necho usage\n")
    ctx = diag.DiagnosticsContext(
        data_dir=tmp_path / "data",
        uv_bin=_exec(tmp_path / "uv", "#!/bin/sh\necho uv\n"),
        engine_bin=engine,
        key="good",
        key_source="env",
        base_url=openrouter,
        model="model/ok",
        free_translator=lambda t: "ciao",
    )
    results = diag.run_all(ctx)
    assert diag.overall_status(results) == diag.Status.OK
    assert diag.health_status(results) == "ok"

    bad = diag.run_all(diag.DiagnosticsContext(
        data_dir=tmp_path / "data", engine_bin=engine, key="bad",
        key_source="env", base_url=openrouter, model="model/ok",
        free_translator=lambda t: "ciao",
    ))
    assert diag.health_status(bad) == "fail"

    broken = diag.run_all(diag.DiagnosticsContext(
        data_dir=tmp_path / "data", engine_bin=None, want_llm_checks=False,
        want_free_checks=False,
    ))
    assert diag.health_status(broken) == "fail"
