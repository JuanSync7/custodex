"""Dogfood (CDM-07): code-doc-monitor monitors its OWN source against its docs.

The shipped ``cdmon.yaml`` maps this package's modules onto the engineering docs
under ``docs/api/`` (with ``schema.py`` as a shared file referenced two ways).
These tests prove (a) the real config resolves against the real code and the
checked-in docs are in sync, and (b) the full self-heal loop works on the real
project when the code changes — exercised on a copy so the repo is untouched.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from code_doc_monitor.config import load_config
from code_doc_monitor.extract import build_document_surface
from code_doc_monitor.monitor import Monitor

_ROOT = Path(__file__).resolve().parents[1]
_CONFIG = _ROOT / "cdmon.yaml"


def test_dogfood_config_exists_and_loads() -> None:
    cfg = load_config(_CONFIG)
    assert cfg.documents
    # the shared file is referenced by more than one document
    refs = [(d.id, r.path) for d in cfg.documents for r in d.code_refs]
    shared = [p for _id, p in refs if p.endswith("schema.py")]
    assert len(shared) >= 2, "schema.py should be a shared, multiply-referenced file"


def test_dogfood_surfaces_resolve_against_real_code() -> None:
    cfg = load_config(_CONFIG)
    for spec in cfg.documents:
        if not spec.code_refs:
            continue  # an index/collection doc has no code surface of its own
        surface = build_document_surface(spec, _ROOT)
        assert surface.symbols, f"{spec.id}: no symbols extracted from real code"


def test_dogfood_docs_are_in_sync() -> None:
    """The checked-in docs match the checked-in code (`cdmon monitor --apply`)."""
    cfg = load_config(_CONFIG)
    report = Monitor(cfg, _ROOT).check()
    assert report.ok, report.summary()


def test_dogfood_self_heals_on_a_copy(tmp_path: Path) -> None:
    # Copy the package + docs + config so the real repo is never mutated.
    dst = tmp_path / "proj"
    dst.mkdir()
    shutil.copytree(_ROOT / "code_doc_monitor", dst / "code_doc_monitor")
    shutil.copytree(_ROOT / "docs", dst / "docs")
    shutil.copy(_CONFIG, dst / "cdmon.yaml")
    cfg = load_config(dst / "cdmon.yaml")

    assert Monitor(cfg, dst).check().ok  # copy starts clean

    # Mutate a real source file: add a public function to config.py.
    target = dst / "code_doc_monitor" / "config.py"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\n\ndef brand_new_public_helper(x: int) -> int:\n    return x\n",
        encoding="utf-8",
    )
    assert not Monitor(cfg, dst).check().ok  # drift detected

    result = Monitor(cfg, dst, now=lambda: "2026-06-01T00:00:00Z").run(apply=True)
    assert result.records  # a verdict was recorded for review
    assert Monitor(cfg, dst).check().ok  # fully self-healed


def test_dogfood_docs_conform_to_layout_standard() -> None:
    """CDM-08: the checked-in docs satisfy the Document Layout Standard."""
    from code_doc_monitor.layout import lint_config

    cfg = load_config(_CONFIG)
    issues = lint_config(cfg, _ROOT)
    assert issues == [], [f"{i.doc_id}: {i.code.value} — {i.detail}" for i in issues]
