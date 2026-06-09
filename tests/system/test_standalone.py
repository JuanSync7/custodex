"""L-01 — the per-repo STANDALONE app (``cdmon serve``) over a REAL temp git repo.

Builds a true on-disk dir-layout git repo (``git init`` / ``config/cdmon`` /
healed in-sync docs / commit on ``main``), then drives the import-safe builders:

* :func:`build_standalone_store` — exactly ONE repo registered, OPEN (no token),
  with ``local_path`` set and BOTH the git + local views pre-populated
  (``config_documents_for`` + ``latest_sync_run``);
* :func:`build_standalone_app` via :class:`TestClient` — ``GET /repos`` lists the
  one repo, ``GET /repos/{id}/documents?sync_kind=git`` returns the doc→code_refs
  tree, ``POST /repos/{id}/sync {mode:"local"}`` succeeds with NO Authorization
  header (the repo is OPEN), and ``GET /`` returns 200 (the landing JSON when no
  SPA is built).

Plus the graceful-skip path: a repo with NO ``main`` branch still builds (local
view populated, git skipped). The git side effect is REAL, and every test asserts
no stray ``git worktree`` is left behind (K1). The clock is injected (``now``) so
the persisted rows are deterministic (K10). Offline — no network.

Features: FEAT-CONFIGV2-001, FEAT-CONFIGV2-003, FEAT-CONFIGV2-008
Features: FEAT-CONFIGV2-012, FEAT-SERVER-001, FEAT-SERVER-004, FEAT-SERVER-009
Features: FEAT-SERVER-010, FEAT-SERVER-014, FEAT-SERVER-015
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")

from fastapi.testclient import TestClient  # noqa: E402

from code_doc_monitor.errors import CodeDocMonitorError  # noqa: E402
from code_doc_monitor.server.standalone import (  # noqa: E402
    build_standalone_app,
    build_standalone_store,
    resolve_repo_id,
)

_NOW = "2026-06-07T00:00:00Z"

# --------------------------------------------------------------------------- #
# A real dir-layout git repo (config/cdmon two levels under root), mirroring
# tests/test_configsync.py but with the index `repo` set to a known id.
# --------------------------------------------------------------------------- #

_INDEX_YAML = """\
---
cdmon-config-version: "2.0.0"
repo: standalone-repo
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
    """Heal the docs to a clean baseline via the real monitor pipeline."""
    from typer.testing import CliRunner

    from code_doc_monitor.cli import app

    result = CliRunner().invoke(
        app, ["monitor", "--config", str(config_dir), "--apply"]
    )
    assert result.exit_code == 0, result.output


def _scaffold(repo: Path) -> Path:
    """Write the dir-layout config + source + healed docs into ``repo``."""
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
    _seed_docs(cfg)  # heal docs/api.md to a clean baseline before committing
    return cfg


def _build_git_repo(tmp_path: Path) -> Path:
    """Build + commit a real dir-layout git repo on ``main``; return its root."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _scaffold(repo)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "tester")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    return repo


def _no_worktrees(repo: Path) -> None:
    """Assert the repo has exactly its main working tree — no leaked worktrees."""
    listed = _git(repo, "worktree", "list").strip().splitlines()
    assert len(listed) == 1, f"leftover worktrees: {listed!r}"


# --------------------------------------------------------------------------- #
# build_standalone_store — exactly one OPEN repo, both views pre-populated.
# --------------------------------------------------------------------------- #


def test_store_has_exactly_one_open_repo_with_local_path(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    store = build_standalone_store(repo, now=_NOW)

    repos = store.list_repos()
    assert len(repos) == 1
    (only,) = repos
    assert only.repo.repo_id == "standalone-repo"  # from the index `repo` field
    assert only.repo.local_path == str(repo)
    assert only.repo.default_branch == "main"
    # Registered OPEN — no token hash, so writes/sync need no bearer token.
    assert store.repo_token_hash("standalone-repo") is None
    _no_worktrees(repo)


def test_store_prepopulates_documents_and_sync_runs(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    store = build_standalone_store(repo, now=_NOW)

    # BOTH the git + local config views are pre-populated.
    git_docs = store.config_documents_for("standalone-repo", "git")
    local_docs = store.config_documents_for("standalone-repo", "local")
    assert [d.doc_id for d in git_docs] == ["api-guide"]
    assert [d.doc_id for d in local_docs] == ["api-guide"]
    assert git_docs[0].synced_at == _NOW  # the injected clock stamps the row (K10)

    # A latest sync run exists for each mode.
    git_run = store.latest_sync_run("standalone-repo", "git")
    local_run = store.latest_sync_run("standalone-repo", "local")
    assert git_run is not None and git_run.sync_kind == "git"
    assert local_run is not None and local_run.sync_kind == "local"
    assert git_run.fully_synced is True  # clean repo at main
    # The code_refs are attributed under the document.
    refs = store.code_refs_for("standalone-repo", sync_kind="git")
    assert [r.path for r in refs] == ["pkg/calc.py"]
    _no_worktrees(repo)


def test_explicit_repo_id_overrides_the_index(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    store = build_standalone_store(repo, repo_id="my/override", now=_NOW)
    assert [r.repo.repo_id for r in store.list_repos()] == ["my/override"]
    _no_worktrees(repo)


# --------------------------------------------------------------------------- #
# Graceful git skip: no `main` branch → local view still populated, git skipped.
# --------------------------------------------------------------------------- #


def test_no_main_branch_skips_git_but_keeps_local(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _scaffold(repo)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "tester")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    # Rename the default branch to something OTHER than `main` so git mode finds
    # no baseline and raises — which the builder must swallow.
    _git(repo, "branch", "-M", "feature")

    store = build_standalone_store(repo, now=_NOW)
    # local is populated; git is skipped (no rows, no run).
    assert store.config_documents_for("standalone-repo", "local")
    assert store.config_documents_for("standalone-repo", "git") == []
    assert store.latest_sync_run("standalone-repo", "git") is None
    assert store.latest_sync_run("standalone-repo", "local") is not None
    _no_worktrees(repo)


def test_local_config_error_is_loud(tmp_path: Path) -> None:
    """A repo with no readable config/cdmon/ raises out of the builder (K8)."""
    repo = tmp_path / "empty"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "tester")
    (repo / "readme.md").write_text("hi", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")

    with pytest.raises(CodeDocMonitorError):
        build_standalone_store(repo, now=_NOW)


# --------------------------------------------------------------------------- #
# resolve_repo_id — explicit > index `repo` > dir name.
# --------------------------------------------------------------------------- #


def test_resolve_repo_id_falls_back_to_dir_name(tmp_path: Path) -> None:
    plain = tmp_path / "just-a-dir"
    plain.mkdir()
    assert resolve_repo_id(plain, None) == "just-a-dir"


def test_resolve_repo_id_reads_index(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _scaffold(repo)
    assert resolve_repo_id(repo, None) == "standalone-repo"


def test_resolve_repo_id_explicit_wins(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _scaffold(repo)
    assert resolve_repo_id(repo, "x/y") == "x/y"


def test_resolve_repo_id_malformed_index_falls_back_to_dir_name(
    tmp_path: Path,
) -> None:
    """A present-but-malformed index.yaml falls back to the dir name (robust K8)."""
    repo = tmp_path / "broken-repo"
    cfg = repo / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "index.yaml").write_text("not: valid: yaml: at: all\n", encoding="utf-8")
    assert resolve_repo_id(repo, None) == "broken-repo"


# --------------------------------------------------------------------------- #
# build_standalone_app — the e2e HTTP surface over a TestClient (no socket).
# --------------------------------------------------------------------------- #


def test_app_lists_one_repo(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    app_obj = build_standalone_app(repo, now=_NOW)
    with TestClient(app_obj) as client:
        repos = client.get("/repos").json()
        assert [r["repo"]["repo_id"] for r in repos] == ["standalone-repo"]
    _no_worktrees(repo)


def test_app_documents_git_tree(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    app_obj = build_standalone_app(repo, now=_NOW)
    with TestClient(app_obj) as client:
        trees = client.get(
            "/repos/standalone-repo/documents", params={"sync_kind": "git"}
        ).json()
    assert len(trees) == 1
    (tree,) = trees
    assert tree["document"]["doc_id"] == "api-guide"
    assert [c["path"] for c in tree["code_refs"]] == ["pkg/calc.py"]
    _no_worktrees(repo)


def test_app_sync_without_authorization_header_succeeds(tmp_path: Path) -> None:
    """The OPEN repo accepts POST /sync with NO Authorization header (L-01)."""
    repo = _build_git_repo(tmp_path)
    app_obj = build_standalone_app(repo, now=_NOW)
    with TestClient(app_obj) as client:
        resp = client.post("/repos/standalone-repo/sync", json={"mode": "local"})
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["sync_kind"] == "local"
    assert run["fully_synced"] is True
    _no_worktrees(repo)


def test_app_root_returns_200(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    app_obj = build_standalone_app(repo, now=_NOW)
    with TestClient(app_obj) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    _no_worktrees(repo)
