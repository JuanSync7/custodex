"""Public, versioned review-record schema (K6, K10).

A :class:`ReviewRecord` is the standardized payload for one handled drift: the
original drift, the LLM's cause + verdict, the proposed fix, and an
audience/config snapshot with hashes and (injected) timestamps. It is the
contract the central system consumes, so it carries a ``schema_version`` and is
emitted *from the pydantic model* — :func:`review_record_schema` is the one
source of truth, never a hand-written schema (K6).

Records are reproducible (K10): :func:`new_record_id` derives a deterministic id
from the drift's identity, and timestamps are injected by the caller rather than
read from the clock here.
"""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, ConfigDict

from .config import Audience
from .ticket import DriftTicket

__all__ = [
    "Verdict",
    "ProposedFix",
    "ReviewRecord",
    "review_record_schema",
    "new_record_id",
    "Resolution",
    "ResolutionRecord",
    "resolution_record_schema",
]

# Frozen + extra="forbid": records are immutable, audited artifacts and an
# unexpected key is a loud error, not a silent pass (K8).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class Verdict(str, Enum):
    """The backend's decision for one drift (mirrors SPEC *Verdict*)."""

    FIX = "FIX"
    INVALIDATE = "INVALIDATE"
    ESCALATE = "ESCALATE"


class ProposedFix(BaseModel):
    """A backend-proposed remediation for one drift.

    Either a region-shaped fix (``region_id`` + ``new_region_body``) or a
    whole-doc fix (``new_doc_text``); ``rationale`` always explains the choice.
    Satisfies the structural ``heal.ProposedFixLike`` Protocol.
    """

    model_config = _MODEL_CONFIG

    region_id: str | None = None
    new_region_body: str | None = None
    new_doc_text: str | None = None
    rationale: str


class ReviewRecord(BaseModel):
    """The public, versioned payload for one handled drift (K5, K6).

    Carries BOTH the original drift (``drift_kind``/``drift_detail``) and the
    proposed ``fix`` so a human can review what changed and why (K5). Timestamps
    are injected ISO strings, never read from the clock here (K10).
    """

    model_config = _MODEL_CONFIG

    # P5 minor bump (K6): `change_severity` added additively (after `drifted_tiers`
    # at P2/1.1.0). The bump is the public signal that the breaking-change taxonomy
    # is available; old "1.0.0"/"1.1.0" records still validate (the new field
    # defaults), and a flag-off record's other bytes are unchanged.
    schema_version: str = "1.2.0"
    record_id: str
    doc_id: str
    doc_path: str
    audience: Audience
    drift_kind: str
    drift_detail: str
    cause: str  # the LLM's explanation
    verdict: Verdict
    fix: ProposedFix | None = None
    surface_hash: str
    backend_kind: str
    detected_at: str  # ISO string, injected (K10)
    resolved_at: str  # ISO string, injected (K10)
    config_snapshot: dict
    # C-05 provenance (ADDITIVE, K6): the code ref/commit this heal came from.
    # Default None keeps pre-C-05 records valid — an old JSONL line without this
    # field still `model_validate_json`s. Appended LAST so existing field order is
    # untouched.
    source_sha: str | None = None
    # T-01 structured ticket (ADDITIVE, K6): the Jira-style artifact a human
    # validates, built FROM this record's drift/verdict/fix. Default None keeps
    # pre-T-01 records valid — an old JSONL line without it still
    # `model_validate_json`s. Appended LAST so existing field order is untouched.
    ticket: DriftTicket | None = None
    # P2 which-tier-moved (ADDITIVE, K6): the surface tier(s) that moved on a HASH
    # drift ("signature"/"docstring"/"body"); () for non-HASH drifts or an OLD doc
    # without stored per-tier digests. Default () keeps pre-P2 records valid — an
    # old JSONL line without it still `model_validate_json`s. Appended LAST.
    drifted_tiers: tuple[str, ...] = ()
    # P5 breaking-change severity (ADDITIVE, K6): the Griffe-style classification of
    # a HASH drift ("breaking"/"additive"/"cosmetic"), stringly-typed here (like
    # `drift_kind`) — the ChangeSeverity enum lives in drift.py. "unknown" for
    # non-HASH drifts or an OLD doc without the structural signals. Default keeps
    # pre-P5 records valid (an old JSONL line still validates). Appended LAST.
    change_severity: str = "unknown"


def review_record_schema() -> dict:
    """Return the public review-record JSON Schema, derived from the model (K6)."""
    return ReviewRecord.model_json_schema()


class Resolution(str, Enum):
    """The human OUTCOME of a handled drift (D-01/D-02).

    A resolution is a SEPARATE append-only event linked to a :class:`ReviewRecord`
    by ``record_id`` — the review log stays immutable (K5); we never mutate a record
    to record what a reviewer decided. This is the learning substrate D-03..D-06 mine.
    """

    ACCEPTED = "accepted"  # the proposed FIX was right, merged as-is
    OVERRIDDEN = "overridden"  # human kept the fix idea but rewrote it (resolved_text)
    REJECTED = "rejected"  # the fix was wrong; drift stands / handled elsewhere
    INVALIDATED = "invalidated"  # a human judged the drift a non-event


class ResolutionRecord(BaseModel):
    """The public, versioned outcome for one handled drift (K5, K6, K10).

    Frozen + ``extra="forbid"``: like :class:`ReviewRecord`, an outcome is an
    immutable audited artifact and an unexpected key is a loud error (K8). Fields are
    additive across versions (K6): ``note`` is appended LAST and defaults to ``None``,
    so an older JSONL line without it still ``model_validate_json``s. ``resolved_at``
    is an injected ISO string, never read from the clock here (K10).
    """

    model_config = _MODEL_CONFIG

    schema_version: str = "1.0.0"
    record_id: str  # FK -> ReviewRecord.record_id
    resolution: Resolution
    resolved_text: str | None = None  # the human's final text when OVERRIDDEN
    resolved_by: str | None = None
    resolved_at: str  # ISO string, injected (K10)
    note: str | None = None


def resolution_record_schema() -> dict:
    """Return the public resolution JSON Schema, derived from the model (K6)."""
    return ResolutionRecord.model_json_schema()


def new_record_id(doc_id: str, surface_hash: str, detected_at: str) -> str:
    """Build a deterministic 12-char id from a drift's identity (K10).

    The id is a sha256 prefix of the joined inputs, so the same drift handled
    with the same inputs always produces the same id — records are reproducible
    and de-dupable without a wall-clock or a counter.
    """
    joined = "\x00".join((doc_id, surface_hash, detected_at))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
