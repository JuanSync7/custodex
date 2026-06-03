"""Tests for code_doc_monitor.schema (CDM-04).

The review-record schema is public and versioned (K6) and derived from the
pydantic models (one source of truth — no hand-written schema). Records are
deterministic: `new_record_id` is a pure function of its inputs (K10). TDD (K9).
"""

from __future__ import annotations

from code_doc_monitor.config import Audience
from code_doc_monitor.schema import (
    ProposedFix,
    ReviewRecord,
    Verdict,
    new_record_id,
    review_record_schema,
)


def _record(**over: object) -> ReviewRecord:
    base: dict[str, object] = dict(
        record_id="abc123",
        doc_id="user-guide",
        doc_path="docs/user-guide.md",
        audience=Audience.USER_GUIDE,
        drift_kind="HASH",
        drift_detail="fingerprint moved",
        cause="public signature changed",
        verdict=Verdict.FIX,
        fix=ProposedFix(
            region_id="symbols",
            new_region_body="new body",
            new_doc_text=None,
            rationale="regenerate the symbol table",
        ),
        surface_hash="deadbeef",
        backend_kind="mock",
        detected_at="2026-06-01T00:00:00Z",
        resolved_at="2026-06-01T00:00:01Z",
        config_snapshot={"version": "1.0.0"},
    )
    base.update(over)
    return ReviewRecord(**base)  # type: ignore[arg-type]


def test_verdict_values() -> None:
    assert Verdict.FIX.value == "FIX"
    assert Verdict.INVALIDATE.value == "INVALIDATE"
    assert Verdict.ESCALATE.value == "ESCALATE"


def test_review_record_round_trips_through_json() -> None:
    rec = _record()
    data = rec.model_dump_json()
    again = ReviewRecord.model_validate_json(data)
    assert again == rec
    assert again.schema_version == "1.0.0"
    assert again.fix is not None
    assert again.fix.region_id == "symbols"


def test_review_record_default_schema_version() -> None:
    assert _record().schema_version == "1.0.0"


def test_fix_is_optional() -> None:
    rec = _record(verdict=Verdict.ESCALATE, fix=None)
    assert rec.fix is None
    assert ReviewRecord.model_validate_json(rec.model_dump_json()).fix is None


def test_proposed_fix_is_frozen_and_forbids_extra() -> None:
    fix = ProposedFix(
        region_id=None,
        new_region_body=None,
        new_doc_text=None,
        rationale="why",
    )
    import pydantic
    import pytest

    with pytest.raises(pydantic.ValidationError):
        ProposedFix(rationale="x", bogus="y")  # type: ignore[call-arg]
    with pytest.raises(pydantic.ValidationError):
        fix.rationale = "mutated"  # type: ignore[misc]


def test_review_record_forbids_extra() -> None:
    import pydantic
    import pytest

    with pytest.raises(pydantic.ValidationError):
        _record(unexpected_field="boom")


def test_review_record_schema_is_versioned_json_schema() -> None:
    schema = review_record_schema()
    assert isinstance(schema, dict)
    assert schema["type"] == "object"
    props = schema["properties"]
    assert "schema_version" in props
    # All the contract fields are present as properties.
    for field in (
        "record_id",
        "doc_id",
        "doc_path",
        "audience",
        "drift_kind",
        "drift_detail",
        "cause",
        "verdict",
        "fix",
        "surface_hash",
        "backend_kind",
        "detected_at",
        "resolved_at",
        "config_snapshot",
    ):
        assert field in props, field


def test_new_record_id_is_deterministic() -> None:
    a = new_record_id("doc", "hash", "2026-06-01T00:00:00Z")
    b = new_record_id("doc", "hash", "2026-06-01T00:00:00Z")
    assert a == b
    assert len(a) == 12
    assert all(c in "0123456789abcdef" for c in a)


def test_new_record_id_is_sensitive_to_each_input() -> None:
    base = new_record_id("doc", "hash", "ts")
    assert new_record_id("DOC", "hash", "ts") != base
    assert new_record_id("doc", "HASH", "ts") != base
    assert new_record_id("doc", "hash", "TS") != base
