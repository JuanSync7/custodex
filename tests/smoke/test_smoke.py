"""Bootstrap smoke test — the package imports and exposes its version."""

from __future__ import annotations

import code_doc_monitor


def test_version_is_exposed() -> None:
    assert code_doc_monitor.__version__ == "0.1.0"
