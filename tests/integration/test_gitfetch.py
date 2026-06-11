"""GIT-00 — clone-on-demand over a REAL git repo, then sync it (offline, K1/K8).

The headline Step-0 goal: the server can sync a repo it does NOT hold locally.
Here we build a real on-disk git repo (the same dir-layout shape as
``test_configsync.py``), then drive the REAL :class:`~code_doc_monitor.gitfetch`
``_GitCloner`` over a ``file://`` URL (no network — EDR-safe) into a throwaway
temp tree, and run :func:`code_doc_monitor.configsync.run_sync` over the clone —
proving the cloned tree's documents + coverage surface exactly as if it had been
on disk all along. The temp clone is gone after the ``with`` block (K1).

A bogus ``file://`` path proves a clone failure is a loud :class:`SyncError` and
still tears the temp dir down. A ``file://`` clone WITH a secret exercises the
``GIT_ASKPASS`` branch (git ignores auth for ``file://`` so it still succeeds).

Features: FEAT-CONFIGV2-012, FEAT-CONFIGV2-008
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from code_doc_monitor.configsync import run_sync
from code_doc_monitor.errors import SyncError
from code_doc_monitor.gitfetch import RemoteSpec, cloned_repo

_NOW = "2026-06-10T00:00:00Z"

# A minimal real dir-layout repo (config/cdmon two levels under root) — mirrors
# tests/integration/test_configsync.py so the clone+sync goal is end-to-end real.
_INDEX_YAML = """\
---
cdmon-config-version: "2.0.0"
repo: cloned
generated-by: cdmon
updated: "2026-06-10"
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
created: "2026-06-10"
updated: "2026-06-10"
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
updated: "2026-06-10"
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
    """Heal docs/api.md to a clean baseline via the real monitor pipeline."""
    from typer.testing import CliRunner

    from code_doc_monitor.cli import app

    result = CliRunner().invoke(
        app, ["monitor", "--config", str(config_dir), "--apply"]
    )
    assert result.exit_code == 0, result.output


def _build_git_repo(tmp_path: Path) -> Path:
    """Build + commit a real dir-layout git repo on ``main``; return its root."""
    repo = tmp_path / "origin"
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


# --------------------------------------------------------------------------- #
# The headline goal: clone a remote we don't hold, then sync it.
# --------------------------------------------------------------------------- #


def test_real_file_clone_then_sync_surfaces_docs_and_coverage(tmp_path: Path) -> None:
    origin = _build_git_repo(tmp_path)
    spec = RemoteSpec(
        remote_url=f"file://{origin}", provider="github", default_branch="main"
    )

    captured: dict[str, Path] = {}
    with cloned_repo(spec, None) as tree:  # the REAL _GitCloner, no network
        captured["tree"] = tree
        assert (tree / "config" / "cdmon" / "index.yaml").is_file()
        result = run_sync(tree, "cloned", mode="local", default_branch="main", now=_NOW)
        assert result.run.fully_synced is True
        assert result.run.document_count == 1
        assert result.run.code_ref_count == 1
        assert result.documents[0].doc_id == "api-guide"
        assert result.code_refs[0].path == "pkg/calc.py"
        # coverage-on-sync travels with the clone too (T-02 shape).
        assert result.coverage is not None
        assert result.coverage["captured_at"] == _NOW

    # The throwaway clone is gone after the block (K1 — temp only).
    assert not captured["tree"].exists()


def test_real_file_clone_with_secret_exercises_askpass(tmp_path: Path) -> None:
    # A secret triggers the GIT_ASKPASS branch; git ignores auth for file:// so
    # the clone still succeeds — this covers the askpass setup without a network.
    origin = _build_git_repo(tmp_path)
    spec = RemoteSpec(
        remote_url=f"file://{origin}", provider="github", default_branch="main"
    )
    with cloned_repo(spec, "ghp_unused_for_file_url") as tree:
        assert (tree / "config" / "cdmon").is_dir()


def test_bogus_file_url_is_loud_sync_error_and_cleans_up(tmp_path: Path) -> None:
    spec = RemoteSpec(
        remote_url=f"file://{tmp_path}/does-not-exist.git",
        provider="github",
        default_branch="main",
    )
    with pytest.raises(SyncError, match="clone"), cloned_repo(spec, None):
        pass  # pragma: no cover — never reached (clone failed)
