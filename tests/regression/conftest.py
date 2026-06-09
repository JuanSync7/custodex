"""H-03 regression corpus — auto-mark every case `regression`.

Every test collected under ``tests/regression/`` is automatically tagged with
the ``regression`` marker, so the curated corpus can be run alone
(``pytest -m regression``) AND is included in the default suite (it lives under
``tests/``). No per-test decorator is needed — adding a case to this package is
enough to enlist it in the corpus.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    for item in items:
        # Only mark cases that physically live in this package.
        if "tests/regression/" in item.nodeid or item.nodeid.startswith(
            "tests/regression"
        ):
            item.add_marker("regression")
