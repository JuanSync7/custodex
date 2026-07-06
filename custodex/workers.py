"""AGT-06 — the two background suggesters: pure ticks, keyed suggestions (K11).

The "two running parallel in Custodex". Each tick is a PURE fold (K1 sense:
read-only filesystem, no mutation, no network, no clock in any output field
that matters) over detectors the engine already ships — the workers NEVER
detect anything new, they only package current reality into an actionable
inbox whose every ``detail`` embeds the exact next HUMAN command (agents
suggest; humans apply — K11):

* :func:`suggest_fixes_tick` — what needs a human NOW: ``FIX_DRIFT`` (per
  drifted doc, from :func:`custodex.drift.detect` — ``SUSPECT_LINK`` drifts
  are excluded here because ``RESOLVE_EDGE`` owns edges: one problem, one
  suggestion), ``RESOLVE_EDGE`` (per non-OK edge from
  :func:`custodex.docdeps.detect_suspect_links`), ``PROMOTE_RULE`` (per
  :func:`custodex.promotion.detect_promotions` candidate over the local
  review/resolution logs).
* :func:`suggest_docs_tick` — what to document and map next:
  ``DOCUMENT_GAP`` (per mentioned-but-undocumented symbol from the AGT-03
  graph's :func:`~custodex.kgraph.rank_centrality` feed) and ``ADD_EDGE``
  (per :func:`custodex.docmap.suggest_edges` suggestion, honoring the
  repo-side :func:`~custodex.docmap.read_rejections` verdicts).

**Key discipline** (the ⟨R⟩ pin — regression-guarded): ``Suggestion.key`` is
``sha256[:16]`` over PINNED STRUCTURED FIELDS per kind, NEVER the prose —
``detail`` / ``evidence`` / ``severity`` / ``now`` are excluded, so a reworded
detail keeps its key while a different OCCURRENCE changes it. Two lifecycle
classes follow from what is hashed:

* **EVENT kinds** (``FIX_DRIFT``, ``RESOLVE_EDGE``) embed the occurrence —
  the current surface hash / upstream fingerprint — so a recurrence AFTER a
  heal is a NEW key and a dismiss silences exactly one occurrence.
* **STANDING kinds** (``ADD_EDGE``, ``DOCUMENT_GAP``, ``PROMOTE_RULE``) are
  occurrence-free — a dismiss is the durable opt-out (and ``ADD_EDGE``
  additionally honors the EdgeRejection file, the repo-side 'no').

``now`` is accepted by both ticks but reserved for the STORED envelope's
``recorded_at`` at the edges (CLI ``--write`` / the server worker loop) — it
never reaches a key (K10). Output is sorted by key (K10).
"""

from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .config import MonitorConfig, resolve_repo_root
from .docdeps import SuspectStatus, detect_suspect_links, upstream_fingerprint
from .docmap import read_rejections, suggest_edges
from .drift import DriftKind, detect
from .extract import build_document_surface
from .kgraph import build_graph, rank_centrality
from .manifest import parse_text
from .monitor import DEFAULT_LOG_PATH
from .promotion import detect_promotions
from .reviewlog import DEFAULT_RESOLUTIONS_PATH, read_all, read_resolutions
from .worklist import WorkSeverity

__all__ = [
    "SuggestionKind",
    "Suggestion",
    "suggest_fixes_tick",
    "suggest_docs_tick",
    "render_suggestions_text",
]

# Frozen + extra="forbid": a suggestion is an immutable advisory snapshot (K10).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class SuggestionKind(str, Enum):
    """The closed suggestion taxonomy (extend deliberately, K6)."""

    FIX_DRIFT = "fix_drift"  # EVENT: a doc drifted from its code surface
    RESOLVE_EDGE = "resolve_edge"  # EVENT: a doc↔doc edge needs re-confirmation
    PROMOTE_RULE = "promote_rule"  # STANDING: a unanimous shape can go LLM-free
    DOCUMENT_GAP = "document_gap"  # STANDING: mentioned-but-undocumented code
    ADD_EDGE = "add_edge"  # STANDING: a suggested depends_on mapping


#: Deterministic severity per kind; ``.get(..., MEDIUM)`` is the robustness
#: default for a future kind that misses this map (⟨R⟩ — not a K8 citation).
_SEVERITY: dict[SuggestionKind, WorkSeverity] = {
    SuggestionKind.FIX_DRIFT: WorkSeverity.HIGH,
    SuggestionKind.RESOLVE_EDGE: WorkSeverity.MEDIUM,
    SuggestionKind.PROMOTE_RULE: WorkSeverity.LOW,
    SuggestionKind.DOCUMENT_GAP: WorkSeverity.LOW,
    SuggestionKind.ADD_EDGE: WorkSeverity.LOW,
}


class Suggestion(BaseModel):
    """One advisory work item — the unit both ticks emit (pure data, K11)."""

    model_config = _MODEL_CONFIG

    key: str  # sha256[:16] over the kind's PINNED fields (see module doc)
    kind: SuggestionKind
    doc_id: str | None  # the doc this concerns (None for repo-level gaps)
    target: str  # the object of the suggestion (doc id / entity id / shape)
    detail: str  # human sentence embedding the exact next command
    evidence: tuple[str, ...]  # sorted supporting facts (never hashed)
    severity: WorkSeverity


def _key(kind: SuggestionKind, *fields: str) -> str:
    """The pinned key: kind + structured fields, unit-separated, sha256[:16]."""
    payload = "\x1f".join((kind.value, *fields))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _severity(kind: SuggestionKind) -> WorkSeverity:
    return _SEVERITY.get(kind, WorkSeverity.MEDIUM)


def suggest_fixes_tick(
    config: MonitorConfig, config_dir: Path, *, now: str
) -> tuple[Suggestion, ...]:
    """The FIXES suggester: drift / suspect edges / promotable shapes (pure).

    ``now`` is reserved for the stored envelope at the edges — it never
    reaches a key or any emitted field (K10).
    """
    del now  # reserved: the envelope's recorded_at is stamped at the edges
    root = resolve_repo_root(config_dir, config.root)
    out: list[Suggestion] = []

    # FIX_DRIFT — one suggestion per drifted doc (EVENT: surface hash in key).
    # SUSPECT_LINK drifts are excluded: RESOLVE_EDGE owns edges — one problem
    # must never bill two suggestions.
    report = detect(config, config_dir)
    by_doc: dict[str, list] = {}
    for drift in report.drifts:
        if drift.kind is DriftKind.SUSPECT_LINK:
            continue
        by_doc.setdefault(drift.doc_id, []).append(drift)
    for doc_id in sorted(by_doc):
        drifts = by_doc[doc_id]
        spec = next(d for d in config.documents if d.id == doc_id)
        surface_hash = build_document_surface(spec, root).fingerprint().composite
        kinds = sorted({d.kind.value for d in drifts})
        out.append(
            Suggestion(
                key=_key(
                    SuggestionKind.FIX_DRIFT, doc_id, ",".join(kinds), surface_hash
                ),
                kind=SuggestionKind.FIX_DRIFT,
                doc_id=doc_id,
                target=spec.path,
                detail=(
                    f"{len(drifts)} drift(s) [{', '.join(kinds)}] on "
                    f"{spec.path} — review and heal with `cdx monitor --apply`"
                ),
                evidence=tuple(
                    sorted(f"{d.kind.value}:{d.region_id or d.detail}" for d in drifts)
                ),
                severity=_severity(SuggestionKind.FIX_DRIFT),
            )
        )

    # RESOLVE_EDGE — one per non-OK edge (EVENT: the CURRENT upstream
    # fingerprint in the key, so a re-suspicion after an ack is new work).
    suspect = detect_suspect_links(config, root)
    doc_by_id = {d.id: d for d in config.documents}
    for link in suspect:
        if link.status is SuspectStatus.OK:
            continue
        upstream_spec = doc_by_id.get(link.upstream_id)
        fingerprint = "missing"
        if upstream_spec is not None:
            upstream_path = root / upstream_spec.path
            if upstream_path.is_file():
                doc = parse_text(
                    upstream_path.read_text(encoding="utf-8"), upstream_path
                )
                fingerprint = upstream_fingerprint(
                    doc, baseline=config.docdeps.baseline
                )
        out.append(
            Suggestion(
                key=_key(
                    SuggestionKind.RESOLVE_EDGE,
                    link.doc_id,
                    link.upstream_id,
                    fingerprint,
                ),
                kind=SuggestionKind.RESOLVE_EDGE,
                doc_id=link.doc_id,
                target=link.upstream_id,
                detail=(
                    f"edge {link.doc_id} → {link.upstream_id} is "
                    f"{link.status.value} — review the upstream change, then "
                    f"`cdx resolve --edge {link.doc_id} {link.upstream_id}`"
                ),
                evidence=(f"{link.status.value}: {link.detail}",),
                severity=_severity(SuggestionKind.RESOLVE_EDGE),
            )
        )

    # PROMOTE_RULE — one per unanimous shape (STANDING: occurrence-free key).
    records = read_all(config_dir / DEFAULT_LOG_PATH)
    resolutions = read_resolutions(config_dir / DEFAULT_RESOLUTIONS_PATH)
    for cand in detect_promotions(records, resolutions):
        out.append(
            Suggestion(
                key=_key(
                    SuggestionKind.PROMOTE_RULE,
                    cand.doc_id,
                    cand.drift_kind,
                    cand.audience.value,
                    cand.resolution.value,
                ),
                kind=SuggestionKind.PROMOTE_RULE,
                doc_id=cand.doc_id,
                target=f"{cand.drift_kind}:{cand.audience.value}",
                detail=(
                    f"{cand.count} resolved record(s) on ({cand.doc_id}, "
                    f"{cand.drift_kind}, {cand.audience.value}) unanimously "
                    f"'{cand.resolution.value}' — promote to a deterministic "
                    "rule (`cdx promote`) so the backend is no longer consulted"
                ),
                evidence=(f"count: {cand.count}",),
                severity=_severity(SuggestionKind.PROMOTE_RULE),
            )
        )

    return tuple(sorted(out, key=lambda s: s.key))


def suggest_docs_tick(
    config: MonitorConfig, config_dir: Path, *, now: str
) -> tuple[Suggestion, ...]:
    """The DOCS suggester: coverage gaps + mapping suggestions (pure).

    ``now`` is reserved for the stored envelope at the edges (K10).
    """
    del now  # reserved: the envelope's recorded_at is stamped at the edges
    root = resolve_repo_root(config_dir, config.root)
    out: list[Suggestion] = []

    # DOCUMENT_GAP — one per mentioned-but-undocumented symbol (STANDING).
    g = build_graph(config, root)
    for node_id, count in rank_centrality(g, undocumented_only=True):
        path = node_id.split(" ", 1)[1].split("#", 1)[0]
        out.append(
            Suggestion(
                key=_key(SuggestionKind.DOCUMENT_GAP, node_id),
                kind=SuggestionKind.DOCUMENT_GAP,
                doc_id=None,
                target=node_id,
                detail=(
                    f"{node_id} is mentioned by {count} doc(s) but covered by "
                    f"none — draft a doc with `cdx write-doc {path}`"
                ),
                evidence=(f"{count} mentioning doc(s)",),
                severity=_severity(SuggestionKind.DOCUMENT_GAP),
            )
        )

    # ADD_EDGE — one per suggested mapping (STANDING; rejections honored: a
    # durable human 'no' silences the pair for the worker too).
    rejections = read_rejections(config_dir / ".cdmon")
    for edge in suggest_edges(config, root, rejections=rejections):
        out.append(
            Suggestion(
                key=_key(
                    SuggestionKind.ADD_EDGE,
                    edge.doc_id,
                    edge.upstream_id,
                    edge.tier.value,
                ),
                kind=SuggestionKind.ADD_EDGE,
                doc_id=edge.doc_id,
                target=edge.upstream_id,
                detail=(
                    f"{edge.tier.value} evidence links {edge.doc_id} → "
                    f"{edge.upstream_id} — accept with `cdx link {edge.doc_id} "
                    f"{edge.upstream_id}` or silence with `cdx link --reject "
                    f"{edge.doc_id} {edge.upstream_id}`"
                ),
                evidence=edge.evidence,
                severity=_severity(SuggestionKind.ADD_EDGE),
            )
        )

    return tuple(sorted(out, key=lambda s: s.key))


#: Display rank: high first (mirrors the worklist and the stored inbox).
_SEVERITY_RANK = {
    WorkSeverity.HIGH: 0,
    WorkSeverity.MEDIUM: 1,
    WorkSeverity.LOW: 2,
}


def render_suggestions_text(
    suggestions: tuple[Suggestion, ...] | list[Suggestion],
) -> str:
    """A deterministic plain-text inbox (K10) — the ``cdx suggest`` view.

    Rendered SEVERITY-FIRST (high → medium → low, then key) — the reading
    order a human triages in (DEMO-107's claim, PR #20 fresh-review fix). The
    tick outputs themselves stay key-sorted; only the display reorders.
    """
    if not suggestions:
        return "# no suggestions — all clear"
    ordered = sorted(
        suggestions, key=lambda s: (_SEVERITY_RANK.get(s.severity, 1), s.key)
    )
    lines = [f"# {len(ordered)} suggestion(s) — advisory; humans apply (K11):"]
    for s in ordered:
        who = f" [{s.doc_id}]" if s.doc_id else ""
        lines.append(f"  {s.severity.value:<6} {s.kind.value}{who} {s.key}")
        lines.append(f"         {s.detail}")
    return "\n".join(lines)
