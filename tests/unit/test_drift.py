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

from pathlib import Path

from custodex.blocks import expected_region, symbol_table
from custodex.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
    RegionMode,
)
from custodex.drift import Drift, DriftKind, DriftReport, detect
from custodex.extract import build_document_surface
from custodex.manifest import (
    render_doc,
    set_fingerprint,
    set_fingerprint_tiers,
    set_region,
    set_region_anchors,
)

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
from custodex.extract import anchor_id  # noqa: E402

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
