"""Tests for code_doc_monitor.reviewlog (CDM-04).

The review log is append-only JSONL (K5): each handled drift is one line and
existing lines are never rewritten. A corrupt line is loud, not silent (K8).
`summarize` counts deterministically. TDD (K9).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_doc_monitor.config import Audience
from code_doc_monitor.errors import SchemaError
from code_doc_monitor.reviewlog import append, read_all, summarize
from code_doc_monitor.schema import ProposedFix, ReviewRecord, Verdict


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


def test_summarize_ordering_is_deterministic() -> None:
    records = [
        _record("r1", "zeta", Audience.ENG_GUIDE, Verdict.ESCALATE),
        _record("r2", "alpha", Audience.USER_GUIDE, Verdict.FIX),
    ]
    summary = summarize(records)
    # Keys sorted deterministically (K10).
    assert list(summary["by_doc_id"].keys()) == ["alpha", "zeta"]
    assert list(summary["by_verdict"].keys()) == ["ESCALATE", "FIX"]
