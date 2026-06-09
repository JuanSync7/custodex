"""CDM-06 — tests for the full `cdmon` CLI (offline, via CliRunner).

Features: FEAT-CLI-004, FEAT-CLI-005, FEAT-CLI-006, FEAT-CLI-007, FEAT-CLI-008
Features: FEAT-CLI-009, FEAT-CLI-013
Features: FEAT-CLI-010, FEAT-CLI-011, FEAT-CLI-015, FEAT-CLI-016, FEAT-CLI-017
Features: FEAT-CLI-018, FEAT-CLI-019, FEAT-CLI-020, FEAT-CLI-021, FEAT-CLI-022
Features: FEAT-DRIFT-001, FEAT-MONITOR-001, FEAT-MONITOR-003, FEAT-MONITOR-005
Features: FEAT-RECORD-001, FEAT-RECORD-003, FEAT-RECORD-006, FEAT-RECORD-007
Features: FEAT-RECORD-009, FEAT-COVERAGE-007, FEAT-COVERAGE-010, FEAT-LEARN-004
Features: FEAT-PR-001, FEAT-PR-002, FEAT-PR-003, FEAT-PR-004, FEAT-PR-006
Features: FEAT-PR-007, FEAT-PR-008, FEAT-LAYOUT-001, FEAT-LAYOUT-002
Features: FEAT-LAYOUT-003, FEAT-LAYOUT-004, FEAT-LAYOUT-007, FEAT-SERVER-017
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from code_doc_monitor.blocks import symbol_table
from code_doc_monitor.cli import app
from code_doc_monitor.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
)
from code_doc_monitor.extract import build_document_surface

runner = CliRunner()

CODE = '''\
"""A tiny module."""


def public_fn(x: int) -> int:
    """Double x."""
    return x * 2
'''


def _write_config(tmp_path: Path) -> Path:
    cfg = (
        'version: "1.0.0"\n'
        'root: "."\n'
        "documents:\n"
        '  - id: "guide"\n'
        '    path: "guide.md"\n'
        '    audience: "eng-guide"\n'
        "    code_refs:\n"
        '      - path: "code.py"\n'
        '    region_keys: ["symbols"]\n'
        "backend:\n"
        '  kind: "mock"\n'
    )
    config_path = tmp_path / "cdmon.yaml"
    config_path.write_text(cfg, encoding="utf-8")
    return config_path


def _spec() -> DocumentSpec:
    return DocumentSpec(
        id="guide",
        path="guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )


def _make_fixture(tmp_path: Path, *, clean: bool) -> Path:
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    config_path = _write_config(tmp_path)
    spec = _spec()
    config = MonitorConfig(root=".", documents=(spec,))
    surface = build_document_surface(spec, tmp_path)
    body = symbol_table(surface) if clean else "OUT OF DATE"
    (tmp_path / "guide.md").write_text(
        f"---\ncdm:\n  fingerprint: {surface.surface_hash()}\n---\n"
        "# Guide\n\n"
        "<!-- CDM:BEGIN symbols -->\n"
        f"{body}\n"
        "<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    _ = config
    return config_path


def test_check_exit_1_on_drift(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1
    assert "drift" in result.stdout.lower()


def test_check_exit_0_when_clean(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.stdout
    assert "clean" in result.stdout.lower()


def test_monitor_apply_closes_drift(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["monitor", "--apply"])
    assert result.exit_code == 0, result.stdout
    assert "FIX" in result.stdout
    # The review log was written under the default location.
    assert (tmp_path / ".cdmon" / "review-log.jsonl").is_file()
    # A re-check is now clean.
    assert runner.invoke(app, ["check"]).exit_code == 0


def test_monitor_no_apply_leaves_drift(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["monitor", "--no-apply"])
    assert result.exit_code == 1
    assert "remaining" in result.output.lower()


def test_surface_lists_docs(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["surface"])
    assert result.exit_code == 0, result.stdout
    assert "guide" in result.stdout
    assert "eng-guide" in result.stdout


def test_surface_json(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["surface", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload[0]["doc_id"] == "guide"
    assert "symbols" in payload[0]


def test_report_prints_counts_after_monitor(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["monitor", "--apply"])
    result = runner.invoke(app, ["report"])
    assert result.exit_code == 0, result.stdout
    summary = json.loads(result.stdout)
    assert summary["total"] >= 1
    assert "FIX" in summary["by_verdict"]


def test_report_empty_log(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["report"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["total"] == 0


def test_report_verdict_lists_matching_records(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["monitor", "--apply"])
    result = runner.invoke(app, ["report", "--verdict", "FIX"])
    assert result.exit_code == 0, result.stdout
    assert "FIX record(s)" in result.stdout
    assert "guide" in result.stdout
    assert "cause:" in result.stdout


def test_report_verdict_is_case_insensitive(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["monitor", "--apply"])
    result = runner.invoke(app, ["report", "--verdict", "fix"])
    assert result.exit_code == 0, result.stdout
    assert "FIX record(s)" in result.stdout


def test_report_verdict_no_match_is_clean(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["monitor", "--apply"])
    result = runner.invoke(app, ["report", "--verdict", "ESCALATE"])
    assert result.exit_code == 0, result.stdout
    assert "no ESCALATE records" in result.stdout


def test_report_verdict_json_emits_full_records(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["monitor", "--apply"])
    result = runner.invoke(app, ["report", "--verdict", "FIX", "--json"])
    assert result.exit_code == 0, result.stdout
    records = json.loads(result.stdout)
    assert records and records[0]["verdict"] == "FIX"
    assert records[0]["doc_id"] == "guide"


def test_report_bad_verdict_clean_error(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["report", "--verdict", "BOGUS"])
    assert result.exit_code == 1
    assert "unknown verdict" in result.output
    assert "Traceback" not in result.output


def test_schema_prints_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert "schema_version" in parsed["properties"]


def test_schema_out_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "schema.json"
    result = runner.invoke(app, ["schema", "--out", str(out)])
    assert result.exit_code == 0, result.stdout
    assert out.is_file()
    assert "schema_version" in json.loads(out.read_text(encoding="utf-8"))["properties"]


def test_bad_config_path_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "error:" in result.output
    # A clean message, not a traceback (K8).
    assert "Traceback" not in result.output


def test_surface_bad_config_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["surface", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "error:" in result.output


def test_monitor_bad_config_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["monitor", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "error:" in result.output


def test_report_bad_config_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["report", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "error:" in result.output


# --- CDM-08: layout lint + new-doc scaffolding -------------------------------


def test_new_doc_scaffolds_conformant_in_sync_doc(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["new-doc", "guide"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "guide.md").is_file()
    # The scaffold passes both gates immediately.
    assert runner.invoke(app, ["lint"]).exit_code == 0
    assert runner.invoke(app, ["check"]).exit_code == 0


def test_new_doc_unknown_id_clean_error(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["new-doc", "nope"])
    assert result.exit_code == 1
    assert "no document with id" in result.output
    assert "Traceback" not in result.output


def test_new_doc_refuses_to_clobber(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["new-doc", "guide"]).exit_code == 0
    again = runner.invoke(app, ["new-doc", "guide"])
    assert again.exit_code == 1
    assert "Refusing to overwrite" in again.output
    assert runner.invoke(app, ["new-doc", "guide", "--force"]).exit_code == 0


def test_lint_flags_legacy_doc_then_clean_after_scaffold(
    tmp_path: Path, monkeypatch
) -> None:
    # The legacy fixture lacks the standard front matter + purpose blockquote.
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    bad = runner.invoke(app, ["lint"])
    assert bad.exit_code == 1
    assert "MISSING_SCHEMA_VERSION" in bad.output
    # Re-scaffolding makes it conform.
    assert runner.invoke(app, ["new-doc", "guide", "--force"]).exit_code == 0
    assert runner.invoke(app, ["lint"]).exit_code == 0


def test_lint_fix_stamps_front_matter(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(
        tmp_path, clean=True
    )  # has fingerprint + title, no sv/audience/purpose
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["lint", "--fix"])
    # Front matter is stamped (reported), but the missing purpose remains.
    assert "fixed front matter" in result.output
    assert result.exit_code == 1
    assert "MISSING_PURPOSE" in result.output
    assert "MISSING_SCHEMA_VERSION" not in result.output


def test_lint_bad_config_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["lint", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "error:" in result.output


# --- B-05: `cdmon lint --modes` per-region authority STATE surface -------------


def _write_config_with_human(tmp_path: Path) -> Path:
    cfg = (
        'version: "1.0.0"\n'
        'root: "."\n'
        "documents:\n"
        '  - id: "guide"\n'
        '    path: "guide.md"\n'
        '    audience: "eng-guide"\n'
        "    code_refs:\n"
        '      - path: "code.py"\n'
        '    region_keys: ["symbols"]\n'
        "    region_modes:\n"
        '      symbols: "human"\n'
        "backend:\n"
        '  kind: "mock"\n'
    )
    config_path = tmp_path / "cdmon.yaml"
    config_path.write_text(cfg, encoding="utf-8")
    return config_path


def test_lint_modes_surfaces_state_without_changing_pass_fail(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    _write_config_with_human(tmp_path)
    monkeypatch.chdir(tmp_path)
    # Scaffold a conformant doc so structural lint passes (exit 0).
    assert runner.invoke(app, ["new-doc", "guide"]).exit_code == 0
    result = runner.invoke(app, ["lint", "--modes"])
    assert result.exit_code == 0, result.output  # still clean — --modes is not a gate
    # The mode + advisory state is surfaced.
    assert "guide::symbols" in result.output
    assert "human" in result.output
    assert "advisory" in result.output


def test_lint_modes_does_not_suppress_structural_failures(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    _write_config(tmp_path)  # generated mode, legacy fixture below is non-conformant
    monkeypatch.chdir(tmp_path)
    # A doc missing the standard front matter -> structural failure even with --modes.
    (tmp_path / "guide.md").write_text(
        "# Guide\n\n<!-- CDM:BEGIN symbols -->\nx\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["lint", "--modes"])
    assert result.exit_code == 1, result.output  # structural gate still fires
    assert "guide::symbols" in result.output  # state still surfaced
    assert "generated" in result.output


# --- A-05/06: `cdmon coverage` CLI + `--fail-under` gate ----------------------

# A repo where one file is fully documented, a second public symbol is an
# undocumented gap, and a third is waived with a reason. Drives every basket.
_DOCUMENTED_CODE = '''\
"""Documented module."""


def documented_fn(x: int) -> int:
    """Doubled."""
    return x * 2
'''

_GAP_CODE = '''\
"""Has an undocumented public symbol and a waived one."""


def gap_fn() -> None:
    """Nobody documents me."""


def waived_fn() -> None:
    """Intentionally not documented."""
'''


def _coverage_fixture(tmp_path: Path) -> Path:
    """A repo + config exercising documented / undocumented / waived baskets."""
    (tmp_path / "documented.py").write_text(_DOCUMENTED_CODE, encoding="utf-8")
    (tmp_path / "gaps.py").write_text(_GAP_CODE, encoding="utf-8")
    cfg = (
        'version: "1.0.0"\n'
        'root: "."\n'
        "documents:\n"
        '  - id: "guide"\n'
        '    path: "guide.md"\n'
        '    audience: "eng-guide"\n'
        "    code_refs:\n"
        '      - path: "documented.py"\n'
        "coverage:\n"
        '  include: ["**/*.py"]\n'
        "  waive:\n"
        '    - path: "gaps.py"\n'
        '      symbol: "waived_fn"\n'
        '      reason: "deprecated; scheduled for removal"\n'
    )
    config_path = tmp_path / "cdmon.yaml"
    config_path.write_text(cfg, encoding="utf-8")
    return config_path


def test_coverage_prints_percentages_and_baskets(tmp_path: Path, monkeypatch) -> None:
    _coverage_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["coverage"])
    assert result.exit_code == 0, result.output
    out = result.output
    # Both percentages are surfaced.
    assert "files" in out.lower()
    assert "symbol" in out.lower()
    # The documented symbol is counted, the gap is listed, the waiver named.
    assert "gaps.py::gap_fn" in out
    assert "gaps.py::waived_fn" in out
    assert "deprecated; scheduled for removal" in out


def test_coverage_json_round_trips(tmp_path: Path, monkeypatch) -> None:
    _coverage_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["coverage", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "percent_public_symbols" in payload
    assert "percent_files" in payload
    # A known basket entry is present and correct.
    gaps = {s["path"] + "::" + s["name"] for s in payload["undocumented_symbols"]}
    assert "gaps.py::gap_fn" in gaps
    waived = {s["name"]: s["waived_reason"] for s in payload["waived_symbols"]}
    assert waived["waived_fn"] == "deprecated; scheduled for removal"


def test_coverage_fail_under_below_exits_1(tmp_path: Path, monkeypatch) -> None:
    _coverage_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    # documented_fn documented, gap_fn a gap => 50% public-symbol coverage.
    result = runner.invoke(app, ["coverage", "--fail-under", "90"])
    assert result.exit_code == 1, result.output


def test_coverage_fail_under_above_exits_0(tmp_path: Path, monkeypatch) -> None:
    _coverage_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["coverage", "--fail-under", "10"])
    assert result.exit_code == 0, result.output


def test_coverage_no_fail_under_always_exits_0(tmp_path: Path, monkeypatch) -> None:
    _coverage_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    # Gaps present, but without the gate it is informational (exit 0).
    result = runner.invoke(app, ["coverage"])
    assert result.exit_code == 0, result.output
    assert "gap_fn" in result.output


def test_coverage_bad_config_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["coverage", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "error:" in result.output
    assert "Traceback" not in result.output


def test_coverage_renders_file_baskets(tmp_path: Path, monkeypatch) -> None:
    """An undocumented file and a whole-file waiver both render in the output."""
    (tmp_path / "documented.py").write_text(_DOCUMENTED_CODE, encoding="utf-8")
    (tmp_path / "lonely.py").write_text(_DOCUMENTED_CODE, encoding="utf-8")
    (tmp_path / "vendor.py").write_text(_DOCUMENTED_CODE, encoding="utf-8")
    cfg = (
        'version: "1.0.0"\n'
        'root: "."\n'
        "documents:\n"
        '  - id: "guide"\n'
        '    path: "guide.md"\n'
        '    audience: "eng-guide"\n'
        "    code_refs:\n"
        '      - path: "documented.py"\n'
        "coverage:\n"
        '  include: ["**/*.py"]\n'
        "  waive:\n"
        '    - path: "vendor.py"\n'
        '      reason: "third-party; documented upstream"\n'
    )
    (tmp_path / "cdmon.yaml").write_text(cfg, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["coverage"])
    assert result.exit_code == 0, result.output
    out = result.output
    # lonely.py is an unreferenced, non-waived file (a file-level gap).
    assert "file(s):" in out
    assert "lonely.py" in out
    # vendor.py is a whole-file waiver with its reason.
    assert "vendor.py — third-party; documented upstream" in out


# --- A-08: `cdmon coverage --write [PATH]` manifest writer (K1/K7/K10) --------


def test_coverage_write_creates_manifest(tmp_path: Path, monkeypatch) -> None:
    _coverage_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["coverage", "--write"])
    assert result.exit_code == 0, result.output

    manifest = tmp_path / ".cdmon" / "coverage.json"
    assert manifest.is_file()
    assert str(manifest) in result.output or ".cdmon/coverage.json" in result.output

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    # The A-05 payload is present...
    assert "percent_public_symbols" in payload
    assert "percent_files" in payload
    gaps = {s["path"] + "::" + s["name"] for s in payload["undocumented_symbols"]}
    assert "gaps.py::gap_fn" in gaps
    # ...plus the A-07 suggestions.
    assert "suggestions" in payload
    by_name = {s["name"]: s for s in payload["suggestions"]}
    assert "gap_fn" in by_name
    # gaps.py has no owned sibling (documented.py is a separate file) -> new doc.
    assert by_name["gap_fn"]["is_new_doc"] is True
    assert by_name["gap_fn"]["suggested_doc_id"] == "gaps"


def test_coverage_write_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    _coverage_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(app, ["coverage", "--write"])
    assert first.exit_code == 0, first.output

    manifest = tmp_path / ".cdmon" / "coverage.json"
    before = manifest.read_text(encoding="utf-8")
    before_mtime = manifest.stat().st_mtime_ns

    second = runner.invoke(app, ["coverage", "--write"])
    assert second.exit_code == 0, second.output
    assert "unchanged" in second.output.lower()
    # Content AND mtime identical (not rewritten) — K7.
    assert manifest.read_text(encoding="utf-8") == before
    assert manifest.stat().st_mtime_ns == before_mtime


def test_coverage_write_custom_path(tmp_path: Path, monkeypatch) -> None:
    _coverage_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    target = "out/cov.json"
    result = runner.invoke(app, ["coverage", "--write", target])
    assert result.exit_code == 0, result.output
    manifest = tmp_path / target
    assert manifest.is_file()
    # Valid JSON at the custom path.
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert "suggestions" in payload
    # The default path was NOT written.
    assert not (tmp_path / ".cdmon" / "coverage.json").exists()


def test_coverage_write_default_invocation_stays_read_only(
    tmp_path: Path, monkeypatch
) -> None:
    """Without --write, `coverage` writes nothing (K1)."""
    _coverage_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["coverage"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / ".cdmon" / "coverage.json").exists()


def test_coverage_write_manifest_is_valid_json(tmp_path: Path, monkeypatch) -> None:
    _coverage_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["coverage", "--write"])
    manifest = tmp_path / ".cdmon" / "coverage.json"
    # Round-trips and sorted keys (deterministic, K10).
    text = manifest.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert text == json.dumps(payload, indent=2, sort_keys=True) + "\n"


# --- C-01: `cdmon sync-pr` doc-patch producer --------------------------------


def test_sync_pr_prints_patch_and_heals(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["sync-pr"])
    assert result.exit_code == 0, result.output
    assert "a/guide.md" in result.stdout
    assert "public_fn" in result.stdout
    assert "doc(s) updated" in result.output
    # The doc on disk is now healed.
    assert "OUT OF DATE" not in (tmp_path / "guide.md").read_text(encoding="utf-8")


def test_sync_pr_dry_run_leaves_tree_unchanged(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    before = (tmp_path / "guide.md").read_bytes()
    result = runner.invoke(app, ["sync-pr", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "a/guide.md" in result.stdout  # same patch
    # K1: byte-identical tree.
    assert (tmp_path / "guide.md").read_bytes() == before


def test_sync_pr_out_writes_patch_file(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "docs.patch"
    result = runner.invoke(app, ["sync-pr", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.is_file()
    assert "a/guide.md" in out.read_text(encoding="utf-8")
    assert "wrote patch to" in result.output


def test_sync_pr_clean_repo_empty_patch(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["sync-pr"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == ""  # empty patch
    assert "clean" in result.output


def test_sync_pr_bad_config_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["sync-pr", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "error:" in result.output
    assert "Traceback" not in result.output


# --- C-03: `cdmon open-docs-pr` bot-PR opener --------------------------------


def test_open_docs_pr_dry_run_prints_plan_and_leaves_tree(
    tmp_path: Path, monkeypatch
) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    before = (tmp_path / "guide.md").read_bytes()
    result = runner.invoke(app, ["open-docs-pr", "--dry-run", "--ref", "abc123"])
    assert result.exit_code == 0, result.output
    plan = json.loads(result.stdout)
    assert plan["source_branch"].startswith("cdmon/docs-sync-")
    assert "abc123" in plan["title"]
    assert any(p == "guide.md" for p, _ in plan["files"])
    # --dry-run uses a dry sync: the working tree is byte-identical (K1), no MR.
    assert (tmp_path / "guide.md").read_bytes() == before


def test_open_docs_pr_clean_repo_is_noop(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["open-docs-pr"])
    assert result.exit_code == 0, result.output
    assert "nothing to open" in result.output


def test_open_docs_pr_missing_env_is_loud(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CI_PROJECT_ID", raising=False)
    monkeypatch.delenv("CDMON_GITLAB_TOKEN", raising=False)
    result = runner.invoke(app, ["open-docs-pr"])
    assert result.exit_code != 0
    assert "error:" in result.output
    assert "CI_PROJECT_ID" in result.output
    assert "Traceback" not in result.output


def test_open_docs_pr_submits_via_stubbed_gitlab_leaf(
    tmp_path: Path, monkeypatch
) -> None:
    """End to end: heal + open an MR, with the one real urlopen leaf stubbed (K4)."""
    import code_doc_monitor.pr as pr_mod

    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI_PROJECT_ID", "123")
    monkeypatch.setenv("CDMON_GITLAB_TOKEN", "s3cret")
    monkeypatch.delenv("CI_API_V4_URL", raising=False)

    seen: list[str] = []

    def fake_request(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        seen.append(url)
        if url.endswith("/merge_requests"):
            return {"web_url": "https://gl.example/mr/5"}
        return {}

    monkeypatch.setattr(pr_mod._UrllibGitLabHttp, "request", fake_request)
    result = runner.invoke(app, ["open-docs-pr"])
    assert result.exit_code == 0, result.output
    assert "https://gl.example/mr/5" in result.output
    assert len(seen) == 3  # branch, commit, merge_request
    # The heal really happened (no dry-run on the open path).
    assert "OUT OF DATE" not in (tmp_path / "guide.md").read_text(encoding="utf-8")


# --- E-02: `cdmon register` repo registration client -------------------------


def _write_register_config(tmp_path: Path, *, with_repo_id: bool = True) -> Path:
    central = (
        "central:\n"
        '  sink: "http"\n'
        '  url: "https://central.example"\n'
        '  auth_env: "CDM_TOKEN"\n'
    )
    if with_repo_id:
        central += (
            '  repo_id: "acme/widget"\n'
            '  repo_name: "widget"\n'
            '  repo_commit: "cafef00d"\n'
        )
    cfg = (
        'version: "1.0.0"\n'
        'root: "."\n'
        "documents:\n"
        '  - id: "guide"\n'
        '    path: "guide.md"\n'
        '    audience: "eng-guide"\n'
        "    code_refs:\n"
        '      - path: "code.py"\n'
        '    region_keys: ["symbols"]\n'
        "backend:\n"
        '  kind: "mock"\n' + central
    )
    config_path = tmp_path / "cdmon.yaml"
    config_path.write_text(cfg, encoding="utf-8")
    return config_path


def test_register_dry_run_prints_payload_no_network(
    tmp_path: Path, monkeypatch
) -> None:
    _write_register_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["register", "--dry-run"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "1.0.0"
    assert payload["repo"]["repo_id"] == "acme/widget"
    assert payload["repo"]["commit"] == "cafef00d"


def test_register_submits_via_stubbed_leaf(tmp_path: Path, monkeypatch) -> None:
    """End to end: register a repo with the one real urlopen leaf stubbed (K4)."""
    import code_doc_monitor.registry as registry_mod

    _write_register_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CDM_TOKEN", "s3cret")

    seen: list[tuple[str, str]] = []

    def fake_request(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        seen.append((url, token))
        return {"id": 7}

    monkeypatch.setattr(registry_mod._UrllibRegisterHttp, "request", fake_request)
    result = runner.invoke(app, ["register"])
    assert result.exit_code == 0, result.output
    assert "registered acme/widget" in result.output
    assert seen == [("https://central.example/repos", "s3cret")]


def test_register_missing_repo_id_is_loud(tmp_path: Path, monkeypatch) -> None:
    _write_register_config(tmp_path, with_repo_id=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["register", "--dry-run"])
    assert result.exit_code != 0
    assert "error:" in result.output
    assert "repo_id" in result.output
    assert "Traceback" not in result.output


# --- C-04: `cdmon should-sync` exit codes (proceed 0 / skip 1) ------------------


def test_should_sync_proceeds_on_non_doc_change(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["should-sync", "code.py"])
    assert result.exit_code == 0, result.output


def test_should_sync_skips_on_doc_only_change(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["should-sync", "guide.md"])
    assert result.exit_code == 1


def test_should_sync_reads_files_from_stdin(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    # No FILES args -> read newline-separated paths from stdin. Doc-only -> skip.
    result = runner.invoke(app, ["should-sync"], input="guide.md\n")
    assert result.exit_code == 1
    result = runner.invoke(app, ["should-sync"], input="code.py\n")
    assert result.exit_code == 0, result.output


def test_should_sync_bad_config_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["should-sync", "--config", str(tmp_path / "nope.yaml"), "x.py"]
    )
    assert result.exit_code == 1
    assert "error:" in result.output
    assert "Traceback" not in result.output


# --- C-05: `cdmon monitor --ref` stamps provenance onto records -----------------


def test_monitor_ref_stamps_source_sha(tmp_path: Path, monkeypatch) -> None:
    from code_doc_monitor.reviewlog import read_all

    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["monitor", "--apply", "--ref", "cafe1234"])
    assert result.exit_code == 0, result.output
    records = read_all(tmp_path / ".cdmon" / "review-log.jsonl")
    assert records
    assert all(rec.source_sha == "cafe1234" for rec in records)


def test_monitor_falls_back_to_ci_commit_sha_env(tmp_path: Path, monkeypatch) -> None:
    from code_doc_monitor.reviewlog import read_all

    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI_COMMIT_SHA", "envsha99")
    result = runner.invoke(app, ["monitor", "--apply"])
    assert result.exit_code == 0, result.output
    records = read_all(tmp_path / ".cdmon" / "review-log.jsonl")
    assert records
    assert all(rec.source_sha == "envsha99" for rec in records)


def test_monitor_ref_flag_overrides_env(tmp_path: Path, monkeypatch) -> None:
    from code_doc_monitor.reviewlog import read_all

    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI_COMMIT_SHA", "envsha99")
    result = runner.invoke(app, ["monitor", "--apply", "--ref", "explicit1"])
    assert result.exit_code == 0, result.output
    records = read_all(tmp_path / ".cdmon" / "review-log.jsonl")
    assert all(rec.source_sha == "explicit1" for rec in records)


def test_monitor_no_ref_no_env_leaves_source_sha_none(
    tmp_path: Path, monkeypatch
) -> None:
    from code_doc_monitor.reviewlog import read_all

    _make_fixture(tmp_path, clean=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CI_COMMIT_SHA", raising=False)
    result = runner.invoke(app, ["monitor", "--apply"])
    assert result.exit_code == 0, result.output
    records = read_all(tmp_path / ".cdmon" / "review-log.jsonl")
    assert records
    assert all(rec.source_sha is None for rec in records)


# --- D-01/D-02: `cdmon resolve` (capture the human outcome) --------------------


def _seed_review_log(tmp_path: Path) -> str:
    """Run monitor to write a real review log; return one record_id from it."""
    from code_doc_monitor.reviewlog import read_all

    _make_fixture(tmp_path, clean=False)
    runner.invoke(app, ["monitor", "--apply"])
    records = read_all(tmp_path / ".cdmon" / "review-log.jsonl")
    assert records
    return records[0].record_id


def test_resolve_appends_resolution_and_confirms(tmp_path: Path, monkeypatch) -> None:
    from code_doc_monitor.reviewlog import read_resolutions

    monkeypatch.chdir(tmp_path)
    rid = _seed_review_log(tmp_path)
    result = runner.invoke(
        app, ["resolve", rid, "--resolution", "accepted", "--by", "alice"]
    )
    assert result.exit_code == 0, result.output
    assert rid in result.output
    res = read_resolutions(tmp_path / ".cdmon" / "resolutions.jsonl")
    assert len(res) == 1
    assert res[0].record_id == rid
    assert res[0].resolution.value == "accepted"
    assert res[0].resolved_by == "alice"


def test_resolve_unknown_id_is_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_review_log(tmp_path)
    result = runner.invoke(app, ["resolve", "doesnotexist", "--resolution", "rejected"])
    assert result.exit_code == 1
    assert "error:" in result.output
    # No traceback leaked (K8).
    assert "Traceback" not in result.output
    # Nothing was written.
    assert not (tmp_path / ".cdmon" / "resolutions.jsonl").exists()


def test_resolve_overridden_stores_text(tmp_path: Path, monkeypatch) -> None:
    from code_doc_monitor.reviewlog import read_resolutions

    monkeypatch.chdir(tmp_path)
    rid = _seed_review_log(tmp_path)
    result = runner.invoke(
        app,
        [
            "resolve",
            rid,
            "--resolution",
            "overridden",
            "--text",
            "the human final body",
            "--note",
            "reworded",
        ],
    )
    assert result.exit_code == 0, result.output
    res = read_resolutions(tmp_path / ".cdmon" / "resolutions.jsonl")
    assert res[0].resolved_text == "the human final body"
    assert res[0].note == "reworded"


def test_resolve_bad_resolution_is_clean_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rid = _seed_review_log(tmp_path)
    result = runner.invoke(app, ["resolve", rid, "--resolution", "bogus"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output


def test_resolve_injected_now_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    from code_doc_monitor import cli as cli_mod
    from code_doc_monitor.reviewlog import read_resolutions

    monkeypatch.chdir(tmp_path)
    rid = _seed_review_log(tmp_path)
    monkeypatch.setattr(cli_mod, "_now", lambda: "2026-06-05T12:00:00+00:00")
    runner.invoke(app, ["resolve", rid, "--resolution", "accepted"])
    res = read_resolutions(tmp_path / ".cdmon" / "resolutions.jsonl")
    assert res[0].resolved_at == "2026-06-05T12:00:00+00:00"


def test_resolve_custom_log_path(tmp_path: Path, monkeypatch) -> None:
    from code_doc_monitor.reviewlog import read_resolutions

    monkeypatch.chdir(tmp_path)
    rid = _seed_review_log(tmp_path)
    custom = tmp_path / "out" / "res.jsonl"
    result = runner.invoke(
        app, ["resolve", rid, "--resolution", "accepted", "--log", str(custom)]
    )
    assert result.exit_code == 0, result.output
    assert custom.is_file()
    assert read_resolutions(custom)[0].record_id == rid


def test_report_shows_resolved_unresolved_counts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rid = _seed_review_log(tmp_path)
    runner.invoke(app, ["resolve", rid, "--resolution", "accepted"])
    result = runner.invoke(app, ["report"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["resolved"] == 1
    assert payload["unresolved"] >= 0


# --- D-05/D-06: `cdmon promotions` (read-only view of promotion candidates) ---


def _seed_resolved(
    tmp_path: Path,
    *,
    n: int,
    resolution: str,
    doc_id: str = "guide",
    drift_kind: str = "HASH",
) -> None:
    """Append `n` resolved records of one shape (each a distinct surface_hash)."""
    from code_doc_monitor.reviewlog import (
        DEFAULT_RESOLUTIONS_PATH,
        append,
        append_resolution,
    )
    from code_doc_monitor.schema import (
        Resolution,
        ResolutionRecord,
        ReviewRecord,
        Verdict,
    )

    log = tmp_path / ".cdmon" / "review-log.jsonl"
    res = tmp_path / DEFAULT_RESOLUTIONS_PATH
    for i in range(n):
        rid = f"{doc_id}-{drift_kind}-{i}"
        append(
            log,
            ReviewRecord(
                record_id=rid,
                doc_id=doc_id,
                doc_path=f"{doc_id}.md",
                audience=Audience.ENG_GUIDE,
                drift_kind=drift_kind,
                drift_detail="docstring changed",
                cause="c",
                verdict=Verdict.INVALIDATE,
                fix=None,
                surface_hash=f"h{i}",
                backend_kind="mock",
                detected_at="2026-06-01T00:00:00Z",
                resolved_at="2026-06-01T00:00:01Z",
                config_snapshot={},
            ),
        )
        append_resolution(
            res,
            ResolutionRecord(
                record_id=rid,
                resolution=Resolution(resolution),
                resolved_at="2026-06-05T00:00:00Z",
            ),
        )


def test_promotions_lists_candidate(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    _seed_resolved(tmp_path, n=3, resolution="invalidated")
    result = runner.invoke(app, ["promotions"])
    assert result.exit_code == 0, result.output
    assert "guide" in result.output
    assert "HASH" in result.output
    assert "invalidated" in result.output


def test_promotions_json(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    _seed_resolved(tmp_path, n=3, resolution="invalidated")
    result = runner.invoke(app, ["promotions", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert payload[0]["doc_id"] == "guide"
    assert payload[0]["resolution"] == "invalidated"
    assert payload[0]["count"] == 3


def test_promotions_min_count_honored(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    _seed_resolved(tmp_path, n=2, resolution="invalidated")
    # Default min-count 3 -> none.
    assert "no promotable" in runner.invoke(app, ["promotions"]).output.lower()
    # --min-count 2 -> one candidate.
    result = runner.invoke(app, ["promotions", "--min-count", "2", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["count"] == 2


def test_promotions_empty(tmp_path: Path, monkeypatch) -> None:
    _make_fixture(tmp_path, clean=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["promotions"])
    assert result.exit_code == 0
    assert "no promotable" in result.output.lower()


# --- H-04: `cdmon surface-gaps` (coverage gaps -> tracker issue) ------------


def test_surface_gaps_dry_run_lists_gap(tmp_path: Path, monkeypatch) -> None:
    _coverage_fixture(tmp_path)  # gaps.py::gap_fn is an undocumented public gap
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["surface-gaps", "--dry-run"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "undocumented public symbol" in payload["title"]
    assert "gaps.py::gap_fn" in payload["body"]
    assert payload["labels"] == ["documentation"]


def test_surface_gaps_no_gaps_is_noop(tmp_path: Path, monkeypatch) -> None:
    # Whole-file ref documents every public symbol -> no gaps.
    (tmp_path / "documented.py").write_text(_DOCUMENTED_CODE, encoding="utf-8")
    cfg = (
        'version: "1.0.0"\n'
        'root: "."\n'
        "documents:\n"
        '  - id: "guide"\n'
        '    path: "guide.md"\n'
        '    audience: "eng-guide"\n'
        "    code_refs:\n"
        '      - path: "documented.py"\n'
        "coverage:\n"
        '  include: ["documented.py"]\n'
    )
    (tmp_path / "cdmon.yaml").write_text(cfg, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["surface-gaps", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "no coverage gaps" in result.output.lower()


def test_surface_gaps_missing_env_is_loud(tmp_path: Path, monkeypatch) -> None:
    _coverage_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CI_PROJECT_ID", raising=False)
    monkeypatch.delenv("CDMON_GITLAB_TOKEN", raising=False)
    # Real submit path with no provider env -> loud K8, clean exit 1.
    result = runner.invoke(app, ["surface-gaps"])
    assert result.exit_code == 1
    assert "error:" in result.output.lower()


def test_surface_gaps_bad_provider_is_loud(tmp_path: Path, monkeypatch) -> None:
    _coverage_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["surface-gaps", "--provider", "bitbucket"])
    assert result.exit_code == 1
    assert "bitbucket" in result.output


def test_surface_gaps_opens_issue_github(tmp_path: Path, monkeypatch) -> None:
    _coverage_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/widget")
    monkeypatch.setenv("CDMON_GITHUB_TOKEN", "ghtok")
    import code_doc_monitor.issues as issues_mod

    def fake_request(self, method, url, *, body, token):
        return {"html_url": "https://github.com/acme/widget/issues/9"}

    monkeypatch.setattr(issues_mod._UrllibGitHubIssueHttp, "request", fake_request)
    result = runner.invoke(app, ["surface-gaps", "--provider", "github"])
    assert result.exit_code == 0, result.output
    assert "issues/9" in result.output


def test_build_renders_html_twin(tmp_path: Path, monkeypatch) -> None:
    # FEAT-CLI-006: `cdmon build` renders every html:true doc to a .html twin.
    cfg = (
        'version: "1.0.0"\n'
        'root: "."\n'
        "documents:\n"
        '  - id: "guide"\n'
        '    path: "guide.md"\n'
        '    audience: "user-guide"\n'
        "    html: true\n"
    )
    (tmp_path / "cdmon.yaml").write_text(cfg, encoding="utf-8")
    (tmp_path / "guide.md").write_text(
        "---\ncdm:\n  fingerprint: x\n---\n\n# Guide\n\n> A user guide.\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 0, result.output
    assert "built 1 HTML twin(s)" in result.output
    twin = tmp_path / "guide.html"
    assert twin.is_file()
    assert '<h1 id="guide">Guide</h1>' in twin.read_text(encoding="utf-8")


def test_serve_loud_without_config_cdmon_index(tmp_path: Path, monkeypatch) -> None:
    # FEAT-CLI-013: `cdmon serve` loud-guards (exit 1) when cwd has no
    # config/cdmon/index.yaml — never binds a socket on this path.
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 1
    assert "no config/cdmon/index.yaml" in result.output
