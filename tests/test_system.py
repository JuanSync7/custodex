"""System / end-to-end acceptance tests (CDM-07).

These exercise the whole pipeline offline (mock backend, file/null sinks) on a
fixture repo and assert the SPEC acceptance criteria:

* a SHARED code file grouped into a ``user-guide`` doc and an ``eng-guide`` doc;
* a public-signature change drifts BOTH docs and ``monitor --apply`` closes both;
* a docstring-only change drifts ONLY the eng-guide (audience-level invalidation
  in the extractor — the strongest form of "this change doesn't affect the user
  guide"), and ``monitor --apply`` closes the eng-guide;
* an unknown managed region ESCALATEs and stays in ``remaining``;
* every handled drift is recorded (original drift + fix) and emitted to a
  central sink;
* swapping the backend ``mock`` -> ``claude-code`` changes only which subprocess
  runs (injected fake runner), not the orchestration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from code_doc_monitor import cli
from code_doc_monitor.backends import BackendResult, ClaudeCodeBackend, FixRequest
from code_doc_monitor.blocks import expected_region
from code_doc_monitor.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
)
from code_doc_monitor.drift import DriftKind
from code_doc_monitor.extract import build_document_surface
from code_doc_monitor.heal import regenerate_regions, render_corrected
from code_doc_monitor.monitor import Monitor
from code_doc_monitor.reviewlog import read_all
from code_doc_monitor.schema import ProposedFix, Verdict
from code_doc_monitor.sinks import FileSink

_NOW = "2026-06-01T00:00:00Z"

_SHARED_V1 = '''\
def compute(a, b):
    """Add two numbers."""
    return a + b


def _private_helper(x):
    """Internal only."""
    return x * 2
'''

_DOC_STUB = """\
# {title}

Prose written by a human.

<!-- CDM:BEGIN symbols -->
PLACEHOLDER
<!-- CDM:END symbols -->
"""


def _make_repo(tmp_path: Path) -> tuple[Path, MonitorConfig]:
    """A fixture repo: one shared code file referenced by two docs."""
    root = tmp_path
    (root / "shared.py").write_text(_SHARED_V1, encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "user.md").write_text(
        _DOC_STUB.format(title="User guide"), encoding="utf-8"
    )
    (root / "docs" / "eng.md").write_text(
        _DOC_STUB.format(title="Engineering guide"), encoding="utf-8"
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
    # Heal to a clean baseline.
    for spec in (user, eng):
        regenerate_regions(root / spec.path, build_document_surface(spec, root))
    return root, cfg


def _monitor(root: Path, cfg: MonitorConfig, **kw: object) -> Monitor:
    return Monitor(cfg, root, now=lambda: _NOW, **kw)  # type: ignore[arg-type]


def test_baseline_is_clean(tmp_path: Path) -> None:
    root, cfg = _make_repo(tmp_path)
    assert _monitor(root, cfg).check().ok


def test_public_signature_change_drifts_both_and_heals(tmp_path: Path) -> None:
    root, cfg = _make_repo(tmp_path)
    # change the PUBLIC signature -> affects every audience
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )
    report = _monitor(root, cfg).check()
    drifted_docs = {d.doc_id for d in report.drifts}
    assert drifted_docs == {"user", "eng"}

    result = _monitor(root, cfg).run(apply=True)
    assert all(h.result.verdict is Verdict.FIX for h in result.handled)
    assert result.remaining == ()
    assert _monitor(root, cfg).check().ok  # fully self-healed


def test_docstring_change_drifts_only_eng_guide(tmp_path: Path) -> None:
    root, cfg = _make_repo(tmp_path)
    # change ONLY a docstring -> invisible to the user guide (extractor filters
    # it out), but real drift for the eng guide.
    (root / "shared.py").write_text(
        _SHARED_V1.replace(
            '"""Add two numbers."""', '"""Add two integers together."""'
        ),
        encoding="utf-8",
    )
    report = _monitor(root, cfg).check()
    drifted_docs = {d.doc_id for d in report.drifts}
    assert drifted_docs == {"eng"}, "user guide must NOT drift on a docstring edit"

    _monitor(root, cfg).run(apply=True)
    assert _monitor(root, cfg).check().ok


def test_private_symbol_change_invisible_to_user_guide(tmp_path: Path) -> None:
    root, cfg = _make_repo(tmp_path)
    (root / "shared.py").write_text(
        _SHARED_V1.replace("return x * 2", "return x * 3"), encoding="utf-8"
    )
    drifted_docs = {d.doc_id for d in _monitor(root, cfg).check().drifts}
    # _private_helper body change: eng-guide tracks it, user-guide does not.
    assert "user" not in drifted_docs


def test_records_written_and_emitted_to_central_sink(tmp_path: Path) -> None:
    root, cfg = _make_repo(tmp_path)
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )
    central = root / "central.jsonl"
    log = root / "review-log.jsonl"
    result = _monitor(root, cfg, sink=FileSink(central), log_path=log).run(apply=True)
    # every handled drift produced a record carrying the original drift + fix
    assert len(result.records) == len(result.handled) >= 2
    on_disk = read_all(log)
    assert len(on_disk) == len(result.records)
    assert all(r.drift_detail for r in on_disk)
    fixes = [r for r in on_disk if r.verdict is Verdict.FIX]
    assert fixes and all(r.fix is not None for r in fixes)
    # the central system received the same records (offline file sink)
    central_lines = central.read_text(encoding="utf-8").strip().splitlines()
    assert len(central_lines) == len(result.records)


def test_unknown_region_escalates_and_remains(tmp_path: Path) -> None:
    root, _ = _make_repo(tmp_path)
    # A doc that DECLARES it manages a region the engine has no renderer for is
    # UNHEALABLE -> the backend ESCALATEs (a human must resolve it), so it stays
    # in `remaining` even after monitor --apply.
    eng = DocumentSpec(
        id="eng",
        path="docs/eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols", "mystery"),
    )
    cfg = MonitorConfig(documents=(eng,))
    doc = root / "docs" / "eng.md"
    doc.write_text(
        doc.read_text(encoding="utf-8")
        + "\n<!-- CDM:BEGIN mystery -->\nx\n<!-- CDM:END mystery -->\n",
        encoding="utf-8",
    )
    result = _monitor(root, cfg).run(apply=True)
    kinds = {d.kind for d in result.remaining}
    assert DriftKind.UNHEALABLE in kinds
    escalated = [h for h in result.handled if h.result.verdict is Verdict.ESCALATE]
    assert escalated


def test_backend_swap_only_changes_the_subprocess(tmp_path: Path) -> None:
    """mock -> claude-code: same orchestration, just an injected runner.

    The fake runner stands in for a headless `claude -p` call and returns the
    JSON verdict contract. No real subprocess is spawned (K4).
    """
    root, cfg = _make_repo(tmp_path)
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_runner(argv: list[str], prompt: str, timeout: int) -> str:
        calls.append(argv)
        # stand in for a headless `claude -p` session that reviewed the drift
        # and returned the JSON verdict contract (no real subprocess, K4).
        return json.dumps(
            {
                "verdict": "ESCALATE",
                "cause": "fake claude session reviewed the drift",
                "fix": None,
            }
        )

    backend = ClaudeCodeBackend(command=("claude", "-p"), runner=fake_runner)
    result = _monitor(root, cfg, backend=backend).run(apply=True)
    # the claude-code backend was actually invoked (the subprocess runner ran)
    assert calls, "the injected runner (the headless claude session) was not called"
    assert all(argv[:2] == ["claude", "-p"] for argv in calls)
    # orchestration still recorded a verdict per drift
    assert len(result.records) == len(result.handled) >= 2


def test_both_shapes_fix_self_heals_in_one_pass(tmp_path: Path) -> None:
    """A real-LLM reply that fills BOTH fix shapes still closes the loop once.

    The headless `claude -p` demo showed a real model returning, for a HASH
    drift, the regenerated region AND a full corrected document. apply_fix must
    prefer the whole-doc text (the only shape that refreshes the fingerprint) so
    ``monitor --apply`` self-heals in a single pass instead of leaving a residual
    HASH drift. This reproduces that reply offline and guards the regression.
    """
    root, cfg = _make_repo(tmp_path)
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )

    class _BothShapesBackend:
        """Stands in for a real LLM that returns a region body AND whole-doc text."""

        def propose(self, req: FixRequest) -> BackendResult:
            corrected = (
                render_corrected(req.doc_text, req.surface) if req.doc_text else None
            )
            return BackendResult(
                verdict=Verdict.FIX,
                cause="both shapes (region + whole-doc), as a real LLM may reply",
                fix=ProposedFix(
                    region_id="symbols",
                    new_region_body=expected_region("symbols", req.surface),
                    new_doc_text=corrected,
                    rationale="returned both a region body and the full document",
                ),
            )

    result = _monitor(root, cfg, backend=_BothShapesBackend()).run(apply=True)
    assert all(h.result.verdict is Verdict.FIX for h in result.handled)
    assert result.remaining == ()  # single-pass heal despite both-shapes fixes
    assert _monitor(root, cfg).check().ok


def test_human_region_reported_but_never_healed(tmp_path: Path) -> None:
    """B-02 validable goal (end-to-end).

    A doc carries a `symbols` region declared `human` plus the fingerprint
    (machine-managed). A public-signature change would drift both. `check`
    REPORTS the human region with healable=False; `monitor --apply` leaves the
    human region BYTE-IDENTICAL while still refreshing the fingerprint; a second
    `--apply` is idempotent (no churn).
    """
    from code_doc_monitor.config import RegionMode
    from code_doc_monitor.manifest import parse_doc, regions, set_region

    root = tmp_path
    (root / "shared.py").write_text(_SHARED_V1, encoding="utf-8")
    (root / "docs").mkdir()
    spec = DocumentSpec(
        id="eng",
        path="docs/eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols",),
        region_modes={"symbols": RegionMode.HUMAN},
    )
    cfg = MonitorConfig(documents=(spec,))

    # Heal to a clean baseline FIRST (with the region still generated-shaped),
    # then a human takes ownership of the body.
    md_path = root / spec.path
    md_path.write_text(_DOC_STUB.format(title="Engineering guide"), encoding="utf-8")
    regenerate_regions(md_path, build_document_surface(spec, root))
    # A human rewrites the region body in their own words.
    text = md_path.read_text(encoding="utf-8")
    text, _ = set_region(
        text, "symbols", "Hand-written API notes a human owns.\nDo not touch."
    )
    md_path.write_text(text, encoding="utf-8")
    human_body = regions(parse_doc(md_path))["symbols"]

    # Re-baseline the fingerprint so only the code change drives drift.
    regenerate_regions(
        md_path,
        build_document_surface(spec, root),
        preserve=frozenset({"symbols"}),
    )
    assert regions(parse_doc(md_path))["symbols"] == human_body
    assert _monitor(root, cfg).check().ok

    # Now change the PUBLIC signature -> both the human region (content) and the
    # fingerprint would move.
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )

    # (a) check REPORTS the human region with healable=False.
    report = _monitor(root, cfg).check()
    region_drift = next(d for d in report.drifts if d.kind is DriftKind.REGION)
    assert region_drift.region_id == "symbols"
    assert region_drift.healable is False
    assert "human-owned" in region_drift.detail

    fp_before = parse_doc(md_path).meta["cdm"]["fingerprint"]

    # (b) monitor --apply leaves the human region byte-identical while still
    #     refreshing the fingerprint.
    _monitor(root, cfg).run(apply=True)
    after = parse_doc(md_path)
    assert regions(after)["symbols"] == human_body  # untouched
    assert after.meta["cdm"]["fingerprint"] != fp_before  # fingerprint refreshed

    # (c) a second --apply is idempotent: human region still untouched.
    body_now = md_path.read_bytes()
    _monitor(root, cfg).run(apply=True)
    assert md_path.read_bytes() == body_now
    assert regions(parse_doc(md_path))["symbols"] == human_body


def test_llm_seeded_fill_then_lock_three_phase(tmp_path: Path) -> None:
    """B-03 validable goal (end-to-end, three phases).

    (1) FILL: `monitor --apply` fills an `llm-seeded` region from the surface and
        stamps its per-region hash.
    (2) LOCK: after a human edits that region body, a subsequent `monitor --apply`
        LEAVES the region byte-identical (the stored hash diverges → locked) and
        is idempotent.
    (3) REPORT: once locked, a code move reports the region REGION healable=False
        (like a human region), while an UNLOCKED llm-seeded region still
        regenerates on a code move.
    """
    from code_doc_monitor.config import RegionMode
    from code_doc_monitor.manifest import (
        parse_doc,
        region_body_hash,
        regions,
        set_region,
        stored_region_hash,
    )

    root = tmp_path
    (root / "shared.py").write_text(_SHARED_V1, encoding="utf-8")
    (root / "docs").mkdir()
    md_path = root / "docs" / "eng.md"
    md_path.write_text(_DOC_STUB.format(title="Engineering guide"), encoding="utf-8")
    spec = DocumentSpec(
        id="eng",
        path="docs/eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols",),
        region_modes={"symbols": RegionMode.LLM_SEEDED},
    )
    cfg = MonitorConfig(documents=(spec,))

    # Phase 1 — FILL: the region stub drifts; monitor --apply fills + stamps it.
    _monitor(root, cfg).run(apply=True)
    assert _monitor(root, cfg).check().ok
    doc = parse_doc(md_path)
    filled = regions(doc)["symbols"]
    assert "compute" in filled  # actually filled from the surface
    assert stored_region_hash(doc, "symbols") == region_body_hash(filled)

    # Phase 2 — LOCK: a human edits the body; its hash now diverges from the stamp.
    text = md_path.read_text(encoding="utf-8")
    text, _ = set_region(
        text, "symbols", "A human rewrote the API notes.\nDo not regenerate."
    )
    md_path.write_text(text, encoding="utf-8")
    human_body = regions(parse_doc(md_path))["symbols"]
    # Re-baseline the fingerprint (preserve the locked body) so only a code move
    # drives further drift.
    from code_doc_monitor.extract import build_document_surface
    from code_doc_monitor.heal import regenerate_regions

    modes = {"symbols": RegionMode.LLM_SEEDED}
    regenerate_regions(
        md_path,
        build_document_surface(spec, root),
        preserve=frozenset({"symbols"}),
        modes=modes,
    )
    assert regions(parse_doc(md_path))["symbols"] == human_body
    assert _monitor(root, cfg).check().ok

    # A code move now: monitor --apply heals the HASH but LEAVES the locked body.
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )
    # Phase 3 — REPORT: check reports the locked region as healable=False.
    report = _monitor(root, cfg).check()
    region_drift = next(d for d in report.drifts if d.kind is DriftKind.REGION)
    assert region_drift.region_id == "symbols"
    assert region_drift.healable is False
    assert "human-owned" in region_drift.detail

    _monitor(root, cfg).run(apply=True)
    after = parse_doc(md_path)
    assert regions(after)["symbols"] == human_body  # locked body untouched

    # Idempotent: a second --apply writes nothing new.
    snapshot = md_path.read_bytes()
    _monitor(root, cfg).run(apply=True)
    assert md_path.read_bytes() == snapshot


def test_llm_seeded_unlocked_regenerates_on_code_move(tmp_path: Path) -> None:
    """An UNLOCKED llm-seeded region still regenerates on a code move (it is
    engine-owned until a human edits it) — the foil to the lock test."""
    from code_doc_monitor.config import RegionMode
    from code_doc_monitor.manifest import parse_doc, regions

    root = tmp_path
    (root / "shared.py").write_text(_SHARED_V1, encoding="utf-8")
    (root / "docs").mkdir()
    md_path = root / "docs" / "eng.md"
    md_path.write_text(_DOC_STUB.format(title="Engineering guide"), encoding="utf-8")
    spec = DocumentSpec(
        id="eng",
        path="docs/eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols",),
        region_modes={"symbols": RegionMode.LLM_SEEDED},
    )
    cfg = MonitorConfig(documents=(spec,))
    _monitor(root, cfg).run(apply=True)  # fill + stamp
    assert _monitor(root, cfg).check().ok

    # Code moves; the region was never human-edited, so the engine regenerates it.
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )
    result = _monitor(root, cfg).run(apply=True)
    assert result.remaining == ()  # fully self-healed (treated like generated)
    after = parse_doc(md_path)
    assert "c=0" in regions(after)["symbols"]


_FOUR_REGION_DOC = """\
# Mixed authorship guide

> One doc carrying all four authority modes.

<!-- CDM:BEGIN gen -->
PLACEHOLDER
<!-- CDM:END gen -->

<!-- CDM:BEGIN human -->
Hand-written prose a human owns.
<!-- CDM:END human -->

<!-- CDM:BEGIN seeded -->
PLACEHOLDER
<!-- CDM:END seeded -->

<!-- CDM:BEGIN llm -->
PLACEHOLDER
<!-- CDM:END llm -->
"""


def _four_region_setup(tmp_path: Path):
    """A single doc with one generated + one human + one llm-seeded + one llm
    region. Every region is renderable via a `symbols`-source template so the
    engine has a renderer for each (the interim `llm` rule needs a renderer to
    behave like `generated`)."""
    from code_doc_monitor.config import (
        RegionColumn,
        RegionMode,
        RegionTemplate,
    )

    root = tmp_path
    (root / "shared.py").write_text(_SHARED_V1, encoding="utf-8")
    (root / "docs").mkdir()
    md_path = root / "docs" / "mixed.md"
    md_path.write_text(_FOUR_REGION_DOC, encoding="utf-8")

    cols = (
        RegionColumn(header="symbol", field="name"),
        RegionColumn(header="signature", field="signature"),
    )
    templates = {
        rid: RegionTemplate(source="symbols", columns=cols)
        for rid in ("gen", "human", "seeded", "llm")
    }
    spec = DocumentSpec(
        id="mixed",
        path="docs/mixed.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("gen", "human", "seeded", "llm"),
        region_modes={
            "human": RegionMode.HUMAN,
            "seeded": RegionMode.LLM_SEEDED,
            "llm": RegionMode.LLM,
            # "gen" omitted -> generated (default)
        },
    )
    cfg = MonitorConfig(documents=(spec,), region_templates=templates)
    modes = dict(spec.region_modes)
    return root, md_path, spec, cfg, modes, templates


def test_mixed_authorship_four_regions_e2e(tmp_path: Path) -> None:
    """B-04 validable goal: four authority modes coexist in ONE doc.

    After a code change + `monitor --apply`:
      * `generated` regenerated from the surface;
      * `human` byte-identical + reported (advisory, healable=False);
      * `llm-seeded` fill-then-lock honored (engine fills, then a human edit
        locks it byte-identical);
      * `llm` WITH a renderer (templated) — mechanically rendered + kept in sync
        (B-06: a renderer-backed `llm` region keeps this behavior; only a
        NO-renderer `llm` region is backend-authored prose — see
        `test_pure_llm_no_renderer_authored_e2e`).
    """
    from code_doc_monitor.config import RegionMode
    from code_doc_monitor.manifest import (
        parse_doc,
        regions,
        set_region,
        stored_region_hash,
    )

    root, md_path, spec, cfg, modes, templates = _four_region_setup(tmp_path)

    # The `human` region is unstamped at baseline (its advisory is dormant until
    # the engine heals a code change and stamps the human body — B-02/B-03); the
    # `seeded`/`llm`/`gen` regions are engine-owned and stamped via `modes`.
    modes_engine = {k: v for k, v in modes.items() if k != "human"}

    # --- Phase 1: fill the engine-owned regions; preserve the human prose -----
    surface = build_document_surface(spec, root)
    regenerate_regions(
        md_path,
        surface,
        templates=templates,
        preserve=frozenset({"human"}),
        modes=modes_engine,
    )
    body0 = regions(parse_doc(md_path))
    # The engine fills the three engine-owned regions from the surface; the
    # `human` region is NEVER authored by the engine (its prose stays as written).
    for rid in ("gen", "seeded", "llm"):
        assert "compute" in body0[rid], rid  # actually rendered from the surface
    assert "Hand-written prose" in body0["human"]  # human prose preserved
    assert _monitor(root, cfg).check().ok

    # A human now takes ownership of the seeded region too (locks it: its body
    # hash diverges from the stamped value).
    text = md_path.read_text(encoding="utf-8")
    text, _ = set_region(text, "seeded", "A human curated the seeded section.")
    md_path.write_text(text, encoding="utf-8")
    # Re-baseline the fingerprint, preserving the two human-owned bodies (this is
    # what `monitor --apply` does at its boundary: a locked seeded region keeps
    # its stamp; the human region stays unstamped until a heal touches it).
    regenerate_regions(
        md_path,
        build_document_surface(spec, root),
        templates=templates,
        preserve=frozenset({"human"}),
        modes=modes_engine,
    )
    human_body = regions(parse_doc(md_path))["human"]
    seeded_body = regions(parse_doc(md_path))["seeded"]
    assert _monitor(root, cfg).check().ok  # locked seeded is in sync now

    # --- Phase 2: a public-signature code change -----------------------------
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )

    # `check` reports: generated + llm regions REGION healable=True; human +
    # locked-seeded REGION healable=False (advisory).
    report = _monitor(root, cfg).check()
    region_drifts = {
        d.region_id: d for d in report.drifts if d.kind is DriftKind.REGION
    }
    assert region_drifts["gen"].healable is True
    assert region_drifts["llm"].healable is True  # renderer-backed -> like generated
    assert region_drifts["human"].healable is False
    assert "human-owned" in region_drifts["human"].detail
    assert region_drifts["seeded"].healable is False  # locked (human-edited)
    assert "human-owned" in region_drifts["seeded"].detail

    # --- Phase 3: monitor --apply heals what it owns, preserves what it doesn't
    _monitor(root, cfg).run(apply=True)
    after = regions(parse_doc(md_path))
    assert "c=0" in after["gen"]  # generated regenerated
    assert "c=0" in after["llm"]  # renderer-backed llm == generated
    assert after["human"] == human_body  # byte-identical, untouched
    assert after["seeded"] == seeded_body  # locked seeded byte-identical

    # The human advisory persists across the fingerprint heal (B-02/B-03):
    # the human region still carries its stamped hash and re-fires until edited.
    persisted = _monitor(root, cfg).check()
    human_after = next(
        d
        for d in persisted.drifts
        if d.kind is DriftKind.REGION and d.region_id == "human"
    )
    assert human_after.healable is False

    # Idempotent: a second --apply changes nothing.
    snap = md_path.read_bytes()
    _monitor(root, cfg).run(apply=True)
    assert md_path.read_bytes() == snap

    # The renderer-backed `llm` region behaves EXACTLY like a generated one: its
    # mode is `llm` but it HAS a renderer and the engine owns it (not preserved,
    # no lock), so a fresh stamp was written and a re-render keeps it in sync.
    doc_after = parse_doc(md_path)
    assert spec.mode_for("llm") is RegionMode.LLM
    assert stored_region_hash(doc_after, "llm") is not None  # engine stamped it


def test_pure_llm_no_renderer_authored_e2e(tmp_path: Path) -> None:
    """B-06 validable goal: a `mode: llm` region with NO renderer is backend
    AUTHORED prose, end to end through `monitor --apply` (offline mock).

    Four goals in one doc:
      1. code surface moves -> the no-renderer `llm` region is RE-AUTHORED prose
         (not escalated UNHEALABLE);
      2. a second `--apply` is a clean no-op (idempotent, K7);
      3. a `human` region alongside stays byte-identical (B-02 unbroken, K5);
      4. with NO authoring path (a purely mechanical `regenerate_regions` heal,
         no backend), the region still SURFACES (loud, never silently stale, K8).
    """
    from code_doc_monitor.config import RegionMode
    from code_doc_monitor.manifest import (
        parse_doc,
        regions,
        render_doc,
        set_fingerprint,
        set_region,
    )

    root = tmp_path
    (root / "shared.py").write_text(_SHARED_V1, encoding="utf-8")
    (root / "docs").mkdir()
    md_path = root / "docs" / "prose.md"

    spec = DocumentSpec(
        id="prose",
        path="docs/prose.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="shared.py"),),
        region_keys=("symbols", "overview", "notes"),
        region_modes={"overview": RegionMode.LLM, "notes": RegionMode.HUMAN},
    )
    cfg = MonitorConfig(documents=(spec,))

    # Baseline: symbols rendered, overview authored prose, notes human prose.
    surface = build_document_surface(spec, root)
    human_body = "Hand-written human notes — do not touch."
    body = (
        "# Prose doc\n\n"
        "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n\n"
        "<!-- CDM:BEGIN overview -->\n<!-- CDM:END overview -->\n\n"
        "<!-- CDM:BEGIN notes -->\n<!-- CDM:END notes -->\n"
    )
    body, _ = set_region(body, "symbols", expected_region("symbols", surface))
    body, _ = set_region(body, "overview", "Initial authored prose about compute.")
    body, _ = set_region(body, "notes", human_body)
    md_path.write_text(
        render_doc(set_fingerprint({}, surface.surface_hash()), body),
        encoding="utf-8",
    )
    assert _monitor(root, cfg).check().ok  # clean baseline

    # --- Goal 1: code surface moves -> overview is a healable REGION (authored) --
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )
    report = _monitor(root, cfg).check()
    overview_drift = next(d for d in report.drifts if d.region_id == "overview")
    assert overview_drift.kind is DriftKind.REGION
    assert overview_drift.healable is True  # NOT UNHEALABLE

    result = _monitor(root, cfg).run(apply=True)
    overview_handled = next(
        h for h in result.handled if h.drift.region_id == "overview"
    )
    assert overview_handled.result.verdict is Verdict.FIX
    assert overview_handled.applied is True
    after = regions(parse_doc(md_path))
    # The prose was re-authored from the current surface (mentions `compute`).
    assert "compute" in after["overview"]
    assert "| symbol | kind |" not in after["overview"]  # prose, not a table
    # --- Goal 3: human region byte-identical (B-02) ---------------------------
    assert after["notes"] == human_body
    assert result.remaining == ()  # everything closed

    # --- Goal 2: a second --apply is a clean no-op (idempotent) ----------------
    snap = md_path.read_bytes()
    _monitor(root, cfg).run(apply=True)
    assert md_path.read_bytes() == snap
    assert _monitor(root, cfg).check().ok

    # --- Goal 4: NO authoring path applied -> the region still SURFACES (loud) --
    # Move the surface again, then run WITHOUT auto-apply (no authoring happens).
    # The no-renderer `llm` region must stay surfaced in `remaining` (a loud,
    # human-visible REGION drift), never silently dropped or hidden (K5/K8).
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0, d=1):"),
        encoding="utf-8",
    )
    noapply = _monitor(root, cfg).run(apply=False)
    assert any(
        d.region_id == "overview" and d.kind is DriftKind.REGION and d.healable
        for d in noapply.remaining
    )
    # It was recorded for a human (K5), not silently dropped.
    assert any(
        rec.drift_kind == DriftKind.REGION.value and "overview" in rec.drift_detail
        for rec in noapply.records
    )


def test_mixed_authorship_lint_modes_surface(tmp_path: Path) -> None:
    """B-05 (e2e): `lint`'s mode surface reports each region's mode + state."""
    from code_doc_monitor.blocks import known_region_ids
    from code_doc_monitor.config import RegionMode
    from code_doc_monitor.layout import config_region_states
    from code_doc_monitor.manifest import set_region

    root, md_path, spec, cfg, modes, templates = _four_region_setup(tmp_path)
    modes_engine = {k: v for k, v in modes.items() if k != "human"}
    regenerate_regions(
        md_path,
        build_document_surface(spec, root),
        templates=templates,
        preserve=frozenset({"human"}),
        modes=modes_engine,
    )
    # Lock the seeded region via a human edit + re-baseline.
    text = md_path.read_text(encoding="utf-8")
    text, _ = set_region(text, "seeded", "human curated")
    md_path.write_text(text, encoding="utf-8")
    regenerate_regions(
        md_path,
        build_document_surface(spec, root),
        templates=templates,
        preserve=frozenset({"human"}),
        modes=modes_engine,
    )

    states = {s.region_id: s for s in config_region_states(cfg, root)}
    assert states["gen"].mode is RegionMode.GENERATED
    assert states["gen"].advisory is False
    assert states["human"].mode is RegionMode.HUMAN
    assert states["human"].advisory is True
    assert states["seeded"].mode is RegionMode.LLM_SEEDED
    assert states["seeded"].locked is True
    assert states["seeded"].advisory is True
    assert states["llm"].mode is RegionMode.LLM
    assert states["llm"].has_renderer is True  # templated -> renderer exists
    assert states["llm"].advisory is False
    # sanity: known set includes all four templated ids
    assert {"gen", "human", "seeded", "llm"} <= known_region_ids(templates)


# ---------------------------------------------------------------------------
# CLI end-to-end
# ---------------------------------------------------------------------------

runner = CliRunner()


def _write_config(root: Path, cfg: MonitorConfig) -> Path:
    cfg_path = root / "cdmon.yaml"
    cfg_path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    return cfg_path


def test_cli_check_then_monitor_then_report(tmp_path: Path) -> None:
    root, cfg = _make_repo(tmp_path)
    cfg_path = _write_config(root, cfg)
    (root / "shared.py").write_text(
        _SHARED_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )
    # check -> drift -> exit 1
    r = runner.invoke(cli.app, ["check", "--config", str(cfg_path)])
    assert r.exit_code == 1, r.output
    # monitor --apply -> heals -> exit 0
    r = runner.invoke(cli.app, ["monitor", "--config", str(cfg_path), "--apply"])
    assert r.exit_code == 0, r.output
    # check is clean now
    r = runner.invoke(cli.app, ["check", "--config", str(cfg_path)])
    assert r.exit_code == 0, r.output
    # report shows the verdicts
    r = runner.invoke(cli.app, ["report", "--config", str(cfg_path)])
    assert r.exit_code == 0
    assert "FIX" in r.output


def test_cli_schema_emits_versioned_json(tmp_path: Path) -> None:
    out = tmp_path / "schema.json"
    r = runner.invoke(cli.app, ["schema", "--out", str(out)])
    assert r.exit_code == 0
    schema = json.loads(out.read_text(encoding="utf-8"))
    assert schema["type"] == "object"
    assert "schema_version" in schema["properties"]


def test_cli_bad_config_is_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Run from an isolated cwd so the CONFIG-V2 auto-detect (config/cdmon/ relative
    # to cwd, now present in THIS repo for dogfooding) cannot satisfy the missing
    # --config — the scenario under test is a genuinely-absent config (Z-01b).
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(cli.app, ["check", "--config", str(tmp_path / "nope.yaml")])
    assert r.exit_code != 0
    assert "Traceback" not in r.output


# --- CDM-08: end-to-end Document Layout Standard lifecycle --------------------


def test_layout_standard_end_to_end_with_html_twin(tmp_path: Path) -> None:
    """Scaffold -> lint clean -> html pairing (missing/derived/stale) -> clean."""
    from code_doc_monitor.layout import (
        embedded_md_hash,
        lint_config,
        md_source_hash,
        scaffold_doc,
    )
    from code_doc_monitor.manifest import parse_doc

    (tmp_path / "mod.py").write_text(
        '"""m."""\n\n\ndef api(x: int) -> int:\n    return x\n', encoding="utf-8"
    )
    spec = DocumentSpec(
        id="guide",
        path="docs/guide.md",
        audience=Audience.USER_GUIDE,
        code_refs=(CodeRef(path="mod.py"),),
        region_keys=("symbols",),
        html=True,
    )
    cfg = MonitorConfig(root=".", documents=(spec,))

    # Scaffold the .md — it is structurally conformant and content-clean...
    surface = build_document_surface(spec, tmp_path)
    md_path = tmp_path / "docs" / "guide.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(scaffold_doc(spec, surface), encoding="utf-8")

    # ...but the declared HTML twin is missing.
    issues = lint_config(cfg, tmp_path)
    assert [i.code.value for i in issues] == ["HTML_MISSING"]

    # Render a derived HTML twin embedding the current body hash -> clean.
    body = parse_doc(md_path).body
    html_path = tmp_path / "docs" / "guide.html"
    html_path.write_text(
        "<!-- generated; do not edit -->\n"
        f'<meta name="code-doc-md-sha256" content="{md_source_hash(body)}">\n'
        "<h1>guide</h1>\n",
        encoding="utf-8",
    )
    assert lint_config(cfg, tmp_path) == []

    # Edit the Markdown body (a reader-visible change) -> the HTML is now stale.
    md_path.write_text(
        md_path.read_text(encoding="utf-8").replace(
            "TODO: one-line purpose", "A real one-line purpose"
        ),
        encoding="utf-8",
    )
    stale = lint_config(cfg, tmp_path)
    assert [i.code.value for i in stale] == ["HTML_STALE"]

    # Re-deriving the HTML from the new body restores sync.
    new_body = parse_doc(md_path).body
    assert embedded_md_hash(html_path.read_text(encoding="utf-8")) != md_source_hash(
        new_body
    )
    html_path.write_text(
        f'<meta name="code-doc-md-sha256" content="{md_source_hash(new_body)}">\n',
        encoding="utf-8",
    )
    assert lint_config(cfg, tmp_path) == []


# --------------------------------------------------------------------------- #
# P-01: body-AST fingerprint tier, end to end (opt-in via config)              #
# --------------------------------------------------------------------------- #
def _make_repo_body_tier(tmp_path: Path) -> tuple[Path, MonitorConfig]:
    """Like _make_repo but the config opts INTO the body tier and the baseline
    fingerprints are stamped WITH it (one-shared-truth)."""
    root = tmp_path
    (root / "shared.py").write_text(_SHARED_V1, encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "user.md").write_text(
        _DOC_STUB.format(title="User guide"), encoding="utf-8"
    )
    (root / "docs" / "eng.md").write_text(
        _DOC_STUB.format(title="Engineering guide"), encoding="utf-8"
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
    cfg = MonitorConfig(documents=(user, eng), fingerprint_body_tier=True)
    for spec in (user, eng):
        regenerate_regions(
            root / spec.path, build_document_surface(spec, root), include_body=True
        )
    return root, cfg


def test_body_tier_off_ignores_comment_only_edit_e2e(tmp_path: Path) -> None:
    """Default (flag absent) → a comment-only edit never drifts (OFF == today)."""
    root, cfg = _make_repo(tmp_path)
    assert cfg.fingerprint_body_tier is False
    (root / "shared.py").write_text(
        _SHARED_V1.replace("return a + b", "return a + b  # add them"),
        encoding="utf-8",
    )
    assert _monitor(root, cfg).check().ok


def test_body_tier_on_eng_guide_body_change_drifts_and_heals_e2e(
    tmp_path: Path,
) -> None:
    root, cfg = _make_repo_body_tier(tmp_path)
    assert _monitor(root, cfg).check().ok  # clean baseline under the flag

    # A body-only change to the PUBLIC compute: signature + docstring unchanged.
    (root / "shared.py").write_text(
        _SHARED_V1.replace("return a + b", "return b + a"), encoding="utf-8"
    )
    report = _monitor(root, cfg).check()
    drifted = {d.doc_id for d in report.drifts}
    assert "eng" in drifted, "eng-guide must see the implementation change"
    assert "user" not in drifted, "user-guide must NOT see a body change (K3)"

    result = _monitor(root, cfg).run(apply=True)
    assert all(h.result.verdict is Verdict.FIX for h in result.handled)
    assert _monitor(root, cfg).check().ok  # re-healed to clean
    # Idempotent (K7): a second apply with no code change does nothing.
    again = _monitor(root, cfg).run(apply=True)
    assert again.handled == ()


def test_which_tier_moved_reported_and_stamped_e2e(tmp_path: Path) -> None:
    """P2 e2e: heal stamps per-tier digests; a body change reports tiers=('body',)."""
    from code_doc_monitor.manifest import parse_doc, stored_fingerprint_tiers

    root, cfg = _make_repo_body_tier(tmp_path)
    # The baseline heal (regenerate_regions, include_body) stamped the tiered
    # fingerprint into the eng doc's front matter (additive to cdm.fingerprint).
    tiers = stored_fingerprint_tiers(parse_doc(root / "docs" / "eng.md"))
    assert tiers is not None and tiers.body is not None

    # A pure body change to the PUBLIC compute → only the body tier moves.
    (root / "shared.py").write_text(
        _SHARED_V1.replace("return a + b", "return b + a"), encoding="utf-8"
    )
    report = _monitor(root, cfg).check()
    eng_hash = next(
        d for d in report.drifts if d.doc_id == "eng" and d.kind is DriftKind.HASH
    )
    assert eng_hash.drifted_tiers == ("body",)
    assert "body" in eng_hash.detail  # the human-readable message names the tier
