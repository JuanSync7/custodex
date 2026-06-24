"""Shared fixtures for the H-03 regression corpus.

A tiny, realistic repo (one shared code file referenced by a user-guide and an
eng-guide doc) mirroring ``tests/test_system.py``'s ``_make_repo`` so the corpus
is self-contained. The corpus deliberately REFERENCES the same engine seams the
system tests do — it is a curated INDEX of invariants, not a fork of the engine.
"""

from __future__ import annotations

from pathlib import Path

from custodex.config import Audience, CodeRef, DocumentSpec, MonitorConfig
from custodex.extract import build_document_surface
from custodex.heal import regenerate_regions
from custodex.monitor import Monitor

NOW = "2026-06-01T00:00:00Z"

SHARED_V1 = '''\
def compute(a, b):
    """Add two numbers."""
    return a + b


def _private_helper(x):
    """Internal only."""
    return x * 2
'''

# A public-signature change: affects every audience.
SHARED_SIG_CHANGE = ("def compute(a, b):", "def compute(a, b, c=0):")
# A docstring-only change: an eng-guide event, a user-guide NON-event (K3).
SHARED_DOCSTRING_CHANGE = ('"""Add two numbers."""', '"""Add two integers together."""')

DOC_STUB = """\
# {title}

Prose written by a human.

<!-- CDM:BEGIN symbols -->
PLACEHOLDER
<!-- CDM:END symbols -->
"""


def make_repo(tmp_path: Path) -> tuple[Path, MonitorConfig]:
    """A fixture repo: one shared code file referenced by two audience docs."""
    root = tmp_path
    (root / "shared.py").write_text(SHARED_V1, encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "user.md").write_text(
        DOC_STUB.format(title="User guide"), encoding="utf-8"
    )
    (root / "docs" / "eng.md").write_text(
        DOC_STUB.format(title="Engineering guide"), encoding="utf-8"
    )
    user = DocumentSpec(
        id="user",
        path="docs/user.md",
        audience=Audience.USER_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols",),
    )
    eng = DocumentSpec(
        id="eng",
        path="docs/eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols",),
    )
    cfg = MonitorConfig(documents=(user, eng))
    for spec in (user, eng):
        regenerate_regions(root / spec.path, build_document_surface(spec, root))
    return root, cfg


def monitor(root: Path, cfg: MonitorConfig, **kw: object) -> Monitor:
    return Monitor(cfg, root, now=lambda: NOW, **kw)  # type: ignore[arg-type]
