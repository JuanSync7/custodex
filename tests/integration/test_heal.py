"""Tests for custodex.heal (CDM-03).

regenerate_regions closes REGION + HASH drift, is idempotent (K7), and leaves
detect() clean afterwards. apply_fix handles both the region-body and the
whole-doc fix shapes. TDD (K9).

Features: FEAT-HEAL-001, FEAT-HEAL-002, FEAT-HEAL-004, FEAT-HEAL-005
Features: FEAT-HEAL-006, FEAT-HEAL-007, FEAT-HEAL-008, FEAT-HEAL-009
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from custodex.blocks import symbol_table
from custodex.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
    RegionMode,
)
from custodex.drift import detect
from custodex.extract import build_document_surface
from custodex.heal import apply_fix, regenerate_regions, render_corrected
from custodex.manifest import (
    parse_doc,
    parse_text,
    region_body_hash,
    regions,
    render_doc,
    set_fingerprint,
    set_region,
    stored_fingerprint,
    stored_region_hash,
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


# --- B-02: the preserve write-boundary guarantee ---------------------------


def _two_region_doc(spec: DocumentSpec, root: Path) -> str:
    """A doc with a `symbols` region (human-owned body) + a `notes` region."""
    surface = build_document_surface(spec, root)
    body = (
        "# T\n\n"
        "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n\n"
        "<!-- CDM:BEGIN notes -->\nNOTES\n<!-- CDM:END notes -->\n"
    )
    body, _ = set_region(body, "symbols", "HUMAN PROSE here\nkeep me byte-exact")
    return render_doc(set_fingerprint({}, surface.surface_hash()), body)


def test_apply_fix_whole_doc_preserves_named_region(tmp_path: Path) -> None:
    """A whole-doc fix re-injects the CURRENT body of a preserved region, so a
    backend that returned whole-doc text cannot clobber a human region."""
    root, _ = _setup(tmp_path)
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols", "notes"),
    )
    doc_path = root / spec.path
    doc_path.write_text(_two_region_doc(spec, root), encoding="utf-8")
    human_body = regions(parse_doc(doc_path))["symbols"]

    # A backend whole-doc fix that tries to overwrite the human region.
    clobber = (
        "# T\n\n"
        "<!-- CDM:BEGIN symbols -->\nBACKEND CLOBBER\n<!-- CDM:END symbols -->\n\n"
        "<!-- CDM:BEGIN notes -->\nFRESH NOTES\n<!-- CDM:END notes -->\n"
    )
    fix = FakeFix(new_doc_text=clobber)
    changed = apply_fix(doc_path, fix, preserve=frozenset({"symbols"}))
    assert changed is True

    after = parse_doc(doc_path)
    # The human region body is byte-identical to before.
    assert regions(after)["symbols"] == human_body
    # The non-preserved region took the backend's new value.
    assert regions(after)["notes"] == "FRESH NOTES"


def test_apply_fix_region_shape_preserved_id_is_noop(tmp_path: Path) -> None:
    root, _ = _setup(tmp_path)
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols", "notes"),
    )
    doc_path = root / spec.path
    doc_path.write_text(_two_region_doc(spec, root), encoding="utf-8")
    before = doc_path.read_bytes()

    fix = FakeFix(region_id="symbols", new_region_body="should be ignored")
    assert apply_fix(doc_path, fix, preserve=frozenset({"symbols"})) is False
    assert doc_path.read_bytes() == before


def test_apply_fix_empty_preserve_is_todays_behavior(tmp_path: Path) -> None:
    """Default empty preserve == EPIC-A: a region-shaped fix still applies."""
    root, spec = _setup(tmp_path)
    doc_path = root / spec.path
    doc_path.write_text(_synced_text(spec, root), encoding="utf-8")
    fix = FakeFix(region_id="symbols", new_region_body="new body")
    assert apply_fix(doc_path, fix, preserve=frozenset()) is True
    assert regions(parse_doc(doc_path))["symbols"] == "new body"


# --- B-03: llm-seeded lock + hash stamping (heal write boundary) ------------


def _llm_seeded_spec(root: Path) -> DocumentSpec:
    return DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols",),
        region_modes={"symbols": RegionMode.LLM_SEEDED},
    )


def test_regenerate_stamps_region_hash_for_generated(tmp_path: Path) -> None:
    """An authored (generated) region gets its body hash stamped (B-03)."""
    root, spec = _setup(tmp_path)
    doc_path = root / spec.path
    doc_path.write_text(_synced_text(spec, root), encoding="utf-8")
    (root / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    surface = build_document_surface(spec, root)
    modes = {"symbols": RegionMode.GENERATED}
    regenerate_regions(doc_path, surface, modes=modes)
    doc = parse_doc(doc_path)
    body = regions(doc)["symbols"]
    assert stored_region_hash(doc, "symbols") == region_body_hash(body)


def test_llm_seeded_unlocked_is_filled_and_stamped(tmp_path: Path) -> None:
    """Phase 1: an unlocked llm-seeded region is authored like generated and
    its hash stamped, so a later human edit can be detected."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "src" / "mod.py").write_text(CODE_V1, encoding="utf-8")
    spec = _llm_seeded_spec(root)
    doc_path = root / spec.path
    doc_path.write_text(
        "# T\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    surface = build_document_surface(spec, root)
    changed = regenerate_regions(
        doc_path, surface, modes={"symbols": RegionMode.LLM_SEEDED}
    )
    assert changed is True
    doc = parse_doc(doc_path)
    body = regions(doc)["symbols"]
    assert body == symbol_table(surface)  # filled from the surface like generated
    assert stored_region_hash(doc, "symbols") == region_body_hash(body)


def test_llm_seeded_locked_is_preserved_not_reauthored(tmp_path: Path) -> None:
    """Phase 2: after a human edits the filled body (hash diverges), a re-heal
    LEAVES the region byte-identical (locked → preserved) and keeps its hash."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "src" / "mod.py").write_text(CODE_V1, encoding="utf-8")
    spec = _llm_seeded_spec(root)
    doc_path = root / spec.path
    doc_path.write_text(
        "# T\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    modes = {"symbols": RegionMode.LLM_SEEDED}
    surface = build_document_surface(spec, root)
    regenerate_regions(doc_path, surface, modes=modes)
    stamped = stored_region_hash(parse_doc(doc_path), "symbols")

    # A human edits the filled region in their own words -> hash diverges.
    text = doc_path.read_text(encoding="utf-8")
    text, _ = set_region(text, "symbols", "A human rewrote this.\nLocked now.")
    doc_path.write_text(text, encoding="utf-8")
    human_body = regions(parse_doc(doc_path))["symbols"]

    # Move the code AND re-heal: the locked region must be left untouched.
    (root / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    surface2 = build_document_surface(spec, root)
    regenerate_regions(doc_path, surface2, modes=modes)
    after = parse_doc(doc_path)
    assert regions(after)["symbols"] == human_body  # preserved (locked)
    # The stored hash is NOT moved to the human body (would unlock it falsely).
    assert stored_region_hash(after, "symbols") == stamped

    # Idempotent: a second heal writes nothing new to the region.
    body_now = regions(parse_doc(doc_path))["symbols"]
    regenerate_regions(doc_path, build_document_surface(spec, root), modes=modes)
    assert regions(parse_doc(doc_path))["symbols"] == body_now


def test_apply_fix_modes_locks_llm_seeded(tmp_path: Path) -> None:
    """At the apply_fix write boundary, a locked llm-seeded region is preserved
    even against a whole-doc fix that tries to re-author it (B-03)."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "src" / "mod.py").write_text(CODE_V1, encoding="utf-8")
    spec = _llm_seeded_spec(root)
    doc_path = root / spec.path
    doc_path.write_text(
        "# T\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    modes = {"symbols": RegionMode.LLM_SEEDED}
    regenerate_regions(doc_path, build_document_surface(spec, root), modes=modes)
    text = doc_path.read_text(encoding="utf-8")
    text, _ = set_region(text, "symbols", "human owns this now\n")
    doc_path.write_text(text, encoding="utf-8")
    human_body = regions(parse_doc(doc_path))["symbols"]

    clobber = (
        "# T\n\n<!-- CDM:BEGIN symbols -->\nBACKEND CLOBBER\n<!-- CDM:END symbols -->\n"
    )
    fix = FakeFix(new_doc_text=clobber)
    apply_fix(doc_path, fix, modes=modes)
    assert regions(parse_doc(doc_path))["symbols"] == human_body


def test_regenerate_regions_skips_preserved(tmp_path: Path) -> None:
    root, spec = _setup(tmp_path)
    doc_path = root / spec.path
    doc_path.write_text(_synced_text(spec, root), encoding="utf-8")
    # Drift the code; the symbols region would normally regenerate.
    (root / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    before_region = regions(parse_doc(doc_path))["symbols"]

    surface = build_document_surface(spec, root)
    changed = regenerate_regions(doc_path, surface, preserve=frozenset({"symbols"}))
    # The fingerprint still moves (HASH), so the file changed...
    assert changed is True
    # ...but the preserved region body is untouched.
    assert regions(parse_doc(doc_path))["symbols"] == before_region


def test_render_corrected_skips_preserved(tmp_path: Path) -> None:
    root, spec = _setup(tmp_path)
    doc_path = root / spec.path
    doc_path.write_text(_synced_text(spec, root), encoding="utf-8")
    (root / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    surface = build_document_surface(spec, root)
    original_text = doc_path.read_text(encoding="utf-8")
    original_region = regions(parse_doc(doc_path))["symbols"]

    corrected = render_corrected(
        original_text, surface, preserve=frozenset({"symbols"})
    )
    corrected_region = regions(parse_text(corrected))["symbols"]
    assert corrected_region == original_region


def test_regenerate_human_region_stamps_body_hash(tmp_path: Path) -> None:
    """B-02 retrofit via the engine heal: a human region's body hash is stamped
    (so its review advisory persists across a fingerprint heal) while its body
    is preserved byte-for-byte."""
    root, _ = _setup(tmp_path)
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols",),
        region_modes={"symbols": RegionMode.HUMAN},
    )
    doc_path = root / spec.path
    text = _synced_text(spec, root)
    text, _ = set_region(text, "symbols", "Human-owned prose.\nReview on change.")
    doc_path.write_text(text, encoding="utf-8")
    human_body = regions(parse_doc(doc_path))["symbols"]

    (root / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    surface = build_document_surface(spec, root)
    modes = {"symbols": RegionMode.HUMAN}
    regenerate_regions(doc_path, surface, preserve=frozenset({"symbols"}), modes=modes)
    after = parse_doc(doc_path)
    assert regions(after)["symbols"] == human_body  # body preserved
    assert stored_region_hash(after, "symbols") == region_body_hash(human_body)


def test_regenerate_modes_no_renderer_region_is_skipped(tmp_path: Path) -> None:
    """A generated-mode region with no known renderer is left as-is under modes
    (the `expected is None` path), not stamped or authored."""
    root, _ = _setup(tmp_path)
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols", "mystery"),
    )
    doc_path = root / spec.path
    surface = build_document_surface(spec, root)
    body = (
        "# T\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n\n"
        "<!-- CDM:BEGIN mystery -->\nopaque\n<!-- CDM:END mystery -->\n"
    )
    body, _ = set_region(body, "symbols", symbol_table(surface))
    doc_path.write_text(
        render_doc(set_fingerprint({}, surface.surface_hash()), body),
        encoding="utf-8",
    )
    modes = {"symbols": RegionMode.GENERATED, "mystery": RegionMode.GENERATED}
    regenerate_regions(doc_path, surface, modes=modes)
    after = parse_doc(doc_path)
    assert regions(after)["mystery"] == "opaque"  # no renderer -> untouched
    assert stored_region_hash(after, "mystery") is None  # not stamped


# ---------------------------------------------------------------------------
# B-06: no-renderer `llm` prose regions survive a whole-doc HASH heal
# ---------------------------------------------------------------------------
def _mixed_doc(tmp_path: Path) -> tuple[Path, DocumentSpec, str]:
    """A doc with `symbols` (rendered), an `llm` no-renderer prose region, and a
    `human` no-renderer region. Returns (root, spec, llm_prose_body)."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "src" / "mod.py").write_text(CODE_V1, encoding="utf-8")
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols", "overview", "notes"),
        region_modes={"overview": RegionMode.LLM, "notes": RegionMode.HUMAN},
    )
    surface = build_document_surface(spec, root)
    llm_body = "Authored prose covering greet."
    human_body = "Hand-written human notes."
    body = (
        "# T\n\n"
        "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n\n"
        "<!-- CDM:BEGIN overview -->\n<!-- CDM:END overview -->\n\n"
        "<!-- CDM:BEGIN notes -->\n<!-- CDM:END notes -->\n"
    )
    body, _ = set_region(body, "symbols", symbol_table(surface))
    body, _ = set_region(body, "overview", llm_body)
    body, _ = set_region(body, "notes", human_body)
    text = render_doc(set_fingerprint({}, surface.surface_hash()), body)
    (root / spec.path).write_text(text, encoding="utf-8")
    return root, spec, llm_body


def test_render_corrected_preserves_no_renderer_llm_region(tmp_path: Path) -> None:
    """B-06 (critical idempotence point): a whole-doc HASH fix regenerates the
    rendered region + fingerprint but PRESERVES a no-renderer `llm` region's body
    byte-identical (the separate REGION fix re-authors it; the HASH fix must never
    blank it)."""
    root, spec, llm_body = _mixed_doc(tmp_path)
    doc_path = root / spec.path
    # Move the code surface so a HASH heal is needed.
    (root / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    surface = build_document_surface(spec, root)
    modes = {rid: spec.mode_for(rid) for rid in spec.region_keys}

    corrected = render_corrected(
        doc_path.read_text(encoding="utf-8"), surface, modes=modes
    )
    new_regions = regions(parse_text(corrected))
    # rendered region refreshed...
    assert new_regions["symbols"] == symbol_table(surface)
    # ...but the no-renderer llm region body is byte-identical (NOT blanked).
    assert new_regions["overview"] == llm_body
    # ...and the human region is untouched too (B-02).
    assert new_regions["notes"] == "Hand-written human notes."


def test_apply_fix_authors_llm_region_and_leaves_human(tmp_path: Path) -> None:
    """B-06: an `llm` REGION fix injects the authored prose; a `human` region
    alongside is untouched (B-02), even via the same write path."""
    root, spec, _ = _mixed_doc(tmp_path)
    doc_path = root / spec.path
    preserve = frozenset({"notes"})
    modes = {rid: spec.mode_for(rid) for rid in spec.region_keys}

    human_before = regions(parse_doc(doc_path))["notes"]
    fix = FakeFix(region_id="overview", new_region_body="Newly authored prose.")
    assert apply_fix(doc_path, fix, preserve=preserve, modes=modes) is True

    after = regions(parse_doc(doc_path))
    assert after["overview"] == "Newly authored prose."
    assert after["notes"] == human_before  # human byte-identical


def test_apply_fix_whole_doc_never_blanks_llm_region(tmp_path: Path) -> None:
    """B-06: even a whole-doc FIX (HASH) re-injects the current no-renderer llm
    body at the write boundary — proving render_corrected + apply_fix together
    never silently drop the prose."""
    root, spec, llm_body = _mixed_doc(tmp_path)
    doc_path = root / spec.path
    (root / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    surface = build_document_surface(spec, root)
    modes = {rid: spec.mode_for(rid) for rid in spec.region_keys}
    preserve = frozenset({"notes"})

    corrected = render_corrected(
        doc_path.read_text(encoding="utf-8"), surface, modes=modes
    )
    fix = FakeFix(new_doc_text=corrected)
    apply_fix(doc_path, fix, preserve=preserve, modes=modes)
    after = regions(parse_doc(doc_path))
    assert after["overview"] == llm_body  # llm prose preserved through the heal
