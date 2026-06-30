"""EPIC B (B-05): the ``cdx deps`` / ``cdx resolve --edge`` CLI + the check gate.

Drives the doc↔doc commands over a self-contained single-file config: ``cdx deps``
shows the dependency graph + suspect status, ``cdx deps --suggest`` infers edges
from Markdown cross-links (the low-tedium authoring aid), ``cdx resolve --edge``
re-stamps exactly one edge (the Doorstop ``clear`` analogue), and ``cdx check``'s
exit honours ``docdeps.gate``. Offline, no backend, no network (K4).

Features: FEAT-DOCDEPS-005
"""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from custodex.cli import app
from custodex.config import load_config
from custodex.extract import build_document_surface
from custodex.manifest import render_doc, set_fingerprint

runner = CliRunner()

_DOCS = [
    {"id": "overview", "path": "docs/overview.md", "audience": "eng-guide"},
    {
        "id": "api",
        "path": "docs/api.md",
        "audience": "eng-guide",
        "depends_on": [{"doc": "overview"}],
    },
]


def _setup(tmp_path: Path, *, gate: bool = True, api_body: str | None = None) -> Path:
    """Write a single-file config + two code↔doc-clean docs; return the config path."""
    cfg = {"version": "1.0.0", "root": ".", "documents": _DOCS}
    if not gate:
        cfg["docdeps"] = {"gate": False}
    cfg_path = tmp_path / "cdmon.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (tmp_path / "docs").mkdir(exist_ok=True)
    loaded = load_config(cfg_path)
    bodies = {
        "overview": "# Overview\nupstream content\n",
        "api": api_body or "# API\ndownstream content\n",
    }
    for spec in loaded.documents:
        surface = build_document_surface(spec, tmp_path)
        meta = set_fingerprint({}, surface.surface_hash())
        (tmp_path / spec.path).write_text(
            render_doc(meta, bodies[spec.id]), encoding="utf-8"
        )
    return cfg_path


def test_deps_lists_unstamped_edge(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    res = runner.invoke(app, ["deps", "--config", str(cfg)])
    assert res.exit_code == 0
    assert "api" in res.stdout and "overview" in res.stdout
    assert "unstamped" in res.stdout


def test_resolve_edge_stamps_then_clean(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    # check is gating on the unstamped edge -> exit 1
    assert runner.invoke(app, ["check", "--config", str(cfg)]).exit_code == 1
    # resolve the one edge -> baseline stamped
    res = runner.invoke(
        app, ["resolve", "--edge", "api", "overview", "--config", str(cfg)]
    )
    assert res.exit_code == 0
    assert "api" in res.stdout and "overview" in res.stdout
    # now clean
    assert runner.invoke(app, ["check", "--config", str(cfg)]).exit_code == 0
    deps = runner.invoke(app, ["deps", "--suspect", "--config", str(cfg)])
    assert "need review" in deps.stdout and "0 edge" in deps.stdout


def test_upstream_change_makes_check_fail(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    runner.invoke(app, ["resolve", "--edge", "api", "overview", "--config", str(cfg)])
    # edit the upstream body
    (tmp_path / "docs" / "overview.md").write_text(
        "# Overview\nUPSTREAM CHANGED\n", encoding="utf-8"
    )
    res = runner.invoke(app, ["check", "--config", str(cfg)])
    assert res.exit_code == 1
    assert "SUSPECT_LINK" in res.stdout


def test_gate_false_does_not_fail_check(tmp_path: Path) -> None:
    """With docdeps.gate=False a suspect link is advisory — check still exits 0."""
    cfg = _setup(tmp_path, gate=False)
    res = runner.invoke(app, ["check", "--config", str(cfg)])
    assert res.exit_code == 0  # unstamped edge present but non-gating
    # ...yet it is still REPORTED, so the user can see it.
    assert "SUSPECT_LINK" in res.stdout


def test_resolve_unknown_edge_is_loud(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    res = runner.invoke(
        app, ["resolve", "--edge", "api", "ghost", "--config", str(cfg)]
    )
    assert res.exit_code != 0
    assert "ghost" in res.stdout or "ghost" in (res.stderr or "")


# --- B-10: `cdx deps --impact` (the proactive blast radius) -----------------
# Feature: FEAT-DOCDEPS-009


def test_deps_impact_shows_dependents(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    res = runner.invoke(app, ["deps", "--impact", "overview", "--config", str(cfg)])
    assert res.exit_code == 0
    assert "api" in res.stdout
    assert "depend on" in res.stdout


def test_deps_impact_leaf_is_safe(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    res = runner.invoke(app, ["deps", "--impact", "api", "--config", str(cfg)])
    assert res.exit_code == 0
    assert "safe to change" in res.stdout


def test_deps_impact_unknown_doc_is_loud(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    res = runner.invoke(app, ["deps", "--impact", "ghost", "--config", str(cfg)])
    assert res.exit_code != 0
    assert "ghost" in res.stdout or "ghost" in (res.stderr or "")


def test_deps_impact_json(tmp_path: Path) -> None:
    import json

    cfg = _setup(tmp_path)
    res = runner.invoke(
        app, ["deps", "--impact", "overview", "--json", "--config", str(cfg)]
    )
    assert res.exit_code == 0
    assert json.loads(res.stdout) == {"impacted": ["api"], "upstream": "overview"}


# --- PROP-01: `cdx deps --transitive` (the eager advisory) ------------------
# Feature: FEAT-DOCDEPS-010

_CHAIN_DOCS = [
    {"id": "leaf", "path": "docs/leaf.md", "audience": "eng-guide"},
    {
        "id": "mid",
        "path": "docs/mid.md",
        "audience": "eng-guide",
        "depends_on": [{"doc": "leaf"}],
    },
    {
        "id": "top",
        "path": "docs/top.md",
        "audience": "eng-guide",
        "depends_on": [{"doc": "mid"}],
    },
]


def _setup_chain(tmp_path: Path) -> Path:
    """top → mid → leaf, each code↔doc-clean; return the config path."""
    cfg = {"version": "1.0.0", "root": ".", "documents": _CHAIN_DOCS}
    cfg_path = tmp_path / "cdmon.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (tmp_path / "docs").mkdir(exist_ok=True)
    loaded = load_config(cfg_path)
    bodies = {"leaf": "# Leaf\nbase\n", "mid": "# Mid\nm\n", "top": "# Top\nt\n"}
    for spec in loaded.documents:
        surface = build_document_surface(spec, tmp_path)
        meta = set_fingerprint({}, surface.surface_hash())
        (tmp_path / spec.path).write_text(
            render_doc(meta, bodies[spec.id]), encoding="utf-8"
        )
    return cfg_path


def _stamp_chain(tmp_path: Path, cfg: Path) -> None:
    runner.invoke(app, ["resolve", "--edge", "mid", "leaf", "--config", str(cfg)])
    runner.invoke(app, ["resolve", "--edge", "top", "mid", "--config", str(cfg)])


def test_deps_transitive_advisory_lists_pending_downstream(tmp_path: Path) -> None:
    cfg = _setup_chain(tmp_path)
    _stamp_chain(tmp_path, cfg)
    assert runner.invoke(app, ["check", "--config", str(cfg)]).exit_code == 0
    # Change the leaf body: mid goes DIRECTLY suspect; top is only TRANSITIVELY
    # pending (mid's body is unchanged, so top's own edge is still OK).
    (tmp_path / "docs" / "leaf.md").write_text(
        "# Leaf\nLEAF CHANGED\n", encoding="utf-8"
    )
    res = runner.invoke(app, ["deps", "--transitive", "--config", str(cfg)])
    assert res.exit_code == 0
    assert "mid" in res.stdout and "leaf" in res.stdout  # direct
    assert "top" in res.stdout and "does NOT gate" in res.stdout  # advisory


def test_check_still_gates_only_on_direct_suspect(tmp_path: Path) -> None:
    """The advisory never changes the gate — only the DIRECT suspect fails check."""
    cfg = _setup_chain(tmp_path)
    _stamp_chain(tmp_path, cfg)
    (tmp_path / "docs" / "leaf.md").write_text(
        "# Leaf\nLEAF CHANGED\n", encoding="utf-8"
    )
    res = runner.invoke(app, ["check", "--config", str(cfg)])
    assert res.exit_code == 1
    assert "SUSPECT_LINK" in res.stdout
    # top is pending only transitively — it is NOT minted as a drift line.
    assert "top:" not in res.stdout


def test_deps_transitive_json_is_opt_in_shape(tmp_path: Path) -> None:
    import json

    cfg = _setup_chain(tmp_path)
    _stamp_chain(tmp_path, cfg)
    (tmp_path / "docs" / "leaf.md").write_text(
        "# Leaf\nLEAF CHANGED\n", encoding="utf-8"
    )
    res = runner.invoke(app, ["deps", "--transitive", "--json", "--config", str(cfg)])
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert set(payload) == {"edges", "transitive"}
    assert any(t["doc_id"] == "top" for t in payload["transitive"])
    # plain `--json` keeps the back-compat bare-list contract (K6)
    plain = json.loads(
        runner.invoke(app, ["deps", "--json", "--config", str(cfg)]).stdout
    )
    assert isinstance(plain, list)


def test_deps_suggest_infers_from_markdown_link(tmp_path: Path) -> None:
    # api body links to overview.md but does NOT declare the edge yet... use a doc
    # whose only relation is the inline link, then drop the declared edge.
    cfg_dict = {
        "version": "1.0.0",
        "root": ".",
        "documents": [
            {"id": "overview", "path": "docs/overview.md", "audience": "eng-guide"},
            {"id": "api", "path": "docs/api.md", "audience": "eng-guide"},
        ],
    }
    cfg_path = tmp_path / "cdmon.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg_dict), encoding="utf-8")
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "overview.md").write_text("# Overview\n", encoding="utf-8")
    (tmp_path / "docs" / "api.md").write_text(
        "# API\n\nSee the [overview](overview.md).\n", encoding="utf-8"
    )
    res = runner.invoke(app, ["deps", "--suggest", "--config", str(cfg_path)])
    assert res.exit_code == 0
    assert "api" in res.stdout and "overview" in res.stdout
    # paste-ready: mentions depends_on so a user can copy it into config
    assert "depends_on" in res.stdout
