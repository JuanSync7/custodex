"""Time-based document staleness / review SLA (EPIC SLA — pure, K1/K3/K8/K10).

The time-based half of accountability (EPIC OWN was the departure-based half): a
document that has not been re-reviewed within its SLA is flagged so its accountable
owner re-reviews it. CONFIG IS THE SOURCE OF TRUTH (like ownership): a human stamps
``reviewed`` (an ISO date) on the document in config; staleness is then computed here
against an INJECTED ``now`` — never the wall clock (K10) — and the SLA is audience-aware
(a user-guide may get a longer window than an eng-guide, K3).

Pure + offline: no I/O, no backend, no clock read. :func:`detect_stale` is the engine;
:func:`reviewed_docs_from_config` adapts a loaded config into its input.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict

from .config import Audience
from .errors import ConfigError

__all__ = [
    "StalenessStatus",
    "ReviewedDoc",
    "StalenessFinding",
    "resolve_sla_days",
    "grade_doc",
    "detect_stale",
    "reviewed_docs_from_config",
    "render_staleness_text",
]

_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class StalenessStatus(str, Enum):
    """A document's freshness against its review SLA."""

    FRESH = "fresh"  # reviewed within the SLA window
    STALE = "stale"  # reviewed, but longer ago than the SLA allows
    NEVER_REVIEWED = "never_reviewed"  # no `reviewed` stamp at all


class ReviewedDoc(BaseModel):
    """The per-document staleness input: identity, audience + the last review date."""

    model_config = _MODEL_CONFIG

    doc_id: str
    doc_path: str
    audience: Audience
    reviewed: str | None = None  # ISO date the doc was last reviewed (config = truth)


class StalenessFinding(BaseModel):
    """One document's staleness verdict (the engine sorts findings by doc_id, K10)."""

    model_config = _MODEL_CONFIG

    doc_id: str
    doc_path: str
    audience: Audience
    status: StalenessStatus
    reviewed: str | None
    sla_days: int
    age_days: int | None  # days since `reviewed`, or None when never reviewed
    detail: str


def resolve_sla_days(
    audience: Audience,
    *,
    default_days: int,
    audience_days: Mapping[Audience, int] | None = None,
) -> int:
    """The SLA (in days) for an audience: its override if any, else the default (K3)."""
    if audience_days and audience in audience_days:
        return audience_days[audience]
    return default_days


def _parse_iso(value: str, *, field: str) -> datetime:
    """Parse an ISO date/datetime; loud :class:`ConfigError` on a bad value (K8)."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigError(f"{field} is not an ISO date: {value!r}") from exc


def _to_naive_utc(value: datetime) -> datetime:
    """Normalize to naive UTC: an aware datetime is CONVERTED to UTC (not just
    stripped) so two instants compare by true time, not wall-clock; a naive one is
    taken as-is. SLA granularity is days, so this is exact enough."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.replace(tzinfo=None)


def _age_days(reviewed: str, now: str) -> int:
    """Whole days between ``reviewed`` and ``now`` (negative clamped to 0).

    Both are normalized to naive UTC so a bare ``reviewed`` date and a tz-aware ``now``
    compare cleanly by instant.
    """
    n = _to_naive_utc(_parse_iso(now, field="now"))
    r = _to_naive_utc(_parse_iso(reviewed, field="reviewed"))
    return max((n - r).days, 0)


def grade_doc(
    reviewed: str | None, now: str, sla_days: int
) -> tuple[StalenessStatus, int | None, str]:
    """Grade ONE document's freshness against its SLA — the shared core (K3/K8/K10).

    ``reviewed is None`` ⇒ NEVER_REVIEWED; ``age > sla_days`` ⇒ STALE; else FRESH.
    Reused by :func:`detect_stale` (CLI, resolves the SLA per audience) and the server
    ``/staleness`` route (uses the SLA already resolved + mirrored at sync).
    """
    if reviewed is None:
        return (
            StalenessStatus.NEVER_REVIEWED,
            None,
            f"never reviewed; SLA is {sla_days} days",
        )
    age = _age_days(reviewed, now)
    if age > sla_days:
        return (
            StalenessStatus.STALE,
            age,
            f"reviewed {age} days ago; SLA is {sla_days} days — re-review due",
        )
    return (
        StalenessStatus.FRESH,
        age,
        f"reviewed {age} days ago; within the {sla_days}-day SLA",
    )


def detect_stale(
    docs: Sequence[ReviewedDoc],
    *,
    now: str,
    default_days: int,
    audience_days: Mapping[Audience, int] | None = None,
    include_fresh: bool = False,
) -> tuple[StalenessFinding, ...]:
    """Grade each document's freshness against its (audience-aware) review SLA.

    Pure + deterministic (K10): ``now`` is injected (no wall-clock), findings are sorted
    by ``doc_id``. A doc with no ``reviewed`` stamp is ``NEVER_REVIEWED``; one reviewed
    longer than its SLA ago is ``STALE``; otherwise ``FRESH`` (omitted unless
    ``include_fresh``). Audience changes the verdict via :func:`resolve_sla_days` (K3).
    """
    findings: list[StalenessFinding] = []
    for doc in sorted(docs, key=lambda d: d.doc_id):
        sla = resolve_sla_days(
            doc.audience, default_days=default_days, audience_days=audience_days
        )
        status, age, detail = grade_doc(doc.reviewed, now, sla)
        if status is StalenessStatus.FRESH and not include_fresh:
            continue
        findings.append(
            StalenessFinding(
                doc_id=doc.doc_id,
                doc_path=doc.doc_path,
                audience=doc.audience,
                status=status,
                reviewed=doc.reviewed,
                sla_days=sla,
                age_days=age,
                detail=detail,
            )
        )
    return tuple(findings)


def reviewed_docs_from_config(config: object) -> tuple[ReviewedDoc, ...]:
    """Project a loaded config's documents into :class:`ReviewedDoc` inputs (sorted)."""
    docs = [
        ReviewedDoc(
            doc_id=spec.id,
            doc_path=spec.path,
            audience=spec.audience,
            reviewed=spec.reviewed,
        )
        for spec in config.documents  # type: ignore[attr-defined]
    ]
    return tuple(sorted(docs, key=lambda d: d.doc_id))


def render_staleness_text(findings: Sequence[StalenessFinding]) -> str:
    """A deterministic human render of staleness findings (K10)."""
    if not findings:
        return "all documents are fresh (within their review SLA)"
    lines = [f"{len(findings)} document(s) need a review:"]
    for finding in findings:
        lines.append(f"  {finding.doc_id} [{finding.status.value}] — {finding.detail}")
    return "\n".join(lines)
