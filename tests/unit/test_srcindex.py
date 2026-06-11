"""Tests for code_doc_monitor.srcindex (EPIC R, R-07).

The source index + source wiki engine: a pure, deterministic engine that
inventories every public symbol of a package (reusing
:func:`code_doc_monitor.inventory.discover_files`/``discover_symbols`` — no AST
re-impl, K0), folds each file into its TOP-LEVEL module, and joins each module to
the catalog features whose ``modules`` name it (the inverse of
``Feature.modules``). ``modules_without_feature`` is the deferred R-02 "no orphan
public capability" check, finally realizable. Pure (K1), sorted/clock-free (K10),
loud on a bad package root via inventory's ``InventoryError`` (K8). Written before
the implementation (K9, TDD).

Features: FEAT-REFERENCE-005, FEAT-REFERENCE-006
"""

from __future__ import annotations

import pkgutil
from pathlib import Path

import pytest
from pydantic import ValidationError

import code_doc_monitor as _pkg
from code_doc_monitor.errors import InventoryError
from code_doc_monitor.featurecatalog import Feature, FeatureCatalog, load_catalog
from code_doc_monitor.srcindex import (
    ModuleIndex,
    SourceIndex,
    build_source_index,
    render_source_wiki_md,
)
from tests._repo import REPO_ROOT

# --------------------------------------------------------------------------
# fixtures: a tiny on-disk package + a fixture catalog
# --------------------------------------------------------------------------


def _feat(fid: str, *modules: str, subsystem: str = "fix") -> Feature:
    return Feature(
        id=fid,
        title=f"T {fid}",
        summary=f"S {fid}.",
        subsystem=subsystem,
        modules=tuple(modules),
    )


_ALPHA = '''\
"""Alpha module."""


def public_fn():
    return 1


def _private_fn():
    return 2


class PublicClass:
    def method(self):
        return 3
'''

_SUB_FILE = '''\
"""A subpackage file (folds into the `beta` top-level module)."""


def beta_fn():
    return 1
'''

_INIT = (
    '"""Pure re-export aggregator."""\n\nfrom .alpha import public_fn  # noqa: F401\n'
)


@pytest.fixture
def pkg(tmp_path: Path) -> Path:
    """A tiny package: alpha.py, a beta/ subpackage, and a re-export __init__."""
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "__init__.py").write_text(_INIT, encoding="utf-8")
    (root / "alpha.py").write_text(_ALPHA, encoding="utf-8")
    (root / "beta").mkdir()
    (root / "beta" / "__init__.py").write_text("", encoding="utf-8")
    (root / "beta" / "core.py").write_text(_SUB_FILE, encoding="utf-8")
    return root


@pytest.fixture
def catalog() -> FeatureCatalog:
    """A catalog that covers `alpha`, names a phantom `gamma`, omits `beta`."""
    return FeatureCatalog(
        features=(
            _feat("FEAT-FIX-001", "alpha"),
            _feat("FEAT-FIX-002", "alpha"),  # second feature for the same module
            _feat("FEAT-FIX-003", "gamma"),  # names a module NOT in the package
        )
    )


# --------------------------------------------------------------------------
# build_source_index
# --------------------------------------------------------------------------


def test_build_returns_source_index(pkg: Path, catalog: FeatureCatalog) -> None:
    """build_source_index returns a SourceIndex of ModuleIndex records."""
    idx = build_source_index(pkg, catalog)
    assert isinstance(idx, SourceIndex)
    assert all(isinstance(m, ModuleIndex) for m in idx.modules)


def test_modules_sorted_by_name(pkg: Path, catalog: FeatureCatalog) -> None:
    """Modules are sorted by module name; the re-export __init__ is skipped."""
    idx = build_source_index(pkg, catalog)
    names = [m.module for m in idx.modules]
    assert names == ["alpha", "beta"]


def test_public_symbols_only_and_sorted(pkg: Path, catalog: FeatureCatalog) -> None:
    """Each module carries its sorted PUBLIC symbol names (privates excluded)."""
    idx = build_source_index(pkg, catalog)
    by_mod = {m.module: m for m in idx.modules}
    assert by_mod["alpha"].public_symbols == ("PublicClass", "public_fn")
    assert "_private_fn" not in by_mod["alpha"].public_symbols
    assert by_mod["beta"].public_symbols == ("beta_fn",)


def test_features_joined_by_module_name(pkg: Path, catalog: FeatureCatalog) -> None:
    """A module's features are the sorted catalog ids whose `modules` name it."""
    idx = build_source_index(pkg, catalog)
    by_mod = {m.module: m for m in idx.modules}
    assert by_mod["alpha"].features == ("FEAT-FIX-001", "FEAT-FIX-002")
    assert by_mod["beta"].features == ()  # un-catalogued module


def test_module_path_is_repo_relative_posix(pkg: Path, catalog: FeatureCatalog) -> None:
    """A top-level module's path is its file; a subpackage's is its __init__/first."""
    idx = build_source_index(pkg, catalog)
    by_mod = {m.module: m for m in idx.modules}
    assert by_mod["alpha"].path == "alpha.py"
    # the beta subpackage folds to a single module; its path is a beta/ file
    assert by_mod["beta"].path.startswith("beta/")


# --------------------------------------------------------------------------
# completeness accessors
# --------------------------------------------------------------------------


def test_features_without_module_match(pkg: Path, catalog: FeatureCatalog) -> None:
    """A catalog feature naming a module absent from the package is reported."""
    idx = build_source_index(pkg, catalog)
    # gamma is named by FEAT-FIX-003 but there is no gamma module in the package
    assert idx.features_without_module_match() == ("FEAT-FIX-003",)


def test_modules_without_feature(pkg: Path, catalog: FeatureCatalog) -> None:
    """A public module with zero catalog features is the orphan check."""
    idx = build_source_index(pkg, catalog)
    # beta is un-catalogued
    assert idx.modules_without_feature() == ("beta",)


def test_accessors_empty_when_reconciled(pkg: Path) -> None:
    """With a catalog covering exactly the package modules, both lists are empty."""
    full = FeatureCatalog(
        features=(_feat("FEAT-FIX-001", "alpha"), _feat("FEAT-FIX-004", "beta"))
    )
    idx = build_source_index(pkg, full)
    assert idx.features_without_module_match() == ()
    assert idx.modules_without_feature() == ()


# --------------------------------------------------------------------------
# determinism + loud + frozen
# --------------------------------------------------------------------------


def test_build_is_deterministic(pkg: Path, catalog: FeatureCatalog) -> None:
    """Two builds of the same package + catalog are byte-identical (K10)."""
    assert build_source_index(pkg, catalog) == build_source_index(pkg, catalog)


def test_build_loud_on_bad_root(tmp_path: Path, catalog: FeatureCatalog) -> None:
    """A missing package root raises a loud InventoryError (K8)."""
    with pytest.raises(InventoryError):
        build_source_index(tmp_path / "nope", catalog)


def test_records_are_frozen(pkg: Path, catalog: FeatureCatalog) -> None:
    """ModuleIndex / SourceIndex are immutable (frozen pydantic)."""
    idx = build_source_index(pkg, catalog)
    with pytest.raises(ValidationError):
        idx.modules[0].module = "mutated"  # type: ignore[misc]


def test_moduleindex_forbids_extra() -> None:
    """ModuleIndex rejects an unknown field (extra=forbid)."""
    with pytest.raises(ValidationError):
        ModuleIndex(
            module="x",
            path="x.py",
            public_symbols=(),
            features=(),
            bogus="z",  # type: ignore[call-arg]
        )


# --------------------------------------------------------------------------
# render_source_wiki_md
# --------------------------------------------------------------------------


def test_render_is_pure_and_stable(pkg: Path, catalog: FeatureCatalog) -> None:
    """Same index in → byte-identical markdown out (no clock — K10)."""
    idx = build_source_index(pkg, catalog)
    assert render_source_wiki_md(idx) == render_source_wiki_md(idx)


def test_render_lists_modules_symbols_and_features(
    pkg: Path, catalog: FeatureCatalog
) -> None:
    """The wiki lists each module's path, public symbols, and feature links."""
    idx = build_source_index(pkg, catalog)
    md = render_source_wiki_md(idx)
    assert "alpha" in md
    assert "public_fn" in md
    assert "FEAT-FIX-001" in md
    assert "alpha.py" in md


def test_render_coverage_summary(pkg: Path, catalog: FeatureCatalog) -> None:
    """The wiki carries a coverage summary naming any orphan module."""
    idx = build_source_index(pkg, catalog)
    md = render_source_wiki_md(idx)
    assert md.endswith("\n")
    # the orphan (un-catalogued) module is surfaced in the summary
    assert "beta" in md


def test_render_coverage_summary_when_reconciled(pkg: Path) -> None:
    """With zero orphans the summary says every module maps to a feature."""
    full = FeatureCatalog(
        features=(_feat("FEAT-FIX-001", "alpha"), _feat("FEAT-FIX-004", "beta"))
    )
    md = render_source_wiki_md(build_source_index(pkg, full))
    assert "every public module maps to at least one catalog feature" in md


# --------------------------------------------------------------------------
# integration / system — the REAL package + real catalog are reconciled
# --------------------------------------------------------------------------


def _real_catalog() -> FeatureCatalog:
    known = {m.name for m in pkgutil.iter_modules(_pkg.__path__)}
    return load_catalog(REPO_ROOT / "feature-doc" / "catalog", known_modules=known)


def test_real_tree_no_feature_names_missing_module() -> None:
    """Every catalog feature names a real module of the package (K8)."""
    idx = build_source_index(REPO_ROOT / "code_doc_monitor", _real_catalog())
    assert idx.features_without_module_match() == ()


def test_real_tree_no_orphan_public_module() -> None:
    """The deferred R-02 guarantee: every public module maps to a feature."""
    idx = build_source_index(REPO_ROOT / "code_doc_monitor", _real_catalog())
    assert idx.modules_without_feature() == ()
