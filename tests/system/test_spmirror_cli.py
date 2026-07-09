"""SP-01 — `cdx sp-sync` end to end: the SharePoint governance loop.

THE flagship flow this epic exists for (all offline, DirSource — K4):
mirror a library into the repo → declare the mirrored doc + a `depends_on`
edge from a git-native doc → `monitor --apply` baselines → the SharePoint
side changes → re-sync → the dependent flips SUSPECT_LINK and gates `cdx
check` → a human `cdx resolve --edge` clears it.

Features: FEAT-SPMIRROR-003

Feature: FEAT-SPMIRROR-003
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from custodex.cli import app
from tests._docx import build_docx

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
    depends_on:
      - doc: sp-design
  - id: sp-design
    path: docs/sharepoint/specs/Design.docx.md
    audience: user-guide
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


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A repo + a fake SharePoint library dir; returns (repo, library, spcfg)."""
    repo = tmp_path / "repo"
    library = tmp_path / "library"
    build_docx(
        library / "specs" / "Design.docx",
        [("Heading1", "Design Spec"), (None, "The API accepts widgets.")],
    )
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "alpha.py").write_text(
        'def solve(x):\n    """Doc."""\n    return x\n', encoding="utf-8"
    )
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text(
        "# Guide\n\nBuilt from the design spec.\n", encoding="utf-8"
    )
    spcfg = repo / "config" / "spmirror.yaml"
    spcfg.parent.mkdir(parents=True)
    spcfg.write_text(
        yaml.safe_dump(
            {
                "spmirror": {
                    "source": "dir",
                    "source_dir": str(library),
                    "dest": "docs/sharepoint",
                    "include": ["**/*.docx"],
                    "converters": {".docx": "docx-text"},
                }
            }
        ),
        encoding="utf-8",
    )
    cfg_dir = repo / "config" / "cdmon"
    cfg_dir.mkdir()
    (cfg_dir / "index.yaml").write_text(_INDEX, encoding="utf-8")
    (cfg_dir / "core.yaml").write_text(_UNIT, encoding="utf-8")
    return repo, library, spcfg


def test_sp_sync_then_suspect_then_resolve_end_to_end(tmp_path: Path) -> None:
    repo, library, spcfg = _setup(tmp_path)
    cfg_dir = repo / "config" / "cdmon"

    # 1. Mirror the library into the repo.
    result = runner.invoke(
        app, ["sp-sync", "--config", str(spcfg), "--repo-root", str(repo)]
    )
    assert result.exit_code == 0, result.output
    mirror = repo / "docs" / "sharepoint" / "specs" / "Design.docx.md"
    assert mirror.is_file() and "# Design Spec" in mirror.read_text()

    # 2. Baseline everything (fingerprints + the guide→sp-design edge stamp).
    result = runner.invoke(app, ["monitor", "--apply", "--config", str(cfg_dir)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["check", "--config", str(cfg_dir)])
    assert result.exit_code == 0, result.output

    # 3. SharePoint side changes; re-sync moves the mirror body...
    build_docx(
        library / "specs" / "Design.docx",
        [
            ("Heading1", "Design Spec"),
            (None, "The API accepts widgets AND gadgets now."),
        ],
    )
    result = runner.invoke(
        app, ["sp-sync", "--config", str(spcfg), "--repo-root", str(repo)]
    )
    assert result.exit_code == 0, result.output
    assert "gadgets" in mirror.read_text()
    # ...and the heal-stamped cdm baseline SURVIVED the overwrite:
    assert mirror.read_text().startswith("---\n")

    # 4. The dependent doc is now SUSPECT and gates check (the whole point).
    result = runner.invoke(app, ["check", "--config", str(cfg_dir)])
    assert result.exit_code == 1
    assert "SUSPECT_LINK" in result.output and "sp-design" in result.output

    # 5. A human reviews and clears the one edge; green again.
    result = runner.invoke(
        app, ["resolve", "--edge", "guide", "sp-design", "--config", str(cfg_dir)]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["check", "--config", str(cfg_dir)])
    assert result.exit_code == 0, result.output


def test_sp_sync_dry_run_writes_nothing(tmp_path: Path) -> None:
    repo, _, spcfg = _setup(tmp_path)
    result = runner.invoke(
        app,
        ["sp-sync", "--config", str(spcfg), "--repo-root", str(repo), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert not (repo / "docs" / "sharepoint").exists()
    assert not (repo / ".cdmon" / "sp-manifest.json").exists()


def test_sp_sync_json_report(tmp_path: Path) -> None:
    repo, _, spcfg = _setup(tmp_path)
    result = runner.invoke(
        app,
        ["sp-sync", "--config", str(spcfg), "--repo-root", str(repo), "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["pulled"] == 1
    assert payload["written"] == ["docs/sharepoint/specs/Design.docx.md"]
    # A second run is a reported no-op (K7).
    result = runner.invoke(
        app,
        ["sp-sync", "--config", str(spcfg), "--repo-root", str(repo), "--json"],
    )
    payload = json.loads(result.output)
    assert payload["pulled"] == 0 and payload["unchanged"] == 1


def test_sp_sync_missing_config_is_loud(tmp_path: Path) -> None:
    result = runner.invoke(app, ["sp-sync", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 1
    assert "error:" in result.output
