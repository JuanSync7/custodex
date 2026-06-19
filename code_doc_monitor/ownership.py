"""Ownership & accountability — peg a human/team to a document (EPIC OWN).

Tier 1 (this module's pure half): given a loaded :class:`~config.MonitorConfig`
(the SOURCE OF TRUTH for ownership, K0 / the K2 scope note) and an injected
:class:`RosterSnapshot` (the central mirror), resolve each document's *accountable*
and *durable* owner and classify orphans. No clock, no network, no new dependency
(K0/K1/K10). The server (`[server]` extra) and the ``cdmon ownership`` CLI both
drive this same pure core.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from .config import Audience, MonitorConfig
from .errors import ConfigError

__all__ = [
    "Identity",
    "RosterSnapshot",
    "EffectiveOwner",
    "OwnershipStatus",
    "OwnershipFinding",
    "resolve_ownership",
    "resolve_accountable_durable",
    "detect_orphans",
    "load_roster",
    "render_ownership_text",
]

# Frozen + extra="forbid": ownership records are immutable snapshots; an unknown
# key is a loud error, never a silent pass (K8), mirroring the config models.
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class Identity(BaseModel):
    """One roster entry — a person or a team handle, with active/departed status.

    The roster is the central MIRROR (it never owns a document — config does); it
    records *who exists and who has left* so a departed owner can be detected.
    """

    model_config = _MODEL_CONFIG

    name: str
    display_name: str | None = None
    kind: Literal["person", "team"] = "person"
    email: str | None = None
    active: bool = True
    departed_at: str | None = None  # injected ISO ts (K10), set when marked departed
    teams: tuple[str, ...] = ()  # teams a person belongs to


class RosterSnapshot(BaseModel):
    """An immutable view of the central roster (the injected mirror)."""

    model_config = _MODEL_CONFIG

    identities: tuple[Identity, ...] = ()

    def get(self, name: str) -> Identity | None:
        """The identity named ``name``, or ``None`` if the roster does not know it."""
        for ident in self.identities:
            if ident.name == name:
                return ident
        return None

    def is_active(self, name: str | None) -> bool:
        """True only if ``name`` is a known, active identity.

        ``None`` (no name at all) and an unknown name both read as inactive — an
        owner the roster cannot vouch for is not an active accountable party.
        """
        if name is None:
            return False
        ident = self.get(name)
        return ident is not None and ident.active


class EffectiveOwner(BaseModel):
    """Resolved ownership for one document — a pure projection of its config."""

    model_config = _MODEL_CONFIG

    doc_id: str
    doc_path: str
    audience: Audience
    owner: str | None = None
    team: str | None = None
    dri: str | None = None
    accountable: str | None = None  # dri → owner → team → inherited unit owner
    durable: str | None = None  # team → owner → inherited unit owner


def resolve_accountable_durable(
    owner: str | None,
    team: str | None,
    dri: str | None,
    inherited: str | None = None,
) -> tuple[str | None, str | None]:
    """The (accountable, durable) precedence — the ONE formula (K10).

    ``accountable = dri → owner → team → inherited`` (the current point of contact);
    ``durable = team → owner → inherited`` (the part that survives a person leaving).
    Shared by :func:`resolve_ownership` (engine/CLI) and the server's sync mirror
    (``configsync``) so the two never diverge.
    """
    accountable = dri or owner or team or inherited
    durable = team or owner or inherited
    return accountable, durable


def resolve_ownership(
    config: MonitorConfig, *, unit_owner: Mapping[str, str] | None = None
) -> tuple[EffectiveOwner, ...]:
    """Resolve each document's accountable + durable owner, sorted by id (K10).

    The *accountable* identity is the current point of contact
    (``dri`` → ``owner`` → ``team`` → the inherited unit owner); the *durable* owner
    is the part that survives a person leaving (``team`` → ``owner`` → inherited).
    ``unit_owner`` maps ``doc_id`` → that document's unit-frontmatter owner (the
    fallback when the document declares none of its own). Pure: no clock, no I/O.
    """
    fallback = unit_owner or {}
    out: list[EffectiveOwner] = []
    for doc in config.documents:
        accountable, durable = resolve_accountable_durable(
            doc.owner, doc.team, doc.dri, fallback.get(doc.id)
        )
        out.append(
            EffectiveOwner(
                doc_id=doc.id,
                doc_path=doc.path,
                audience=doc.audience,
                owner=doc.owner,
                team=doc.team,
                dri=doc.dri,
                accountable=accountable,
                durable=durable,
            )
        )
    return tuple(sorted(out, key=lambda owner: owner.doc_id))


class OwnershipStatus(str, Enum):
    """How a document's accountability stands against the roster."""

    OK = "ok"  # the accountable identity is known + active
    UNOWNED = "unowned"  # no owner/team/dri declared anywhere
    ORPHAN_OWNER_DEPARTED = (
        "orphan_owner_departed"  # accountable gone, no active fallback
    )
    ORPHAN_DRI_VACANT = (
        "orphan_dri_vacant"  # DRI gone but durable owner still active (soft)
    )


class OwnershipFinding(BaseModel):
    """One document's accountability verdict — the orphan signal (K5)."""

    model_config = _MODEL_CONFIG

    doc_id: str
    doc_path: str
    audience: Audience
    status: OwnershipStatus
    detail: str
    accountable: str | None = None
    owner: str | None = None
    team: str | None = None
    dri: str | None = None


def detect_orphans(
    owners: Sequence[EffectiveOwner],
    roster: RosterSnapshot,
    *,
    include_ok: bool = False,
) -> tuple[OwnershipFinding, ...]:
    """Classify each document against the roster, sorted by id (pure, no clock).

    An orphan is never *healable* (no code change fixes it) — it is resolved by
    reassignment (OWN-05). ``OK`` findings are omitted unless ``include_ok`` so the
    default result is exactly the docs that need a human (K5). The roster is the
    injected mirror; an unknown-or-departed accountable name is treated inactive.
    """
    findings: list[OwnershipFinding] = []
    for owner in owners:
        status, detail = _classify(owner, roster)
        if status is OwnershipStatus.OK and not include_ok:
            continue
        findings.append(
            OwnershipFinding(
                doc_id=owner.doc_id,
                doc_path=owner.doc_path,
                audience=owner.audience,
                status=status,
                detail=detail,
                accountable=owner.accountable,
                owner=owner.owner,
                team=owner.team,
                dri=owner.dri,
            )
        )
    return tuple(sorted(findings, key=lambda finding: finding.doc_id))


def _classify(
    owner: EffectiveOwner, roster: RosterSnapshot
) -> tuple[OwnershipStatus, str]:
    """The pure per-document verdict (accountable vs durable vs roster)."""
    if owner.accountable is None:
        return OwnershipStatus.UNOWNED, "no owner/team/dri declared"
    if roster.is_active(owner.accountable):
        return OwnershipStatus.OK, f"accountable owner {owner.accountable!r} is active"
    # The accountable identity is departed/unknown. A distinct, still-active durable
    # owner (the team) makes this a SOFT orphan — assign a new DRI, no panic.
    if (
        owner.durable is not None
        and owner.durable != owner.accountable
        and roster.is_active(owner.durable)
    ):
        return (
            OwnershipStatus.ORPHAN_DRI_VACANT,
            f"DRI {owner.accountable!r} departed; durable owner "
            f"{owner.durable!r} still active — assign a new DRI",
        )
    return (
        OwnershipStatus.ORPHAN_OWNER_DEPARTED,
        f"accountable owner {owner.accountable!r} is departed/unknown and no "
        f"active fallback — reassign this document",
    )


def load_roster(path: Path) -> RosterSnapshot:
    """Load an offline roster YAML (``identities: [...]``) → :class:`RosterSnapshot`.

    The roster is the OFFLINE, injected mirror the ``cdmon ownership`` CLI
    cross-checks against (K4): a mapping with an ``identities`` list of Identity
    dicts. Loud (``ConfigError``) on a missing/unreadable file, a non-mapping
    document, or a malformed identity (K8) — never a silent empty roster.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"could not read roster {str(path)!r}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("identities"), list):
        raise ConfigError(
            f"roster {str(path)!r} must be a mapping with an 'identities' list"
        )
    try:
        return RosterSnapshot(
            identities=tuple(Identity(**item) for item in raw["identities"])
        )
    except (TypeError, ValidationError) as exc:
        raise ConfigError(f"malformed roster {str(path)!r}: {exc}") from exc


def render_ownership_text(
    owners: Sequence[EffectiveOwner], findings: Sequence[OwnershipFinding]
) -> str:
    """A deterministic plain-text ownership report (K10) — the CLI's human view."""
    lines = [f"# Ownership — {len(owners)} document(s)", ""]
    for owner in owners:
        meta = (
            f"owner={owner.owner or '—'} "
            f"team={owner.team or '—'} "
            f"dri={owner.dri or '—'}"
        )
        lines.append(
            f"  {owner.doc_id}  [{owner.audience.value}]  "
            f"accountable={owner.accountable or '—'}  ({meta})"
        )
    if findings:
        lines.append("")
        lines.append(f"# Findings — {len(findings)} document(s) need a human")
        for finding in findings:
            lines.append(
                f"  [{finding.status.value}] {finding.doc_id}: {finding.detail}"
            )
    return "\n".join(lines)
