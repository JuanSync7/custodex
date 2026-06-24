"""Tests for custodex.ticket (T-01).

A :class:`DriftTicket` is the structured, human-validatable artifact built FROM
an existing backend result — pure and deterministic (K1/K10): every field is
derived from the drift, verdict, cause, fix and surface already in
``monitor._record_for``, with no clock and no I/O. :func:`ticket_status` is a
pure mapping from a :class:`ResolutionRecord` outcome. TDD (K9).

Features: FEAT-PR-009, FEAT-PR-010, FEAT-PR-011
"""

from __future__ import annotations

import pydantic
import pytest

from custodex.config import Audience
from custodex.drift import Drift, DriftKind
from custodex.extract import DocumentSurface, Symbol
from custodex.schema import ProposedFix, Resolution, ResolutionRecord, Verdict
from custodex.ticket import (
    AcceptanceCheck,
    DriftTicket,
    TicketSeverity,
    TicketStatus,
    build_ticket,
    ticket_status,
)


def _symbol(name: str, *, is_public: bool) -> Symbol:
    return Symbol(
        name=name,
        kind="function",
        signature=f"{name}()",
        lineno=1,
        end_lineno=1,
        is_public=is_public,
        docstring=None,
    )


def _surface(*names_public: tuple[str, bool]) -> DocumentSurface:
    return DocumentSurface(
        doc_id="guide",
        audience=Audience.ENG_GUIDE,
        symbols=tuple(_symbol(n, is_public=p) for n, p in names_public),
    )


def _drift(**over: object) -> Drift:
    base: dict[str, object] = dict(
        kind=DriftKind.REGION,
        doc_id="guide",
        doc_path="docs/guide.md",
        detail="managed region 'symbols' is out of date",
        region_id="symbols",
        healable=True,
        audience=Audience.ENG_GUIDE,
        diff="--- a\n+++ b\n",
    )
    base.update(over)
    return Drift(**base)  # type: ignore[arg-type]


def _region_fix() -> ProposedFix:
    return ProposedFix(
        region_id="symbols",
        new_region_body="new body",
        new_doc_text=None,
        rationale="regenerate the symbol table from the current surface",
    )


def _whole_doc_fix() -> ProposedFix:
    return ProposedFix(
        region_id=None,
        new_region_body=None,
        new_doc_text="# Whole new doc\n",
        rationale="rewrite the whole document",
    )


def _build(**over: object) -> DriftTicket:
    base: dict[str, object] = dict(
        drift=_drift(),
        verdict=Verdict.FIX,
        cause="public signature changed",
        fix=_region_fix(),
        surface=_surface(("public_fn", True), ("_private", False)),
        ticket_id="CDM-abc123",
    )
    base.update(over)
    return build_ticket(**base)  # type: ignore[arg-type]


# --- enums + models ----------------------------------------------------------


def test_severity_values() -> None:
    assert TicketSeverity.LOW.value == "low"
    assert TicketSeverity.MEDIUM.value == "medium"
    assert TicketSeverity.HIGH.value == "high"


def test_status_values() -> None:
    assert TicketStatus.PROPOSED.value == "proposed"
    assert TicketStatus.VALIDATED.value == "validated"
    assert TicketStatus.CHANGES_REQUESTED.value == "changes-requested"
    assert TicketStatus.REJECTED.value == "rejected"


def test_acceptance_check_defaults_and_frozen() -> None:
    chk = AcceptanceCheck(text="something")
    assert chk.auto_satisfied is False
    with pytest.raises(pydantic.ValidationError):
        chk.text = "mutated"  # type: ignore[misc]
    with pytest.raises(pydantic.ValidationError):
        AcceptanceCheck(text="x", bogus="y")  # type: ignore[call-arg]


def test_ticket_is_frozen_and_forbids_extra() -> None:
    ticket = _build()
    with pytest.raises(pydantic.ValidationError):
        ticket.title = "mutated"  # type: ignore[misc]
    with pytest.raises(pydantic.ValidationError):
        DriftTicket(  # type: ignore[call-arg]
            ticket_id="x",
            title="t",
            summary="s",
            severity=TicketSeverity.LOW,
            drift_kind="HASH",
            doc_id="d",
            doc_path="p",
            audience="eng-guide",
            root_cause="c",
            proposed_change="pc",
            change_kind="none",
            verdict="FIX",
            recommended_action="ra",
            bogus="y",
        )


def test_ticket_round_trips_through_json() -> None:
    ticket = _build()
    again = DriftTicket.model_validate_json(ticket.model_dump_json())
    assert again == ticket
    assert again.schema_version == "1.0.0"


# --- build_ticket: purity / determinism --------------------------------------


def test_build_ticket_is_deterministic() -> None:
    a = _build()
    b = _build()
    assert a == b


# --- build_ticket: severity heuristic ----------------------------------------


def test_severity_high_on_escalate() -> None:
    t = _build(verdict=Verdict.ESCALATE, fix=None)
    assert t.severity is TicketSeverity.HIGH


def test_severity_high_on_unhealable_kind() -> None:
    t = _build(
        drift=_drift(kind=DriftKind.UNHEALABLE, healable=False),
        verdict=Verdict.FIX,
        fix=None,
    )
    assert t.severity is TicketSeverity.HIGH


def test_severity_high_on_not_healable() -> None:
    t = _build(drift=_drift(healable=False), verdict=Verdict.FIX, fix=None)
    assert t.severity is TicketSeverity.HIGH


def test_severity_low_on_invalidate() -> None:
    t = _build(verdict=Verdict.INVALIDATE, fix=None)
    assert t.severity is TicketSeverity.LOW


def test_severity_medium_on_fix_region() -> None:
    t = _build(verdict=Verdict.FIX, fix=_region_fix())
    assert t.severity is TicketSeverity.MEDIUM


# --- build_ticket: change_kind -----------------------------------------------


def test_change_kind_region() -> None:
    assert _build(fix=_region_fix()).change_kind == "region"


def test_change_kind_whole_doc() -> None:
    assert _build(fix=_whole_doc_fix()).change_kind == "whole-doc"


def test_change_kind_none() -> None:
    assert _build(verdict=Verdict.ESCALATE, fix=None).change_kind == "none"


def test_change_kind_none_for_bodyless_fix() -> None:
    # A ProposedFix that carries a rationale but NO region/whole-doc body is
    # classified "none" — distinct from the fix-is-None path above.
    bodyless = ProposedFix(rationale="explained, but proposes no concrete edit")
    assert _build(fix=bodyless).change_kind == "none"


# --- build_ticket: affected symbols ------------------------------------------


def test_affected_symbols_public_sorted_only() -> None:
    surface = _surface(
        ("zebra", True),
        ("_hidden", False),
        ("alpha", True),
    )
    t = _build(surface=surface)
    assert t.affected_symbols == ("alpha", "zebra")


# --- build_ticket: derived text fields ---------------------------------------


def test_title_and_region_suffix() -> None:
    t = _build()
    assert t.title.startswith("[MEDIUM] REGION in guide")
    assert "region symbols" in t.title
    assert len(t.title) < 100


def test_title_without_region() -> None:
    t = _build(drift=_drift(kind=DriftKind.HASH, region_id=None, diff=""))
    assert "region" not in t.title.split("in guide")[-1]


def test_summary_and_root_cause() -> None:
    t = _build()
    assert "out of date" in t.summary
    assert "public signature changed" in t.summary
    assert t.root_cause == "public signature changed"


def test_diff_passthrough() -> None:
    assert _build().diff == "--- a\n+++ b\n"
    assert _build(drift=_drift(diff="")).diff == ""


def test_proposed_change_uses_fix_rationale() -> None:
    t = _build(fix=_region_fix())
    assert "regenerate the symbol table" in t.proposed_change


def test_proposed_change_no_fix_invalidate() -> None:
    t = _build(verdict=Verdict.INVALIDATE, fix=None)
    assert "No documentation change needed" in t.proposed_change


def test_proposed_change_no_fix_escalate() -> None:
    t = _build(verdict=Verdict.ESCALATE, fix=None)
    assert "Needs a human author" in t.proposed_change


def test_recommended_action_by_verdict() -> None:
    assert _build(verdict=Verdict.FIX).recommended_action == "Apply the proposed fix"
    assert (
        _build(verdict=Verdict.INVALIDATE, fix=None).recommended_action
        == "Dismiss as not-applicable"
    )
    assert (
        _build(verdict=Verdict.ESCALATE, fix=None).recommended_action
        == "Escalate to a human author"
    )


def test_verdict_and_ids_carried() -> None:
    t = _build()
    assert t.verdict == "FIX"
    assert t.ticket_id == "CDM-abc123"
    assert t.doc_id == "guide"
    assert t.doc_path == "docs/guide.md"
    assert t.region_id == "symbols"
    assert t.audience == "eng-guide"
    assert t.drift_kind == "REGION"


# --- build_ticket: acceptance criteria differ by verdict ---------------------


def test_acceptance_criteria_fix() -> None:
    crit = _build(verdict=Verdict.FIX, fix=_region_fix()).acceptance_criteria
    assert len(crit) == 3
    texts = [c.text for c in crit]
    assert any("current code surface" in t for t in texts)
    assert any("human-owned region" in t for t in texts)
    assert any("cdx lint" in t for t in texts)
    assert crit[0].auto_satisfied is True
    assert crit[-1].auto_satisfied is False


def test_acceptance_criteria_invalidate() -> None:
    crit = _build(verdict=Verdict.INVALIDATE, fix=None).acceptance_criteria
    assert len(crit) == 2
    texts = [c.text for c in crit]
    assert any("non-public surface" in t for t in texts)
    assert any("Public API is unchanged" in t for t in texts)


def test_acceptance_criteria_escalate() -> None:
    crit = _build(verdict=Verdict.ESCALATE, fix=None).acceptance_criteria
    assert len(crit) == 2
    texts = [c.text for c in crit]
    assert any("human has authored" in t for t in texts)
    assert any("in sync with the code surface" in t for t in texts)
    assert all(c.auto_satisfied is False for c in crit)


# --- ticket_status -----------------------------------------------------------


def _resolution(res: Resolution) -> ResolutionRecord:
    return ResolutionRecord(
        record_id="abc123",
        resolution=res,
        resolved_at="2026-06-05T00:00:00Z",
    )


def test_ticket_status_none_is_proposed() -> None:
    assert ticket_status(None) is TicketStatus.PROPOSED


def test_ticket_status_accepted_is_validated() -> None:
    assert ticket_status(_resolution(Resolution.ACCEPTED)) is TicketStatus.VALIDATED


def test_ticket_status_overridden_is_changes_requested() -> None:
    assert (
        ticket_status(_resolution(Resolution.OVERRIDDEN))
        is TicketStatus.CHANGES_REQUESTED
    )


def test_ticket_status_rejected_is_rejected() -> None:
    assert ticket_status(_resolution(Resolution.REJECTED)) is TicketStatus.REJECTED


def test_ticket_status_invalidated_is_rejected() -> None:
    assert ticket_status(_resolution(Resolution.INVALIDATED)) is TicketStatus.REJECTED
