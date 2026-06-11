"""Tests for code_doc_monitor.featurecatalog (EPIC R, R-01).

The golden feature-catalog loader: a frozen, typed ``Feature`` model and a
deterministic, loud (K8) ``load_catalog`` over ``feature-doc/catalog/*.yaml``.
Pure with no FS mutation (K1), no new dependency (K0, pydantic+pyyaml only),
sorted/clock-free output (K10). Written before the implementation (K9, TDD).

Features: FEAT-REFERENCE-001, FEAT-REFERENCE-002
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from code_doc_monitor.errors import CatalogError, CodeDocMonitorError
from code_doc_monitor.featurecatalog import (
    FEATURE_ID_RE,
    Feature,
    FeatureCatalog,
    load_catalog,
    render_features_md,
)
from tests._repo import REPO_ROOT

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

_GOOD = {
    "id": "FEAT-EXTRACT-001",
    "title": "Audience-aware code surface",
    "summary": "Builds a per-document, audience-filtered surface from the AST.",
    "subsystem": "extract",
    "modules": ["extract"],
    "constraints": ["K0", "K3"],
}


def _write_catalog(root: Path, **files: str) -> Path:
    """Create ``root/catalog/<name>.yaml`` for each kw and return the dir."""
    d = root / "catalog"
    d.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (d / f"{name}.yaml").write_text(text, encoding="utf-8")
    return d


def _feature_yaml(*bodies: str) -> str:
    return "features:\n" + "".join(bodies)


def _one(
    fid: str = "FEAT-EXTRACT-001",
    subsystem: str = "extract",
    module: str = "extract",
) -> str:
    return (
        f"  - id: {fid}\n"
        f"    title: T {fid}\n"
        f"    summary: S {fid}.\n"
        f"    subsystem: {subsystem}\n"
        f"    modules: [{module}]\n"
    )


# --------------------------------------------------------------------------
# unit — the Feature model
# --------------------------------------------------------------------------


def test_unit_feature_id_pattern_constant() -> None:
    assert FEATURE_ID_RE.match("FEAT-EXTRACT-001")
    assert FEATURE_ID_RE.match("FEAT-CONFIGV2-042")
    assert not FEATURE_ID_RE.match("FEAT-extract-001")  # lowercase subsystem
    assert not FEATURE_ID_RE.match("FEAT-EXTRACT-1")  # not 3 digits
    assert not FEATURE_ID_RE.match("EXTRACT-001")  # missing prefix


def test_unit_feature_accepts_valid() -> None:
    f = Feature(**_GOOD)
    assert f.id == "FEAT-EXTRACT-001"
    assert f.modules == ("extract",)
    assert f.status == "implemented"  # default
    assert f.demos == () and f.tests == ()


def test_unit_feature_is_frozen_and_forbids_extra() -> None:
    f = Feature(**_GOOD)
    with pytest.raises(ValidationError):
        f.title = "mutated"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Feature(**{**_GOOD, "bogus": "x"})


def test_unit_feature_bad_id_rejected() -> None:
    with pytest.raises(ValidationError):
        Feature(**{**_GOOD, "id": "FEAT-extract-1"})


def test_unit_feature_empty_modules_rejected() -> None:
    with pytest.raises(ValidationError):
        Feature(**{**_GOOD, "modules": []})


def test_unit_feature_bad_status_rejected() -> None:
    with pytest.raises(ValidationError):
        Feature(**{**_GOOD, "status": "wip"})


# --------------------------------------------------------------------------
# unit — FeatureCatalog accessors
# --------------------------------------------------------------------------


def test_unit_catalog_by_id_and_miss() -> None:
    a = Feature(**_GOOD)
    b = Feature(
        **{**_GOOD, "id": "FEAT-DRIFT-001", "subsystem": "drift", "modules": ["drift"]}
    )
    cat = FeatureCatalog(features=(a, b))
    assert cat.by_id("FEAT-DRIFT-001") is b
    with pytest.raises(CatalogError):
        cat.by_id("FEAT-NOPE-999")


def test_unit_catalog_by_subsystem_grouping() -> None:
    a = Feature(**_GOOD)
    b = Feature(
        **{**_GOOD, "id": "FEAT-DRIFT-001", "subsystem": "drift", "modules": ["drift"]}
    )
    cat = FeatureCatalog(features=(a, b))
    groups = cat.by_subsystem()
    assert set(groups) == {"extract", "drift"}
    assert groups["extract"] == (a,)


def test_unit_render_features_md_pure_and_stable() -> None:
    a = Feature(**_GOOD)
    b = Feature(
        **{**_GOOD, "id": "FEAT-DRIFT-001", "subsystem": "drift", "modules": ["drift"]}
    )
    cat = FeatureCatalog(features=(a, b))
    out1 = render_features_md(cat)
    out2 = render_features_md(cat)
    assert out1 == out2  # deterministic (K10)
    assert "FEAT-EXTRACT-001" in out1 and "FEAT-DRIFT-001" in out1
    assert "extract" in out1 and "drift" in out1


# --------------------------------------------------------------------------
# integration — load_catalog over a real on-disk tree
# --------------------------------------------------------------------------


def test_integration_load_aggregates_and_sorts(tmp_path: Path) -> None:
    d = _write_catalog(
        tmp_path,
        b_drift=_feature_yaml(_one("FEAT-DRIFT-001", "drift", "drift")),
        a_extract=_feature_yaml(_one("FEAT-EXTRACT-002"), _one("FEAT-EXTRACT-001")),
    )
    cat = load_catalog(d)
    # sorted by id regardless of file order / in-file order (K10)
    assert [f.id for f in cat.features] == [
        "FEAT-DRIFT-001",
        "FEAT-EXTRACT-001",
        "FEAT-EXTRACT-002",
    ]


def test_integration_duplicate_id_is_loud(tmp_path: Path) -> None:
    d = _write_catalog(
        tmp_path,
        one=_feature_yaml(_one("FEAT-EXTRACT-001")),
        two=_feature_yaml(_one("FEAT-EXTRACT-001")),
    )
    with pytest.raises(CatalogError) as ei:
        load_catalog(d)
    assert "FEAT-EXTRACT-001" in str(ei.value)


def test_integration_unknown_module_is_loud(tmp_path: Path) -> None:
    d = _write_catalog(tmp_path, x=_feature_yaml(_one(module="not_a_real_module")))
    with pytest.raises(CatalogError) as ei:
        load_catalog(d, known_modules={"extract", "drift"})
    assert "not_a_real_module" in str(ei.value)


def test_integration_known_module_ok(tmp_path: Path) -> None:
    d = _write_catalog(tmp_path, x=_feature_yaml(_one()))
    cat = load_catalog(d, known_modules={"extract"})
    assert cat.features[0].id == "FEAT-EXTRACT-001"


def test_integration_missing_dir_is_loud(tmp_path: Path) -> None:
    with pytest.raises(CatalogError):
        load_catalog(tmp_path / "nope")


def test_integration_empty_dir_is_loud(tmp_path: Path) -> None:
    d = tmp_path / "catalog"
    d.mkdir()
    with pytest.raises(CatalogError):
        load_catalog(d)  # no *.yaml → loud, never a silent empty catalog (K8)


def test_integration_malformed_yaml_is_loud(tmp_path: Path) -> None:
    d = _write_catalog(tmp_path, bad="features:\n  - id: [unclosed\n")
    with pytest.raises(CatalogError):
        load_catalog(d)


def test_integration_bad_id_in_file_names_file(tmp_path: Path) -> None:
    d = _write_catalog(tmp_path, bad=_feature_yaml(_one("FEAT-bad-1")))
    with pytest.raises(CatalogError) as ei:
        load_catalog(d)
    assert "bad.yaml" in str(ei.value)


def test_integration_catalogerror_is_cdm_error() -> None:
    assert issubclass(CatalogError, CodeDocMonitorError)


# --------------------------------------------------------------------------
# integration — the REAL seed catalog loads clean against real modules
# --------------------------------------------------------------------------


def _real_catalog_dir() -> Path:
    # tests/ -> repo root -> feature-doc/catalog
    return REPO_ROOT / "feature-doc" / "catalog"


def _real_modules() -> set[str]:
    import pkgutil

    import code_doc_monitor as pkg

    return {m.name for m in pkgutil.iter_modules(pkg.__path__)}


def test_integration_real_seed_catalog_loads() -> None:
    d = _real_catalog_dir()
    if not d.is_dir():
        pytest.skip("no feature-doc/catalog seed yet")
    cat = load_catalog(d, known_modules=_real_modules())
    assert len(cat.features) >= 1
    # every feature names only real modules + a unique, well-formed id
    seen: set[str] = set()
    for f in cat.features:
        assert FEATURE_ID_RE.match(f.id)
        assert f.id not in seen
        seen.add(f.id)
