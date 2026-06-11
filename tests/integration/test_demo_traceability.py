"""R-04 — the demo catalog (`demo/DEMOS.md`) maps EVERY feature to a demo case.

R-03 built the traceability engine; R-04 closes the DEMO side of the matrix:
``demo/DEMOS.md`` enumerates observable ``DEMO-NNN`` cases, each ending in an
inline ``Features: <id>...`` tag line that :func:`traceability.scan_refs` picks
up. This test asserts the validable goal of the slice purely over the public
traceability API (no line counts, no prose matching):

* ``demo/DEMOS.md`` exists;
* ``scan_refs(demo, DEMO)`` finds at least one ref (the catalog is wired);
* every demo-tagged id is a REAL catalog id (no unknown refs, K8); and
* ``build_matrix(...).features_without_demo() == ()`` — every one of the 186
  catalogued features is demonstrated by at least one case.

The TEST side of the matrix is intentionally NOT asserted here (R-05 tags the
tests); only the demo coverage is in scope for R-04.

Features: FEAT-REFERENCE-001
"""

from __future__ import annotations

import pkgutil

import code_doc_monitor as _pkg
from code_doc_monitor.featurecatalog import load_catalog
from code_doc_monitor.traceability import EvidenceKind, build_matrix, scan_refs
from tests._repo import REPO_ROOT

_REPO_ROOT = REPO_ROOT
_DEMO_DIR = _REPO_ROOT / "demo"
_DEMOS_MD = _DEMO_DIR / "DEMOS.md"
_CATALOG_DIR = _REPO_ROOT / "feature-doc" / "catalog"


def _catalog() -> object:
    known = {m.name for m in pkgutil.iter_modules(_pkg.__path__)}
    return load_catalog(_CATALOG_DIR, known_modules=known)


def test_demos_md_exists() -> None:
    assert _DEMOS_MD.is_file(), "demo/DEMOS.md must exist (the demo catalog)"


def test_demo_scan_finds_feature_refs() -> None:
    refs = scan_refs(_DEMO_DIR, EvidenceKind.DEMO)
    assert refs, "demo/ must carry at least one inline `Features:` tag"
    # Every scanned ref is a DEMO ref over a real demo file.
    assert all(r.kind is EvidenceKind.DEMO for r in refs)


def test_no_unknown_demo_refs() -> None:
    """Every id tagged in the demo is a real catalog id (no typos — K8)."""
    catalog = _catalog()
    matrix = build_matrix(catalog, tests_root=_REPO_ROOT / "tests", demo_root=_DEMO_DIR)
    unknown = [r.feature_id for r in matrix.unknown_refs()]
    assert unknown == [], f"unknown demo refs (not in the catalog): {unknown}"


def test_every_feature_has_a_demo() -> None:
    """The slice's validable goal: zero features without demo evidence."""
    catalog = _catalog()
    matrix = build_matrix(catalog, tests_root=_REPO_ROOT / "tests", demo_root=_DEMO_DIR)
    assert matrix.features_without_demo() == ()
