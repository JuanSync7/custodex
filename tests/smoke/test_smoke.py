"""Bootstrap smoke test — the package imports and exposes its version."""

from __future__ import annotations

import custodex


def test_version_is_exposed() -> None:
    assert custodex.__version__ == "0.1.0"
