"""Promotion detector + deterministic rule application (D-05/D-06 — pure — K0/K10).

The self-improvement payoff of the learning substrate (D-01/02): when humans
resolve the SAME drift SHAPE the SAME way >= K times, that decision can be
PROMOTED to a deterministic rule so the LLM is no longer consulted for it — the
system's cost curve bends DOWN as it learns.

:func:`detect_promotions` mines the review log joined to the append-only
resolutions log for a **generalizable** shape ``(doc_id, drift_kind, audience)``
— NOT ``surface_hash``. ``surface_hash`` is the EXACT code state (similar.py's
dominant feature) and never recurs across edits, so it cannot ground a recurring
rule; the audience-scoped doc+kind is the shape that DOES recur. A shape
qualifies iff >= ``min_count`` of its RESOLVED records share ONE **decision**
resolution.

Only DECISION-shaped resolutions auto-promote: ``invalidated`` and ``rejected``
carry NO content (a pure human judgement), so automating them is safe and
content-free. ``overridden`` carries human prose (``resolved_text``) that rarely
generalizes, and ``accepted`` of a mechanical fix is already LLM-free — both are
EXCLUDED here (a future content-rule slice could mine ``overridden``).

:func:`rule_from_candidate`/:func:`rule_for` map a candidate to a
:class:`PromotionRule` the monitor applies WITHOUT a backend call (D-06: a
matched drift is resolved by the rule with ZERO backend calls). All pure: no
I/O, no wall-clock (K10).
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, ConfigDict

from .config import Audience
from .drift import Drift
from .reviewlog import resolved_index
from .schema import Resolution, ResolutionRecord, ReviewRecord, Verdict

__all__ = [
    "PromotionCandidate",
    "PromotionRule",
    "PROMOTABLE_RESOLUTIONS",
    "detect_promotions",
    "rule_from_candidate",
    "rule_for",
]

# Frozen + extra="forbid": a candidate/rule is an immutable artifact and an
# unexpected key is a loud error, not a silent pass (K8).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

#: The DECISION-shaped resolutions that auto-promote. Both are content-free human
#: judgements (no ``resolved_text``), so a rule can reproduce them deterministically.
#: ``overridden`` (human prose) and ``accepted`` (already-LLM-free mechanical fix) are
#: deliberately excluded — see the module docstring.
PROMOTABLE_RESOLUTIONS: frozenset[Resolution] = frozenset(
    {Resolution.INVALIDATED, Resolution.REJECTED}
)

#: A promotable decision resolution -> the deterministic verdict its rule synthesizes.
#: Both decisions mean "do not auto-edit this doc" -> INVALIDATE (record it, no fix).
_RESOLUTION_VERDICT: dict[Resolution, Verdict] = {
    Resolution.INVALIDATED: Verdict.INVALIDATE,
    Resolution.REJECTED: Verdict.INVALIDATE,
}


class PromotionCandidate(BaseModel):
    """A generalizable shape whose resolved records unanimously share one decision."""

    model_config = _MODEL_CONFIG

    doc_id: str
    drift_kind: str
    audience: Audience
    resolution: Resolution  # the UNANIMOUS human decision for this shape
    count: int  # how many RESOLVED records support it (>= min_count)


class PromotionRule(BaseModel):
    """A promoted rule: a shape -> a deterministic verdict (applied with no backend)."""

    model_config = _MODEL_CONFIG

    doc_id: str
    drift_kind: str
    audience: Audience
    verdict: Verdict


def detect_promotions(
    records: list[ReviewRecord],
    resolutions: list[ResolutionRecord],
    *,
    min_count: int = 3,
) -> list[PromotionCandidate]:
    """Return one :class:`PromotionCandidate` per qualifying generalizable shape.

    Shape key = ``(doc_id, drift_kind, audience)`` (GENERALIZABLE, NOT
    ``surface_hash``). Population = RESOLVED records only (``record_id`` in
    :func:`~custodex.reviewlog.resolved_index`, last-write-wins). A shape
    QUALIFIES iff >= ``min_count`` of its resolved records share ONE
    :data:`PROMOTABLE_RESOLUTIONS` decision (unanimous among that shape's resolved
    records — a single differing resolution disqualifies it). Orphan resolutions
    (a ``record_id`` not in ``records``) are ignored so they cannot inflate a count.
    Output is sorted by ``(doc_id, drift_kind, audience, resolution)`` for
    determinism (K10). Pure: no I/O, no wall-clock.
    """
    index = resolved_index(resolutions)

    # Group the RESOLUTIONS of each shape's resolved records.
    by_shape: dict[tuple[str, str, Audience], list[Resolution]] = defaultdict(list)
    for record in records:
        resolution = index.get(record.record_id)
        if resolution is None:
            continue  # unresolved record is not part of the population
        key = (record.doc_id, record.drift_kind, record.audience)
        by_shape[key].append(resolution.resolution)

    candidates: list[PromotionCandidate] = []
    for (doc_id, drift_kind, audience), outcomes in by_shape.items():
        if len(outcomes) < min_count:
            continue  # too few resolved records for this shape
        unique = set(outcomes)
        if len(unique) != 1:
            continue  # not unanimous -> does not generalize to one rule
        (decision,) = unique
        if decision not in PROMOTABLE_RESOLUTIONS:
            continue  # overridden/accepted are not decision-shaped (excluded)
        candidates.append(
            PromotionCandidate(
                doc_id=doc_id,
                drift_kind=drift_kind,
                audience=audience,
                resolution=decision,
                count=len(outcomes),
            )
        )

    candidates.sort(
        key=lambda c: (c.doc_id, c.drift_kind, c.audience.value, c.resolution.value)
    )
    return candidates


def rule_from_candidate(candidate: PromotionCandidate) -> PromotionRule:
    """Map a :class:`PromotionCandidate` to its :class:`PromotionRule` (trivial).

    The candidate's decision resolution chooses the rule's verdict via
    :data:`_RESOLUTION_VERDICT` (both promotable decisions -> ``INVALIDATE``).
    """
    return PromotionRule(
        doc_id=candidate.doc_id,
        drift_kind=candidate.drift_kind,
        audience=candidate.audience,
        verdict=_RESOLUTION_VERDICT[candidate.resolution],
    )


def rule_for(drift: Drift, rules: tuple[PromotionRule, ...]) -> PromotionRule | None:
    """Return the FIRST rule whose shape matches ``drift``, else ``None``.

    A rule matches on the generalizable shape ``(doc_id, drift_kind, audience)``;
    ``drift.kind`` is an enum, compared on its ``.value`` against the rule's string.
    Pure and deterministic — first match in ``rules`` order wins (K10).
    """
    for rule in rules:
        if (
            rule.doc_id == drift.doc_id
            and rule.drift_kind == drift.kind.value
            and rule.audience == drift.audience
        ):
            return rule
    return None
