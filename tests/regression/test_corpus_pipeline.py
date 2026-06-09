"""H-03 regression corpus — the heal/drift pipeline invariants.

Each case names the lesson id it guards (`[B-02]`, `[CDM-07]`, …) so a failure
points straight to the LESSON_LEARNT.md / problems writeup. These are the durable
pipeline guarantees: a learned failure with a corpus guard cannot silently return.

See ``tests/regression/README.md`` for the case → lesson map.
"""

from __future__ import annotations

from pathlib import Path

from code_doc_monitor.config import Audience, RegionMode
from code_doc_monitor.drift import DriftKind
from code_doc_monitor.extract import build_document_surface
from code_doc_monitor.heal import regenerate_regions
from code_doc_monitor.manifest import (
    parse_doc,
    region_body_hash,
    regions,
    set_region,
    stored_region_hash,
)
from code_doc_monitor.schema import Verdict
from code_doc_monitor.syncpr import should_sync

from ._fixtures import (
    DOC_STUB,
    SHARED_DOCSTRING_CHANGE,
    SHARED_SIG_CHANGE,
    SHARED_V1,
    make_repo,
    monitor,
)

# ---------------------------------------------------------------------------
# [CDM-07] Audience invalidation at extraction: a docstring/comment-only edit
# drifts the eng-guide but is a NON-event for the user-guide.
# ---------------------------------------------------------------------------


def test_audience_invalidation_docstring_only_drifts_eng_not_user(
    tmp_path: Path,
) -> None:
    """[CDM-07] A docstring-only change drifts eng, never user.

    The user-guide surface hash excludes docstrings, so the change produces ZERO
    user-guide drift (stronger than detect-then-INVALIDATE). Guards the
    extraction-level audience policy (extract.build_document_surface).

    BREAK-IT (confirmed bites; not committed): folding the docstring into the
    user-guide payload (drop the `audience is ENG_GUIDE` guard in
    `extract.surface_hash`) makes `drifted == {"user", "eng"}` → this reds.
    """
    root, cfg = make_repo(tmp_path)
    old, new = SHARED_DOCSTRING_CHANGE
    (root / "shared.py").write_text(SHARED_V1.replace(old, new), encoding="utf-8")

    drifted = {d.doc_id for d in monitor(root, cfg).check().drifts}
    assert drifted == {"eng"}, "user guide must NOT drift on a docstring-only edit"


def test_audience_public_signature_drifts_both(tmp_path: Path) -> None:
    """[CDM-07] A PUBLIC signature change is an event for EVERY audience.

    The foil to the docstring case: proves the audience filter is selective, not
    a blanket suppressor — a real surface move reaches both docs.
    """
    root, cfg = make_repo(tmp_path)
    old, new = SHARED_SIG_CHANGE
    (root / "shared.py").write_text(SHARED_V1.replace(old, new), encoding="utf-8")

    drifted = {d.doc_id for d in monitor(root, cfg).check().drifts}
    assert drifted == {"user", "eng"}


# ---------------------------------------------------------------------------
# [CDM-03] Heal idempotence + no-trailing-newline: regenerate → clean →
# regenerate is False.
# ---------------------------------------------------------------------------


def test_heal_is_idempotent_no_perpetual_region_drift(tmp_path: Path) -> None:
    """[CDM-03] regenerate_regions closes drift then a re-run makes NO change.

    A region body never carries a trailing newline (set_region/regions split on
    "\\n"), so the rendered body must equal the stored body — else REGION drift
    would be perpetual. Guards the regenerate→detect-clean→regenerate-False loop.

    BREAK-IT (confirmed bites): having `symbol_table`/`expected_region` emit a
    body WITH a trailing newline makes the freshly-rendered body never equal the
    stored body → the second `regenerate_regions` returns True → this reds.
    """
    root, cfg = make_repo(tmp_path)
    old, new = SHARED_SIG_CHANGE
    (root / "shared.py").write_text(SHARED_V1.replace(old, new), encoding="utf-8")
    assert not monitor(root, cfg).check().ok  # drift present

    spec = next(d for d in cfg.documents if d.id == "eng")
    doc_path = root / spec.path
    surface = build_document_surface(spec, root)

    assert regenerate_regions(doc_path, surface) is True  # heals
    assert regenerate_regions(doc_path, surface) is False  # idempotent (K7)


# ---------------------------------------------------------------------------
# [B-02] A human-owned region is never auto-edited; its body survives
# `monitor --apply` byte-identical while the fingerprint is refreshed.
# ---------------------------------------------------------------------------


def _human_eng_spec(root: Path) -> object:
    from code_doc_monitor.config import CodeRef, DocumentSpec

    return DocumentSpec(
        id="eng",
        path="docs/eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols",),
        region_modes={"symbols": RegionMode.HUMAN},
    )


def test_human_region_never_auto_edited(tmp_path: Path) -> None:
    """[B-02] A `human` region survives `monitor --apply` BYTE-IDENTICAL.

    The write-boundary guarantee (apply_fix re-injects the current body of every
    preserved region) holds regardless of backend; the fingerprint still
    refreshes. Guards heal.apply_fix's `preserve` contract end to end.

    BREAK-IT (confirmed bites; reverted): making `heal.locked_region_ids` return
    an empty set (so the engine re-authors a `human` region instead of preserving
    it) makes apply_fix overwrite the human body → the `== human_body` assertion
    reds. (The redundant `preserve` set in `monitor.run` is belt-and-suspenders;
    the load-bearing guard is the modes-derived lock in heal.)
    """
    from code_doc_monitor.config import MonitorConfig

    root, _ = make_repo(tmp_path)
    spec = _human_eng_spec(root)
    cfg = MonitorConfig(documents=(spec,))  # type: ignore[arg-type]

    md_path = root / spec.path  # type: ignore[attr-defined]
    regenerate_regions(md_path, build_document_surface(spec, root))  # type: ignore[arg-type]
    text = md_path.read_text(encoding="utf-8")
    text, _ = set_region(text, "symbols", "Hand-written notes a human owns.")
    md_path.write_text(text, encoding="utf-8")
    human_body = regions(parse_doc(md_path))["symbols"]
    # Re-baseline the fingerprint, preserving the (unstamped) human body.
    regenerate_regions(
        md_path,
        build_document_surface(spec, root),  # type: ignore[arg-type]
        preserve=frozenset({"symbols"}),
    )
    assert monitor(root, cfg).check().ok

    old, new = SHARED_SIG_CHANGE
    (root / "shared.py").write_text(SHARED_V1.replace(old, new), encoding="utf-8")

    # check REPORTS the human region as unhealable advisory.
    report = monitor(root, cfg).check()
    region_drift = next(d for d in report.drifts if d.kind is DriftKind.REGION)
    assert region_drift.healable is False
    assert "human-owned" in region_drift.detail

    fp_before = parse_doc(md_path).meta["cdm"]["fingerprint"]
    monitor(root, cfg).run(apply=True)
    after = parse_doc(md_path)
    assert regions(after)["symbols"] == human_body  # never auto-edited
    assert after.meta["cdm"]["fingerprint"] != fp_before  # fingerprint refreshed


def test_human_advisory_persists_until_human_edits(tmp_path: Path) -> None:
    """[B-03] The human advisory persists across a fingerprint heal, then clears.

    Stamping the human BODY (not withholding the fingerprint) is what makes the
    advisory survive `--apply` and clear only when the body changes. Guards the
    drift advisory-persistence property at the unit seam.
    """
    from code_doc_monitor.drift import detect

    root, _ = make_repo(tmp_path)
    spec = _human_eng_spec(root)
    from code_doc_monitor.config import MonitorConfig

    cfg = MonitorConfig(root=".", documents=(spec,))  # type: ignore[arg-type]
    md_path = root / spec.path  # type: ignore[attr-defined]

    regenerate_regions(md_path, build_document_surface(spec, root))  # type: ignore[arg-type]
    text = md_path.read_text(encoding="utf-8")
    text, _ = set_region(text, "symbols", "Human prose.")
    md_path.write_text(text, encoding="utf-8")
    # Stamp the human body (as a real `--apply` heal would).
    modes = {"symbols": RegionMode.HUMAN}
    regenerate_regions(
        md_path,
        build_document_surface(spec, root),  # type: ignore[arg-type]
        preserve=frozenset({"symbols"}),
        modes=modes,
    )
    # While the body still equals its stamp, the advisory keeps firing.
    report = detect(cfg, root)
    region_drifts = [d for d in report.drifts if d.kind is DriftKind.REGION]
    assert region_drifts and all(not d.healable for d in region_drifts)

    # The human edits the body → the advisory clears (body diverges from stamp).
    text2 = md_path.read_text(encoding="utf-8")
    text2, _ = set_region(text2, "symbols", "Human prose, now revised.")
    md_path.write_text(text2, encoding="utf-8")
    assert detect(cfg, root).ok


# ---------------------------------------------------------------------------
# [B-03] llm-seeded fill-then-lock three-phase property.
# ---------------------------------------------------------------------------


def test_llm_seeded_fill_then_lock_three_phase(tmp_path: Path) -> None:
    """[B-03] FILL → LOCK → REPORT for an `llm-seeded` region.

    (1) `--apply` fills the region from the surface and stamps its hash;
    (2) after a human edits the body, `--apply` leaves it byte-identical (locked);
    (3) a locked region reports REGION healable=False on a code move.
    Guards the central B-03 lock predicate (manifest.region_is_locked) end to end.

    BREAK-IT (confirmed bites; reverted): making `heal.locked_region_ids` return
    an empty set unlocks the human-edited body → phase 3's `--apply` re-authors it
    → the `== human_body` assertion reds.
    """
    from code_doc_monitor.config import CodeRef, DocumentSpec, MonitorConfig

    root, _ = make_repo(tmp_path)
    spec = DocumentSpec(
        id="eng",
        path="docs/eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols",),
        region_modes={"symbols": RegionMode.LLM_SEEDED},
    )
    cfg = MonitorConfig(documents=(spec,))
    md_path = root / spec.path
    # Reset the eng doc to an UNFILLED stub so phase 1 actually fills it
    # (make_repo pre-heals it as `generated`).
    md_path.write_text(DOC_STUB.format(title="Engineering guide"), encoding="utf-8")

    # Phase 1 — FILL + stamp.
    monitor(root, cfg).run(apply=True)
    assert monitor(root, cfg).check().ok
    doc = parse_doc(md_path)
    filled = regions(doc)["symbols"]
    assert "compute" in filled
    assert stored_region_hash(doc, "symbols") == region_body_hash(filled)

    # Phase 2 — LOCK: a human edit diverges from the stamp.
    text = md_path.read_text(encoding="utf-8")
    text, _ = set_region(text, "symbols", "A human rewrote the notes.")
    md_path.write_text(text, encoding="utf-8")
    human_body = regions(parse_doc(md_path))["symbols"]
    modes = {"symbols": RegionMode.LLM_SEEDED}
    regenerate_regions(
        md_path,
        build_document_surface(spec, root),
        preserve=frozenset({"symbols"}),
        modes=modes,
    )
    assert monitor(root, cfg).check().ok

    old, new = SHARED_SIG_CHANGE
    (root / "shared.py").write_text(SHARED_V1.replace(old, new), encoding="utf-8")

    # Phase 3 — REPORT + locked body untouched by --apply.
    report = monitor(root, cfg).check()
    region_drift = next(d for d in report.drifts if d.kind is DriftKind.REGION)
    assert region_drift.healable is False
    monitor(root, cfg).run(apply=True)
    assert regions(parse_doc(md_path))["symbols"] == human_body


def test_llm_seeded_unlocked_regenerates_on_code_move(tmp_path: Path) -> None:
    """[B-03] An UNLOCKED llm-seeded region still regenerates (engine-owned).

    The foil to the lock case: until a human edits it, an llm-seeded region is
    treated like `generated`, so a code move heals it cleanly.
    """
    from code_doc_monitor.config import CodeRef, DocumentSpec, MonitorConfig

    root, _ = make_repo(tmp_path)
    spec = DocumentSpec(
        id="eng",
        path="docs/eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols",),
        region_modes={"symbols": RegionMode.LLM_SEEDED},
    )
    cfg = MonitorConfig(documents=(spec,))
    md_path = root / spec.path
    md_path.write_text(DOC_STUB.format(title="Engineering guide"), encoding="utf-8")
    monitor(root, cfg).run(apply=True)
    assert monitor(root, cfg).check().ok

    old, new = SHARED_SIG_CHANGE
    (root / "shared.py").write_text(SHARED_V1.replace(old, new), encoding="utf-8")
    result = monitor(root, cfg).run(apply=True)
    assert result.remaining == ()
    assert "c=0" in regions(parse_doc(md_path))["symbols"]


# ---------------------------------------------------------------------------
# [CDM-07] Detection and remediation agree on "fully healed": a realistic code
# change (HASH + REGION) closes in ONE `monitor --apply` pass.
# ---------------------------------------------------------------------------


def test_both_drift_shapes_close_in_one_apply(tmp_path: Path) -> None:
    """[CDM-07] A real code change raises HASH+REGION; one --apply converges.

    The whole-doc FIX regenerates regions AND refreshes the fingerprint together,
    so a backend FIX and an engine heal cannot disagree and the loop closes.
    """
    root, cfg = make_repo(tmp_path)
    old, new = SHARED_SIG_CHANGE
    (root / "shared.py").write_text(SHARED_V1.replace(old, new), encoding="utf-8")

    result = monitor(root, cfg).run(apply=True)
    assert all(h.result.verdict is Verdict.FIX for h in result.handled)
    assert result.remaining == ()
    assert monitor(root, cfg).check().ok  # fully self-healed


# ---------------------------------------------------------------------------
# [C-04] Loop-safety: a doc-only commit → should_sync is False (truth table).
# ---------------------------------------------------------------------------


def _doc_only_config() -> object:
    from code_doc_monitor.config import DocumentSpec, MonitorConfig

    return MonitorConfig(
        root=".",
        documents=(
            DocumentSpec(
                id="user-guide",
                path="docs/user-guide.md",
                audience=Audience.USER_GUIDE,
            ),
            DocumentSpec(
                id="eng-guide",
                path="docs/eng-guide.md",
                audience=Audience.ENG_GUIDE,
            ),
        ),
    )


def test_loop_safety_doc_only_commit_does_not_resync(tmp_path: Path) -> None:
    """[C-04] should_sync is False iff EVERY changed file is a managed doc.

    The structural loop-breaker (pure set membership, separator-normalized) is
    what stops the PR-driven heal loop from re-triggering on the bot's own
    doc-only commit. Guards the truth table + the `./`/`\\` normalization.

    BREAK-IT (confirmed bites): dropping the POSIX normalization (compare raw
    strings) makes `docs\\user-guide.md` look non-managed → should_sync True →
    the doc-only assertions red.
    """
    cfg = _doc_only_config()
    docs = ["docs/user-guide.md", "docs/eng-guide.md"]
    assert should_sync(docs, cfg) is False  # type: ignore[arg-type]
    assert should_sync([], cfg) is False  # type: ignore[arg-type]
    # A single non-doc file flips it.
    assert should_sync(["docs/user-guide.md", "src/app.py"], cfg) is True  # type: ignore[arg-type]
    # Normalization: `./` + back-slash variants of the managed doc stay doc-only.
    assert should_sync(["./docs/user-guide.md"], cfg) is False  # type: ignore[arg-type]
    assert should_sync(["docs\\user-guide.md"], cfg) is False  # type: ignore[arg-type]
    assert should_sync(["./src/app.py"], cfg) is True  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# [B-06] A pure-`llm` (no-renderer) region is backend-authored prose:
# re-authored on a code move, idempotent, and never touches a human region.
# ---------------------------------------------------------------------------


def test_pure_llm_no_renderer_authored_reauthor_idempotent_human_untouched(
    tmp_path: Path,
) -> None:
    """[B-06] A `mode: llm` no-renderer region is AUTHORED prose, end to end.

    (1) a code move surfaces it as a healable REGION drift (not UNHEALABLE) and
        `--apply` re-authors its prose from the current surface;
    (2) a second `--apply` is a clean no-op (idempotent, K7/K10);
    (3) a `human` region alongside is byte-identical throughout (B-02, K5).

    BREAK-IT (confirmed bites; reverted): reverting the drift.py B-06 branch
    (so a no-renderer `llm` region falls back to UNHEALABLE) reds (1) — the drift
    is UNHEALABLE and `--apply` never authors `compute` into the prose.
    """
    from code_doc_monitor.blocks import symbol_table
    from code_doc_monitor.config import CodeRef, DocumentSpec, MonitorConfig
    from code_doc_monitor.manifest import render_doc, set_fingerprint

    root, _ = make_repo(tmp_path)
    spec = DocumentSpec(
        id="eng",
        path="docs/eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols", "overview", "notes"),
        region_modes={"overview": RegionMode.LLM, "notes": RegionMode.HUMAN},
    )
    cfg = MonitorConfig(documents=(spec,))
    md_path = root / spec.path

    surface = build_document_surface(spec, root)
    human_body = "Hand-written human notes."
    body = (
        "# Engineering guide\n\n"
        "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n\n"
        "<!-- CDM:BEGIN overview -->\n<!-- CDM:END overview -->\n\n"
        "<!-- CDM:BEGIN notes -->\n<!-- CDM:END notes -->\n"
    )
    body, _ = set_region(body, "symbols", symbol_table(surface))
    body, _ = set_region(body, "overview", "Initial authored prose.")
    body, _ = set_region(body, "notes", human_body)
    md_path.write_text(
        render_doc(set_fingerprint({}, surface.surface_hash()), body),
        encoding="utf-8",
    )
    assert monitor(root, cfg).check().ok

    # (1) code move -> healable REGION drift -> --apply re-authors the prose.
    old, new = SHARED_SIG_CHANGE
    (root / "shared.py").write_text(SHARED_V1.replace(old, new), encoding="utf-8")
    report = monitor(root, cfg).check()
    overview = next(d for d in report.drifts if d.region_id == "overview")
    assert overview.kind is DriftKind.REGION
    assert overview.healable is True

    result = monitor(root, cfg).run(apply=True)
    assert result.remaining == ()
    after = regions(parse_doc(md_path))
    assert "compute" in after["overview"]  # re-authored from the surface
    assert "| symbol |" not in after["overview"]  # prose, not a table
    assert after["notes"] == human_body  # (3) human byte-identical

    # (2) idempotent: a second --apply changes nothing.
    snap = md_path.read_bytes()
    monitor(root, cfg).run(apply=True)
    assert md_path.read_bytes() == snap
    assert monitor(root, cfg).check().ok
