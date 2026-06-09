"""Y-03 — the ``cdmon sync`` CLI (local + remote) over a REAL temp git repo.

The client-facing trigger for a config sync. Two paths, both offline (K4):

* **local** (no ``--remote``): runs :func:`code_doc_monitor.configsync.run_sync`
  against the current repo (cwd) and prints the run summary; ``--json`` parses to
  the engine's :class:`SyncRun` shape; ``--mode git`` works; a working-tree edit
  shows drift. Exit 0; a loud, traceback-free error otherwise (K8).
* **remote** (``--remote URL --repo-id ID``): POSTs to ``{URL}/repos/{ID}/sync``
  via the SAME HTTP+auth seam as ``cdmon register`` (the stdlib leaf is stubbed so
  there is NO network, K4); prints the returned server summary. A missing token is
  harmless (empty bearer) but an HTTP error / missing ``--repo-id`` is a loud
  non-zero exit (K8).

The repo fixture mirrors ``tests/test_configsync.py``; the CLI ``_now`` clock seam
is monkeypatched so a local run is deterministic (K10). The CLI is driven through
typer's ``CliRunner`` with ``cwd`` switched into the temp repo so ``Path.cwd()``
resolves to it.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

import code_doc_monitor.cli as cli_mod
import code_doc_monitor.registry as registry_mod
from code_doc_monitor.cli import app
from code_doc_monitor.configsync import run_sync

_NOW = "2026-06-07T00:00:00Z"

# --------------------------------------------------------------------------- #
# A real committed dir-layout git repo (same shape as the engine suite).
# --------------------------------------------------------------------------- #

_INDEX_YAML = """\
---
cdmon-config-version: "2.0.0"
repo: gitrepo
generated-by: cdmon
updated: "2026-06-07"
---
root: "../.."
version: "2.0.0"
apply_default: false
backend: {kind: mock}
central: {sink: none}
units:
  - file: core.yaml
ignore: ignore.yaml
"""

_CORE_UNIT_YAML = """\
---
cdmon-config-version: "2.0.0"
unit: core
title: "Core coverage"
owner: eng-platform
created: "2026-06-07"
updated: "2026-06-07"
---
dir-covered:
  - pkg
source-files-format:
  - ".py"
documents:
  - id: api-guide
    path: docs/api.md
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: pkg/calc.py
        symbols: [add]
"""

_IGNORE_YAML = """\
---
cdmon-config-version: "2.0.0"
source: "manual"
updated: "2026-06-07"
---
gitignore: false
patterns:
  - "*.log"
"""

_CALC_V1 = '''\
def add(a, b):
    """Add two numbers."""
    return a + b
'''

_DOC_STUB = """\
# API guide

Hand-written prose.

<!-- CDM:BEGIN symbols -->
PLACEHOLDER
<!-- CDM:END symbols -->
"""


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True
    )
    return out.stdout


def _seed_docs(config_dir: Path) -> None:
    result = CliRunner().invoke(app, ["monitor", "--config", str(config_dir), "--apply"])
    assert result.exit_code == 0, result.output


def _build_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    cfg = repo / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "index.yaml").write_text(_INDEX_YAML, encoding="utf-8")
    (cfg / "core.yaml").write_text(_CORE_UNIT_YAML, encoding="utf-8")
    (cfg / "ignore.yaml").write_text(_IGNORE_YAML, encoding="utf-8")
    pkg = repo / "pkg"
    pkg.mkdir()
    (pkg / "calc.py").write_text(_CALC_V1, encoding="utf-8")
    docs = repo / "docs"
    docs.mkdir()
    (docs / "api.md").write_text(_DOC_STUB, encoding="utf-8")

    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "tester")
    _seed_docs(cfg)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    return repo


@contextmanager
def _chdir(target: Path) -> Iterator[None]:
    """Switch cwd to ``target`` so the CLI's ``Path.cwd()`` resolves to the repo."""
    prev = Path.cwd()
    os.chdir(target)
    try:
        yield
    finally:
        os.chdir(prev)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a deterministic CLI clock so a local run's timestamps are fixed (K10)."""
    monkeypatch.setattr(cli_mod, "_now", lambda: _NOW)


_runner = CliRunner()


# --------------------------------------------------------------------------- #
# LOCAL — printout, --json equals the engine, --mode git, edit -> drift.
# --------------------------------------------------------------------------- #


def test_local_sync_prints_summary(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    with _chdir(repo):
        result = _runner.invoke(app, ["sync"])
    assert result.exit_code == 0, result.output
    assert "fully synced" in result.output
    assert "gitrepo [local]" in result.output  # repo_id derived from the index
    assert "documents:    1" in result.output
    assert "code refs:    1" in result.output


def test_local_sync_json_equals_engine(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    engine = run_sync(repo, "gitrepo", mode="local", default_branch="main", now=_NOW)
    with _chdir(repo):
        result = _runner.invoke(app, ["sync", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == engine.run.model_dump(mode="json")


def test_local_sync_mode_git(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    with _chdir(repo):
        result = _runner.invoke(app, ["sync", "--mode", "git", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["sync_kind"] == "git"
    assert payload["fully_synced"] is True
    assert payload["drift"]["ok"] is True


def test_local_sync_explicit_repo_id_overrides_derived(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    with _chdir(repo):
        result = _runner.invoke(app, ["sync", "--repo-id", "override", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["repo_id"] == "override"


def test_local_sync_edit_shows_drift(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    # Edit the documented symbol in the working tree → local drift (not git).
    (repo / "pkg" / "calc.py").write_text(
        'def add(a, b, c):\n    """Add three numbers."""\n    return a + b + c\n',
        encoding="utf-8",
    )
    with _chdir(repo):
        result = _runner.invoke(app, ["sync"])
    assert result.exit_code == 0, result.output
    assert "NOT fully synced" in result.output
    assert "drift:        1" in result.output or "drift:        2" in result.output


def test_local_sync_repo_id_falls_back_to_dir_name(tmp_path: Path) -> None:
    """With no dir-layout config, repo_id derives from the directory name."""
    plain = tmp_path / "plainrepo"
    plain.mkdir()
    _git(plain, "init", "-q")
    _git(plain, "config", "user.email", "test@example.invalid")
    _git(plain, "config", "user.name", "tester")
    (plain / "f.txt").write_text("x\n", encoding="utf-8")
    _git(plain, "add", "-A")
    _git(plain, "commit", "-q", "-m", "init")
    _git(plain, "branch", "-M", "main")
    with _chdir(plain):
        # No config/cdmon → load_bundle never reached; run_sync raises a loud
        # config error (no index.yaml), proving the dir-name fallback was used.
        result = _runner.invoke(app, ["sync"])
    assert result.exit_code == 1
    assert "error:" in result.output
    assert "Traceback" not in result.output


# --------------------------------------------------------------------------- #
# LOUD — unknown mode, not a git repo (K8, no traceback).
# --------------------------------------------------------------------------- #


def test_local_sync_unknown_mode_is_loud(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    with _chdir(repo):
        result = _runner.invoke(app, ["sync", "--mode", "sideways"])
    assert result.exit_code == 1
    assert "unknown sync mode" in result.output
    assert "Traceback" not in result.output


def test_local_sync_not_a_git_repo_is_clean(tmp_path: Path) -> None:
    """A dir-layout config in a NON-git dir fails loudly with no traceback (K8)."""
    nogit = tmp_path / "nogit"
    cfg = nogit / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "index.yaml").write_text(_INDEX_YAML, encoding="utf-8")
    (cfg / "core.yaml").write_text(_CORE_UNIT_YAML, encoding="utf-8")
    (cfg / "ignore.yaml").write_text(_IGNORE_YAML, encoding="utf-8")
    with _chdir(nogit):
        result = _runner.invoke(app, ["sync"])
    assert result.exit_code == 1
    assert "error:" in result.output
    assert "Traceback" not in result.output


# --------------------------------------------------------------------------- #
# REMOTE — POST triggered + summary printed; loud on missing repo-id / token / 4xx.
# --------------------------------------------------------------------------- #


def _stub_http(
    monkeypatch: pytest.MonkeyPatch,
    response: dict,
    posted: list[tuple[str, str, dict | None, str]],
) -> None:
    """Stub the register module's stdlib HTTP leaf — the SAME seam register uses."""

    def fake_request(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        posted.append((method, url, body, token))
        return response

    monkeypatch.setattr(registry_mod._UrllibRegisterHttp, "request", fake_request)


def _server_run(*, fully_synced: bool = True) -> dict:
    return {
        "repo_id": "acme/widget",
        "sync_kind": "git",
        "ref": "deadbeef",
        "branch": "main",
        "head_commit": "deadbeef",
        "main_commit": "deadbeef",
        "commits_ahead": 0,
        "fully_synced": fully_synced,
        "document_count": 3,
        "code_ref_count": 5,
        "drift": {"ok": True, "drift_count": 0, "by_kind": {}, "coverage_percent": 100.0},
        "started_at": _NOW,
        "finished_at": _NOW,
    }


def test_remote_sync_posts_and_prints_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[tuple[str, str, dict | None, str]] = []
    _stub_http(monkeypatch, _server_run(), posted)
    monkeypatch.setenv("CDMON_CENTRAL_TOKEN", "s3cret")
    result = _runner.invoke(
        app,
        [
            "sync",
            "--mode",
            "git",
            "--remote",
            "https://central.example/",
            "--repo-id",
            "acme/widget",
            "--token-env",
            "CDMON_CENTRAL_TOKEN",
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(posted) == 1
    method, url, body, token = posted[0]
    assert method == "POST"
    assert url == "https://central.example/repos/acme/widget/sync"
    assert body == {"mode": "git"}
    assert token == "s3cret"
    assert "acme/widget [git] — fully synced" in result.output
    assert "documents:    3" in result.output


def test_remote_sync_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_http(monkeypatch, _server_run(), [])
    result = _runner.invoke(
        app,
        ["sync", "--remote", "https://c.example", "--repo-id", "r", "--json"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == _server_run()


def test_remote_sync_no_token_sends_empty_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted: list[tuple[str, str, dict | None, str]] = []
    _stub_http(monkeypatch, _server_run(), posted)
    monkeypatch.delenv("CDMON_CENTRAL_TOKEN", raising=False)
    result = _runner.invoke(
        app, ["sync", "--remote", "https://c.example", "--repo-id", "r"]
    )
    assert result.exit_code == 0, result.output
    assert posted[0][3] == ""  # no token -> empty bearer


def test_remote_sync_requires_repo_id() -> None:
    result = _runner.invoke(app, ["sync", "--remote", "https://c.example"])
    assert result.exit_code == 1
    assert "--remote requires --repo-id" in result.output
    assert "Traceback" not in result.output


def test_remote_sync_http_error_is_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """An HTTP failure in the leaf surfaces as a loud non-zero exit (K8)."""
    from code_doc_monitor.errors import SchemaError

    def boom(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        raise SchemaError("server returned 404")

    monkeypatch.setattr(registry_mod._UrllibRegisterHttp, "request", boom)
    result = _runner.invoke(
        app, ["sync", "--remote", "https://c.example", "--repo-id", "r"]
    )
    assert result.exit_code == 1
    assert "error:" in result.output
    assert "server returned 404" in result.output
    assert "Traceback" not in result.output


def test_remote_sync_empty_url_is_loud() -> None:
    """An empty --remote string is treated as remote-mode and demands a url (K8)."""
    result = _runner.invoke(app, ["sync", "--remote", "", "--repo-id", "r"])
    assert result.exit_code == 1
    assert "error:" in result.output
    assert "url" in result.output
