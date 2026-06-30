"""Detect-only drift detection: docs graded against the code (K1, K2, K3).

:func:`detect` is **pure and side-effect free** (K1): it never writes a file and
never calls a backend. For each document it builds the code surface (the single
source of truth, K2) and compares the doc to it:

* the doc file is missing -> ``MISSING_DOC`` (a stub can be created, healable);
* the stored fingerprint differs from the surface hash -> ``HASH``;
* a managed region whose id is a known :data:`REGION_KEYS` key has a body that
  differs from the freshly rendered body -> ``REGION`` (healable);
* a managed region whose id is *not* a known key -> ``UNHEALABLE`` (we cannot
  regenerate prose we do not own).

The audience rule (K3) is enforced upstream in extraction: the user-guide
surface hash excludes docstrings and private symbols, so a comment/docstring- or
private-only change simply does not move that hash and produces no ``HASH``
drift — while it does for an eng-guide. Every :class:`Drift` carries the doc's
audience.
"""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .blocks import REGION_KEYS, expected_region, known_region_ids
from .config import Audience, MonitorConfig, RegionMode, resolve_repo_root
from .docdeps import detect_suspect_links
from .extract import build_document_surface
from .index import render_index
from .manifest import (
    parse_doc,
    region_is_locked,
    regions,
    stored_fingerprint,
    stored_fingerprint_tiers,
    stored_region_anchors,
    stored_region_hash,
)

__all__ = [
    "DriftKind",
    "ChangeSeverity",
    "classify_change_severity",
    "Drift",
    "DriftReport",
    "detect",
]


class DriftKind(str, Enum):
    """The kind of discrepancy detected between a doc and its code surface."""

    MISSING_DOC = "MISSING_DOC"
    HASH = "HASH"
    REGION = "REGION"
    UNHEALABLE = "UNHEALABLE"
    # EPIC B: an upstream doc this one ``depends_on`` changed since last review.
    # Never auto-edited (healable=False) — resolved by ``cdx resolve --edge``.
    SUSPECT_LINK = "SUSPECT_LINK"


class ChangeSeverity(str, Enum):
    """Griffe-style severity of a HASH (code↔doc surface) change (P5).

    Classifies WHAT a HASH drift means for a downstream consumer, derived purely
    from signals ``detect`` ALREADY captures — the P2 ``drifted_tiers`` and the P4
    anchor-identity deltas — so it is a verdict layer, not a new analysis:

    * ``BREAKING`` — a documented symbol was removed/renamed, or (with the same
      symbol set) a public signature changed: a consumer can break.
    * ``ADDITIVE`` — only new symbols appeared (no removals): backward-compatible.
    * ``COSMETIC`` — only docstring/body prose moved, same symbols and signatures:
      no API impact.
    * ``UNKNOWN`` — not classifiable: a non-HASH drift, or an OLD doc carrying
      neither per-tier digests nor stored anchors to diff against.
    """

    BREAKING = "breaking"
    ADDITIVE = "additive"
    COSMETIC = "cosmetic"
    UNKNOWN = "unknown"


def classify_change_severity(
    drifted_tiers: Sequence[str],
    anchors_added: Sequence[str],
    anchors_removed: Sequence[str],
) -> ChangeSeverity:
    """Map the structural HASH signals onto a :class:`ChangeSeverity` (pure, K10).

    Precedence (the Griffe spirit — removals/changes break, additions don't):

    1. a removed/renamed documented symbol ⇒ ``BREAKING``;
    2. else a newly-added symbol ⇒ ``ADDITIVE`` (additions are non-breaking, even
       though they also move the aggregate signature tier);
    3. else a moved ``signature`` tier with NO anchor delta ⇒ ``BREAKING`` (the same
       symbol set, so a signature changed in place — or an old doc whose signature
       tier moved with no anchors to attribute it to: flag it, conservatively);
    4. else any moved tier (docstring/body only) ⇒ ``COSMETIC``;
    5. else ``UNKNOWN`` (no signal — a pre-P2/P4 doc with only a composite hash).

    Caveat (a known false-negative class, not a one-off): whenever a symbol is
    ADDED in the same edit that also changes an existing symbol's signature IN
    PLACE, this returns ``ADDITIVE`` (step 2 wins) even though the in-place change
    is genuinely breaking — so ``ADDITIVE`` is NOT a guarantee of backward
    compatibility when ``anchors_added`` is non-empty. The aggregate signals cannot
    separate the two: a pure addition ALSO moves the ``signature`` tier (the set of
    signatures grew), so promoting "signature in tiers" above the addition check
    would instead mislabel every pure addition BREAKING — the wrong, noisier
    direction. Distinguishing them needs per-symbol signature digests (a deliberate
    further deferral). The reverse direction — a removed/renamed symbol — is always
    caught first (step 1), so a deletion is never masked.
    """
    if anchors_removed:
        return ChangeSeverity.BREAKING
    if anchors_added:
        return ChangeSeverity.ADDITIVE
    if "signature" in drifted_tiers:
        return ChangeSeverity.BREAKING
    if drifted_tiers:
        return ChangeSeverity.COSMETIC
    return ChangeSeverity.UNKNOWN


class Drift(BaseModel):
    """One detected doc<->code discrepancy (data, never an exception)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: DriftKind
    doc_id: str
    doc_path: str
    detail: str
    region_id: str | None = None
    healable: bool = True
    audience: Audience
    diff: str = ""
    # P2: on a HASH drift, which surface tier(s) moved ("signature"/"docstring"/
    # "body"). Empty when not applicable or unknowable (an OLD doc carrying only a
    # composite fingerprint, with no stored per-tier digests to diff against).
    drifted_tiers: tuple[str, ...] = ()
    # P4: anchor delta on a HASH drift — anchor_ids documented now but not in the
    # stored region anchor set (added), and vice-versa (removed). Both empty ⇒ the
    # SAME symbol identities (a move/reorder or an internal body/docstring change,
    # i.e. re-bind, not a structural change); nonempty ⇒ a symbol was added /
    # removed / renamed. Empty when the doc predates P4 (no stored anchors).
    anchors_added: tuple[str, ...] = ()
    anchors_removed: tuple[str, ...] = ()
    # P5: the Griffe-style breaking-change severity of a HASH drift, classified from
    # drifted_tiers + the anchor deltas above (breaking/additive/cosmetic). UNKNOWN
    # for non-HASH drifts and for an OLD doc with no per-tier/anchor signals.
    change_severity: ChangeSeverity = ChangeSeverity.UNKNOWN


class DriftReport(BaseModel):
    """The full set of drifts found across a config's documents."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    drifts: tuple[Drift, ...]

    @property
    def ok(self) -> bool:
        """True when no drift was detected."""
        return not self.drifts

    def summary(self) -> str:
        """A short human-readable summary of the report."""
        if not self.drifts:
            return "clean — no drift detected"
        lines = [f"{len(self.drifts)} drift(s) detected:"]
        for d in self.drifts:
            loc = f" [{d.region_id}]" if d.region_id else ""
            heal = "" if d.healable else " (UNHEALABLE)"
            # P5: annotate a HASH drift with its breaking-change severity (additive
            # to the line — substring assertions still hold; UNKNOWN stays silent).
            sev = (
                f" [{d.change_severity.value}]"
                if d.kind is DriftKind.HASH
                and d.change_severity is not ChangeSeverity.UNKNOWN
                else ""
            )
            lines.append(f"  {d.doc_id}{loc}: {d.kind.value}{sev}{heal} — {d.detail}")
        return "\n".join(lines)


def _short_diff(expected: str, actual: str, region_id: str) -> str:
    """A compact unified diff of an expected vs actual region body."""
    return "\n".join(
        difflib.unified_diff(
            actual.split("\n"),
            expected.split("\n"),
            fromfile=f"{region_id} (doc)",
            tofile=f"{region_id} (code)",
            lineterm="",
        )
    )


def detect(config: MonitorConfig, config_dir: Path) -> DriftReport:
    """Detect drift for every document in ``config`` (pure, K1).

    The repo root is ``resolve_repo_root(config_dir, config.root)`` (N-06: the
    ONE shared formula = ``normpath(config_dir / root)``). Doc and code paths are
    resolved under that root. Returns a :class:`DriftReport`; the file system is
    never mutated.
    """
    root = resolve_repo_root(config_dir, config.root)
    templates = config.region_templates
    known = known_region_ids(templates)
    drifts: list[Drift] = []

    for spec in config.documents:
        surface = build_document_surface(spec, root)
        doc_path = root / spec.path

        if not doc_path.is_file():
            drifts.append(
                Drift(
                    kind=DriftKind.MISSING_DOC,
                    doc_id=spec.id,
                    doc_path=spec.path,
                    detail="document file is missing — a stub can be created",
                    healable=True,
                    audience=spec.audience,
                )
            )
            continue

        doc = parse_doc(doc_path)

        stored = stored_fingerprint(doc)
        current_fp = surface.fingerprint(include_body=config.fingerprint_body_tier)
        current = current_fp.composite
        if stored != current:
            # P2: when the doc carries stored per-tier digests, report WHICH tier
            # moved; otherwise (an OLD doc with only the composite) fall back to the
            # composite-only message with empty drifted_tiers.
            stored_tiers = stored_fingerprint_tiers(doc)
            drifted_tiers = (
                current_fp.drifted_against(stored_tiers) if stored_tiers else ()
            )
            if drifted_tiers:
                detail = (
                    f"surface drifted in {', '.join(drifted_tiers)} tier(s); "
                    f"fingerprint {stored!r} != current surface hash {current!r}"
                )
            else:
                detail = f"fingerprint {stored!r} != current surface hash {current!r}"
            # P4: classify the change by symbol IDENTITY. Compare the anchor set the
            # symbol-table region documents now against the stamped set; a delta
            # means a symbol was added/removed/renamed (structural), while an empty
            # delta means the SAME symbols changed internally (a re-bind, not a
            # structural move). Empty when the doc has no stamped anchors (pre-P4).
            current_anchors = {sym.anchor_id for sym in surface.symbols}
            stored_anchors: set[str] | None = None
            for region_id in spec.region_keys:
                if region_id not in REGION_KEYS:
                    continue
                stamped = stored_region_anchors(doc, region_id)
                if stamped is not None:
                    stored_anchors = (
                        set(stamped)
                        if stored_anchors is None
                        else stored_anchors | set(stamped)
                    )
            anchors_added: tuple[str, ...] = ()
            anchors_removed: tuple[str, ...] = ()
            if stored_anchors is not None:
                anchors_added = tuple(sorted(current_anchors - stored_anchors))
                anchors_removed = tuple(sorted(stored_anchors - current_anchors))
                if anchors_added or anchors_removed:
                    detail += (
                        f" (anchored symbols changed: +{len(anchors_added)}/"
                        f"-{len(anchors_removed)})"
                    )
            # P5: classify the breaking-change severity from the structural signals
            # just computed (no new analysis) so check/monitor/the audit record can
            # say breaking vs additive vs cosmetic at a glance.
            change_severity = classify_change_severity(
                drifted_tiers, anchors_added, anchors_removed
            )
            drifts.append(
                Drift(
                    kind=DriftKind.HASH,
                    doc_id=spec.id,
                    doc_path=spec.path,
                    detail=detail,
                    healable=True,
                    audience=spec.audience,
                    drifted_tiers=drifted_tiers,
                    anchors_added=anchors_added,
                    anchors_removed=anchors_removed,
                    change_severity=change_severity,
                )
            )

        doc_regions = regions(doc)
        for region_id, current_body in doc_regions.items():
            if region_id not in spec.region_keys:
                # Present in the doc but not declared by the spec — ignore it;
                # the spec governs which regions this doc manages.
                continue
            mode = spec.mode_for(region_id)
            # B-03: an `llm-seeded` region is engine-owned until a human edits it
            # — a stored per-region hash diverges from the current body (the
            # SHARED lock predicate). Once locked it is treated exactly like a
            # `human` region (engine will not author it).
            locked = mode is RegionMode.LLM_SEEDED and region_is_locked(
                doc, region_id, current_body
            )
            is_human = mode is RegionMode.HUMAN
            owned = is_human or locked  # engine will not author this body
            if region_id not in known:
                if owned:
                    # Intentionally human-/locked-owned region the engine cannot
                    # render — not an error, and not auto-healable (B-02/B-03).
                    continue
                if mode is RegionMode.LLM:
                    # B-06: a pure-`llm` region (no mechanical renderer) is
                    # backend-AUTHORED prose, not unknown. Its body legitimately
                    # differs from any render, so it is NOT graded against one.
                    # It is re-authored only when the code surface it documents
                    # MOVES (the whole-doc fingerprint diverges); while the
                    # surface is unchanged the prose stands (no drift). When the
                    # code moved, surface a healable REGION drift — the backend
                    # re-authors it from the current surface (offline by default
                    # via the deterministic MockBackend prose rule, K4/K10).
                    if stored != current:
                        drifts.append(
                            Drift(
                                kind=DriftKind.REGION,
                                doc_id=spec.id,
                                doc_path=spec.path,
                                detail=(
                                    f"llm-authored region {region_id!r} is stale; "
                                    "backend will re-author from the current surface"
                                ),
                                region_id=region_id,
                                healable=True,
                                audience=spec.audience,
                            )
                        )
                    continue
                drifts.append(
                    Drift(
                        kind=DriftKind.UNHEALABLE,
                        doc_id=spec.id,
                        doc_path=spec.path,
                        detail=(
                            f"managed region {region_id!r} has no known renderer; "
                            "cannot auto-heal"
                        ),
                        region_id=region_id,
                        healable=False,
                        audience=spec.audience,
                    )
                )
                continue
            template = templates.get(region_id)
            expected: str | None
            if template is not None and template.source == "index":
                expected = render_index(template, spec, config, root)
            else:
                expected = expected_region(region_id, surface, template)
            if expected is not None and current_body != expected:
                if owned:
                    # B-02 retrofit (B-03): a human region's advisory PERSISTS
                    # across a fingerprint heal until the body actually changes.
                    # It carries a stored per-region hash stamped when last
                    # reviewed; while the current body still matches that stamp
                    # (the human has not acknowledged) the advisory keeps firing,
                    # even though the fingerprint may now be in sync. With no
                    # stamp yet, fall back to the code-moved (fingerprint) signal.
                    human_advisory_pending = (
                        is_human
                        and stored_region_hash(doc, region_id) is not None
                        and not region_is_locked(doc, region_id, current_body)
                    )
                    code_moved = stored != current
                    if not code_moved and not human_advisory_pending:
                        # A human/locked body differs from the generated render by
                        # definition; with the code unchanged and the human still
                        # at the reviewed body, this is NOT drift.
                        continue
                # A human-/locked-owned region whose code HAS moved is REPORTED for
                # review but never auto-edited (healable=False) — the human owns it.
                detail = (
                    f"managed region {region_id!r} is human-owned (mode="
                    f"{'llm-seeded, locked' if locked else 'human'}); "
                    "engine will not auto-edit — review manually"
                    if owned
                    else f"managed region {region_id!r} is out of date"
                )
                drifts.append(
                    Drift(
                        kind=DriftKind.REGION,
                        doc_id=spec.id,
                        doc_path=spec.path,
                        detail=detail,
                        region_id=region_id,
                        healable=not owned,
                        audience=spec.audience,
                        diff=_short_diff(expected, current_body, region_id),
                    )
                )

    # EPIC B: append doc↔doc suspect links (a downstream whose upstream changed).
    # Pure data like any other Drift; never auto-edited (healable=False) — a human
    # re-confirms with `cdx resolve --edge`. Gated by `docdeps.enabled` inside
    # detect_suspect_links. Detection writes nothing (K1).
    for link in detect_suspect_links(config, root):
        drifts.append(
            Drift(
                kind=DriftKind.SUSPECT_LINK,
                doc_id=link.doc_id,
                doc_path=link.doc_path,
                detail=f"{link.upstream_id}: {link.detail}",
                healable=False,
                audience=link.audience,
            )
        )

    return DriftReport(drifts=tuple(drifts))
