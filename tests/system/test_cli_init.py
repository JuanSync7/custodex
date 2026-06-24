"""CDM-01 — tests for `cdx init`.

Features: FEAT-CLI-001, FEAT-CONFIG-008, FEAT-CONFIG-009, FEAT-CONFIG-010
Features: FEAT-RECORD-012, FEAT-RECORD-013
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from custodex.cli import app
from custodex.config import CONFIG_TEMPLATE, Audience, load_config
from custodex.sinks import HttpSink, make_sink

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


# --------------------------------------------------------------------------
# G-01 — `cdx init --central`
# --------------------------------------------------------------------------
def test_init_without_central_is_byte_identical_template(tmp_path: Path) -> None:
    target = tmp_path / "cdmon.yaml"
    result = runner.invoke(app, ["init", "--path", str(target)])
    assert result.exit_code == 0, result.stdout
    # ADDITIVE invariant: the offline template is byte-identical to today's.
    assert target.read_text(encoding="utf-8") == CONFIG_TEMPLATE


def test_init_central_writes_http_config_that_round_trips(tmp_path: Path) -> None:
    target = tmp_path / "cdmon.yaml"
    result = runner.invoke(
        app,
        [
            "init",
            "--path",
            str(target),
            "--central",
            "http://localhost:33333",
            "--repo-id",
            "demo/x",
        ],
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_config(target)
    assert cfg.central.sink == "http"
    assert cfg.central.url == "http://localhost:33333"
    assert cfg.central.repo_id == "demo/x"
    assert cfg.central.auth_env == "CDMON_CENTRAL_TOKEN"
    # ...and make_sink builds a real HttpSink from it (repo_id present).
    assert isinstance(make_sink(cfg.central), HttpSink)


def test_init_central_token_env_and_repo_url(tmp_path: Path) -> None:
    target = tmp_path / "cdmon.yaml"
    result = runner.invoke(
        app,
        [
            "init",
            "--path",
            str(target),
            "--central",
            "http://localhost:33333",
            "--repo-id",
            "demo/x",
            "--token-env",
            "MY_TOKEN",
            "--repo-url",
            "https://gitlab.com/demo/x",
        ],
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_config(target)
    assert cfg.central.auth_env == "MY_TOKEN"
    assert cfg.central.repo_url == "https://gitlab.com/demo/x"


def test_init_central_repo_id_defaults_to_cwd_name(tmp_path: Path, monkeypatch) -> None:
    work = tmp_path / "myrepo"
    work.mkdir()
    monkeypatch.chdir(work)
    result = runner.invoke(app, ["init", "--central", "http://localhost:33333"])
    assert result.exit_code == 0, result.stdout
    cfg = load_config(work / "cdmon.yaml")
    assert cfg.central.repo_id == "myrepo"


def test_init_central_still_carries_both_audiences(tmp_path: Path) -> None:
    target = tmp_path / "cdmon.yaml"
    result = runner.invoke(
        app,
        ["init", "--path", str(target), "--central", "http://x", "--repo-id", "r"],
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_config(target)
    audiences = {d.audience for d in cfg.documents}
    assert Audience.USER_GUIDE in audiences
    assert Audience.ENG_GUIDE in audiences
