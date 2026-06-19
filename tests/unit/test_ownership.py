"""EPIC OWN (OWN-01) — per-document ownership-of-record + the pure resolver.

Pins the Tier-1 contract: ``DocumentSpec`` carries optional ``owner``/``team``/
``dri`` (additive, K6), they round-trip through ``dump_unit_file``/``load_unit_file``
byte-identically (K7), and ``ownership.resolve_ownership`` resolves each document's
``accountable`` (dri→owner→team→inherited unit owner) and ``durable`` (team→owner→
inherited) identity, sorted, clock-free (K1/K10). The roster models (``Identity``/
``RosterSnapshot``) are the offline, injected mirror an unknown/departed name reads
as inactive against.

Features: FEAT-OWNERSHIP-001, FEAT-OWNERSHIP-002, FEAT-OWNERSHIP-003
"""

from __future__ import annotations

from pathlib import Path

from code_doc_monitor.config import (
    Audience,
    DocumentSpec,
    MonitorConfig,
    UnitFile,
    UnitFrontmatter,
    dump_unit_file,
    load_unit_file,
)
from code_doc_monitor.ownership import (
    EffectiveOwner,
    Identity,
    OwnershipFinding,
    OwnershipStatus,
    RosterSnapshot,
    detect_orphans,
    resolve_ownership,
)

NOW = "2026-06-19"


def _owned_unit() -> UnitFile:
    """A unit whose first doc carries owner+team+dri; the second is unowned."""
    fm = UnitFrontmatter(
        **{
            "cdmon-config-version": "2.0.0",
            "unit": "core",
            "title": "core engine",
            "owner": "platform-team",
            "created": "2026-06-07",
            "updated": NOW,
        }
    )
    owned = DocumentSpec(
        id="foundation",
        path="docs/api/foundation.md",
        audience=Audience.ENG_GUIDE,
        owner="alice",
        team="platform-team",
        dri="alice",
    )
    bare = DocumentSpec(
        id="api-index",
        path="docs/api/index.md",
        audience=Audience.USER_GUIDE,
        index=True,
    )
    return UnitFile(
        **{
            "frontmatter": fm,
            "dir-covered": ("code_doc_monitor",),
            "source-files-format": (".py",),
            "documents": (owned, bare),
        }
    )


# ── Tier-1 config fields ─────────────────────────────────────────────────────


def test_document_spec_ownership_defaults_none() -> None:
    """owner/team/dri are optional and default to None (back-compat, K6)."""
    doc = DocumentSpec(id="d", path="p.md", audience=Audience.ENG_GUIDE)
    assert doc.owner is None and doc.team is None and doc.dri is None


def test_document_spec_accepts_ownership() -> None:
    doc = DocumentSpec(
        id="d",
        path="p.md",
        audience=Audience.ENG_GUIDE,
        owner="bob",
        team="t",
        dri="bob",
    )
    assert (doc.owner, doc.team, doc.dri) == ("bob", "t", "bob")


def test_ownership_round_trips(tmp_path: Path) -> None:
    """A doc with owner/team/dri survives dump→load equal AND idempotent (K7)."""
    unit = _owned_unit()
    text1 = dump_unit_file(unit, now=NOW)
    p = tmp_path / "core.yaml"
    p.write_text(text1, encoding="utf-8")
    reloaded = load_unit_file(p)
    assert reloaded == unit
    assert dump_unit_file(reloaded, now=NOW) == text1


def test_unowned_doc_emits_no_ownership_keys(tmp_path: Path) -> None:
    """Defaults are dropped — an unowned doc serializes without owner keys."""
    text = dump_unit_file(_owned_unit(), now=NOW)
    # The second (unowned) doc block must not introduce owner/team/dri keys.
    api_index_block = text.split("id: api-index", 1)[1]
    assert "owner:" not in api_index_block
    assert "team:" not in api_index_block
    assert "dri:" not in api_index_block


# ── Roster models ────────────────────────────────────────────────────────────


def test_identity_defaults() -> None:
    me = Identity(name="alice")
    assert me.kind == "person" and me.active is True and me.departed_at is None
    assert me.teams == ()


def test_roster_is_active() -> None:
    roster = RosterSnapshot(
        identities=(
            Identity(name="alice", active=True),
            Identity(name="carol", active=False, departed_at="2026-01-01T00:00:00Z"),
        )
    )
    assert roster.is_active("alice") is True
    assert roster.is_active("carol") is False
    assert roster.is_active("nobody") is False  # unknown name → inactive
    assert roster.is_active(None) is False  # no name at all → inactive
    assert roster.get("alice") is not None and roster.get("ghost") is None


# ── resolve_ownership ────────────────────────────────────────────────────────


def _cfg(*docs: DocumentSpec) -> MonitorConfig:
    return MonitorConfig(documents=docs)


def test_resolve_precedence_and_sorted() -> None:
    """accountable = dri→owner→team→unit; durable = team→owner→unit; sorted by id."""
    cfg = _cfg(
        DocumentSpec(
            id="z",
            path="z.md",
            audience=Audience.ENG_GUIDE,
            dri="dee",
            owner="ohh",
            team="tee",
        ),
        DocumentSpec(
            id="a", path="a.md", audience=Audience.ENG_GUIDE, owner="ohh", team="tee"
        ),
        DocumentSpec(id="m", path="m.md", audience=Audience.ENG_GUIDE, team="tee"),
        DocumentSpec(id="bare", path="b.md", audience=Audience.USER_GUIDE),
    )
    owners = resolve_ownership(cfg, unit_owner={"bare": "inherited-team"})
    assert [o.doc_id for o in owners] == ["a", "bare", "m", "z"]  # sorted
    by_id = {o.doc_id: o for o in owners}
    assert (by_id["z"].accountable, by_id["z"].durable) == ("dee", "tee")
    assert (by_id["a"].accountable, by_id["a"].durable) == ("ohh", "tee")
    assert (by_id["m"].accountable, by_id["m"].durable) == ("tee", "tee")
    # the bare doc inherits the unit owner as both accountable and durable
    assert (by_id["bare"].accountable, by_id["bare"].durable) == (
        "inherited-team",
        "inherited-team",
    )


def test_resolve_no_fallback_leaves_none() -> None:
    owners = resolve_ownership(
        _cfg(DocumentSpec(id="x", path="x.md", audience=Audience.ENG_GUIDE))
    )
    assert owners[0].accountable is None and owners[0].durable is None


def test_resolve_empty_config() -> None:
    assert resolve_ownership(_cfg()) == ()


def test_effective_owner_carries_raw_fields() -> None:
    owners = resolve_ownership(
        _cfg(
            DocumentSpec(
                id="x",
                path="x.md",
                audience=Audience.ENG_GUIDE,
                owner="o",
                team="t",
                dri="d",
            )
        )
    )
    o = owners[0]
    assert isinstance(o, EffectiveOwner)
    assert (o.owner, o.team, o.dri) == ("o", "t", "d")
    assert o.doc_path == "x.md" and o.audience == Audience.ENG_GUIDE


# ── detect_orphans (OWN-02) ──────────────────────────────────────────────────


def _eo(**owner_kw: str) -> EffectiveOwner:
    """One resolved EffectiveOwner via the real resolver (accountable/durable)."""
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(id="d", path="d.md", audience=Audience.ENG_GUIDE, **owner_kw),
        )
    )
    return resolve_ownership(cfg)[0]


def _roster(*pairs: tuple[str, bool]) -> RosterSnapshot:
    return RosterSnapshot(
        identities=tuple(Identity(name=n, active=a) for n, a in pairs)
    )


def test_unowned_when_no_identity_named() -> None:
    findings = detect_orphans((_eo(),), _roster())
    assert len(findings) == 1
    assert findings[0].status is OwnershipStatus.UNOWNED


def test_ok_active_dri_is_omitted_by_default() -> None:
    findings = detect_orphans(
        (_eo(owner="o", team="t", dri="alice"),), _roster(("alice", True))
    )
    assert findings == ()  # OK findings omitted unless include_ok


def test_ok_active_dri_included_when_asked() -> None:
    findings = detect_orphans(
        (_eo(owner="o", team="t", dri="alice"),),
        _roster(("alice", True)),
        include_ok=True,
    )
    assert [f.status for f in findings] == [OwnershipStatus.OK]


def test_dri_vacant_when_dri_departed_but_team_active() -> None:
    # accountable=alice (departed), durable=platform (active) → soft orphan
    finding = detect_orphans(
        (_eo(team="platform", dri="alice"),),
        _roster(("alice", False), ("platform", True)),
    )[0]
    assert finding.status is OwnershipStatus.ORPHAN_DRI_VACANT
    assert finding.accountable == "alice" and "platform" in finding.detail


def test_owner_departed_when_dri_and_team_both_gone() -> None:
    finding = detect_orphans(
        (_eo(team="platform", dri="alice"),),
        _roster(("alice", False), ("platform", False)),
    )[0]
    assert finding.status is OwnershipStatus.ORPHAN_OWNER_DEPARTED


def test_lone_owner_departed() -> None:
    finding = detect_orphans((_eo(owner="bob"),), _roster(("bob", False)))[0]
    assert finding.status is OwnershipStatus.ORPHAN_OWNER_DEPARTED


def test_lone_team_disbanded() -> None:
    # only a team, the team itself is inactive → owner-departed (no DRI to vacate)
    finding = detect_orphans((_eo(team="ghosts"),), _roster(("ghosts", False)))[0]
    assert finding.status is OwnershipStatus.ORPHAN_OWNER_DEPARTED


def test_unknown_name_reads_as_departed() -> None:
    # an accountable name no roster knows is not a silently-OK owner (K8)
    finding = detect_orphans((_eo(owner="nobody"),), _roster())[0]
    assert finding.status is OwnershipStatus.ORPHAN_OWNER_DEPARTED


def test_findings_sorted_and_each_doc_classified_with_include_ok() -> None:
    owners = (
        _named_eo("z", owner="bob"),
        _named_eo("a", dri="alice", team="t"),
        _named_eo("m"),
    )
    roster = _roster(("alice", True), ("bob", False))
    findings = detect_orphans(owners, roster, include_ok=True)
    assert [f.doc_id for f in findings] == ["a", "m", "z"]  # sorted, one per doc
    assert all(isinstance(f, OwnershipFinding) for f in findings)
    by_id = {f.doc_id: f.status for f in findings}
    assert by_id["a"] is OwnershipStatus.OK
    assert by_id["m"] is OwnershipStatus.UNOWNED
    assert by_id["z"] is OwnershipStatus.ORPHAN_OWNER_DEPARTED


def test_detect_empty() -> None:
    assert detect_orphans((), _roster()) == ()


def _named_eo(doc_id: str, **owner_kw: str) -> EffectiveOwner:
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(
                id=doc_id, path=f"{doc_id}.md", audience=Audience.ENG_GUIDE, **owner_kw
            ),
        )
    )
    return resolve_ownership(cfg)[0]
