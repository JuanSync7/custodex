"""DEMOS.md id-uniqueness lint (AGT-01 hardening rider).

The traceability engine scans only ``Features:`` tag lines, never the
``### DEMO-NNN`` headers — so a duplicated demo id merges silently (the
review found DEMO-052/053/054 each used twice). This smoke guard makes a
collision loud: every demo header id in demo/DEMOS.md must be unique.

Features: FEAT-ENTITIES-003
"""

from __future__ import annotations

import re
from collections import Counter

from tests._repo import REPO_ROOT

_HEADER = re.compile(r"^### (DEMO-\d+)\b", re.MULTILINE)


def test_demo_header_ids_are_unique() -> None:
    text = (REPO_ROOT / "demo" / "DEMOS.md").read_text(encoding="utf-8")
    ids = _HEADER.findall(text)
    assert ids, "no demo headers found — the header convention changed?"
    duplicates = [demo_id for demo_id, n in Counter(ids).items() if n > 1]
    assert duplicates == [], f"duplicate demo ids in demo/DEMOS.md: {duplicates}"
