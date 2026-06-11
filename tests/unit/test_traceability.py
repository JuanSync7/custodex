"""Tests for code_doc_monitor.traceability (EPIC R, R-03).

The feature ⇄ demo/test/source coverage matrix: a pure, deterministic engine
that scans evidence files for the inline ``Feature:`` tag convention, crosses
them against the golden catalog, and reports gaps + unknown refs (K8). Pure,
never imports the scanned files (K1); no new dependency (K0, pydantic only);
sorted/clock-free output (K10). Written before the implementation (K9, TDD).

Features: FEAT-REFERENCE-003
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from code_doc_monitor.cli import app
from code_doc_monitor.featurecatalog import Feature, FeatureCatalog
from code_doc_monitor.traceability import (
    _TAG_RE,
    FEATURE_REF_RE,
    EvidenceKind,
    FeatureRef,
    TraceMatrix,
    build_matrix,
    render_matrix_md,
    scan_refs,
)
from tests._repo import REPO_ROOT

runner = CliRunner()

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _feat(fid: str, subsystem: str = "extract", module: str = "extract") -> Feature:
    return Feature(
        id=fid,
        title=f"T {fid}",
        summary=f"S {fid}.",
        subsystem=subsystem,
        modules=(module,),
    )


def _write_catalog(root: Path, *feats: Feature) -> Path:
    """Write a ``catalog/`` dir with one yaml file holding ``feats``."""
    import yaml

    d = root / "catalog"
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "features": [
            {
                "id": f.id,
                "title": f.title,
                "summary": f.summary,
                "subsystem": f.subsystem,
                "modules": list(f.modules),
            }
            for f in feats
        ]
    }
    (d / "seed.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
    return d


# --------------------------------------------------------------------------
# unit — the tag regexes
# --------------------------------------------------------------------------


def test_unit_feature_ref_re_matches_well_formed_id() -> None:
    assert FEATURE_REF_RE.search("see FEAT-EXTRACT-001 here")
    assert FEATURE_REF_RE.search("FEAT-CONFIGV2-042")
    assert not FEATURE_REF_RE.search("FEAT-extract-001")  # lowercase
    assert not FEATURE_REF_RE.search("FEAT-EXTRACT-1")  # not 3 digits


def test_unit_tag_re_matches_single_marker() -> None:
    m = _TAG_RE.search("    Feature: FEAT-EXTRACT-001")
    assert m is not None
    assert "FEAT-EXTRACT-001" in m.group("ids")


def test_unit_tag_re_matches_plural_marker_and_multiple_ids() -> None:
    m = _TAG_RE.search("# Features: FEAT-EXTRACT-001, FEAT-DRIFT-002")
    assert m is not None
    ids = FEATURE_REF_RE.findall(m.group("ids"))
    assert ids == ["FEAT-EXTRACT-001", "FEAT-DRIFT-002"]


def test_unit_tag_re_is_case_insensitive_marker() -> None:
    assert _TAG_RE.search("feature: FEAT-EXTRACT-001")
    assert _TAG_RE.search("FEATURE: FEAT-EXTRACT-001")


def test_unit_bare_mention_is_not_a_reference() -> None:
    # A bare FEAT-id WITHOUT the `Feature:` marker is prose, NOT evidence.
    assert _TAG_RE.search("This relates to FEAT-EXTRACT-001 somehow.") is None
    # But FEATURE_REF_RE alone DOES see the bare id (the marker disambiguates).
    assert FEATURE_REF_RE.search("This relates to FEAT-EXTRACT-001 somehow.")


# --------------------------------------------------------------------------
# unit — scan_refs over a tmp tree
# --------------------------------------------------------------------------


def test_unit_scan_refs_finds_tagged_ids_with_path_line_kind(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        '"""mod.\n\nFeature: FEAT-EXTRACT-001\n"""\n', encoding="utf-8"
    )
    refs = scan_refs(tmp_path, EvidenceKind.TEST)
    assert len(refs) == 1
    r = refs[0]
    assert r.feature_id == "FEAT-EXTRACT-001"
    assert r.path == "a.py"
    assert r.kind is EvidenceKind.TEST
    assert r.line == 3  # 1-based


def test_unit_scan_refs_bare_mention_ignored(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("# just FEAT-EXTRACT-001 in a comment\n", "utf-8")
    assert scan_refs(tmp_path, EvidenceKind.TEST) == []


def test_unit_scan_refs_multiple_ids_one_line(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text(
        "Features: FEAT-EXTRACT-001, FEAT-DRIFT-002\n", "utf-8"
    )
    refs = scan_refs(tmp_path, EvidenceKind.DEMO)
    assert [r.feature_id for r in refs] == ["FEAT-DRIFT-002", "FEAT-EXTRACT-001"]


def test_unit_scan_refs_ignores_other_suffixes(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("Feature: FEAT-EXTRACT-001\n", "utf-8")
    assert scan_refs(tmp_path, EvidenceKind.TEST) == []


def test_unit_scan_refs_custom_suffixes(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("Feature: FEAT-EXTRACT-001\n", "utf-8")
    refs = scan_refs(tmp_path, EvidenceKind.TEST, suffixes=(".txt",))
    assert [r.feature_id for r in refs] == ["FEAT-EXTRACT-001"]


def test_unit_scan_refs_recurses_and_sorts(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "z.py").write_text("Feature: FEAT-EXTRACT-001\n", "utf-8")
    (tmp_path / "sub" / "a.py").write_text("Feature: FEAT-DRIFT-002\n", "utf-8")
    refs = scan_refs(tmp_path, EvidenceKind.TEST)
    # sorted by (path, line) — repo-relative posix paths (K10)
    assert [r.path for r in refs] == ["sub/a.py", "z.py"]


def test_unit_scan_refs_missing_root_is_empty(tmp_path: Path) -> None:
    assert scan_refs(tmp_path / "nope", EvidenceKind.TEST) == []


# --------------------------------------------------------------------------
# unit — FeatureRef / TraceMatrix models
# --------------------------------------------------------------------------


def test_unit_feature_ref_frozen_and_forbids_extra() -> None:
    r = FeatureRef(
        feature_id="FEAT-EXTRACT-001", path="a.py", kind=EvidenceKind.TEST, line=1
    )
    with pytest.raises(ValidationError):
        r.line = 2  # type: ignore[misc]
    with pytest.raises(ValidationError):
        FeatureRef(
            feature_id="FEAT-EXTRACT-001",
            path="a.py",
            kind=EvidenceKind.TEST,
            line=1,
            bogus="x",  # type: ignore[call-arg]
        )


def _matrix(catalog_ids: tuple[str, ...], refs: tuple[FeatureRef, ...]) -> TraceMatrix:
    return TraceMatrix(catalog_ids=catalog_ids, refs=refs)


def test_unit_matrix_accessors_and_is_complete() -> None:
    refs = (
        FeatureRef(
            feature_id="FEAT-EXTRACT-001", path="t.py", kind=EvidenceKind.TEST, line=1
        ),
        FeatureRef(
            feature_id="FEAT-EXTRACT-001", path="d.py", kind=EvidenceKind.DEMO, line=1
        ),
    )
    m = _matrix(("FEAT-EXTRACT-001",), refs)
    assert m.tests_for("FEAT-EXTRACT-001") == ("t.py",)
    assert m.demos_for("FEAT-EXTRACT-001") == ("d.py",)
    assert m.features_without_test() == ()
    assert m.features_without_demo() == ()
    assert m.unknown_refs() == ()
    assert m.is_complete() is True


def test_unit_matrix_gaps_make_incomplete() -> None:
    m = _matrix(("FEAT-EXTRACT-001",), ())
    assert m.features_without_test() == ("FEAT-EXTRACT-001",)
    assert m.features_without_demo() == ("FEAT-EXTRACT-001",)
    assert m.is_complete() is False


def test_unit_matrix_unknown_ref_is_loud_gap() -> None:
    refs = (
        FeatureRef(
            feature_id="FEAT-NOPE-999", path="t.py", kind=EvidenceKind.TEST, line=1
        ),
    )
    m = _matrix(("FEAT-EXTRACT-001",), refs)
    unknown = m.unknown_refs()
    assert len(unknown) == 1 and unknown[0].feature_id == "FEAT-NOPE-999"
    # an unknown ref alone makes the matrix incomplete (K8)
    assert m.is_complete() is False


# --------------------------------------------------------------------------
# integration — build_matrix over a fixture catalog + tagged test + demo
# --------------------------------------------------------------------------


def _gap_fixture(tmp_path: Path) -> tuple[FeatureCatalog, Path, Path]:
    catalog = FeatureCatalog(
        features=(_feat("FEAT-EXTRACT-001"), _feat("FEAT-DRIFT-002", "drift", "drift"))
    )
    tests_root = tmp_path / "tests"
    demo_root = tmp_path / "demo"
    tests_root.mkdir()
    demo_root.mkdir()
    # F1 tagged in BOTH a test and a demo; F2 tagged NOWHERE; a bogus id in a test.
    (tests_root / "test_x.py").write_text(
        '"""Feature: FEAT-EXTRACT-001\n\nFeature: FEAT-NOPE-999\n"""\n', "utf-8"
    )
    (demo_root / "walk.py").write_text("# Feature: FEAT-EXTRACT-001\n", "utf-8")
    return catalog, tests_root, demo_root


def test_integration_build_matrix_covered_gap_and_unknown(tmp_path: Path) -> None:
    catalog, tests_root, demo_root = _gap_fixture(tmp_path)
    m = build_matrix(catalog, tests_root=tests_root, demo_root=demo_root)
    assert m.catalog_ids == ("FEAT-DRIFT-002", "FEAT-EXTRACT-001")
    # F1 is covered both ways
    assert m.tests_for("FEAT-EXTRACT-001")
    assert m.demos_for("FEAT-EXTRACT-001")
    # F2 is a gap both ways
    assert "FEAT-DRIFT-002" in m.features_without_test()
    assert "FEAT-DRIFT-002" in m.features_without_demo()
    # the bogus id surfaces as an unknown ref
    assert [r.feature_id for r in m.unknown_refs()] == ["FEAT-NOPE-999"]
    assert m.is_complete() is False


def test_integration_build_matrix_complete_when_all_covered(tmp_path: Path) -> None:
    catalog = FeatureCatalog(features=(_feat("FEAT-EXTRACT-001"),))
    tests_root = tmp_path / "tests"
    demo_root = tmp_path / "demo"
    tests_root.mkdir()
    demo_root.mkdir()
    (tests_root / "t.py").write_text("Feature: FEAT-EXTRACT-001\n", "utf-8")
    (demo_root / "d.py").write_text("Feature: FEAT-EXTRACT-001\n", "utf-8")
    m = build_matrix(catalog, tests_root=tests_root, demo_root=demo_root)
    assert m.is_complete() is True


def test_integration_build_matrix_with_source_root(tmp_path: Path) -> None:
    catalog = FeatureCatalog(features=(_feat("FEAT-EXTRACT-001"),))
    tests_root = tmp_path / "tests"
    demo_root = tmp_path / "demo"
    source_root = tmp_path / "src"
    for d in (tests_root, demo_root, source_root):
        d.mkdir()
    (source_root / "m.py").write_text("# Feature: FEAT-EXTRACT-001\n", "utf-8")
    m = build_matrix(
        catalog, tests_root=tests_root, demo_root=demo_root, source_root=source_root
    )
    assert any(r.kind is EvidenceKind.SOURCE for r in m.refs)


def test_integration_render_matrix_md_pure_and_lists_ids_and_gaps(
    tmp_path: Path,
) -> None:
    catalog, tests_root, demo_root = _gap_fixture(tmp_path)
    m = build_matrix(catalog, tests_root=tests_root, demo_root=demo_root)
    out1 = render_matrix_md(m)
    out2 = render_matrix_md(m)
    assert out1 == out2  # deterministic (K10)
    assert "FEAT-EXTRACT-001" in out1 and "FEAT-DRIFT-002" in out1
    assert "Gaps" in out1
    assert "FEAT-NOPE-999" in out1  # the unknown ref is reported


def test_integration_render_matrix_md_complete_says_none(tmp_path: Path) -> None:
    catalog = FeatureCatalog(features=(_feat("FEAT-EXTRACT-001"),))
    tests_root = tmp_path / "tests"
    demo_root = tmp_path / "demo"
    tests_root.mkdir()
    demo_root.mkdir()
    (tests_root / "t.py").write_text("Feature: FEAT-EXTRACT-001\n", "utf-8")
    (demo_root / "d.py").write_text("Feature: FEAT-EXTRACT-001\n", "utf-8")
    m = build_matrix(catalog, tests_root=tests_root, demo_root=demo_root)
    out = render_matrix_md(m)
    assert "COMPLETE" in out
    assert "None — every feature" in out


# --------------------------------------------------------------------------
# system / e2e — `cdmon trace` over a tmp fixture via the Typer CLI runner
# --------------------------------------------------------------------------


def _cli_fixture(tmp_path: Path, *, complete: bool) -> None:
    """Lay out catalog/ + tests/ + demo/ under tmp_path for `cdmon trace`."""
    _write_catalog(
        tmp_path / "feature-doc", _feat("FEAT-EXTRACT-001", module="extract")
    )
    tests_root = tmp_path / "tests"
    demo_root = tmp_path / "demo"
    tests_root.mkdir()
    demo_root.mkdir()
    (tests_root / "t.py").write_text("Feature: FEAT-EXTRACT-001\n", "utf-8")
    if complete:
        (demo_root / "d.py").write_text("Feature: FEAT-EXTRACT-001\n", "utf-8")


def test_system_trace_exit_0_when_complete(tmp_path: Path, monkeypatch) -> None:
    _cli_fixture(tmp_path, complete=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["trace", "--fail-on-gap"])
    assert result.exit_code == 0, result.stdout
    assert "COMPLETE" in result.stdout


def test_system_trace_nonzero_on_gap(tmp_path: Path, monkeypatch) -> None:
    _cli_fixture(tmp_path, complete=False)  # no demo → gap
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["trace", "--fail-on-gap"])
    assert result.exit_code != 0


def test_system_trace_without_fail_on_gap_exits_0_despite_gap(
    tmp_path: Path, monkeypatch
) -> None:
    _cli_fixture(tmp_path, complete=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["trace"])
    assert result.exit_code == 0, result.stdout


def test_system_trace_json_reflects_matrix(tmp_path: Path, monkeypatch) -> None:
    _cli_fixture(tmp_path, complete=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["trace", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["catalog_ids"] == ["FEAT-EXTRACT-001"]
    assert "FEAT-EXTRACT-001" in payload["features_without_demo"]


def test_system_trace_loud_on_missing_catalog(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # no feature-doc/catalog
    result = runner.invoke(app, ["trace"])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower() or "error" in (result.stderr or "").lower()


def test_system_trace_on_real_tree_runs(monkeypatch) -> None:
    # Against the real repo tree it MUST run and exit 0 WITHOUT --fail-on-gap
    # (real tests/demos are not annotated until R-04/R-05 → ~100% gaps is fine).
    repo_root = REPO_ROOT
    if not (repo_root / "feature-doc" / "catalog").is_dir():
        pytest.skip("no feature-doc/catalog seed yet")
    monkeypatch.chdir(repo_root)
    result = runner.invoke(app, ["trace"])
    assert result.exit_code == 0, result.stdout
