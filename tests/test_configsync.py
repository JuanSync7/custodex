"""Y-02 — the config-sync engine over a REAL temp git repo (offline, K1/K8/K10).

Every test builds a true on-disk git repo (``git init`` / config / commit) with a
``config/cdmon/`` dir layout + source + healed docs, then drives
:func:`code_doc_monitor.configsync.run_sync` in both modes:

* clean repo → ``fully_synced`` True, correct counts + attribution;
* a working-tree edit → ``local`` drift non-empty while ``git`` (the default
  branch) stays clean — the central baseline is unaffected by uncommitted work;
* a feature-branch COMMIT → ``commits_ahead >= 1``.

The git side effect is REAL (the default subprocess leaf is exercised), and a
final assertion proves no stray ``git worktree`` is left behind (K1). The clock
is injected (``now``) so the persisted rows are deterministic (K10).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from code_doc_monitor.configsync import read_config_at, run_sync
from code_doc_monitor.errors import SyncError

_NOW = "2026-06-07T00:00:00Z"

# --------------------------------------------------------------------------- #
# A real dir-layout repo (config/cdmon two levels under root) — same shape as
# tests/test_dirlayout_e2e.py, but committed into a real git repo.
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
    """Heal the docs to a clean baseline via the real monitor pipeline."""
    from typer.testing import CliRunner

    from code_doc_monitor.cli import app

    result = CliRunner().invoke(
        app, ["monitor", "--config", str(config_dir), "--apply"]
    )
    assert result.exit_code == 0, result.output


def _build_git_repo(tmp_path: Path) -> Path:
    """Build + commit a real dir-layout git repo on ``main``; return its root."""
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
    _seed_docs(cfg)  # heal docs/api.md before the first commit (clean baseline)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    return repo


def _no_worktrees(repo: Path) -> None:
    """Assert the repo has exactly its main working tree — no leaked worktrees."""
    listed = _git(repo, "worktree", "list").strip().splitlines()
    assert len(listed) == 1, f"leftover worktrees: {listed!r}"


# --------------------------------------------------------------------------- #
# Clean repo → fully_synced in both modes, correct counts + attribution.
# --------------------------------------------------------------------------- #


def test_clean_repo_git_mode_fully_synced(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    result = run_sync(repo, "gitrepo", mode="git", default_branch="main", now=_NOW)
    run = result.run
    assert run.fully_synced is True
    assert run.sync_kind == "git"
    assert run.document_count == 1
    assert run.code_ref_count == 1
    assert run.commits_ahead == 0
    assert run.drift["ok"] is True
    assert run.drift["drift_count"] == 0
    assert run.drift["coverage_percent"] == 100.0
    assert run.started_at == _NOW and run.finished_at == _NOW
    _no_worktrees(repo)


def test_clean_repo_local_mode_fully_synced(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    result = run_sync(repo, "gitrepo", mode="local", default_branch="main", now=_NOW)
    assert result.run.fully_synced is True
    assert result.run.sync_kind == "local"
    assert result.run.commits_ahead == 0
    _no_worktrees(repo)


def test_attribution_unit_sync_kind_ref(tmp_path: Path) -> None:
    """Documents/code_refs carry unit, sync_kind=mode, ref=commit, synced_at."""
    repo = _build_git_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD").strip()
    result = run_sync(repo, "gitrepo", mode="git", default_branch="main", now=_NOW)

    (doc,) = result.documents
    assert doc.doc_id == "api-guide"
    assert doc.unit == "core"
    assert doc.audience == "eng-guide"
    assert doc.region_keys == ("symbols",)
    assert doc.sync_kind == "git"
    assert doc.ref == head  # git mode pins the default-branch tip
    assert doc.synced_at == _NOW

    (ref,) = result.code_refs
    assert ref.doc_id == "api-guide"
    assert ref.path == "pkg/calc.py"
    assert ref.symbols == ("add",)
    assert ref.unit == "core"
    assert ref.sync_kind == "git"


def test_local_ref_is_working_tree_head(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD").strip()
    result = run_sync(repo, "gitrepo", mode="local", default_branch="main", now=_NOW)
    assert result.run.ref == head
    assert result.run.head_commit == head
    assert result.documents[0].ref == head


# --------------------------------------------------------------------------- #
# A working-tree edit → local drift, git(main) still clean.
# --------------------------------------------------------------------------- #


def test_working_tree_edit_local_drifts_git_clean(tmp_path: Path) -> None:
    """An uncommitted symbol edit drifts the local view but NOT the main baseline."""
    repo = _build_git_repo(tmp_path)
    # Edit the COVERED symbol's signature in the working tree only (not committed)
    # so the documented surface for `add` moves → eng-guide HASH drift.
    (repo / "pkg" / "calc.py").write_text(
        'def add(a, b, c):\n    """Add three numbers."""\n    return a + b + c\n',
        encoding="utf-8",
    )
    local = run_sync(repo, "gitrepo", mode="local", default_branch="main", now=_NOW)
    git = run_sync(repo, "gitrepo", mode="git", default_branch="main", now=_NOW)

    assert local.run.fully_synced is False
    assert local.run.drift["ok"] is False
    assert local.run.drift["drift_count"] >= 1
    # git mode reads the COMMITTED main content, which is still in sync.
    assert git.run.fully_synced is True
    assert git.run.drift["ok"] is True
    _no_worktrees(repo)


# --------------------------------------------------------------------------- #
# A feature-branch commit → commits_ahead >= 1.
# --------------------------------------------------------------------------- #


def test_feature_branch_commit_reports_commits_ahead(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "pkg" / "calc.py").write_text(
        _CALC_V1 + "\n\ndef sub(a, b):\n    return a - b\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add sub")

    local = run_sync(repo, "gitrepo", mode="local", default_branch="main", now=_NOW)
    assert local.run.commits_ahead == 1
    assert local.run.branch == "feature"
    # git mode still reads main → no drift there, ahead is reported for context.
    git = run_sync(repo, "gitrepo", mode="git", default_branch="main", now=_NOW)
    assert git.run.fully_synced is True
    assert git.run.commits_ahead == 1
    assert git.run.main_commit is not None
    _no_worktrees(repo)


def test_no_default_branch_zero_commits_ahead(tmp_path: Path) -> None:
    """A repo whose default branch is absent reports commits_ahead 0 (no baseline)."""
    repo = _build_git_repo(tmp_path)
    # Rename main away so 'main' no longer exists.
    _git(repo, "branch", "-m", "main", "trunk")
    result = run_sync(repo, "gitrepo", mode="local", default_branch="main", now=_NOW)
    assert result.run.commits_ahead == 0
    assert result.run.main_commit is None


# --------------------------------------------------------------------------- #
# Loud failures (K8).
# --------------------------------------------------------------------------- #


def test_unknown_mode_is_sync_error(tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    with pytest.raises(SyncError, match="unknown sync mode"):
        run_sync(repo, "gitrepo", mode="weird", default_branch="main", now=_NOW)


def test_missing_local_path_is_sync_error(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(SyncError, match="does not exist"):
        run_sync(missing, "gitrepo", mode="local", default_branch="main", now=_NOW)


def test_git_failure_is_sync_error_no_leak(tmp_path: Path) -> None:
    """A non-git directory makes the first rev-parse fail loudly (K8)."""
    plain = tmp_path / "plain"
    (plain / "config" / "cdmon").mkdir(parents=True)
    with pytest.raises(SyncError):
        run_sync(plain, "gitrepo", mode="git", default_branch="main", now=_NOW)


def test_read_config_at_git_mode_cleans_up(tmp_path: Path) -> None:
    """The public read_config_at façade tears its git worktree down on return."""
    repo = _build_git_repo(tmp_path)
    bundle, config_dir, git = read_config_at(repo, mode="git", branch="main", now=_NOW)
    assert bundle.config.documents[0].id == "api-guide"
    assert git.ref == git.main_commit
    _no_worktrees(repo)


# --------------------------------------------------------------------------- #
# Subdir-awareness (M-02): config/cdmon under a SUBDIR of the git toplevel.
# --------------------------------------------------------------------------- #


def _build_git_repo_in_subdir(tmp_path: Path) -> tuple[Path, Path]:
    """Build a dir-layout repo INSIDE ``<top>/sub`` of a fresh git repo on ``main``.

    The config thus lives at ``sub/config/cdmon`` — two levels under the git
    toplevel — so git-mode sync must resolve ``rel = "sub"`` and read the config
    from ``<worktree>/sub/config/cdmon``. Returns ``(toplevel, sub)``.
    """
    top = tmp_path / "outer"
    sub = top / "sub"
    cfg = sub / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "index.yaml").write_text(_INDEX_YAML, encoding="utf-8")
    (cfg / "core.yaml").write_text(_CORE_UNIT_YAML, encoding="utf-8")
    (cfg / "ignore.yaml").write_text(_IGNORE_YAML, encoding="utf-8")
    pkg = sub / "pkg"
    pkg.mkdir()
    (pkg / "calc.py").write_text(_CALC_V1, encoding="utf-8")
    docs = sub / "docs"
    docs.mkdir()
    (docs / "api.md").write_text(_DOC_STUB, encoding="utf-8")

    _git(top, "init", "-q")
    _git(top, "config", "user.email", "test@example.invalid")
    _git(top, "config", "user.name", "tester")
    _seed_docs(cfg)  # heal sub/docs/api.md before committing (clean baseline)
    _git(top, "add", "-A")
    _git(top, "commit", "-q", "-m", "init")
    _git(top, "branch", "-M", "main")
    return top, sub


def test_git_mode_reads_config_under_subdir(tmp_path: Path) -> None:
    """Git-mode sync reads config from a SUBDIR of the git toplevel (M-02 #1)."""
    top, sub = _build_git_repo_in_subdir(tmp_path)
    result = run_sync(sub, "gitrepo", mode="git", default_branch="main", now=_NOW)
    run = result.run
    assert run.fully_synced is True
    assert run.document_count == 1
    assert run.code_ref_count == 1
    assert run.commits_ahead == 0
    assert result.documents[0].doc_id == "api-guide"
    assert result.code_refs[0].path == "pkg/calc.py"
    _no_worktrees(top)


def test_git_mode_subdir_no_leftover_worktree(tmp_path: Path) -> None:
    top, sub = _build_git_repo_in_subdir(tmp_path)
    run_sync(sub, "gitrepo", mode="git", default_branch="main", now=_NOW)
    run_sync(sub, "gitrepo", mode="git", default_branch="main", now=_NOW)
    _no_worktrees(top)


def test_git_mode_subdir_missing_config_on_branch_is_loud(tmp_path: Path) -> None:
    """A subdir whose config/cdmon is absent on the default branch is a loud K8."""
    top = tmp_path / "outer"
    top.mkdir()
    (top / "readme.md").write_text("hi\n", encoding="utf-8")
    _git(top, "init", "-q")
    _git(top, "config", "user.email", "test@example.invalid")
    _git(top, "config", "user.name", "tester")
    _git(top, "add", "-A")
    _git(top, "commit", "-q", "-m", "init")
    _git(top, "branch", "-M", "main")
    # The subdir exists in the WORKING TREE only, never committed to main.
    sub = top / "sub"
    (sub / "config" / "cdmon").mkdir(parents=True)
    with pytest.raises(SyncError, match="config/cdmon"):
        run_sync(sub, "gitrepo", mode="git", default_branch="main", now=_NOW)
    _no_worktrees(top)
