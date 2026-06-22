"""EPIC SVR (SVR-03) — the ``cdmon settings`` CLI (offline, read-only, K1/K4).

Resolves a settings file + env overrides and prints the effective server runtime
settings + secret presence (never the values); loud ConfigError → nonzero exit.

Features: FEAT-SETTINGS-008
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from code_doc_monitor.cli import app

runner = CliRunner()


def _settings_file(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "settings.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_settings_table_shows_resolved_values(tmp_path: Path) -> None:
    cfg = _settings_file(tmp_path, "server:\n  port: 9001\n  log_level: warning\n")
    res = runner.invoke(app, ["settings", "--settings", str(cfg)])
    assert res.exit_code == 0, res.output
    assert "server.port: 9001" in res.output
    assert "server.log_level: warning" in res.output
    assert "secrets (presence only" in res.output


def test_settings_json_shape(tmp_path: Path) -> None:
    cfg = _settings_file(tmp_path, "server:\n  host: 127.0.0.1\n")
    res = runner.invoke(app, ["settings", "--settings", str(cfg), "--json"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["settings"]["server"]["host"] == "127.0.0.1"
    assert set(payload["secrets"]) == {
        "admin_token_configured",
        "database_url_set",
        "secret_key_set",
    }


def test_settings_env_overrides_file(tmp_path: Path, monkeypatch) -> None:
    cfg = _settings_file(tmp_path, "server:\n  port: 9001\n")
    monkeypatch.setenv("CDMON_SERVER_PORT", "7007")
    res = runner.invoke(app, ["settings", "--settings", str(cfg)])
    assert res.exit_code == 0, res.output
    assert "server.port: 7007" in res.output  # env wins over the file


def test_settings_reports_secret_presence_not_value(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _settings_file(tmp_path, "{}\n")
    monkeypatch.setenv("CDMON_ADMIN_TOKEN", "tok-DONOTLEAK")
    res = runner.invoke(app, ["settings", "--settings", str(cfg)])
    assert res.exit_code == 0, res.output
    assert "admin_token_configured: set" in res.output
    assert "DONOTLEAK" not in res.output  # the value is never printed


def test_settings_absent_file_is_defaults(tmp_path: Path) -> None:
    res = runner.invoke(app, ["settings", "--settings", str(tmp_path / "absent.yaml")])
    assert res.exit_code == 0, res.output
    assert "server.port: 33333" in res.output  # built-in default


def test_settings_loud_on_bad_file(tmp_path: Path) -> None:
    cfg = _settings_file(tmp_path, "server:\n  port: 70000\n")  # out of range
    res = runner.invoke(app, ["settings", "--settings", str(cfg)])
    assert res.exit_code == 1
    assert "error:" in res.output
