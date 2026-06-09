"""Auto-mark each collected test with its boundary marker by directory (R-05).

The test suite is physically organized into four boundary directories —
``tests/unit/``, ``tests/integration/``, ``tests/system/``, ``tests/smoke/`` —
plus the ``tests/regression/`` corpus (marked separately by its own conftest).
Rather than decorate every test function, this collection hook reads each item's
path and applies the matching boundary marker, so ``pytest -m unit`` (etc.)
selects exactly the directory's tests. Placing a test file under a boundary
directory IS its classification — the directory is the single source of truth.

``tests/regression/`` items are left to the regression conftest's ``regression``
marker and deliberately receive NO boundary marker; the marker-lint in
``tests/smoke/test_boundaries.py`` enforces that every collected item carries
exactly one of {unit, integration, system, smoke, regression}.
"""

from __future__ import annotations

import pytest

_BOUNDARY_BY_DIR = {
    "unit": "unit",
    "integration": "integration",
    "system": "system",
    "smoke": "smoke",
}

# The boundary markers a collected test may carry; the marker-lint in
# tests/smoke/test_boundaries.py asserts every item has EXACTLY one of these.
BOUNDARY_MARKERS = ("unit", "integration", "system", "smoke", "regression")

# Snapshot of (nodeid, frozenset-of-boundary-markers) for every collected item,
# populated AFTER both this hook and the regression conftest's hook have run, so
# the marker-lint test can verify the whole collected session in-process (K10).
COLLECTED_BOUNDARIES: list[tuple[str, frozenset[str]]] = []


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    for item in items:
        parts = item.path.parts
        if "regression" in parts:
            # The regression corpus is marked by tests/regression/conftest.py.
            continue
        for directory, marker in _BOUNDARY_BY_DIR.items():
            if directory in parts:
                item.add_marker(getattr(pytest.mark, marker))
                break


@pytest.hookimpl(trylast=True)
def pytest_collection_finish(session: pytest.Session) -> None:
    # trylast → runs after every other conftest's modifyitems (incl. regression),
    # so the snapshot reflects the FINAL marker set on each item.
    COLLECTED_BOUNDARIES.clear()
    for item in session.items:
        marks = frozenset(
            m.name for m in item.iter_markers() if m.name in BOUNDARY_MARKERS
        )
        COLLECTED_BOUNDARIES.append((item.nodeid, marks))
