"""Test della console di installazione/gestione (``tools/noesis.py``).

Solo logica pura: nessuna rete, nessun servizio, nessuna modifica al sistema.
Le funzioni che eseguono comandi vengono sostituite con finti runner.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
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


def test_service_spec_uses_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ROLE", "api")
    spec = noesis._service_spec(tmp_path, host="0.0.0.0", port=18080)
    assert spec.role == "api"
    assert spec.env_file == tmp_path / "noesis.env"


def test_service_spec_user_from_sudo(tmp_path, monkeypatch):
    monkeypatch.setenv("SUDO_USER", "alice")
    spec = noesis._service_spec(tmp_path, host="0.0.0.0", port=18080)
    assert spec.user == "alice"


# ── firewall ────────────────────────────────────────────────────────────────


def test_firewall_commands():
    assert noesis.firewall_open_command("ufw", 18080) == ["sudo", "ufw", "allow", "18080/tcp"]
    assert "firewall-cmd" in noesis.firewall_open_command("firewalld", 18080)
    win = noesis.firewall_open_command("windows", 18080)
    assert win is not None and "netsh" in win
    assert noesis.firewall_open_command("macos", 18080) is None


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
