"""AGT-04 — `cdx onboard` end to end: dry-run plan → --apply → arrive-green.

The onboarding agent on a real tmp repo: the default dry-run prints the plan
and writes NOTHING (K11); `--apply` writes config/cdmon/, scaffolds the docs,
heals them with the mock backend, and self-validates — the very next
`cdx check` and `cdx index --check` exit 0 (the Mintlify arrive-green rule);
re-running refuses without `--force`; the owner falls back to git user.name
through the injected seam. Offline, no network (K4).

Features: FEAT-ONBOARD-001, FEAT-ONBOARD-002
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from custodex import cli as cli_mod
from custodex.cli import app

runner = CliRunner()


def _fixture_repo(tmp_path: Path) -> Path:
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "core.py").write_text(
        'def solve(x):\n    """Doc."""\n    return x\n', encoding="utf-8"
    )
    (tmp_path / "beta").mkdir()
    (tmp_path / "beta" / "engine.py").write_text(
        "class Engine:\n    def run(self):\n        return 1\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# Widget\n\nA thing.\n", encoding="utf-8")
    return tmp_path


def test_dry_run_prints_plan_and_writes_nothing(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    before = sorted(p.as_posix() for p in root.rglob("*"))
    result = runner.invoke(app, ["onboard", "--path", str(root), "--owner", "me"])
    assert result.exit_code == 0, result.output
    assert "## Detected surfaces" in result.output
    assert "dry-run — nothing written" in result.output
    assert sorted(p.as_posix() for p in root.rglob("*")) == before


def test_apply_arrives_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _fixture_repo(tmp_path)
    monkeypatch.setattr(cli_mod, "_git_user_name", lambda _root: "git-mei")
    result = runner.invoke(app, ["onboard", "--path", str(root), "--apply"])
    assert result.exit_code == 0, result.output
    assert "onboarded — `cdx check` is green" in result.output

    config_dir = root / "config" / "cdmon"
    assert (config_dir / "alpha.yaml").is_file()
    assert "git-mei" in (config_dir / "alpha.yaml").read_text(encoding="utf-8")
    assert (root / "docs" / "alpha-api.md").is_file()

    # The arrive-green core: the freshly-onboarded repo passes the gates NOW.
    check = runner.invoke(app, ["check", "--config", str(config_dir)])
    assert check.exit_code == 0, check.output
    index = runner.invoke(app, ["index", "--check", "--config-dir", str(config_dir)])
    assert index.exit_code == 0, index.output


def test_apply_refuses_existing_config_without_force(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    config_dir = root / "config" / "cdmon"
    config_dir.mkdir(parents=True)
    (config_dir / "index.yaml").write_text("x: 1\n", encoding="utf-8")
    result = runner.invoke(
        app, ["onboard", "--path", str(root), "--apply", "--owner", "me"]
    )
    assert result.exit_code == 1
    assert "--force" in result.output


def test_apply_force_replaces_existing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fixture_repo(tmp_path)
    config_dir = root / "config" / "cdmon"
    config_dir.mkdir(parents=True)
    (config_dir / "stale.yaml").write_text("x: 1\n", encoding="utf-8")
    monkeypatch.setattr(cli_mod, "_git_user_name", lambda _root: None)
    result = runner.invoke(app, ["onboard", "--path", str(root), "--apply", "--force"])
    assert result.exit_code == 0, result.output
    assert not (config_dir / "stale.yaml").exists()
    assert "unassigned" in (config_dir / "alpha.yaml").read_text(encoding="utf-8")


def test_dry_run_reports_already_configured(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    (root / "cdmon.yaml").write_text("x: 1\n", encoding="utf-8")
    result = runner.invoke(app, ["onboard", "--path", str(root)])
    assert result.exit_code == 0
    assert "already configured" in result.output
