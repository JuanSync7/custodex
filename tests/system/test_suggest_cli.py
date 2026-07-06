"""AGT-06 — the ``cdx suggest`` CLI end to end (text/json/write, K7/K11).

One foreground run of the two background suggesters over a real dir-layout
bundle: healed first, then one drift + one suspect edge + one coverage gap +
one mapping suggestion introduced. Offline (mock backend), read-only except
the opt-in ``--write`` audit log.

Features: FEAT-WORKERS-001
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from custodex.cli import app

runner = CliRunner()

_UNIT = """\
---
cdmon-config-version: "2.0.0"
unit: core
title: "core docs"
owner: eng
created: "2026-07-01"
updated: "2026-07-01"
---
dir-covered:
  - src
source-files-format:
  - .py
documents:
  - id: guide
    path: docs/guide.md
    audience: eng-guide
    code_refs:
      - path: src/alpha.py
  - id: api
    path: docs/api.md
    audience: eng-guide
    region_keys: []
  - id: notes
    path: docs/notes.md
    audience: eng-guide
    region_keys: []
    depends_on:
      - doc: api
"""

_INDEX = """\
---
cdmon-config-version: "2.0.0"
repo: t
generated-by: cdx
updated: "2026-07-01"
---
root: "../.."
version: "2.0.0"
backend: {kind: mock}
units:
  - file: core.yaml
"""


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _setup(tmp_path: Path) -> Path:
    cfg_dir = tmp_path / "config" / "cdmon"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "index.yaml").write_text(_INDEX, encoding="utf-8")
    (cfg_dir / "core.yaml").write_text(_UNIT, encoding="utf-8")
    _write(
        tmp_path, "src/alpha.py", 'def solve_widget(x):\n    """Doc."""\n    return x\n'
    )
    _write(tmp_path, "src/gamma.py", "def hot_gap(z):\n    return z\n")
    _write(tmp_path, "docs/guide.md", "# Guide\n\nCall `hot_gap` and `solve_widget`.\n")
    _write(tmp_path, "docs/api.md", "# API\n\nReference.\n")
    _write(tmp_path, "docs/notes.md", "# Notes\n\nUses `solve_widget` too.\n")
    healed = runner.invoke(app, ["monitor", "--apply", "--config", str(cfg_dir)])
    assert healed.exit_code == 0, healed.output
    # One drift (alpha's surface changes) + one suspect edge (api's PROSE
    # changes after the stamp — frontmatter preserved).
    _write(
        tmp_path,
        "src/alpha.py",
        'def solve_widget(x, *, scale=1):\n    """Doc."""\n    return x * scale\n',
    )
    api = tmp_path / "docs" / "api.md"
    api.write_text(
        api.read_text(encoding="utf-8").replace("Reference.", "Reference, revised."),
        encoding="utf-8",
    )
    return cfg_dir


def test_suggest_text_lists_both_suggesters(tmp_path: Path) -> None:
    cfg_dir = _setup(tmp_path)
    result = runner.invoke(app, ["suggest", "--config", str(cfg_dir)])
    assert result.exit_code == 0, result.output
    for kind in ("fix_drift", "resolve_edge", "document_gap", "add_edge"):
        assert kind in result.output
    assert "cdx monitor --apply" in result.output
    assert "cdx resolve --edge notes api" in result.output
    assert "cdx write-doc src/gamma.py" in result.output
    assert "cdx link notes guide" in result.output


def test_suggest_kind_filters(tmp_path: Path) -> None:
    cfg_dir = _setup(tmp_path)
    fixes = runner.invoke(app, ["suggest", "--kind", "fixes", "--config", str(cfg_dir)])
    assert "fix_drift" in fixes.output and "document_gap" not in fixes.output
    docs = runner.invoke(app, ["suggest", "--kind", "docs", "--config", str(cfg_dir)])
    assert "document_gap" in docs.output and "fix_drift" not in docs.output
    bogus = runner.invoke(
        app, ["suggest", "--kind", "ghosts", "--config", str(cfg_dir)]
    )
    assert bogus.exit_code == 1 and "ghosts" in bogus.output


def test_suggest_json_shape(tmp_path: Path) -> None:
    cfg_dir = _setup(tmp_path)
    result = runner.invoke(app, ["suggest", "--json", "--config", str(cfg_dir)])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert isinstance(payload, list) and payload
    for item in payload:
        assert {
            "key",
            "kind",
            "doc_id",
            "target",
            "detail",
            "evidence",
            "severity",
        } <= set(item)


def test_suggest_write_is_append_only_and_idempotent(tmp_path: Path) -> None:
    cfg_dir = _setup(tmp_path)
    first = runner.invoke(app, ["suggest", "--write", "--config", str(cfg_dir)])
    assert first.exit_code == 0
    log = cfg_dir / ".cdmon" / "suggestions.jsonl"
    assert log.is_file()
    lines = [line for line in log.read_text(encoding="utf-8").splitlines() if line]
    assert lines and all(
        json.loads(line)["source"] == "cli" and json.loads(line)["recorded_at"]
        for line in lines
    )
    # K7: a second run with no change appends NOTHING.
    second = runner.invoke(app, ["suggest", "--write", "--config", str(cfg_dir)])
    assert "0 new suggestion(s)" in second.output
    lines2 = [line for line in log.read_text(encoding="utf-8").splitlines() if line]
    assert lines2 == lines
