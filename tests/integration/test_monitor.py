"""CDM-06 — tests for the Monitor orchestration (offline, deterministic).

Features: FEAT-MONITOR-001, FEAT-MONITOR-002, FEAT-MONITOR-003, FEAT-MONITOR-004
Features: FEAT-MONITOR-005, FEAT-MONITOR-006, FEAT-MONITOR-007, FEAT-MONITOR-008
Features: FEAT-PR-009, FEAT-DRIFT-005, FEAT-RECORD-005, FEAT-RECORD-007
Features: FEAT-LEARN-001, FEAT-LEARN-003, FEAT-LEARN-006
Features: FEAT-MONITOR-010
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custodex.backends import MockBackend
from custodex.blocks import symbol_table
from custodex.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
    RegionMode,
)
from custodex.drift import Drift, DriftKind
from custodex.extract import build_document_surface
from custodex.heal import regenerate_regions
from custodex.monitor import Monitor
from custodex.reviewlog import read_all
from custodex.schema import Verdict
from custodex.sinks import FileSink, NullSink

FIXED_NOW = "2026-06-01T00:00:00+00:00"


def _now() -> str:
    return FIXED_NOW


CODE = '''\
"""A tiny module."""


def public_fn(x: int) -> int:
    """Double x."""
    return x * 2


class Widget:
    """A widget."""

    def spin(self) -> None:
        """Spin it."""
'''


def _write_doc(doc_path: Path, surface_body: str, fingerprint: str | None) -> None:
    """Write a doc with a (possibly stale) managed region + fingerprint."""
    fm = ""
    if fingerprint is not None:
        fm = f"---\ncdm:\n  fingerprint: {fingerprint}\n---\n"
    doc_path.write_text(
        f"{fm}# Guide\n\n"
        "<!-- CDM:BEGIN symbols -->\n"
        f"{surface_body}\n"
        "<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )


def _make_fixture(
    tmp_path: Path,
    *,
    audience: Audience = Audience.ENG_GUIDE,
    stale: bool = True,
) -> tuple[MonitorConfig, Path, Path, DocumentSpec]:
    """A code file + a doc whose region/fingerprint is stale -> REGION+HASH drift."""
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    doc_path = tmp_path / "guide.md"

    spec = DocumentSpec(
        id="guide",
        path="guide.md",
        audience=audience,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )
    surface = build_document_surface(spec, tmp_path)
    if stale:
        # Fingerprint matches the surface (no HASH drift), but the region body
        # is stale -> a single REGION drift the MockBackend can FIX cleanly.
        _write_doc(doc_path, "OUT OF DATE", fingerprint=surface.surface_hash())
    else:
        _write_doc(doc_path, symbol_table(surface), surface.surface_hash())

    config = MonitorConfig(root=".", documents=(spec,))
    return config, tmp_path, doc_path, spec


def test_check_is_pure_no_mutation(tmp_path: Path) -> None:
    config, cfg_dir, doc_path, _ = _make_fixture(tmp_path)
    before = doc_path.read_bytes()
    monitor = Monitor(config, cfg_dir, now=_now, sink=NullSink())

    report = monitor.check()

    assert not report.ok  # drift present
    assert doc_path.read_bytes() == before  # K1: check never mutates


def test_run_apply_fixes_and_records(tmp_path: Path) -> None:
    config, cfg_dir, doc_path, _ = _make_fixture(tmp_path)
    log_path = cfg_dir / ".cdmon" / "review-log.jsonl"
    monitor = Monitor(config, cfg_dir, now=_now, sink=NullSink())

    result = monitor.run(apply=True)

    # The region drift was FIXed and the re-check is clean.
    assert result.remaining == ()
    assert any(h.applied for h in result.handled)
    assert all(h.result.verdict == Verdict.FIX for h in result.handled)

    # A review record was appended to the default log and carries both
    # the original drift and the fix (K5).
    records = read_all(log_path)
    assert len(records) == len(result.records) >= 1
    rec = records[0]
    assert rec.doc_id == "guide"
    assert rec.verdict == Verdict.FIX
    assert rec.fix is not None
    assert rec.detected_at == FIXED_NOW
    assert rec.resolved_at == FIXED_NOW
    assert rec.config_snapshot["backend"] == "mock"


def test_run_attaches_ticket_to_each_record(tmp_path: Path) -> None:
    """T-01: every record carries a DriftTicket with a CDM-<id> ticket_id."""
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    monitor = Monitor(config, cfg_dir, now=_now, sink=NullSink())

    result = monitor.run(apply=False)

    assert result.records
    for rec in result.records:
        assert rec.ticket is not None
        assert rec.ticket.ticket_id == f"CDM-{rec.record_id}"
        assert rec.ticket.verdict == rec.verdict.value
        assert rec.ticket.doc_id == rec.doc_id


def test_record_id_deterministic_across_runs(tmp_path: Path) -> None:
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    log_path = cfg_dir / ".cdmon" / "review-log.jsonl"

    # First run records (no apply) -> drift persists, so a second run records
    # the same drift again with an identical record_id (same now + surface).
    Monitor(config, cfg_dir, now=_now, sink=NullSink()).run(apply=False)
    first = read_all(log_path)[0]

    Monitor(config, cfg_dir, now=_now, sink=NullSink()).run(apply=False)
    records = read_all(log_path)
    assert records[0].record_id == records[1].record_id == first.record_id


def test_run_no_apply_records_but_leaves_drift(tmp_path: Path) -> None:
    config, cfg_dir, doc_path, _ = _make_fixture(tmp_path)
    before = doc_path.read_bytes()
    monitor = Monitor(config, cfg_dir, now=_now, sink=NullSink())

    result = monitor.run(apply=False)

    assert result.records  # recorded (K5)
    assert result.remaining  # drift still present
    assert all(not h.applied for h in result.handled)
    assert doc_path.read_bytes() == before  # nothing applied


def test_run_emits_to_sink(tmp_path: Path) -> None:
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    central = cfg_dir / "central.jsonl"
    monitor = Monitor(config, cfg_dir, now=_now, sink=FileSink(central))

    monitor.run(apply=True)

    emitted = read_all(central)
    assert len(emitted) >= 1
    assert emitted[0].doc_id == "guide"


def test_run_apply_idempotent(tmp_path: Path) -> None:
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    log_path = cfg_dir / ".cdmon" / "review-log.jsonl"

    Monitor(config, cfg_dir, now=_now, sink=NullSink()).run(apply=True)
    after_first = read_all(log_path)

    # K7: a second run on a now-clean doc finds no drift and writes no record.
    result2 = Monitor(config, cfg_dir, now=_now, sink=NullSink()).run(apply=True)
    assert result2.handled == ()
    assert result2.records == ()
    assert result2.remaining == ()
    assert read_all(log_path) == after_first


def test_escalate_stays_in_remaining(tmp_path: Path) -> None:
    # An UNHEALABLE region (unknown id) -> MockBackend ESCALATEs -> stays.
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    doc_path = tmp_path / "guide.md"
    doc_path.write_text(
        "# Guide\n\n"
        "<!-- CDM:BEGIN prose -->\n"
        "hand-written prose\n"
        "<!-- CDM:END prose -->\n",
        encoding="utf-8",
    )
    spec = DocumentSpec(
        id="guide",
        path="guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("prose",),
    )
    config = MonitorConfig(root=".", documents=(spec,))
    monitor = Monitor(config, tmp_path, now=_now, sink=NullSink())

    result = monitor.run(apply=True)

    assert any(h.result.verdict == Verdict.ESCALATE for h in result.handled)
    assert any(d.kind == DriftKind.UNHEALABLE for d in result.remaining)


def test_default_backend_and_sink(tmp_path: Path) -> None:
    # No backend/sink injected -> defaults from config (mock + null sink).
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    monitor = Monitor(config, cfg_dir, now=_now)
    assert isinstance(monitor._backend, MockBackend)
    assert isinstance(monitor._sink, NullSink)
    result = monitor.run(apply=True)
    assert result.remaining == ()


def test_default_now_is_iso(tmp_path: Path) -> None:
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    monitor = Monitor(config, cfg_dir, sink=NullSink())
    # Default now() returns a non-empty ISO-ish timestamp string.
    stamp = monitor._now()
    assert isinstance(stamp, str)
    assert "T" in stamp


def test_apply_default_used_when_apply_none(tmp_path: Path) -> None:
    # apply_default False -> run() with apply=None records but does not apply.
    config, cfg_dir, doc_path, _ = _make_fixture(tmp_path)
    before = doc_path.read_bytes()
    result = Monitor(config, cfg_dir, now=_now, sink=NullSink()).run()
    assert result.remaining  # not applied
    assert doc_path.read_bytes() == before


def test_missing_doc_surface_builds(tmp_path: Path) -> None:
    # MISSING_DOC: surface still builds from code, doc_text="" path exercised.
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    spec = DocumentSpec(
        id="guide",
        path="missing.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )
    config = MonitorConfig(root=".", documents=(spec,))
    result = Monitor(config, tmp_path, now=_now, sink=NullSink()).run(apply=True)
    # The mock backend ESCALATEs a MISSING_DOC (no region to regenerate).
    assert result.handled
    assert any(d.kind == DriftKind.MISSING_DOC for d in result.remaining)


def test_custom_log_path(tmp_path: Path) -> None:
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    custom = tmp_path / "custom" / "log.jsonl"
    monitor = Monitor(config, cfg_dir, now=_now, sink=NullSink(), log_path=custom)
    monitor.run(apply=True)
    assert custom.is_file()
    assert read_all(custom)


def test_source_sha_defaults_none_on_every_record(tmp_path: Path) -> None:
    """C-05: with no source_sha passed, every record's source_sha is None (K6)."""
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    result = Monitor(config, cfg_dir, now=_now, sink=NullSink()).run(apply=False)
    assert result.records
    assert all(rec.source_sha is None for rec in result.records)


def test_source_sha_stamped_on_every_record(tmp_path: Path) -> None:
    """C-05: a passed source_sha is stamped onto every emitted record."""
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    monitor = Monitor(config, cfg_dir, now=_now, sink=NullSink(), source_sha="deadbeef")
    result = monitor.run(apply=True)
    assert result.records
    assert all(rec.source_sha == "deadbeef" for rec in result.records)


@pytest.fixture(autouse=True)
def _no_network() -> None:
    # Offline guarantee is structural (MockBackend default); this fixture is a
    # readable marker that these tests never touch the network (K4).
    return None


# ---------------------------------------------------------------------------
# D-04 — opt-in exemplar retrieval (default OFF = byte-identical to today)
# ---------------------------------------------------------------------------
class _RecordingBackend:
    """Wraps MockBackend, capturing the FixRequest it was handed (for exemplars)."""

    def __init__(self) -> None:
        self._inner = MockBackend()
        self.seen: list = []

    def propose(self, req):
        self.seen.append(req)
        return self._inner.propose(req)


def _seed_resolved_history(cfg_dir: Path, *, doc_id: str, surface_hash: str) -> None:
    """Append a RESOLVED past record (same doc + surface) so retrieval finds it."""
    from custodex.reviewlog import (
        DEFAULT_RESOLUTIONS_PATH,
        append,
        append_resolution,
    )
    from custodex.schema import (
        ProposedFix,
        Resolution,
        ResolutionRecord,
        ReviewRecord,
    )

    past = ReviewRecord(
        record_id="past1",
        doc_id=doc_id,
        doc_path=f"{doc_id}.md",
        audience=Audience.ENG_GUIDE,
        drift_kind="REGION",
        drift_detail="region 'symbols' is out of date",
        cause="surface moved",
        verdict=Verdict.FIX,
        fix=ProposedFix(
            region_id="symbols",
            new_region_body="| past |",
            new_doc_text=None,
            rationale="regenerated",
        ),
        surface_hash=surface_hash,
        backend_kind="mock",
        detected_at="2026-05-01T00:00:00Z",
        resolved_at="2026-05-01T00:00:01Z",
        config_snapshot={},
    )
    append(cfg_dir / ".cdmon" / "review-log.jsonl", past)
    append_resolution(
        cfg_dir / DEFAULT_RESOLUTIONS_PATH,
        ResolutionRecord(
            record_id="past1",
            resolution=Resolution.OVERRIDDEN,
            resolved_text="| the human body |",
            resolved_at="2026-05-02T00:00:00Z",
        ),
    )


def test_default_off_no_exemplars_and_no_resolution_read(tmp_path: Path) -> None:
    # Even with a seeded resolved history, default use_exemplars=False attaches NO
    # exemplars (byte-identical to pre-D-04 behavior).
    config, cfg_dir, _, spec = _make_fixture(tmp_path)
    surface = build_document_surface(spec, cfg_dir)
    _seed_resolved_history(cfg_dir, doc_id="guide", surface_hash=surface.surface_hash())
    backend = _RecordingBackend()
    Monitor(config, cfg_dir, now=_now, sink=NullSink(), backend=backend).run(
        apply=False
    )
    assert backend.seen
    assert all(req.exemplars == () for req in backend.seen)


def test_use_exemplars_attaches_ranked_exemplars(tmp_path: Path) -> None:
    config, cfg_dir, _, spec = _make_fixture(tmp_path)
    surface = build_document_surface(spec, cfg_dir)
    _seed_resolved_history(cfg_dir, doc_id="guide", surface_hash=surface.surface_hash())
    backend = _RecordingBackend()
    Monitor(
        config,
        cfg_dir,
        now=_now,
        sink=NullSink(),
        backend=backend,
        use_exemplars=True,
    ).run(apply=False)
    # The seeded resolved record (same doc + surface_hash) is retrieved as an
    # exemplar on the FixRequest handed to the backend.
    seen_with_ex = [req for req in backend.seen if req.exemplars]
    assert seen_with_ex
    ex = seen_with_ex[0].exemplars[0]
    assert ex.record.record_id == "past1"
    assert ex.resolution.resolved_text == "| the human body |"


def test_use_exemplars_empty_history_attaches_nothing(tmp_path: Path) -> None:
    # use_exemplars=True but NO resolved history -> no exemplars (graceful).
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    backend = _RecordingBackend()
    Monitor(
        config,
        cfg_dir,
        now=_now,
        sink=NullSink(),
        backend=backend,
        use_exemplars=True,
    ).run(apply=False)
    assert backend.seen
    assert all(req.exemplars == () for req in backend.seen)


# ---------------------------------------------------------------------------
# D-06 — opt-in promoted rules (default () = byte-identical; matched = 0 calls)
# ---------------------------------------------------------------------------
class _SpyBackend:
    """Counts `propose` calls; a matched-rule drift must NEVER reach it (D-06)."""

    def __init__(self) -> None:
        self._inner = MockBackend()
        self.calls = 0

    def propose(self, req):
        self.calls += 1
        return self._inner.propose(req)


def test_matched_rule_resolves_with_zero_backend_calls(tmp_path: Path) -> None:
    from custodex.promotion import PromotionRule

    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    log_path = cfg_dir / ".cdmon" / "review-log.jsonl"
    spy = _SpyBackend()
    # The fixture raises a single REGION drift for doc 'guide' (eng-guide).
    rule = PromotionRule(
        doc_id="guide",
        drift_kind=DriftKind.REGION.value,
        audience=Audience.ENG_GUIDE,
        verdict=Verdict.INVALIDATE,
    )
    result = Monitor(
        config, cfg_dir, now=_now, sink=NullSink(), backend=spy, rules=(rule,)
    ).run(apply=True)

    # The validable goal: the rule resolved the drift with ZERO backend calls.
    assert spy.calls == 0
    assert len(result.handled) == 1
    assert result.handled[0].result.verdict is Verdict.INVALIDATE
    assert result.handled[0].result.fix is None
    assert result.handled[0].applied is False  # INVALIDATE never applies a fix

    # Recorded for human audit (K5) with the rule verdict + a rule-sourced marker.
    records = read_all(log_path)
    assert len(records) == 1
    assert records[0].verdict is Verdict.INVALIDATE
    assert records[0].config_snapshot.get("resolved_by") == "rule"
    assert records[0].cause.lower().startswith("promoted rule")


def test_nonmatching_drift_still_hits_backend(tmp_path: Path) -> None:
    from custodex.promotion import PromotionRule

    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    spy = _SpyBackend()
    # A rule for a DIFFERENT shape -> the real drift does not match it.
    rule = PromotionRule(
        doc_id="other-doc",
        drift_kind=DriftKind.HASH.value,
        audience=Audience.USER_GUIDE,
        verdict=Verdict.INVALIDATE,
    )
    Monitor(config, cfg_dir, now=_now, sink=NullSink(), backend=spy, rules=(rule,)).run(
        apply=False
    )

    assert spy.calls == 1  # the non-matching drift went to the backend as usual


def test_default_no_rules_calls_backend_for_everything(tmp_path: Path) -> None:
    config, cfg_dir, _, _ = _make_fixture(tmp_path)
    spy = _SpyBackend()
    # Default rules=() -> additive: every drift still goes to the backend.
    Monitor(config, cfg_dir, now=_now, sink=NullSink(), backend=spy).run(apply=False)
    assert spy.calls == 1


# --------------------------------------------------------------------------- #
# P-02: a HASH record carries which surface tier(s) moved (drifted_tiers)       #
# --------------------------------------------------------------------------- #
def test_record_carries_drifted_tiers_for_body_change(tmp_path: Path) -> None:
    """A body-only change (flag ON) records drift_kind HASH with tiers ('body',)."""
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    spec = DocumentSpec(
        id="guide",
        path="guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )
    config = MonitorConfig(root=".", documents=(spec,), fingerprint_body_tier=True)
    # Scaffold a fully-synced doc (composite + per-tier digests stamped, flag ON).
    from custodex.layout import scaffold_doc

    surface = build_document_surface(spec, tmp_path)
    (tmp_path / "guide.md").write_text(
        scaffold_doc(spec, surface, include_body=True), encoding="utf-8"
    )
    assert Monitor(config, tmp_path, now=_now, sink=NullSink()).check().ok

    # A pure body change to a public function: signature/docstring unchanged.
    (tmp_path / "code.py").write_text(
        CODE.replace("return x * 2", "return x * 3"), encoding="utf-8"
    )
    result = Monitor(config, tmp_path, now=_now, sink=NullSink()).run(apply=False)
    hash_recs = [r for r in result.records if r.drift_kind == DriftKind.HASH.value]
    assert hash_recs, "expected a HASH record for the body-only change"
    assert hash_recs[0].drifted_tiers == ("body",)
    # P5: the same body-only change classifies as a COSMETIC breaking-change severity.
    assert hash_recs[0].change_severity == "cosmetic"


# --------------------------------------------------------------------------- #
# P-05: a HASH record carries the breaking-change severity (change_severity)     #
# Feature: FEAT-DRIFT-011                                                         #
# --------------------------------------------------------------------------- #
def test_record_carries_breaking_change_severity_for_signature(tmp_path: Path) -> None:
    """Changing a public function's signature records change_severity 'breaking'."""
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    spec = DocumentSpec(
        id="guide",
        path="guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )
    config = MonitorConfig(root=".", documents=(spec,))
    from custodex.layout import scaffold_doc

    surface = build_document_surface(spec, tmp_path)
    (tmp_path / "guide.md").write_text(
        scaffold_doc(spec, surface, include_body=False), encoding="utf-8"
    )
    assert Monitor(config, tmp_path, now=_now, sink=NullSink()).check().ok

    # Add a parameter to a public function (an IN-PLACE signature change — same
    # symbol identity) → the signature tier moves, no anchor delta → breaking.
    (tmp_path / "code.py").write_text(
        CODE.replace(
            "def public_fn(x: int) -> int:", "def public_fn(x: int, y: int) -> int:"
        ),
        encoding="utf-8",
    )
    result = Monitor(config, tmp_path, now=_now, sink=NullSink()).run(apply=False)
    hash_recs = [r for r in result.records if r.drift_kind == DriftKind.HASH.value]
    assert hash_recs, "expected a HASH record for the signature change"
    assert hash_recs[0].change_severity == "breaking"


# Feature: FEAT-DRIFT-012
def test_record_carries_breaking_for_masked_add_plus_inplace_signature(
    tmp_path: Path,
) -> None:
    """DIG-01 end-to-end: add a public symbol AND change a SURVIVING symbol's signature
    in ONE edit → the persisted HASH ReviewRecord reads 'breaking' (was 'additive').

    scaffold_doc stamps cdm.symbol_sigs, so the masked case is detectable through the
    monitor/record tier, not just at detect()."""
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    spec = DocumentSpec(
        id="guide",
        path="guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )
    config = MonitorConfig(root=".", documents=(spec,))
    from custodex.layout import scaffold_doc

    surface = build_document_surface(spec, tmp_path)
    (tmp_path / "guide.md").write_text(
        scaffold_doc(spec, surface, include_body=False), encoding="utf-8"
    )
    assert Monitor(config, tmp_path, now=_now, sink=NullSink()).check().ok

    # The masked edit: ADD a public function AND change public_fn's signature in place.
    edited = (
        CODE.replace(
            "def public_fn(x: int) -> int:", "def public_fn(x: int, y: int) -> int:"
        )
        + '\n\ndef brand_new(z: int) -> int:\n    """New."""\n    return z\n'
    )
    (tmp_path / "code.py").write_text(edited, encoding="utf-8")
    result = Monitor(config, tmp_path, now=_now, sink=NullSink()).run(apply=False)
    hash_recs = [r for r in result.records if r.drift_kind == DriftKind.HASH.value]
    assert hash_recs, "expected a HASH record for the masked edit"
    # Without per-symbol digests this would be 'additive' (masked); DIG-01 → 'breaking'.
    assert hash_recs[0].change_severity == "breaking"


# ---------------------------------------------------------------------------
# RTE-03c — `--tiered` restrains `--apply`: never write a document that
# needs human intent. Feature: FEAT-MONITOR-010
# ---------------------------------------------------------------------------

CODE_MOVED = '''\
"""A tiny module."""


def public_fn(x: int) -> int:
    """Double x, carefully."""
    return x * 2


class Widget:
    """A widget."""

    def spin(self) -> None:
        """Spin it."""
'''


def _mixed_fixture(
    tmp_path: Path, *, with_prose: bool
) -> tuple[MonitorConfig, Path, Path]:
    """A doc synced to the code, then the code moves — HASH + REGION drift.

    ``with_prose`` adds a no-renderer ``mode: llm`` region, which classifies
    DELEGATED and therefore HOLDS the whole document under `--tiered`. Without it
    every actionable drift is CODE_DERIVED and the document is mechanical.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    doc_path = tmp_path / "guide.md"
    region_keys = ("symbols", "overview") if with_prose else ("symbols",)
    spec = DocumentSpec(
        id="guide",
        path="guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=region_keys,
        region_modes={"overview": RegionMode.LLM} if with_prose else {},
    )
    prose = (
        "<!-- CDM:BEGIN overview -->\nProse a model authored.\n"
        "<!-- CDM:END overview -->\n\n"
        if with_prose
        else ""
    )
    doc_path.write_text(
        f"# Guide\n\n{prose}<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    # Stamp it the way a real run leaves it — the tiered digests and per-symbol
    # signatures included. A doc carrying only a COMPOSITE fingerprint classifies
    # UNKNOWN (and so NEEDS_INTENT) by design, which would mask what this fixture
    # is here to exercise.
    regenerate_regions(
        doc_path,
        build_document_surface(spec, tmp_path),
        modes={rid: spec.mode_for(rid) for rid in spec.region_keys},
    )
    # Now move the code: a DOCSTRING-only edit, so the symbol table is untouched
    # and the change grades COSMETIC -> CODE_DERIVED.
    (tmp_path / "code.py").write_text(CODE_MOVED, encoding="utf-8")
    return MonitorConfig(root=".", documents=(spec,)), tmp_path, doc_path


def _run(config, cfg_dir, **kw):
    return Monitor(config, cfg_dir, now=_now, sink=NullSink()).run(**kw)


def test_tiered_holds_a_document_that_needs_human_intent(tmp_path: Path) -> None:
    """The bug this epic exists to fix, reproduced and then closed.

    Applying a doc's mechanical HASH fix while its sibling prose region is
    ESCALATED destroys the ONLY staleness trigger that prose region has: heal
    stamps the fingerprint even when it skips the region, so the next `cdx check`
    is green FOREVER and the human is never asked again. `--tiered` refuses to
    write the document at all.
    """
    config, cfg_dir, doc_path = _mixed_fixture(tmp_path, with_prose=True)
    before = doc_path.read_bytes()

    result = _run(config, cfg_dir, apply=True, tiered=True)

    assert doc_path.read_bytes() == before  # nothing written
    assert not any(h.applied for h in result.handled)
    assert result.remaining  # the drift is STILL reported next cycle


def test_tiered_still_records_a_held_document_for_the_human(tmp_path: Path) -> None:
    """K5: holding the WRITE never means dropping the record.

    The human must still receive a ReviewRecord carrying BOTH the original drift
    and a proposed fix — that is the whole point of routing to them.
    """
    config, cfg_dir, _doc = _mixed_fixture(tmp_path, with_prose=True)

    result = _run(config, cfg_dir, apply=True, tiered=True)

    assert result.records
    assert any(r.fix is not None for r in result.records)
    assert len(result.handled) == len(result.records)  # the MCP zip lockstep


def test_tiered_still_writes_a_fully_mechanical_document(tmp_path: Path) -> None:
    """The foil: with no prose region every drift is CODE_DERIVED, so it closes."""
    config, cfg_dir, doc_path = _mixed_fixture(tmp_path, with_prose=False)
    before = doc_path.read_bytes()

    result = _run(config, cfg_dir, apply=True, tiered=True)

    assert doc_path.read_bytes() != before
    assert result.remaining == ()


def test_tiered_off_writes_the_held_document_exactly_as_today(tmp_path: Path) -> None:
    """DEFAULT OFF is byte-identical to today — this slice is opt-in (K6/K9)."""
    config, cfg_dir, doc_path = _mixed_fixture(tmp_path, with_prose=True)
    before = doc_path.read_bytes()

    _run(config, cfg_dir, apply=True)

    assert doc_path.read_bytes() != before


def test_tiered_defaults_to_the_config_knob(tmp_path: Path) -> None:
    """`tiered=None` resolves to `config.apply_tiered`, mirroring `apply`."""
    config, cfg_dir, doc_path = _mixed_fixture(tmp_path, with_prose=True)
    tiered_cfg = config.model_copy(update={"apply_tiered": True})
    before = doc_path.read_bytes()

    _run(tiered_cfg, cfg_dir, apply=True)

    assert doc_path.read_bytes() == before


def test_tiered_never_writes_without_apply(tmp_path: Path) -> None:
    """`--tiered` narrows `--apply`; it can never turn a dry run into a write."""
    config, cfg_dir, doc_path = _mixed_fixture(tmp_path, with_prose=False)
    before = doc_path.read_bytes()

    _run(config, cfg_dir, apply=False, tiered=True)

    assert doc_path.read_bytes() == before


# ---------------------------------------------------------------------------
# RTE-03c — the `apply_tiered` LEAK gate. Feature: FEAT-MONITOR-011
#
# `tiered=None` resolves to `config.apply_tiered`, mirroring `apply` — which
# means every call site that does not pass it inherits the repo's knob BY
# OMISSION. MCP-02 ratified the opposite rule in writing for `apply`
# (`mcp/tools.py`: "passed THROUGH EXPLICITLY so a repo's `apply_default: true`
# can NEVER be triggered implicitly by a remote agent"), and `server/app.py`
# loads the config of a CLONED, untrusted repo. So every non-`cdx monitor` site
# passes `tiered=False` explicitly, and each one is pinned here.
# ---------------------------------------------------------------------------


def _tiered_leak_fixture(tmp_path: Path) -> tuple[MonitorConfig, Path, Path]:
    """A HELD document (one DELEGATED drift) in a repo whose config says tiered."""
    config, cfg_dir, doc_path = _mixed_fixture(tmp_path, with_prose=True)
    return config.model_copy(update={"apply_tiered": True}), cfg_dir, doc_path


def test_sync_pr_does_not_inherit_apply_tiered_from_config(tmp_path: Path) -> None:
    """`cdx sync-pr` / `open-docs-pr` / the server docs-PR route / MCP sync_docs.

    All four reach `syncpr.sync_pr`, which heals in place with `apply=True`. A
    cloned remote's `apply_tiered` must not decide the server's authoring
    authority, so `sync_pr` defaults `tiered=False` and the choice is visible in
    the signature rather than implied by an omission.
    """
    from custodex.syncpr import sync_pr

    config, cfg_dir, doc_path = _tiered_leak_fixture(tmp_path)
    before = doc_path.read_bytes()

    sync_pr(Monitor(config, cfg_dir, now=_now, sink=NullSink()))

    assert doc_path.read_bytes() != before  # full-apply semantics, unchanged


def test_sync_pr_can_be_asked_for_tiered_explicitly(tmp_path: Path) -> None:
    """The foil: the parameter exists, so a caller CAN opt in deliberately."""
    from custodex.syncpr import sync_pr

    config, cfg_dir, doc_path = _tiered_leak_fixture(tmp_path)
    before = doc_path.read_bytes()

    sync_pr(Monitor(config, cfg_dir, now=_now, sink=NullSink()), tiered=True)

    assert doc_path.read_bytes() == before


def test_monitor_run_tiered_is_explicit_at_every_non_cli_call_site() -> None:
    """Static gate: no `Monitor.run(` outside `cli.monitor` may omit `tiered=`.

    A leak here is invisible at runtime — the call simply inherits the knob — so
    the guard is on the SOURCE. `cdx monitor` is the one site that resolves the
    config (that is what the knob is for); `syncpr.sync_pr` forwards its own
    explicit parameter.
    """
    import re

    root = Path(__file__).resolve().parents[2] / "custodex"
    allowed = {"cli.py", "syncpr.py"}
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if path.name == "monitor.py":
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\.run\(\s*apply=[^)]*\)", text):
            call = match.group(0)
            if "tiered=" in call:
                continue
            if path.name in allowed:
                continue
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.name}:{line} {call}")
    assert not offenders, f"Monitor.run without an explicit tiered=: {offenders}"


# ---------------------------------------------------------------------------
# RTE-03d — the ENGINE closes the mechanical path itself: ZERO backend calls,
# plus the closure alarm. Feature: FEAT-MONITOR-012, FEAT-RECORD-014
# ---------------------------------------------------------------------------


class ExplodingBackend:
    """Any call is a failure: the mechanical path must never consult a backend."""

    def propose(self, req):  # noqa: ANN001, ANN201
        raise AssertionError(
            f"backend consulted for a CODE_DERIVED drift: {req.drift.doc_id} "
            f"{req.drift.kind.value} [{req.drift.apply_tier.value}]"
        )


def _engine_run(config, cfg_dir, **kw):
    return Monitor(
        config, cfg_dir, backend=ExplodingBackend(), now=_now, sink=NullSink()
    ).run(**kw)


def test_a_mechanical_document_closes_with_zero_backend_calls(tmp_path: Path) -> None:
    """The cost claim, instrumented — not asserted.

    On the CODE_DERIVED path there is no model to be confident about: the bytes
    are the engine's own projection of the surface, produced by the same functions
    heal calls. So the backend is not consulted at all, and a backend that raises
    on any call proves it.
    """
    config, cfg_dir, doc_path = _mixed_fixture(tmp_path, with_prose=False)
    before = doc_path.read_bytes()

    result = _engine_run(config, cfg_dir, apply=True, tiered=True)

    assert doc_path.read_bytes() != before
    assert result.remaining == ()
    assert all(h.result.verdict is Verdict.FIX for h in result.handled)


def test_engine_closure_is_recorded_as_engine_sourced(tmp_path: Path) -> None:
    """K5: an unattended close is still fully auditable, and says who closed it."""
    config, cfg_dir, _doc = _mixed_fixture(tmp_path, with_prose=False)

    result = _engine_run(config, cfg_dir, apply=True, tiered=True)

    assert result.records
    for rec in result.records:
        assert rec.verdict is Verdict.FIX
        assert rec.fix is not None  # BOTH the drift and the proposed fix (K5)
        assert rec.config_snapshot["resolved_by"] == "engine"  # mirrors D-06 "rule"


def test_engine_fix_keeps_the_backend_fix_SHAPE(tmp_path: Path) -> None:
    """A REGION close stays region-scoped; only a HASH close is whole-doc.

    Collapsing both into one whole-doc `render_corrected` would make a REGION close
    rewrite front-matter it never touches today — `fingerprint_tiers` and
    `symbol_sigs` — which on a legacy composite-only doc silently ADDS the digests
    `classify_change_severity` needs to move a FUTURE HASH drift from UNKNOWN
    (NEEDS_INTENT) to COSMETIC (CODE_DERIVED). The unattended write would widen
    what it may next write unattended.
    """
    config, cfg_dir, doc_path = _mixed_fixture(tmp_path, with_prose=False)
    # Make the symbol table stale too, so BOTH shapes appear in one run.
    text = doc_path.read_text(encoding="utf-8").replace("| public_fn", "| STALE_fn")
    doc_path.write_text(text, encoding="utf-8")

    result = _engine_run(config, cfg_dir, apply=False, tiered=True)

    by_kind = {h.drift.kind: h.result.fix for h in result.handled}
    assert by_kind[DriftKind.REGION].region_id == "symbols"
    assert by_kind[DriftKind.REGION].new_doc_text is None
    assert by_kind[DriftKind.HASH].region_id is None
    assert by_kind[DriftKind.HASH].new_doc_text is not None


def test_engine_close_is_idempotent(tmp_path: Path) -> None:
    """K7: a second tiered run on the closed doc writes nothing and records nothing."""
    config, cfg_dir, doc_path = _mixed_fixture(tmp_path, with_prose=False)
    _engine_run(config, cfg_dir, apply=True, tiered=True)
    after_first = doc_path.read_bytes()

    second = _engine_run(config, cfg_dir, apply=True, tiered=True)

    assert doc_path.read_bytes() == after_first
    assert second.records == () and second.closures == ()


def test_promoted_rule_still_wins_over_the_engine(tmp_path: Path) -> None:
    """D-06 keeps its precedence: a learned human verdict is never overwritten.

    A promoted rule is a verdict humans reached >=K times. A CODE_DERIVED HASH
    drift is exactly the shape a repo would promote an INVALIDATE rule for, so if
    the engine branch sat above `rule_for`, that learned verdict would silently
    become an engine WRITE — the learning loop inverted.
    """
    from custodex.promotion import PromotionRule

    config, cfg_dir, doc_path = _mixed_fixture(tmp_path, with_prose=False)
    rule = PromotionRule(
        doc_id="guide",
        drift_kind=DriftKind.HASH.value,
        audience=Audience.ENG_GUIDE,
        verdict=Verdict.INVALIDATE,
    )
    monitor = Monitor(
        config,
        cfg_dir,
        backend=ExplodingBackend(),
        now=_now,
        sink=NullSink(),
        rules=(rule,),
    )

    result = monitor.run(apply=True, tiered=True)

    hash_records = [r for r in result.records if r.drift_kind == DriftKind.HASH.value]
    assert hash_records
    assert all(r.verdict is Verdict.INVALIDATE for r in hash_records)
    assert all(r.config_snapshot["resolved_by"] == "rule" for r in hash_records)


# --- the ClosureRecord alarm ------------------------------------------------


def test_closure_record_describes_a_converged_close(tmp_path: Path) -> None:
    config, cfg_dir, _doc = _mixed_fixture(tmp_path, with_prose=False)

    result = _engine_run(config, cfg_dir, apply=True, tiered=True)

    assert len(result.closures) == 1
    closure = result.closures[0]
    assert closure.doc_id == "guide"
    assert closure.attempted and closure.wrote and closure.verified
    assert closure.drift_kinds == ("HASH",)
    assert closure.evidence == ("severity:cosmetic", "surface-refresh")
    assert closure.record_ids  # joinable to the review log


def test_closure_is_a_preview_when_apply_was_never_requested(tmp_path: Path) -> None:
    """`attempted=False` — the alarm must never report a write that never ran."""
    config, cfg_dir, _doc = _mixed_fixture(tmp_path, with_prose=False)

    result = _engine_run(config, cfg_dir, apply=False, tiered=True)

    assert len(result.closures) == 1
    assert not result.closures[0].attempted
    assert not result.closures[0].wrote
    assert not result.closures[0].verified


def test_closure_alarms_when_the_write_boundary_declines(
    tmp_path: Path, monkeypatch
) -> None:
    """`wrote=False, verified=False` is the case gating on `wrote` would HIDE.

    `apply_fix` returns False for an ATTEMPTED write it declined — a preserved id,
    or a B-03 locked region. That is precisely "routing promised mechanical closure
    and the write boundary silently refused", so the alarm gates on `attempted`,
    never on `wrote`.
    """
    import custodex.monitor as monitor_mod

    config, cfg_dir, _doc = _mixed_fixture(tmp_path, with_prose=False)
    monkeypatch.setattr(monitor_mod, "apply_fix", lambda *a, **k: False)

    result = _engine_run(config, cfg_dir, apply=True, tiered=True)

    closure = result.closures[0]
    assert closure.attempted and not closure.wrote and not closure.verified


def test_no_closure_for_a_document_that_was_held(tmp_path: Path) -> None:
    """A held document is not a closure — it is an escalation."""
    config, cfg_dir, _doc = _mixed_fixture(tmp_path, with_prose=True)

    result = Monitor(config, cfg_dir, now=_now, sink=NullSink()).run(
        apply=True, tiered=True
    )

    assert result.closures == ()


def test_closures_are_absent_when_tiered_is_off(tmp_path: Path) -> None:
    """Default OFF stays byte-identical to today, closures included (K6)."""
    config, cfg_dir, _doc = _mixed_fixture(tmp_path, with_prose=False)

    result = Monitor(config, cfg_dir, now=_now, sink=NullSink()).run(apply=True)

    assert result.closures == ()


def test_closures_are_sorted_by_doc_id(tmp_path: Path) -> None:
    """K10: nothing iterates a frozenset into the result."""
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    specs = []
    for doc_id in ("zulu", "alpha", "mike"):
        spec = DocumentSpec(
            id=doc_id,
            path=f"{doc_id}.md",
            audience=Audience.ENG_GUIDE,
            code_refs=(CodeRef(path="code.py"),),
            region_keys=("symbols",),
        )
        (tmp_path / spec.path).write_text(
            "# D\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
            encoding="utf-8",
        )
        regenerate_regions(
            tmp_path / spec.path,
            build_document_surface(spec, tmp_path),
            modes={"symbols": RegionMode.GENERATED},
        )
        specs.append(spec)
    (tmp_path / "code.py").write_text(CODE_MOVED, encoding="utf-8")
    config = MonitorConfig(root=".", documents=tuple(specs))

    result = _engine_run(config, tmp_path, apply=True, tiered=True)

    assert [c.doc_id for c in result.closures] == ["alpha", "mike", "zulu"]


def test_engine_renders_an_index_region_with_the_INDEX_aware_layer(
    tmp_path: Path,
) -> None:
    """[RTE-03d] The engine's close uses the SAME selector `detect` grades against.

    An `index` region is a table over the config's OTHER documents, so it is not a
    function of this document's surface. `expected_region` declines it (RTE-03a);
    the engine must branch to `render_index` exactly as `drift.detect` does. Drop
    that branch and the unattended close writes a header-only table over a live
    landing page — silent data loss, on the one path with no human watching.
    """
    from custodex.config import RegionColumn, RegionTemplate
    from custodex.index import render_index

    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    sibling = DocumentSpec(
        id="guide",
        path="guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )
    index_spec = DocumentSpec(
        id="api-index",
        path="index.md",
        audience=Audience.ENG_GUIDE,
        region_keys=("api-index",),
    )
    template = RegionTemplate(
        source="index",
        kind="eng-guide",
        columns=(
            RegionColumn(header="Document", field="title"),
            RegionColumn(header="What it covers", field="summary"),
        ),
    )
    config = MonitorConfig(
        root=".",
        documents=(index_spec, sibling),
        region_templates={"api-index": template},
    )
    (tmp_path / "guide.md").write_text(
        "# Guide\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    (tmp_path / "index.md").write_text(
        "# Index\n\n<!-- CDM:BEGIN api-index -->\n<!-- CDM:END api-index -->\n",
        encoding="utf-8",
    )
    # Stamp both docs the way a real run leaves them, THEN break only the index
    # body — so the sole drift is the REGION the engine must render index-aware.
    for spec in (sibling, index_spec):
        regenerate_regions(
            tmp_path / spec.path,
            build_document_surface(spec, tmp_path),
            config.region_templates,
            modes={rid: spec.mode_for(rid) for rid in spec.region_keys},
        )
    from custodex.manifest import set_region

    stale, _ = set_region(
        (tmp_path / "index.md").read_text(encoding="utf-8"), "api-index", "STALE"
    )
    (tmp_path / "index.md").write_text(stale, encoding="utf-8")

    result = _engine_run(config, tmp_path, apply=True, tiered=True)

    from custodex.manifest import parse_doc, regions

    body = regions(parse_doc(tmp_path / "index.md"))["api-index"]
    assert body == render_index(template, index_spec, config, tmp_path)
    assert "| guide |" in body or "guide" in body  # the sibling row survived
    assert any(c.doc_id == "api-index" and c.verified for c in result.closures)


def test_engine_escalates_when_it_cannot_render_what_routing_promised(
    tmp_path: Path, monkeypatch
) -> None:
    """[RTE-03d] The router and the renderer disagreeing is LOUD, never a silent FIX.

    A `FIX` verdict carrying no fix would look handled in the log while nothing
    was written — the exact silence the alarm exists to break (K8).
    """
    # A REGION-only drift (the fingerprint already matches), so nothing else can
    # close the document behind the failing renderer.
    config, cfg_dir, _doc, _spec = _make_fixture(tmp_path)
    monkeypatch.setattr(Monitor, "_region_body", lambda *a, **k: None)

    result = _engine_run(config, cfg_dir, apply=True, tiered=True)

    region = next(h for h in result.handled if h.drift.kind is DriftKind.REGION)
    assert region.result.verdict is Verdict.ESCALATE
    assert region.result.fix is None
    assert "router and the renderer disagree" in region.result.cause
    assert result.closures[0].attempted and not result.closures[0].verified


def test_closure_facets_are_sorted_not_encounter_ordered(tmp_path: Path) -> None:
    """[RTE-03d] K10: `drift_kinds` and `evidence` are sorted, not in arrival order.

    Exercised directly on the fold with facts supplied in REVERSE-sorted encounter
    order, so any implementation that preserves arrival order (the mutation a
    refactor actually introduces) is killed deterministically — a fixture with one
    kind and one evidence string cannot defend sortedness at all.
    """
    from custodex.monitor import ClosureRecord

    facts = [
        (
            Drift(
                kind=DriftKind.REGION,
                doc_id="d",
                doc_path="d.md",
                detail="x",
                audience=Audience.ENG_GUIDE,
                healable=True,
                tier_evidence=("region:symbols", "mechanical-render"),
            ),
            "rec1",
            True,
            True,
        ),
        (
            Drift(
                kind=DriftKind.HASH,
                doc_id="d",
                doc_path="d.md",
                detail="x",
                audience=Audience.ENG_GUIDE,
                healable=True,
                tier_evidence=("surface-refresh", "severity:cosmetic"),
            ),
            "rec1",
            True,
            True,
        ),
    ]

    out = Monitor._closures({"d": facts}, ())

    assert isinstance(out[0], ClosureRecord)
    assert out[0].drift_kinds == ("HASH", "REGION")  # not ("REGION", "HASH")
    assert out[0].evidence == (
        "mechanical-render",
        "region:symbols",
        "severity:cosmetic",
        "surface-refresh",
    )


def test_closure_names_every_record_under_a_MOVING_clock(tmp_path: Path) -> None:
    """[RTE-03d] `record_ids` is a tuple because of the CLOCK, not for symmetry.

    `new_record_id` hashes `(doc_id, surface_hash, detected_at)`, so under a FIXED
    injected clock N drifts on one document collapse to ONE id and a singular field
    looks correct. Under the production clock each `_record_for` stamps a different
    instant, the ids are DISTINCT, and a singular field would silently name only
    the first — losing the audit trail for every other drift on the document. This
    injects a MOVING clock, which is what production actually looks like.
    """
    from custodex.manifest import set_region

    config, cfg_dir, doc_path = _mixed_fixture(tmp_path, with_prose=False)
    stale, _ = set_region(doc_path.read_text(encoding="utf-8"), "symbols", "STALE")
    doc_path.write_text(stale, encoding="utf-8")  # a HASH *and* a REGION drift
    ticks = iter(f"2026-06-01T00:00:0{i}+00:00" for i in range(9))

    result = Monitor(
        config,
        cfg_dir,
        backend=ExplodingBackend(),
        now=lambda: next(ticks),
        sink=NullSink(),
    ).run(apply=True, tiered=True)

    written = {rec.record_id for rec in result.records}
    assert len(written) == 2, "the moving clock must produce DISTINCT record ids"
    closure = result.closures[0]
    assert set(closure.record_ids) == written  # every record is named
    assert closure.record_ids == tuple(sorted(closure.record_ids))  # K10


def test_tiered_replaces_the_authority_it_does_not_merely_narrow_it(
    tmp_path: Path,
) -> None:
    """[RTE-03c ⟨R-CORRECTED⟩] `--tiered` is NOT a subset of `--apply`.

    An earlier draft of this epic claimed it was, in six places. On the mechanical
    path no backend is consulted AT ALL, so a backend that would have DECLINED never
    gets the chance: `--apply` writes nothing, `--apply --tiered` writes. That is the
    epic's thesis working as designed — on the code-derived path there is no model
    judgement to defer to — but it is a real, adopter-visible semantic for anyone
    whose backend is deliberately conservative, so it is pinned rather than claimed
    away. On every document that is NOT mechanical, tiered IS strictly narrower.
    """

    class Declining:
        """A backend that declines — both shapes a real LLM actually returns."""

        def __init__(self, verdict: Verdict) -> None:
            self.verdict = verdict

        def propose(self, req):  # noqa: ANN001, ANN201
            from custodex.backends import BackendResult

            return BackendResult(verdict=self.verdict, cause="declined", fix=None)

    # BOTH declining verdicts, because they are different real cases: INVALIDATE is
    # "this change does not affect this audience" (K3), ESCALATE is "a human must
    # decide". Neither can hold the write once the engine stops asking.
    for verdict in (Verdict.INVALIDATE, Verdict.ESCALATE):
        outcomes = {}
        for tiered in (False, True):
            case = tmp_path / f"{verdict.value}-{int(tiered)}"
            config, cfg_dir, doc_path = _mixed_fixture(case, with_prose=False)
            before = doc_path.read_bytes()
            result = Monitor(
                config, cfg_dir, backend=Declining(verdict), now=_now, sink=NullSink()
            ).run(apply=True, tiered=tiered)
            outcomes[tiered] = (doc_path.read_bytes() != before, bool(result.remaining))

        assert outcomes[False] == (False, True), verdict  # declined; drift remains
        assert outcomes[True] == (True, False), verdict  # engine closed it unasked


def test_a_rule_held_region_is_not_overwritten_by_a_sibling_HASH_close(
    tmp_path: Path,
) -> None:
    """[RTE-03d ⟨R-CORRECTED⟩] A promoted rule holds the WHOLE document.

    An earlier draft argued a rule match need not remove the document from
    `mechanical_docs`, because a region-scoped close does not stamp
    `cdm.fingerprint`. That reasoning covered only the REGION direction. The HASH
    close is WHOLE-DOC (`render_corrected`), and it regenerates every known region —
    including the one the rule just held. Reproduced: the rule INVALIDATEd the
    REGION drift and the engine's sibling HASH write overwrote the body anyway,
    inverting the learning loop silently.
    """
    from custodex.promotion import PromotionRule

    config, cfg_dir, doc_path = _mixed_fixture(tmp_path, with_prose=False)
    from custodex.manifest import set_region

    held, _ = set_region(
        doc_path.read_text(encoding="utf-8"), "symbols", "HELD BY A PROMOTED RULE"
    )
    doc_path.write_text(held, encoding="utf-8")
    rule = PromotionRule(
        doc_id="guide",
        drift_kind=DriftKind.REGION.value,
        audience=Audience.ENG_GUIDE,
        verdict=Verdict.INVALIDATE,
    )

    # The default (mock) backend: the point is that NOTHING is written, not that
    # no backend was called — a held document legitimately consults one (K5).
    result = Monitor(config, cfg_dir, now=_now, sink=NullSink(), rules=(rule,)).run(
        apply=True, tiered=True
    )

    body = doc_path.read_text(encoding="utf-8")
    assert "HELD BY A PROMOTED RULE" in body  # the learned verdict stands
    assert result.closures == ()  # and the document was never a closure


def test_two_specs_on_one_FILE_hold_each_other(tmp_path: Path) -> None:
    """[RTE-03b ⟨R-CORRECTED⟩] The fold keys on doc_id; the WRITE keys on doc_path.

    `MonitorConfig` accepts two documents that share a `path`. If one is mechanical
    and the other needs human intent, closing the first REWRITES the second's file
    and stamps its fingerprint — blessing the held document, with `cdx check` green
    and no alarm. So a blocked drift blocks every document sharing its FILE, not
    only its id.
    """
    (tmp_path / "code.py").write_text(CODE, encoding="utf-8")
    doc_path = tmp_path / "shared.md"
    mech = DocumentSpec(
        id="mech",
        path="shared.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("symbols",),
    )
    held = DocumentSpec(
        id="held",
        path="shared.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="code.py"),),
        region_keys=("prose",),  # no renderer -> UNHEALABLE -> NEEDS_INTENT
    )
    doc_path.write_text(
        "# S\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n\n"
        "<!-- CDM:BEGIN prose -->\nhand-written\n<!-- CDM:END prose -->\n",
        encoding="utf-8",
    )
    regenerate_regions(
        doc_path,
        build_document_surface(mech, tmp_path),
        modes={"symbols": RegionMode.GENERATED},
    )
    # Move the code so `mech` genuinely has a CODE_DERIVED drift of its own —
    # otherwise it is absent from every set and the test passes vacuously.
    (tmp_path / "code.py").write_text(CODE_MOVED, encoding="utf-8")
    config = MonitorConfig(root=".", documents=(mech, held))
    before = doc_path.read_bytes()
    from custodex.drift import detect, mechanical_docs

    report = detect(config, tmp_path)
    assert any(
        d.doc_id == "mech" and d.apply_tier.value == "code-derived"
        for d in report.drifts
    ), "the fixture must give `mech` a real mechanical drift"
    assert mechanical_docs(report) == frozenset()  # held by its FILE-mate

    result = Monitor(config, tmp_path, now=_now, sink=NullSink()).run(
        apply=True, tiered=True
    )

    assert doc_path.read_bytes() == before  # neither document was written
    assert result.closures == ()


def test_local_sync_pr_honours_the_repo_s_own_apply_tiered(tmp_path: Path) -> None:
    """[RTE-03c ⟨R-CORRECTED⟩] Forcing `tiered=False` everywhere went too far.

    The leak that had to be closed was CONFIG arriving by OMISSION on paths where
    the config is not the operator's — a remote agent's tool call, and the server's
    docs-PR route on a CLONED repo. `cdx sync-pr` / `cdx open-docs-pr` run against
    the operator's OWN checkout, so refusing to honour their own `apply_tiered`
    re-opened the exact permanent-staleness bug RTE-03 exists to fix on the docs-PR
    path. The distinction is whose config it is, not which function is called.
    """
    from custodex.syncpr import sync_pr

    config, cfg_dir, doc_path = _mixed_fixture(tmp_path, with_prose=True)
    tiered_cfg = config.model_copy(update={"apply_tiered": True})
    before = doc_path.read_bytes()

    # What `cli.sync_pr_cmd` now does: pass the repo's own knob EXPLICITLY.
    sync_pr(
        Monitor(tiered_cfg, cfg_dir, now=_now, sink=NullSink()),
        tiered=tiered_cfg.apply_tiered,
    )

    assert doc_path.read_bytes() == before  # the held document is protected
