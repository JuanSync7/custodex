"""TDOC-01 — the test→test-doc mirror: a test file syncs to a test-doc exactly
the way a source file syncs to a document.

The engine is generic over any ``.py`` file (K0), so monitoring a test file needs
no new code — only the config convention: a unit whose ``code_refs`` point at
``tests/**`` and whose docs live under a top-level ``test-docs/`` directory. These
tests prove (a) the generic mechanism extracts a test file's ``test_*`` functions
into a documentable surface and heals idempotently, and (b) cdx dogfoods this on
its own ``tests/smoke/`` boundary (the ``tests`` unit + the ``test-docs/smoke/*``
docs are in sync with the code).

Features: FEAT-CONFIGV2-017
"""

from __future__ import annotations

from pathlib import Path

from custodex.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    load_config_dir,
)
from custodex.extract import build_document_surface
from custodex.heal import regenerate_regions
from custodex.layout import scaffold_doc
from custodex.monitor import Monitor
from tests._repo import REPO_ROOT

_CONFIG_DIR = REPO_ROOT / "config" / "cdmon"


def _test_doc_spec(doc_path: str, code_ref: str) -> DocumentSpec:
    return DocumentSpec(
        id="t",
        path=doc_path,
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path=code_ref),),
        region_keys=("symbols",),
    )


def test_engine_extracts_test_functions_as_a_documentable_surface(
    tmp_path: Path,
) -> None:
    """K0/K2: a test file is just a ``.py`` file — its ``test_*`` functions form a
    surface exactly like a source module's public API."""
    (tmp_path / "tests" / "foo").mkdir(parents=True)
    (tmp_path / "tests" / "foo" / "test_thing.py").write_text(
        "def test_alpha() -> None:\n    assert True\n\n\n"
        "def test_beta() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    spec = _test_doc_spec("test-docs/foo/test_thing.md", "tests/foo/test_thing.py")
    surface = build_document_surface(spec, tmp_path)
    names = {s.name for s in surface.symbols}
    assert {"test_alpha", "test_beta"} <= names


def test_testdoc_region_heals_and_is_idempotent(tmp_path: Path) -> None:
    """K7: scaffolding then re-healing a test-doc is a byte-stable no-op, and a new
    test function drifts the doc until it is rehealed (the same contract as docs)."""
    (tmp_path / "tests" / "foo").mkdir(parents=True)
    test_file = tmp_path / "tests" / "foo" / "test_thing.py"
    test_file.write_text(
        "def test_alpha() -> None:\n    assert True\n", encoding="utf-8"
    )
    spec = _test_doc_spec("test-docs/foo/test_thing.md", "tests/foo/test_thing.py")
    doc_path = tmp_path / spec.path
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    surface = build_document_surface(spec, tmp_path)
    doc_path.write_text(scaffold_doc(spec, surface), encoding="utf-8")

    # Re-healing an in-sync doc changes nothing (idempotent, K7).
    assert regenerate_regions(doc_path, surface) is False

    # Adding a test function drifts the doc; a reheal closes it.
    test_file.write_text(
        test_file.read_text(encoding="utf-8")
        + "\n\ndef test_gamma() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    drifted = build_document_surface(spec, tmp_path)
    assert regenerate_regions(doc_path, drifted) is True
    assert "test_gamma" in doc_path.read_text(encoding="utf-8")


def test_dogfood_tests_unit_monitors_the_smoke_boundary() -> None:
    """cdx dogfoods the mirror: a ``tests`` unit declares one test-doc per
    ``tests/smoke/`` file, each tracked against the test file's functions, and the
    checked-in test-docs are in sync with the code."""
    cfg = load_config_dir(_CONFIG_DIR)
    by_id = {d.id: d for d in cfg.documents}
    spec = by_id.get("test-smoke-boundaries")
    assert spec is not None, (
        "config/cdmon/tests.yaml must declare test-smoke-boundaries"
    )
    assert spec.path == "test-docs/smoke/test_boundaries.md"
    assert spec.audience is Audience.ENG_GUIDE
    assert any(r.path == "tests/smoke/test_boundaries.py" for r in spec.code_refs)

    surface = build_document_surface(spec, _CONFIG_DIR / cfg.root)
    names = {s.name for s in surface.symbols}
    assert "test_no_test_file_outside_a_boundary_dir" in names

    # The checked-in test-docs are in sync with the test code (K2).
    assert Monitor(cfg, _CONFIG_DIR).check().ok
