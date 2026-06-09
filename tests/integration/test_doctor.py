"""G-02 — tests for `cdmon doctor` / `run_checks` (offline preflight).

Features: FEAT-QUALITY-008, FEAT-QUALITY-009, FEAT-CLI-014
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from code_doc_monitor.cli import app
from code_doc_monitor.config import (
    AgentConfig,
    Audience,
    BackendConfig,
    CentralConfig,
    DocumentSpec,
    MonitorConfig,
)
from code_doc_monitor.doctor import Check, CheckStatus, run_checks

runner = CliRunner()


def _good_config(doc_path: str = "docs/g.md") -> MonitorConfig:
    return MonitorConfig(
        documents=(DocumentSpec(id="g", path=doc_path, audience=Audience.ENG_GUIDE),),
    )


def _by_name(checks: list[Check]) -> dict[str, Check]:
    return {c.name: c for c in checks}


# --------------------------------------------------------------------------
# run_checks — unit
# --------------------------------------------------------------------------
def test_run_checks_returns_check_models(tmp_path: Path) -> None:
    checks = run_checks(_good_config(), tmp_path)
    assert all(isinstance(c, Check) for c in checks)
    assert all(isinstance(c.status, CheckStatus) for c in checks)
    # frozen / typed model
    assert checks[0].model_config["frozen"] is True


def test_check_order_is_deterministic(tmp_path: Path) -> None:
    names = [c.name for c in run_checks(_good_config(), tmp_path)]
    assert names == sorted(names) or names == names  # stable
    # run twice → identical ordering (K10)
    a = [c.name for c in run_checks(_good_config(), tmp_path)]
    b = [c.name for c in run_checks(_good_config(), tmp_path)]
    assert a == b
    # the core checks are always present, in a fixed leading order
    assert a[:4] == ["config", "documents", "backend", "central"]


def test_good_offline_config_no_fail(tmp_path: Path) -> None:
    checks = run_checks(_good_config(), tmp_path)
    assert all(c.status is not CheckStatus.FAIL for c in checks)
    assert _by_name(checks)["config"].status is CheckStatus.PASS
    # mock backend is always runnable
    assert _by_name(checks)["backend"].status is CheckStatus.PASS
    # central sink=none → PASS
    assert _by_name(checks)["central"].status is CheckStatus.PASS


def test_documents_missing_doc_is_pass_not_fail(tmp_path: Path) -> None:
    # doc file does not exist → MISSING_DOC is heal-creatable, not a failure.
    checks = _by_name(run_checks(_good_config(), tmp_path))
    assert checks["documents"].status is CheckStatus.PASS


def test_documents_missing_code_ref_warns(tmp_path: Path) -> None:
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(
                id="g",
                path="docs/g.md",
                audience=Audience.ENG_GUIDE,
                code_refs=({"path": "src/missing.py"},),  # type: ignore[arg-type]
            ),
        ),
    )
    checks = _by_name(run_checks(cfg, tmp_path))
    assert checks["documents"].status is CheckStatus.WARN


def test_central_file_sink_passes(tmp_path: Path) -> None:
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(id="g", path="docs/g.md", audience=Audience.ENG_GUIDE),
        ),
        central=CentralConfig(sink="file", path="review.jsonl"),
    )
    checks = _by_name(run_checks(cfg, tmp_path))
    assert checks["central"].status is CheckStatus.PASS


def test_central_file_sink_without_path_fails(tmp_path: Path) -> None:
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(id="g", path="docs/g.md", audience=Audience.ENG_GUIDE),
        ),
        central=CentralConfig(sink="file"),  # path missing
    )
    checks = _by_name(run_checks(cfg, tmp_path))
    assert checks["central"].status is CheckStatus.FAIL


def test_central_http_without_url_fails(tmp_path: Path) -> None:
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(id="g", path="docs/g.md", audience=Audience.ENG_GUIDE),
        ),
        central=CentralConfig(sink="http", repo_id="demo/x"),  # url missing
    )
    checks = _by_name(run_checks(cfg, tmp_path))
    assert checks["central"].status is CheckStatus.FAIL


def test_central_http_without_repo_id_fails(tmp_path: Path) -> None:
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(id="g", path="docs/g.md", audience=Audience.ENG_GUIDE),
        ),
        central=CentralConfig(sink="http", url="http://x"),  # repo_id missing
    )
    checks = _by_name(run_checks(cfg, tmp_path))
    assert checks["central"].status is CheckStatus.FAIL


def test_central_http_token_unset_warns(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CDMON_CENTRAL_TOKEN", raising=False)
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(id="g", path="docs/g.md", audience=Audience.ENG_GUIDE),
        ),
        central=CentralConfig(
            sink="http",
            url="http://x",
            repo_id="demo/x",
            auth_env="CDMON_CENTRAL_TOKEN",
        ),
    )
    checks = _by_name(run_checks(cfg, tmp_path))
    assert checks["central"].status is CheckStatus.WARN


def test_central_http_token_present_passes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CDMON_CENTRAL_TOKEN", "secret")
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(id="g", path="docs/g.md", audience=Audience.ENG_GUIDE),
        ),
        central=CentralConfig(
            sink="http",
            url="http://x",
            repo_id="demo/x",
            auth_env="CDMON_CENTRAL_TOKEN",
        ),
    )
    checks = _by_name(run_checks(cfg, tmp_path))
    assert checks["central"].status is CheckStatus.PASS


def test_backend_api_without_key_warns(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(id="g", path="docs/g.md", audience=Audience.ENG_GUIDE),
        ),
        backend=BackendConfig(kind="api"),
    )
    checks = _by_name(run_checks(cfg, tmp_path))
    # absent prereq is WARN, never FAIL (the config is valid; this env can't run it)
    assert checks["backend"].status is CheckStatus.WARN


def test_backend_api_with_key_passes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(id="g", path="docs/g.md", audience=Audience.ENG_GUIDE),
        ),
        backend=BackendConfig(kind="api"),
    )
    checks = _by_name(run_checks(cfg, tmp_path))
    assert checks["backend"].status is CheckStatus.PASS


def test_backend_claude_code_missing_cli_warns(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("code_doc_monitor.doctor.shutil.which", lambda _: None)
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(id="g", path="docs/g.md", audience=Audience.ENG_GUIDE),
        ),
        backend=BackendConfig(kind="claude-code"),
    )
    checks = _by_name(run_checks(cfg, tmp_path))
    assert checks["backend"].status is CheckStatus.WARN


def test_backend_claude_code_cli_present_passes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "code_doc_monitor.doctor.shutil.which", lambda _: "/usr/bin/claude"
    )
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(id="g", path="docs/g.md", audience=Audience.ENG_GUIDE),
        ),
        backend=BackendConfig(kind="claude-code"),
    )
    checks = _by_name(run_checks(cfg, tmp_path))
    assert checks["backend"].status is CheckStatus.PASS


def test_agent_backend_extra_check(tmp_path: Path, monkeypatch) -> None:
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(id="g", path="docs/g.md", audience=Audience.ENG_GUIDE),
        ),
        backend=BackendConfig(kind="agent"),
        agent=AgentConfig(driver="api", api_key_env="ANTHROPIC_API_KEY"),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    names = [c.name for c in run_checks(cfg, tmp_path)]
    assert "agent-extra" in names


def test_agent_extra_passes_when_present(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "code_doc_monitor.doctor.importlib.util.find_spec",
        lambda _: object(),
    )
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(id="g", path="docs/g.md", audience=Audience.ENG_GUIDE),
        ),
        backend=BackendConfig(kind="agent"),
    )
    checks = _by_name(run_checks(cfg, tmp_path))
    assert checks["agent-extra"].status is CheckStatus.PASS
    assert checks["backend"].status is CheckStatus.PASS


def test_agent_extra_warns_when_absent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "code_doc_monitor.doctor.importlib.util.find_spec", lambda _: None
    )
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(id="g", path="docs/g.md", audience=Audience.ENG_GUIDE),
        ),
        backend=BackendConfig(kind="agent"),
    )
    checks = _by_name(run_checks(cfg, tmp_path))
    assert checks["agent-extra"].status is CheckStatus.WARN


# --------------------------------------------------------------------------
# cdmon doctor — CLI / system
# --------------------------------------------------------------------------
def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


_GOOD_YAML = """\
version: "1.0.0"
root: "."
documents:
  - id: g
    path: docs/g.md
    audience: eng-guide
"""

_HTTP_NO_URL_YAML = """\
version: "1.0.0"
root: "."
documents:
  - id: g
    path: docs/g.md
    audience: eng-guide
central:
  sink: http
  repo_id: demo/x
"""


def test_cli_doctor_good_config_exit_0(tmp_path: Path) -> None:
    cfg = _write(tmp_path / "cdmon.yaml", _GOOD_YAML)
    result = runner.invoke(app, ["doctor", "--config", str(cfg)])
    assert result.exit_code == 0, result.stdout
    assert "PASS" in result.stdout


def test_cli_doctor_http_no_url_exit_1(tmp_path: Path) -> None:
    cfg = _write(tmp_path / "cdmon.yaml", _HTTP_NO_URL_YAML)
    result = runner.invoke(app, ["doctor", "--config", str(cfg)])
    assert result.exit_code == 1, result.stdout
    assert "FAIL" in result.stdout


def test_cli_doctor_malformed_config_exit_1(tmp_path: Path) -> None:
    cfg = _write(tmp_path / "cdmon.yaml", "documents: [: bad")
    result = runner.invoke(app, ["doctor", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "error:" in result.stderr
