"""Tests for code_doc_monitor.testwiki (EPIC R, R-06 Part A).

The test-wiki extractor: a pure, deterministic engine that AST-parses the test
tree (NEVER importing it — K1), pulling each ``test_*`` function's docstring
summary, boundary-from-path, and inline ``Feature:`` tags (per-test + inherited
from the module docstring's ``Features:`` line), then renders a byte-stable wiki
grouped by boundary → module with a per-feature "tested by" index (K10). Loud
only on a genuinely unparseable test file (K8). Written before the
implementation (K9, TDD).

Features: FEAT-REFERENCE-004
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from code_doc_monitor.errors import CatalogError
from code_doc_monitor.testwiki import (
    TestBoundary,
    TestCase,
    TestModule,
    collect_tests,
    render_test_wiki_md,
)
from tests._repo import REPO_ROOT

# --------------------------------------------------------------------------
# fixtures: a tiny on-disk test tree
# --------------------------------------------------------------------------

_UNIT_FILE = '''\
"""A unit fixture module.

Features: FEAT-EXTRACT-001
"""


def test_top_level():
    """Top-level test summary.

    Feature: FEAT-EXTRACT-002
    """
    assert True


def test_no_docstring():
    assert True


class TestGroup:
    """A grouping class (not collected itself)."""

    def test_nested():
        """Nested test summary.

        Feature: FEAT-EXTRACT-003
        """
        assert True

    def helper_not_a_test():
        return 1
'''

_INTEGRATION_FILE = '''\
"""An integration fixture module."""


def test_seam():
    """Seam test.

    Features: FEAT-CONFIGV2-001, FEAT-CONFIGV2-002
    """
    assert True
'''


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Build a tmp tests tree with a unit/ and integration/ file."""
    (tmp_path / "unit").mkdir()
    (tmp_path / "integration").mkdir()
    (tmp_path / "unit" / "test_thing.py").write_text(_UNIT_FILE, encoding="utf-8")
    (tmp_path / "integration" / "test_seam.py").write_text(
        _INTEGRATION_FILE, encoding="utf-8"
    )
    return tmp_path


# --------------------------------------------------------------------------
# collect_tests
# --------------------------------------------------------------------------


def test_collect_finds_modules(tree: Path) -> None:
    """collect_tests returns one TestModule per test_*.py, sorted by path."""
    modules = collect_tests(tree)
    assert isinstance(modules, tuple)
    paths = [m.path for m in modules]
    assert paths == ["integration/test_seam.py", "unit/test_thing.py"]
    assert all(isinstance(m, TestModule) for m in modules)


def test_collect_finds_top_level_and_nested(tree: Path) -> None:
    """Both top-level and class-nested test_* functions are collected."""
    modules = {m.path: m for m in collect_tests(tree)}
    unit = modules["unit/test_thing.py"]
    names = [c.name for c in unit.cases]
    # source order preserved within the file (K10), helper excluded
    assert names == ["test_top_level", "test_no_docstring", "test_nested"]
    assert all(isinstance(c, TestCase) for c in unit.cases)


def test_collect_nodeids(tree: Path) -> None:
    """Top-level → path::func; class-nested → path::Class::func."""
    unit = {m.path: m for m in collect_tests(tree)}["unit/test_thing.py"]
    by_name = {c.name: c for c in unit.cases}
    assert by_name["test_top_level"].nodeid == "unit/test_thing.py::test_top_level"
    assert by_name["test_nested"].nodeid == "unit/test_thing.py::TestGroup::test_nested"


def test_collect_docstring_summary(tree: Path) -> None:
    """summary is the first line of the test docstring; '' when absent."""
    unit = {m.path: m for m in collect_tests(tree)}["unit/test_thing.py"]
    by_name = {c.name: c for c in unit.cases}
    assert by_name["test_top_level"].summary == "Top-level test summary."
    assert by_name["test_no_docstring"].summary == ""


def test_collect_boundary_from_path(tree: Path) -> None:
    """Boundary is resolved from the directory in the path."""
    modules = {m.path: m for m in collect_tests(tree)}
    assert modules["unit/test_thing.py"].boundary is TestBoundary.UNIT
    assert modules["integration/test_seam.py"].boundary is TestBoundary.INTEGRATION
    for m in modules.values():
        for c in m.cases:
            assert c.boundary is m.boundary


def test_collect_feature_inheritance(tree: Path) -> None:
    """Each case carries per-test + module-level Features, sorted + deduped."""
    modules = {m.path: m for m in collect_tests(tree)}
    unit = modules["unit/test_thing.py"]
    assert unit.module_features == ("FEAT-EXTRACT-001",)
    by_name = {c.name: c for c in unit.cases}
    # per-test FEAT-002 plus inherited module-level FEAT-001, sorted
    assert by_name["test_top_level"].features == (
        "FEAT-EXTRACT-001",
        "FEAT-EXTRACT-002",
    )
    # no per-test tag → just the inherited module feature
    assert by_name["test_no_docstring"].features == ("FEAT-EXTRACT-001",)
    assert by_name["test_nested"].features == (
        "FEAT-EXTRACT-001",
        "FEAT-EXTRACT-003",
    )


def test_collect_module_without_features(tree: Path) -> None:
    """A module with no Features: tag has empty module_features."""
    integ = {m.path: m for m in collect_tests(tree)}["integration/test_seam.py"]
    assert integ.module_features == ()
    case = integ.cases[0]
    assert case.features == ("FEAT-CONFIGV2-001", "FEAT-CONFIGV2-002")


def test_collect_boundary_unknown(tmp_path: Path) -> None:
    """A test file outside the known boundary dirs → UNKNOWN."""
    (tmp_path / "misc").mkdir()
    (tmp_path / "misc" / "test_x.py").write_text(
        "def test_a():\n    pass\n", encoding="utf-8"
    )
    modules = collect_tests(tmp_path)
    assert modules[0].boundary is TestBoundary.UNKNOWN
    assert modules[0].cases[0].boundary is TestBoundary.UNKNOWN


def test_collect_all_boundaries(tmp_path: Path) -> None:
    """Each known boundary dir name resolves to its enum member."""
    for d in ("unit", "integration", "system", "smoke", "regression"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "test_a.py").write_text(
            "def test_a():\n    pass\n", encoding="utf-8"
        )
    modules = {m.path: m for m in collect_tests(tmp_path)}
    assert modules["unit/test_a.py"].boundary is TestBoundary.UNIT
    assert modules["integration/test_a.py"].boundary is TestBoundary.INTEGRATION
    assert modules["system/test_a.py"].boundary is TestBoundary.SYSTEM
    assert modules["smoke/test_a.py"].boundary is TestBoundary.SMOKE
    assert modules["regression/test_a.py"].boundary is TestBoundary.REGRESSION


def test_collect_ignores_non_test_files(tmp_path: Path) -> None:
    """Only test_*.py files are parsed; conftest/_helpers ignored."""
    (tmp_path / "unit").mkdir()
    (tmp_path / "unit" / "conftest.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "unit" / "_helper.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "unit" / "test_real.py").write_text(
        "def test_a():\n    pass\n", encoding="utf-8"
    )
    modules = collect_tests(tmp_path)
    assert [m.path for m in modules] == ["unit/test_real.py"]


def test_collect_unparseable_is_loud(tmp_path: Path) -> None:
    """A syntactically broken test file raises a loud CatalogError (K8)."""
    (tmp_path / "unit").mkdir()
    (tmp_path / "unit" / "test_broken.py").write_text(
        "def test_a(:\n    pass\n", encoding="utf-8"
    )
    with pytest.raises(CatalogError):
        collect_tests(tmp_path)


def test_collect_missing_root_is_empty(tmp_path: Path) -> None:
    """A missing tests_root yields an empty tuple (no evidence, not an error)."""
    assert collect_tests(tmp_path / "nope") == ()


def test_collect_deterministic(tree: Path) -> None:
    """Two collections of the same tree are byte-identical (K10)."""
    assert collect_tests(tree) == collect_tests(tree)


def test_records_frozen(tree: Path) -> None:
    """TestCase / TestModule are immutable (frozen pydantic)."""
    case = collect_tests(tree)[0].cases[0]
    with pytest.raises(ValidationError):
        case.name = "mutated"  # type: ignore[misc]


# --------------------------------------------------------------------------
# render_test_wiki_md
# --------------------------------------------------------------------------


def test_render_is_pure_and_stable(tree: Path) -> None:
    """Same modules in → byte-identical markdown out (no clock — K10)."""
    modules = collect_tests(tree)
    assert render_test_wiki_md(modules) == render_test_wiki_md(modules)


def test_render_contains_boundary_headings(tree: Path) -> None:
    """The wiki has a heading per boundary present."""
    md = render_test_wiki_md(collect_tests(tree))
    assert "Unit" in md or "UNIT" in md
    assert "Integration" in md or "INTEGRATION" in md


def test_render_contains_feature_index(tree: Path) -> None:
    """A per-feature 'tested by' index maps feature id → nodeids."""
    md = render_test_wiki_md(collect_tests(tree))
    assert "FEAT-EXTRACT-001" in md
    assert "unit/test_thing.py::test_top_level" in md
    # the index lists the nodeids that tag a feature
    assert "Tested by" in md or "tested by" in md


def test_render_includes_summaries(tree: Path) -> None:
    """Each case row carries its docstring summary."""
    md = render_test_wiki_md(collect_tests(tree))
    assert "Top-level test summary." in md
    assert "Seam test." in md


def test_render_empty(tmp_path: Path) -> None:
    """Rendering no modules still produces a valid (non-crashing) document."""
    md = render_test_wiki_md(())
    assert isinstance(md, str)
    assert md.endswith("\n")


# --------------------------------------------------------------------------
# integration: the REAL test tree classifies cleanly
# --------------------------------------------------------------------------


def test_collect_real_tree() -> None:
    """collect_tests over the real tests/ returns modules; every case has a
    non-UNKNOWN boundary (proves the R-05 dirs classify). Does NOT assert
    feature-coverage completeness — that is Part B.
    """
    modules = collect_tests(REPO_ROOT / "tests")
    assert len(modules) > 0
    total_cases = sum(len(m.cases) for m in modules)
    assert total_cases > 0
    for m in modules:
        assert m.boundary is not TestBoundary.UNKNOWN, m.path
        for c in m.cases:
            assert c.boundary is not TestBoundary.UNKNOWN, c.nodeid
