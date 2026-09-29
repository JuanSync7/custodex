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
from collections import Counter
from collections.abc import Collection, Sequence
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .blocks import REGION_KEYS, expected_region, known_region_ids
from .config import Audience, MonitorConfig, RegionMode, resolve_repo_root
from .docdeps import detect_suspect_links
from .extract import DocumentSurface, SurfaceFingerprint, build_document_surface
from .index import render_index
from .manifest import (
    parse_doc,
    region_is_locked,
    regions,
    stored_fingerprint,
    stored_fingerprint_tiers,
    stored_region_anchors,
    stored_region_hash,
    stored_symbol_sigs,
)

__all__ = [
    "DriftKind",
    "ChangeSeverity",
    "classify_change_severity",
    "ApplyTier",
    "classify_apply_tier",
    "AUTO_TIERS",
    "Drift",
    "DriftReport",
    "auto_routable_docs",
    "docs_closable_by",
    "mechanical_docs",
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

    * ``BREAKING`` — a documented symbol was removed/renamed (one of several
      same-name symbols included, unless the stored signature tier proves the
      anchor stamp merely over-counts it), or (with the same symbol set) a
      public signature changed: a consumer can break. It ALSO covers a
      signature move the engine cannot ATTRIBUTE: under a same-name
      (repeating) stamped anchor the per-symbol digests keep only the last
      writer, so when the new symbols cannot be proven to explain the whole move
      it is held conservatively — deny by default, even when the move turns out
      to be only a same-name tie reordered by a line shift, a grown collision, a
      ``records`` change, or an anchor stamp that under-counts (stale).
    * ``ADDITIVE`` — only new symbols appeared (no removals), and no repeating
      stamped anchor could be hiding a signature move: backward-compatible.
      Within what the name-keyed stamps can tell: on a doc with no stamped
      same-name anchor no proof runs, so a ``records`` change, or an in-place
      signature change on a doc stamped before DIG-01, travelling with an
      addition is not yet excluded there (follow-up S1-ADDPROOF); and an anchor
      stamp that is STALE (under-counts a same-name symbol) can hide that
      symbol's deletion, which then reads as no removal (until the anchor stamp
      is completed on every write, follow-up S1-E4).
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
    sigs_changed: Sequence[str] = (),
    sigs_ambiguous: Sequence[str] = (),
) -> ChangeSeverity:
    """Map the structural HASH signals onto a :class:`ChangeSeverity` (pure, K10).

    Precedence (the Griffe spirit — removals/changes break, additions don't):

    1. a removed/renamed documented symbol ⇒ ``BREAKING``;
    2. else a SURVIVING symbol whose signature changed IN PLACE (``sigs_changed``,
       DIG-01) ⇒ ``BREAKING`` — checked ABOVE the addition rule so a simultaneous
       add + in-place change is no longer masked;
    2b. else a REPEATING stamped anchor that could be hiding the signature move
       (``sigs_ambiguous`` — candidates, not culprits) ⇒ ``BREAKING``,
       unconditionally (whatever tiers moved). The per-symbol digests are keyed by
       anchor, and an anchor is the qualified name only, so two same-name symbols
       (``main`` in two code_refs, an ``@overload`` stack, a property getter and
       setter) share ONE digest — the last writer's. A change to the shadowed one
       leaves ``sigs_changed`` empty, and without this rule any addition in the
       same edit would grade ``ADDITIVE`` and route ``CODE_DERIVED`` (unattended
       under ``--tiered``). Unattributable is not innocent: deny by default;
    3. else a newly-added symbol ⇒ ``ADDITIVE`` (additions are non-breaking, even
       though they also move the aggregate signature tier);
    4. else a moved ``signature`` tier with NO anchor/signature delta ⇒ ``BREAKING``
       (a pre-DIG-01 doc whose signature tier moved with no per-symbol digests to
       attribute it to: flag it, conservatively);
    5. else any moved tier (docstring/body only) ⇒ ``COSMETIC``;
    6. else ``UNKNOWN`` (no signal — a pre-P2/P4 doc with only a composite hash).

    DIG-01 closes the former masked false-negative: ``sigs_changed`` is the set of
    documented symbols present BEFORE and AFTER whose signature digest differs (from
    the stored ``cdm.symbol_sigs``), so an in-place signature change is caught even when
    a symbol is ALSO added in the same edit. It is empty for a pure addition (no
    survivor's signature moved), so additions still classify ``ADDITIVE`` — not the
    noisier "every addition is breaking" direction — PROVIDED no repeating stamped
    anchor could be hiding a move (rule 2b). Where one could, ``detect`` must
    prove the additions explain the whole signature-tier move; it cannot when a
    same-name tie reorders while the last writer stays last (lines added OR
    removed above a collider move it past a non-last sibling), a collision
    grows, ``records`` moved in the same edit, or the anchor stamp under-counts
    (is stale), so such additions are held ``BREAKING`` (the tie-reorder cost
    until a lineno-free tie order exists, review slice 1b; the grown-collision
    cost until per-occurrence identity, slice 2). When ``sigs_changed`` is empty
    because the doc predates DIG-01 (no stored per-symbol digests), the classifier
    falls through to the aggregate behaviour above (steps 2b-6), so old docs degrade
    gracefully (K6) — rule 2b included: the collision proof needs only the stored
    tiers, so a shadowed break on a pre-DIG-01 doc is still held. A removed/renamed
    symbol is still caught first (step 1).
    """
    if anchors_removed:
        return ChangeSeverity.BREAKING
    if sigs_changed:
        return ChangeSeverity.BREAKING
    if sigs_ambiguous:
        return ChangeSeverity.BREAKING
    if anchors_added:
        return ChangeSeverity.ADDITIVE
    if "signature" in drifted_tiers:
        return ChangeSeverity.BREAKING
    if drifted_tiers:
        return ChangeSeverity.COSMETIC
    return ChangeSeverity.UNKNOWN


class ApplyTier(str, Enum):
    """Which AUTHORITY can close a drift — provenance, never a magnitude (RTE-01).

    K11 bans a bare confidence float, and a float is also the wrong MODEL of the
    problem: on the ``CODE_DERIVED`` path there is no model judgement to be
    confident *about* — the bytes are the engine's own projection of the surface,
    produced by the same functions :mod:`custodex.heal` calls. So the question is
    not "how sure is the backend?" but "what closes this?":

    * ``CODE_DERIVED`` — an engine projection of the extracted surface. NO model is
      consulted, so there is nothing to estimate: a renderer-backed region body, or
      a symbol-table refresh whose severity proves no sentence was falsified.
    * ``DELEGATED`` — prose a model authors into a region a HUMAN declared
      ``mode: llm``. The consent is the config line, granted per region.
    * ``NEEDS_INTENT`` — closing it needs a WHY the code cannot supply (why this
      symbol exists, what it is for), or the engine simply may not author it.

    The fourth instance of a shape already pinned three times
    (:class:`custodex.kgraph.EdgeTier`, :class:`custodex.docmap.SuggestionTier`,
    :class:`ChangeSeverity`).
    """

    CODE_DERIVED = "code-derived"
    DELEGATED = "delegated"
    NEEDS_INTENT = "needs-intent"

    @property
    def is_auto(self) -> bool:
        """True when this tier could close unattended (the route is DERIVED).

        Route is never stored alongside the tier — one fact, one field (K10). The
        WRITE is gated separately and far more tightly (RTE-03/RTE-04); this only
        says a human is not structurally required.
        """
        return self is not ApplyTier.NEEDS_INTENT


#: The tiers that route AUTO — DERIVED from :attr:`ApplyTier.is_auto`, never a
#: hand-written literal. A literal would be a SECOND encoding of the route, free
#: to drift from the property that actually drives the fold (K10).
AUTO_TIERS: frozenset[ApplyTier] = frozenset(t for t in ApplyTier if t.is_auto)


def classify_apply_tier(
    kind: DriftKind,
    change_severity: ChangeSeverity,
    *,
    healable: bool,
    region_id: str | None = None,
    region_mode: RegionMode = RegionMode.GENERATED,
    renderer_backed: bool = False,
) -> tuple[ApplyTier, tuple[str, ...]]:
    """Map a drift's structural signals onto an :class:`ApplyTier` (pure, K1/K10).

    Ordered, first match wins, DENY BY DEFAULT — the chain is total, so an
    unrecognised combination lands on ``NEEDS_INTENT`` rather than falling through
    to something permissive. Returns the tier plus a SORTED evidence tuple naming
    the rule that fired, so a reviewer (and the RTE-03 audit record) can see WHY.

    Takes no clock, no config, no filesystem and no backend — the same discipline
    as :func:`classify_change_severity`, which it CONSUMES and never re-tunes (K9).

    The rules, in precedence order:

    1. ``SUSPECT_LINK`` — a doc↔doc edge is not closable from the code surface.
    2. ``MISSING_DOC`` — writing a document that does not exist is authoring.
    3. ``UNHEALABLE`` — a managed region with no renderer cannot be regenerated.
    4. ``not healable`` — a human-owned region whose code moved: reported, never
       auto-edited. Ordered BELOW 1-3 on purpose: those kinds are always built
       ``healable=False``, so putting this rule first would make them dead code and
       collapse three distinct reasons into one undifferentiated evidence string.
    5. ``region_mode`` is ``HUMAN``/``LLM_SEEDED`` — defence in depth over rule 4.
       An UNLOCKED ``llm-seeded`` region is engine-owned and IS healed mechanically,
       so it could in principle be ``CODE_DERIVED`` — but this function is not given
       the lock state, only the mode. **A rule must not decide what its inputs
       cannot evaluate**, so it denies the whole mode it cannot fully see.
    6. a renderer-backed ``REGION`` ⇒ ``CODE_DERIVED``: the body is
       :func:`custodex.blocks.expected_region` of the surface, no model involved.
    7. a ``mode: llm`` ``REGION`` with no renderer ⇒ ``DELEGATED``.
    8. any other ``REGION`` ⇒ authored prose the engine does not own.
    9. ``HASH`` + ``BREAKING`` ⇒ a documented symbol was removed/renamed or a
       survivor's signature moved, so prose naming it is now FALSE — or cannot be
       PROVEN true (a signature move under a same-name anchor that the per-symbol
       digests cannot attribute, see :func:`classify_change_severity` rule 2b). The
       argument is about prose OUTSIDE the managed regions, which the engine can
       neither see nor repair — hence a human.
    10. ``HASH`` + ``UNKNOWN`` ⇒ overloaded (a non-HASH drift *or* a legacy doc with
        nothing to diff against), so it is never read as safe.
    11. ``HASH`` + ``COSMETIC``/``ADDITIVE`` ⇒ ``CODE_DERIVED``. COSMETIC means the
        same symbols and signatures, so no sentence anywhere can have been
        falsified; ADDITIVE means nothing was removed, so the doc is now
        *incomplete*, not *wrong*, and a refreshed table beats a stale one.
    12. anything else ⇒ deny.

    There is deliberately NO audience term. K3 is enforced UPSTREAM inside the
    fingerprint (``include_docstrings = audience is ENG_GUIDE``), so a user-guide's
    ``drifted_tiers`` can only ever be ``("signature",)`` and ``COSMETIC`` is
    structurally unreachable there — the severity axis has ALREADY made this rule
    stricter for user guides. A hand-written clause would double-count K3.
    """

    def verdict(tier: ApplyTier, *evidence: str) -> tuple[ApplyTier, tuple[str, ...]]:
        return tier, tuple(sorted(evidence))

    def region_marker() -> tuple[str, ...]:
        return () if region_id is None else (f"region:{region_id}",)

    if kind is DriftKind.SUSPECT_LINK:
        return verdict(ApplyTier.NEEDS_INTENT, "doc-doc-edge")
    if kind is DriftKind.MISSING_DOC:
        return verdict(ApplyTier.NEEDS_INTENT, "no-document-yet")
    if kind is DriftKind.UNHEALABLE:
        return verdict(ApplyTier.NEEDS_INTENT, "no-renderer")
    if not healable:
        return verdict(ApplyTier.NEEDS_INTENT, "human-owned")
    if region_mode in (RegionMode.HUMAN, RegionMode.LLM_SEEDED):
        return verdict(ApplyTier.NEEDS_INTENT, "human-owned-region")
    if kind is DriftKind.REGION:
        if renderer_backed:
            return verdict(
                ApplyTier.CODE_DERIVED, "mechanical-render", *region_marker()
            )
        if region_mode is RegionMode.LLM:
            return verdict(ApplyTier.DELEGATED, "delegated-prose", *region_marker())
        return verdict(ApplyTier.NEEDS_INTENT, "authored-prose")
    if kind is DriftKind.HASH:
        if change_severity in (ChangeSeverity.COSMETIC, ChangeSeverity.ADDITIVE):
            return verdict(
                ApplyTier.CODE_DERIVED,
                "surface-refresh",
                f"severity:{change_severity.value}",
            )
        return verdict(ApplyTier.NEEDS_INTENT, f"severity:{change_severity.value}")
    return verdict(ApplyTier.NEEDS_INTENT, "unclassified")


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
    # A MULTISET delta: an anchor repeats once per same-name symbol, so (against a
    # current anchor stamp) deleting one of two `main`s is one removal of `main`,
    # not "no change". A count-only decrease the stored signature tier proves
    # STALE (the stamp over-counts; `_stale_stamp_overcounts`) is not reported.
    # Sorted (K10).
    anchors_added: tuple[str, ...] = ()
    anchors_removed: tuple[str, ...] = ()
    # DIG-01: anchor_ids of SURVIVING documented symbols (present before AND after)
    # whose signature digest changed in place, from the stored `cdm.symbol_sigs`. Drives
    # the masked add+in-place-signature case to BREAKING; empty for a pure addition and
    # for a doc that predates DIG-01 (no stored per-symbol digests). Sorted (K10).
    sigs_changed: tuple[str, ...] = ()
    # Anchor collisions: the STAMPED anchor_ids now shared by 2+ same-name symbols
    # that COULD be hiding a signature move the per-anchor digests cannot
    # attribute — candidates, not culprits. Set only when an addition would
    # otherwise have graded ADDITIVE and the additions cannot be proven to explain
    # the whole signature-tier move; a wholly-new same-name group is never listed.
    # Non-empty ⇒ BREAKING (rule 2b). Sorted (K10); defaulted, so every existing
    # construction still validates (K6).
    sigs_ambiguous: tuple[str, ...] = ()
    # P5: the Griffe-style breaking-change severity of a HASH drift, classified from
    # drifted_tiers + the anchor deltas + sigs_changed (breaking/additive/cosmetic).
    # UNKNOWN for non-HASH drifts and for an OLD doc with no per-tier/anchor signals.
    change_severity: ChangeSeverity = ChangeSeverity.UNKNOWN
    # RTE-01: which AUTHORITY can close this drift, and the sorted evidence naming
    # the rule that decided. Provenance, never a score (K11). The default is the
    # DENY value, so a Drift built outside `detect` — or a construction point that
    # forgets to classify — fails SAFE and is never auto-applied.
    apply_tier: ApplyTier = ApplyTier.NEEDS_INTENT
    tier_evidence: tuple[str, ...] = ()


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
        # RTE-01/RTE-03b: the routing tally — how much of this report could close
        # itself, and by WHOSE authority. Appended LAST so every pre-RTE-01
        # substring assertion still holds (K9).
        #
        # The three buckets PARTITION the documents that have something to close.
        # A doc whose only drift is a SUSPECT_LINK is excluded from the
        # denominator entirely: it has nothing to close, so counting it anywhere
        # would mislabel it — as `mechanical` it is the phantom closure, and as
        # `delegated`/`held` it invents work that does not exist.
        actionable = {
            d.doc_id for d in self.drifts if d.kind is not DriftKind.SUSPECT_LINK
        }
        mech = mechanical_docs(self)
        held = actionable - auto_routable_docs(self)
        delegated = actionable - mech - held
        lines.append(
            f"routing: {len(mech)}/{len(actionable)} document(s) mechanical, "
            f"{len(delegated)} delegated, {len(held)} need human intent"
        )
        return "\n".join(lines)


def auto_routable_docs(report: DriftReport) -> frozenset[str]:
    """Doc ids whose EVERY actionable drift routes AUTO (pure, K10).

    **One ``NEEDS_INTENT`` drift holds the WHOLE document and nothing on it is
    written.** This per-DOCUMENT grain is the correctness condition of the epic, not
    a refinement of it: :func:`custodex.heal._corrected` skips a region it cannot
    render but still stamps the doc fingerprint, and that stamp is the ONLY staleness
    trigger such a region has (``stored != current``). Routing per-DRIFT would
    therefore let a document's mechanical HASH refresh bless its own sibling prose
    region into PERMANENT staleness — ``remaining`` comes back empty, ``cdx check``
    is green, and the next cycle detects nothing, forever. That is the exact
    inversion of "nothing is missed".

    ``SUSPECT_LINK`` drifts are excluded from the fold: :meth:`Monitor.run` skips
    past them and handles them in a pass that never calls ``apply_fix``, so they can
    neither be applied nor blessed — a doc↔doc edge must not veto its document. A
    document whose ONLY drifts are suspect links is therefore vacuously auto-routable,
    which is harmless: nothing on it ever reaches the apply gate.
    """
    return docs_closable_by(report, AUTO_TIERS)


def docs_closable_by(
    report: DriftReport,
    tiers: Collection[ApplyTier],
    *,
    require_actionable: bool = False,
) -> frozenset[str]:
    """Doc ids whose EVERY actionable drift carries a tier in ``tiers`` (pure, K10).

    The generalised per-document fold behind :func:`auto_routable_docs` (which asks
    "could this close itself at all?") and :func:`mechanical_docs` ("could the
    ENGINE close it, with no model at all?"). ``tiers`` is the only difference
    between the two questions — the fold itself is one implementation.

    ``require_actionable`` additionally demands at least ONE qualifying actionable
    drift. The fold is otherwise "nothing blocks", so a document whose only drift
    is a ``SUSPECT_LINK`` is a member by VACUOUS TRUTH. That is harmless for
    routing — nothing on such a doc ever reaches the apply gate — and dangerous for
    CLOSING, where it would produce a phantom closure claiming a document is done
    while its doc↔doc edge is still open and awaiting ``cdx resolve --edge``.
    """
    wanted = frozenset(tiers)
    actionable = [d for d in report.drifts if d.kind is not DriftKind.SUSPECT_LINK]
    # Blocking is by FILE, not by document id. `MonitorConfig` accepts two
    # documents that share a `path`: the fold keys on ``doc_id`` but the WRITE keys
    # on ``doc_path``, so closing the mechanical one would rewrite the held one's
    # file and stamp its fingerprint — blessing it with `cdx check` green and no
    # alarm. Same correctness condition as the per-document fold, one level down.
    #
    # Blocking by path SUBSUMES blocking by id: every drift a document raises
    # carries that document's own ``doc_path``, so a doc blocked by its own drift
    # is always blocked by its own file too. A separate ``blocked_ids`` set was
    # therefore dead weight — mutation testing proved it an equivalent mutant.
    blocked_paths = {d.doc_path for d in actionable if d.apply_tier not in wanted}
    qualified = (
        {(d.doc_id, d.doc_path) for d in actionable}
        if require_actionable
        else {(d.doc_id, d.doc_path) for d in report.drifts}
    )
    return frozenset(
        doc_id for doc_id, doc_path in qualified if doc_path not in blocked_paths
    )


def mechanical_docs(report: DriftReport) -> frozenset[str]:
    """Doc ids the ENGINE can close entirely by itself — no model at all (pure, K10).

    Strictly NARROWER than :func:`auto_routable_docs`: ``DELEGATED`` is
    auto-routable but is prose a MODEL authors, which is RTE-04 and carries a K11
    widening that needs explicit human ratification. This set is the one an
    unattended write is allowed to touch, so it also requires a qualifying
    actionable drift (see ``require_actionable``).
    """
    return docs_closable_by(report, {ApplyTier.CODE_DERIVED}, require_actionable=True)


def _signature_reproduced(
    surface: DocumentSurface,
    set_aside: Collection[str],
    stored_tiers: SurfaceFingerprint,
) -> bool:
    """Does the surface, minus ``set_aside``, re-derive the stored signature tier?

    Pure (K1/K10). Every symbol whose anchor is in ``set_aside`` is dropped and
    the SIGNATURE tier is re-derived with the engine's own
    :meth:`DocumentSurface.fingerprint` (records kept). That payload lists EVERY
    occurrence, name-sorted, so a byte-for-byte match means the symbols left are
    exactly the ones the tier was stamped over: the same names, the same count
    per name, the same signatures.
    """
    kept = tuple(s for s in surface.symbols if s.anchor_id not in set_aside)
    baseline = surface.model_copy(update={"symbols": kept}).fingerprint()
    return baseline.signature == stored_tiers.signature


def _stale_stamp_overcounts(
    surface: DocumentSurface,
    current_counts: Counter[str],
    stored_counts: Counter[str],
    stored_tiers: SurfaceFingerprint | None,
    drifted_tiers: Sequence[str],
) -> frozenset[str]:
    """Anchors whose COUNT-ONLY decrease is a stale stamp's, not a deletion.

    Pure (K1/K10). A count-only decrease is an anchor the stamp counts more
    often than the code while the code still has it (``0 < current < stored``):
    one of several same-name symbols is gone. Against a CURRENT stamp that is a
    genuine removal (rule 1). But the stamp can OVER-count. Heal re-stamps
    ``fingerprint_tiers`` and ``symbol_sigs`` on every write, yet stamps
    ``region_anchors`` only when it renders the region. So once a same-name
    symbol is deleted on a doc whose ``symbols`` region is preserved (``mode:
    human``, B-03-locked) or absent from the body, the stamp keeps counting it,
    and — read as a removal — it would hold EVERY later drift on that doc
    BREAKING with a phantom "-1", even a docstring-only edit.

    The stored signature tier arbitrates. Every engine writer of the anchor
    stamp (``heal._corrected``, ``layout.scaffold_doc``) also stamps the tiers
    from the same surface in the same write, so where the two disagree the tier
    is the newer. The decreases are returned — to be discharged — only when the
    tier PROVES the stamp stale:

    * no stored tier ⇒ nothing to prove it with ⇒ ``frozenset()`` (keep);
    * the signature tier did not move ⇒ the code's signature population is the
      stored one, so the tier counts exactly what the code has ⇒ stale;
    * else the tier re-derived with every ADDED anchor set aside
      (:func:`_signature_reproduced`) reproduces the stored one ⇒ the
      surviving occurrences are exactly those the tier was stamped over ⇒ stale;
    * otherwise keep every decrease (the proof is tier-wide: all or nothing).

    A genuine same-name deletion always changes the name-sorted payload, which
    lists every occurrence, so neither proof passes against a current tier and
    the removal stands. A wholly-removed name (count 0) is never discharged:
    the set delta reported it before the multiset existed. Where the tiers are
    stale TOO — a backend's whole-doc FIX through ``heal.apply_fix`` writes the
    model's front matter as returned — nothing is proven and the removal is
    kept. The premise binds future writers: one that stamps ``region_anchors``
    without re-stamping ``fingerprint_tiers`` would make a stale tier look
    newer, and this proof would then discharge a real deletion.
    """
    shrunk = frozenset(a for a, n in stored_counts.items() if 0 < current_counts[a] < n)
    if not shrunk or stored_tiers is None:
        return frozenset()
    if "signature" not in drifted_tiers or _signature_reproduced(
        surface, current_counts - stored_counts, stored_tiers
    ):
        return shrunk
    return frozenset()


def _ambiguous_sig_anchors(
    surface: DocumentSurface,
    current_counts: Counter[str],
    stored_counts: Counter[str],
    stored_tiers: SurfaceFingerprint | None,
    drifted_tiers: Sequence[str],
) -> tuple[str, ...]:
    """Repeating anchors that could be HIDING a signature move (pure, K1/K10).

    An anchor is the qualified name only, so same-name symbols share one — and
    DIG-01's per-symbol digest map keeps only the LAST writer per anchor. Called
    only where the classification is about to say ``ADDITIVE`` (anchors added,
    NONE removed, no attributed ``sigs_changed``). It reads only the anchor stamp
    and the stored tiers — never ``symbol_sigs`` — so a doc stamped before
    DIG-01 (no per-symbol digests until its next heal) is protected too.

    The CANDIDATES are the anchors that repeat now AND were already stamped. With
    nothing removed the current multiset contains the stored one, so an anchor
    that repeated when stamped still repeats now, and one stamped once that now
    repeats is a grown collision — both are candidates. A wholly-NEW same-name
    group (an ``@overload`` stack added in this edit) never is: it has no stored
    digest to shadow and the proof below sets every one of its occurrences
    aside, so it can hide nothing, and naming it would send the reviewer to an
    innocent symbol (and make the verdict depend on whether a new name repeats).
    The guard runs for ANY addition, a grown-only one included (a new same-name
    symbol and no new name): it is not reserved for edits adding a new name.

    Returns the candidates, sorted, unless the move is PROVABLY explained by the
    additions, else ``()``:

    * no candidate ⇒ ``()`` — every stamped anchor still names one symbol, so
      DIG-01's digests are exact. Every later branch returns ``()`` or the (here
      empty) candidate tuple anyway, so this is purely the fast path that skips
      a re-derivation, not a rule;
    * no stored signature tier ⇒ nothing can prove the move innocent ⇒ deny;
    * the signature tier did not move ⇒ ``()`` — no signature changed anywhere.
      Only reachable with a stale anchor stamp and a docstring/body-only edit
      (a real addition always moves the signature tier), and the edit then
      grades ``ADDITIVE`` with a phantom "+N" in the detail — where the pre-fix
      set delta said ``COSMETIC`` for a phantom grown collision. The routing
      (``CODE_DERIVED``) is the same;
    * else set every symbol under an ADDED anchor aside and re-derive the
      signature tier (:func:`_signature_reproduced`). Reproducing the stored
      digest byte-for-byte means the additions explain the whole move ⇒ ``()``.
      Anything else denies, and the candidates are only the anchors that COULD
      hide a change — never a claim that one did. The move may come from any
      of: a shadowed same-name symbol changed; a same-name tie reordered; a
      GROWN collision (setting aside all of an added anchor's occurrences can
      never reproduce a digest that held some of them, because which
      occurrence is new cannot be told from name-keyed stamps); a ``records``
      change (rows fold into the signature tier); or an in-place change to a
      unique symbol on a doc stamped without ``symbol_sigs`` (pre-DIG-01, so
      ``sigs_changed`` could not attribute it). Unattributable is not innocent
      (RTE-01).

    KNOWN COST (until review slice 1b makes the tie order lineno-free): same-name
    symbols are ordered by ``(name, lineno)`` and the signature payload is order-
    sensitive, so a PURE addition travelling with ANY edit that reorders
    same-name colliders while the last writer stays last — lines added OR
    removed above a collider move it past a non-last sibling with a different
    signature (a function inserted near the top of a module, an import line
    added above it or an unused one deleted); it takes 3+ same-name symbols —
    cannot be proven and is held. A reorder that changes the last writer was
    already ``BREAKING`` under DIG-01 (its digest moves: rule 2), except on a doc
    stamped without ``symbol_sigs``, where it reaches this proof and is held
    too. Nothing is searched to undo such a reorder — an enumeration would need
    a bound, which is a tunable.

    KNOWN COST (until per-occurrence identity, review slice 2): a GROWN
    collision — a new same-name symbol under a stamped anchor (another overload
    in an existing ``@overload`` stack, another ``main``) — can never be proven
    (see above), so it is always held. ALONE (no wholly-new name) that costs
    nothing new: the pre-fix set delta saw no addition and rule 4 held it too,
    and it must stay held, because the new occurrence can shadow a break. In
    the SAME edit as another addition it is newly held: the pre-fix engine
    graded that ``ADDITIVE`` on the new name (unless the new occurrence became
    the last writer, which rule 2 already holds).

    KNOWN COST (until the anchor stamp is completed on every write, step-1
    slice S1-E4): a STALE anchor stamp — one that under-counts OR over-counts a
    same-name symbol relative to the stored tiers. Three writers leave one:
    heal skips a PRESERVED ``symbols`` region (``mode: human`` healed by ``cdx
    generate``, or a B-03-locked region); heal stamps anchors only for a region
    PRESENT in the body, so a declared ``symbols`` region a human deleted keeps
    its last stamp — both still re-stamp ``fingerprint_tiers`` and
    ``symbol_sigs``; and a backend's whole-doc FIX through ``heal.apply_fix``
    (the live-LLM path) writes the model's front matter as returned —
    typically the current composite copied from the drift detail over
    otherwise stale stamps, tiers included. Only an engine RENDER of the region
    (``heal._corrected``) re-stamps the anchors. Three effects follow:

    * UNDER-count, OVER-hold (this proof): every later pure addition reports the
      under-counted symbol as a PHANTOM addition (a phantom grown collision, or
      a phantom new name), the proof sets it aside against a tier that contains
      it, and — on a doc with a stamped same-name anchor — the addition is held
      on every cycle. For a preserved region this changes only the HASH label:
      its B-02 REGION advisory holds the doc whenever the owned body differs
      from the render, which a pure addition always causes (it adds a table
      row). For an absent region or a whole-doc backend fix it changes the
      routing. It is kept: keeping stamped anchors' occurrences in the
      re-derivation would clear only the phantom grown collision and would
      trust a stamp known to be wrong; the fix belongs at the writers.
    * UNDER-count, UNDER-hold (not this proof, and not changed by it): deleting
      the under-counted same-name symbol puts no removal in the multiset delta
      and no candidate repeats, so a delete + add grades ``ADDITIVE`` exactly as
      it did before this guard existed — a hidden deletion ``--tiered`` can
      close. Completing the anchor stamp closes it; S1-ADDPROOF closes it only
      where the stored tiers are current (not after a whole-doc backend fix).
    * OVER-count (a same-name symbol deleted since the stamp): the count-only
      decrease would read as a phantom removal on every later drift. ``detect``
      discharges it where the stored signature tier proves the stamp stale
      (:func:`_stale_stamp_overcounts`) — after heal's preserved and
      absent-region writes, whose tiers are current — so the verdict is the
      pre-fix engine's. Where the same edit ALSO moves a signature (a real
      in-place or ``records`` change) nothing is proven, and the phantom "-1"
      rides beside a verdict that is ``BREAKING`` anyway; the heal that
      resolves it re-stamps the tier, so the discharge applies again next
      time. After a whole-doc backend fix the tiers are stale too: the phantom
      removal is kept and the doc held, which the pre-fix engine also did
      whenever the stale last-writer digest moved (colliders with different
      signatures).

    Only the SIGNATURE tier is proven. It hashes signature-only symbols plus
    records — never a docstring or a body — so a docstring/body edit in the same
    change cannot hide a signature move, and proving the composite instead would
    hold every addition that travels with one. No body flag enters the re-derivation.
    """
    repeating = tuple(
        sorted(a for a, n in current_counts.items() if n > 1 and a in stored_counts)
    )
    if not repeating:
        return ()
    if stored_tiers is None:
        return repeating
    if "signature" not in drifted_tiers:
        return ()
    added = current_counts - stored_counts
    return () if _signature_reproduced(surface, added, stored_tiers) else repeating


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
            tier, evidence = classify_apply_tier(
                DriftKind.MISSING_DOC, ChangeSeverity.UNKNOWN, healable=True
            )
            drifts.append(
                Drift(
                    kind=DriftKind.MISSING_DOC,
                    doc_id=spec.id,
                    doc_path=spec.path,
                    detail="document file is missing — a stub can be created",
                    healable=True,
                    audience=spec.audience,
                    apply_tier=tier,
                    tier_evidence=evidence,
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
            # P4: classify the change by symbol IDENTITY. Compare the anchors the
            # symbol-table region documents now against the stamped ones; a delta
            # means a symbol was added/removed/renamed (structural), while an empty
            # delta means the SAME symbols changed internally (a re-bind, not a
            # structural move). Empty when the doc has no stamped anchors (pre-P4).
            # MULTISETS, not sets: an anchor is the qualified name only, so it
            # repeats once per same-name symbol (and the stamped `region_anchors`
            # keep those duplicates). As sets, deleting one of two `main`s was "no
            # removal" and a same-edit addition graded ADDITIVE. The count is only
            # as current as the stamp: a stale one that under-counts `main` still
            # hides that deletion (see `_ambiguous_sig_anchors`, KNOWN COST); one
            # that OVER-counts it is discharged below when the stored signature
            # tier proves the stamp stale (`_stale_stamp_overcounts`).
            current_counts = Counter(sym.anchor_id for sym in surface.symbols)
            current_anchors = set(current_counts)
            stored_counts: Counter[str] | None = None
            for region_id in spec.region_keys:
                if region_id not in REGION_KEYS:
                    continue
                stamped = stored_region_anchors(doc, region_id)
                if stamped is not None:
                    # `|` is the multiset UNION (max count) — the analogue of the
                    # set union it replaces, and idempotent: a key the config lists
                    # twice (accepted today) re-reads the same stamp, and a SUM would
                    # double every count into a phantom removal.
                    stored_counts = (
                        Counter(stamped)
                        if stored_counts is None
                        else stored_counts | Counter(stamped)
                    )
            anchors_added: tuple[str, ...] = ()
            anchors_removed: tuple[str, ...] = ()
            if stored_counts is not None:
                # A count-only decrease the stored tier proves stale is the
                # stamp's, not the code's: a phantom removal would otherwise hold
                # every later drift on the doc.
                stale = _stale_stamp_overcounts(
                    surface, current_counts, stored_counts, stored_tiers, drifted_tiers
                )
                anchors_added = tuple(
                    sorted((current_counts - stored_counts).elements())
                )
                anchors_removed = tuple(
                    sorted(
                        a
                        for a in (stored_counts - current_counts).elements()
                        if a not in stale
                    )
                )
                if anchors_added or anchors_removed:
                    detail += (
                        f" (anchored symbols changed: +{len(anchors_added)}/"
                        f"-{len(anchors_removed)})"
                    )
            # DIG-01: among the SURVIVING symbols (present before AND after), which
            # signatures changed IN PLACE? Compare the stored per-symbol digests
            # (`cdm.symbol_sigs`) to the current ones. ``None`` ⇒ a pre-DIG-01 doc, so
            # leave it empty and let severity degrade to the aggregate behaviour (K6).
            sigs_changed: tuple[str, ...] = ()
            stored_sig_map = stored_symbol_sigs(doc)
            if stored_sig_map is not None:
                current_sig_map = current_fp.sig_by_anchor or {}
                survivors = current_anchors & set(stored_sig_map)
                sigs_changed = tuple(
                    sorted(
                        a
                        for a in survivors
                        if current_sig_map.get(a) != stored_sig_map.get(a)
                    )
                )
            # Anchor collisions: DIG-01's digests are keyed by anchor, so a change
            # to a SHADOWED same-name symbol is invisible to `sigs_changed`. Only
            # consulted where it could matter — when an addition would otherwise
            # grade ADDITIVE (removals and attributed changes already say BREAKING).
            sigs_ambiguous: tuple[str, ...] = ()
            if (
                stored_counts is not None
                and anchors_added
                and not anchors_removed
                and not sigs_changed
            ):
                sigs_ambiguous = _ambiguous_sig_anchors(
                    surface,
                    current_counts,
                    stored_counts,
                    stored_tiers,
                    drifted_tiers,
                )
                if sigs_ambiguous:
                    # Describe the PROOF that failed, never a culprit: the detail
                    # is copied into the ReviewRecord a human acts on (K5), and the
                    # move may come from records or a tie reorder, not a collider.
                    why = (
                        "no stored signature tier to check the additions against"
                        if stored_tiers is None
                        else "the additions alone do not reproduce the stored "
                        "signature tier"
                    )
                    detail += (
                        f" (unproven: {why}; {len(sigs_ambiguous)} same-name "
                        "anchor(s) could hide a change)"
                    )
            # P5/DIG-01: classify the breaking-change severity from the structural
            # signals just computed (no new analysis) so check/monitor/the audit record
            # can say breaking vs additive vs cosmetic at a glance.
            change_severity = classify_change_severity(
                drifted_tiers,
                anchors_added,
                anchors_removed,
                sigs_changed,
                sigs_ambiguous,
            )
            # RTE-01: and which authority could close it (pure, consumes the
            # severity above — never re-tunes it, K9).
            tier, evidence = classify_apply_tier(
                DriftKind.HASH, change_severity, healable=True
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
                    sigs_changed=sigs_changed,
                    sigs_ambiguous=sigs_ambiguous,
                    change_severity=change_severity,
                    apply_tier=tier,
                    tier_evidence=evidence,
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
                        tier, evidence = classify_apply_tier(
                            DriftKind.REGION,
                            ChangeSeverity.UNKNOWN,
                            healable=True,
                            region_id=region_id,
                            region_mode=mode,
                            renderer_backed=False,
                        )
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
                                apply_tier=tier,
                                tier_evidence=evidence,
                            )
                        )
                    continue
                tier, evidence = classify_apply_tier(
                    DriftKind.UNHEALABLE,
                    ChangeSeverity.UNKNOWN,
                    healable=False,
                    region_id=region_id,
                    region_mode=mode,
                )
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
                        apply_tier=tier,
                        tier_evidence=evidence,
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
                tier, evidence = classify_apply_tier(
                    DriftKind.REGION,
                    ChangeSeverity.UNKNOWN,
                    healable=not owned,
                    region_id=region_id,
                    region_mode=mode,
                    renderer_backed=True,
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
                        apply_tier=tier,
                        tier_evidence=evidence,
                    )
                )

    # EPIC B: append doc↔doc suspect links (a downstream whose upstream changed).
    # Pure data like any other Drift; never auto-edited (healable=False) — a human
    # re-confirms with `cdx resolve --edge`. Gated by `docdeps.enabled` inside
    # detect_suspect_links. Detection writes nothing (K1).
    for link in detect_suspect_links(config, root):
        tier, evidence = classify_apply_tier(
            DriftKind.SUSPECT_LINK, ChangeSeverity.UNKNOWN, healable=False
        )
        drifts.append(
            Drift(
                kind=DriftKind.SUSPECT_LINK,
                doc_id=link.doc_id,
                doc_path=link.doc_path,
                detail=f"{link.upstream_id}: {link.detail}",
                healable=False,
                audience=link.audience,
                apply_tier=tier,
                tier_evidence=evidence,
            )
        )

    return DriftReport(drifts=tuple(drifts))
