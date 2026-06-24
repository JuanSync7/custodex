"""Tests for custodex.promotion (D-05/D-06 — pure detector + rule app).

`detect_promotions` mines the review log joined to the resolutions log for a
GENERALIZABLE shape `(doc_id, drift_kind, audience)` whose RESOLVED records >= K
ALL share ONE DECISION resolution (`invalidated`/`rejected`); `overridden` is
excluded (human prose). Deterministic (K10). `rule_for`/`rule_from_candidate`
map a candidate to a `PromotionRule` the Monitor applies WITHOUT a backend call
(D-06: zero backend calls on a matched drift). TDD (K9).

Features: FEAT-LEARN-004, FEAT-LEARN-005, FEAT-LEARN-006
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from custodex.config import Audience
from custodex.drift import Drift, DriftKind
from custodex.promotion import (
    PromotionCandidate,
    PromotionRule,
    detect_promotions,
    rule_for,
    rule_from_candidate,
)
from custodex.schema import (
    Resolution,
    ResolutionRecord,
    ReviewRecord,
    Verdict,
)


def _record(
    record_id: str,
    *,
    doc_id: str = "user-guide",
    audience: Audience = Audience.USER_GUIDE,
    drift_kind: str = "HASH",
    surface_hash: str = "h0",
    verdict: Verdict = Verdict.INVALIDATE,
) -> ReviewRecord:
    return ReviewRecord(
        record_id=record_id,
        doc_id=doc_id,
        doc_path=f"docs/{doc_id}.md",
        audience=audience,
        drift_kind=drift_kind,
        drift_detail="docstring changed",
        cause="changed",
        verdict=verdict,
        fix=None,
        surface_hash=surface_hash,
        backend_kind="mock",
        detected_at="2026-06-01T00:00:00Z",
        resolved_at="2026-06-01T00:00:01Z",
        config_snapshot={},
    )


def _resolution(
    record_id: str,
    *,
    resolution: Resolution = Resolution.INVALIDATED,
    resolved_text: str | None = None,
    resolved_at: str = "2026-06-05T00:00:00Z",
) -> ResolutionRecord:
    return ResolutionRecord(
        record_id=record_id,
        resolution=resolution,
        resolved_text=resolved_text,
        resolved_at=resolved_at,
    )


# --- D-05: detect_promotions ------------------------------------------------


def test_three_unanimous_invalidations_one_candidate() -> None:
    # 3 resolved records of one shape, all invalidated -> 1 candidate (count=3),
    # even with DIFFERENT surface_hash (proves the shape generalizes, NOT exact state).
    records = [
        _record("r1", surface_hash="h1"),
        _record("r2", surface_hash="h2"),
        _record("r3", surface_hash="h3"),
    ]
    resolutions = [
        _resolution("r1"),
        _resolution("r2"),
        _resolution("r3"),
    ]
    candidates = detect_promotions(records, resolutions)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.doc_id == "user-guide"
    assert c.drift_kind == "HASH"
    assert c.audience is Audience.USER_GUIDE
    assert c.resolution is Resolution.INVALIDATED
    assert c.count == 3


def test_below_min_count_no_candidate() -> None:
    # Only 2 resolved records of the shape -> below default min_count=3 -> none.
    records = [_record("r1"), _record("r2")]
    resolutions = [_resolution("r1"), _resolution("r2")]
    assert detect_promotions(records, resolutions) == []


def test_mixed_resolutions_no_candidate() -> None:
    # 3 resolved records but NOT unanimous -> not promotable.
    records = [_record("r1"), _record("r2"), _record("r3")]
    resolutions = [
        _resolution("r1", resolution=Resolution.INVALIDATED),
        _resolution("r2", resolution=Resolution.REJECTED),
        _resolution("r3", resolution=Resolution.INVALIDATED),
    ]
    assert detect_promotions(records, resolutions) == []


def test_overridden_excluded() -> None:
    # `overridden` carries human prose -> never auto-promoted, even if unanimous >=K.
    records = [_record("r1"), _record("r2"), _record("r3")]
    resolutions = [
        _resolution("r1", resolution=Resolution.OVERRIDDEN, resolved_text="x"),
        _resolution("r2", resolution=Resolution.OVERRIDDEN, resolved_text="y"),
        _resolution("r3", resolution=Resolution.OVERRIDDEN, resolved_text="z"),
    ]
    assert detect_promotions(records, resolutions) == []


def test_accepted_excluded() -> None:
    # `accepted` of a mechanical fix is already LLM-free; not a decision rule.
    records = [_record("r1"), _record("r2"), _record("r3")]
    resolutions = [
        _resolution(r, resolution=Resolution.ACCEPTED) for r in ("r1", "r2", "r3")
    ]
    assert detect_promotions(records, resolutions) == []


def test_rejected_promotes() -> None:
    records = [_record("r1"), _record("r2"), _record("r3")]
    resolutions = [
        _resolution(r, resolution=Resolution.REJECTED) for r in ("r1", "r2", "r3")
    ]
    candidates = detect_promotions(records, resolutions)
    assert len(candidates) == 1
    assert candidates[0].resolution is Resolution.REJECTED


def test_unresolved_records_ignored() -> None:
    # A record with no resolution is not part of the population.
    records = [_record("r1"), _record("r2"), _record("r3"), _record("r4")]
    resolutions = [_resolution("r1"), _resolution("r2"), _resolution("r3")]
    candidates = detect_promotions(records, resolutions)
    assert candidates[0].count == 3  # r4 (unresolved) does not inflate the count


def test_last_write_wins_join() -> None:
    # A record resolved twice -> last resolution wins (a correction).
    records = [_record("r1"), _record("r2"), _record("r3")]
    resolutions = [
        _resolution(
            "r1", resolution=Resolution.REJECTED, resolved_at="2026-06-01T00:00:00Z"
        ),
        _resolution(
            "r1", resolution=Resolution.INVALIDATED, resolved_at="2026-06-02T00:00:00Z"
        ),
        _resolution("r2"),
        _resolution("r3"),
    ]
    candidates = detect_promotions(records, resolutions)
    assert len(candidates) == 1
    assert candidates[0].resolution is Resolution.INVALIDATED


def test_min_count_honored() -> None:
    records = [_record("r1"), _record("r2")]
    resolutions = [_resolution("r1"), _resolution("r2")]
    candidates = detect_promotions(records, resolutions, min_count=2)
    assert len(candidates) == 1
    assert candidates[0].count == 2


def test_deterministic_sorted_output() -> None:
    # Two distinct qualifying shapes -> sorted deterministically by key.
    records = [
        _record("a1", doc_id="zeta", drift_kind="HASH"),
        _record("a2", doc_id="zeta", drift_kind="HASH"),
        _record("a3", doc_id="zeta", drift_kind="HASH"),
        _record("b1", doc_id="alpha", drift_kind="REGION"),
        _record("b2", doc_id="alpha", drift_kind="REGION"),
        _record("b3", doc_id="alpha", drift_kind="REGION"),
    ]
    resolutions = [_resolution(r) for r in ("a1", "a2", "a3", "b1", "b2", "b3")]
    candidates = detect_promotions(records, resolutions)
    assert [c.doc_id for c in candidates] == ["alpha", "zeta"]
    # Stable across input order.
    assert detect_promotions(list(reversed(records)), resolutions) == candidates


def test_orphan_resolution_ignored() -> None:
    # A resolution whose record_id is not in records cannot create a phantom shape.
    records = [_record("r1"), _record("r2"), _record("r3")]
    resolutions = [
        _resolution("r1"),
        _resolution("r2"),
        _resolution("r3"),
        _resolution("ghost"),
    ]
    candidates = detect_promotions(records, resolutions)
    assert len(candidates) == 1
    assert candidates[0].count == 3


def test_candidate_is_frozen_extra_forbid() -> None:
    c = PromotionCandidate(
        doc_id="d",
        drift_kind="HASH",
        audience=Audience.USER_GUIDE,
        resolution=Resolution.INVALIDATED,
        count=3,
    )
    with pytest.raises(ValidationError):
        c.count = 4  # type: ignore[misc]
    with pytest.raises(ValidationError):
        PromotionCandidate(
            doc_id="d",
            drift_kind="HASH",
            audience=Audience.USER_GUIDE,
            resolution=Resolution.INVALIDATED,
            count=3,
            extra="x",  # type: ignore[call-arg]
        )


# --- D-06: rule mapping -----------------------------------------------------


def _drift(
    *,
    doc_id: str = "user-guide",
    kind: DriftKind = DriftKind.HASH,
    audience: Audience = Audience.USER_GUIDE,
) -> Drift:
    return Drift(
        kind=kind,
        doc_id=doc_id,
        doc_path=f"docs/{doc_id}.md",
        detail="docstring changed",
        audience=audience,
    )


def test_rule_from_candidate_invalidated_maps_to_invalidate() -> None:
    c = PromotionCandidate(
        doc_id="user-guide",
        drift_kind="HASH",
        audience=Audience.USER_GUIDE,
        resolution=Resolution.INVALIDATED,
        count=3,
    )
    rule = rule_from_candidate(c)
    assert rule.verdict is Verdict.INVALIDATE
    assert rule.doc_id == "user-guide"
    assert rule.drift_kind == "HASH"
    assert rule.audience is Audience.USER_GUIDE


def test_rule_from_candidate_rejected_maps_to_invalidate() -> None:
    c = PromotionCandidate(
        doc_id="d",
        drift_kind="HASH",
        audience=Audience.USER_GUIDE,
        resolution=Resolution.REJECTED,
        count=3,
    )
    assert rule_from_candidate(c).verdict is Verdict.INVALIDATE


def test_rule_for_matches_on_shape() -> None:
    rule = PromotionRule(
        doc_id="user-guide",
        drift_kind="HASH",
        audience=Audience.USER_GUIDE,
        verdict=Verdict.INVALIDATE,
    )
    assert rule_for(_drift(), (rule,)) is rule


def test_rule_for_no_match_returns_none() -> None:
    rule = PromotionRule(
        doc_id="other",
        drift_kind="HASH",
        audience=Audience.USER_GUIDE,
        verdict=Verdict.INVALIDATE,
    )
    assert rule_for(_drift(), (rule,)) is None
    # Audience differs.
    rule2 = PromotionRule(
        doc_id="user-guide",
        drift_kind="HASH",
        audience=Audience.ENG_GUIDE,
        verdict=Verdict.INVALIDATE,
    )
    assert rule_for(_drift(), (rule2,)) is None
    # Empty rules.
    assert rule_for(_drift(), ()) is None


def test_rule_for_returns_first_match() -> None:
    r1 = PromotionRule(
        doc_id="user-guide",
        drift_kind="HASH",
        audience=Audience.USER_GUIDE,
        verdict=Verdict.INVALIDATE,
    )
    r2 = PromotionRule(
        doc_id="user-guide",
        drift_kind="HASH",
        audience=Audience.USER_GUIDE,
        verdict=Verdict.ESCALATE,
    )
    assert rule_for(_drift(), (r1, r2)) is r1
