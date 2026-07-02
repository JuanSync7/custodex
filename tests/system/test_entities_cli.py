"""AGT-01: the ``cdx entities`` CLI — the mention layer end to end.

Drives the read-only command over a self-contained single-file config: the
full report, the one-doc filter, ``--unresolved`` (the rot view), ``--json``,
and the loud unknown-doc error. Offline, no backend, no network (K1/K4).

Features: FEAT-ENTITIES-003
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
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "guide.md").write_text(
        "# Guide\n\nUse `solve_widget` and `missing_thing` and [o](other.md).\n",
        encoding="utf-8",
    )
    (docs_dir / "other.md").write_text("# Other\n\nProse.\n", encoding="utf-8")
    cfg = {
        "version": "1.0.0",
        "root": ".",
        "coverage": {"include": ["**/*.py"], "exclude": []},
        "documents": [
            {"id": "guide", "path": "docs/guide.md", "audience": "eng-guide"},
            {"id": "other", "path": "docs/other.md", "audience": "eng-guide"},
        ],
    }
    path = tmp_path / "cdmon.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_entities_reports_mentions(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    result = runner.invoke(app, ["entities", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "solve_widget" in result.output
    assert "doc docs/other.md" in result.output
    assert "UNRESOLVED" in result.output  # missing_thing


def test_entities_unresolved_filter(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    result = runner.invoke(app, ["entities", "--config", str(cfg), "--unresolved"])
    assert result.exit_code == 0
    assert "missing_thing" in result.output
    assert "alpha.py#solve_widget" not in result.output


def test_entities_single_doc_filter(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    result = runner.invoke(app, ["entities", "other", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "1 document(s)" in result.output


def test_entities_json_shape(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    result = runner.invoke(app, ["entities", "--config", str(cfg), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [d["doc_id"] for d in payload] == ["guide", "other"]
    guide = payload[0]
    texts = {m["text"] for m in guide["mentions"]}
    assert {"solve_widget", "missing_thing", "other.md"} <= texts


def test_entities_json_unresolved_filter(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    result = runner.invoke(
        app, ["entities", "--config", str(cfg), "--json", "--unresolved"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    for doc in payload:
        assert all(not m["resolved"] for m in doc["mentions"])


def test_entities_unknown_doc_is_loud(tmp_path: Path) -> None:
    cfg = _setup(tmp_path)
    result = runner.invoke(app, ["entities", "nope", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "error:" in result.output
    assert "nope" in result.output
