"""N-06 — end-to-end regression for the ``config/cdmon/`` dir layout.

This is the test whose ABSENCE hid the N-06 repo-root divergence: the per-slice
N-01..N-05 tests exercised the loader/merge/coverage-derivation but never drove
``detect()`` / ``cdmon check`` / ``cdmon monitor --apply`` / ``cdmon coverage``
through the dir-layout resolution path against REAL on-disk source + docs. With
the old divergent formula (``Monitor.root = config_dir / config.root`` resolving
``config/cdmon/..`` = ``<repo>/config``) ``cdmon check`` looked for code under
``config/cdmon/../pkg`` and could never find it. This test builds a true on-disk
dir-layout repo and asserts the whole pipeline resolves code + docs under the
REAL repo root (``<repo>``), heals idempotently (K7), and reports correct
coverage — the exact scenario the per-slice tests skipped.

It also pins single-file back-compat: a Monitor over ``config_dir = repo``,
``root = "."`` must still resolve to the repo (no regression).

Features: FEAT-CLI-005, FEAT-CLI-007, FEAT-CLI-017, FEAT-CONFIG-009
Features: FEAT-CONFIGV2-001, FEAT-CONFIGV2-002, FEAT-CONFIGV2-006
Features: FEAT-CONFIGV2-008, FEAT-DRIFT-001, FEAT-MONITOR-003, FEAT-HEAL-001
Features: FEAT-COVERAGE-006, FEAT-COVERAGE-007, FEAT-COVERAGE-008, FEAT-COVERAGE-009
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from code_doc_monitor.cli import app
from code_doc_monitor.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
    load_config_dir,
    resolve_repo_root,
)
from code_doc_monitor.drift import detect
from code_doc_monitor.monitor import Monitor

runner = CliRunner()

# --------------------------------------------------------------------------- #
# Fixture: a REAL on-disk dir-layout repo (config/cdmon two levels under root).
# --------------------------------------------------------------------------- #

_INDEX_YAML = """\
---
cdmon-config-version: "2.0.0"
repo: e2e-demo
generated-by: cdmon
updated: "2026-06-07"
---
root: "../.."
version: "2.0.0"
apply_default: false
backend: {kind: mock}
central: {sink: none}
coverage:
  waive:
    - {path: "pkg/_gen.py", reason: "generated; documented upstream"}
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


def multiply(a, b):
    """Multiply two numbers."""
    return a * b
'''

_DOC_STUB = """\
# API guide

Hand-written prose.

<!-- CDM:BEGIN symbols -->
PLACEHOLDER
<!-- CDM:END symbols -->
"""


def _build_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Lay out a real dir-layout repo; return ``(repo_root, config_dir)``.

    ``config/cdmon/`` lives TWO levels under the repo root, so the index
    ``root: "../.."`` must resolve back to the repo root for code + docs to be
    found (the N-06 invariant).
    """
    repo = tmp_path / "repo"
    cfg = repo / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "index.yaml").write_text(_INDEX_YAML, encoding="utf-8")
    (cfg / "core.yaml").write_text(_CORE_UNIT_YAML, encoding="utf-8")
    (cfg / "ignore.yaml").write_text(_IGNORE_YAML, encoding="utf-8")

    pkg = repo / "pkg"
    pkg.mkdir()
    (pkg / "calc.py").write_text(_CALC_V1, encoding="utf-8")
    # A waived (generated) file — removed from the coverage denominator.
    (pkg / "_gen.py").write_text("def gen():\n    return 0\n", encoding="utf-8")

    docs = repo / "docs"
    docs.mkdir()
    (docs / "api.md").write_text(_DOC_STUB, encoding="utf-8")
    return repo, cfg


def _seed_in_sync(cfg_dir: Path) -> None:
    """Heal the docs to a clean baseline via ``cdmon monitor --apply``."""
    result = runner.invoke(app, ["monitor", "--config", str(cfg_dir), "--apply"])
    assert result.exit_code == 0, result.output


# --------------------------------------------------------------------------- #
# The N-06 invariant: the ONE resolver maps BOTH layouts to the right root.
# --------------------------------------------------------------------------- #


def test_resolve_repo_root_dir_layout_points_at_repo(tmp_path: Path) -> None:
    """``resolve_repo_root(config/cdmon, "../..")`` is the repo root, NOT config/."""
    repo, cfg = _build_repo(tmp_path)
    assert resolve_repo_root(cfg, "../..") == repo
    # The old broken formula resolved to <repo>/config — assert we are NOT there.
    assert resolve_repo_root(cfg, "../..") != repo / "config"


def test_resolve_repo_root_single_file_is_unchanged(tmp_path: Path) -> None:
    """Single-file back-compat: config_dir == repo, root == "." ⇒ the repo."""
    assert resolve_repo_root(tmp_path, ".") == tmp_path


def test_monitor_root_under_true_repo_for_dir_layout(tmp_path: Path) -> None:
    """``Monitor.root`` resolves to the repo root (where pkg/ + docs/ live)."""
    repo, cfg = _build_repo(tmp_path)
    config = load_config_dir(cfg)
    mon = Monitor(config, cfg)
    assert mon.root == repo
    assert (mon.root / "pkg" / "calc.py").is_file()
    assert (mon.root / "docs" / "api.md").is_file()


# --------------------------------------------------------------------------- #
# Clean repo → no drift; drift on a code edit; heal; idempotent re-check.
# --------------------------------------------------------------------------- #


def test_clean_repo_detects_no_drift(tmp_path: Path) -> None:
    """After seeding, ``detect()`` and ``cdmon check`` agree: zero drift."""
    repo, cfg = _build_repo(tmp_path)
    _seed_in_sync(cfg)

    config = load_config_dir(cfg)
    assert detect(config, cfg).ok

    result = runner.invoke(app, ["check", "--config", str(cfg)])
    assert result.exit_code == 0, result.output


def test_code_edit_drifts_then_heals_idempotently(tmp_path: Path) -> None:
    """A symbol edit drifts; ``monitor --apply`` heals; re-check is clean (K7)."""
    repo, cfg = _build_repo(tmp_path)
    _seed_in_sync(cfg)

    # Edit a public symbol signature under the TRUE repo root.
    (repo / "pkg" / "calc.py").write_text(
        _CALC_V1.replace("def add(a, b):", "def add(a, b, c=0):"),
        encoding="utf-8",
    )

    config = load_config_dir(cfg)
    report = detect(config, cfg)
    assert not report.ok, "a code edit under the repo root must drift"
    assert {d.doc_id for d in report.drifts} == {"api-guide"}

    # cdmon check sees the drift (exit 1).
    check1 = runner.invoke(app, ["check", "--config", str(cfg)])
    assert check1.exit_code == 1, check1.output

    # monitor --apply heals it.
    heal = runner.invoke(app, ["monitor", "--config", str(cfg), "--apply"])
    assert heal.exit_code == 0, heal.output

    # Re-check is clean.
    check2 = runner.invoke(app, ["check", "--config", str(cfg)])
    assert check2.exit_code == 0, check2.output
    assert detect(load_config_dir(cfg), cfg).ok

    # K7 idempotent: a SECOND apply changes nothing on disk.
    doc_after_heal = (repo / "docs" / "api.md").read_text(encoding="utf-8")
    heal2 = runner.invoke(app, ["monitor", "--config", str(cfg), "--apply"])
    assert heal2.exit_code == 0, heal2.output
    assert (repo / "docs" / "api.md").read_text(encoding="utf-8") == doc_after_heal


# --------------------------------------------------------------------------- #
# Coverage resolves code under the TRUE repo root (not config/).
# --------------------------------------------------------------------------- #


def test_coverage_resolves_code_under_true_repo_root(tmp_path: Path) -> None:
    """``cdmon coverage`` scans pkg/ under the repo root and reports correct %.

    With the old divergent formula coverage scanned the wrong directory; here
    ``pkg/calc.py`` is documented (api-guide), ``pkg/_gen.py`` is waived, so file
    coverage is 100% (the waived file leaves the denominator).
    """
    repo, cfg = _build_repo(tmp_path)
    _seed_in_sync(cfg)

    result = runner.invoke(app, ["coverage", "--config", str(cfg), "--json"])
    assert result.exit_code == 0, result.output

    import json

    payload = json.loads(result.output)
    # calc.py is the one scanned+documented file (it has owners); _gen.py waived.
    documented = {f["path"] for f in payload["files"] if f["owners"]}
    assert "pkg/calc.py" in documented
    waived = {f["path"] for f in payload["waived_files"]}
    assert "pkg/_gen.py" in waived
    # No uncovered files ⇒ 100% file coverage (waived removed from both sides).
    assert payload["percent_files"] == pytest.approx(100.0)
    assert payload["undocumented_files"] == []


def test_coverage_reports_a_gap_when_code_undocumented(tmp_path: Path) -> None:
    """A new undocumented .py under pkg/ surfaces as an uncovered file."""
    repo, cfg = _build_repo(tmp_path)
    _seed_in_sync(cfg)
    # Add a real, non-waived, undocumented source file under the repo root.
    (repo / "pkg" / "extra.py").write_text(
        "def extra():\n    return 7\n", encoding="utf-8"
    )

    result = runner.invoke(app, ["coverage", "--config", str(cfg), "--json"])
    assert result.exit_code == 0, result.output

    import json

    payload = json.loads(result.output)
    gaps = {f["path"] for f in payload["undocumented_files"]}
    assert "pkg/extra.py" in gaps, "an undocumented repo-root file must be a gap"


# --------------------------------------------------------------------------- #
# Single-file back-compat MUST NOT regress.
# --------------------------------------------------------------------------- #


def test_single_file_layout_still_resolves_and_checks(tmp_path: Path) -> None:
    """A single-file config (root ".") still resolves code/docs under the repo."""
    root = tmp_path
    (root / "shared.py").write_text(_CALC_V1, encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "api.md").write_text(_DOC_STUB, encoding="utf-8")
    spec = DocumentSpec(
        id="api-guide",
        path="docs/api.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols",),
    )
    cfg = MonitorConfig(documents=(spec,))  # root defaults to "."

    mon = Monitor(cfg, root)
    assert mon.root == root  # config_dir IS the repo
    # Seed in-sync, then a clean check.
    mon.run(apply=True)
    assert detect(cfg, root).ok
