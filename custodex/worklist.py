"""WL-01 — the per-owner review worklist: one queue per accountable owner.

The accountability JOIN: every document needing a human's attention — an ownership
**orphan** (Pillar C / EPIC OWN), a **staleness** breach (EPIC SLA), or a doc↔doc
**suspect** link (Pillar B) — bucketed under its *accountable* owner so each person
sees ONE prioritised queue instead of three separate reports.

This module JOINS, it never re-detects: :func:`build_worklist` is a pure data join
over the already-computed ``OwnershipFinding`` / ``StalenessFinding`` / ``SuspectLink``
sequences plus the ``EffectiveOwner`` projection (no clock, no I/O, no network — K0/K1/
K10), so the server route can reuse the SAME function with ``suspect=()`` for the K2
partial mirror. :func:`worklist_from_repo` is the one thin impure adapter that runs the
three detectors and hands their output to :func:`build_worklist`.

Bucketing is by *accountable* (``dri → owner → team → inherited`` — the current point of
contact): the worklist routes LIVE work. The exception is an ORPHANED doc, whose
accountable has departed — its work is re-routed to the live assignee the orphan status
implies (a DRI-vacant doc to its still-active *durable* owner; an owner-departed doc to
the unowned bucket), so a "reassign me" item never sits in a departed person's queue. A
document with no live assignee falls into the ``None`` bucket (sorted last).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .config import Audience, MonitorConfig
from .docdeps import SuspectLink, SuspectStatus, detect_suspect_links
from .ownership import (
    EffectiveOwner,
    OwnershipFinding,
    OwnershipStatus,
    RosterSnapshot,
    detect_orphans,
    resolve_ownership,
)
from .staleness import (
    StalenessFinding,
    StalenessStatus,
    detect_stale,
    reviewed_docs_from_config,
)

__all__ = [
    "WorkReason",
    "WorkSeverity",
    "WorkItem",
    "OwnerWorklist",
    "Worklist",
    "build_worklist",
    "worklist_from_repo",
    "render_worklist_text",
]

# Frozen + extra="forbid": a worklist is an immutable snapshot and an unknown key is a
# loud error (K8), mirroring the ownership / staleness / docdeps result models.
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class WorkReason(str, Enum):
    """Why a document is on someone's worklist."""

    ORPHAN = "orphan"  # the accountable owner departed / the doc is unowned (EPIC OWN)
    STALE = "stale"  # past its review SLA / never reviewed (EPIC SLA)
    SUSPECT = "suspect"  # a doc↔doc upstream changed / edge unstamped (Pillar B)


class WorkSeverity(str, Enum):
    """Priority of a work item — drives the queue ordering (high first)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Deterministic rank maps (K10): lower sorts first.
_SEVERITY_RANK = {WorkSeverity.HIGH: 0, WorkSeverity.MEDIUM: 1, WorkSeverity.LOW: 2}
_REASON_RANK = {WorkReason.ORPHAN: 0, WorkReason.STALE: 1, WorkReason.SUSPECT: 2}

# A finding's status → its work severity. Anything unmapped falls back to MEDIUM, so a
# new status can never crash the join (K8) — it just gets a sane default priority. NOTE:
# callers pass only ACTIONABLE findings (the detectors omit OK/FRESH by default), so the
# non-actionable statuses are deliberately absent here (not mapped to a no-op severity).
_ORPHAN_SEVERITY = {
    OwnershipStatus.ORPHAN_OWNER_DEPARTED: WorkSeverity.HIGH,
    OwnershipStatus.ORPHAN_DRI_VACANT: WorkSeverity.MEDIUM,
    OwnershipStatus.UNOWNED: WorkSeverity.MEDIUM,
}
_STALE_SEVERITY = {
    StalenessStatus.NEVER_REVIEWED: WorkSeverity.HIGH,
    StalenessStatus.STALE: WorkSeverity.MEDIUM,
}
_SUSPECT_SEVERITY = {
    SuspectStatus.SUSPECT: WorkSeverity.HIGH,
    SuspectStatus.MISSING_UPSTREAM: WorkSeverity.HIGH,
    SuspectStatus.UNSTAMPED: WorkSeverity.LOW,
    SuspectStatus.SUSPECT_TRANSITIVE: WorkSeverity.LOW,
}


class WorkItem(BaseModel):
    """One unit of attention: a (document, reason), with the upstream for a suspect.

    A single document can appear as MULTIPLE items (e.g. both stale AND suspect, or
    suspect on two different upstream edges), so the worklist granularity is per
    ``(doc_id, reason, upstream_id)`` — never collapsed, so no reason is hidden.
    """

    model_config = _MODEL_CONFIG

    doc_id: str
    doc_path: str
    audience: Audience  # the DOWNSTREAM/owning doc's audience (K3)
    reason: WorkReason
    severity: WorkSeverity
    detail: str
    upstream_id: str | None = None  # the changed upstream, for a SUSPECT item


class OwnerWorklist(BaseModel):
    """One accountable owner's prioritised queue (``accountable is None`` ⇒ unowned)."""

    model_config = _MODEL_CONFIG

    accountable: str | None
    items: tuple[WorkItem, ...]
    item_count: int  # number of work items (a doc may contribute several)
    doc_count: int  # number of DISTINCT documents (so the UI never double-counts)


class Worklist(BaseModel):
    """The whole worklist — owners sorted, with the unowned bucket last (K10)."""

    model_config = _MODEL_CONFIG

    owners: tuple[OwnerWorklist, ...]
    item_count: int
    doc_count: int
    # False when suspect links were intentionally omitted (the central hub: it has the
    # GRAPH but not the doc bodies needed to hash an upstream, so suspect STATUS is
    # repo-local — K2). An honest flag so a client never mistakes a partial worklist
    # for a complete one.
    includes_suspect: bool = True


def _item_sort_key(item: WorkItem) -> tuple[int, int, str, str]:
    return (
        _SEVERITY_RANK[item.severity],
        _REASON_RANK[item.reason],
        item.doc_id,
        item.upstream_id or "",
    )


def build_worklist(
    owners: Sequence[EffectiveOwner],
    *,
    orphans: Sequence[OwnershipFinding] = (),
    stale: Sequence[StalenessFinding] = (),
    suspect: Sequence[SuspectLink] = (),
    owner_filter: str | None = None,
    includes_suspect: bool = True,
) -> Worklist:
    """Join the three attention signals into a per-owner worklist (pure, K1/K10).

    Each finding is turned into a :class:`WorkItem` and bucketed under its document's
    LIVE assignee (looked up from ``owners`` by ``doc_id``; missing ⇒ the unowned
    ``None`` bucket). Normally that is the *accountable* owner — but an ORPHANED doc's
    accountable has, by construction, DEPARTED, so routing work there is a dead queue.
    EVERY item for an orphaned doc is re-routed to the live assignee the orphan STATUS
    implies: an ``ORPHAN_DRI_VACANT`` doc to its still-active durable owner (the
    "assign a new DRI" target), an ``ORPHAN_OWNER_DEPARTED`` doc (no active fallback) to
    the unowned bucket. ``owner_filter`` keeps only that one NAMED owner's bucket (the
    unowned ``None`` bucket cannot be isolated this way — ``None`` means "no filter").
    ``suspect`` accepts ANY :class:`SuspectLink` — direct OR the ``SUSPECT_TRANSITIVE``
    advisory —
    so the function is unchanged whether or not propagation is in play; pass
    ``includes_suspect=False`` (with ``suspect=()``) to flag a deliberately suspect-less
    worklist (the hub's K2 mirror). Owners sorted (unowned last); items sorted by
    ``(severity, reason, doc_id, upstream_id)``; counts derived from the items (never
    summed across the inputs, so a doc that is stale AND suspect is one doc, two items).
    """
    accountable_by_doc = {owner.doc_id: owner.accountable for owner in owners}
    durable_by_doc = {owner.doc_id: owner.durable for owner in owners}
    # An orphaned document's accountable owner has departed — re-route its work to the
    # live assignee the orphan STATUS implies (DRI-vacant ⇒ the still-active durable
    # owner; owner-departed ⇒ no active fallback ⇒ the unowned bucket). UNOWNED docs
    # already resolve to None, so they need no override.
    reassign: dict[str, str | None] = {}
    for orphan in orphans:
        if orphan.status is OwnershipStatus.ORPHAN_DRI_VACANT:
            reassign[orphan.doc_id] = durable_by_doc.get(orphan.doc_id)
        elif orphan.status is OwnershipStatus.ORPHAN_OWNER_DEPARTED:
            reassign[orphan.doc_id] = None

    buckets: dict[str | None, list[WorkItem]] = {}

    def _add(item: WorkItem) -> None:
        bucket = (
            reassign[item.doc_id]
            if item.doc_id in reassign
            else accountable_by_doc.get(item.doc_id)
        )
        buckets.setdefault(bucket, []).append(item)

    for orphan in orphans:
        _add(
            WorkItem(
                doc_id=orphan.doc_id,
                doc_path=orphan.doc_path,
                audience=orphan.audience,
                reason=WorkReason.ORPHAN,
                severity=_ORPHAN_SEVERITY.get(orphan.status, WorkSeverity.MEDIUM),
                detail=orphan.detail,
            )
        )
    for finding in stale:
        _add(
            WorkItem(
                doc_id=finding.doc_id,
                doc_path=finding.doc_path,
                audience=finding.audience,
                reason=WorkReason.STALE,
                severity=_STALE_SEVERITY.get(finding.status, WorkSeverity.MEDIUM),
                detail=finding.detail,
            )
        )
    for link in suspect:
        _add(
            WorkItem(
                doc_id=link.doc_id,
                doc_path=link.doc_path,
                audience=link.audience,
                reason=WorkReason.SUSPECT,
                severity=_SUSPECT_SEVERITY.get(link.status, WorkSeverity.MEDIUM),
                detail=link.detail,
                upstream_id=link.upstream_id,
            )
        )

    owner_lists: list[OwnerWorklist] = []
    for accountable, items in buckets.items():
        if owner_filter is not None and accountable != owner_filter:
            continue
        ordered = tuple(sorted(items, key=_item_sort_key))
        owner_lists.append(
            OwnerWorklist(
                accountable=accountable,
                items=ordered,
                item_count=len(ordered),
                doc_count=len({item.doc_id for item in ordered}),
            )
        )
    # Unowned (None) bucket sorts last; named owners alphabetical (K10).
    owner_lists.sort(key=lambda w: (w.accountable is None, w.accountable or ""))

    all_items = [item for w in owner_lists for item in w.items]
    return Worklist(
        owners=tuple(owner_lists),
        item_count=len(all_items),
        doc_count=len({item.doc_id for item in all_items}),
        includes_suspect=includes_suspect,
    )


def worklist_from_repo(
    config: MonitorConfig,
    root: Path,
    *,
    now: str,
    roster: RosterSnapshot | None = None,
    unit_owner: Mapping[str, str] | None = None,
    include_suspect: bool = True,
    owner_filter: str | None = None,
) -> Worklist:
    """Run the three detectors over a loaded repo, then :func:`build_worklist` (impure).

    The one place the worklist touches the detectors. ``now`` is INJECTED (no clock
    read, K10). Orphan detection needs the central ``roster`` mirror; without it (a
    repo with no roster) there are no departures to flag, so orphans are empty.
    ``include_suspect`` runs the doc-doc detector repo-side; the hub passes ``False``
    (no body to hash an upstream, K2) and the ``includes_suspect`` flag records that.
    """
    owners = resolve_ownership(config, unit_owner=unit_owner)
    orphans = detect_orphans(owners, roster) if roster is not None else ()
    stale = detect_stale(
        reviewed_docs_from_config(config),
        now=now,
        default_days=config.staleness.default_days,
        audience_days=config.staleness.audience_days,
    )
    suspect = detect_suspect_links(config, root) if include_suspect else ()
    return build_worklist(
        owners,
        orphans=orphans,
        stale=stale,
        suspect=suspect,
        owner_filter=owner_filter,
        includes_suspect=include_suspect,
    )


def render_worklist_text(worklist: Worklist) -> str:
    """A deterministic plain-text worklist report (K10) — the ``cdx worklist`` view."""
    header = (
        f"# Worklist — {worklist.item_count} item(s) across {worklist.doc_count} "
        f"document(s), {len(worklist.owners)} owner(s)"
    )
    lines = [header]
    if not worklist.includes_suspect:
        lines.append("  (suspect-link items omitted — this is the central mirror, K2)")
    if not worklist.owners:
        lines.append("")
        lines.append("  nothing needs review — all clear")
        return "\n".join(lines)
    for owner in worklist.owners:
        name = owner.accountable if owner.accountable is not None else "(unowned)"
        lines.append("")
        lines.append(
            f"  {name}: {owner.item_count} item(s) across {owner.doc_count} doc(s)"
        )
        for item in owner.items:
            target = item.doc_id
            if item.upstream_id is not None:
                target = f"{item.doc_id} → {item.upstream_id}"
            tag = f"[{item.severity.value}] {item.reason.value}"
            lines.append(f"    {tag} {target} — {item.detail}")
    return "\n".join(lines)
