"""Ownership & accountability — peg a human/team to a document (EPIC OWN).

Tier 1 (this module's pure half): given a loaded :class:`~config.MonitorConfig`
(the SOURCE OF TRUTH for ownership, K0 / the K2 scope note) and an injected
:class:`RosterSnapshot` (the central mirror), resolve each document's *accountable*
and *durable* owner and classify orphans. No clock, no network, no new dependency
(K0/K1/K10). The server (`[server]` extra) and the ``cdmon ownership`` CLI both
drive this same pure core.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .config import Audience, MonitorConfig

__all__ = [
    "Identity",
    "RosterSnapshot",
    "EffectiveOwner",
    "resolve_ownership",
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
        inherited = fallback.get(doc.id)
        accountable = doc.dri or doc.owner or doc.team or inherited
        durable = doc.team or doc.owner or inherited
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
