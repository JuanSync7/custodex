"""Tests for code_doc_monitor.heal (CDM-03).

regenerate_regions closes REGION + HASH drift, is idempotent (K7), and leaves
detect() clean afterwards. apply_fix handles both the region-body and the
whole-doc fix shapes. TDD (K9).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from code_doc_monitor.blocks import symbol_table
from code_doc_monitor.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
)
from code_doc_monitor.drift import detect
from code_doc_monitor.extract import build_document_surface
from code_doc_monitor.heal import apply_fix, regenerate_regions
from code_doc_monitor.manifest import (
    parse_doc,
    regions,
    render_doc,
    set_fingerprint,
    set_region,
    stored_fingerprint,
)

CODE_V1 = '''\
def greet(name: str) -> str:
    """Say hi."""
    return name
'''

CODE_V2 = '''\
def greet(name: str, loud: bool = False) -> str:
    """Say hi, maybe loudly."""
    return name
'''


@dataclass
class FakeFix:
    """A ProposedFix-shaped stand-in (schema.py not built yet)."""

    region_id: str | None = None
    new_region_body: str | None = None
    new_doc_text: str | None = None
    rationale: str = ""


def _setup(tmp_path: Path) -> tuple[Path, DocumentSpec]:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "src" / "mod.py").write_text(CODE_V1, encoding="utf-8")
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols",),
    )
    return root, spec


def _synced_text(spec: DocumentSpec, root: Path) -> str:
    surface = build_document_surface(spec, root)
    body = "# T\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    body, _ = set_region(body, "symbols", symbol_table(surface))
    return render_doc(set_fingerprint({}, surface.surface_hash()), body)


def test_regenerate_closes_drift_and_is_idempotent(tmp_path: Path) -> None:
    root, spec = _setup(tmp_path)
    doc_path = root / spec.path
    doc_path.write_text(_synced_text(spec, root), encoding="utf-8")

    # Change the code so both HASH and REGION drift appear.
    (root / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    config = MonitorConfig(root="repo", documents=(spec,))
    assert not detect(config, tmp_path).ok

    surface = build_document_surface(spec, root)
    changed = regenerate_regions(doc_path, surface)
    assert changed is True

    # detect() is now clean.
    assert detect(config, tmp_path).ok

    # Region body matches expectation and fingerprint refreshed.
    doc = parse_doc(doc_path)
    assert regions(doc)["symbols"] == symbol_table(surface)
    assert stored_fingerprint(doc) == surface.surface_hash()

    # Idempotent: a second call with no code change makes no change (K7).
    assert regenerate_regions(doc_path, surface) is False


def test_apply_fix_region_shape(tmp_path: Path) -> None:
    root, spec = _setup(tmp_path)
    doc_path = root / spec.path
    doc_path.write_text(_synced_text(spec, root), encoding="utf-8")

    fix = FakeFix(region_id="symbols", new_region_body="brand new region")
    assert apply_fix(doc_path, fix) is True
    assert regions(parse_doc(doc_path))["symbols"] == "brand new region"

    # Idempotent: applying the same fix again changes nothing.
    assert apply_fix(doc_path, fix) is False


def test_apply_fix_whole_doc_shape(tmp_path: Path) -> None:
    root, spec = _setup(tmp_path)
    doc_path = root / spec.path
    doc_path.write_text("original\n", encoding="utf-8")

    fix = FakeFix(new_doc_text="completely rewritten\n")
    assert apply_fix(doc_path, fix) is True
    assert doc_path.read_text(encoding="utf-8") == "completely rewritten\n"
    assert apply_fix(doc_path, fix) is False


def test_apply_fix_prefers_whole_doc_when_both_shapes_present(tmp_path: Path) -> None:
    """A fix carrying BOTH a region body and whole-doc text applies the latter.

    A real LLM, asked to remediate a HASH drift, may return the regenerated
    region *and* the full corrected document (with a refreshed fingerprint). The
    whole-doc text must win — applying only the region would leave a stale
    fingerprint, and the HASH drift would not close in one pass.
    """
    root, spec = _setup(tmp_path)
    doc_path = root / spec.path
    doc_path.write_text("original\n", encoding="utf-8")

    fix = FakeFix(
        region_id="symbols",
        new_region_body="just the region",
        new_doc_text="WHOLE DOC with refreshed fingerprint\n",
    )
    assert apply_fix(doc_path, fix) is True
    # The whole-doc text was written, not merely a region splice.
    assert doc_path.read_text(encoding="utf-8") == (
        "WHOLE DOC with refreshed fingerprint\n"
    )
    # Idempotent: re-applying the same both-shapes fix changes nothing.
    assert apply_fix(doc_path, fix) is False


def test_apply_fix_noop_when_empty(tmp_path: Path) -> None:
    root, spec = _setup(tmp_path)
    doc_path = root / spec.path
    doc_path.write_text("x\n", encoding="utf-8")
    assert apply_fix(doc_path, FakeFix()) is False
    assert doc_path.read_text(encoding="utf-8") == "x\n"
