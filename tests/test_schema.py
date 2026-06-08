"""Tests for code_doc_monitor.schema (CDM-04).

The review-record schema is public and versioned (K6) and derived from the
pydantic models (one source of truth — no hand-written schema). Records are
deterministic: `new_record_id` is a pure function of its inputs (K10). TDD (K9).
"""

from __future__ import annotations

import json

from code_doc_monitor.config import Audience
from code_doc_monitor.schema import (
    ProposedFix,
    Resolution,
    ResolutionRecord,
    ReviewRecord,
    Verdict,
    new_record_id,
    resolution_record_schema,
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
    assert again.schema_version == "1.1.0"
    assert again.fix is not None
    assert again.fix.region_id == "symbols"


def test_review_record_default_schema_version() -> None:
    assert _record().schema_version == "1.1.0"  # P2 minor bump


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


def test_source_sha_defaults_none_and_round_trips() -> None:
    """C-05: `source_sha` is additive — default None, and a set value round-trips."""
    assert _record().source_sha is None
    rec = _record(source_sha="abc123")
    again = ReviewRecord.model_validate_json(rec.model_dump_json())
    assert again.source_sha == "abc123"
    assert again == rec


def test_pre_c05_record_without_source_sha_still_parses() -> None:
    """K6 back-compat: an OLD JSONL line (no `source_sha`) must still validate."""
    legacy = json.dumps(
        {
            "schema_version": "1.0.0",
            "record_id": "abc123",
            "doc_id": "user-guide",
            "doc_path": "docs/user-guide.md",
            "audience": "user-guide",
            "drift_kind": "HASH",
            "drift_detail": "fingerprint moved",
            "cause": "public signature changed",
            "verdict": "FIX",
            "fix": None,
            "surface_hash": "deadbeef",
            "backend_kind": "mock",
            "detected_at": "2026-06-01T00:00:00Z",
            "resolved_at": "2026-06-01T00:00:01Z",
            "config_snapshot": {"version": "1.0.0"},
        }
    )
    rec = ReviewRecord.model_validate_json(legacy)
    assert rec.source_sha is None  # absent field defaults to None (K6)


def test_review_record_schema_includes_source_sha() -> None:
    """C-05: the emitted schema carries the new optional `source_sha` property."""
    assert "source_sha" in review_record_schema()["properties"]


def test_pre_t01_record_without_ticket_still_parses() -> None:
    """K6 back-compat: an OLD JSONL line (no `ticket`) must still validate."""
    legacy = json.dumps(
        {
            "schema_version": "1.0.0",
            "record_id": "abc123",
            "doc_id": "user-guide",
            "doc_path": "docs/user-guide.md",
            "audience": "user-guide",
            "drift_kind": "HASH",
            "drift_detail": "fingerprint moved",
            "cause": "public signature changed",
            "verdict": "FIX",
            "fix": None,
            "surface_hash": "deadbeef",
            "backend_kind": "mock",
            "detected_at": "2026-06-01T00:00:00Z",
            "resolved_at": "2026-06-01T00:00:01Z",
            "config_snapshot": {"version": "1.0.0"},
        }
    )
    rec = ReviewRecord.model_validate_json(legacy)
    assert rec.ticket is None  # absent additive field defaults to None (K6)


def test_record_with_ticket_round_trips() -> None:
    """T-01: a record carrying a DriftTicket round-trips through JSON (K6)."""
    from code_doc_monitor.ticket import DriftTicket, TicketSeverity

    ticket = DriftTicket(
        ticket_id="CDM-abc123",
        title="[MEDIUM] HASH in user-guide",
        summary="fingerprint moved. The remediation agent's read: changed",
        severity=TicketSeverity.MEDIUM,
        drift_kind="HASH",
        doc_id="user-guide",
        doc_path="docs/user-guide.md",
        audience="user-guide",
        root_cause="changed",
        proposed_change="regenerate",
        change_kind="region",
        verdict="FIX",
        recommended_action="Apply the proposed fix",
    )
    rec = _record(ticket=ticket)
    again = ReviewRecord.model_validate_json(rec.model_dump_json())
    assert again == rec
    assert again.ticket is not None
    assert again.ticket.ticket_id == "CDM-abc123"


def test_record_ticket_defaults_none() -> None:
    assert _record().ticket is None


def test_drifted_tiers_defaults_empty_and_round_trips() -> None:
    """P2: `drifted_tiers` is additive — default (), and a set value round-trips."""
    assert _record().drifted_tiers == ()
    rec = _record(drifted_tiers=("signature", "body"))
    again = ReviewRecord.model_validate_json(rec.model_dump_json())
    assert again.drifted_tiers == ("signature", "body")
    assert again == rec


def test_pre_p02_record_without_drifted_tiers_still_parses() -> None:
    """K6 back-compat: an OLD 1.0.0 JSONL line (no `drifted_tiers`) still validates."""
    legacy = json.dumps(
        {
            "schema_version": "1.0.0",
            "record_id": "abc123",
            "doc_id": "user-guide",
            "doc_path": "docs/user-guide.md",
            "audience": "user-guide",
            "drift_kind": "HASH",
            "drift_detail": "fingerprint moved",
            "cause": "public signature changed",
            "verdict": "FIX",
            "fix": None,
            "surface_hash": "deadbeef",
            "backend_kind": "mock",
            "detected_at": "2026-06-01T00:00:00Z",
            "resolved_at": "2026-06-01T00:00:01Z",
            "config_snapshot": {"version": "1.0.0"},
        }
    )
    rec = ReviewRecord.model_validate_json(legacy)
    assert rec.drifted_tiers == ()  # absent additive field defaults to () (K6)
    assert rec.schema_version == "1.0.0"  # the old line's own version is preserved


def test_review_record_schema_includes_drifted_tiers() -> None:
    assert "drifted_tiers" in review_record_schema()["properties"]


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


# --- D-01/D-02: ResolutionRecord (the human outcome, a separate event) ---------


def _resolution(**over: object) -> ResolutionRecord:
    base: dict[str, object] = dict(
        record_id="abc123",
        resolution=Resolution.ACCEPTED,
        resolved_at="2026-06-05T00:00:00Z",
    )
    base.update(over)
    return ResolutionRecord(**base)  # type: ignore[arg-type]


def test_resolution_enum_values() -> None:
    assert Resolution.ACCEPTED.value == "accepted"
    assert Resolution.OVERRIDDEN.value == "overridden"
    assert Resolution.REJECTED.value == "rejected"
    assert Resolution.INVALIDATED.value == "invalidated"


def test_resolution_record_round_trips_through_json() -> None:
    rec = _resolution(
        resolution=Resolution.OVERRIDDEN,
        resolved_text="the human's final body",
        resolved_by="alice",
        note="reworded for clarity",
    )
    again = ResolutionRecord.model_validate_json(rec.model_dump_json())
    assert again == rec
    assert again.schema_version == "1.0.0"
    assert again.resolved_text == "the human's final body"
    assert again.resolved_by == "alice"


def test_resolution_record_optional_fields_default_none() -> None:
    rec = _resolution()
    assert rec.resolved_text is None
    assert rec.resolved_by is None
    assert rec.note is None


def test_resolution_record_is_frozen_and_forbids_extra() -> None:
    import pydantic
    import pytest

    rec = _resolution()
    with pytest.raises(pydantic.ValidationError):
        _resolution(bogus="y")
    with pytest.raises(pydantic.ValidationError):
        rec.resolution = Resolution.REJECTED  # type: ignore[misc]


def test_resolution_record_schema_is_versioned_json_schema() -> None:
    schema = resolution_record_schema()
    assert isinstance(schema, dict)
    assert schema["type"] == "object"
    props = schema["properties"]
    for field in (
        "schema_version",
        "record_id",
        "resolution",
        "resolved_text",
        "resolved_by",
        "resolved_at",
        "note",
    ):
        assert field in props, field


def test_resolution_line_without_future_field_still_parses() -> None:
    """K6 back-compat: a line missing the (additive) `note` field still validates."""
    legacy = json.dumps(
        {
            "schema_version": "1.0.0",
            "record_id": "abc123",
            "resolution": "accepted",
            "resolved_text": None,
            "resolved_by": None,
            "resolved_at": "2026-06-05T00:00:00Z",
        }
    )
    rec = ResolutionRecord.model_validate_json(legacy)
    assert rec.note is None  # absent additive field defaults to None (K6)
