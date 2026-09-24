"""Test della console di installazione/gestione (``tools/noesis.py``).

Solo logica pura: nessuna rete, nessun servizio, nessuna modifica al sistema.
Le funzioni che eseguono comandi vengono sostituite con finti runner.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pytest
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("noesis_console", ROOT / "tools" / "noesis.py")
noesis = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["noesis_console"] = noesis  # necessario per @dataclass
_spec.loader.exec_module(noesis)


# ── config ──────────────────────────────────────────────────────────────────


def test_parse_and_render_env_roundtrip():
    text = """
# commento
HOST=0.0.0.0
PORT=18080
OPENROUTER_API_KEY="sk-abc"
VIDEO=
"""
    values = noesis.parse_env_file(text)
    assert values["HOST"] == "0.0.0.0"
    assert values["PORT"] == "18080"
    assert values["OPENROUTER_API_KEY"] == "sk-abc"
    assert values["VIDEO"] == ""

    rendered = noesis.render_config({"HOST": "127.0.0.1", "PORT": "1234"})
    assert "HOST=127.0.0.1" in rendered
    assert "OPENROUTER_API_KEY=" in rendered  # segnaposto presente


def test_save_and_load_config_merge(tmp_path):
    noesis.save_config(tmp_path, {"HOST": "0.0.0.0", "PORT": "18080"})
    noesis.save_config(tmp_path, {"PORT": "9000"})  # merge, non sovrascrive HOST
    loaded = noesis.load_config(tmp_path)
    assert loaded["HOST"] == "0.0.0.0"
    assert loaded["PORT"] == "9000"


def test_load_config_defaults_when_missing(tmp_path):
    loaded = noesis.load_config(tmp_path / "nope")
    assert loaded["PORT"] == str(noesis.DEFAULT_PORT)
    assert loaded["ROLE"] == "all"


def test_build_env_shell_wins_over_config(tmp_path):
    noesis.save_config(tmp_path, {"HOST": "0.0.0.0", "PORT": "18080"})
    env = noesis.build_env(tmp_path, base={"HOST": "10.0.0.1"})
    assert env["HOST"] == "10.0.0.1"       # la shell vince
    assert env["PORT"] == "18080"          # il resto dalla config
    assert env["DATA_DIR"] == str(tmp_path)


def test_render_config_omits_placeholder_when_key_present():
    text = noesis.render_config({"HOST": "0.0.0.0", "OPENROUTER_API_KEY": "sk-or-x"})
    assert "OPENROUTER_API_KEY=sk-or-x" in text
    assert "# OPENROUTER_API_KEY=" not in text  # niente riga duplicata/commentata


@pytest.mark.skipif(sys.platform.startswith("win"), reason="permessi POSIX")
def test_save_config_sets_private_permissions(tmp_path):
    path = noesis.save_config(tmp_path, {"HOST": "0.0.0.0"})
    assert (path.stat().st_mode & 0o777) == 0o600


def test_save_config_skips_chmod_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(noesis, "is_windows", lambda: True)
    called: list[tuple] = []
    monkeypatch.setattr(noesis.os, "chmod", lambda *a: called.append(a))
    noesis.save_config(tmp_path, {"HOST": "0.0.0.0"})
    assert called == []


# ── chiave OpenRouter ───────────────────────────────────────────────────────


def test_ensure_openrouter_key_skips_when_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")
    noesis.ensure_openrouter_key(tmp_path, noesis.UI(quiet=True))
    assert not noesis.config_path(tmp_path).exists()


def test_ensure_openrouter_key_skips_when_in_config(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    noesis.save_config(tmp_path, {"OPENROUTER_API_KEY": "sk-or-cfg"})
    noesis.ensure_openrouter_key(tmp_path, noesis.UI(quiet=True))
    assert noesis.load_config(tmp_path)["OPENROUTER_API_KEY"] == "sk-or-cfg"


def test_ensure_openrouter_key_writes_when_prompted(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(noesis.UI, "is_interactive", lambda self: True)
    monkeypatch.setattr(noesis.UI, "prompt_secret", lambda self, q: "sk-or-typed")
    noesis.ensure_openrouter_key(tmp_path, noesis.UI(quiet=True))
    assert noesis.load_config(tmp_path)["OPENROUTER_API_KEY"] == "sk-or-typed"


def test_ensure_openrouter_key_empty_input_does_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(noesis.UI, "is_interactive", lambda self: True)
    monkeypatch.setattr(noesis.UI, "prompt_secret", lambda self, q: "")
    noesis.ensure_openrouter_key(tmp_path, noesis.UI(quiet=True))
    assert not noesis.config_path(tmp_path).exists()


def test_ensure_openrouter_key_non_interactive_never_prompts(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(noesis.UI, "is_interactive", lambda self: False)
    called: list[str] = []
    monkeypatch.setattr(noesis.UI, "prompt_secret", lambda self, q: called.append(q) or "x")
    noesis.ensure_openrouter_key(tmp_path, noesis.UI(quiet=True))
    assert called == []
    assert not noesis.config_path(tmp_path).exists()


# ── verifica chiave/modello OpenRouter ──────────────────────────────────────


def _fake_venv(tmp_path):
    venv = tmp_path / "venv"
    py = noesis.venv_python_in(venv)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("", encoding="utf-8")
    return venv


def test_verify_openrouter_key_without_key_does_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    called: list[int] = []
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: called.append(1))
    assert noesis.verify_openrouter_key(tmp_path, noesis.UI(quiet=True)) is False
    assert called == []


def test_verify_openrouter_key_requires_venv(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    monkeypatch.setattr(noesis, "service_venv", lambda: tmp_path / "missing")
    called: list[int] = []
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: called.append(1))
    assert noesis.verify_openrouter_key(tmp_path, noesis.UI(quiet=True)) is False
    assert called == []


def test_verify_openrouter_key_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    monkeypatch.setattr(noesis, "service_venv", lambda: _fake_venv(tmp_path))
    payload = json.dumps([
        {"id": "key.valid", "status": "ok", "code": "key_valid", "message": "", "data": {}},
        {"id": "key.credits", "status": "ok", "code": "ok", "message": "",
         "data": {"limit_remaining": 5.0}},
        {"id": "llm.model", "status": "ok", "code": "model_ok", "message": "HTTP 200", "data": {}},
    ])
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(0, payload))
    ui = noesis.UI(quiet=True)
    assert noesis.verify_openrouter_key(tmp_path, ui) is True
    messages = " | ".join(e["message"] for e in ui.events)
    assert "modello LLM: ok" in messages
    assert "residuo 5.0" in messages


def test_verify_openrouter_key_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    monkeypatch.setattr(noesis, "service_venv", lambda: _fake_venv(tmp_path))
    payload = json.dumps([
        {"id": "key.valid", "status": "fail", "code": "invalid_key",
         "message": "HTTP 401", "data": {}},
    ])
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(0, payload))
    ui = noesis.UI(quiet=True)
    assert noesis.verify_openrouter_key(tmp_path, ui) is False
    assert any(e["level"] == "warn" and "invalid_key" in e["message"] for e in ui.events)


def test_verify_openrouter_key_garbage_output(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    monkeypatch.setattr(noesis, "service_venv", lambda: _fake_venv(tmp_path))
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(0, "Traceback (most recent call last):"))
    assert noesis.verify_openrouter_key(tmp_path, noesis.UI(quiet=True)) is False


# ── report di salute + link ─────────────────────────────────────────────────


def test_ui_link_plain_without_color():
    assert noesis.UI(color=False).link("http://x:1/") == "http://x:1/"


def test_ui_link_osc8_with_color():
    out = noesis.UI(color=True).link("http://x:1/")
    assert out == "\033]8;;http://x:1/\033\\http://x:1/\033]8;;\033\\"


def test_print_health_report_renders_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(noesis, "DRY_RUN", False)
    monkeypatch.setattr(noesis, "service_venv", lambda: _fake_venv(tmp_path))
    payload = json.dumps({
        "status": "ok",
        "checks": [
            {"id": "env.data", "status": "ok", "code": "ok", "message": "", "fix": "", "data": {}},
            {"id": "engine.bin", "status": "ok", "code": "ok", "message": "", "fix": "",
             "data": {"path": "/r/.venv2/bin/pdf2zh_next"}},
            {"id": "key.present", "status": "warn", "code": "key_missing", "message": "",
             "fix": "enter_key", "data": {}},
        ],
    })
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(0, payload))
    ui = noesis.UI(quiet=True)
    noesis.print_health_report(tmp_path, ui)
    messages = " | ".join(e["message"] for e in ui.events)
    assert "env.data" in messages
    assert "pdf2zh_next" in messages
    assert "esito: ok" in messages
    assert any(e["level"] == "warn" and "key.present" in e["message"] for e in ui.events)


def test_print_health_report_skips_without_venv(tmp_path, monkeypatch):
    monkeypatch.setattr(noesis, "DRY_RUN", False)
    monkeypatch.setattr(noesis, "service_venv", lambda: tmp_path / "missing")
    called: list[int] = []
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: called.append(1))
    noesis.print_health_report(tmp_path, noesis.UI(quiet=True))
    assert called == []


def test_print_health_report_dry_run_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(noesis, "DRY_RUN", True)
    called: list[int] = []
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: called.append(1))
    noesis.print_health_report(tmp_path, noesis.UI(quiet=True))
    assert called == []


def test_print_summary_shows_local_and_lan_links(tmp_path, monkeypatch):
    monkeypatch.setattr(noesis, "DRY_RUN", False)
    monkeypatch.setattr(noesis, "print_health_report", lambda data_dir, ui: None)
    monkeypatch.setattr(noesis, "wait_for_health", lambda host, port, **k: True)
    monkeypatch.setattr(noesis, "local_ip", lambda: "10.0.0.5")
    ui = noesis.UI(quiet=True, color=False)
    noesis._print_summary(tmp_path, ui, host="0.0.0.0", port=18080, started=True)
    messages = " | ".join(e["message"] for e in ui.events)
    assert "locale: http://127.0.0.1:18080" in messages
    assert "LAN: http://10.0.0.5:18080" in messages


def test_print_summary_report_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(noesis, "DRY_RUN", False)
    monkeypatch.setattr(noesis, "wait_for_health", lambda *a, **k: True)
    monkeypatch.setattr(noesis, "local_ip", lambda: None)
    calls: list[int] = []
    monkeypatch.setattr(noesis, "print_health_report", lambda data_dir, ui: calls.append(1))
    noesis._print_summary(tmp_path, noesis.UI(quiet=True), host="127.0.0.1", port=18080, report=False)
    assert calls == []
    noesis._print_summary(tmp_path, noesis.UI(quiet=True), host="127.0.0.1", port=18080, report=True)
    assert calls == [1]


# ── piattaforma / percorsi ──────────────────────────────────────────────────


def test_default_data_dir_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(noesis, "is_windows", lambda: False)
    monkeypatch.setattr(noesis, "is_macos", lambda: False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert noesis.default_data_dir() == tmp_path / "xdg" / noesis.APP_NAME


def test_default_data_dir_macos(monkeypatch):
    monkeypatch.setattr(noesis, "is_windows", lambda: False)
    monkeypatch.setattr(noesis, "is_macos", lambda: True)
    monkeypatch.setattr(noesis.Path, "home", classmethod(lambda cls: Path("/Users/tester")))
    assert noesis.default_data_dir() == Path("/Users/tester/Library/Application Support") / noesis.APP_NAME


def test_default_data_dir_windows(monkeypatch):
    monkeypatch.setattr(noesis, "is_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", "/win/appdata")
    assert noesis.default_data_dir() == Path("/win/appdata") / noesis.APP_NAME


def test_invoking_user_prefers_sudo(monkeypatch):
    monkeypatch.setenv("USER", "alice")
    monkeypatch.setenv("LOGNAME", "alice")
    monkeypatch.delenv("SUDO_USER", raising=False)
    assert noesis.invoking_user() == "alice"
    monkeypatch.setenv("SUDO_USER", "bob")
    assert noesis.invoking_user() == "bob"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="pwd assente su Windows")
def test_invoking_home_resolves_sudo_user(monkeypatch):
    import pwd
    import types

    monkeypatch.setenv("SUDO_USER", "alice")
    monkeypatch.setattr(pwd, "getpwnam", lambda name: types.SimpleNamespace(pw_dir="/home/alice"))
    assert noesis.invoking_home() == Path("/home/alice")


def test_invoking_home_unknown_sudo_user_falls_back(monkeypatch):
    monkeypatch.setenv("SUDO_USER", "no-such-user-xyz")
    monkeypatch.setattr(noesis.Path, "home", classmethod(lambda cls: Path("/home/fallback")))
    assert noesis.invoking_home() == Path("/home/fallback")


def test_invoking_home_ignores_sudo_root(monkeypatch):
    monkeypatch.setenv("SUDO_USER", "root")
    monkeypatch.setattr(noesis.Path, "home", classmethod(lambda cls: Path("/home/fallback")))
    assert noesis.invoking_home() == Path("/home/fallback")


@pytest.mark.skipif(sys.platform.startswith("win"), reason="pwd assente su Windows")
def test_default_data_dir_uses_sudo_home(monkeypatch):
    import pwd
    import types

    monkeypatch.setattr(noesis, "is_windows", lambda: False)
    monkeypatch.setattr(noesis, "is_macos", lambda: False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("SUDO_USER", "alice")
    monkeypatch.setattr(pwd, "getpwnam", lambda name: types.SimpleNamespace(pw_dir="/home/alice"))
    assert noesis.default_data_dir() == Path("/home/alice/.local/share") / noesis.APP_NAME


def test_platform_tag_shape():
    tag = noesis.platform_tag()
    assert "-" in tag
    assert tag == tag.lower()


def test_venv_python_paths(monkeypatch):
    monkeypatch.setattr(noesis, "is_windows", lambda: False)
    assert noesis.venv_python_in(Path("/r/.venv")) == Path("/r/.venv/bin/python")
    monkeypatch.setattr(noesis, "is_windows", lambda: True)
    assert noesis.venv_python_in(Path(r"C:\r\.venv")) == Path(r"C:\r\.venv/Scripts/python.exe")


def test_is_wsl_from_env(monkeypatch):
    monkeypatch.setattr(noesis, "is_linux", lambda: True)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert noesis.is_wsl() is True
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.setattr(noesis, "is_linux", lambda: False)
    assert noesis.is_wsl() is False


# ── rete ────────────────────────────────────────────────────────────────────


def test_server_urls_binds_all_interfaces(monkeypatch):
    monkeypatch.setattr(noesis, "local_ip", lambda: "192.168.1.50")
    urls = noesis.server_urls("0.0.0.0", 18080)
    assert "http://127.0.0.1:18080" in urls
    assert "http://192.168.1.50:18080" in urls


def test_server_urls_localhost_only():
    urls = noesis.server_urls("127.0.0.1", 18080)
    assert urls == ["http://127.0.0.1:18080"]


def test_port_listening_detects_and_releases():
    import socket as _socket

    server = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert noesis.port_listening("127.0.0.1", port) is True
    finally:
        server.close()
    assert noesis.port_listening("127.0.0.1", port) is False


def test_warn_if_port_busy_warns_for_foreign_process(monkeypatch):
    monkeypatch.setattr(noesis, "port_listening", lambda *a, **k: True)
    monkeypatch.setattr(noesis, "health_check", lambda *a, **k: False)
    ui = noesis.UI(quiet=True)
    assert noesis.warn_if_port_busy("0.0.0.0", 18080, ui) is True
    assert any(e["level"] == "warn" and "già in ascolto" in e["message"] for e in ui.events)


def test_warn_if_port_busy_ignores_our_service(monkeypatch):
    monkeypatch.setattr(noesis, "port_listening", lambda *a, **k: True)
    monkeypatch.setattr(noesis, "health_check", lambda *a, **k: True)
    assert noesis.warn_if_port_busy("0.0.0.0", 18080, noesis.UI(quiet=True)) is False


def test_warn_if_port_busy_free_port(monkeypatch):
    monkeypatch.setattr(noesis, "port_listening", lambda *a, **k: False)
    assert noesis.warn_if_port_busy("0.0.0.0", 18080, noesis.UI(quiet=True)) is False


def test_wait_for_health_returns_when_ready(monkeypatch):
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return calls["n"] >= 2

    monkeypatch.setattr(noesis, "health_check", fake)
    monkeypatch.setattr(noesis.time, "sleep", lambda _seconds: None)
    assert noesis.wait_for_health("127.0.0.1", 18080, timeout=5.0, interval=0.0) is True
    assert calls["n"] == 2


def test_wait_for_health_times_out(monkeypatch):
    monkeypatch.setattr(noesis, "health_check", lambda *a, **k: False)
    assert noesis.wait_for_health("127.0.0.1", 18080, timeout=0.0) is False


# ── risoluzione host/porta ──────────────────────────────────────────────────


def test_resolve_host_port_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    noesis.save_config(tmp_path, {"HOST": "10.1.1.1", "PORT": "7777"})
    args = argparse.Namespace(host=None, port=None)
    assert noesis.resolve_host_port(args, tmp_path) == ("10.1.1.1", 7777)
    args = argparse.Namespace(host="5.5.5.5", port=42)
    assert noesis.resolve_host_port(args, tmp_path) == ("5.5.5.5", 42)


# ── PID ─────────────────────────────────────────────────────────────────────


def test_pid_roundtrip(tmp_path):
    assert noesis.read_pid(tmp_path) is None
    noesis.write_pid(tmp_path, 4321)
    assert noesis.read_pid(tmp_path) == 4321
    noesis.remove_pid(tmp_path)
    assert noesis.read_pid(tmp_path) is None


def test_read_pid_invalid(tmp_path):
    noesis.pid_path(tmp_path).write_text("not-a-number")
    assert noesis.read_pid(tmp_path) is None


# ── status ──────────────────────────────────────────────────────────────────


def _status_args(tmp_path):
    return noesis.build_parser().parse_args(["status", "--data-dir", str(tmp_path)])


class _FakeController:
    def __init__(self, kind: str, status: str):
        self._kind = kind
        self._status = status

    def kind(self) -> str:
        return self._kind

    def status(self) -> str:
        return self._status


def _patch_service(monkeypatch, kind: str, status: str) -> None:
    monkeypatch.setattr(noesis, "ServiceController", lambda *a, **k: _FakeController(kind, status))


def test_status_ok_when_service_active(tmp_path, monkeypatch):
    # Servizio systemd attivo, nessun PID file: deve risultare in funzione (exit 0).
    _patch_service(monkeypatch, "systemd-user", "active")
    monkeypatch.setattr(noesis, "health_check", lambda *a, **k: True)
    assert noesis.cmd_status(_status_args(tmp_path), _ui()) == 0


def test_status_ok_when_only_health_responds(tmp_path, monkeypatch):
    _patch_service(monkeypatch, "none", "none")
    monkeypatch.setattr(noesis, "health_check", lambda *a, **k: True)
    assert noesis.cmd_status(_status_args(tmp_path), _ui()) == 0


def test_status_ok_with_background_pid(tmp_path, monkeypatch):
    noesis.write_pid(tmp_path, os.getpid())
    _patch_service(monkeypatch, "none", "none")
    monkeypatch.setattr(noesis, "health_check", lambda *a, **k: True)
    assert noesis.cmd_status(_status_args(tmp_path), _ui()) == 0


def test_status_fails_when_nothing_running(tmp_path, monkeypatch):
    _patch_service(monkeypatch, "none", "none")
    monkeypatch.setattr(noesis, "health_check", lambda *a, **k: False)
    assert noesis.cmd_status(_status_args(tmp_path), _ui()) == 1


# ── servizio: rendering ─────────────────────────────────────────────────────


def _spec(tmp_path: Path) -> noesis.ServiceSpec:
    return noesis.ServiceSpec(
        repo_root=Path("/opt/noesis"),
        venv_python=Path("/opt/noesis/.venv/bin/python"),
        host="0.0.0.0",
        port=18080,
        env_file=tmp_path / "noesis.env",
        data_dir=tmp_path,
        role="all",
        user="tester",
    )


def test_systemd_unit_user(tmp_path):
    spec = _spec(tmp_path)
    text = noesis.systemd_unit_text(spec, system=False)
    assert f"ExecStart={spec.venv_python} -m uvicorn app.main:app" in text
    assert "--host 0.0.0.0 --port 18080" in text
    assert "WantedBy=default.target" in text
    assert "EnvironmentFile=" in text
    assert "User=" not in text


def test_systemd_unit_system(tmp_path):
    text = noesis.systemd_unit_text(_spec(tmp_path), system=True)
    assert "WantedBy=multi-user.target" in text
    assert "User=tester" in text


def _schtasks_create(tmp_path, monkeypatch, *, system: bool) -> list[str]:
    spec = _spec(tmp_path)
    spec.data_dir = tmp_path
    controller = noesis.ServiceController(tmp_path, noesis.UI(quiet=True), system=system, spec=spec)
    monkeypatch.setattr(controller, "kind", lambda: "schtasks")
    monkeypatch.setattr(controller, "windows_runner_path", lambda: tmp_path / "run.cmd")
    monkeypatch.setattr(controller, "_env", lambda: {})
    monkeypatch.setattr(noesis, "DRY_RUN", False)
    calls: list[list[str]] = []
    monkeypatch.setattr(controller, "_run", lambda cmd, **k: calls.append(list(cmd)))
    controller.install()
    return next(c for c in calls if c[0] == "schtasks" and "/Create" in c)


def test_schtasks_user_mode_onlogon(tmp_path, monkeypatch):
    create = _schtasks_create(tmp_path, monkeypatch, system=False)
    assert "ONLOGON" in create and "LIMITED" in create


def test_schtasks_system_mode_onstart(tmp_path, monkeypatch):
    create = _schtasks_create(tmp_path, monkeypatch, system=True)
    assert "ONSTART" in create and "SYSTEM" in create


def test_systemd_unit_includes_uv_when_known(tmp_path):
    spec = _spec(tmp_path)
    spec.uv_bin = "/home/tester/.local/bin/uv"
    expected = "Environment=UV=/home/tester/.local/bin/uv"
    assert expected in noesis.systemd_unit_text(spec, system=False)
    assert expected in noesis.systemd_unit_text(spec, system=True)


def test_systemd_unit_omits_uv_when_unknown(tmp_path):
    assert "Environment=UV=" not in noesis.systemd_unit_text(_spec(tmp_path), system=False)


def test_launchd_plist(tmp_path):
    text = noesis.launchd_plist_text(_spec(tmp_path), {"HOST": "0.0.0.0"})
    assert "<key>Label</key>" in text
    assert noesis.SERVICE_LABEL in text
    assert "<key>ProgramArguments</key>" in text
    assert "<key>RunAtLoad</key>" in text
    assert "<key>HOST</key>" in text


def test_windows_runner(tmp_path):
    text = noesis.windows_runner_text(_spec(tmp_path), {"HOST": "0.0.0.0", "PORT": "18080"})
    assert "set HOST=0.0.0.0" in text
    assert "uvicorn" in text
    # Redirige l'output su file, così `noesis logs` funziona anche su Windows.
    assert '>> "' in text and "noesis.out" in text


def test_service_spec_uses_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ROLE", "api")
    spec = noesis._service_spec(tmp_path, host="0.0.0.0", port=18080)
    assert spec.role == "api"
    assert spec.env_file == tmp_path / "noesis.env"


def test_service_spec_user_from_sudo(tmp_path, monkeypatch):
    monkeypatch.setenv("SUDO_USER", "alice")
    spec = noesis._service_spec(tmp_path, host="0.0.0.0", port=18080)
    assert spec.user == "alice"


def test_service_spec_sets_uv_bin(tmp_path, monkeypatch):
    monkeypatch.setattr(noesis, "find_uv", lambda: "/opt/uv")
    spec = noesis._service_spec(tmp_path, host="0.0.0.0", port=18080)
    assert spec.uv_bin == "/opt/uv"


# ── firewall ────────────────────────────────────────────────────────────────


def test_firewall_commands():
    assert noesis.firewall_open_command("ufw", 18080) == ["sudo", "ufw", "allow", "18080/tcp"]
    assert noesis.firewall_open_command("ufw", 18080, "192.168.1.0/24") == [
        "sudo", "ufw", "allow", "from", "192.168.1.0/24",
        "to", "any", "port", "18080", "proto", "tcp",
    ]
    assert "firewall-cmd" in noesis.firewall_open_command("firewalld", 18080)
    firewalld_scoped = noesis.firewall_open_command("firewalld", 18080, "192.168.1.0/24")
    assert any("192.168.1.0/24" in part for part in firewalld_scoped)
    win = noesis.firewall_open_command("windows", 18080)
    assert win is not None and "netsh" in win
    assert noesis.firewall_open_command("macos", 18080) is None


def test_local_subnet_from_default_route(monkeypatch):
    monkeypatch.setattr(noesis.shutil, "which", lambda name: "/usr/sbin/ip" if name == "ip" else None)

    def fake(cmd, **k):
        if "route" in cmd:
            return _cp(0, "default via 192.168.1.1 dev wlp3s0 proto static src 192.168.1.125 metric 600")
        if "addr" in cmd:
            return _cp(0, "3: wlp3s0    inet 192.168.1.125/24 brd 192.168.1.255 scope global wlp3s0")
        return _cp(0, "")

    monkeypatch.setattr(noesis, "run_command", fake)
    assert noesis.local_subnet() == "192.168.1.0/24"


def test_local_subnet_none_without_ip(monkeypatch):
    monkeypatch.setattr(noesis.shutil, "which", lambda name: None)
    assert noesis.local_subnet() is None


def test_ufw_enabled_reads_conf(tmp_path, monkeypatch):
    conf = tmp_path / "ufw.conf"
    monkeypatch.setattr(noesis, "UFW_CONF", conf)
    conf.write_text("ENABLED=yes\n", encoding="utf-8")
    assert noesis.ufw_enabled() is True
    conf.write_text("ENABLED=no\n", encoding="utf-8")
    assert noesis.ufw_enabled() is False


def test_ufw_enabled_falls_back_to_status(tmp_path, monkeypatch):
    monkeypatch.setattr(noesis, "UFW_CONF", tmp_path / "missing.conf")
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(0, "Stato: inattivo"))
    assert noesis.ufw_enabled() is False
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(0, "Stato: attivo"))
    assert noesis.ufw_enabled() is True


def test_firewall_rule_present_ufw(monkeypatch):
    out = "To                         Action      From\n--                         ------      ----\n18080/tcp                  ALLOW       192.168.1.0/24\n"
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(0, out))
    assert noesis.firewall_rule_present("ufw", 18080, "192.168.1.0/24") is True
    assert noesis.firewall_rule_present("ufw", 18080, "10.0.0.0/8") is False
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(0, ""))
    assert noesis.firewall_rule_present("ufw", 18080, None) is None


def test_maybe_open_firewall_warns_when_active(monkeypatch):
    monkeypatch.setattr(noesis, "detect_firewall", lambda: "ufw")
    monkeypatch.setattr(noesis, "local_subnet", lambda: "192.168.1.0/24")
    monkeypatch.setattr(noesis, "firewall_active", lambda fw: True)
    ui = noesis.UI(quiet=True)
    noesis._maybe_open_firewall(argparse.Namespace(open_firewall=False), ui, port=18080)
    assert any(e["level"] == "warn" and "192.168.1.0/24" in e["message"] for e in ui.events)


def test_maybe_open_firewall_skips_when_inactive(monkeypatch):
    monkeypatch.setattr(noesis, "detect_firewall", lambda: "ufw")
    monkeypatch.setattr(noesis, "local_subnet", lambda: "192.168.1.0/24")
    monkeypatch.setattr(noesis, "firewall_active", lambda fw: False)
    ui = noesis.UI(quiet=True)
    noesis._maybe_open_firewall(argparse.Namespace(open_firewall=False), ui, port=18080)
    assert any("già raggiungibile" in e["message"] for e in ui.events)
    assert not any(e["level"] == "warn" for e in ui.events)


def test_maybe_open_firewall_opens_scoped_rule(monkeypatch):
    monkeypatch.setattr(noesis, "detect_firewall", lambda: "ufw")
    monkeypatch.setattr(noesis, "local_subnet", lambda: "192.168.1.0/24")
    monkeypatch.setattr(noesis, "firewall_active", lambda fw: True)
    monkeypatch.setattr(noesis, "DRY_RUN", False)
    monkeypatch.setattr(noesis, "firewall_rule_present", lambda fw, port, subnet: True)
    commands: list[list[str]] = []
    monkeypatch.setattr(noesis, "run_command", lambda cmd, **k: commands.append(list(cmd)) or _cp(0, "Rule added"))
    ui = noesis.UI(quiet=True)
    noesis._maybe_open_firewall(argparse.Namespace(open_firewall=True), ui, port=18080)
    assert ["sudo", "ufw", "allow", "from", "192.168.1.0/24",
            "to", "any", "port", "18080", "proto", "tcp"] in commands
    assert any(e["level"] == "ok" and "192.168.1.0/24" in e["message"] for e in ui.events)


def test_maybe_open_firewall_inactive_skips_even_with_flag(monkeypatch):
    monkeypatch.setattr(noesis, "detect_firewall", lambda: "ufw")
    monkeypatch.setattr(noesis, "local_subnet", lambda: "192.168.1.0/24")
    monkeypatch.setattr(noesis, "firewall_active", lambda fw: False)
    commands: list[list[str]] = []
    monkeypatch.setattr(noesis, "run_command", lambda cmd, **k: commands.append(list(cmd)) or _cp(0, ""))
    ui = noesis.UI(quiet=True)
    noesis._maybe_open_firewall(argparse.Namespace(open_firewall=True), ui, port=18080)
    assert commands == []  # niente regola: ufw è inattivo
    assert any("inattivo" in e["message"] for e in ui.events)


def test_maybe_open_firewall_reports_failure(monkeypatch):
    monkeypatch.setattr(noesis, "detect_firewall", lambda: "ufw")
    monkeypatch.setattr(noesis, "local_subnet", lambda: "192.168.1.0/24")
    monkeypatch.setattr(noesis, "firewall_active", lambda fw: True)
    monkeypatch.setattr(noesis, "DRY_RUN", False)
    monkeypatch.setattr(noesis, "run_command", lambda cmd, **k: _cp(1, "permission denied"))
    ui = noesis.UI(quiet=True)
    noesis._maybe_open_firewall(argparse.Namespace(open_firewall=True), ui, port=18080)
    assert any(e["level"] == "error" for e in ui.events)
    assert not any(e["level"] == "ok" for e in ui.events)


def test_firewall_active_windows(monkeypatch):
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(0, "2"))
    assert noesis.firewall_active("windows") is True
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(0, "0"))
    assert noesis.firewall_active("windows") is False
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(1, ""))
    assert noesis.firewall_active("windows") is None


def test_firewall_rule_present_windows(monkeypatch):
    out = "Rule Name: Noesis PDF Cloner 18080\nLocalPort: 18080\nRemoteIP: LocalSubnet\n"
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(0, out))
    assert noesis.firewall_rule_present("windows", 18080, None) is True
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(1, "No rules match the specified criteria."))
    assert noesis.firewall_rule_present("windows", 18080, None) is False
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(1, ""))
    assert noesis.firewall_rule_present("windows", 18080, None) is None


def test_maybe_open_firewall_windows_warns(monkeypatch):
    monkeypatch.setattr(noesis, "detect_firewall", lambda: "windows")
    monkeypatch.setattr(noesis, "firewall_active", lambda fw: True)
    ui = noesis.UI(quiet=True)
    noesis._maybe_open_firewall(argparse.Namespace(open_firewall=False), ui, port=18080)
    assert any(e["level"] == "warn" and "amministratore" in e["message"] for e in ui.events)


def test_maybe_open_firewall_windows_inactive_skips(monkeypatch):
    monkeypatch.setattr(noesis, "detect_firewall", lambda: "windows")
    monkeypatch.setattr(noesis, "firewall_active", lambda fw: False)
    called: list[int] = []
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: called.append(1))
    ui = noesis.UI(quiet=True)
    noesis._maybe_open_firewall(argparse.Namespace(open_firewall=True), ui, port=18080)
    assert called == []
    assert any("inattivo" in e["message"] for e in ui.events)


def test_maybe_open_firewall_windows_opens(monkeypatch):
    monkeypatch.setattr(noesis, "detect_firewall", lambda: "windows")
    monkeypatch.setattr(noesis, "firewall_active", lambda fw: True)
    monkeypatch.setattr(noesis, "firewall_rule_present", lambda fw, port, subnet: True)
    monkeypatch.setattr(noesis, "DRY_RUN", False)
    commands: list[list[str]] = []
    monkeypatch.setattr(noesis, "run_command", lambda cmd, **k: commands.append(list(cmd)) or _cp(0, "Ok."))
    ui = noesis.UI(quiet=True)
    noesis._maybe_open_firewall(argparse.Namespace(open_firewall=True), ui, port=18080)
    assert any(c and c[0] == "netsh" and "remoteip=localsubnet" in c for c in commands)
    assert any(e["level"] == "ok" and "aperta" in e["message"] for e in ui.events)


def test_maybe_open_firewall_windows_elevates_on_failure(monkeypatch):
    monkeypatch.setattr(noesis, "detect_firewall", lambda: "windows")
    monkeypatch.setattr(noesis, "firewall_active", lambda fw: True)
    monkeypatch.setattr(noesis, "firewall_rule_present", lambda fw, port, subnet: True)
    monkeypatch.setattr(noesis, "DRY_RUN", False)
    monkeypatch.setattr(noesis, "run_command", lambda cmd, **k: _cp(1, "requires elevation"))
    monkeypatch.setattr(noesis, "_run_elevated_windows", lambda command, ui: True)
    ui = noesis.UI(quiet=True)
    noesis._maybe_open_firewall(argparse.Namespace(open_firewall=True), ui, port=18080)
    assert any(e["level"] == "ok" for e in ui.events)


def test_maybe_open_firewall_windows_instructions_on_failure(monkeypatch):
    monkeypatch.setattr(noesis, "detect_firewall", lambda: "windows")
    monkeypatch.setattr(noesis, "firewall_active", lambda fw: True)
    monkeypatch.setattr(noesis, "DRY_RUN", False)
    monkeypatch.setattr(noesis, "run_command", lambda cmd, **k: _cp(1, "requires elevation"))
    monkeypatch.setattr(noesis, "_run_elevated_windows", lambda command, ui: False)
    ui = noesis.UI(quiet=True)
    noesis._maybe_open_firewall(argparse.Namespace(open_firewall=True), ui, port=18080)
    assert any(e["level"] == "error" for e in ui.events)
    assert any("comando manuale" in e["message"] for e in ui.events)


# ── uvicorn ─────────────────────────────────────────────────────────────────


def test_uvicorn_command(monkeypatch):
    monkeypatch.setattr(noesis, "is_windows", lambda: False)
    venv = Path("/r/.venv")
    cmd = noesis.uvicorn_command(venv, "0.0.0.0", 18080)
    assert cmd[0] == str(noesis.venv_python_in(venv))
    assert cmd[1:4] == ["-m", "uvicorn", "app.main:app"]
    assert cmd[-1] == "18080"


# ── UI (fallback ASCII su console non-UTF8, es. Windows cp1252) ─────────────


def test_ui_ascii_fallback(monkeypatch):
    monkeypatch.setattr(noesis, "_stream_supports_unicode", lambda: False)
    ui = noesis.UI()
    assert ui.icons["ok"] == "+"
    assert "\u2714" not in ui._paint("ok", "ciao")


def test_ui_unicode_when_supported(monkeypatch):
    monkeypatch.setattr(noesis, "_stream_supports_unicode", lambda: True)
    ui = noesis.UI()
    assert ui.icons["ok"] == "\u2714"


# ── doctor ──────────────────────────────────────────────────────────────────


def test_doctor_checks_smoke(tmp_path, monkeypatch):
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(0, "x\ny\n"))
    monkeypatch.setattr(noesis, "health_check", lambda *a, **k: False)
    monkeypatch.setattr(noesis, "find_uv", lambda: "/usr/bin/uv")
    monkeypatch.setattr(noesis, "detect_firewall", lambda: None)
    monkeypatch.setattr(noesis, "is_wsl", lambda: False)
    checks = noesis.doctor_checks(tmp_path)
    assert any(c.message.startswith("piattaforma") for c in checks)
    assert any("cartella dati scrivibile" in c.message for c in checks)


# ── bundle ──────────────────────────────────────────────────────────────────


def test_bundle_manifest(tmp_path):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "a.whl").write_text("x")
    (wheelhouse / "b.whl").write_text("x")
    manifest = noesis.bundle_manifest(tmp_path, wheelhouse, None)
    assert manifest["wheels"] == 2
    assert manifest["models"] is False
    assert manifest["app"] == noesis.APP_NAME


def test_create_and_install_bundle(tmp_path, monkeypatch):
    models = tmp_path / "babeldoc"
    models.mkdir()
    (models / "model.bin").write_text("modello")
    monkeypatch.setattr(noesis, "babeldoc_cache_dir", lambda: models)

    def fake_download(uv, dest, ui):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "fake.whl").write_text("wheel")

    monkeypatch.setattr(noesis, "download_wheels", fake_download)

    ui = noesis.UI(quiet=True)
    archive = tmp_path / "bundle.tar.gz"
    noesis.create_bundle("uv", tmp_path, archive, ui)
    assert archive.is_file()
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert any(n.endswith("manifest.json") for n in names)
    assert any(n.endswith("fake.whl") for n in names)
    assert any("models/babeldoc/model.bin" in n for n in names)

    calls: list[Path | None] = []
    monkeypatch.setattr(noesis, "ensure_service_venv", lambda uv, ui, offline=None: calls.append(offline))
    monkeypatch.setattr(noesis, "ensure_engine_venv", lambda uv, ui, offline=None: calls.append(offline))
    target = tmp_path / "restored" / "babeldoc"
    monkeypatch.setattr(noesis, "babeldoc_cache_dir", lambda: target)
    noesis.install_from_bundle("uv", tmp_path, archive, ui)
    assert (target / "model.bin").read_text() == "modello"
    assert all(c is not None for c in calls)


# ── CLI ─────────────────────────────────────────────────────────────────────


def test_parser_install_flags():
    parser = noesis.build_parser()
    args = parser.parse_args(["install", "--no-service", "--skip-warm", "--ci"])
    assert args.command == "install"
    assert args.no_service and args.skip_warm and args.ci


def test_parser_defaults_host_port_none():
    parser = noesis.build_parser()
    args = parser.parse_args(["start"])
    assert args.host is None and args.port is None


def test_handlers_cover_all_commands():
    parser = noesis.build_parser()
    subcommands = {a for action in parser._actions if isinstance(action, argparse._SubParsersAction) for a in action.choices}
    assert subcommands == set(noesis._HANDLERS)


# ── install (wiring chiave OpenRouter) ──────────────────────────────────────


def _install_args(tmp_path, **over):
    base = dict(
        data_dir=str(tmp_path), host=None, port=None, bundle=None,
        no_engine=False, skip_warm=True, no_service=True, no_browser=True,
        ci=False, mode="user", open_firewall=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


def _patch_install_heavy(monkeypatch):
    monkeypatch.setattr(noesis, "DRY_RUN", False)
    monkeypatch.setattr(noesis, "ensure_uv", lambda ui: "/usr/bin/uv")
    monkeypatch.setattr(noesis, "ensure_service_venv", lambda uv, ui, offline=None: None)
    monkeypatch.setattr(noesis, "ensure_engine_venv", lambda uv, ui, offline=None: None)
    monkeypatch.setattr(noesis, "warm_engine", lambda ui: True)
    monkeypatch.setattr(noesis, "detect_firewall", lambda: None)
    monkeypatch.setattr(noesis, "health_check", lambda *a, **k: True)
    monkeypatch.setattr(noesis, "port_listening", lambda *a, **k: False)
    monkeypatch.setattr(noesis, "local_ip", lambda: None)
    monkeypatch.setattr(noesis, "print_health_report", lambda data_dir, ui: None)


def test_cmd_install_calls_openrouter_prompt(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    calls: list[Path] = []
    monkeypatch.setattr(noesis, "ensure_openrouter_key", lambda data_dir, ui: calls.append(data_dir))
    _patch_install_heavy(monkeypatch)
    assert noesis.cmd_install(_install_args(tmp_path), noesis.UI(quiet=True)) == 0
    assert calls == [tmp_path]


def test_cmd_install_ci_skips_openrouter_prompt(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    calls: list[Path] = []
    monkeypatch.setattr(noesis, "ensure_openrouter_key", lambda data_dir, ui: calls.append(data_dir))
    _patch_install_heavy(monkeypatch)
    assert noesis.cmd_install(_install_args(tmp_path, ci=True), noesis.UI(quiet=True)) == 0
    assert calls == []


def test_cmd_install_calls_verify_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    calls: list[Path] = []
    monkeypatch.setattr(noesis, "ensure_openrouter_key", lambda data_dir, ui: None)
    monkeypatch.setattr(noesis, "verify_openrouter_key", lambda data_dir, ui: calls.append(data_dir))
    _patch_install_heavy(monkeypatch)
    assert noesis.cmd_install(_install_args(tmp_path), noesis.UI(quiet=True)) == 0
    assert calls == [tmp_path]


def test_cmd_install_ci_skips_verify_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    calls: list[Path] = []
    monkeypatch.setattr(noesis, "ensure_openrouter_key", lambda data_dir, ui: None)
    monkeypatch.setattr(noesis, "verify_openrouter_key", lambda data_dir, ui: calls.append(data_dir))
    _patch_install_heavy(monkeypatch)
    assert noesis.cmd_install(_install_args(tmp_path, ci=True), noesis.UI(quiet=True)) == 0
    assert calls == []


def test_cmd_install_waits_for_health(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(noesis, "ensure_openrouter_key", lambda data_dir, ui: None)
    monkeypatch.setattr(noesis, "verify_openrouter_key", lambda data_dir, ui: None)
    _patch_install_heavy(monkeypatch)

    class _FakeService:
        def __init__(self, *a, **k):
            pass

        def install(self):
            pass

    monkeypatch.setattr(noesis, "ServiceController", _FakeService)
    waited: list[int] = []
    monkeypatch.setattr(noesis, "wait_for_health", lambda host, port, **k: waited.append(port) or True)
    ui = noesis.UI(quiet=True)
    assert noesis.cmd_install(_install_args(tmp_path, no_service=False), ui) == 0
    assert waited  # attesa health eseguita
    assert any("raggiungibile" in e["message"] for e in ui.events)


def test_cmd_install_no_service_does_not_wait(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(noesis, "ensure_openrouter_key", lambda data_dir, ui: None)
    monkeypatch.setattr(noesis, "verify_openrouter_key", lambda data_dir, ui: None)
    _patch_install_heavy(monkeypatch)
    called: list[int] = []
    monkeypatch.setattr(noesis, "wait_for_health", lambda host, port, **k: called.append(port) or True)
    ui = noesis.UI(quiet=True)
    assert noesis.cmd_install(_install_args(tmp_path, no_service=True), ui) == 0
    assert called == []  # --no-service: nessuna attesa, solo hint


def test_cmd_install_ci_skips_report(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(noesis, "ensure_openrouter_key", lambda data_dir, ui: None)
    monkeypatch.setattr(noesis, "verify_openrouter_key", lambda data_dir, ui: None)
    _patch_install_heavy(monkeypatch)
    calls: list[int] = []
    monkeypatch.setattr(noesis, "print_health_report", lambda data_dir, ui: calls.append(1))
    assert noesis.cmd_install(_install_args(tmp_path, ci=True), noesis.UI(quiet=True)) == 0
    assert calls == []  # --ci: niente report (nessuna rete in CI)
    assert noesis.cmd_install(_install_args(tmp_path, ci=False), noesis.UI(quiet=True)) == 0
    assert calls == [1]


# ── logs ────────────────────────────────────────────────────────────────────


def test_cmd_logs_reads_file(tmp_path, capsys):
    log = noesis.service_log(tmp_path)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("a\nb\nc\n", encoding="utf-8")
    args = argparse.Namespace(data_dir=str(tmp_path), lines=2)
    assert noesis.cmd_logs(args, noesis.UI(quiet=True)) == 0
    assert capsys.readouterr().out.strip().splitlines() == ["b", "c"]


def test_cmd_logs_falls_back_to_journalctl(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(noesis, "is_windows", lambda: False)
    monkeypatch.setattr(noesis, "is_macos", lambda: False)
    monkeypatch.setattr(noesis.shutil, "which", lambda name: "/usr/bin/journalctl" if name == "journalctl" else None)
    monkeypatch.setattr(noesis, "run_command", lambda *a, **k: _cp(0, "journal line 1\njournal line 2"))
    args = argparse.Namespace(data_dir=str(tmp_path), lines=5)
    assert noesis.cmd_logs(args, noesis.UI(quiet=True)) == 0
    assert "journal line 1" in capsys.readouterr().out


def test_cmd_logs_no_log_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(noesis, "is_windows", lambda: True)  # niente fallback journalctl
    ui = noesis.UI(quiet=True)
    args = argparse.Namespace(data_dir=str(tmp_path), lines=5)
    assert noesis.cmd_logs(args, ui) == 1
    assert any(e["level"] == "warn" for e in ui.events)


# ── uninstall ───────────────────────────────────────────────────────────────


def _uninstall_args(*argv):
    return noesis.build_parser().parse_args(["uninstall", *argv])


def _ui():
    return noesis.UI(quiet=True)


def _fake_uninstall_env(tmp_path, monkeypatch):
    """Venv/motore/BabelDOC/data finti + servizio neutralizzato."""
    service = tmp_path / "svc-venv"
    engine = tmp_path / "eng-venv"
    babeldoc = tmp_path / "babeldoc"
    data = tmp_path / "data"
    for venv in (service, engine):
        venv.mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text("home = /python", encoding="utf-8")
    babeldoc.mkdir()
    (babeldoc / "model.bin").write_text("m" * 32, encoding="utf-8")
    data.mkdir()
    (data / "jobs.db").write_text("db" * 16, encoding="utf-8")

    monkeypatch.setattr(noesis, "service_venv", lambda: service)
    monkeypatch.setattr(noesis, "engine_venv", lambda: engine)
    monkeypatch.setattr(noesis, "babeldoc_cache_dir", lambda: babeldoc)
    monkeypatch.setattr(noesis, "DRY_RUN", False)
    calls: list[str] = []
    monkeypatch.setattr(noesis, "stop_background", lambda *a, **k: calls.append("stop") or True)

    class _FakeController:
        def __init__(self, *a, **k):
            pass

        def uninstall(self):
            calls.append("service")

    monkeypatch.setattr(noesis, "ServiceController", _FakeController)
    return service, engine, babeldoc, data, calls


def test_fmt_size_and_path_size(tmp_path):
    assert noesis._fmt_size(0) == "0 B"
    assert noesis._fmt_size(1536) == "1.5 KB"
    folder = tmp_path / "d"
    folder.mkdir()
    (folder / "a").write_bytes(b"x" * 100)
    assert noesis._path_size(folder) == 100
    assert noesis._path_size(None) == 0
    assert noesis._path_size(tmp_path / "missing") == 0


def test_is_venv(tmp_path):
    venv = tmp_path / "v"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("x", encoding="utf-8")
    assert noesis._is_venv(venv)
    assert not noesis._is_venv(tmp_path)


def test_parse_selection():
    assert noesis._parse_selection("", 4) == set()
    assert noesis._parse_selection("a", 4) == {1, 2, 3, 4}
    assert noesis._parse_selection("2,3", 4) == {2, 3}
    assert noesis._parse_selection("9", 4) == set()
    assert noesis._parse_selection("1 4", 4) == {1, 4}


def test_external_cache_dir(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    external = tmp_path / "ext-cache"
    external.mkdir()
    monkeypatch.setenv("CACHE_ROOT", str(external))
    assert noesis._external_cache_dir(data) == external
    inside = data / "cache"
    inside.mkdir()
    monkeypatch.setenv("CACHE_ROOT", str(inside))
    assert noesis._external_cache_dir(data) is None


def test_uninstall_dry_run_changes_nothing(tmp_path, monkeypatch):
    service, engine, babeldoc, data, calls = _fake_uninstall_env(tmp_path, monkeypatch)
    monkeypatch.setattr(noesis, "DRY_RUN", True)
    code = noesis.cmd_uninstall(
        _uninstall_args("--all", "--data-dir", str(data)), _ui()
    )
    assert code == 0
    assert service.exists() and engine.exists() and babeldoc.exists() and data.exists()
    assert calls == []  # in dry-run non si ferma né rimuove nulla


def test_uninstall_all_removes_everything_but_uv(tmp_path, monkeypatch):
    service, engine, babeldoc, data, calls = _fake_uninstall_env(tmp_path, monkeypatch)
    uv_cache = tmp_path / "uv-cache"
    uv_cache.mkdir()
    (uv_cache / "f").write_text("k", encoding="utf-8")
    code = noesis.cmd_uninstall(
        _uninstall_args("--all", "--yes", "--data-dir", str(data)), _ui()
    )
    assert code == 0
    assert not service.exists()
    assert not engine.exists()
    assert not babeldoc.exists()
    assert not data.exists()
    assert uv_cache.exists()  # la cache condivisa di uv non si tocca
    assert calls == ["stop", "service"]


def test_uninstall_data_only(tmp_path, monkeypatch):
    service, engine, babeldoc, data, _ = _fake_uninstall_env(tmp_path, monkeypatch)
    code = noesis.cmd_uninstall(_uninstall_args("--data", "--data-dir", str(data)), _ui())
    assert code == 0
    assert not data.exists()
    assert service.exists() and engine.exists() and babeldoc.exists()


def test_uninstall_engine_includes_babeldoc(tmp_path, monkeypatch):
    service, engine, babeldoc, data, _ = _fake_uninstall_env(tmp_path, monkeypatch)
    code = noesis.cmd_uninstall(_uninstall_args("--engine", "--data-dir", str(data)), _ui())
    assert code == 0
    assert not engine.exists()
    assert not babeldoc.exists()  # --engine include la cache BabelDOC
    assert service.exists() and data.exists()


def test_uninstall_skips_non_venv(tmp_path, monkeypatch):
    service, engine, babeldoc, data, _ = _fake_uninstall_env(tmp_path, monkeypatch)
    (engine / "pyvenv.cfg").unlink()
    code = noesis.cmd_uninstall(_uninstall_args("--venv", "--data-dir", str(data)), _ui())
    assert code == 0
    assert engine.exists()  # non è un venv: saltato per sicurezza


def test_uninstall_missing_engine_skipped_silently(tmp_path, monkeypatch):
    import shutil

    service, engine, babeldoc, data, _ = _fake_uninstall_env(tmp_path, monkeypatch)
    shutil.rmtree(engine)  # motore già assente
    ui = noesis.UI(quiet=True)
    code = noesis.cmd_uninstall(_uninstall_args("--all", "--yes", "--data-dir", str(data)), ui)
    assert code == 0
    # Un path assente non deve produrre l'avviso "non sembra un venv".
    assert not any("non sembra un venv" in e["message"] for e in ui.events)


def test_uninstall_dry_run_marks_absent(tmp_path, monkeypatch):
    import shutil

    service, engine, babeldoc, data, _ = _fake_uninstall_env(tmp_path, monkeypatch)
    shutil.rmtree(engine)
    monkeypatch.setattr(noesis, "DRY_RUN", True)
    ui = noesis.UI(quiet=True)
    noesis.cmd_uninstall(_uninstall_args("--all", "--data-dir", str(data)), ui)
    assert any(
        "Motore (.venv2)" in e["message"] and "(assente)" in e["message"] for e in ui.events
    )


def test_uninstall_external_cache(tmp_path, monkeypatch):
    service, engine, babeldoc, data, _ = _fake_uninstall_env(tmp_path, monkeypatch)
    external = tmp_path / "ext-cache"
    external.mkdir()
    (external / "split").write_text("s", encoding="utf-8")
    monkeypatch.setenv("CACHE_ROOT", str(external))
    noesis.cmd_uninstall(_uninstall_args("--cache", "--data-dir", str(data)), _ui())
    assert not external.exists()
    assert data.exists()


def test_parser_uninstall_flags():
    args = _uninstall_args("--all", "-y", "--dry-run")
    assert args.all_ and args.yes and args.dry_run
    alias = _uninstall_args("--purge")
    assert alias.data  # retro-compatibile con --purge


def test_uninstall_interactive_selection(tmp_path, monkeypatch):
    service, engine, babeldoc, data, calls = _fake_uninstall_env(tmp_path, monkeypatch)
    ui = noesis.UI(quiet=True)
    # Simula un TTY e la selezione "2,3" = motore + cache BabelDOC.
    monkeypatch.setattr(noesis.UI, "is_interactive", lambda self: True)
    monkeypatch.setattr(noesis.UI, "ask", lambda self, q, default="": "2,3")
    monkeypatch.setattr(noesis.UI, "ask_yes_no", lambda self, q, default=False: True)
    code = noesis.cmd_uninstall(_uninstall_args("--data-dir", str(data)), ui)
    assert code == 0
    assert not engine.exists()
    assert not babeldoc.exists()
    assert service.exists() and data.exists()  # non selezionati: conservati
    assert calls == ["stop", "service"]


def test_uninstall_interactive_all(tmp_path, monkeypatch):
    service, engine, babeldoc, data, calls = _fake_uninstall_env(tmp_path, monkeypatch)
    ui = noesis.UI(quiet=True)
    monkeypatch.setattr(noesis.UI, "is_interactive", lambda self: True)
    monkeypatch.setattr(noesis.UI, "ask", lambda self, q, default="": "a")
    monkeypatch.setattr(noesis.UI, "ask_yes_no", lambda self, q, default=False: True)
    code = noesis.cmd_uninstall(_uninstall_args("--data-dir", str(data)), ui)
    assert code == 0
    assert not service.exists() and not engine.exists()
    assert not babeldoc.exists() and not data.exists()


# ── helper ──────────────────────────────────────────────────────────────────


def _cp(returncode: int, stdout: str = ""):
    import subprocess

    return subprocess.CompletedProcess([], returncode, stdout, "")
