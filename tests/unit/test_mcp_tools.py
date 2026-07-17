"""Unit tests for ``custodex.mcp.tools`` — the pure MCP projection logic (MCP-00).

These import ONLY the pure ``tools`` layer (no ``mcp`` SDK), proving the
boundary: the status projection + config resolution test even in a core-only
install. Covers the clean and code↔doc-drift status folds, both
``load_repo_bundle`` layouts + the loud no-config path, and ``resolve_repo_id``.

Features: FEAT-MCP-001
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custodex.blocks import symbol_table
from custodex.config import (
    Audience,
    CodeRef,
    DocDepsConfig,
    DocEdge,
    DocumentSpec,
    MonitorConfig,
    write_template,
)
from custodex.docdeps import stamp_edges
from custodex.errors import McpError
from custodex.extract import build_document_surface
from custodex.manifest import render_doc, set_fingerprint, set_region
from custodex.mcp.tools import (
    StatusSummary,
    load_repo_bundle,
    resolve_repo_id,
    status_summary,
)
from custodex.templates_v2 import scaffold_config_dir

CODE_V1 = '''\
def greet(name: str) -> str:
    """Say hello."""
    return f"hi {name}"
'''

# The public signature changed (a new parameter) → the symbol region + the
# surface fingerprint both drift (an eng-guide surface change, K3).
CODE_V2 = '''\
def greet(name: str, loud: bool) -> str:
    """Say hello."""
    return f"hi {name}"
'''


def _synced_repo(tmp_path: Path) -> MonitorConfig:
    """A one-doc repo whose region + fingerprint match CODE_V1 (in sync)."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "src" / "mod.py").write_text(CODE_V1, encoding="utf-8")
    spec = DocumentSpec(
        id="api",
        path="docs/api.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols",),
    )
    surface = build_document_surface(spec, root)
    body = "# API\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    body, _ = set_region(body, "symbols", symbol_table(surface))
    meta = set_fingerprint({}, surface.surface_hash())
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")
    return MonitorConfig(root="repo", documents=(spec,))


def test_status_summary_clean(tmp_path: Path) -> None:
    cfg = _synced_repo(tmp_path)
    summary = status_summary(cfg, tmp_path, repo_id="demo")
    assert isinstance(summary, StatusSummary)
    assert summary.repo_id == "demo"
    assert summary.clean is True
    assert summary.drift_total == 0
    assert summary.code_doc_drift == 0
    assert summary.suspect_link_drift == 0
    assert summary.doc_count == 1
    assert "clean" in summary.summary.lower()


def test_status_summary_flags_code_doc_drift(tmp_path: Path) -> None:
    cfg = _synced_repo(tmp_path)
    # Mutate the public signature → the doc's symbol region + fingerprint drift.
    (tmp_path / "repo" / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    summary = status_summary(cfg, tmp_path, repo_id="demo")
    assert summary.clean is False
    assert summary.drift_total >= 1
    assert summary.code_doc_drift >= 1
    assert summary.suspect_link_drift == 0
    # The counts partition the total (no double-counting).
    assert summary.code_doc_drift + summary.suspect_link_drift == summary.drift_total


def test_status_summary_counts_suspect_link_drift(tmp_path: Path) -> None:
    # A doc↔doc edge (api depends_on overview) goes SUSPECT when the upstream body
    # moves — exercises the code↔doc vs doc↔doc split with suspect_link_drift != 0
    # (so a one-sided miscount of the split can't survive; the code↔doc side is
    # covered by test_status_summary_flags_code_doc_drift).
    overview = DocumentSpec(
        id="overview", path="overview.md", audience=Audience.ENG_GUIDE
    )
    api = DocumentSpec(
        id="api",
        path="api.md",
        audience=Audience.USER_GUIDE,
        depends_on=(DocEdge(doc="overview"),),
    )
    cfg = MonitorConfig(
        root=".", documents=(overview, api), docdeps=DocDepsConfig(enabled=True)
    )

    def _managed(spec: DocumentSpec, body: str) -> None:
        surface = build_document_surface(spec, tmp_path)
        meta = set_fingerprint({}, surface.surface_hash())
        (tmp_path / spec.path).write_text(render_doc(meta, body), encoding="utf-8")

    _managed(overview, "# Overview\nupstream\n")
    _managed(api, "# API\ndownstream\n")
    stamp_edges(cfg, tmp_path, "api")  # baseline the edge → starts OK
    assert status_summary(cfg, tmp_path, repo_id="demo").clean is True

    _managed(overview, "# Overview\nUPSTREAM MOVED\n")  # move the upstream body
    summary = status_summary(cfg, tmp_path, repo_id="demo")
    assert summary.clean is False
    assert summary.suspect_link_drift >= 1
    assert summary.code_doc_drift == 0  # the ONLY drift is the doc↔doc suspect link
    assert summary.code_doc_drift + summary.suspect_link_drift == summary.drift_total


def test_load_repo_bundle_single_file(tmp_path: Path) -> None:
    write_template(tmp_path / "cdmon.yaml")
    cfg, config_dir = load_repo_bundle(tmp_path)
    assert isinstance(cfg, MonitorConfig)
    assert config_dir == tmp_path


def test_load_repo_bundle_dir_layout(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "cdmon"
    scaffold_config_dir(config_dir, repo="demo", now="2026-01-01T00:00:00+00:00")
    cfg, resolved_dir = load_repo_bundle(tmp_path)
    assert isinstance(cfg, MonitorConfig)
    assert resolved_dir == config_dir


def test_load_repo_bundle_no_config_is_loud(tmp_path: Path) -> None:
    with pytest.raises(McpError):
        load_repo_bundle(tmp_path)


def test_resolve_repo_id_from_index(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "cdmon"
    scaffold_config_dir(config_dir, repo="widget", now="2026-01-01T00:00:00+00:00")
    assert resolve_repo_id(tmp_path, config_dir) == "widget"


def test_resolve_repo_id_falls_back_to_dir_name(tmp_path: Path) -> None:
    # No index.yaml under config_dir → the repo directory name is the safe id.
    assert resolve_repo_id(tmp_path, tmp_path) == tmp_path.name


def test_resolve_repo_id_falls_back_when_bundle_load_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An index.yaml is present but the bundle fails to load → the dir name is the
    # safe id (the status detect step surfaces the real config error loudly, K8).
    import custodex.mcp.tools as tools_mod

    config_dir = tmp_path / "config" / "cdmon"
    config_dir.mkdir(parents=True)
    (config_dir / "index.yaml").write_text("repo: broken\n", encoding="utf-8")

    def _boom(_dir: Path) -> object:
        from custodex.errors import ConfigError

        raise ConfigError("malformed bundle")

    monkeypatch.setattr(tools_mod, "load_bundle", _boom)
    assert resolve_repo_id(tmp_path, config_dir) == tmp_path.name
