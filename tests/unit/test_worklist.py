"""WL-01 — the per-owner review worklist (pure join of orphan + stale + suspect).

Pins the join contract (K0/K1/K10): every attention signal is bucketed under its
document's *accountable* owner, a doc with multiple problems yields multiple items
(distinct doc_count), owners sort with the unowned bucket last, items sort by
(severity, reason, doc_id, upstream_id), and the central-mirror path carries an honest
``includes_suspect=False`` flag. Hand-built findings: no I/O, no clock.

Features: FEAT-WORKLIST-001
"""

from __future__ import annotations

from custodex.config import Audience, DocEdgeType
from custodex.docdeps import SuspectLink, SuspectStatus
from custodex.ownership import EffectiveOwner, OwnershipFinding, OwnershipStatus
from custodex.staleness import StalenessFinding, StalenessStatus
from custodex.worklist import (
    WorkReason,
    WorkSeverity,
    build_worklist,
    render_worklist_text,
)


def _owner(doc_id: str, accountable: str | None) -> EffectiveOwner:
    return EffectiveOwner(
        doc_id=doc_id,
        doc_path=f"docs/{doc_id}.md",
        audience=Audience.ENG_GUIDE,
        accountable=accountable,
    )


def _orphan(doc_id: str, status: OwnershipStatus) -> OwnershipFinding:
    return OwnershipFinding(
        doc_id=doc_id,
        doc_path=f"docs/{doc_id}.md",
        audience=Audience.ENG_GUIDE,
        status=status,
        detail="orphan detail",
    )


def _stale(doc_id: str, status: StalenessStatus) -> StalenessFinding:
    return StalenessFinding(
        doc_id=doc_id,
        doc_path=f"docs/{doc_id}.md",
        audience=Audience.ENG_GUIDE,
        status=status,
        reviewed=None,
        sla_days=90,
        age_days=None,
        detail="stale detail",
    )


def _suspect(doc_id: str, upstream_id: str, status: SuspectStatus) -> SuspectLink:
    return SuspectLink(
        doc_id=doc_id,
        doc_path=f"docs/{doc_id}.md",
        upstream_id=upstream_id,
        type=DocEdgeType.DEPENDS,
        status=status,
        detail="suspect detail",
        audience=Audience.ENG_GUIDE,
    )


# --------------------------------------------------------------------------- #
# bucketing by accountable owner
# --------------------------------------------------------------------------- #
def test_items_bucket_under_their_accountable_owner() -> None:
    owners = (_owner("a", "alice"), _owner("b", "bob"))
    wl = build_worklist(
        owners,
        stale=(_stale("a", StalenessStatus.STALE),),
        suspect=(_suspect("b", "up", SuspectStatus.SUSPECT),),
    )
    by_owner = {w.accountable: [i.doc_id for i in w.items] for w in wl.owners}
    assert by_owner == {"alice": ["a"], "bob": ["b"]}


def test_unowned_doc_goes_to_none_bucket_sorted_last() -> None:
    owners = (_owner("a", "alice"), _owner("z", None))
    wl = build_worklist(
        owners,
        stale=(_stale("a", StalenessStatus.STALE), _stale("z", StalenessStatus.STALE)),
    )
    # None (unowned) bucket sorts last, after named owners.
    assert [w.accountable for w in wl.owners] == ["alice", None]


def test_finding_for_unknown_doc_falls_into_none_bucket() -> None:
    # A finding whose doc_id is not in `owners` has no accountable → unowned bucket.
    wl = build_worklist((), stale=(_stale("ghost", StalenessStatus.STALE),))
    assert [w.accountable for w in wl.owners] == [None]


# --------------------------------------------------------------------------- #
# one doc, multiple reasons → multiple items, distinct doc_count
# --------------------------------------------------------------------------- #
def test_one_doc_with_three_problems_is_three_items_one_doc() -> None:
    owners = (_owner("a", "alice"),)
    wl = build_worklist(
        owners,
        orphans=(_orphan("a", OwnershipStatus.ORPHAN_DRI_VACANT),),
        stale=(_stale("a", StalenessStatus.STALE),),
        suspect=(_suspect("a", "up", SuspectStatus.SUSPECT),),
    )
    (alice,) = wl.owners
    assert alice.item_count == 3
    assert alice.doc_count == 1  # all three items are the SAME document
    assert {i.reason for i in alice.items} == {
        WorkReason.ORPHAN,
        WorkReason.STALE,
        WorkReason.SUSPECT,
    }
    # top-level counts are derived from items, not summed across inputs.
    assert wl.item_count == 3 and wl.doc_count == 1


def test_two_suspect_edges_on_one_doc_are_two_items() -> None:
    owners = (_owner("a", "alice"),)
    wl = build_worklist(
        owners,
        suspect=(
            _suspect("a", "up2", SuspectStatus.SUSPECT),
            _suspect("a", "up1", SuspectStatus.SUSPECT),
        ),
    )
    (alice,) = wl.owners
    assert alice.item_count == 2 and alice.doc_count == 1
    # sorted by upstream_id within the same (severity, reason, doc).
    assert [i.upstream_id for i in alice.items] == ["up1", "up2"]


# --------------------------------------------------------------------------- #
# item ordering — severity, then reason, then doc_id, then upstream_id
# --------------------------------------------------------------------------- #
def test_items_sorted_by_severity_then_reason() -> None:
    owners = (_owner("a", "alice"),)
    wl = build_worklist(
        owners,
        # ORPHAN_DRI_VACANT = MEDIUM; STALE = MEDIUM; SUSPECT = HIGH
        orphans=(_orphan("a", OwnershipStatus.ORPHAN_DRI_VACANT),),
        stale=(_stale("a", StalenessStatus.STALE),),
        suspect=(_suspect("a", "u", SuspectStatus.SUSPECT),),
    )
    (alice,) = wl.owners
    # HIGH suspect first; then the two MEDIUMs by reason rank (orphan < stale).
    assert [(i.severity, i.reason) for i in alice.items] == [
        (WorkSeverity.HIGH, WorkReason.SUSPECT),
        (WorkSeverity.MEDIUM, WorkReason.ORPHAN),
        (WorkSeverity.MEDIUM, WorkReason.STALE),
    ]


def test_severity_mapping_per_status() -> None:
    owners = (_owner("a", "x"),)
    H, M, L = WorkSeverity.HIGH, WorkSeverity.MEDIUM, WorkSeverity.LOW

    def sev(**kw: object) -> WorkSeverity:
        return build_worklist(owners, **kw).owners[0].items[0].severity  # type: ignore[arg-type]

    assert sev(orphans=(_orphan("a", OwnershipStatus.ORPHAN_OWNER_DEPARTED),)) is H
    assert sev(stale=(_stale("a", StalenessStatus.NEVER_REVIEWED),)) is H
    assert sev(stale=(_stale("a", StalenessStatus.STALE),)) is M
    assert sev(suspect=(_suspect("a", "u", SuspectStatus.UNSTAMPED),)) is L
    assert sev(suspect=(_suspect("a", "u", SuspectStatus.SUSPECT_TRANSITIVE),)) is L


# --------------------------------------------------------------------------- #
# owner_filter + includes_suspect flag + empty
# --------------------------------------------------------------------------- #
def test_owner_filter_keeps_only_that_owner() -> None:
    owners = (_owner("a", "alice"), _owner("b", "bob"))
    wl = build_worklist(
        owners,
        stale=(_stale("a", StalenessStatus.STALE), _stale("b", StalenessStatus.STALE)),
        owner_filter="alice",
    )
    assert [w.accountable for w in wl.owners] == ["alice"]
    assert wl.item_count == 1


def test_includes_suspect_flag_is_honest() -> None:
    owners = (_owner("a", "alice"),)
    # the hub path: no suspect links, flag says so.
    wl = build_worklist(
        owners, stale=(_stale("a", StalenessStatus.STALE),), includes_suspect=False
    )
    assert wl.includes_suspect is False
    assert "central mirror" in render_worklist_text(wl)


def test_empty_worklist_is_all_clear() -> None:
    wl = build_worklist((_owner("a", "alice"),))
    assert wl.owners == () and wl.item_count == 0 and wl.doc_count == 0
    assert "all clear" in render_worklist_text(wl)


def test_render_lists_owner_and_items() -> None:
    owners = (_owner("a", "alice"),)
    wl = build_worklist(owners, suspect=(_suspect("a", "up", SuspectStatus.SUSPECT),))
    text = render_worklist_text(wl)
    assert "alice" in text and "a → up" in text and "[high] suspect" in text
