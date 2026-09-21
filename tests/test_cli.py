"""Test della CLI headless (con motore fittizio)."""

import app.cli as cli

from helpers import FakeEngine, make_pdf


def test_build_parser_defaults():
    parser = cli.build_parser()
    args = parser.parse_args(["input.pdf"])
    assert args.pages == "all"
    assert args.dst == "it"
    assert args.engine == "google"
    assert args.range_mode == "merged"


def test_list_engines_and_langs(capsys):
    assert cli.main(["--list-engines"]) == 0
    assert "google" in capsys.readouterr().out
    assert cli.main(["--list-langs"]) == 0
    assert "Italiano" in capsys.readouterr().out


def test_missing_file_is_fatal(capsys):
    assert cli.main(["/non/esiste.pdf"]) == 2


def test_list_pages(tmp_path, capsys):
    pdf = make_pdf(tmp_path / "doc.pdf", 3)
    assert cli.main([str(pdf), "--list-pages"]) == 0
    out = capsys.readouterr().out
    assert "3 pagine" in out
    assert "1\t1" in out


def test_end_to_end_local(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / "report.pdf", 3)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(
        cli,
        "_make_engine",
        lambda settings: FakeEngine(settings.cache_root, max_engine_procs=2),
    )
    code = cli.main([
        str(pdf),
        "-p", "1-2",
        "--dst", "it",
        "--out-dir", str(out_dir),
        "--data-dir", str(tmp_path / "data"),
        "--cache-dir", str(tmp_path / "cache"),
    ])
    assert code == 0
    assert (out_dir / "report_it.pdf").is_file()


def test_end_to_end_single_zip(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / "report.pdf", 3)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(
        cli,
        "_make_engine",
        lambda settings: FakeEngine(settings.cache_root, max_engine_procs=2),
    )
    code = cli.main([
        str(pdf),
        "-p", "1-3",
        "--range-mode", "single",
        "--output", "mio",
        "--out-dir", str(out_dir),
        "--data-dir", str(tmp_path / "data"),
        "--cache-dir", str(tmp_path / "cache"),
    ])
    assert code == 0
    assert (out_dir / "mio.zip").is_file()


def test_remote_mode_is_seam(tmp_path, capsys):
    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    assert cli.main([str(pdf), "--server", "http://x"]) == 2
    assert "seam" in capsys.readouterr().err
