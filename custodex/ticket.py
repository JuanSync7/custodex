"""The structured DriftTicket the agent fills and a human validates (T-01).

A :class:`DriftTicket` replaces the one-liner ``ProposedFix.rationale`` with a
Jira-style artifact: title, summary, severity, affected symbols, root cause,
proposed change + diff, and an explicit acceptance checklist a reviewer ticks
off. :func:`build_ticket` derives every field from inputs already present in
``monitor._record_for`` — it is PURE and DETERMINISTIC (K1/K10): no clock, no
I/O, same inputs always yield an identical ticket. :func:`ticket_status` maps a
human :class:`~custodex.schema.ResolutionRecord` outcome to a status.

No new dependencies (K0): stdlib + pydantic only. To avoid an import cycle
(``schema`` imports :class:`DriftTicket`, ``backends`` imports ``schema``) this
module imports ``Verdict``/``ProposedFix``/``Resolution`` only lazily inside the
functions and under ``TYPE_CHECKING`` for annotations — never ``backends``.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from .drift import Drift
    from .extract import DocumentSurface
    from .schema import ProposedFix, ResolutionRecord, Verdict

__all__ = [
    "TicketSeverity",
    "TicketStatus",
    "AcceptanceCheck",
    "DriftTicket",
    "build_ticket",
    "ticket_status",
]

# Frozen + extra="forbid": a ticket is an immutable, audited artifact and an
# unexpected key is a loud error, not a silent pass (K8).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class TicketSeverity(str, Enum):
    """How urgently a human should look at a drift ticket."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TicketStatus(str, Enum):
    """The validation state of a ticket, derived from the human resolution."""

    PROPOSED = "proposed"
    VALIDATED = "validated"
    CHANGES_REQUESTED = "changes-requested"
    REJECTED = "rejected"


class AcceptanceCheck(BaseModel):
    """One acceptance-criterion line a reviewer confirms (K8 immutable).

    ``auto_satisfied`` is the agent's CLAIM that the proposed change already
    meets this criterion; the human still confirms it.
    """

    model_config = _MODEL_CONFIG

    text: str
    auto_satisfied: bool = False


class DriftTicket(BaseModel):
    """The structured, human-validatable artifact for one handled drift (K6).

    Frozen + ``extra="forbid"``: an immutable audited artifact (K8). Built
    deterministically from the drift/verdict/cause/fix/surface (K10), never from
    a clock or I/O. Carries a ``schema_version`` and is emitted from the model.
    """

    model_config = _MODEL_CONFIG

    schema_version: str = "1.0.0"
    ticket_id: str
    title: str
    summary: str
    severity: TicketSeverity
    drift_kind: str
    doc_id: str
    doc_path: str
    region_id: str | None = None
    audience: str
    affected_symbols: tuple[str, ...] = ()
    root_cause: str
    proposed_change: str
    change_kind: str  # "region" | "whole-doc" | "none"
    diff: str = ""
    acceptance_criteria: tuple[AcceptanceCheck, ...] = ()
    verdict: str
    recommended_action: str


def _severity(drift: Drift, verdict: Verdict) -> TicketSeverity:
    """Deterministic severity: ESCALATE/UNHEALABLE/unhealable HIGH, else by verdict."""
    from .drift import DriftKind
    from .schema import Verdict

    if (
        verdict is Verdict.ESCALATE
        or drift.kind is DriftKind.UNHEALABLE
        or not drift.healable
    ):
        return TicketSeverity.HIGH
    if verdict is Verdict.INVALIDATE:
        return TicketSeverity.LOW
    return TicketSeverity.MEDIUM


def _change_kind(fix: ProposedFix | None) -> str:
    """Classify a fix shape: region / whole-doc / none."""
    if fix is None:
        return "none"
    if fix.region_id is not None or fix.new_region_body is not None:
        return "region"
    if fix.new_doc_text is not None:
        return "whole-doc"
    return "none"


def _proposed_change(verdict: Verdict, cause: str, fix: ProposedFix | None) -> str:
    """The proposed change text: the fix rationale, or a verdict-aware no-fix line."""
    from .schema import Verdict

    if fix is not None:
        return fix.rationale
    if verdict is Verdict.INVALIDATE:
        return f"No documentation change needed — {cause}"
    return f"Needs a human author — {cause}"


def _recommended_action(verdict: Verdict) -> str:
    """The single next action a reviewer should take, by verdict."""
    from .schema import Verdict

    if verdict is Verdict.INVALIDATE:
        return "Dismiss as not-applicable"
    if verdict is Verdict.ESCALATE:
        return "Escalate to a human author"
    return "Apply the proposed fix"


def _acceptance_criteria(verdict: Verdict) -> tuple[AcceptanceCheck, ...]:
    """The verdict-aware acceptance checklist (deterministic)."""
    from .schema import Verdict

    if verdict is Verdict.INVALIDATE:
        return (
            AcceptanceCheck(
                text=(
                    "Change is confined to non-public surface "
                    "(docstring/comment/private)"
                ),
                auto_satisfied=True,
            ),
            AcceptanceCheck(text="Public API is unchanged", auto_satisfied=False),
        )
    if verdict is Verdict.ESCALATE:
        return (
            AcceptanceCheck(
                text="A human has authored the missing/owned content",
                auto_satisfied=False,
            ),
            AcceptanceCheck(
                text="The new content is in sync with the code surface",
                auto_satisfied=False,
            ),
        )
    return (
        AcceptanceCheck(
            text="Proposed text matches the current code surface",
            auto_satisfied=True,
        ),
        AcceptanceCheck(
            text="No human-owned region is modified",
            auto_satisfied=True,
        ),
        AcceptanceCheck(
            text="Document still passes `cdx lint`",
            auto_satisfied=False,
        ),
    )


def build_ticket(
    *,
    drift: Drift,
    verdict: Verdict,
    cause: str,
    fix: ProposedFix | None,
    surface: DocumentSurface,
    ticket_id: str,
) -> DriftTicket:
    """Build a :class:`DriftTicket` from a handled drift — PURE/DETERMINISTIC (K1/K10).

    Derives every field from inputs already in ``monitor._record_for`` (the
    drift, the verdict/cause/fix, the code surface) with no clock and no I/O, so
    the same inputs always yield an identical ticket.
    """
    severity = _severity(drift, verdict)
    region_suffix = f" · region {drift.region_id}" if drift.region_id else ""
    title = (
        f"[{severity.value.upper()}] {drift.kind.value} "
        f"in {drift.doc_id}{region_suffix}"
    )
    summary = f"{drift.detail} The remediation agent's read: {cause}"
    affected = tuple(sorted(s.name for s in surface.symbols if s.is_public))
    return DriftTicket(
        ticket_id=ticket_id,
        title=title,
        summary=summary,
        severity=severity,
        drift_kind=drift.kind.value,
        doc_id=drift.doc_id,
        doc_path=drift.doc_path,
        region_id=drift.region_id,
        audience=drift.audience.value,
        affected_symbols=affected,
        root_cause=cause,
        proposed_change=_proposed_change(verdict, cause, fix),
        change_kind=_change_kind(fix),
        diff=drift.diff,
        acceptance_criteria=_acceptance_criteria(verdict),
        verdict=verdict.value,
        recommended_action=_recommended_action(verdict),
    )


def ticket_status(resolution: ResolutionRecord | None) -> TicketStatus:
    """Map a human :class:`ResolutionRecord` outcome to a :class:`TicketStatus` (pure).

    ``None`` (no resolution yet) maps to ``PROPOSED``; ``accepted`` to
    ``VALIDATED``; ``overridden`` to ``CHANGES_REQUESTED``; ``rejected`` and
    ``invalidated`` both to ``REJECTED``.
    """
    from .schema import Resolution

    if resolution is None:
        return TicketStatus.PROPOSED
    if resolution.resolution is Resolution.ACCEPTED:
        return TicketStatus.VALIDATED
    if resolution.resolution is Resolution.OVERRIDDEN:
        return TicketStatus.CHANGES_REQUESTED
    return TicketStatus.REJECTED
