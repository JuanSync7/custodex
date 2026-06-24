"""N-04 — tests for the ``coverage.rpt`` report (CONFIG-V2 §3, K1/K7/K8/K10).

Covers the new :mod:`custodex.report` surface: the frozen
:class:`CoverageRpt`/:class:`RptSummary`/:class:`RptUnit`/:class:`RptUndocumented`
models; :func:`build_coverage_rpt` (which REUSES ``effective_coverage`` +
``discover_files``/``discover_symbols``/``resolve_coverage`` — never forks the
coverage engine); deterministic 2-dp percent formatting (``n/a`` when the
denominator is 0); per-unit attribution by ``dir-covered``; ``suggested_unit``
resolution (matching unit / format mismatch / no-unit → null+reason);
:func:`render_rpt` (``---`` frontmatter + YAML body, NO wall-clock so it is
byte-stable); the parse round-trip; and the ``cdx rpt`` CLI (default prints,
``--write`` writes idempotently, ``--ref`` lands in frontmatter).

Features: FEAT-QUALITY-005, FEAT-QUALITY-006, FEAT-QUALITY-007, FEAT-CLI-003
Features: FEAT-COVERAGE-001, FEAT-CONFIGV2-006
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from custodex.cli import app
from custodex.config import load_bundle
from custodex.errors import ConfigError
from custodex.report import (
    CoverageRpt,
    RptSummary,
    RptUndocumented,
    RptUnit,
    build_coverage_rpt,
    parse_rpt,
    render_rpt,
    write_rpt,
)

runner = CliRunner()


# --------------------------------------------------------------------------- #
# Fixture repo: config/cdmon with 2 units. ``core`` is fully documented; ``util``
# has an undocumented .py (the gap) and a .log (ignored by format).
# --------------------------------------------------------------------------- #

_INDEX_YAML = """\
---
cdmon-config-version: "2.0.0"
repo: demo
generated-by: cdx
updated: "2026-06-07"
---
root: "../.."
version: "2.0.0"
units:
  - file: core.yaml
  - file: util.yaml
"""

_CORE_YAML = """\
---
cdmon-config-version: "2.0.0"
unit: core
title: "Core coverage"
owner: eng-platform
created: "2026-06-07"
updated: "2026-06-07"
---
dir-covered:
  - core
source-files-format:
  - ".py"
documents:
  - id: core-doc
    path: docs/core.md
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: core/main.py
"""

_UTIL_YAML = """\
---
cdmon-config-version: "2.0.0"
unit: util
title: "Util coverage"
owner: eng-platform
created: "2026-06-07"
updated: "2026-06-07"
---
dir-covered:
  - util
source-files-format:
  - ".py"
documents:
  - id: util-doc
    path: docs/util.md
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: util/helpers.py
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
  - "**/_skip.py"
"""


def _build_repo(
    tmp_path: Path,
    *,
    index_text: str = _INDEX_YAML,
    core_text: str = _CORE_YAML,
    util_text: str = _UTIL_YAML,
    ignore_text: str = _IGNORE_YAML,
) -> tuple[Path, Path]:
    """Lay out a real repo with config/cdmon + a core/ and util/ source tree."""
    repo = tmp_path / "repo"
    cfg = repo / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "index.yaml").write_text(index_text, encoding="utf-8")
    (cfg / "core.yaml").write_text(core_text, encoding="utf-8")
    (cfg / "util.yaml").write_text(util_text, encoding="utf-8")
    (cfg / "ignore.yaml").write_text(ignore_text, encoding="utf-8")

    core = repo / "core"
    core.mkdir()
    (core / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")

    util = repo / "util"
    util.mkdir()
    (util / "helpers.py").write_text("def helper():\n    return 2\n", encoding="utf-8")
    (util / "orphan.py").write_text("def orphan():\n    return 3\n", encoding="utf-8")
    (util / "_skip.py").write_text("def skip():\n    return 4\n", encoding="utf-8")
    (util / "run.log").write_text("noise\n", encoding="utf-8")
    return repo, cfg


# --------------------------------------------------------------------------- #
# unit — percent formatting (2 dp; 100.0, 0.0; n/a when denominator 0).
# --------------------------------------------------------------------------- #


def test_percent_two_decimals() -> None:
    s = RptSummary(
        scanned_files=14,
        documented_files=13,
        waived_files=0,
        ignored_files=0,
        uncovered_files=1,
        percent=92.857142,
    )
    # Rendered with 2 dp deterministically.
    assert "92.86" in render_rpt(
        CoverageRpt(
            cdmon_report_version="1.0.0",
            kind="coverage",
            repo="demo",
            ref=None,
            summary=s,
            units=(),
            undocumented=(),
        )
    )


def test_percent_round_values() -> None:
    body = render_rpt(
        CoverageRpt(
            cdmon_report_version="1.0.0",
            kind="coverage",
            repo="demo",
            ref=None,
            summary=RptSummary(
                scanned_files=2,
                documented_files=2,
                waived_files=0,
                ignored_files=0,
                uncovered_files=0,
                percent=100.0,
            ),
            units=(),
            undocumented=(),
        )
    )
    assert "percent: 100.00" in body


def test_percent_na_when_denominator_zero() -> None:
    body = render_rpt(
        CoverageRpt(
            cdmon_report_version="1.0.0",
            kind="coverage",
            repo="demo",
            ref=None,
            summary=RptSummary(
                scanned_files=0,
                documented_files=0,
                waived_files=0,
                ignored_files=0,
                uncovered_files=0,
                percent=None,
            ),
            units=(),
            undocumented=(),
        )
    )
    assert "percent: n/a" in body
    # And it round-trips back to None.
    assert parse_rpt(body).summary.percent is None


# --------------------------------------------------------------------------- #
# build_coverage_rpt — golden summary, per-unit percents, suggested_unit.
# --------------------------------------------------------------------------- #


def test_build_summary_counts(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    rpt = build_coverage_rpt(load_bundle(cfg), repo, ref="main")
    s = rpt.summary
    # Universe = core/main.py, util/helpers.py, util/orphan.py (the .log is out).
    assert s.scanned_files == 3
    assert s.documented_files == 2
    assert s.uncovered_files == 1
    assert s.waived_files == 0
    # percent = round(100 * 2 / (3 - 0), 2) = 66.67 (stored 2-dp for round-trip)
    assert s.percent == 66.67


def test_build_per_unit_breakdown(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    rpt = build_coverage_rpt(load_bundle(cfg), repo, ref="main")
    by_file = {u.file: u for u in rpt.units}
    assert by_file["core.yaml"].scanned == 1
    assert by_file["core.yaml"].documented == 1
    assert by_file["core.yaml"].percent == pytest.approx(100.0)
    assert by_file["core.yaml"].uncovered == ()

    assert by_file["util.yaml"].scanned == 2
    assert by_file["util.yaml"].documented == 1
    assert by_file["util.yaml"].percent == pytest.approx(50.0)
    assert by_file["util.yaml"].uncovered == ("util/orphan.py",)


# A global waiver removes the waived file from BOTH the overall AND the per-unit
# denominators (M-02): the same `scanned - waived` math, so the two stay consistent.
_INDEX_WAIVED = """\
---
cdmon-config-version: "2.0.0"
repo: demo
generated-by: cdx
updated: "2026-06-07"
---
root: "../.."
version: "2.0.0"
coverage:
  waive:
    - path: "util/orphan.py"
      reason: "deliberate demo gap; surface documented elsewhere"
units:
  - file: core.yaml
  - file: util.yaml
"""


def test_per_unit_percent_removes_waived_from_denominator(tmp_path: Path) -> None:
    """A unit of 2 files with 1 waived + 1 documented reports 100.0, not 50.0 —
    waived files leave BOTH sides per-unit, exactly as the overall summary does."""
    repo, cfg = _build_repo(tmp_path, index_text=_INDEX_WAIVED)
    rpt = build_coverage_rpt(load_bundle(cfg), repo, ref="main")

    by_file = {u.file: u for u in rpt.units}
    util = by_file["util.yaml"]
    # scanned still counts every universe file under the unit (waived is a
    # universe file); the percent removes the waived one from the denominator.
    assert util.scanned == 2
    assert util.documented == 1
    assert util.percent == pytest.approx(100.0)
    # The waived file is NOT an uncovered gap.
    assert util.uncovered == ()

    # The overall summary is consistent: 3 scanned, 2 documented, 1 waived -> 100.0.
    assert rpt.summary.scanned_files == 3
    assert rpt.summary.documented_files == 2
    assert rpt.summary.waived_files == 1
    assert rpt.summary.percent == pytest.approx(100.0)


def test_build_undocumented_suggested_unit(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    rpt = build_coverage_rpt(load_bundle(cfg), repo, ref="main")
    assert len(rpt.undocumented) == 1
    entry = rpt.undocumented[0]
    assert entry.path == "util/orphan.py"
    assert entry.suggested_unit == "util.yaml"
    assert "util" in entry.reason and ".py" in entry.reason


def test_build_frontmatter_fields(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    rpt = build_coverage_rpt(load_bundle(cfg), repo, ref="abc123")
    assert rpt.cdmon_report_version == "1.0.0"
    assert rpt.kind == "coverage"
    assert rpt.repo == "demo"
    assert rpt.ref == "abc123"


def test_build_ref_none(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    rpt = build_coverage_rpt(load_bundle(cfg), repo, ref=None)
    assert rpt.ref is None
    body = render_rpt(rpt)
    assert parse_rpt(body).ref is None


# --------------------------------------------------------------------------- #
# suggested_unit — format mismatch (different unit / none) and no-unit → null.
# --------------------------------------------------------------------------- #


_IGNORE_EMPTY = """\
---
cdmon-config-version: "2.0.0"
source: "manual"
updated: "2026-06-07"
---
gitignore: false
patterns: []
"""


def test_suggested_unit_format_match_resolves(tmp_path: Path) -> None:
    """A .log file under util's dir, when util scopes .log, attributes to util."""
    util = _UTIL_YAML.replace('  - ".py"', '  - ".log"')
    repo, cfg = _build_repo(tmp_path, util_text=util, ignore_text=_IGNORE_EMPTY)
    bundle = load_bundle(cfg)
    from custodex.report import _suggest_unit

    su, reason = _suggest_unit(bundle, "util/run.log")
    assert su == "util.yaml"
    assert ".log" in reason


def test_suggested_unit_no_unit_dir_match(tmp_path: Path) -> None:
    """A file under no unit's dir-covered → suggested_unit null with a reason."""
    repo, cfg = _build_repo(tmp_path)
    bundle = load_bundle(cfg)
    from custodex.report import _suggest_unit

    su, reason = _suggest_unit(bundle, "outside/thing.py")
    assert su is None
    assert "no unit" in reason.lower()


def test_suggested_unit_dir_match_format_mismatch_null(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    bundle = load_bundle(cfg)
    from custodex.report import _suggest_unit

    # core's dir contains it, but .md is not in core's source-files-format.
    su, reason = _suggest_unit(bundle, "core/readme.md")
    assert su is None
    assert "format" in reason.lower()


# --------------------------------------------------------------------------- #
# Z-01a — nested units: deepest-wins attribution (no parent double-count) and
# suggested_unit picks the deepest unit.
# --------------------------------------------------------------------------- #

# Parent unit ``core`` owns the whole repo dir ``pkg``; child unit ``sub`` owns
# the nested ``pkg/sub``. Both scope ``.py``. A file in ``pkg/sub`` must count
# under the CHILD only.
_NEST_INDEX = """\
---
cdmon-config-version: "2.0.0"
repo: demo
generated-by: cdx
updated: "2026-06-07"
---
root: "../.."
version: "2.0.0"
units:
  - file: core.yaml
  - file: sub.yaml
"""

_NEST_CORE = """\
---
cdmon-config-version: "2.0.0"
unit: core
title: "Core (parent) coverage"
owner: eng-platform
created: "2026-06-07"
updated: "2026-06-07"
---
dir-covered:
  - pkg
source-files-format:
  - ".py"
documents:
  - id: core-doc
    path: docs/core.md
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: pkg/main.py
"""

_NEST_SUB = """\
---
cdmon-config-version: "2.0.0"
unit: sub
title: "Sub (child) coverage"
owner: eng-platform
created: "2026-06-07"
updated: "2026-06-07"
---
dir-covered:
  - pkg/sub
source-files-format:
  - ".py"
documents:
  - id: sub-doc
    path: docs/sub.md
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: pkg/sub/child.py
"""

_NEST_IGNORE = """\
---
cdmon-config-version: "2.0.0"
source: "manual"
updated: "2026-06-07"
---
gitignore: false
patterns: []
"""


def _build_nested_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    cfg = repo / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "index.yaml").write_text(_NEST_INDEX, encoding="utf-8")
    (cfg / "core.yaml").write_text(_NEST_CORE, encoding="utf-8")
    (cfg / "sub.yaml").write_text(_NEST_SUB, encoding="utf-8")
    (cfg / "ignore.yaml").write_text(_NEST_IGNORE, encoding="utf-8")

    pkg = repo / "pkg"
    pkg.mkdir()
    (pkg / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    sub = pkg / "sub"
    sub.mkdir()
    # child.py is documented; gap.py is an undocumented gap under the child dir.
    (sub / "child.py").write_text("def child():\n    return 2\n", encoding="utf-8")
    (sub / "gap.py").write_text("def gap():\n    return 3\n", encoding="utf-8")
    return repo, cfg


def test_nested_per_unit_no_double_count(tmp_path: Path) -> None:
    """A file in the child dir counts under the CHILD unit only — the parent unit
    does not double-count it (Z-01a deepest-wins)."""
    repo, cfg = _build_nested_repo(tmp_path)
    rpt = build_coverage_rpt(load_bundle(cfg), repo, ref="main")
    by_file = {u.file: u for u in rpt.units}

    # Parent owns only pkg/main.py (pkg/sub/* belongs to the child).
    assert by_file["core.yaml"].scanned == 1
    assert by_file["core.yaml"].documented == 1
    assert by_file["core.yaml"].uncovered == ()

    # Child owns both pkg/sub/child.py (documented) and pkg/sub/gap.py (gap).
    assert by_file["sub.yaml"].scanned == 2
    assert by_file["sub.yaml"].documented == 1
    assert by_file["sub.yaml"].uncovered == ("pkg/sub/gap.py",)

    # The per-unit scanned counts partition the universe (no overlap, no loss).
    assert by_file["core.yaml"].scanned + by_file["sub.yaml"].scanned == (
        rpt.summary.scanned_files
    )


def test_nested_suggested_unit_picks_deepest(tmp_path: Path) -> None:
    """suggested_unit for a gap under the child dir is the CHILD unit, not the
    parent that also contains the path (Z-01a deepest-wins)."""
    repo, cfg = _build_nested_repo(tmp_path)
    rpt = build_coverage_rpt(load_bundle(cfg), repo, ref="main")
    assert len(rpt.undocumented) == 1
    entry = rpt.undocumented[0]
    assert entry.path == "pkg/sub/gap.py"
    assert entry.suggested_unit == "sub.yaml"  # the deepest, not core.yaml


# --------------------------------------------------------------------------- #
# render / round-trip — parse(render(r)) == r; frontmatter shape; no wall-clock.
# --------------------------------------------------------------------------- #


def test_render_has_frontmatter_and_body(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    rpt = build_coverage_rpt(load_bundle(cfg), repo, ref="main")
    text = render_rpt(rpt)
    assert text.startswith("---\n")
    assert "cdmon-report-version: 1.0.0" in text
    assert "kind: coverage" in text
    assert "generated-by: cdx rpt" in text
    assert "ref: main" in text
    # Body markers.
    assert "\nsummary:" in text
    assert "\nunits:" in text
    assert "\nundocumented:" in text


def test_render_golden_exact_text(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    rpt = build_coverage_rpt(load_bundle(cfg), repo, ref="main")
    expected = (
        "---\n"
        "cdmon-report-version: 1.0.0\n"
        "kind: coverage\n"
        "repo: demo\n"
        "ref: main\n"
        "generated-by: cdx rpt\n"
        "---\n"
        "summary:\n"
        "  scanned_files: 3\n"
        "  documented_files: 2\n"
        "  waived_files: 0\n"
        "  ignored_files: 1\n"
        "  uncovered_files: 1\n"
        "  percent: 66.67\n"
        "units:\n"
        "  - unit: core\n"
        "    file: core.yaml\n"
        "    scanned: 1\n"
        "    documented: 1\n"
        "    percent: 100.00\n"
        "    uncovered: []\n"
        "  - unit: util\n"
        "    file: util.yaml\n"
        "    scanned: 2\n"
        "    documented: 1\n"
        "    percent: 50.00\n"
        "    uncovered:\n"
        "      - util/orphan.py\n"
        "undocumented:\n"
        "  - path: util/orphan.py\n"
        "    suggested_unit: util.yaml\n"
        "    reason: under dir-covered 'util' and format '.py'\n"
    )
    assert render_rpt(rpt) == expected


def test_render_round_trip(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    rpt = build_coverage_rpt(load_bundle(cfg), repo, ref="main")
    assert parse_rpt(render_rpt(rpt)) == rpt


def test_render_no_wall_clock(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    rpt = build_coverage_rpt(load_bundle(cfg), repo, ref="main")
    text = render_rpt(rpt)
    # No generated/updated/timestamp keys leak into the byte-stable file (K7).
    assert "generated:" not in text
    assert "updated:" not in text
    assert "timestamp" not in text


def test_render_deterministic(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    rpt = build_coverage_rpt(load_bundle(cfg), repo, ref="main")
    assert render_rpt(rpt) == render_rpt(rpt)


def test_parse_rejects_missing_frontmatter() -> None:
    with pytest.raises(ConfigError):
        parse_rpt("summary: {}\n")


def test_parse_rejects_unterminated_fence() -> None:
    with pytest.raises(ConfigError):
        parse_rpt("---\ncdmon-report-version: 1.0.0\nno closing fence\n")


def test_parse_rejects_non_mapping_frontmatter() -> None:
    with pytest.raises(ConfigError):
        parse_rpt("---\n- a\n- b\n---\nsummary: {}\n")


def test_parse_rejects_non_mapping_body() -> None:
    fm = "---\ncdmon-report-version: 1.0.0\nkind: coverage\nrepo: d\nref: null\n---\n"
    with pytest.raises(ConfigError):
        parse_rpt(fm + "- not a mapping\n")


def test_parse_rejects_malformed_body_yaml() -> None:
    fm = "---\ncdmon-report-version: 1.0.0\nkind: coverage\nrepo: d\nref: null\n---\n"
    with pytest.raises(ConfigError):
        parse_rpt(fm + "summary: {: :\n")


def test_parse_rejects_missing_summary_field() -> None:
    fm = "---\ncdmon-report-version: 1.0.0\nkind: coverage\nrepo: d\nref: null\n---\n"
    # summary mapping missing required keys → KeyError → ConfigError.
    with pytest.raises(ConfigError):
        parse_rpt(fm + "summary:\n  scanned_files: 1\n")


def test_round_trip_empty_units_and_na(tmp_path: Path) -> None:
    rpt = CoverageRpt(
        cdmon_report_version="1.0.0",
        kind="coverage",
        repo="demo",
        ref=None,
        summary=RptSummary(
            scanned_files=0,
            documented_files=0,
            waived_files=0,
            ignored_files=0,
            uncovered_files=0,
            percent=None,
        ),
        units=(),
        undocumented=(),
    )
    text = render_rpt(rpt)
    assert "units: []" in text
    assert "undocumented: []" in text
    assert parse_rpt(text) == rpt


def test_reason_with_special_chars_round_trips() -> None:
    rpt = CoverageRpt(
        cdmon_report_version="1.0.0",
        kind="coverage",
        repo="demo",
        ref=None,
        summary=RptSummary(
            scanned_files=1,
            documented_files=0,
            waived_files=0,
            ignored_files=0,
            uncovered_files=1,
            percent=0.0,
        ),
        units=(),
        undocumented=(
            RptUndocumented(
                path="a/b.py",
                suggested_unit=None,
                reason="no unit dir-covered contains 'a/b.py': weird: chars",
            ),
        ),
    )
    assert parse_rpt(render_rpt(rpt)) == rpt


def test_parse_rejects_wrong_version() -> None:
    repo_text = render_rpt(
        CoverageRpt(
            cdmon_report_version="1.0.0",
            kind="coverage",
            repo="demo",
            ref=None,
            summary=RptSummary(
                scanned_files=0,
                documented_files=0,
                waived_files=0,
                ignored_files=0,
                uncovered_files=0,
                percent=None,
            ),
            units=(),
            undocumented=(),
        )
    ).replace("1.0.0", "9.9.9")
    with pytest.raises(ConfigError):
        parse_rpt(repo_text)


# --------------------------------------------------------------------------- #
# write_rpt — writes config/cdmon/coverage.rpt; loud on OSError.
# --------------------------------------------------------------------------- #


def test_write_rpt_creates_file(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    rpt = build_coverage_rpt(load_bundle(cfg), repo, ref="main")
    text = render_rpt(rpt)
    write_rpt(cfg, text)
    out = cfg / "coverage.rpt"
    assert out.is_file()
    assert out.read_text(encoding="utf-8") == text


def test_write_rpt_loud_on_oserror(tmp_path: Path) -> None:
    # A config_dir that does not exist → write fails loudly (K8).
    with pytest.raises(ConfigError):
        write_rpt(tmp_path / "does" / "not" / "exist", "x")


# --------------------------------------------------------------------------- #
# CLI — default prints (no write, K1); --write writes; --write twice byte-stable;
# --ref lands in frontmatter.
# --------------------------------------------------------------------------- #


def test_cli_default_prints_no_write(tmp_path: Path, monkeypatch) -> None:
    repo, cfg = _build_repo(tmp_path)
    monkeypatch.chdir(repo)
    result = runner.invoke(app, ["rpt"])
    assert result.exit_code == 0, result.output
    assert "kind: coverage" in result.output
    # Read-only: no coverage.rpt written (K1).
    assert not (cfg / "coverage.rpt").exists()


def test_cli_write_creates_file(tmp_path: Path, monkeypatch) -> None:
    repo, cfg = _build_repo(tmp_path)
    monkeypatch.chdir(repo)
    result = runner.invoke(app, ["rpt", "--write"])
    assert result.exit_code == 0, result.output
    out = cfg / "coverage.rpt"
    assert out.is_file()
    assert "kind: coverage" in out.read_text(encoding="utf-8")


def test_cli_write_idempotent(tmp_path: Path, monkeypatch) -> None:
    repo, cfg = _build_repo(tmp_path)
    monkeypatch.chdir(repo)
    runner.invoke(app, ["rpt", "--write", "--ref", "main"])
    first = (cfg / "coverage.rpt").read_text(encoding="utf-8")
    runner.invoke(app, ["rpt", "--write", "--ref", "main"])
    second = (cfg / "coverage.rpt").read_text(encoding="utf-8")
    assert first == second  # byte-identical (K7)


def test_cli_ref_in_frontmatter(tmp_path: Path, monkeypatch) -> None:
    repo, cfg = _build_repo(tmp_path)
    monkeypatch.chdir(repo)
    result = runner.invoke(app, ["rpt", "--ref", "feature/x"])
    assert result.exit_code == 0, result.output
    assert "ref: feature/x" in result.output


def test_cli_config_dir_option(tmp_path: Path) -> None:
    repo, cfg = _build_repo(tmp_path)
    result = runner.invoke(app, ["rpt", "--config-dir", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "kind: coverage" in result.output


def test_cli_loud_on_missing_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["rpt", "--config-dir", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "error:" in result.output


def test_cli_write_parses_back(tmp_path: Path, monkeypatch) -> None:
    repo, cfg = _build_repo(tmp_path)
    monkeypatch.chdir(repo)
    runner.invoke(app, ["rpt", "--write", "--ref", "main"])
    text = (cfg / "coverage.rpt").read_text(encoding="utf-8")
    rpt = parse_rpt(text)
    assert rpt.repo == "demo"
    assert rpt.ref == "main"
    # The written file is valid YAML with a frontmatter fence.
    assert text.startswith("---\n")


# --------------------------------------------------------------------------- #
# model shapes — frozen, equality.
# --------------------------------------------------------------------------- #


def test_models_frozen() -> None:
    s = RptSummary(
        scanned_files=1,
        documented_files=1,
        waived_files=0,
        ignored_files=0,
        uncovered_files=0,
        percent=100.0,
    )
    with pytest.raises(ValidationError):
        s.scanned_files = 2  # type: ignore[misc]


def test_rpt_unit_and_undocumented_shapes() -> None:
    u = RptUnit(
        unit="core",
        file="core.yaml",
        scanned=1,
        documented=1,
        percent=100.0,
        uncovered=(),
    )
    d = RptUndocumented(path="a/b.py", suggested_unit="core.yaml", reason="why")
    assert u.unit == "core"
    assert d.path == "a/b.py"
