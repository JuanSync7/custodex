"""AGT-03 — the ``cdx graph`` CLI end to end (summary/focus/rank/json/write).

Offline, no backend, no network (K1/K4); the only write is the regenerable
``.cdmon/graph.json`` artifact behind ``--write`` (idempotent, K7).

Features: FEAT-KGRAPH-001, FEAT-KGRAPH-002
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from custodex.cli import app

runner = CliRunner()


def _setup(tmp_path: Path) -> Path:
    (tmp_path / "alpha.py").write_text(
        'def solve_widget(x):\n    """Doc."""\n    return x\n', encoding="utf-8"
    )
    (tmp_path / "beta.py").write_text("def hot_gap(y):\n    return y\n", "utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(
        "# Guide\n\nCall `hot_gap` twice: `hot_gap`. See [api](api.md).\n",
        encoding="utf-8",
    )
    (docs / "api.md").write_text("# API\n\nReference.\n", encoding="utf-8")
    cfg = {
        "version": "1.0.0",
        "root": ".",
        "coverage": {"include": ["**/*.py"], "exclude": []},
        "documents": [
            {"id": "guide", "path": "docs/guide.md", "audience": "eng-guide"},
            {
                "id": "api",
                "path": "docs/api.md",
                "audience": "eng-guide",
                "code_refs": [{"path": "alpha.py"}],
            },
        ],
    }
    path = tmp_path / "cdmon.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_graph_summary_view(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    result = runner.invoke(app, ["graph", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "Knowledge graph" in result.output
    assert "documents=" in result.output and "mentions=" in result.output


def test_graph_focus_view_and_loud_unknown(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    result = runner.invoke(
        app, ["graph", "--focus", "doc docs/api.md", "--config", str(cfg)]
    )
    assert result.exit_code == 0
    assert "doc docs/api.md" in result.output
    result = runner.invoke(app, ["graph", "--focus", "ghost", "--config", str(cfg)])
    assert result.exit_code == 1 and "error:" in result.output


def test_graph_rank_surfaces_undocumented_gap(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    result = runner.invoke(app, ["graph", "--rank", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "symbol beta.py#hot_gap" in result.output
    ranked = runner.invoke(app, ["graph", "--rank", "--json", "--config", str(cfg)])
    payload = json.loads(ranked.output)
    # Count = DISTINCT mentioning docs (edges are a set): two mentions inside
    # one doc are one edge — a doc can't vote a symbol up twice.
    assert payload[0] == {"mentions": 1, "node": "symbol beta.py#hot_gap"}


def test_graph_json_and_idempotent_write(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    result = runner.invoke(app, ["graph", "--json", "--config", str(cfg)])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0.0"
    assert {n["kind"] for n in payload["nodes"]} >= {"doc", "symbol", "section"}

    first = runner.invoke(app, ["graph", "--write", "--config", str(cfg)])
    assert first.exit_code == 0 and "wrote" in first.output
    artifact = tmp_path / ".cdmon" / "graph.json"
    assert artifact.is_file()
    second = runner.invoke(app, ["graph", "--write", "--config", str(cfg)])
    assert second.exit_code == 0 and "unchanged" in second.output  # K7
