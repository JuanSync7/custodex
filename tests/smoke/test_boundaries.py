"""Marker-lint — the "clear boundary" guarantee, automated (R-05, K8/K10).

Two complementary checks enforce that the test taxonomy stays honest:

1. *Structure* — every ``test_*.py`` physically lives under one of the boundary
   directories (``tests/{unit,integration,system,smoke,regression}/``); no test
   file is left stranded directly in ``tests/``. This fails loud, listing any
   unclassified file, the moment someone adds a test in the wrong place.

2. *Markers* — every collected test item carries EXACTLY one boundary marker
   (one of unit/integration/system/smoke/regression). This reads the live
   collected session (snapshotted by the root conftest after all collection
   hooks run), so a file under a boundary dir that somehow escaped marking — or
   a test double-marked — fails the gate.
"""

from __future__ import annotations

from tests._repo import REPO_ROOT
from tests.conftest import BOUNDARY_MARKERS, COLLECTED_BOUNDARIES

_TESTS = REPO_ROOT / "tests"
_BOUNDARY_DIRS = ("unit", "integration", "system", "smoke", "regression")


def test_no_test_file_outside_a_boundary_dir() -> None:
    """Every ``test_*.py`` lives under a known boundary directory."""
    stranded = sorted(p.name for p in _TESTS.glob("test_*.py"))
    assert not stranded, (
        "test files must live under a boundary directory "
        f"({'/'.join(_BOUNDARY_DIRS)}), found stranded directly in tests/: "
        f"{stranded}"
    )

    # Also assert nothing hides one level down under an UNKNOWN directory.
    misplaced = sorted(
        str(p.relative_to(_TESTS))
        for p in _TESTS.glob("*/test_*.py")
        if p.parent.name not in _BOUNDARY_DIRS
    )
    assert not misplaced, (
        f"test files under an unrecognized directory: {misplaced}; "
        f"valid boundaries are {_BOUNDARY_DIRS}"
    )


def test_every_collected_item_has_exactly_one_boundary_marker() -> None:
    """No unclassified (or multiply-classified) test in the collected session."""
    assert COLLECTED_BOUNDARIES, "collection snapshot is empty — conftest not loaded?"

    unmarked = sorted(nid for nid, marks in COLLECTED_BOUNDARIES if len(marks) == 0)
    over_marked = sorted(
        f"{nid} -> {sorted(marks)}"
        for nid, marks in COLLECTED_BOUNDARIES
        if len(marks) > 1
    )
    assert not unmarked, (
        "these collected tests carry NO boundary marker (unclassified); "
        f"expected exactly one of {BOUNDARY_MARKERS}: {unmarked}"
    )
    assert not over_marked, (
        f"these collected tests carry MORE THAN ONE boundary marker: {over_marked}"
    )
