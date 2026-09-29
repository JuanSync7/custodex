"""Tests for custodex.drift (CDM-03).

Detection is pure and side-effect free (K1). Covers each DriftKind, the
healable/audience fields, and — end to end through `detect` — the audience rule
(K3): a docstring-only edit drifts an eng-guide doc but NOT a user-guide doc
over the same code file.

Features: FEAT-DRIFT-001, FEAT-DRIFT-002, FEAT-DRIFT-003, FEAT-DRIFT-004
Features: FEAT-DRIFT-005, FEAT-DRIFT-006, FEAT-DRIFT-007, FEAT-DRIFT-008
Features: FEAT-DRIFT-009, FEAT-DRIFT-010, FEAT-CONFIG-011
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import cast

import pytest

from custodex.blocks import expected_region, symbol_table
from custodex.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
    RegionMode,
)
from custodex.drift import (
    AUTO_TIERS,
    ApplyTier,
    ChangeSeverity,
    Drift,
    DriftKind,
    DriftReport,
    auto_routable_docs,
    classify_apply_tier,
    classify_change_severity,
    detect,
    docs_closable_by,
    mechanical_docs,
)
from custodex.extract import anchor_id, build_document_surface
from custodex.heal import apply_fix, regenerate_regions
from custodex.manifest import (
    parse_doc,
    render_doc,
    set_fingerprint,
    set_fingerprint_tiers,
    set_region,
    set_region_anchors,
    set_symbol_sigs,
    stored_region_anchors,
    stored_symbol_sigs,
)
from custodex.schema import ProposedFix

CODE_V1 = '''\
def greet(name: str) -> str:
    """Say hello."""
    return f"hi {name}"


def _hidden(x):
    """Internal."""
    return x
'''

# Same public signatures; only a docstring and a private body changed (K3).
CODE_V2 = '''\
def greet(name: str) -> str:
    """Say hello to the user politely."""
    return f"hi {name}"


def _hidden(x):
    """Internal, now different."""
    return x + 1
'''


def _setup(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    return root


def _write_code(root: Path, text: str) -> None:
    (root / "src" / "mod.py").write_text(text, encoding="utf-8")


def _doc_spec(doc_id: str, audience: Audience) -> DocumentSpec:
    return DocumentSpec(
        id=doc_id,
        path=f"docs/{doc_id}.md",
        audience=audience,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols",),
    )


def _synced_doc_text(spec: DocumentSpec, root: Path) -> str:
    """Build doc text whose region + fingerprint match the current surface."""
    surface = build_document_surface(spec, root)
    body = "# Title\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    body, _ = set_region(body, "symbols", symbol_table(surface))
    meta = set_fingerprint({}, surface.surface_hash())
    return render_doc(meta, body)


def _config(root: Path, specs: tuple[DocumentSpec, ...]) -> MonitorConfig:
    return MonitorConfig(root="repo", documents=specs)


def test_detect_clean(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(_synced_doc_text(spec, root), encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    assert report.ok
    assert report.drifts == ()
    assert "clean" in report.summary().lower() or "no drift" in report.summary().lower()


def test_detect_missing_doc(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    report = detect(_config(root, (spec,)), tmp_path)
    assert not report.ok
    (d,) = report.drifts
    assert d.kind is DriftKind.MISSING_DOC
    assert d.healable is True
    assert d.audience is Audience.ENG_GUIDE
    assert d.doc_id == "eng-guide"
    assert "MISSING_DOC" in report.summary()


def test_detect_hash_drift(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(_synced_doc_text(spec, root), encoding="utf-8")
    # Change the code so the surface hash moves.
    _write_code(root, CODE_V2)
    report = detect(_config(root, (spec,)), tmp_path)
    kinds = {d.kind for d in report.drifts}
    assert DriftKind.HASH in kinds
    hash_drift = next(d for d in report.drifts if d.kind is DriftKind.HASH)
    assert hash_drift.healable is True
    assert hash_drift.detail


def test_detect_region_drift(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    text = _synced_doc_text(spec, root)
    # Corrupt only the region body, keep the fingerprint correct.
    text = text.replace(
        text.split("<!-- CDM:BEGIN symbols -->\n")[1].split("<!-- CDM:END symbols -->")[
            0
        ],
        "stale region contents\n",
    )
    (root / spec.path).write_text(text, encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    region_drift = next(d for d in report.drifts if d.kind is DriftKind.REGION)
    assert region_drift.region_id == "symbols"
    assert region_drift.healable is True


def test_detect_unhealable_unknown_region(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols", "mystery"),
    )
    surface = build_document_surface(spec, root)
    body = (
        "# Title\n\n"
        "<!-- CDM:BEGIN symbols -->\n"
        "<!-- CDM:END symbols -->\n\n"
        "<!-- CDM:BEGIN mystery -->\nhand written\n<!-- CDM:END mystery -->\n"
    )
    body, _ = set_region(body, "symbols", symbol_table(surface))
    meta = set_fingerprint({}, surface.surface_hash())
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    unhealable = next(d for d in report.drifts if d.kind is DriftKind.UNHEALABLE)
    assert unhealable.healable is False
    assert unhealable.region_id == "mystery"


def test_detect_is_side_effect_free(tmp_path: Path) -> None:
    """K1: detect never mutates the doc file."""
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    text = _synced_doc_text(spec, root)
    (root / spec.path).write_text(text, encoding="utf-8")
    _write_code(root, CODE_V2)
    detect(_config(root, (spec,)), tmp_path)
    assert (root / spec.path).read_text(encoding="utf-8") == text


def test_audience_split_docstring_only_change(tmp_path: Path) -> None:
    """K3 end-to-end: two docs over the same file, different audiences.

    Editing only a docstring (and a private body) must keep the user-guide doc
    clean while drifting the eng-guide doc.
    """
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    user_spec = _doc_spec("user-guide", Audience.USER_GUIDE)
    eng_spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    for spec in (user_spec, eng_spec):
        (root / spec.path).write_text(_synced_doc_text(spec, root), encoding="utf-8")

    # Edit only the docstring + a private symbol body.
    _write_code(root, CODE_V2)

    report = detect(_config(root, (user_spec, eng_spec)), tmp_path)
    by_doc = {d.doc_id for d in report.drifts}
    # User-guide stays clean; eng-guide drifts.
    assert "user-guide" not in by_doc
    assert "eng-guide" in by_doc
    eng_drift = next(d for d in report.drifts if d.doc_id == "eng-guide")
    assert eng_drift.audience is Audience.ENG_GUIDE


def test_drift_report_summary_and_ok() -> None:
    empty = DriftReport(drifts=())
    assert empty.ok
    d = Drift(
        kind=DriftKind.HASH,
        doc_id="x",
        doc_path="docs/x.md",
        detail="moved",
        audience=Audience.ENG_GUIDE,
    )
    rep = DriftReport(drifts=(d,))
    assert not rep.ok
    assert "x" in rep.summary()


def test_detect_ignores_region_not_declared_by_spec(tmp_path: Path) -> None:
    """A region present in the doc but absent from spec.region_keys is ignored."""
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=(),  # declares NO managed regions
    )
    surface = build_document_surface(spec, root)
    body = "# T\n\n<!-- CDM:BEGIN symbols -->\nstale\n<!-- CDM:END symbols -->\n"
    meta = set_fingerprint({}, surface.surface_hash())
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    # The undeclared region is not graded, so the report is clean.
    assert report.ok


def test_detect_human_region_stale_is_reported_unhealable(tmp_path: Path) -> None:
    """B-02: a human-owned renderer-backed region that is stale → REGION,
    healable=False (reported for review, but the engine will not auto-edit)."""
    from custodex.config import RegionMode

    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols",),
        region_modes={"symbols": RegionMode.HUMAN},
    )
    # Start in sync (region = human body, fingerprint matches V1), then move the
    # CODE. A human region's body always differs from the generated render, so
    # the review signal fires only when the code it reflects changes (the
    # fingerprint going stale), not on every human wording. Both a HASH and the
    # human REGION drift result; we assert on the REGION one.
    text = _synced_doc_text(spec, root)
    region_body = text.split("<!-- CDM:BEGIN symbols -->\n")[1].split(
        "<!-- CDM:END symbols -->"
    )[0]
    text = text.replace(region_body, "a human wrote this and tweaked it\n")
    (root / spec.path).write_text(text, encoding="utf-8")
    _write_code(root, CODE_V2)  # code moves -> fingerprint stale -> review fires

    report = detect(_config(root, (spec,)), tmp_path)
    region = next(d for d in report.drifts if d.kind is DriftKind.REGION)
    assert region.region_id == "symbols"
    assert region.healable is False
    assert "human-owned" in region.detail
    assert "(UNHEALABLE)" in report.summary()


def test_detect_human_region_no_renderer_suppresses_unhealable(tmp_path: Path) -> None:
    """B-02: a human region the engine cannot render is intentional, not an
    error — the UNHEALABLE drift is suppressed for it."""
    from custodex.config import RegionMode

    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols", "mystery"),
        region_modes={"mystery": RegionMode.HUMAN},
    )
    surface = build_document_surface(spec, root)
    body = (
        "# Title\n\n"
        "<!-- CDM:BEGIN symbols -->\n"
        "<!-- CDM:END symbols -->\n\n"
        "<!-- CDM:BEGIN mystery -->\nhand written\n<!-- CDM:END mystery -->\n"
    )
    body, _ = set_region(body, "symbols", symbol_table(surface))
    meta = set_fingerprint({}, surface.surface_hash())
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")

    report = detect(_config(root, (spec,)), tmp_path)
    # No UNHEALABLE drift for the intentionally-human no-renderer region.
    assert all(d.kind is not DriftKind.UNHEALABLE for d in report.drifts)


def test_detect_generated_region_no_renderer_still_unhealable(tmp_path: Path) -> None:
    """B-02 additive: a NON-human region with no renderer is still UNHEALABLE."""
    from custodex.config import RegionMode

    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols", "mystery"),
        region_modes={"mystery": RegionMode.GENERATED},  # explicit default
    )
    surface = build_document_surface(spec, root)
    body = (
        "# Title\n\n"
        "<!-- CDM:BEGIN symbols -->\n"
        "<!-- CDM:END symbols -->\n\n"
        "<!-- CDM:BEGIN mystery -->\nhand written\n<!-- CDM:END mystery -->\n"
    )
    body, _ = set_region(body, "symbols", symbol_table(surface))
    meta = set_fingerprint({}, surface.surface_hash())
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")

    report = detect(_config(root, (spec,)), tmp_path)
    assert any(
        d.kind is DriftKind.UNHEALABLE and d.region_id == "mystery"
        for d in report.drifts
    )


def test_expected_region_unknown_id_is_none() -> None:
    spec = DocumentSpec(
        id="e",
        path="docs/e.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(),
    )
    surface = build_document_surface(spec, Path("."))
    assert expected_region("nope", surface) is None
    assert expected_region("symbols", surface) is not None


# --- B-03: llm-seeded lock in drift -----------------------------------------


def _llm_seeded_spec_drift() -> DocumentSpec:
    return DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols",),
        region_modes={"symbols": RegionMode.LLM_SEEDED},
    )


def _seeded_doc_text(spec: DocumentSpec, root: Path, body: str | None = None) -> str:
    """A doc whose symbols region is filled + stamped with its body hash."""
    from custodex.manifest import region_body_hash, set_region_hash

    surface = build_document_surface(spec, root)
    filled = symbol_table(surface) if body is None else body
    doc_body = "# Title\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    doc_body, _ = set_region(doc_body, "symbols", filled)
    meta = set_fingerprint({}, surface.surface_hash())
    meta = set_region_hash(meta, "symbols", region_body_hash(filled))
    return render_doc(meta, doc_body)


def test_llm_seeded_unlocked_behaves_like_generated(tmp_path: Path) -> None:
    """An unlocked llm-seeded region (body == stamp) that is stale on a code move
    is REGION healable=True, exactly like a generated region."""

    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _llm_seeded_spec_drift()
    (root / spec.path).write_text(_seeded_doc_text(spec, root), encoding="utf-8")
    assert detect(_config(root, (spec,)), tmp_path).ok  # in sync

    # Move a public signature so the symbols REGION genuinely drifts.
    _write_code(
        root,
        CODE_V1.replace("def greet(name: str)", "def greet(name: str, x: int = 0)"),
    )
    report = detect(_config(root, (spec,)), tmp_path)
    region = next(d for d in report.drifts if d.kind is DriftKind.REGION)
    assert region.region_id == "symbols"
    assert region.healable is True
    assert "human-owned" not in region.detail


def test_llm_seeded_locked_behaves_like_human(tmp_path: Path) -> None:
    """Once a human edits the llm-seeded body (hash diverges), a code move makes
    it REGION healable=False with the human-owned advisory (locked)."""

    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _llm_seeded_spec_drift()
    # Seed with a human-edited body whose hash is stamped to the ORIGINAL fill
    # (so the current human body diverges from the stamp -> locked).
    surface = build_document_surface(spec, root)
    from custodex.manifest import region_body_hash, set_region_hash

    body = "# Title\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    body, _ = set_region(body, "symbols", "a human took this over\n")
    meta = set_fingerprint({}, surface.surface_hash())
    meta = set_region_hash(meta, "symbols", region_body_hash(symbol_table(surface)))
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")

    # Move the public signature so the code (fingerprint) drifts.
    _write_code(
        root,
        CODE_V1.replace("def greet(name: str)", "def greet(name: str, x: int = 0)"),
    )
    report = detect(_config(root, (spec,)), tmp_path)
    region = next(d for d in report.drifts if d.kind is DriftKind.REGION)
    assert region.region_id == "symbols"
    assert region.healable is False
    assert "human-owned" in region.detail


def test_human_region_advisory_persists_across_fingerprint_heal(tmp_path: Path) -> None:
    """B-02 retrofit: a human region with a stamped hash keeps firing its
    advisory even after the fingerprint is in sync — until the body changes."""
    from custodex.manifest import region_body_hash, set_region_hash

    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols",),
        region_modes={"symbols": RegionMode.HUMAN},
    )
    human_body = "Hand-written notes a human owns.\nReview me on code change."
    # Fingerprint is IN SYNC (no HASH drift) but the region carries a stamped
    # hash that equals the current body -> the persisted "needs review" advisory.
    surface = build_document_surface(spec, root)
    body = "# Title\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    body, _ = set_region(body, "symbols", human_body)
    meta = set_fingerprint({}, surface.surface_hash())
    meta = set_region_hash(meta, "symbols", region_body_hash(human_body))
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")

    report = detect(_config(root, (spec,)), tmp_path)
    region = next(d for d in report.drifts if d.kind is DriftKind.REGION)
    assert region.region_id == "symbols"
    assert region.healable is False
    assert "human-owned" in region.detail

    # The human edits the body -> hash diverges -> advisory CLEARS.
    text = (root / spec.path).read_text(encoding="utf-8")
    text, _ = set_region(text, "symbols", "Now the human updated the prose.\nDone.")
    (root / spec.path).write_text(text, encoding="utf-8")
    report2 = detect(_config(root, (spec,)), tmp_path)
    assert all(d.kind is not DriftKind.REGION for d in report2.drifts)


# ---------------------------------------------------------------------------
# B-06: pure-`llm` (no-renderer) prose-authored regions
# ---------------------------------------------------------------------------
def _llm_no_renderer_doc(
    tmp_path: Path,
) -> tuple[Path, DocumentSpec, MonitorConfig]:
    """A doc with `symbols` (rendered) + an `llm` no-renderer prose region.

    The prose region (`overview`) has no template and no built-in renderer, so
    `expected_region` returns None for it: it is authored by the backend (B-06).
    """
    from custodex.config import RegionMode

    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols", "overview"),
        region_modes={"overview": RegionMode.LLM},
    )
    surface = build_document_surface(spec, root)
    body = (
        "# Title\n\n"
        "<!-- CDM:BEGIN symbols -->\n"
        "<!-- CDM:END symbols -->\n\n"
        "<!-- CDM:BEGIN overview -->\nAuthored prose about greet.\n"
        "<!-- CDM:END overview -->\n"
    )
    body, _ = set_region(body, "symbols", symbol_table(surface))
    meta = set_fingerprint({}, surface.surface_hash())
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")
    return root, spec, _config(root, (spec,))


def test_detect_llm_no_renderer_code_unchanged_is_not_drift(tmp_path: Path) -> None:
    """B-06: an `llm` no-renderer region whose code is unchanged is NOT drift.

    Its prose legitimately differs from any mechanical render; with the surface
    fingerprint in sync, the prose stands and the engine raises nothing for it.
    """
    root, spec, cfg = _llm_no_renderer_doc(tmp_path)
    report = detect(cfg, tmp_path)
    # No UNHEALABLE for the llm prose region, and no REGION drift on it either.
    assert all(d.region_id != "overview" for d in report.drifts)
    assert report.ok


def test_detect_llm_no_renderer_code_moved_is_healable_region(tmp_path: Path) -> None:
    """B-06: when the code surface moves, the `llm` no-renderer region surfaces
    as a healable REGION drift (the backend re-authors), NOT UNHEALABLE."""
    root, spec, cfg = _llm_no_renderer_doc(tmp_path)
    _write_code(root, CODE_V2 + "\n\ndef added(z):\n    return z\n")  # surface moves

    report = detect(cfg, tmp_path)
    overview = next(d for d in report.drifts if d.region_id == "overview")
    assert overview.kind is DriftKind.REGION
    assert overview.healable is True
    assert overview.kind is not DriftKind.UNHEALABLE
    assert "llm" in overview.detail.lower()
    # No UNHEALABLE drift for it anywhere.
    assert all(
        not (d.kind is DriftKind.UNHEALABLE and d.region_id == "overview")
        for d in report.drifts
    )


def test_detect_non_llm_no_renderer_still_unhealable(tmp_path: Path) -> None:
    """B-06: a NON-`llm` (generated) no-renderer region is still UNHEALABLE even
    when the code moves — there is genuinely no authoring path (loud, K8)."""
    from custodex.config import RegionMode

    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = DocumentSpec(
        id="eng-guide",
        path="docs/eng-guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols", "overview"),
        region_modes={"overview": RegionMode.GENERATED},
    )
    surface = build_document_surface(spec, root)
    body = (
        "# Title\n\n"
        "<!-- CDM:BEGIN symbols -->\n"
        "<!-- CDM:END symbols -->\n\n"
        "<!-- CDM:BEGIN overview -->\nprose\n<!-- CDM:END overview -->\n"
    )
    body, _ = set_region(body, "symbols", symbol_table(surface))
    meta = set_fingerprint({}, surface.surface_hash())
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")
    _write_code(root, CODE_V2 + "\n\ndef added(z):\n    return z\n")

    report = detect(_config(root, (spec,)), tmp_path)
    assert any(
        d.kind is DriftKind.UNHEALABLE and d.region_id == "overview"
        for d in report.drifts
    )


# --------------------------------------------------------------------------- #
# P-01: opt-in body-AST fingerprint tier                                       #
# --------------------------------------------------------------------------- #
# greet's signature AND docstring are unchanged; only the returned string (the
# body) differs — a pure implementation change.
CODE_BODY_ONLY = '''\
def greet(name: str) -> str:
    """Say hello."""
    return f"hello {name}"


def _hidden(x):
    """Internal."""
    return x
'''


def _synced_on(spec: DocumentSpec, root: Path) -> str:
    """Doc text whose fingerprint is stamped WITH the body tier (flag ON)."""
    surface = build_document_surface(spec, root)
    body = "# Title\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    body, _ = set_region(body, "symbols", symbol_table(surface))
    meta = set_fingerprint({}, surface.surface_hash(include_body=True))
    return render_doc(meta, body)


def _config_on(root: Path, specs: tuple[DocumentSpec, ...]) -> MonitorConfig:
    return MonitorConfig(root="repo", documents=specs, fingerprint_body_tier=True)


def test_config_body_tier_defaults_off(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    assert _config(root, (spec,)).fingerprint_body_tier is False


def test_body_only_change_no_drift_when_flag_off(tmp_path: Path) -> None:
    """A public body-only change is invisible to the default (OFF) fingerprint."""
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(_synced_doc_text(spec, root), encoding="utf-8")
    _write_code(root, CODE_BODY_ONLY)
    report = detect(_config(root, (spec,)), tmp_path)
    assert DriftKind.HASH not in {d.kind for d in report.drifts}


def test_body_only_change_drifts_eng_guide_when_flag_on(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(_synced_on(spec, root), encoding="utf-8")
    _write_code(root, CODE_BODY_ONLY)
    report = detect(_config_on(root, (spec,)), tmp_path)
    assert DriftKind.HASH in {d.kind for d in report.drifts}


def test_body_only_change_never_drifts_user_guide_when_flag_on(tmp_path: Path) -> None:
    """K3 hard line: a body change is a non-event for the user-guide, flag or not."""
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("user-guide", Audience.USER_GUIDE)
    (root / spec.path).write_text(_synced_on(spec, root), encoding="utf-8")
    _write_code(root, CODE_BODY_ONLY)
    report = detect(_config_on(root, (spec,)), tmp_path)
    assert DriftKind.HASH not in {d.kind for d in report.drifts}


def test_stamp_on_detect_on_is_clean(tmp_path: Path) -> None:
    """One-shared-truth: a fingerprint stamped ON is clean to detect ON."""
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(_synced_on(spec, root), encoding="utf-8")
    report = detect(_config_on(root, (spec,)), tmp_path)
    assert report.ok


# --------------------------------------------------------------------------- #
# P-02: which-tier-moved reporting (Drift.drifted_tiers)                       #
# --------------------------------------------------------------------------- #
# Same signature + docstring; only the public body differs (flag-ON visible).
CODE_BODY_EDIT = '''\
def greet(name: str) -> str:
    """Say hello."""
    return f"HELLO {name}"


def _hidden(x):
    """Internal."""
    return x
'''

# Signature changed (drops the param) — moves the signature tier for any audience.
CODE_SIG_EDIT = '''\
def greet() -> str:
    """Say hello."""
    return "hi"


def _hidden(x):
    """Internal."""
    return x
'''


def _synced_tiers(spec: DocumentSpec, root: Path, *, include_body: bool) -> str:
    """Synced doc text stamping BOTH the composite and the per-tier digests."""
    surface = build_document_surface(spec, root)
    body = "# Title\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    body, _ = set_region(body, "symbols", symbol_table(surface))
    fp = surface.fingerprint(include_body=include_body)
    meta = set_fingerprint({}, fp.composite)
    meta = set_fingerprint_tiers(meta, fp)
    return render_doc(meta, body)


def _hash_drift(report: DriftReport) -> Drift:
    return next(d for d in report.drifts if d.kind is DriftKind.HASH)


def test_hash_drift_reports_body_tier(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_BODY_ONLY)  # greet body == f"hello {name}"
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_tiers(spec, root, include_body=True), encoding="utf-8"
    )
    _write_code(root, CODE_BODY_EDIT)  # only greet's body changed
    report = detect(_config_on(root, (spec,)), tmp_path)
    assert _hash_drift(report).drifted_tiers == ("body",)


def test_hash_drift_reports_signature_tier(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_tiers(spec, root, include_body=False), encoding="utf-8"
    )
    _write_code(root, CODE_SIG_EDIT)
    report = detect(_config(root, (spec,)), tmp_path)
    assert _hash_drift(report).drifted_tiers == ("signature",)


def test_hash_drift_reports_docstring_tier(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_tiers(spec, root, include_body=False), encoding="utf-8"
    )
    _write_code(root, CODE_V2)  # docstring (+private body) changed
    report = detect(_config(root, (spec,)), tmp_path)
    assert _hash_drift(report).drifted_tiers == ("docstring",)


def test_hash_drift_without_stored_tiers_falls_back(tmp_path: Path) -> None:
    """An old doc with only a composite fingerprint drifts with empty drifted_tiers."""
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_doc_text(spec, root),
        encoding="utf-8",  # composite only, no tiers
    )
    _write_code(root, CODE_SIG_EDIT)
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.drifted_tiers == ()
    assert "fingerprint" in drift.detail  # the composite-only fallback message


# --------------------------------------------------------------------------- #
# P-04: anchor delta on a HASH drift (symbol moved/stable vs added/removed)     #
# --------------------------------------------------------------------------- #

# CODE_V1 + a NEW public function (signature tier moves → HASH drift).
CODE_PLUS_SYMBOL = '''\
def greet(name: str) -> str:
    """Say hello."""
    return f"hi {name}"


def farewell(name: str) -> str:
    """Say bye."""
    return f"bye {name}"


def _hidden(x):
    """Internal."""
    return x
'''


def _synced_anchored(spec: DocumentSpec, root: Path, *, include_body: bool) -> str:
    """Synced doc text stamping composite + per-tier digests + region anchors."""
    surface = build_document_surface(spec, root)
    body = "# Title\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    body, _ = set_region(body, "symbols", symbol_table(surface))
    fp = surface.fingerprint(include_body=include_body)
    meta = set_fingerprint({}, fp.composite)
    meta = set_fingerprint_tiers(meta, fp)
    meta = set_region_anchors(
        meta, "symbols", tuple(s.anchor_id for s in surface.symbols)
    )
    return render_doc(meta, body)


def test_body_only_change_keeps_anchors_stable(tmp_path: Path) -> None:
    """Re-bind: the SAME symbol identities, only a body changed (P4 + P2 tiers)."""
    root = _setup(tmp_path)
    _write_code(root, CODE_BODY_ONLY)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_anchored(spec, root, include_body=True), encoding="utf-8"
    )
    _write_code(root, CODE_BODY_EDIT)  # greet body only
    drift = _hash_drift(detect(_config_on(root, (spec,)), tmp_path))
    assert drift.drifted_tiers == ("body",)
    assert drift.anchors_added == ()  # no symbol added/removed/renamed
    assert drift.anchors_removed == ()


def test_added_symbol_reports_anchor_added(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_anchored(spec, root, include_body=False), encoding="utf-8"
    )
    _write_code(root, CODE_PLUS_SYMBOL)  # adds public `farewell`
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.anchors_added == (anchor_id("farewell"),)
    assert drift.anchors_removed == ()


def test_removed_symbol_reports_anchor_removed(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_PLUS_SYMBOL)  # greet + farewell + _hidden
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_anchored(spec, root, include_body=False), encoding="utf-8"
    )
    _write_code(root, CODE_V1)  # drops `farewell`
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.anchors_removed == (anchor_id("farewell"),)
    assert drift.anchors_added == ()


def test_old_doc_without_anchors_has_no_delta(tmp_path: Path) -> None:
    """A pre-P4 doc (composite only, no stored anchors) → empty anchor delta."""
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(_synced_doc_text(spec, root), encoding="utf-8")
    _write_code(root, CODE_PLUS_SYMBOL)
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.anchors_added == ()
    assert drift.anchors_removed == ()


# --------------------------------------------------------------------------- #
# P-05: breaking-change severity (Drift.change_severity) — the Griffe-style       #
# verdict over the P2 tiers + P4 anchors.                                         #
#                                                                                 #
# Feature: FEAT-DRIFT-011                                                          #
# --------------------------------------------------------------------------- #
def test_classify_change_severity_truth_table() -> None:
    C = ChangeSeverity
    # a removed/renamed symbol dominates → BREAKING (even alongside an addition).
    assert classify_change_severity((), (), ("greet",)) is C.BREAKING
    assert classify_change_severity(("signature",), ("new",), ("old",)) is C.BREAKING
    # DIG-01: a surviving symbol's in-place signature change → BREAKING, ABOVE the
    # addition rule (so a simultaneous add + in-place change is no longer masked).
    assert (
        classify_change_severity(("signature",), ("new",), (), ("greet",)) is C.BREAKING
    )
    # a pure addition (no survivor's signature moved) → ADDITIVE, even with sig tier.
    assert classify_change_severity(("signature",), ("new",), (), ()) is C.ADDITIVE
    # same symbol set, signature tier moved in place, no per-symbol digests → BREAKING.
    assert classify_change_severity(("signature",), (), ()) is C.BREAKING
    # only docstring/body prose moved, same symbols → COSMETIC.
    assert classify_change_severity(("docstring",), (), ()) is C.COSMETIC
    assert classify_change_severity(("body",), (), ()) is C.COSMETIC
    # no signal at all (a pre-P2/P4 composite-only doc) → UNKNOWN.
    assert classify_change_severity((), (), ()) is C.UNKNOWN


def test_classify_change_severity_masked_case_closed_by_digests() -> None:
    """DIG-01 closes the former masked false-negative: an addition concurrent with an
    in-place signature change is BREAKING WHEN per-symbol digests name the changed
    survivor; without them (a pre-DIG-01 doc, ``sigs_changed`` empty) it degrades to
    ADDITIVE, never over-firing on a pure addition."""
    C = ChangeSeverity
    # add + in-place signature change of a SURVIVING symbol → BREAKING (now caught).
    assert (
        classify_change_severity(("signature",), ("new",), (), ("greet",)) is C.BREAKING
    )
    # the SAME aggregate signals, but no per-symbol digests → degrade to ADDITIVE.
    assert classify_change_severity(("signature",), ("new",), ()) is C.ADDITIVE
    # a pure addition with digests present (no survivor changed) stays ADDITIVE.
    assert classify_change_severity(("signature",), ("new",), (), ()) is C.ADDITIVE
    # a removal alongside the addition is still caught first (step 1) → BREAKING.
    assert classify_change_severity(("signature",), ("new",), ("gone",)) is C.BREAKING


def test_added_symbol_is_additive(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_anchored(spec, root, include_body=False), encoding="utf-8"
    )
    _write_code(root, CODE_PLUS_SYMBOL)  # adds public `farewell`
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.change_severity is ChangeSeverity.ADDITIVE


def test_removed_symbol_is_breaking(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_PLUS_SYMBOL)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_anchored(spec, root, include_body=False), encoding="utf-8"
    )
    _write_code(root, CODE_V1)  # drops `farewell`
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.change_severity is ChangeSeverity.BREAKING


def test_inplace_signature_change_is_breaking(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_tiers(spec, root, include_body=False), encoding="utf-8"
    )
    _write_code(root, CODE_SIG_EDIT)  # same symbol, dropped param
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.change_severity is ChangeSeverity.BREAKING
    # and it surfaces in the human summary (additive token).
    assert "[breaking]" in report.summary()


def test_docstring_only_change_is_cosmetic(tmp_path: Path) -> None:
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_tiers(spec, root, include_body=False), encoding="utf-8"
    )
    _write_code(root, CODE_V2)  # docstring (+private body) changed
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.change_severity is ChangeSeverity.COSMETIC


def test_old_doc_severity_is_unknown(tmp_path: Path) -> None:
    """A composite-only doc has no structural signal → UNKNOWN (and no summary tag)."""
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(_synced_doc_text(spec, root), encoding="utf-8")
    _write_code(root, CODE_SIG_EDIT)
    report = detect(_config(root, (spec,)), tmp_path)
    assert _hash_drift(report).change_severity is ChangeSeverity.UNKNOWN
    # UNKNOWN stays silent in the summary (no severity token).
    assert "[unknown]" not in report.summary()


# --------------------------------------------------------------------------- #
# DIG-01: per-symbol signature digests close the masked add+in-place-signature  #
# false-negative. `_synced_with_sigs` stamps cdm.symbol_sigs (a DIG-01 doc);    #
# `_synced_anchored` does NOT (a pre-DIG-01 doc → graceful degrade).            #
#                                                                              #
# Feature: FEAT-DRIFT-012                                                       #
# --------------------------------------------------------------------------- #

# greet GAINS a parameter (in-place signature change) AND a new public `farewell`
# is added — in a SINGLE edit. The aggregate signals alone read this as ADDITIVE.
CODE_ADD_PLUS_SIG_EDIT = '''\
def greet(name: str, loud: bool = False) -> str:
    """Say hello."""
    return f"hi {name}"


def farewell(name: str) -> str:
    """Say bye."""
    return f"bye {name}"


def _hidden(x):
    """Internal."""
    return x
'''


def _synced_with_sigs(spec: DocumentSpec, root: Path, *, include_body: bool) -> str:
    """Synced doc text stamping composite + tiers + region anchors + symbol_sigs."""
    surface = build_document_surface(spec, root)
    body = "# Title\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    body, _ = set_region(body, "symbols", symbol_table(surface))
    fp = surface.fingerprint(include_body=include_body)
    meta = set_fingerprint({}, fp.composite)
    meta = set_fingerprint_tiers(meta, fp)
    meta = set_region_anchors(
        meta, "symbols", tuple(s.anchor_id for s in surface.symbols)
    )
    meta = set_symbol_sigs(meta, fp.sig_by_anchor or {})
    return render_doc(meta, body)


def test_masked_add_plus_inplace_signature_is_breaking(tmp_path: Path) -> None:
    """THE fix: add a symbol AND change a surviving symbol's signature in one edit →
    BREAKING (was ADDITIVE before per-symbol digests)."""
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_with_sigs(spec, root, include_body=False), encoding="utf-8"
    )
    _write_code(root, CODE_ADD_PLUS_SIG_EDIT)  # adds farewell + greet gains a param
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.change_severity is ChangeSeverity.BREAKING
    # exactly the surviving symbol greet (by stable anchor_id) — not the added farewell.
    assert drift.sigs_changed == (anchor_id("greet"),)
    assert "[breaking]" in report.summary()


def test_masked_add_without_digests_degrades_to_additive(tmp_path: Path) -> None:
    """Back-compat (K6): the SAME edit on a pre-DIG-01 doc (region anchors but NO
    symbol_sigs) degrades to the old ADDITIVE — it must never crash."""
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_anchored(spec, root, include_body=False), encoding="utf-8"
    )
    _write_code(root, CODE_ADD_PLUS_SIG_EDIT)
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.change_severity is ChangeSeverity.ADDITIVE  # degraded, not crashed
    assert drift.sigs_changed == ()  # no stored digests → nothing to compare


def test_pure_addition_with_digests_stays_additive(tmp_path: Path) -> None:
    """No over-fire: with digests present, a PURE addition (no survivor's signature
    moved) is still ADDITIVE."""
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_with_sigs(spec, root, include_body=False), encoding="utf-8"
    )
    _write_code(root, CODE_PLUS_SYMBOL)  # adds farewell; greet unchanged
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.change_severity is ChangeSeverity.ADDITIVE
    assert drift.sigs_changed == ()  # greet's signature did not move


def test_docstring_only_change_with_digests_stays_cosmetic(tmp_path: Path) -> None:
    """No over-fire: with digests present, a docstring/private-body-only change of a
    surviving symbol is still COSMETIC (its SIGNATURE digest is unchanged)."""
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_with_sigs(spec, root, include_body=False), encoding="utf-8"
    )
    _write_code(root, CODE_V2)  # docstring + private body changed; signatures intact
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.change_severity is ChangeSeverity.COSMETIC
    assert drift.sigs_changed == ()


# --------------------------------------------------------------------------- #
# RTE-01: the apply-tier router (Drift.apply_tier / classify_apply_tier /        #
# auto_routable_docs) — provenance, never a score (K11). The tier says WHICH     #
# AUTHORITY can close a drift; it is a pure classification over signals `detect` #
# already captures, so it needs no backend, no clock and no network (K1/K10).    #
#                                                                                #
# Feature: FEAT-DRIFT-013                                                         #
# --------------------------------------------------------------------------- #
def _tier(
    kind: DriftKind,
    severity: ChangeSeverity = ChangeSeverity.UNKNOWN,
    **kw: object,
) -> tuple[ApplyTier, tuple[str, ...]]:
    """Call the classifier with `healable=True` unless a case overrides it."""
    kw.setdefault("healable", True)
    return classify_apply_tier(kind, severity, **kw)  # type: ignore[arg-type]


def test_classify_apply_tier_truth_table() -> None:
    """Every rule of the ordered precedence chain, in table order.

    Mirrors ``test_classify_change_severity_truth_table``: the chain is TOTAL and
    deny-by-default, so this table is the contract. A rule that stops firing here
    is a routing regression, and routing decides what gets written unattended.
    """
    T, K, C = ApplyTier, DriftKind, ChangeSeverity

    # 1. a doc<->doc suspect edge is never closable from the code surface.
    assert _tier(K.SUSPECT_LINK, healable=False) == (T.NEEDS_INTENT, ("doc-doc-edge",))
    # 2. there is no document yet — writing one is an authoring decision.
    assert _tier(K.MISSING_DOC) == (T.NEEDS_INTENT, ("no-document-yet",))
    # 3. a managed region with no renderer cannot be regenerated at all.
    assert _tier(K.UNHEALABLE, healable=False) == (T.NEEDS_INTENT, ("no-renderer",))
    # 4. a human-owned REGION whose code moved: reported, never auto-edited.
    assert _tier(K.REGION, healable=False) == (T.NEEDS_INTENT, ("human-owned",))
    # 5. the classifier is not given the LOCK state, only the mode — so it denies
    #    the whole mode it cannot fully evaluate (see ARCHITECTURE EPIC RTE).
    assert _tier(K.REGION, region_mode=RegionMode.HUMAN, renderer_backed=True) == (
        T.NEEDS_INTENT,
        ("human-owned-region",),
    )
    assert _tier(K.REGION, region_mode=RegionMode.LLM_SEEDED, renderer_backed=True) == (
        T.NEEDS_INTENT,
        ("human-owned-region",),
    )
    # 6. a renderer-backed region IS a pure projection of the surface — no model.
    assert _tier(K.REGION, region_id="symbols", renderer_backed=True) == (
        T.CODE_DERIVED,
        ("mechanical-render", "region:symbols"),
    )
    # 7. prose in a region a HUMAN declared `mode: llm` — delegated, not derived.
    assert _tier(K.REGION, region_id="overview", region_mode=RegionMode.LLM) == (
        T.DELEGATED,
        ("delegated-prose", "region:overview"),
    )
    # 8. any other REGION drift is authored prose the engine does not own.
    assert _tier(K.REGION, region_id="notes") == (T.NEEDS_INTENT, ("authored-prose",))
    # 9. BREAKING: prose naming a removed/renamed symbol is now FALSE.
    assert _tier(K.HASH, C.BREAKING) == (T.NEEDS_INTENT, ("severity:breaking",))
    # 10. UNKNOWN is overloaded (not-a-HASH vs legacy-doc) — never auto-apply it.
    assert _tier(K.HASH, C.UNKNOWN) == (T.NEEDS_INTENT, ("severity:unknown",))
    # 11. COSMETIC/ADDITIVE cannot have falsified a sentence -> mechanical refresh.
    assert _tier(K.HASH, C.COSMETIC) == (
        T.CODE_DERIVED,
        ("severity:cosmetic", "surface-refresh"),
    )
    assert _tier(K.HASH, C.ADDITIVE) == (
        T.CODE_DERIVED,
        ("severity:additive", "surface-refresh"),
    )


def test_classify_apply_tier_terminal_denies_an_unhandled_kind() -> None:
    """A DriftKind added LATER with no rule written must DENY, not fall through.

    This is the single most safety-relevant line in the chain, and it is
    unreachable through the enum today precisely because every current kind is
    handled — so it can only be exercised by simulating the future mistake it
    exists to catch: a new kind reaching a classifier nobody updated. Without the
    terminal, such a kind would fall off the end and (once RTE-03 reads the tier)
    could be written unattended.
    """

    class _FutureKind(str, Enum):
        NEW = "NEW"

    tier, evidence = classify_apply_tier(
        cast(DriftKind, _FutureKind.NEW), ChangeSeverity.UNKNOWN, healable=True
    )
    assert tier is ApplyTier.NEEDS_INTENT
    assert evidence == ("unclassified",)


def test_drift_model_default_is_the_deny_value() -> None:
    """A Drift built OUTSIDE `detect` is never auto-routable.

    Detection is not the only way a Drift comes into being (tests, adapters, a
    future caller), so the field default — not just the classifier — has to be the
    deny value.
    """
    d = Drift(
        kind=DriftKind.HASH,
        doc_id="d",
        doc_path="d.md",
        detail="hand-built outside detect",
        audience=Audience.ENG_GUIDE,
    )
    assert d.apply_tier is ApplyTier.NEEDS_INTENT
    assert d.tier_evidence == ()
    assert not d.apply_tier.is_auto
    assert auto_routable_docs(DriftReport(drifts=(d,))) == frozenset()


def test_apply_tier_evidence_is_sorted_and_route_is_derived() -> None:
    """Evidence is a sorted tuple (K10) and the route is DERIVED from the tier."""
    _, evidence = classify_apply_tier(
        DriftKind.HASH, ChangeSeverity.COSMETIC, healable=True
    )
    assert list(evidence) == sorted(evidence)
    assert ApplyTier.CODE_DERIVED.is_auto is True
    assert ApplyTier.DELEGATED.is_auto is True
    assert ApplyTier.NEEDS_INTENT.is_auto is False


def _d(doc_id: str, kind: DriftKind, tier: ApplyTier) -> Drift:
    return Drift(
        kind=kind,
        doc_id=doc_id,
        doc_path=f"{doc_id}.md",
        detail="x",
        audience=Audience.ENG_GUIDE,
        healable=kind is not DriftKind.SUSPECT_LINK,
        apply_tier=tier,
    )


def test_auto_routable_docs_is_per_document_not_per_drift() -> None:
    """ONE NEEDS_INTENT drift holds the WHOLE document.

    This is the epic's correctness condition, not a refinement: `heal._corrected`
    skips a no-renderer region but still stamps the fingerprint, and that stamp is
    the ONLY staleness trigger such a region has. Routing per-drift would let doc
    B's mechanical HASH fix bless its sibling prose region into PERMANENT
    staleness with `cdx check` green forever — the exact inversion of "nothing is
    missed".
    """
    report = DriftReport(
        drifts=(
            _d("A", DriftKind.HASH, ApplyTier.CODE_DERIVED),
            _d("A", DriftKind.REGION, ApplyTier.CODE_DERIVED),
            _d("B", DriftKind.HASH, ApplyTier.CODE_DERIVED),
            _d("B", DriftKind.REGION, ApplyTier.NEEDS_INTENT),
        )
    )
    assert auto_routable_docs(report) == frozenset({"A"})


def test_auto_routable_docs_ignores_suspect_links() -> None:
    """A SUSPECT_LINK must not veto its document.

    `monitor.run` `continue`s past suspect links and handles them in a pass that
    never calls `apply_fix`, so they can neither be applied nor blessed.
    """
    report = DriftReport(
        drifts=(
            _d("A", DriftKind.HASH, ApplyTier.CODE_DERIVED),
            _d("A", DriftKind.SUSPECT_LINK, ApplyTier.NEEDS_INTENT),
        )
    )
    assert auto_routable_docs(report) == frozenset({"A"})


def test_auto_routable_docs_delegated_counts_as_auto() -> None:
    """DELEGATED routes AUTO for the per-document fold (RTE-04 gates the write)."""
    report = DriftReport(drifts=(_d("A", DriftKind.REGION, ApplyTier.DELEGATED),))
    assert auto_routable_docs(report) == frozenset({"A"})


def test_auto_routable_docs_empty_report_is_empty() -> None:
    assert auto_routable_docs(DriftReport(drifts=())) == frozenset()


def test_summary_reports_the_routing_tally_additively() -> None:
    """The routing line is ADDITIVE — every existing substring still holds (K9)."""
    report = DriftReport(
        drifts=(
            _d("A", DriftKind.HASH, ApplyTier.CODE_DERIVED),
            _d("B", DriftKind.REGION, ApplyTier.NEEDS_INTENT),
        )
    )
    out = report.summary()
    assert "2 drift(s) detected:" in out  # the pre-RTE-01 header is untouched
    assert "A: HASH" in out and "B: REGION" in out
    assert "routing:" in out
    assert "1" in out.split("routing:")[1]


def test_detect_never_leaves_a_drift_on_the_deny_default(tmp_path: Path) -> None:
    """Every Drift `detect` emits carries REAL routing evidence.

    The deny default makes a forgotten construction point fail SAFE, but silently —
    such a drift would escalate to a human forever with no reason attached. Empty
    `tier_evidence` is therefore the signature of an unclassified construction
    point, and this is the guard that catches one being added later.
    """
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)

    # (a) no doc on disk yet -> MISSING_DOC.
    report = detect(_config(root, (spec,)), tmp_path)
    (missing,) = report.drifts
    assert missing.apply_tier is ApplyTier.NEEDS_INTENT
    assert missing.tier_evidence == ("no-document-yet",)

    # (b) sync + move the code -> HASH and a renderer-backed REGION together.
    (root / spec.path).write_text(
        _synced_anchored(spec, root, include_body=True), encoding="utf-8"
    )
    _write_code(root, CODE_PLUS_SYMBOL)
    report = detect(_config_on(root, (spec,)), tmp_path)
    assert report.drifts, "expected drift after the code moved"
    for d in report.drifts:
        assert d.tier_evidence != (), f"unclassified construction point: {d.kind}"


def test_legacy_doc_without_stamped_tiers_is_never_auto_routable(
    tmp_path: Path,
) -> None:
    """A doc carrying only a composite fingerprint can never close itself.

    `ChangeSeverity.UNKNOWN` is OVERLOADED — it means both "not a HASH drift, the
    question does not apply" AND "this IS a HASH drift but the doc predates the
    per-tier digests, so there is nothing to diff against". The router cannot tell
    those apart, so rule 10 denies it: an un-attributable surface move is exactly
    the case where auto-applying could bless a falsified sentence.
    """
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    # `_synced_doc_text` stamps the COMPOSITE only — a pre-P2/P4 shaped doc.
    (root / spec.path).write_text(_synced_doc_text(spec, root), encoding="utf-8")
    _write_code(root, CODE_PLUS_SYMBOL)

    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.change_severity is ChangeSeverity.UNKNOWN
    assert drift.apply_tier is ApplyTier.NEEDS_INTENT
    assert drift.tier_evidence == ("severity:unknown",)
    assert auto_routable_docs(detect(_config(root, (spec,)), tmp_path)) == frozenset()


def test_additive_change_on_a_stamped_doc_is_fully_auto_routable(
    tmp_path: Path,
) -> None:
    """The happy path end to end: an ADDED symbol needs no human.

    Nothing was removed and no survivor's signature moved, so no existing sentence
    can have been falsified — the doc is now merely INCOMPLETE, and a refreshed
    symbol table is strictly better than a stale one. Both drifts it raises (the
    HASH refresh and the renderer-backed table) are pure projections of the
    surface, so the WHOLE document routes AUTO.
    """
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        _synced_anchored(spec, root, include_body=True), encoding="utf-8"
    )
    _write_code(root, CODE_PLUS_SYMBOL)

    report = detect(_config_on(root, (spec,)), tmp_path)
    hash_drift = _hash_drift(report)
    assert hash_drift.change_severity is ChangeSeverity.ADDITIVE
    assert hash_drift.apply_tier is ApplyTier.CODE_DERIVED
    assert hash_drift.tier_evidence == ("severity:additive", "surface-refresh")

    region = [d for d in report.drifts if d.kind is DriftKind.REGION]
    assert region and all(d.apply_tier is ApplyTier.CODE_DERIVED for d in region)
    assert all("mechanical-render" in d.tier_evidence for d in region)

    assert auto_routable_docs(report) == frozenset({"eng-guide"})


# ---------------------------------------------------------------------------#
# RTE-03b — the fold PRIMITIVES and the three-way routing tally.              #
# Feature: FEAT-DRIFT-014                                                    #
#                                                                            #
# RTE-01 answered "could this close itself?"; RTE-03 must answer "could the   #
# ENGINE close it, with no model at all?" — a strictly narrower question, and #
# the one that decides whether an unattended write is allowed.                #
# ---------------------------------------------------------------------------#


def test_auto_tiers_is_derived_from_is_auto_never_duplicated() -> None:
    """`AUTO_TIERS` is computed from `is_auto` — one fact, one definition (K10).

    A hand-written literal would be a SECOND encoding of the route, free to drift
    from the property that actually drives the fold.
    """
    assert frozenset(t for t in ApplyTier if t.is_auto) == AUTO_TIERS
    assert ApplyTier.NEEDS_INTENT not in AUTO_TIERS


def test_docs_closable_by_folds_per_document_over_the_given_tiers() -> None:
    """The fold generalises: a doc qualifies iff EVERY actionable drift is in tiers."""
    report = DriftReport(
        drifts=(
            _d("A", DriftKind.HASH, ApplyTier.CODE_DERIVED),
            _d("A", DriftKind.REGION, ApplyTier.CODE_DERIVED),
            _d("B", DriftKind.HASH, ApplyTier.CODE_DERIVED),
            _d("B", DriftKind.REGION, ApplyTier.DELEGATED),
        )
    )
    assert docs_closable_by(report, {ApplyTier.CODE_DERIVED}) == frozenset({"A"})
    assert docs_closable_by(
        report, {ApplyTier.CODE_DERIVED, ApplyTier.DELEGATED}
    ) == frozenset({"A", "B"})
    assert docs_closable_by(report, {ApplyTier.DELEGATED}) == frozenset()


def test_auto_routable_docs_output_is_unchanged_by_the_generalisation() -> None:
    """The RTE-01 contract survives verbatim — including its VACUOUS member.

    A doc whose only drift is a suspect link is auto-routable by vacuous truth
    (nothing blocks). RTE-01 documented that as harmless because nothing on it
    ever reaches the apply gate; this pins that RTE-03b did not "fix" it.
    """
    report = DriftReport(
        drifts=(
            _d("A", DriftKind.HASH, ApplyTier.CODE_DERIVED),
            _d("links-only", DriftKind.SUSPECT_LINK, ApplyTier.NEEDS_INTENT),
        )
    )
    assert auto_routable_docs(report) == frozenset({"A", "links-only"})
    assert auto_routable_docs(report) == docs_closable_by(report, AUTO_TIERS)


def test_mechanical_docs_requires_a_qualifying_actionable_drift() -> None:
    """A suspect-link-only doc is NOT mechanically closable — the phantom-closure bug.

    Vacuous membership is harmless for ROUTING (nothing reaches the apply gate) and
    dangerous for CLOSING: RTE-03d turns this set into the closure set, and a
    phantom `ClosureRecord(verified=True)` would print a GREEN line for a document
    whose suspect link is still open and was just ESCALATE'd.
    """
    report = DriftReport(
        drifts=(_d("links-only", DriftKind.SUSPECT_LINK, ApplyTier.NEEDS_INTENT),)
    )
    assert auto_routable_docs(report) == frozenset({"links-only"})  # unchanged
    assert mechanical_docs(report) == frozenset()  # but nothing to close


def test_mechanical_docs_is_strictly_narrower_than_auto_routable() -> None:
    """DELEGATED is auto-routable but is MODEL-authored prose — RTE-04, not RTE-03."""
    report = DriftReport(
        drifts=(
            _d("mech", DriftKind.HASH, ApplyTier.CODE_DERIVED),
            _d("prose", DriftKind.REGION, ApplyTier.DELEGATED),
        )
    )
    assert auto_routable_docs(report) == frozenset({"mech", "prose"})
    assert mechanical_docs(report) == frozenset({"mech"})


def test_mechanical_docs_still_ignores_a_suspect_link_beside_real_drift() -> None:
    """A doc↔doc edge must not veto a document that IS mechanically closable."""
    report = DriftReport(
        drifts=(
            _d("A", DriftKind.HASH, ApplyTier.CODE_DERIVED),
            _d("A", DriftKind.SUSPECT_LINK, ApplyTier.NEEDS_INTENT),
        )
    )
    assert mechanical_docs(report) == frozenset({"A"})


def test_summary_reports_the_three_way_routing_tally() -> None:
    """`cdx check` answers "how much of this would `--tiered` close?" in one line.

    Every bucket count is DISTINCT on purpose (2 / 1 / 3). Equal counts make a
    swapped pair of labels an unkillable mutant — the same gap that let "sort the
    decorators" survive RTE-02a's first mutation pass because every fixture symbol
    carried exactly one decorator.
    """
    report = DriftReport(
        drifts=(
            _d("mech", DriftKind.HASH, ApplyTier.CODE_DERIVED),
            _d("mech2", DriftKind.REGION, ApplyTier.CODE_DERIVED),
            _d("prose", DriftKind.REGION, ApplyTier.DELEGATED),
            _d("held", DriftKind.REGION, ApplyTier.NEEDS_INTENT),
            _d("held2", DriftKind.MISSING_DOC, ApplyTier.NEEDS_INTENT),
            _d("held3", DriftKind.UNHEALABLE, ApplyTier.NEEDS_INTENT),
        )
    )
    line = [ln for ln in report.summary().splitlines() if ln.startswith("routing:")]
    assert line == [
        "routing: 2/6 document(s) mechanical, 1 delegated, 3 need human intent"
    ]


def test_summary_tally_partitions_the_ACTIONABLE_documents() -> None:
    """The three buckets partition the docs that have something to close.

    A doc whose only drift is a suspect link is excluded from the denominator
    entirely — it has nothing to close, so counting it in any bucket would mislabel
    it (as `mechanical` it is the phantom closure; as `delegated` or `held` it
    invents work that does not exist).
    """
    report = DriftReport(
        drifts=(
            _d("mech", DriftKind.HASH, ApplyTier.CODE_DERIVED),
            _d("prose", DriftKind.REGION, ApplyTier.DELEGATED),
            _d("held", DriftKind.REGION, ApplyTier.NEEDS_INTENT),
            _d("links-only", DriftKind.SUSPECT_LINK, ApplyTier.NEEDS_INTENT),
        )
    )
    line = next(ln for ln in report.summary().splitlines() if ln.startswith("routing:"))
    assert "1/3 document(s) mechanical, 1 delegated, 1 need human intent" in line
    assert "links-only" not in line


# --------------------------------------------------------------------------- #
# Anchor collisions (review finding jarvis-contribution-key-identity, slice 1a). #
#                                                                               #
# `anchor_id` hashes the qualified name ONLY, so two documented symbols can      #
# share an anchor: `main` in two code_refs, an `@overload` stack, a property     #
# getter/setter. The stored `region_anchors` keep the duplicates, but DIG-01's   #
# `symbol_sigs` is a dict keyed by anchor — the LAST writer wins — so a change   #
# to an earlier collider is invisible to `sigs_changed`. Worse, the anchor delta #
# was a SET, so deleting one of two same-name symbols looked like "no removal".  #
# Either way an in-place break plus any addition in the same edit graded         #
# ADDITIVE -> CODE_DERIVED, and `monitor --apply --tiered` closed it with no     #
# review. Slice 1a: multiset deltas + never ADDITIVE while a repeating anchor    #
# could be hiding the signature move. No fingerprint changes (1b re-baselines). #
# --------------------------------------------------------------------------- #

COLLIDE_A_V1 = "def main(x: int) -> int:\n    return x\n"
# b.main sits BELOW a.main by line number, so it is the LAST writer of the shared
# `symbol_sigs[anchor_id("main")]` entry — a.main's digest is overwritten.
COLLIDE_B_V1 = (
    "# pad\n# pad\n# pad\ndef main(y: str, z: str) -> str:\n    return y + z\n"
)
_EXTRA = "\n\ndef extra() -> None:\n    pass\n"


def _collide_setup(
    tmp_path: Path,
    a_src: str,
    b_src: str,
    audience: Audience = Audience.USER_GUIDE,
    *,
    include_body: bool = False,
    extra_srcs: tuple[str, ...] = (),
    rows_json: str | None = None,
) -> tuple[Path, DocumentSpec]:
    """Code_refs that each define `main`, healed by the REAL heal (ship shape).

    `regenerate_regions` stamps exactly what production stamps — the composite,
    the per-tier digests, the duplicate-keeping `region_anchors` and the
    last-writer `symbol_sigs` — so the fixture cannot drift from the shape a real
    adopter's doc has. ``include_body`` heals with the opt-in body tier (check it
    with :func:`_config_on`); ``extra_srcs`` become ``src/c.py``, ``src/d.py``, …
    code_refs AFTER a/b, in that order. ``rows_json`` becomes ``src/rows.json``,
    a JSON ``records`` ref (list key ``items``) whose rows fold into the
    signature tier.
    """
    root = _setup(tmp_path)
    (root / "src" / "a.py").write_text(a_src, encoding="utf-8")
    (root / "src" / "b.py").write_text(b_src, encoding="utf-8")
    refs = [CodeRef(path="src/a.py"), CodeRef(path="src/b.py")]
    for i, src in enumerate(extra_srcs):
        rel = f"src/{chr(ord('c') + i)}.py"
        (root / rel).write_text(src, encoding="utf-8")
        refs.append(CodeRef(path=rel))
    if rows_json is not None:
        (root / "src" / "rows.json").write_text(rows_json, encoding="utf-8")
        refs.append(
            CodeRef(path="src/rows.json", extract="records", json_records="items")
        )
    spec = DocumentSpec(
        id="api",
        path="docs/api.md",
        audience=audience,
        code_refs=tuple(refs),
        region_keys=("symbols",),
    )
    (root / spec.path).write_text(
        "# API\n\nCall `main(x)` with one int.\n\n"
        "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    regenerate_regions(
        root / spec.path, build_document_surface(spec, root), include_body=include_body
    )
    config = (_config_on if include_body else _config)(root, (spec,))
    assert detect(config, tmp_path).ok, "fixture must start healed"
    return root, spec


def test_collided_earlier_symbol_signature_change_plus_addition_is_breaking(
    tmp_path: Path,
) -> None:
    """rc_mask: a break under a shadowed anchor is never graded ADDITIVE.

    a.main gains a required parameter and `extra` is added in the same edit.
    a.main's digest was overwritten by b.main's in `symbol_sigs`, so
    `sigs_changed` is empty and the addition used to win: ADDITIVE ->
    CODE_DERIVED, closed unattended while the prose "Call `main(x)` with one int"
    is now false. The collided anchor must hold the document for a human.
    """
    # Feature: FEAT-DRIFT-012
    root, spec = _collide_setup(tmp_path, COLLIDE_A_V1, COLLIDE_B_V1)
    (root / "src" / "a.py").write_text(
        "def main(x: int, strict: bool) -> int:\n    return x\n" + _EXTRA,
        encoding="utf-8",
    )
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.apply_tier is ApplyTier.NEEDS_INTENT
    assert mechanical_docs(report) == frozenset()
    # The per-symbol digest genuinely cannot see it (last writer b.main unchanged)…
    assert drift.sigs_changed == ()
    assert drift.anchors_added == (anchor_id("extra"),)
    # …so the verdict names the anchor that COULD hide it, and says what failed:
    # the proof, not a culprit (the detail is copied into the ReviewRecord, K5).
    assert drift.sigs_ambiguous == (anchor_id("main"),)
    assert (
        "(unproven: the additions alone do not reproduce the stored signature "
        "tier; 1 same-name anchor(s) could hide a change)"
    ) in drift.detail
    assert "[breaking]" in report.summary()


def test_removing_one_of_two_same_name_symbols_is_a_removal(tmp_path: Path) -> None:
    """rc_rm: the anchor delta is a MULTISET, so a shadowed deletion is counted.

    Deleting a.main while b.main survives left the anchor SET unchanged, so the
    removal vanished and a same-edit addition graded ADDITIVE. Counted as a
    multiset (the stamped `region_anchors` already keep duplicates) it is one
    removal of `main` — BREAKING by rule 1.
    """
    # Feature: FEAT-DRIFT-006
    root, spec = _collide_setup(tmp_path, COLLIDE_A_V1, COLLIDE_B_V1)
    (root / "src" / "a.py").write_text(_EXTRA.lstrip("\n"), encoding="utf-8")
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.anchors_removed == (anchor_id("main"),)
    assert drift.anchors_added == (anchor_id("extra"),)
    assert drift.apply_tier is ApplyTier.NEEDS_INTENT
    assert "+1/-1" in drift.detail
    # The removal is the sharper evidence and the detail claims no failed proof.
    # (No collision survives this removal, so these two lines cannot tell "guard
    # not consulted" from "consulted, found nothing"; the overload-of-three
    # removal below, where `f` still repeats, can.)
    assert drift.sigs_ambiguous == ()
    assert "unproven" not in drift.detail


def test_overload_stack_signature_change_plus_addition_is_breaking(
    tmp_path: Path,
) -> None:
    """ov_v: one file, an `@overload` stack — three symbols, one anchor.

    The FIRST overload changes `int -> int` to `float -> float` and `g` is added.
    The implementation (the last writer) is unchanged, so the digest map saw
    nothing and the edit graded ADDITIVE. It must be BREAKING.
    """
    # Feature: FEAT-DRIFT-012
    root = _setup(tmp_path)
    head = "from typing import overload\n\n\n@overload\n"
    tail = "@overload\ndef f(x: str) -> str: ...\ndef f(x):\n    return x\n"
    _write_code(root, head + "def f(x: int) -> int: ...\n" + tail)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        "# Mod\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    regenerate_regions(root / spec.path, build_document_surface(spec, root))
    _write_code(root, head + "def f(x: float) -> float: ...\n" + tail + _EXTRA)
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.sigs_ambiguous == (anchor_id("f"),)
    assert drift.apply_tier is ApplyTier.NEEDS_INTENT


def test_property_getter_change_plus_addition_is_breaking(tmp_path: Path) -> None:
    """rc_prop: a property getter and setter are both `C.x` — one anchor.

    The setter is the last writer, so a getter return-type change is invisible to
    the digest map; with a method added in the same edit it must still be held.
    """
    # Feature: FEAT-DRIFT-012
    root = _setup(tmp_path)
    getter = "class C:\n    @property\n    def x(self) -> {ret}:\n        return 1\n\n"
    setter = "    @x.setter\n    def x(self, v: int) -> None:\n        pass\n"
    _write_code(root, getter.format(ret="int") + setter)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        "# Mod\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    regenerate_regions(root / spec.path, build_document_surface(spec, root))
    added = "\n    def y(self) -> None:\n        pass\n"
    _write_code(root, getter.format(ret="str") + setter + added)
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.sigs_ambiguous == (anchor_id("C.x"),)


def test_later_collider_change_plus_addition_stays_breaking(tmp_path: Path) -> None:
    """rc_ctrlA (control): the LAST writer's change was already caught by DIG-01.

    b.main is the last writer, so its in-place change is a real `sigs_changed`
    entry and rule 2 fires before the collision guard is ever consulted — the
    guard adds nothing here and must not disturb the existing evidence.
    """
    # Feature: FEAT-DRIFT-012
    root, spec = _collide_setup(tmp_path, COLLIDE_A_V1, COLLIDE_B_V1)
    (root / "src" / "b.py").write_text(
        "# pad\n# pad\n# pad\ndef main(y: str, z: str, w: int) -> str:\n"
        "    return y + z\n" + _EXTRA,
        encoding="utf-8",
    )
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.sigs_changed == (anchor_id("main"),)
    assert drift.sigs_ambiguous == ()


def test_pure_addition_beside_a_collision_stays_additive(tmp_path: Path) -> None:
    """Control: a collision alone must NOT over-fire on a genuine addition.

    Nothing under `main` moved; only `extra` was appended (below every existing
    symbol, so no same-name tie reorders). With the added symbol set aside, the
    signature tier reproduces the stored one byte-for-byte — so no repeating
    anchor can be hiding a change, and the refresh stays mechanical. The proof
    SUCCEEDED, so the detail (copied into the ReviewRecord, K5) must not say it
    failed: no "unproven … could hide a change" suffix.
    """
    # Feature: FEAT-DRIFT-012
    root, spec = _collide_setup(tmp_path, COLLIDE_A_V1, COLLIDE_B_V1)
    (root / "src" / "b.py").write_text(COLLIDE_B_V1 + _EXTRA, encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.change_severity is ChangeSeverity.ADDITIVE
    assert drift.apply_tier is ApplyTier.CODE_DERIVED
    assert drift.anchors_added == (anchor_id("extra"),)
    assert drift.anchors_removed == ()
    assert drift.sigs_ambiguous == ()
    assert mechanical_docs(report) == frozenset({"api"})
    assert "(anchored symbols changed: +1/-0)" in drift.detail
    assert "unproven" not in drift.detail
    assert "could hide" not in drift.detail


def test_adding_another_same_name_symbol_is_counted_and_held(tmp_path: Path) -> None:
    """A GROWN collision is an addition the engine cannot attribute: held.

    b.py gains a second `main` ABOVE a.main (so a.main stays the last writer and
    the digest map sees no change) alongside `extra`. The multiset delta reports
    BOTH additions — `main` too, which the set delta dropped — but WHICH `main`
    is the new one cannot be told from name-keyed stamps, so the guard cannot
    prove nothing moved under it and denies (deny by default, RTE-01).
    """
    # Feature: FEAT-DRIFT-006
    a_src = "# pad\n" * 8 + COLLIDE_A_V1
    root, spec = _collide_setup(tmp_path, a_src, "def other() -> None:\n    pass\n")
    (root / "src" / "b.py").write_text(
        "def main(q: bytes) -> bytes:\n    return q\n\n\n"
        "def other() -> None:\n    pass\n" + _EXTRA,
        encoding="utf-8",
    )
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.anchors_added == tuple(sorted((anchor_id("extra"), anchor_id("main"))))
    assert drift.sigs_changed == ()
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.sigs_ambiguous == (anchor_id("main"),)


def test_collision_on_a_doc_without_stored_tiers_is_denied(tmp_path: Path) -> None:
    """No stored signature tier -> nothing can PROVE the move innocent -> deny.

    A doc carrying anchors + digests but no `fingerprint_tiers` (hand-stamped;
    heal always writes both) gives the guard nothing to reconstruct against, so
    a would-be ADDITIVE with a repeating anchor is held rather than trusted.
    """
    # Feature: FEAT-DRIFT-012
    root, spec = _collide_setup(tmp_path, COLLIDE_A_V1, COLLIDE_B_V1)
    doc_path = root / spec.path
    text = doc_path.read_text(encoding="utf-8")
    start = text.index("  fingerprint_tiers:")
    end = text.index("  region_anchors:")
    doc_path.write_text(text[:start] + text[end:], encoding="utf-8")
    (root / "src" / "b.py").write_text(COLLIDE_B_V1 + _EXTRA, encoding="utf-8")
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.drifted_tiers == ()
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.sigs_ambiguous == (anchor_id("main"),)
    # No proof ran, so the detail must not claim one failed.
    assert (
        "(unproven: no stored signature tier to check the additions against; "
        "1 same-name anchor(s) could hide a change)"
    ) in drift.detail
    assert "do not reproduce" not in drift.detail


def test_collided_inplace_change_without_addition_keeps_rule_4(
    tmp_path: Path,
) -> None:
    """va0: with no addition the guard is never consulted — rule 4 already holds.

    The shadowed a.main changes in place and nothing is added, so there is no
    ADDITIVE verdict to guard: the moved signature tier with no attributable
    delta is BREAKING by the pre-existing fallback, and `sigs_ambiguous` stays
    empty (the guard re-labels nothing it does not need to).
    """
    # Feature: FEAT-DRIFT-012
    root, spec = _collide_setup(tmp_path, COLLIDE_A_V1, COLLIDE_B_V1)
    (root / "src" / "a.py").write_text(
        "def main(x: int, strict: bool) -> int:\n    return x\n", encoding="utf-8"
    )
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.anchors_added == () and drift.anchors_removed == ()
    assert drift.sigs_changed == ()
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.sigs_ambiguous == ()


def test_guard_is_silent_when_the_signature_tier_did_not_move(
    tmp_path: Path,
) -> None:
    """No signature moved anywhere ⇒ nothing can hide under a repeating anchor.

    Reachable when the `symbols` anchor stamp is OLDER than the fingerprint (heal
    re-stamps anchors only when it authors the region): the stale stamp lacks
    `extra`, so a docstring-only edit reports it as added. The signature tier is
    byte-identical, so the guard must not fire — the verdict is exactly what it
    was before the guard existed.
    """
    # Feature: FEAT-DRIFT-012
    a_src = 'def main(x: int) -> int:\n    """One."""\n    return x\n' + _EXTRA
    root, spec = _collide_setup(tmp_path, a_src, COLLIDE_B_V1, Audience.ENG_GUIDE)
    doc_path = root / spec.path
    text = doc_path.read_text(encoding="utf-8")
    stale = f"    - {anchor_id('extra')}\n"
    assert text.count(stale) == 1
    doc_path.write_text(text.replace(stale, ""), encoding="utf-8")
    (root / "src" / "a.py").write_text(
        a_src.replace('"""One."""', '"""One, reworded."""'), encoding="utf-8"
    )
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.drifted_tiers == ("docstring",)
    assert drift.anchors_added == (anchor_id("extra"),)
    assert drift.sigs_ambiguous == ()
    assert drift.change_severity is ChangeSeverity.ADDITIVE


def test_removing_one_overload_of_three_is_a_removal_not_an_ambiguity(
    tmp_path: Path,
) -> None:
    """A multiset removal is reported AS a removal, even while `f` still repeats.

    One of three `@overload`-stacked `f`s is deleted and `g` is added. As a set,
    `f` was still present — "no removal" — and the addition graded ADDITIVE. As a
    multiset it is one removal of `f` (rule 1). Two `f`s still share the anchor
    afterwards, but the sharper removal evidence stands: the collision guard is
    not consulted, `sigs_ambiguous` stays empty, and the detail — copied into
    the ReviewRecord (K5) — claims no failed proof. Because `f` still repeats
    and the addition alone cannot reproduce the stored tier, a guard consulted
    here WOULD deny, so this row (unlike a removal that leaves no collision)
    catches the field and the "unproven" wording being decoupled.
    """
    # Feature: FEAT-DRIFT-006
    root = _setup(tmp_path)
    head = "from typing import overload\n\n\n"
    over = "@overload\ndef f(x: {t}) -> {t}: ...\n"
    impl = "def f(x):\n    return x\n"
    _write_code(root, head + over.format(t="int") + over.format(t="str") + impl)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        "# Mod\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    regenerate_regions(root / spec.path, build_document_surface(spec, root))
    _write_code(root, head + over.format(t="str") + impl + _EXTRA)
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.anchors_removed == (anchor_id("f"),)
    assert drift.anchors_added == (anchor_id("extra"),)
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.sigs_ambiguous == ()
    assert "unproven" not in drift.detail
    assert "could hide" not in drift.detail


@pytest.mark.parametrize(
    ("b_src", "added", "severity"),
    [
        pytest.param(
            COLLIDE_B_V1 + _EXTRA,
            (anchor_id("extra"),),
            ChangeSeverity.ADDITIVE,
            id="pure-addition",
        ),
        # b.main (the last writer) gains a parameter: a real, attributed
        # in-place change and no addition, so the moved signature tier proves
        # nothing about the stamp.
        pytest.param(
            "# pad\n# pad\n# pad\ndef main(y: str, z: str, w: int) -> str:\n"
            "    return y + z\n",
            (),
            ChangeSeverity.BREAKING,
            id="in-place-signature-change",
        ),
    ],
)
def test_a_region_key_declared_twice_never_double_counts_its_stamp(
    tmp_path: Path, b_src: str, added: tuple[str, ...], severity: ChangeSeverity
) -> None:
    """The stamp merge is a multiset UNION (max), so re-reading it is harmless.

    `region_keys` accepts a key listed twice, and each listed anchored key reads
    its stamp. A SUM would double every stored count and turn every documented
    symbol into a count-only decrease, i.e. a phantom removal. On the pure
    addition the stale-stamp discharge would hide that (the stored tier proves
    the doubled counts wrong), so the in-place-change row carries the pin: its
    signature tier moved for a real reason, nothing is discharged, and only
    the max-merge keeps ``anchors_removed`` empty (the break is attributed by
    ``sigs_changed``, not by a phantom "-2").
    """
    # Feature: FEAT-DRIFT-006
    root, spec = _collide_setup(tmp_path, COLLIDE_A_V1, COLLIDE_B_V1)
    spec = spec.model_copy(update={"region_keys": ("symbols", "symbols")})
    (root / "src" / "b.py").write_text(b_src, encoding="utf-8")
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.anchors_removed == ()
    assert drift.anchors_added == added
    assert drift.change_severity is severity


def test_classify_change_severity_ambiguous_anchor_outranks_addition() -> None:
    """The truth-table row: an ambiguous anchor sits between rules 2 and 3.

    Below removals and attributed signature changes (those already say BREAKING
    with sharper evidence), ABOVE the addition rule it exists to guard.
    """
    # Feature: FEAT-DRIFT-012
    C = ChangeSeverity
    sig = ("signature",)
    assert classify_change_severity(sig, ("new",), (), (), ("dup",)) is C.BREAKING
    assert classify_change_severity(sig, ("new",), (), ()) is C.ADDITIVE
    assert classify_change_severity(sig, ("new",), (), (), ()) is C.ADDITIVE
    assert classify_change_severity(sig, (), (), (), ("dup",)) is C.BREAKING
    # Rule 2b is UNCONDITIONAL for the public pure function: with no signature
    # tier (the row above is already BREAKING by rule 4, so it proves nothing),
    # no tier at all (else UNKNOWN) and a docstring-only move (else COSMETIC).
    assert classify_change_severity((), (), (), (), ("dup",)) is C.BREAKING
    assert classify_change_severity(("docstring",), (), (), (), ("dup",)) is (
        C.BREAKING
    )


def test_docstring_reword_plus_addition_beside_a_collision_stays_additive(
    tmp_path: Path,
) -> None:
    """The proof re-derives the SIGNATURE tier only, never the composite.

    On an eng-guide the composite also folds in docstrings, so a pure addition
    made in the same edit as a docstring reword moves the composite even with the
    added symbol set aside. The signature tier is what the per-anchor digests
    cannot attribute; the docstring tier cannot hide a signature change. Proving
    against the composite would hold every addition that travels with a
    docstring edit — this stays ADDITIVE / CODE_DERIVED.
    """
    # Feature: FEAT-DRIFT-012
    a_src = 'def main(x: int) -> int:\n    """One."""\n    return x\n'
    root, spec = _collide_setup(tmp_path, a_src, COLLIDE_B_V1, Audience.ENG_GUIDE)
    (root / "src" / "a.py").write_text(
        a_src.replace('"""One."""', '"""One, reworded."""') + _EXTRA,
        encoding="utf-8",
    )
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.drifted_tiers == ("docstring", "signature")
    assert drift.anchors_added == (anchor_id("extra"),)
    assert drift.sigs_changed == ()
    assert drift.sigs_ambiguous == ()
    assert drift.change_severity is ChangeSeverity.ADDITIVE
    assert drift.apply_tier is ApplyTier.CODE_DERIVED


def test_body_edit_plus_addition_beside_a_collision_stays_additive(
    tmp_path: Path,
) -> None:
    """With the opt-in body tier on, a body edit cannot hide a signature change.

    Same contract as the docstring case, for ``fingerprint_body_tier``: the
    shadowed a.main's BODY changes and ``extra`` is added. Only the signature
    tier is proven; the body tier (and the composite that folds it in) is not the
    subject, so the refresh stays mechanical.
    """
    # Feature: FEAT-DRIFT-012
    root, spec = _collide_setup(
        tmp_path, COLLIDE_A_V1, COLLIDE_B_V1, Audience.ENG_GUIDE, include_body=True
    )
    (root / "src" / "a.py").write_text(
        COLLIDE_A_V1.replace("return x", "return x + 1") + _EXTRA, encoding="utf-8"
    )
    drift = _hash_drift(detect(_config_on(root, (spec,)), tmp_path))
    # `extra` adds a docstring-tier item too; the body tier moved on its own.
    assert drift.drifted_tiers == ("body", "docstring", "signature")
    assert drift.sigs_ambiguous == ()
    assert drift.change_severity is ChangeSeverity.ADDITIVE
    assert drift.apply_tier is ApplyTier.CODE_DERIVED


def test_two_repeating_anchors_are_reported_in_sorted_anchor_order(
    tmp_path: Path,
) -> None:
    """``Drift.sigs_ambiguous`` is sorted by anchor_id (K10), not surface order.

    b.py carries an ``@overload`` stack of ``f`` AND the last-writer ``main``, so
    two anchors repeat. The surface is ordered by NAME (``f`` before ``main``)
    while the anchor ids order the other way (``main`` < ``f`` as hex), so an
    unsorted tuple would leak the surface order into the evidence.
    """
    # Feature: FEAT-DRIFT-012
    b_src = (
        "from typing import overload\n\n\n"
        "@overload\ndef f(x: int) -> int: ...\n"
        "@overload\ndef f(x: str) -> str: ...\n"
        "def f(x):\n    return x\n\n\n"
        "# pad\n# pad\n# pad\ndef main(y: str, z: str) -> str:\n    return y + z\n"
    )
    root, spec = _collide_setup(tmp_path, COLLIDE_A_V1, b_src)
    (root / "src" / "a.py").write_text(
        "def main(x: int, strict: bool) -> int:\n    return x\n" + _EXTRA,
        encoding="utf-8",
    )
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    expected = tuple(sorted((anchor_id("f"), anchor_id("main"))))
    assert expected != (anchor_id("f"), anchor_id("main")), "fixture must disagree"
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.sigs_ambiguous == expected
    # The count is of the repeating anchors, not of the additions (1 here).
    assert drift.anchors_added == (anchor_id("extra"),)
    assert "2 same-name anchor(s) could hide a change" in drift.detail


def test_an_unsorted_anchor_stamp_still_yields_sorted_removals(
    tmp_path: Path,
) -> None:
    """Removals are sorted by anchor_id even when the stored stamp is not (K10).

    Heal always stamps ``region_anchors`` sorted, but the reader accepts any
    order, so a hand-edited (or foreign-tool) stamp in reverse order must not
    leak its order into ``Drift.anchors_removed`` — the multiset difference
    iterates the stamp in insertion order.
    """
    # Feature: FEAT-DRIFT-006
    root = _setup(tmp_path)
    _write_code(
        root,
        "def alpha() -> None:\n    pass\n\n\n"
        "def beta() -> None:\n    pass\n\n\n"
        "def omega() -> None:\n    pass\n",
    )
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    doc_path = root / spec.path
    doc_path.write_text(
        "# Mod\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    regenerate_regions(doc_path, build_document_surface(spec, root))
    stamped = stored_region_anchors(parse_doc(doc_path), "symbols")
    assert stamped is not None and list(stamped) == sorted(stamped)
    text = doc_path.read_text(encoding="utf-8")
    block = "".join(f"    - {a}\n" for a in stamped)
    assert text.count(block) == 1
    doc_path.write_text(
        text.replace(block, "".join(f"    - {a}\n" for a in reversed(stamped))),
        encoding="utf-8",
    )
    _write_code(root, "def omega() -> None:\n    pass\n")
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.anchors_removed == tuple(
        sorted((anchor_id("alpha"), anchor_id("beta")))
    )


# Three `main`s: a.main and b.main both sit on line 1 (the stable sort keeps
# code_ref order, a before b) and c.main on line 21 is the LAST writer of the
# shared digest. Moving a.main down by any number of lines reorders it past
# b.main in the (name, lineno) tie, which the signature payload is order-
# sensitive to — while the digest map, which only sees c.main, sees nothing.
_TIE_A = "def main(x: int) -> int:\n    return x\n"
_TIE_B = "def main(y: str) -> str:\n    return y\n"
_TIE_C = "# pad\n" * 20 + "def main(z: bytes) -> bytes:\n    return z\n"


@pytest.mark.parametrize(
    ("a_before", "a_after", "held"),
    [
        pytest.param(
            _TIE_A, _TIE_A + _EXTRA, False, id="appended-below-every-collider"
        ),
        pytest.param(
            _TIE_A,
            _EXTRA.lstrip("\n") + "\n\n" + _TIE_A,
            True,
            id="inserted-above-a-collider",
        ),
        pytest.param(
            _TIE_A,
            "import os\n" + _TIE_A + _EXTRA,
            True,
            id="import-line-plus-appended",
        ),
        # The REMOVAL direction: a.main starts one line BELOW b.main (b, a, c);
        # deleting the unused import lifts it onto b.main's line, and the stable
        # tie puts it first again (a, b, c).
        pytest.param(
            "import os\n" + _TIE_A,
            _TIE_A + _EXTRA,
            True,
            id="import-line-removed-plus-appended",
        ),
    ],
)
def test_pure_addition_that_shifts_a_non_last_collider_is_held_until_slice_1b(
    tmp_path: Path, a_before: str, a_after: str, held: bool
) -> None:
    """KNOWN COST of slice 1a, pinned so slice 1b flips it DELIBERATELY.

    Nothing's signature changes in any case — ``extra`` is a pure addition. When
    it is appended below every collider the proof reproduces the stored
    signature tier and the refresh stays mechanical. But ANY edit that reorders
    the same-name tie while the LAST writer stays last — lines added OR removed
    above a collider move it past a non-last sibling (the function inserted at
    the top of a.py, a one-line import added above it, or an unused import
    deleted from above it) — cannot be reproduced from name-keyed stamps by the
    order-sensitive signature payload, and the addition is held as BREAKING /
    NEEDS_INTENT. That takes 3+ same-name symbols (hence c.main): a reorder that
    changes the last writer moves its DIG-01 digest and was already BREAKING by
    rule 2 (on a doc stamped without ``symbol_sigs`` it is newly held too).

    Measured at CKI-1a on this repo's dogfood (every .py code_ref of every
    colliding doc, DIG-01-stamped; flips vs the pre-fix engine): the insertion
    probe held 25 of the 344 edits that insert lines (387 rows with the 43
    appended ones, which held 0) — a LOWER BOUND, since it only inserts lines —
    and the removal probe (1-3 import lines removed plus an appended function)
    held 6 of 110.

    Slice 1b (a lineno-free tie key, a deliberate re-baseline) removes lineno
    from the order; when it lands the three held rows here must become ADDITIVE.
    """
    # Feature: FEAT-DRIFT-012
    root, spec = _collide_setup(tmp_path, a_before, _TIE_B, extra_srcs=(_TIE_C,))
    (root / "src" / "a.py").write_text(a_after, encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.anchors_added == (anchor_id("extra"),)
    assert drift.anchors_removed == ()
    assert drift.sigs_changed == (), "the last writer (c.main) never moved"
    if held:
        assert drift.change_severity is ChangeSeverity.BREAKING
        assert drift.apply_tier is ApplyTier.NEEDS_INTENT
        assert drift.sigs_ambiguous == (anchor_id("main"),)
        assert mechanical_docs(report) == frozenset()
    else:
        assert drift.change_severity is ChangeSeverity.ADDITIVE
        assert drift.apply_tier is ApplyTier.CODE_DERIVED
        assert drift.sigs_ambiguous == ()
        assert mechanical_docs(report) == frozenset({"api"})


# --- CKI-1a round 2: multi-occurrence counts, records in the proof, candidates -- #

_OVERLOAD_HEAD = "from typing import overload\n\n\n"
_G_STACK = (
    "\n\n@overload\ndef g(x: int) -> int: ...\n"
    "@overload\ndef g(x: str) -> str: ...\n"
    "def g(x):\n    return x\n"
)
_G_SINGLE = "\n\ndef g(x: int) -> int:\n    return x\n"
_BASE = _OVERLOAD_HEAD + "def base() -> None:\n    pass\n"


def _heal_mod(root: Path, src: str) -> DocumentSpec:
    """A one-module eng-guide over ``src/mod.py``, healed by the real heal."""
    _write_code(root, src)
    spec = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    (root / spec.path).write_text(
        "# Mod\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    regenerate_regions(root / spec.path, build_document_surface(spec, root))
    return spec


def _strip_stored_tiers(doc_path: Path) -> None:
    """Drop the stamped ``fingerprint_tiers`` block (heal always writes it)."""
    text = doc_path.read_text(encoding="utf-8")
    start = text.index("  fingerprint_tiers:")
    end = text.index("  region_anchors:")
    doc_path.write_text(text[:start] + text[end:], encoding="utf-8")


def test_a_new_overload_stack_counts_one_added_anchor_per_occurrence(
    tmp_path: Path,
) -> None:
    """An addition is counted once PER same-name symbol, not once per name.

    A new ``@overload`` stack ``g`` (two overloads + the implementation) is three
    documented symbols under one anchor. The multiset delta reports all three,
    and the ``+3/-0`` count reaches ``Drift.detail`` — and from there the
    ReviewRecord. A set delta would report ``+1``. Nothing is shadowed (``g`` is
    wholly new), so the pure addition stays ADDITIVE.
    """
    # Feature: FEAT-DRIFT-006
    root = _setup(tmp_path)
    spec = _heal_mod(root, _BASE)
    _write_code(root, _BASE + _G_STACK)
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.anchors_added == (anchor_id("g"),) * 3
    assert drift.anchors_removed == ()
    assert "(anchored symbols changed: +3/-0)" in drift.detail
    assert drift.sigs_ambiguous == ()
    assert drift.change_severity is ChangeSeverity.ADDITIVE


def test_deleting_two_overloads_counts_two_removals(tmp_path: Path) -> None:
    """A removal is counted once PER same-name symbol removed (rule 1).

    ``f`` is an ``@overload`` stack of two overloads plus the implementation;
    both overloads are deleted and the implementation kept. As a set nothing was
    removed (``f`` survives); as a multiset it is two removals of ``f``, shown as
    ``+0/-2`` — BREAKING, since the documented ``f(int)``/``f(str)`` are gone.
    """
    # Feature: FEAT-DRIFT-006
    root = _setup(tmp_path)
    over = "@overload\ndef f(x: {t}) -> {t}: ...\n"
    impl = "def f(x):\n    return x\n"
    spec = _heal_mod(
        root, _OVERLOAD_HEAD + over.format(t="int") + over.format(t="str") + impl
    )
    _write_code(root, _OVERLOAD_HEAD + impl)
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.anchors_removed == (anchor_id("f"),) * 2
    assert drift.anchors_added == ()
    assert "(anchored symbols changed: +0/-2)" in drift.detail
    assert drift.change_severity is ChangeSeverity.BREAKING


_ROWS_V1 = '{"items": [{"name": "port", "value": "80"}]}'
_ROWS_V2 = '{"items": [{"name": "port", "value": "8443"}]}'


def test_records_are_kept_in_the_signature_proof(tmp_path: Path) -> None:
    """The proof re-derives the WHOLE signature tier, records included.

    The signature tier hashes the signature-only symbols AND the ``records``
    rows. A collision doc that also carries a JSON records ref gets a pure
    addition (``extra`` appended below every collider, rows untouched): with
    the added symbol set aside, the re-derived tier must reproduce the stored one
    — which it can only do if the rows stay in the payload. Dropping them would
    hold every pure addition on any doc that has records.
    """
    # Feature: FEAT-DRIFT-012
    root, spec = _collide_setup(
        tmp_path, COLLIDE_A_V1, COLLIDE_B_V1, rows_json=_ROWS_V1
    )
    (root / "src" / "b.py").write_text(COLLIDE_B_V1 + _EXTRA, encoding="utf-8")
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.anchors_added == (anchor_id("extra"),)
    assert drift.sigs_ambiguous == ()
    assert drift.change_severity is ChangeSeverity.ADDITIVE
    assert drift.apply_tier is ApplyTier.CODE_DERIVED


def test_records_move_beside_a_collision_is_held_without_naming_a_culprit(
    tmp_path: Path,
) -> None:
    """The evidence describes the failed PROOF, not a guilty symbol.

    Neither ``main`` changes: the ``port`` row moves 80 -> 8443 (a records move,
    which folds into the signature tier) and ``extra`` is appended. The proof
    cannot reproduce the stored signature tier, so the verdict is still held
    (deny by default), and ``sigs_ambiguous`` still lists ``main`` as the anchor
    that COULD hide a change. But the detail — copied verbatim into the
    ReviewRecord a human reads (K5) — must not assert that the same-name symbol
    moved: it says the additions alone do not reproduce the stored tier, which
    is true whatever the real cause.
    """
    # Feature: FEAT-DRIFT-012
    root, spec = _collide_setup(
        tmp_path, COLLIDE_A_V1, COLLIDE_B_V1, rows_json=_ROWS_V1
    )
    (root / "src" / "rows.json").write_text(_ROWS_V2, encoding="utf-8")
    (root / "src" / "b.py").write_text(COLLIDE_B_V1 + _EXTRA, encoding="utf-8")
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.apply_tier is ApplyTier.NEEDS_INTENT
    assert drift.sigs_ambiguous == (anchor_id("main"),)
    assert (
        "(unproven: the additions alone do not reproduce the stored signature "
        "tier; 1 same-name anchor(s) could hide a change)"
    ) in drift.detail
    # No culprit is named: the candidate symbol appears nowhere in the detail.
    assert "main" not in drift.detail


def test_a_wholly_new_same_name_group_is_never_named_ambiguous(
    tmp_path: Path,
) -> None:
    """Only a STAMPED anchor can hide a change; a brand-new stack never can.

    The shadowed a.main gains a parameter (a real hidden break) and a new
    ``@overload`` stack ``g`` is appended in the same edit. ``g`` repeats, but
    none of its occurrences was stamped and the proof sets all of them aside, so
    it cannot be hiding anything — naming it would send the reviewer to an
    innocent symbol. The evidence is exactly the collided ``main``.
    """
    # Feature: FEAT-DRIFT-012
    a_src = _OVERLOAD_HEAD + COLLIDE_A_V1
    root, spec = _collide_setup(tmp_path, a_src, COLLIDE_B_V1)
    (root / "src" / "a.py").write_text(
        _OVERLOAD_HEAD
        + "def main(x: int, strict: bool) -> int:\n    return x\n"
        + _G_STACK,
        encoding="utf-8",
    )
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.anchors_added == (anchor_id("g"),) * 3
    assert drift.sigs_changed == ()
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.sigs_ambiguous == (anchor_id("main"),)
    assert "1 same-name anchor(s) could hide a change" in drift.detail


@pytest.mark.parametrize(
    "added",
    [pytest.param(_G_SINGLE, id="single-def"), pytest.param(_G_STACK, id="stack")],
)
def test_a_new_overload_stack_grades_like_a_single_new_def(
    tmp_path: Path, added: str
) -> None:
    """Whether a NEW name repeats must not change the verdict.

    On a collision-free doc stamped without ``fingerprint_tiers`` (so no proof
    can run), a pure addition of ``g`` is ADDITIVE / CODE_DERIVED as one def.
    Added as an ``@overload`` stack it is the same addition: no stamped anchor
    repeats, every survivor's DIG-01 digest is exact, and ``g`` has no stored
    occurrence to shadow — so the guard has nothing to deny. Nor may the detail
    of this mechanically closed drift (copied into its ReviewRecord, K5) claim a
    failed proof: "no stored signature tier" is only the reason a HELD drift
    could not be proven, never a caveat on one that needed no proof.
    """
    # Feature: FEAT-DRIFT-012
    root = _setup(tmp_path)
    spec = _heal_mod(root, _BASE)
    _strip_stored_tiers(root / spec.path)
    _write_code(root, _BASE + added)
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.drifted_tiers == ()
    assert drift.sigs_ambiguous == ()
    assert drift.change_severity is ChangeSeverity.ADDITIVE
    assert drift.apply_tier is ApplyTier.CODE_DERIVED
    assert mechanical_docs(report) == frozenset({"eng-guide"})
    assert "unproven" not in drift.detail
    assert "could hide" not in drift.detail


# --- CKI-1a round 4: pre-DIG-01 docs, proof-honest detail, stale anchor stamps -- #


def _strip_symbol_sigs(doc_path: Path) -> None:
    """Drop the stamped ``symbol_sigs`` block: the pre-DIG-01 front-matter shape.

    DIG-01 rolled out lazily, so an adopter doc keeps ``region_anchors`` and
    ``fingerprint_tiers`` but carries no per-symbol digests until its next heal.
    """
    text = doc_path.read_text(encoding="utf-8")
    start = text.index("  symbol_sigs:")
    end = text.index("---\n", start)
    doc_path.write_text(text[:start] + text[end:], encoding="utf-8")
    assert stored_symbol_sigs(parse_doc(doc_path)) is None


@pytest.mark.parametrize(
    "added",
    [pytest.param(_G_SINGLE, id="single-def"), pytest.param(_G_STACK, id="stack")],
)
def test_a_proven_addition_carries_no_unproven_suffix(
    tmp_path: Path, added: str
) -> None:
    """The "unproven … could hide a change" wording appears ONLY on a held drift.

    A collision-free doc stamped by the real heal gets a pure addition (``g``,
    as one def or as a new ``@overload`` stack). Nothing is held, so the detail
    — copied verbatim into the ReviewRecord of a mechanically closed drift
    (K5) — must not tell the reviewer that a proof failed or that "0 same-name
    anchor(s) could hide a change".
    """
    # Feature: FEAT-DRIFT-012
    root = _setup(tmp_path)
    spec = _heal_mod(root, _BASE)
    _write_code(root, _BASE + added)
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.change_severity is ChangeSeverity.ADDITIVE
    assert drift.apply_tier is ApplyTier.CODE_DERIVED
    assert drift.sigs_ambiguous == ()
    assert "(anchored symbols changed: +" in drift.detail
    assert "unproven" not in drift.detail
    assert "could hide" not in drift.detail


@pytest.mark.parametrize(
    ("a_after", "held"),
    [
        pytest.param(
            "def main(x: int, strict: bool) -> int:\n    return x\n" + _EXTRA,
            True,
            id="shadowed-break-plus-addition",
        ),
        pytest.param(COLLIDE_A_V1 + _EXTRA, False, id="appended-addition"),
    ],
)
def test_a_doc_stamped_without_symbol_sigs_still_holds_a_shadowed_break(
    tmp_path: Path, a_after: str, held: bool
) -> None:
    """The collision guard does not depend on DIG-01's per-symbol digests.

    A pre-DIG-01 doc (``region_anchors`` + ``fingerprint_tiers``, no
    ``symbol_sigs`` until its next heal) cannot attribute ANY in-place change,
    so ``sigs_changed`` is always empty there. The shadowed a.main gaining a
    required parameter plus ``extra`` must still be held BREAKING /
    NEEDS_INTENT: the proof re-derives the signature tier from the stored
    ``fingerprint_tiers``, which this doc has. Gating the guard on
    ``symbol_sigs`` being present would grade it ADDITIVE -> CODE_DERIVED and
    let ``monitor --apply --tiered`` close it unattended. Control: an appended
    pure addition on the same doc is proven and stays mechanical.
    """
    # Feature: FEAT-DRIFT-012
    root, spec = _collide_setup(tmp_path, COLLIDE_A_V1, COLLIDE_B_V1)
    _strip_symbol_sigs(root / spec.path)
    assert detect(_config(root, (spec,)), tmp_path).ok, "stripping keeps it healed"
    (root / "src" / "a.py").write_text(a_after, encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.anchors_added == (anchor_id("extra"),)
    assert drift.anchors_removed == ()
    assert drift.sigs_changed == ()
    if held:
        assert drift.sigs_ambiguous == (anchor_id("main"),)
        assert drift.change_severity is ChangeSeverity.BREAKING
        assert drift.apply_tier is ApplyTier.NEEDS_INTENT
        assert mechanical_docs(report) == frozenset()
        assert (
            "(unproven: the additions alone do not reproduce the stored signature "
            "tier; 1 same-name anchor(s) could hide a change)"
        ) in drift.detail
    else:
        assert drift.sigs_ambiguous == ()
        assert drift.change_severity is ChangeSeverity.ADDITIVE
        assert drift.apply_tier is ApplyTier.CODE_DERIVED
        assert mechanical_docs(report) == frozenset({"api"})
        assert "unproven" not in drift.detail


_OTHER = "def other() -> None:\n    pass\n"


@pytest.mark.parametrize(
    ("a_src", "b_src", "b_grown", "phantom", "stamped_mains"),
    [
        # No collision when first stamped (a.main + other); b.py then gains a
        # `main` ABOVE a.main, so the doc's stored tier holds two mains while
        # the stale stamp still holds one: the next addition reports a PHANTOM
        # grown collision.
        pytest.param(
            "# pad\n" * 8 + COLLIDE_A_V1,
            _OTHER,
            "def main(q: bytes) -> bytes:\n    return q\n\n\n" + _OTHER,
            "main",
            1,
            id="phantom-grown-collision",
        ),
        # Colliding from the start; b.py then gains a NEW name `g` that the
        # stale stamp never records: the next addition reports `g` as added
        # although the stored tier already holds it.
        pytest.param(
            COLLIDE_A_V1,
            COLLIDE_B_V1,
            COLLIDE_B_V1 + "\n\ndef g() -> None:\n    pass\n",
            "g",
            2,
            id="phantom-new-name",
        ),
    ],
)
def test_a_stale_anchor_stamp_on_a_preserved_symbols_region_holds_additions(
    tmp_path: Path,
    a_src: str,
    b_src: str,
    b_grown: str,
    phantom: str,
    stamped_mains: int,
) -> None:
    """KNOWN over-hold, pinned: a stale ``region_anchors`` stamp denies the proof.

    Heal skips a PRESERVED ``symbols`` region (``mode: human`` healed by
    ``cdx generate``'s ``regenerate_regions(..., preserve, modes)`` call, or a
    B-03-locked region) and so never re-stamps its ``region_anchors`` — yet it
    always re-stamps ``fingerprint_tiers`` and ``symbol_sigs``. The anchor stamp
    then under-counts a symbol the stored signature tier already holds, every
    later pure addition reports that symbol as a PHANTOM addition, the proof
    sets it aside against a tier that contains it, and the addition is held
    BREAKING / NEEDS_INTENT on each cycle until an engine RENDER of the region
    re-stamps the anchors (a backend's whole-doc fix does not: see
    :func:`test_a_stale_anchor_stamp_from_an_unrendered_write_holds_additions`).

    For THIS population the hold changes the HASH label only, not the routing:
    an owned ``symbols`` region raises the B-02 REGION advisory (NEEDS_INTENT)
    whenever its owned body differs from the render — which a pure addition
    always causes, since the render gains a table row — so the doc is never
    mechanical on either engine. (A docstring-only edit leaves the table, and
    so the advisory, untouched: see
    :func:`test_an_over_counting_anchor_stamp_is_no_phantom_removal`.) The
    routing-changing stale shapes (a declared region absent from the body, a
    whole-doc backend fix) are pinned by that sibling test.

    This is the conservative direction and it is kept deliberately: the pre-fix
    engine graded the same state ADDITIVE, which could equally mask a shadowed
    break. Proving it here instead (keeping a stamped anchor's occurrences in
    the re-derivation) would clear only the grown-collision row, never the
    new-name row, and would trust a stamp known to be wrong. The ROOT cause is
    heal, fixed in step-1 slice S1-E4 (heal re-stamps ``region_anchors`` from
    the surface for every declared symbol-table region, even when its body is
    preserved). When that lands the stale-stamp precondition below goes red:
    flip the verdict rows to ADDITIVE deliberately.
    """
    # Feature: FEAT-DRIFT-012
    root, spec = _collide_setup(tmp_path, a_src, b_src)
    spec = spec.model_copy(update={"region_modes": {"symbols": RegionMode.HUMAN}})
    doc_path = root / spec.path
    (root / "src" / "b.py").write_text(b_grown, encoding="utf-8")
    # Heal exactly as `cdx generate` does for a human-owned symbols region.
    regenerate_regions(
        doc_path,
        build_document_surface(spec, root),
        None,
        frozenset({"symbols"}),
        {"symbols": RegionMode.HUMAN},
    )
    # The re-heal settles the fingerprint (only the B-02 human-region advisory,
    # a REGION drift, stays open until the human acknowledges it).
    settled = detect(_config(root, (spec,)), tmp_path)
    assert [d.kind for d in settled.drifts] == [DriftKind.REGION]
    # Precondition — the stamp is STALE (S1-E4 turns this red when it lands).
    stamp = stored_region_anchors(parse_doc(doc_path), "symbols") or ()
    assert stamp.count(anchor_id("main")) == stamped_mains
    assert stamp.count(anchor_id(phantom)) < sum(
        s.anchor_id == anchor_id(phantom)
        for s in build_document_surface(spec, root).symbols
    )
    (root / "src" / "b.py").write_text(b_grown + _EXTRA, encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.anchors_added == tuple(
        sorted((anchor_id("extra"), anchor_id(phantom)))
    )
    assert drift.anchors_removed == ()
    assert drift.sigs_changed == ()
    assert drift.sigs_ambiguous == (anchor_id("main"),)
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.apply_tier is ApplyTier.NEEDS_INTENT
    # Label-only here: the owned region's advisory already holds the doc (so a
    # `mechanical_docs == frozenset()` check could not fail on either engine).
    advisory = [d for d in report.drifts if d.kind is DriftKind.REGION]
    assert [d.apply_tier for d in advisory] == [ApplyTier.NEEDS_INTENT]


# --- CKI-1a round 5: the stale stamps that change ROUTING; the K6 default ------ #

# b.py gains a `main` ABOVE a.main (a grown collision) on a doc stamped with one.
_A_PADDED = "# pad\n" * 8 + COLLIDE_A_V1
_B_GROWN = "def main(q: bytes) -> bytes:\n    return q\n\n\n" + _OTHER
_B_PROSE = "Use `main(q: bytes)` from b.py for raw payloads.\n"


def _stale_anchor_stamp(tmp_path: Path, shape: str) -> tuple[Path, DocumentSpec]:
    """A doc brought back in sync by a write that never re-stamps its anchors.

    Stamped with one `main` (a.main + other), b.py then gains a second `main`
    and the doc is re-synced in one of two ship shapes that leave the
    ``region_anchors`` stamp counting ONE `main`:

    * ``whole-doc-backend-fix`` — a backend's whole-doc FIX through
      :func:`heal.apply_fix` (the live-LLM path). The model re-renders the
      table, documents b.main in prose and copies the current composite (as the
      drift detail invites) over front matter it otherwise leaves as it found
      it, so ``fingerprint_tiers``, ``symbol_sigs`` and ``region_anchors`` all
      stay stale;
    * ``declared-region-absent`` — a human replaced the declared ``symbols``
      region, markers and all, with prose. Heal re-stamps the tiers and the
      digests but stamps anchors only for a region present in the body.

    Returns once ``detect`` reads the doc clean, after asserting the stale
    stamp. Heal completing a declared-but-absent region's anchor stamp (S1-E4)
    turns that precondition red for ``declared-region-absent``. The
    ``whole-doc-backend-fix`` shape calls :func:`heal.apply_fix` DIRECTLY, and
    ``apply_fix`` has no surface to complete a stamp from, so a completion done
    by ``Monitor.run`` after the fix leaves this precondition green: that row
    must be re-driven through ``Monitor.run`` with a whole-doc backend to see
    such a fix.
    """
    root, spec = _collide_setup(tmp_path, _A_PADDED, _OTHER)
    doc_path = root / spec.path
    (root / "src" / "b.py").write_text(_B_GROWN, encoding="utf-8")
    surface = build_document_surface(spec, root)
    if shape == "whole-doc-backend-fix":
        doc = parse_doc(doc_path)
        body, _ = set_region(doc.body, "symbols", expected_region("symbols", surface))
        meta = set_fingerprint(doc.meta, surface.fingerprint().composite)
        fix = ProposedFix(
            new_doc_text=render_doc(meta, body + _B_PROSE),
            rationale="b.py gained main(q: bytes)",
        )
        assert apply_fix(doc_path, fix)
    else:
        text = doc_path.read_text(encoding="utf-8")
        start = text.index("<!-- CDM:BEGIN symbols -->")
        end = text.index("<!-- CDM:END symbols -->") + len("<!-- CDM:END symbols -->")
        doc_path.write_text(text[:start] + _B_PROSE + text[end:], encoding="utf-8")
        regenerate_regions(doc_path, surface)
    assert detect(_config(root, (spec,)), tmp_path).ok, "re-synced"
    stamp = stored_region_anchors(parse_doc(doc_path), "symbols") or ()
    assert stamp.count(anchor_id("main")) == 1
    assert sum(s.anchor_id == anchor_id("main") for s in surface.symbols) == 2
    return root, spec


_STALE_SHAPES = [
    pytest.param("whole-doc-backend-fix", id="whole-doc-backend-fix"),
    pytest.param("declared-region-absent", id="declared-region-absent"),
]


@pytest.mark.parametrize("shape", _STALE_SHAPES)
def test_a_stale_anchor_stamp_from_an_unrendered_write_holds_additions(
    tmp_path: Path, shape: str
) -> None:
    """KNOWN over-hold that changes ROUTING, pinned until the stamp is completed.

    After a write that never re-stamps ``region_anchors`` (a whole-doc backend
    fix, or heal over a declared ``symbols`` region a human deleted), a pure
    addition of ``extra`` also reports the under-counted `main` as a PHANTOM
    grown collision; the proof sets both `main`s aside against a tier that
    holds them and denies. Nothing else holds these docs — no owned-region
    advisory — so the verdict IS the routing: held BREAKING / NEEDS_INTENT
    where the pre-fix engine (set delta: just ``extra``) closed it
    mechanically. With the live-LLM backend no engine render follows, so the
    hold recurs on every later addition.

    Kept conservative, like the preserved-region shape. The two rows leave
    differently:

    * ``declared-region-absent`` — when S1-E4 makes heal stamp the anchors of a
      declared region absent from the body, the fixture's stale-stamp
      precondition goes red: flip the row to ADDITIVE / CODE_DERIVED
      deliberately (heal re-stamps the tiers in the same write, so the proof
      then passes);
    * ``whole-doc-backend-fix`` — completing ``region_anchors`` ALONE does not
      flip it: the whole-doc fix leaves ``fingerprint_tiers`` stale too, so
      with two `main`s stamped the proof still cannot reproduce the stored
      tier and the addition stays BREAKING. It flips only once the tiers and
      ``symbol_sigs`` are completed in the same write (S1-RULE11's tier
      completion or equivalent), and — the fixture reaching ``apply_fix``
      directly — only on a row re-driven through ``Monitor.run``.
    """
    # Feature: FEAT-DRIFT-012
    root, spec = _stale_anchor_stamp(tmp_path, shape)
    (root / "src" / "b.py").write_text(_B_GROWN + _EXTRA, encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.anchors_added == tuple(sorted((anchor_id("extra"), anchor_id("main"))))
    assert drift.anchors_removed == ()
    assert drift.sigs_changed == ()
    assert drift.sigs_ambiguous == (anchor_id("main"),)
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.apply_tier is ApplyTier.NEEDS_INTENT
    held = [d.kind for d in report.drifts if d.apply_tier is ApplyTier.NEEDS_INTENT]
    assert held == [DriftKind.HASH], "only the HASH verdict holds this doc"
    assert mechanical_docs(report) == frozenset()


@pytest.mark.parametrize("shape", _STALE_SHAPES)
def test_a_stale_anchor_stamp_still_hides_a_same_name_deletion(
    tmp_path: Path, shape: str
) -> None:
    """KNOWN FALSE NEGATIVE, pre-existing — pinned so its fix flips it on purpose.

    Same stale stamp (one `main` stamped, two in the code). b.main is deleted
    and ``extra`` added in one edit, while the doc still tells readers to use
    ``main(q: bytes)`` from b.py. The multiset delta is only as current as the
    stamp: it counts one `main` before and after, so the deletion is invisible
    (``anchors_removed == ()``), no stamped anchor repeats, the collision proof
    never runs, and the drift grades ADDITIVE -> CODE_DERIVED — closable by
    ``monitor --apply --tiered``. The pre-fix engine grades it identically;
    CKI-1a neither causes nor fixes it, so "deleting one of several same-name
    symbols is a removal" holds only against a CURRENT anchor stamp.

    This row asserts the DEFECT, not the contract. ``declared-region-absent``
    flips to a removal (BREAKING) when S1-E4 makes heal complete that region's
    anchor stamp (the precondition goes red first); S1-ADDPROOF alone would
    also hold it (its stored tiers are current). ``whole-doc-backend-fix``
    stays green under any completion done by ``Monitor.run`` — the fixture
    calls ``apply_fix`` directly — so re-drive it through ``Monitor.run`` when
    S1-E4 lands. That completion must re-stamp the tiers WITH the anchors: two
    `main`s stamped over the stale one-`main` tier make the deletion a
    count-only decrease that the stale tier "proves" phantom (with ``extra``
    set aside it reproduces), so the drift would still grade ADDITIVE.
    """
    # Feature: FEAT-DRIFT-012
    root, spec = _stale_anchor_stamp(tmp_path, shape)
    (root / "src" / "b.py").write_text(_OTHER + _EXTRA, encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.anchors_removed == ()
    assert drift.anchors_added == (anchor_id("extra"),)
    assert drift.sigs_ambiguous == ()
    assert drift.change_severity is ChangeSeverity.ADDITIVE
    assert drift.apply_tier is ApplyTier.CODE_DERIVED
    assert mechanical_docs(report) == frozenset({"api"})


def test_a_drift_that_ran_no_collision_proof_names_no_candidate(
    tmp_path: Path,
) -> None:
    """``Drift.sigs_ambiguous`` defaults EMPTY: only a failed proof fills it.

    The field is rule-2b evidence (non-empty => BREAKING) and it was added
    additively (K6), so every drift ``detect`` builds without running the
    collision proof — a MISSING_DOC, a REGION — and every Drift built outside
    ``detect`` must carry ``()``. A non-empty default would put a phantom
    candidate on each of them the day a consumer (the MCP drift view, JSON
    output) surfaces the field.
    """
    # Feature: FEAT-DRIFT-012
    root = _setup(tmp_path)
    _write_code(root, CODE_V1)
    missing = _doc_spec("eng-guide", Audience.ENG_GUIDE)
    stale = _doc_spec("user-guide", Audience.USER_GUIDE)
    text = _synced_doc_text(stale, root)
    table = text.split("<!-- CDM:BEGIN symbols -->\n")[1].split(
        "<!-- CDM:END symbols -->"
    )[0]
    (root / stale.path).write_text(
        text.replace(table, "stale region contents\n"), encoding="utf-8"
    )
    report = detect(_config(root, (missing, stale)), tmp_path)
    assert sorted(d.kind.value for d in report.drifts) == ["MISSING_DOC", "REGION"]
    hand_built = Drift(
        kind=DriftKind.HASH,
        doc_id="d",
        doc_path="d.md",
        detail="hand-built outside detect",
        audience=Audience.ENG_GUIDE,
    )
    for drift in (*report.drifts, hand_built):
        assert drift.sigs_ambiguous == ()


# --- CKI-1a convergence: an OVER-counting anchor stamp; a grown-only addition -- #

_OTHER_DOC = 'def other() -> None:\n    """Other."""\n    pass\n'
_OTHER_REWORDED = _OTHER_DOC.replace('"""Other."""', '"""Other, reworded."""')
_C_MAIN = "def main(z: bytes) -> bytes:\n    return z\n"
_G_DEF = "\n\ndef g() -> None:\n    pass\n"
_HUMAN_SYMBOLS = {"symbols": RegionMode.HUMAN}


def _generate_human(doc_path: Path, spec: DocumentSpec, root: Path) -> None:
    """Heal exactly as ``cdx generate`` does for a human-owned symbols region."""
    regenerate_regions(
        doc_path,
        build_document_surface(spec, root),
        None,
        frozenset({"symbols"}),
        _HUMAN_SYMBOLS,
    )


def _over_counting_stamp(
    tmp_path: Path,
    shape: str,
    *,
    t1_b_src: str = _OTHER_DOC,
    third_main: bool = False,
) -> tuple[Path, DocumentSpec]:
    """A doc whose ``region_anchors`` stamp OVER-counts `main` after a real deletion.

    a.main and b.main (plus c.main when ``third_main``) are healed, so the stamp
    holds one `main` per symbol. T1 deletes b.main (``t1_b_src`` replaces b.py):
    against that CURRENT stamp the deletion is graded as one removal. The doc is
    then re-synced by a write that leaves the anchor stamp counting b.main:

    * ``declared-region-absent`` — a human replaced the declared ``symbols``
      region, markers and all, with prose. Heal re-stamps ``fingerprint_tiers``
      and ``symbol_sigs`` but stamps anchors only for a region in the body;
    * ``preserved-acknowledged`` — a ``mode: human`` region healed the way
      ``cdx generate`` heals it (preserved), after the human acknowledged the
      B-02 advisory by syncing the owned table to the render. Same stamps;
    * ``whole-doc-backend-fix`` — a backend's whole-doc FIX through
      :func:`heal.apply_fix` (the live-LLM path) that copies the current
      composite over front matter it otherwise leaves as it found it, so the
      TIERS and ``symbol_sigs`` are stale too.

    Returns once ``detect`` reads the doc clean, after asserting the stale
    stamp: one more `main` than the code has.
    """
    root, spec = _collide_setup(
        tmp_path,
        COLLIDE_A_V1,
        COLLIDE_B_V1 + "\n\n" + _OTHER_DOC,
        Audience.ENG_GUIDE,
        extra_srcs=(_C_MAIN,) if third_main else (),
    )
    doc_path = root / spec.path
    if shape == "preserved-acknowledged":
        spec = spec.model_copy(update={"region_modes": _HUMAN_SYMBOLS})
        _generate_human(doc_path, spec, root)
    elif shape == "declared-region-absent":
        text = doc_path.read_text(encoding="utf-8")
        start = text.index("<!-- CDM:BEGIN symbols -->")
        end = text.index("<!-- CDM:END symbols -->") + len("<!-- CDM:END symbols -->")
        doc_path.write_text(
            text[:start] + "See the wiki for the table.\n" + text[end:],
            encoding="utf-8",
        )
        regenerate_regions(doc_path, build_document_surface(spec, root))
    assert detect(_config(root, (spec,)), tmp_path).ok, "fixture must start healed"
    (root / "src" / "b.py").write_text(t1_b_src, encoding="utf-8")
    # T1 — a GENUINE deletion of one of the same-name symbols: a removal.
    t1 = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert t1.anchors_removed.count(anchor_id("main")) == 1
    assert t1.change_severity is ChangeSeverity.BREAKING
    surface = build_document_surface(spec, root)
    if shape == "preserved-acknowledged":
        _generate_human(doc_path, spec, root)
        text = doc_path.read_text(encoding="utf-8")
        synced, _ = set_region(text, "symbols", expected_region("symbols", surface))
        doc_path.write_text(synced, encoding="utf-8")
        _generate_human(doc_path, spec, root)
    elif shape == "declared-region-absent":
        regenerate_regions(doc_path, surface)
    else:
        doc = parse_doc(doc_path)
        body, _ = set_region(doc.body, "symbols", expected_region("symbols", surface))
        meta = set_fingerprint(doc.meta, surface.fingerprint().composite)
        fix = ProposedFix(
            new_doc_text=render_doc(meta, body + "b.main was removed.\n"),
            rationale="b.main removed",
        )
        assert apply_fix(doc_path, fix)
    assert detect(_config(root, (spec,)), tmp_path).ok, "re-synced"
    # Precondition — the stamp is STALE: it still counts b.main.
    stamp = stored_region_anchors(parse_doc(doc_path), "symbols") or ()
    in_code = sum(s.anchor_id == anchor_id("main") for s in surface.symbols)
    assert stamp.count(anchor_id("main")) == in_code + 1
    return root, spec


@pytest.mark.parametrize(
    ("shape", "b_src", "severity", "added", "mechanical"),
    [
        pytest.param(
            "declared-region-absent",
            _OTHER_REWORDED,
            ChangeSeverity.COSMETIC,
            (),
            frozenset({"api"}),
            id="declared-region-absent-docstring-only",
        ),
        pytest.param(
            "declared-region-absent",
            _OTHER_DOC + _EXTRA,
            ChangeSeverity.ADDITIVE,
            (anchor_id("extra"),),
            frozenset({"api"}),
            id="declared-region-absent-pure-add",
        ),
        pytest.param(
            "preserved-acknowledged",
            _OTHER_REWORDED,
            ChangeSeverity.COSMETIC,
            (),
            frozenset({"api"}),
            id="preserved-acknowledged-docstring-only",
        ),
        # The owned table now lacks `extra`, so its B-02 REGION advisory holds
        # the doc: only the HASH label is at stake on this row.
        pytest.param(
            "preserved-acknowledged",
            _OTHER_DOC + _EXTRA,
            ChangeSeverity.ADDITIVE,
            (anchor_id("extra"),),
            frozenset(),
            id="preserved-acknowledged-pure-add",
        ),
    ],
)
def test_an_over_counting_anchor_stamp_is_no_phantom_removal(
    tmp_path: Path,
    shape: str,
    b_src: str,
    severity: ChangeSeverity,
    added: tuple[str, ...],
    mechanical: frozenset[str],
) -> None:
    """A stale stamp that OVER-counts a same-name symbol is not a removal.

    b.main was deleted and that removal already graded (T1); the re-sync
    re-stamped the tiers but not the anchors, so the stamp still counts two
    `main`s against one in the code. As a multiset that is a count-only
    decrease — `main` is still present — and every LATER drift on the doc read
    it as a phantom removal: BREAKING / NEEDS_INTENT with a false "-1" in the
    ReviewRecord, on every cycle, even for a docstring-only edit. The pre-fix
    set delta could not see a count, so it graded these COSMETIC / ADDITIVE
    and closed them mechanically (unless the owned table's advisory held the
    doc, as on the preserved pure-add row).

    The stored signature tier settles it: with the additions set aside it
    re-derives byte-for-byte (or the tier did not move at all), so it counts
    exactly the `main`s the code has and the stamp's extra one is stale. The
    decrease is discharged, and the verdict and routing are the pre-fix
    engine's on every row.
    """
    # Feature: FEAT-DRIFT-006
    root, spec = _over_counting_stamp(tmp_path, shape)
    (root / "src" / "b.py").write_text(b_src, encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.anchors_removed == ()
    assert drift.anchors_added == added
    assert drift.sigs_ambiguous == ()
    assert drift.change_severity is severity
    assert drift.apply_tier is ApplyTier.CODE_DERIVED
    assert "-1)" not in drift.detail
    assert mechanical_docs(report) == mechanical


def test_an_over_counting_stamp_that_also_misses_a_name_is_no_phantom_removal(
    tmp_path: Path,
) -> None:
    """The tier that did not move proves the stale stamp wrong both ways.

    T1 deletes b.main AND adds ``g`` in one edit, so after the re-sync the stamp
    both over-counts `main` and lacks ``g``. A docstring-only edit then reports
    ``g`` as a phantom addition and `main` as a phantom count-only decrease.
    Setting ``g`` aside cannot reproduce a stored tier that holds it, but the
    signature tier did not move at all, so the stored tier counts exactly what
    the code has and the decrease is discharged. The result — ADDITIVE with a
    phantom "+1", CODE_DERIVED — is the pre-fix engine's verdict for the same
    state (its set delta saw only ``g``).
    """
    # Feature: FEAT-DRIFT-006
    root, spec = _over_counting_stamp(
        tmp_path, "declared-region-absent", t1_b_src=_OTHER_DOC + _G_DEF
    )
    (root / "src" / "b.py").write_text(_OTHER_REWORDED + _G_DEF, encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.drifted_tiers == ("docstring",)
    assert drift.anchors_added == (anchor_id("g"),)
    assert drift.anchors_removed == ()
    assert drift.change_severity is ChangeSeverity.ADDITIVE
    assert mechanical_docs(report) == frozenset({"api"})


def test_a_genuine_deletion_under_an_over_counting_stamp_stays_a_removal(
    tmp_path: Path,
) -> None:
    """The stale-stamp discharge never launders a REAL same-name deletion.

    Three `main`s healed; T1 deletes b.main (the stamp keeps three, the tier
    two). T2 then deletes c.main — a genuine deletion — and adds ``extra``. The
    re-derived tier (``extra`` set aside) holds one `main` where the stored
    tier holds two, so nothing proves the decrease stale and it stays a removal
    (rule 1). The count is not split: the stamp's stale `main` and the real one
    are both reported, since the tier proof is all-or-nothing.
    """
    # Feature: FEAT-DRIFT-006
    root, spec = _over_counting_stamp(
        tmp_path, "declared-region-absent", third_main=True
    )
    (root / "src" / "c.py").write_text("", encoding="utf-8")
    (root / "src" / "b.py").write_text(_OTHER_DOC + _EXTRA, encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.anchors_removed == (anchor_id("main"),) * 2
    assert drift.anchors_added == (anchor_id("extra"),)
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.apply_tier is ApplyTier.NEEDS_INTENT
    assert mechanical_docs(report) == frozenset()


def test_an_over_counting_stamp_without_stored_tiers_keeps_the_removal(
    tmp_path: Path,
) -> None:
    """No stored signature tier ⇒ nothing can prove the stamp stale ⇒ keep it.

    Same over-counting stamp, but the doc carries no ``fingerprint_tiers``
    (hand-stamped; heal always writes them), so ``drifted_tiers`` is empty —
    which must not be read as "the signature tier did not move". The
    count-only decrease stays a removal and the doc is held.
    """
    # Feature: FEAT-DRIFT-006
    root, spec = _over_counting_stamp(tmp_path, "declared-region-absent")
    _strip_stored_tiers(root / spec.path)
    (root / "src" / "b.py").write_text(_OTHER_REWORDED, encoding="utf-8")
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.drifted_tiers == ()
    assert drift.anchors_removed == (anchor_id("main"),)
    assert drift.change_severity is ChangeSeverity.BREAKING


def test_an_over_counting_stamp_over_stale_tiers_keeps_the_removal(
    tmp_path: Path,
) -> None:
    """KNOWN residual, pinned: stale TIERS cannot prove a stale stamp wrong.

    A backend's whole-doc FIX (the live-LLM path) copied the current composite
    over stale ``fingerprint_tiers``, ``symbol_sigs`` and ``region_anchors``, so
    after b.main's deletion all three still count two `main`s. A later pure
    addition cannot re-derive the stored tier, the count-only decrease stays a
    removal, and the "-1" is a phantom. The verdict matches the pre-fix engine,
    which held it too: the stale last-writer digest (b.main's) no longer
    matches the surviving a.main, so ``sigs_changed`` names `main`. The stale
    state goes once the whole-doc write completes the anchors, the tiers and
    ``symbol_sigs`` together (S1-E4 with S1-RULE11's tier completion); the
    fixture calls ``apply_fix`` directly, so re-drive this row through
    ``Monitor.run`` then and flip it to ADDITIVE deliberately.
    """
    # Feature: FEAT-DRIFT-006
    root, spec = _over_counting_stamp(tmp_path, "whole-doc-backend-fix")
    (root / "src" / "b.py").write_text(_OTHER_DOC + _EXTRA, encoding="utf-8")
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.anchors_removed == (anchor_id("main"),)
    assert drift.sigs_changed == (anchor_id("main"),)
    assert drift.change_severity is ChangeSeverity.BREAKING


@pytest.mark.parametrize(
    "a_src",
    [
        # A second `main` ABOVE the unchanged a.main; b.main stays last writer.
        pytest.param(
            "def main(w: float) -> float:\n    return w\n" + COLLIDE_A_V1,
            id="grown-only",
        ),
        # The same, while the shadowed a.main ALSO gains a required parameter.
        pytest.param(
            "def main(w: float) -> float:\n    return w\n"
            "def main(x: int, strict: bool) -> int:\n    return x\n",
            id="grown-only-plus-shadowed-break",
        ),
    ],
)
def test_a_grown_only_addition_is_held(tmp_path: Path, a_src: str) -> None:
    """A new same-name symbol with NO wholly-new name is held (conservative).

    a.py gains a second `main` above a.main, so b.main (b.py line 4) stays the
    last writer: ``sigs_changed`` is empty and the multiset delta reports only
    the extra `main`. Which `main` is new cannot be told from name-keyed stamps,
    so the collision proof must still run — it is not reserved for edits that
    add a wholly-new name — and it cannot reproduce the stored tier. Both rows
    are held BREAKING / NEEDS_INTENT, including the innocent one: the pre-fix
    engine held them too (its set delta saw no addition, so rule 4 fired). A
    guard narrowed to "a new name was added" would grade the shadowed break
    ADDITIVE and let ``--tiered`` close it.
    """
    # Feature: FEAT-DRIFT-012
    root, spec = _collide_setup(tmp_path, COLLIDE_A_V1, COLLIDE_B_V1)
    (root / "src" / "a.py").write_text(a_src, encoding="utf-8")
    report = detect(_config(root, (spec,)), tmp_path)
    drift = _hash_drift(report)
    assert drift.anchors_added == (anchor_id("main"),)
    assert drift.anchors_removed == ()
    assert drift.sigs_changed == ()
    assert drift.sigs_ambiguous == (anchor_id("main"),)
    assert drift.change_severity is ChangeSeverity.BREAKING
    assert drift.apply_tier is ApplyTier.NEEDS_INTENT
    assert mechanical_docs(report) == frozenset()


def test_a_wholly_removed_name_on_an_over_counting_stamp_stays_a_removal(
    tmp_path: Path,
) -> None:
    """Only a COUNT-ONLY decrease is discharged; a vanished name stays a removal.

    T1 deletes b.main AND ``other`` (the whole of b.py); after the re-sync the
    stamp still counts two `main`s and ``other``. A pure addition then proves
    the `main` decrease stale (``extra`` set aside, the stored tier
    reproduces), so no phantom "-1" for `main`. The stale ``other`` is a
    removal of a WHOLE name — which the pre-fix set delta reported too, on
    both engines — and it is left as is: BREAKING. Discharging it would be
    sound by the same proof, but it is not the multiset's regression; S1-E4's
    stamp completion removes that stale state.
    """
    # Feature: FEAT-DRIFT-006
    root, spec = _over_counting_stamp(tmp_path, "declared-region-absent", t1_b_src="")
    (root / "src" / "b.py").write_text(_EXTRA.lstrip("\n"), encoding="utf-8")
    drift = _hash_drift(detect(_config(root, (spec,)), tmp_path))
    assert drift.anchors_removed == (anchor_id("other"),)
    assert drift.anchors_added == (anchor_id("extra"),)
    assert drift.change_severity is ChangeSeverity.BREAKING
