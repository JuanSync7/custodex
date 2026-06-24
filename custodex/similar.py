"""Similarity retrieval over resolved drifts (D-03 — pure, deterministic — K0/K10).

The learning substrate (D-01/02) is a review log joined to an append-only
resolutions log. This module mines it: given a *target* drift (a
:class:`~custodex.schema.ReviewRecord`), :func:`rank_similar` returns the
N most-similar PAST **resolved** records as :class:`Exemplar`\\s, so D-04 can feed
them to the agent backend as few-shot examples ("here is a drift like this one
and how a human resolved it").

The score is a **deterministic weighted feature-match** — no embeddings, no new
dependency (K0), no I/O and no wall-clock (K10). Vector/embedding retrieval is a
documented FUTURE option; the feature-match score is sufficient, offline, and
fully reproducible. Ranking is a total order (score, then recency, then
``record_id``) so two equal-score candidates have a stable, deterministic order
(K10).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .reviewlog import resolved_index
from .schema import ResolutionRecord, ReviewRecord

__all__ = ["Exemplar", "rank_similar", "FEATURE_WEIGHTS"]

# Frozen + extra="forbid": an exemplar is an immutable retrieval result and an
# unexpected key is a loud error, not a silent pass (K8).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

#: The feature-match weights (descending, distinct). Each feature compares one
#: ``ReviewRecord`` attribute of the target against a candidate; an EQUAL value
#: adds the weight. ``surface_hash`` (the exact code surface) dominates, then the
#: document, the drift kind, and finally the audience. ``ReviewRecord`` carries no
#: ``region_id``, so the region is deliberately NOT a feature. Max score = 11.0.
FEATURE_WEIGHTS: dict[str, float] = {
    "surface_hash": 5.0,
    "doc_id": 3.0,
    "drift_kind": 2.0,
    "audience": 1.0,
}


class Exemplar(BaseModel):
    """One retrieved past-resolved drift + its human outcome and match score."""

    model_config = _MODEL_CONFIG

    record: ReviewRecord  # the past RESOLVED drift
    resolution: ResolutionRecord  # its human outcome (resolved_text for OVERRIDDEN)
    score: float  # the deterministic feature-match score


def _score(target: ReviewRecord, candidate: ReviewRecord) -> float:
    """Sum the weights of the features the candidate shares with the target.

    Pure: compares plain ``ReviewRecord`` attributes; ``audience`` is an enum so
    equality is on the member, which is deterministic (K10).
    """
    total = 0.0
    for feature, weight in FEATURE_WEIGHTS.items():
        if getattr(target, feature) == getattr(candidate, feature):
            total += weight
    return total


def rank_similar(
    target: ReviewRecord,
    records: list[ReviewRecord],
    resolutions: list[ResolutionRecord],
    *,
    top_n: int = 3,
) -> list[Exemplar]:
    """Return the ``top_n`` most-similar PAST RESOLVED records to ``target``.

    Population is **resolved only**: a candidate is eligible iff its ``record_id``
    is in :func:`~custodex.reviewlog.resolved_index` (last-write-wins). The
    ``target`` itself is always excluded (by ``record_id``), even when resolved. The
    score is the deterministic feature-match (:data:`FEATURE_WEIGHTS`); ranking is a
    total order — higher score, then more-recent ``resolution.resolved_at`` (ISO
    strings sort chronologically), then ``record_id`` ascending — so the result is
    stable and reproducible (K10). ``top_n <= 0`` or an empty resolved population →
    ``[]``. Pure: no I/O, no wall-clock.
    """
    if top_n <= 0:
        return []

    index = resolved_index(resolutions)
    exemplars: list[Exemplar] = []
    for candidate in records:
        if candidate.record_id == target.record_id:
            continue
        resolution = index.get(candidate.record_id)
        if resolution is None:
            continue
        exemplars.append(
            Exemplar(
                record=candidate,
                resolution=resolution,
                score=_score(target, candidate),
            )
        )

    # Total order (K10): score DESC, recency DESC, record_id ASC. Negate the
    # descending keys so a single ascending sort gives the full order.
    exemplars.sort(
        key=lambda e: (
            -e.score,
            _neg_iso(e.resolution.resolved_at),
            e.record.record_id,
        )
    )
    return exemplars[:top_n]


def _neg_iso(value: str) -> tuple[int, ...]:
    """Map an ISO timestamp to a key that sorts MORE-RECENT FIRST.

    ISO-8601 strings sort lexicographically in chronological order, so a more
    recent timestamp is a larger string. To make recency descending inside an
    otherwise-ascending sort, invert each code point. Deterministic, no clock.
    """
    return tuple(-ord(ch) for ch in value)
