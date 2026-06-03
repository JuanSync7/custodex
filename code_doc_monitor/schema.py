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

__all__ = [
    "Verdict",
    "ProposedFix",
    "ReviewRecord",
    "review_record_schema",
    "new_record_id",
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

    schema_version: str = "1.0.0"
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


def review_record_schema() -> dict:
    """Return the public review-record JSON Schema, derived from the model (K6)."""
    return ReviewRecord.model_json_schema()


def new_record_id(doc_id: str, surface_hash: str, detected_at: str) -> str:
    """Build a deterministic 12-char id from a drift's identity (K10).

    The id is a sha256 prefix of the joined inputs, so the same drift handled
    with the same inputs always produces the same id — records are reproducible
    and de-dupable without a wall-clock or a counter.
    """
    joined = "\x00".join((doc_id, surface_hash, detected_at))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
