"""PROMO-DISTINCT (idea 21): promotion counts DISTINCT human decisions.

A human decision is one resolved ``record_id`` (``resolved_index`` keeps ONE
resolution per id, last-write-wins). ``schema.new_record_id`` hashes only
``(doc_id, surface_hash, detected_at)``, so under one injected clock every drift
of a document shares one id, and a retried resolve appends a second resolution
line for the same id. Before this slice ``detect_promotions`` counted review-log
LINES, so ONE resolve of a three-region doc read as three unanimous decisions and
crossed the default threshold on its own.

These are pure unit tests over hand-built records; the ship-shape end-to-end
(MCP, CLI, worker, hub) lives in ``tests/integration/test_promotion_distinct.py``.

Features: FEAT-LEARN-007, FEAT-LEARN-008
"""

from __future__ import annotations

import itertools

import pytest

from custodex.config import Audience
from custodex.errors import ConfigError
from custodex.promotion import detect_promotions
from custodex.schema import Resolution, ResolutionRecord, ReviewRecord, Verdict


def _record(
    record_id: str,
    *,
    doc_id: str = "api",
    drift_kind: str = "REGION",
    drift_detail: str = "region 'symbols' drifted",
    audience: Audience = Audience.ENG_GUIDE,
) -> ReviewRecord:
    return ReviewRecord(
        record_id=record_id,
        doc_id=doc_id,
        doc_path=f"docs/{doc_id}.md",
        audience=audience,
        drift_kind=drift_kind,
        drift_detail=drift_detail,
        cause="changed",
        verdict=Verdict.FIX,
        fix=None,
        surface_hash=f"s-{record_id}",
        backend_kind="mock",
        detected_at="2026-06-01T00:00:00Z",
        resolved_at="2026-06-01T00:00:00Z",
        config_snapshot={},
    )


def _shared(record_id: str, details: tuple[str, ...]) -> list[ReviewRecord]:
    """One id spread over several REGION drifts (what one injected clock yields)."""
    return [_record(record_id, drift_detail=d) for d in details]


def _resolution(
    record_id: str,
    resolution: Resolution = Resolution.INVALIDATED,
    *,
    at: str = "2026-06-05T00:00:00Z",
) -> ResolutionRecord:
    return ResolutionRecord(record_id=record_id, resolution=resolution, resolved_at=at)


def _shape_counts(cands: list) -> list[tuple[str, str, int]]:
    return [(c.doc_id, c.drift_kind, c.count) for c in cands]


THREE = ("region 'a'", "region 'b'", "region 'c'")


def test_one_resolve_of_a_shared_id_is_one_decision() -> None:
    # Feature: FEAT-LEARN-007
    # Three REGION drifts share id r1 (one fixed clock); the human resolves r1 ONCE.
    records = _shared("r1", THREE)
    resolutions = [_resolution("r1")]
    assert detect_promotions(records, resolutions) == []
    (cand,) = detect_promotions(records, resolutions, min_count=1)
    assert cand.count == 1


def test_count_is_distinct_record_ids_not_record_lines() -> None:
    # Feature: FEAT-LEARN-007
    # r1 carries 2 lines, r2 and r3 one each: 4 lines, 3 decisions.
    records = _shared("r1", THREE[:2]) + [_record("r2"), _record("r3")]
    resolutions = [_resolution(r) for r in ("r1", "r2", "r3")]
    (cand,) = detect_promotions(records, resolutions)
    assert cand.count == 3


def test_duplicate_log_lines_do_not_inflate_the_count() -> None:
    # Feature: FEAT-LEARN-007
    # Byte-identical lines (a same-clock re-run, a sink re-POST) are still ONE id.
    line = _record("r1")
    records = [line, line, line]
    resolutions = [_resolution("r1")]
    assert detect_promotions(records, resolutions) == []
    (cand,) = detect_promotions(records, resolutions, min_count=1)
    assert cand.count == 1


def test_a_shared_id_counts_once_in_each_shape_it_spans() -> None:
    # Feature: FEAT-LEARN-008
    # The HASH and two REGION drifts of one doc share id r1: it is one decision in
    # EACH shape it spans (not dropped from the second shape, not doubled).
    records = [_record("r1", drift_kind="HASH")] + _shared("r1", THREE[:2])
    resolutions = [_resolution("r1")]
    assert _shape_counts(detect_promotions(records, resolutions, min_count=1)) == [
        ("api", "HASH", 1),
        ("api", "REGION", 1),
    ]


def test_dedupe_never_overwrites_a_dissenting_decision() -> None:
    # Feature: FEAT-LEARN-008
    # Two ids with the SAME drift_detail but different decisions: a dedupe keyed on
    # anything coarser than record_id would let one overwrite the other and launder
    # the dissent. Both orders must give no candidate.
    a = _record("r1", drift_detail="same")
    b = _record("r2", drift_detail="same")
    c = _record("r3", drift_detail="same")
    resolutions = [
        _resolution("r1", Resolution.REJECTED),
        _resolution("r2"),
        _resolution("r3"),
    ]
    for records in ([a, b, c], [b, c, a], [c, b, a]):
        assert detect_promotions(records, resolutions, min_count=2) == []


def test_distinct_count_is_input_order_independent() -> None:
    # Feature: FEAT-LEARN-007
    # K10: every ordering of the records gives the same candidates.
    records = _shared("r1", THREE) + [_record("r2"), _record("r2"), _record("r3")]
    resolutions = [_resolution(r) for r in ("r1", "r2", "r3")]
    seen = {
        tuple(_shape_counts(detect_promotions(list(p), resolutions)))
        for p in itertools.permutations(records)
    }
    assert seen == {(("api", "REGION", 3),)}


def test_count_is_scoped_to_its_own_shape() -> None:
    # Feature: FEAT-LEARN-008
    # Two qualifying shapes with DIFFERENT distinct counts in one call: each
    # candidate reports its OWN shape's count, never a pool across shapes.
    records = [_record(f"h{i}", drift_kind="HASH") for i in range(3)] + [
        _record(f"g{i}") for i in range(4)
    ]
    resolutions = [_resolution(r.record_id) for r in records]
    assert _shape_counts(detect_promotions(records, resolutions)) == [
        ("api", "HASH", 3),
        ("api", "REGION", 4),
    ]


def test_min_count_threshold_is_per_shape() -> None:
    # Feature: FEAT-LEARN-008
    # REGION has 3 decisions, HASH 1 (its id is shared with a REGION drift). A pool
    # of all distinct ids (3) must NOT lift HASH over the threshold.
    records = [_record("g0", drift_kind="HASH")] + [_record(f"g{i}") for i in range(3)]
    resolutions = [_resolution(f"g{i}") for i in range(3)]
    assert _shape_counts(detect_promotions(records, resolutions)) == [
        ("api", "REGION", 3)
    ]


def test_a_corrected_shared_id_counts_once_with_its_latest_decision() -> None:
    # Feature: FEAT-LEARN-007
    # r1 (shared by 3 drifts) is first REJECTED then corrected to INVALIDATED. It is
    # one decision — the latest — so with r2, r3 the shape is unanimous at 3.
    records = _shared("r1", THREE) + [_record("r2"), _record("r3")]
    resolutions = [
        _resolution("r1", Resolution.REJECTED, at="2026-06-05T00:00:00Z"),
        _resolution("r2"),
        _resolution("r3"),
        _resolution("r1", Resolution.INVALIDATED, at="2026-06-06T00:00:00Z"),
    ]
    (cand,) = detect_promotions(records, resolutions)
    assert (cand.resolution, cand.count) == (Resolution.INVALIDATED, 3)


def test_a_repeated_resolution_is_still_one_decision() -> None:
    # Feature: FEAT-LEARN-007
    # Every resolve path appends: a retried resolve leaves two lines for one id.
    records = [_record("r1"), _record("r2")]
    resolutions = [_resolution("r1"), _resolution("r1"), _resolution("r2")]
    assert detect_promotions(records, resolutions) == []
    (cand,) = detect_promotions(records, resolutions, min_count=2)
    assert cand.count == 2


def test_unresolved_ids_never_count_toward_the_threshold() -> None:
    # Feature: FEAT-LEARN-007
    # r1 (3 lines) and r2 are resolved; r3 is open. Two decisions < 3.
    records = _shared("r1", THREE) + [_record("r2"), _record("r3")]
    resolutions = [_resolution("r1"), _resolution("r2")]
    assert detect_promotions(records, resolutions) == []
    (cand,) = detect_promotions(records, resolutions, min_count=2)
    assert cand.count == 2


def test_each_shape_is_unanimous_on_its_own() -> None:
    # Feature: FEAT-LEARN-008
    # Two shapes on one doc with OPPOSITE unanimous decisions (no id is shared):
    # unanimity is checked per shape, so HASH promotes INVALIDATED (h*) and REGION
    # promotes REJECTED (g*); a doc-wide unanimity check would promote neither.
    records = [_record(f"h{i}", drift_kind="HASH") for i in range(3)] + [
        _record(f"g{i}") for i in range(3)
    ]
    resolutions = [_resolution(f"h{i}") for i in range(3)] + [
        _resolution(f"g{i}", Resolution.REJECTED) for i in range(3)
    ]
    assert [
        (c.drift_kind, c.resolution, c.count)
        for c in detect_promotions(records, resolutions)
    ] == [
        ("HASH", Resolution.INVALIDATED, 3),
        ("REGION", Resolution.REJECTED, 3),
    ]


@pytest.mark.parametrize("bad", [0, -5])
def test_min_count_below_one_is_a_loud_config_error(bad: int) -> None:
    # Feature: FEAT-LEARN-007
    # K8: a threshold below one decision is malformed input, not a silent "1".
    with pytest.raises(ConfigError, match="min_count"):
        detect_promotions([_record("r1")], [_resolution("r1")], min_count=bad)


def test_a_non_promotable_dissent_blocks_the_shape() -> None:
    # Feature: FEAT-LEARN-008
    # Three ids INVALIDATED, one OVERRIDDEN (a human wrote prose for that case): the
    # shape is NOT unanimous, so it must not promote - the override is a dissent, not
    # noise to filter out before the unanimity or threshold check.
    records = [_record(f"r{i}") for i in range(4)]
    resolutions = [_resolution(f"r{i}") for i in range(3)] + [
        _resolution("r3", Resolution.OVERRIDDEN)
    ]
    assert detect_promotions(records, resolutions) == []
    assert detect_promotions(records, resolutions, min_count=1) == []


def test_audiences_are_separate_shapes_of_one_doc() -> None:
    # Feature: FEAT-LEARN-008
    # K3: audience is part of the shape. Two user-guide and two eng-guide decisions
    # on the same doc/kind (e.g. the doc's audience was reconfigured) are two shapes
    # of two decisions each, never one shape of four.
    records = [_record(f"u{i}", audience=Audience.USER_GUIDE) for i in range(2)] + [
        _record(f"e{i}", audience=Audience.ENG_GUIDE) for i in range(2)
    ]
    resolutions = [_resolution(r.record_id) for r in records]
    assert detect_promotions(records, resolutions) == []
    got = [
        (c.audience, c.count)
        for c in detect_promotions(records, resolutions, min_count=2)
    ]
    assert sorted(got, key=lambda t: t[0].value) == sorted(
        [(Audience.USER_GUIDE, 2), (Audience.ENG_GUIDE, 2)], key=lambda t: t[0].value
    )


@pytest.mark.parametrize("bad", [0, -1])
def test_min_count_below_one_fails_even_on_an_empty_log(bad: int) -> None:
    # Feature: FEAT-LEARN-007
    # K8: a malformed threshold is loud whatever the data - a fresh repo with an
    # empty review log must not silently accept `--min-count 0`.
    with pytest.raises(ConfigError, match="min_count"):
        detect_promotions([], [], min_count=bad)
