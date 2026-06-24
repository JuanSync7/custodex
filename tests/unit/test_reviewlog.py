"""Tests for custodex.reviewlog (CDM-04).

The review log is append-only JSONL (K5): each handled drift is one line and
existing lines are never rewritten. A corrupt line is loud, not silent (K8).
`summarize` counts deterministically. TDD (K9).

Features: FEAT-RECORD-007, FEAT-RECORD-008, FEAT-RECORD-009
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custodex.config import Audience
from custodex.errors import SchemaError
from custodex.reviewlog import (
    append,
    append_resolution,
    read_all,
    read_resolutions,
    resolved_index,
    select_by_verdict,
    summarize,
    summarize_with_resolutions,
)
from custodex.schema import (
    ProposedFix,
    Resolution,
    ResolutionRecord,
    ReviewRecord,
    Verdict,
)


def _record(
    record_id: str,
    doc_id: str = "user-guide",
    audience: Audience = Audience.USER_GUIDE,
    verdict: Verdict = Verdict.FIX,
) -> ReviewRecord:
    return ReviewRecord(
        record_id=record_id,
        doc_id=doc_id,
        doc_path=f"docs/{doc_id}.md",
        audience=audience,
        drift_kind="HASH",
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
        surface_hash="hash",
        backend_kind="mock",
        detected_at="2026-06-01T00:00:00Z",
        resolved_at="2026-06-01T00:00:01Z",
        config_snapshot={},
    )


def test_read_all_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_all(tmp_path / "nope.jsonl") == []


def test_append_creates_parent_dirs_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deep" / "review.jsonl"
    rec = _record("r1")
    append(path, rec)
    assert path.is_file()
    out = read_all(path)
    assert out == [rec]


def test_append_is_additive_not_truncating(tmp_path: Path) -> None:
    path = tmp_path / "review.jsonl"
    recs = [_record("r1"), _record("r2"), _record("r3")]
    for rec in recs:
        append(path, rec)
    # Three distinct lines, in order, nothing overwritten.
    assert path.read_text(encoding="utf-8").count("\n") == 3
    assert read_all(path) == recs


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "review.jsonl"
    append(path, _record("r1"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n   \n")
    append(path, _record("r2"))
    assert [r.record_id for r in read_all(path)] == ["r1", "r2"]


def test_corrupt_line_raises_schema_error(tmp_path: Path) -> None:
    path = tmp_path / "review.jsonl"
    append(path, _record("r1"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write("this is not json\n")
    with pytest.raises(SchemaError):
        read_all(path)


def test_summarize_counts_by_verdict_audience_and_doc(tmp_path: Path) -> None:
    records = [
        _record("r1", "user-guide", Audience.USER_GUIDE, Verdict.FIX),
        _record("r2", "user-guide", Audience.USER_GUIDE, Verdict.INVALIDATE),
        _record("r3", "eng-guide", Audience.ENG_GUIDE, Verdict.FIX),
        _record("r4", "eng-guide", Audience.ENG_GUIDE, Verdict.ESCALATE),
    ]
    summary = summarize(records)
    assert summary["total"] == 4
    assert summary["by_verdict"] == {"FIX": 2, "INVALIDATE": 1, "ESCALATE": 1}
    assert summary["by_audience"] == {"user-guide": 2, "eng-guide": 2}
    assert summary["by_doc_id"] == {"user-guide": 2, "eng-guide": 2}


def test_summarize_empty_is_zeroed() -> None:
    summary = summarize([])
    assert summary["total"] == 0
    assert summary["by_verdict"] == {}
    assert summary["by_audience"] == {}
    assert summary["by_doc_id"] == {}


def test_select_by_verdict_filters_and_preserves_order() -> None:
    records = [
        _record("r1", "user-guide", Audience.USER_GUIDE, Verdict.FIX),
        _record("r2", "eng-guide", Audience.ENG_GUIDE, Verdict.ESCALATE),
        _record("r3", "user-guide", Audience.USER_GUIDE, Verdict.INVALIDATE),
        _record("r4", "eng-guide", Audience.ENG_GUIDE, Verdict.ESCALATE),
    ]
    escalations = select_by_verdict(records, Verdict.ESCALATE)
    # Only ESCALATE records, in append (chronological) order.
    assert [r.record_id for r in escalations] == ["r2", "r4"]


def test_select_by_verdict_no_match_is_empty() -> None:
    records = [_record("r1", verdict=Verdict.FIX)]
    assert select_by_verdict(records, Verdict.ESCALATE) == []


def test_summarize_ordering_is_deterministic() -> None:
    records = [
        _record("r1", "zeta", Audience.ENG_GUIDE, Verdict.ESCALATE),
        _record("r2", "alpha", Audience.USER_GUIDE, Verdict.FIX),
    ]
    summary = summarize(records)
    # Keys sorted deterministically (K10).
    assert list(summary["by_doc_id"].keys()) == ["alpha", "zeta"]
    assert list(summary["by_verdict"].keys()) == ["ESCALATE", "FIX"]


# --- D-01/D-02: resolutions log (separate append-only event, joined by FK) -----


def _resolution(
    record_id: str,
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


def test_read_resolutions_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_resolutions(tmp_path / "nope.jsonl") == []


def test_append_resolution_creates_parent_dirs_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deep" / "resolutions.jsonl"
    rec = _resolution("r1")
    append_resolution(path, rec)
    assert path.is_file()
    assert read_resolutions(path) == [rec]


def test_append_resolution_is_additive_not_truncating(tmp_path: Path) -> None:
    path = tmp_path / "resolutions.jsonl"
    recs = [_resolution("r1"), _resolution("r2"), _resolution("r3")]
    for rec in recs:
        append_resolution(path, rec)
    assert path.read_text(encoding="utf-8").count("\n") == 3
    assert read_resolutions(path) == recs


def test_resolution_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "resolutions.jsonl"
    append_resolution(path, _resolution("r1"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n   \n")
    append_resolution(path, _resolution("r2"))
    assert [r.record_id for r in read_resolutions(path)] == ["r1", "r2"]


def test_corrupt_resolution_line_raises_schema_error(tmp_path: Path) -> None:
    path = tmp_path / "resolutions.jsonl"
    append_resolution(path, _resolution("r1"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write("this is not json\n")
    with pytest.raises(SchemaError):
        read_resolutions(path)


def test_resolved_index_last_write_wins() -> None:
    # A record resolved twice: the LAST appended resolution wins (append-only log;
    # a correction is a new event, never a mutation).
    resolutions = [
        _resolution("r1", Resolution.REJECTED, resolved_at="2026-06-05T00:00:00Z"),
        _resolution("r1", Resolution.ACCEPTED, resolved_at="2026-06-05T01:00:00Z"),
        _resolution("r2", Resolution.OVERRIDDEN),
    ]
    index = resolved_index(resolutions)
    assert set(index) == {"r1", "r2"}
    assert index["r1"].resolution == Resolution.ACCEPTED  # last wins
    assert index["r1"].resolved_at == "2026-06-05T01:00:00Z"


def test_summarize_with_resolutions_counts_resolved_unresolved() -> None:
    records = [
        _record("r1"),
        _record("r2"),
        _record("r3"),
    ]
    resolutions = [
        _resolution("r1", Resolution.ACCEPTED),
        _resolution("r2", Resolution.OVERRIDDEN, resolved_text="reworded"),
    ]
    summary = summarize_with_resolutions(records, resolutions)
    assert summary["total"] == 3
    assert summary["resolved"] == 2
    assert summary["unresolved"] == 1
    assert summary["by_resolution"] == {"accepted": 1, "overridden": 1}


def test_summarize_with_resolutions_ignores_orphan_resolutions() -> None:
    # A resolution whose record_id is not in the review log does not inflate counts.
    records = [_record("r1")]
    resolutions = [
        _resolution("r1", Resolution.ACCEPTED),
        _resolution("ghost", Resolution.REJECTED),
    ]
    summary = summarize_with_resolutions(records, resolutions)
    assert summary["total"] == 1
    assert summary["resolved"] == 1
    assert summary["unresolved"] == 0
    assert summary["by_resolution"] == {"accepted": 1}


def test_summarize_with_resolutions_empty_is_zeroed() -> None:
    summary = summarize_with_resolutions([], [])
    assert summary == {
        "total": 0,
        "resolved": 0,
        "unresolved": 0,
        "by_resolution": {},
    }


def test_summarize_with_resolutions_by_resolution_is_sorted() -> None:
    records = [_record("r1"), _record("r2")]
    resolutions = [
        _resolution("r1", Resolution.REJECTED),
        _resolution("r2", Resolution.ACCEPTED),
    ]
    keys = list(summarize_with_resolutions(records, resolutions)["by_resolution"])
    assert keys == ["accepted", "rejected"]  # sorted, deterministic (K10)
