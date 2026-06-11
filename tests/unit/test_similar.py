"""Tests for code_doc_monitor.similar (D-03 — pure, deterministic — K0/K10).

`rank_similar` retrieves the N most-similar PAST RESOLVED records to a target
drift, with a deterministic feature-match score and a total-order tie-break. No
embeddings, no I/O, no wall-clock (K0/K10). TDD (K9).

Features: FEAT-LEARN-001, FEAT-LEARN-002, FEAT-LEARN-003
"""

from __future__ import annotations

from pydantic import ValidationError

from code_doc_monitor.config import Audience
from code_doc_monitor.schema import (
    ProposedFix,
    Resolution,
    ResolutionRecord,
    ReviewRecord,
    Verdict,
)
from code_doc_monitor.similar import Exemplar, rank_similar


def _record(
    record_id: str,
    *,
    doc_id: str = "user-guide",
    audience: Audience = Audience.USER_GUIDE,
    drift_kind: str = "HASH",
    surface_hash: str = "h0",
    verdict: Verdict = Verdict.FIX,
) -> ReviewRecord:
    return ReviewRecord(
        record_id=record_id,
        doc_id=doc_id,
        doc_path=f"docs/{doc_id}.md",
        audience=audience,
        drift_kind=drift_kind,
        drift_detail="moved",
        cause="changed",
        verdict=verdict,
        fix=ProposedFix(
            region_id="symbols",
            new_region_body="body",
            new_doc_text=None,
            rationale="r",
        )
        if verdict == Verdict.FIX
        else None,
        surface_hash=surface_hash,
        backend_kind="mock",
        detected_at="2026-06-01T00:00:00Z",
        resolved_at="2026-06-01T00:00:01Z",
        config_snapshot={},
    )


def _resolution(
    record_id: str,
    *,
    resolution: Resolution = Resolution.ACCEPTED,
    resolved_text: str | None = None,
    resolved_at: str = "2026-06-05T00:00:00Z",
) -> ResolutionRecord:
    return ResolutionRecord(
        record_id=record_id,
        resolution=resolution,
        resolved_text=resolved_text,
        resolved_at=resolved_at,
    )


# ---------------------------------------------------------------------------
# Exemplar model
# ---------------------------------------------------------------------------
def test_exemplar_is_frozen_and_forbids_extra() -> None:
    rec = _record("r1")
    res = _resolution("r1")
    ex = Exemplar(record=rec, resolution=res, score=5.0)
    assert ex.record is rec
    assert ex.resolution is res
    assert ex.score == 5.0
    import pytest

    with pytest.raises(ValidationError):
        Exemplar(record=rec, resolution=res, score=1.0, extra="x")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ex.score = 9.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# rank_similar — population + exclusions
# ---------------------------------------------------------------------------
def test_planted_near_duplicate_ranks_first() -> None:
    target = _record(
        "tgt", doc_id="guide", audience=Audience.ENG_GUIDE, drift_kind="REGION"
    )
    near = _record(
        "near", doc_id="guide", audience=Audience.ENG_GUIDE, drift_kind="REGION"
    )
    unrelated = _record(
        "far", doc_id="other", audience=Audience.USER_GUIDE, drift_kind="HASH"
    )
    records = [near, unrelated]
    resolutions = [_resolution("near"), _resolution("far")]
    out = rank_similar(target, records, resolutions)
    assert [e.record.record_id for e in out] == ["near", "far"]
    assert out[0].score > out[1].score


def test_unresolved_records_are_excluded() -> None:
    target = _record("tgt", doc_id="guide", drift_kind="REGION")
    resolved = _record("res", doc_id="guide", drift_kind="REGION")
    unresolved = _record("unres", doc_id="guide", drift_kind="REGION")
    records = [resolved, unresolved]
    resolutions = [_resolution("res")]  # only `res` is resolved
    out = rank_similar(target, records, resolutions)
    assert [e.record.record_id for e in out] == ["res"]


def test_target_is_excluded_from_its_own_results() -> None:
    target = _record("tgt", doc_id="guide", drift_kind="REGION")
    other = _record("other", doc_id="guide", drift_kind="REGION")
    records = [target, other]
    # Even though the target itself is resolved, it must not appear.
    resolutions = [_resolution("tgt"), _resolution("other")]
    out = rank_similar(target, records, resolutions)
    assert [e.record.record_id for e in out] == ["other"]


def test_empty_population_returns_empty() -> None:
    target = _record("tgt")
    assert rank_similar(target, [], []) == []
    # records present but none resolved -> empty
    assert rank_similar(target, [_record("a")], []) == []


def test_top_n_caps_results() -> None:
    target = _record("tgt", doc_id="g", drift_kind="REGION")
    records = [_record(f"r{i}", doc_id="g", drift_kind="REGION") for i in range(5)]
    resolutions = [_resolution(f"r{i}") for i in range(5)]
    out = rank_similar(target, records, resolutions, top_n=2)
    assert len(out) == 2


def test_top_n_zero_or_negative_returns_empty() -> None:
    target = _record("tgt", doc_id="g")
    records = [_record("r0", doc_id="g")]
    resolutions = [_resolution("r0")]
    assert rank_similar(target, records, resolutions, top_n=0) == []
    assert rank_similar(target, records, resolutions, top_n=-3) == []


# ---------------------------------------------------------------------------
# Scoring — weighted feature match
# ---------------------------------------------------------------------------
def test_surface_hash_match_outweighs_all_lower_features() -> None:
    target = _record(
        "tgt",
        doc_id="g",
        audience=Audience.ENG_GUIDE,
        drift_kind="REGION",
        surface_hash="SAME",
    )
    # Same surface_hash only (weight 5), everything else different.
    same_surface = _record(
        "surf",
        doc_id="x",
        audience=Audience.USER_GUIDE,
        drift_kind="HASH",
        surface_hash="SAME",
    )
    # Matches doc_id + drift_kind + audience (3+2+1=6 ... but those differ here).
    # Build a candidate matching doc+kind+audience but NOT surface (3+2+1=6 > 5):
    lower = _record(
        "lower",
        doc_id="g",
        audience=Audience.ENG_GUIDE,
        drift_kind="REGION",
        surface_hash="DIFF",
    )
    records = [same_surface, lower]
    resolutions = [_resolution("surf"), _resolution("lower")]
    out = rank_similar(target, records, resolutions)
    by_id = {e.record.record_id: e.score for e in out}
    assert by_id["surf"] == 5.0
    assert by_id["lower"] == 6.0  # doc 3 + kind 2 + audience 1
    # `lower` (6.0) ranks above `surf` (5.0).
    assert [e.record.record_id for e in out] == ["lower", "surf"]


def test_exact_full_match_scores_max() -> None:
    target = _record(
        "tgt",
        doc_id="g",
        audience=Audience.ENG_GUIDE,
        drift_kind="REGION",
        surface_hash="H",
    )
    twin = _record(
        "twin",
        doc_id="g",
        audience=Audience.ENG_GUIDE,
        drift_kind="REGION",
        surface_hash="H",
    )
    out = rank_similar(target, [twin], [_resolution("twin")])
    assert out[0].score == 11.0  # 5 + 3 + 2 + 1


def test_zero_score_candidate_still_eligible_but_last() -> None:
    target = _record(
        "tgt",
        doc_id="g",
        audience=Audience.ENG_GUIDE,
        drift_kind="REGION",
        surface_hash="H",
    )
    nomatch = _record(
        "none",
        doc_id="x",
        audience=Audience.USER_GUIDE,
        drift_kind="HASH",
        surface_hash="Z",
    )
    match = _record(
        "some",
        doc_id="g",
        audience=Audience.ENG_GUIDE,
        drift_kind="REGION",
        surface_hash="H",
    )
    out = rank_similar(
        target, [nomatch, match], [_resolution("none"), _resolution("some")]
    )
    assert [e.record.record_id for e in out] == ["some", "none"]
    assert out[-1].score == 0.0


# ---------------------------------------------------------------------------
# Tie-break — total order (score, then recency, then record_id) — K10
# ---------------------------------------------------------------------------
def test_equal_score_tie_breaks_by_recency_then_id() -> None:
    target = _record("tgt", doc_id="g", drift_kind="REGION", surface_hash="H")
    # Three identical-feature candidates -> identical score; differ only by
    # resolved_at (recency) and record_id.
    a = _record("a", doc_id="g", drift_kind="REGION", surface_hash="H")
    b = _record("b", doc_id="g", drift_kind="REGION", surface_hash="H")
    c = _record("c", doc_id="g", drift_kind="REGION", surface_hash="H")
    resolutions = [
        _resolution("a", resolved_at="2026-06-01T00:00:00Z"),
        _resolution("b", resolved_at="2026-06-03T00:00:00Z"),  # most recent
        _resolution("c", resolved_at="2026-06-03T00:00:00Z"),  # tie w/ b on time
    ]
    out = rank_similar(target, [a, b, c], resolutions)
    # b and c tie on score+recency -> record_id ascending => b before c; both
    # more recent than a.
    assert [e.record.record_id for e in out] == ["b", "c", "a"]


def test_ranking_is_deterministic_across_input_order() -> None:
    target = _record("tgt", doc_id="g", drift_kind="REGION", surface_hash="H")
    a = _record("a", doc_id="g", drift_kind="REGION", surface_hash="H")
    b = _record("b", doc_id="g", drift_kind="REGION", surface_hash="H")
    resolutions = [
        _resolution("a", resolved_at="2026-06-05T00:00:00Z"),
        _resolution("b", resolved_at="2026-06-05T00:00:00Z"),
    ]
    out1 = rank_similar(target, [a, b], resolutions)
    out2 = rank_similar(target, [b, a], list(reversed(resolutions)))
    assert [e.record.record_id for e in out1] == [e.record.record_id for e in out2]
    assert [e.record.record_id for e in out1] == ["a", "b"]


def test_last_write_wins_resolution_used() -> None:
    # A record resolved twice -> the LAST appended resolution is the one carried.
    target = _record("tgt", doc_id="g", drift_kind="REGION", surface_hash="H")
    rec = _record("rec", doc_id="g", drift_kind="REGION", surface_hash="H")
    resolutions = [
        _resolution("rec", resolution=Resolution.REJECTED),
        _resolution(
            "rec", resolution=Resolution.OVERRIDDEN, resolved_text="final body"
        ),
    ]
    out = rank_similar(target, [rec], resolutions)
    assert len(out) == 1
    assert out[0].resolution.resolution == Resolution.OVERRIDDEN
    assert out[0].resolution.resolved_text == "final body"
