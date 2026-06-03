"""CDM-01 — tests for `cdmon init`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from code_doc_monitor.cli import app
from code_doc_monitor.config import Audience, load_config

runner = CliRunner()


def test_help_works() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.stdout


def test_init_writes_file(tmp_path: Path) -> None:
    target = tmp_path / "cdmon.yaml"
    result = runner.invoke(app, ["init", "--path", str(target)])
    assert result.exit_code == 0, result.stdout
    assert target.exists()
    # the file it wrote is a valid, loadable config
    cfg = load_config(target)
    audiences = {d.audience for d in cfg.documents}
    assert Audience.USER_GUIDE in audiences
    assert Audience.ENG_GUIDE in audiences


def test_init_refuses_overwrite_without_force(tmp_path: Path) -> None:
    target = tmp_path / "cdmon.yaml"
    target.write_text("original: keepme\n", encoding="utf-8")
    result = runner.invoke(app, ["init", "--path", str(target)])
    assert result.exit_code != 0
    # the existing file is untouched
    assert target.read_text(encoding="utf-8") == "original: keepme\n"


def test_init_overwrites_with_force(tmp_path: Path) -> None:
    target = tmp_path / "cdmon.yaml"
    target.write_text("original: keepme\n", encoding="utf-8")
    result = runner.invoke(app, ["init", "--path", str(target), "--force"])
    assert result.exit_code == 0, result.stdout
    assert target.read_text(encoding="utf-8") != "original: keepme\n"
    cfg = load_config(target)
    assert len(cfg.documents) >= 2


def test_init_default_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "cdmon.yaml").exists()
