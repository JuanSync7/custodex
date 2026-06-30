"""Pillar B — document↔document dependencies + suspect-link drift (EPIC B).

The doc↔doc analogue of code↔doc drift, built on the proven Doorstop model: a
document declares it ``depends_on`` an upstream document (the DECLARATION lives in
config, the source of truth K2); the downstream carries a per-edge baseline STAMP
— the upstream's content hash at last review — in its ``cdm.upstream_hashes``
front matter (machine-managed, exactly like ``cdm.fingerprint``). When the
upstream's body changes, the stamp no longer matches and the edge is **suspect**
until a human re-confirms it with ``cdx resolve --edge`` (the Doorstop ``clear``).

This mirrors :mod:`custodex.ownership`: a pure detection core (no clock, no
network, no new dependency — K0/K1/K10) that both the engine/`cdx` CLI and the
server drive, plus one clearly-isolated impure writer (:func:`stamp_edges`) used
only by the mutation commands (``link`` / ``resolve`` / ``monitor --apply``),
never by the detect-only ``check``.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Sequence
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .config import Audience, DocEdgeType, MonitorConfig
from .errors import DriftError
from .manifest import (
    Doc,
    parse_doc,
    region_body_hash,
    render_doc,
    set_upstream_hash,
    stored_upstream_hashes,
)

__all__ = [
    "SuspectStatus",
    "SuspectLink",
    "InferredEdge",
    "upstream_fingerprint",
    "detect_suspect_links",
    "infer_edges_from_links",
    "impacted_by",
    "propagate_suspect",
    "stamp_edges",
    "render_deps_text",
    "render_impact_text",
]

# Frozen + extra="forbid": a suspect-link verdict is an immutable snapshot and an
# unknown key is a loud error (K8), mirroring the config + ownership models.
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

# A Markdown inline link: [text](target). Capture the target only.
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


class SuspectStatus(str, Enum):
    """How one downstream→upstream edge stands against its baseline stamp."""

    OK = "ok"  # the upstream is unchanged since the edge was last reviewed
    UNSTAMPED = "unstamped"  # the edge has no baseline yet — needs a first review
    SUSPECT = "suspect"  # the upstream changed; re-confirm the downstream
    MISSING_UPSTREAM = "missing_upstream"  # the upstream doc file is gone
    # An ADVISORY status (PROP-01): a directly-suspect upstream lies transitively
    # upstream of this edge, so it will need re-confirming once the wavefront reaches
    # it. Emitted ONLY by :func:`propagate_suspect`, never by detect; it does NOT gate
    # `cdx check` and never mints a drift (a transitive edge has no changed upstream
    # body to stamp — K7).
    SUSPECT_TRANSITIVE = "suspect_transitive"


class SuspectLink(BaseModel):
    """One downstream→upstream edge verdict (data, never an exception)."""

    model_config = _MODEL_CONFIG

    doc_id: str  # the downstream (dependent) document
    doc_path: str
    upstream_id: str  # the document this one depends on
    type: DocEdgeType
    status: SuspectStatus
    detail: str
    audience: Audience  # the DOWNSTREAM doc's audience (K3)


class InferredEdge(BaseModel):
    """A link-inference suggestion: a doc→doc edge implied by a Markdown link."""

    model_config = _MODEL_CONFIG

    doc_id: str  # the downstream doc that contains the link
    upstream_id: str  # the managed doc the link points at
    via: str  # the relative link target that implied the edge


def upstream_fingerprint(doc: Doc) -> str:
    """The hash of an upstream doc's BODY (not its front matter), sha256[:16] (K10).

    Body-only on purpose: the upstream's own ``cdm.fingerprint`` re-stamp (a
    code↔doc heal) churns its front matter but not its meaning, and must NOT trip a
    suspect link. Reuses :func:`manifest.region_body_hash` so the normalization
    (CRLF→LF, first 16 hex) is identical to every other content hash in the engine.
    """
    return region_body_hash(doc.body)


def _path_to_id(config: MonitorConfig) -> dict[str, str]:
    """Map each managed document's normalized repo-relative path → its id."""
    return {posixpath.normpath(doc.path): doc.id for doc in config.documents}


def detect_suspect_links(
    config: MonitorConfig, root: Path, *, include_ok: bool = False
) -> tuple[SuspectLink, ...]:
    """Classify every doc↔doc edge against its baseline stamp (pure, K1/K10).

    For each document with ``depends_on`` edges, recompute each upstream's
    :func:`upstream_fingerprint` and compare it to the downstream's stored stamp:
    equal⇒OK, differ⇒SUSPECT, absent⇒UNSTAMPED, upstream file gone⇒MISSING_UPSTREAM.
    ``OK`` edges are omitted unless ``include_ok`` (so the default result is exactly
    the edges that need a human, like :func:`ownership.detect_orphans`). Returns
    ``()`` when ``docdeps.enabled`` is False. Sorted by ``(doc_id, upstream_id)``.
    """
    if not config.docdeps.enabled:
        return ()
    specs_by_id = {doc.id: doc for doc in config.documents}
    _cache: dict[str, str | None] = {}  # upstream id -> current fingerprint or None

    def _current(upstream_id: str) -> str | None:
        if upstream_id not in _cache:
            up_spec = specs_by_id[upstream_id]
            up_path = root / up_spec.path
            _cache[upstream_id] = (
                upstream_fingerprint(parse_doc(up_path)) if up_path.is_file() else None
            )
        return _cache[upstream_id]

    out: list[SuspectLink] = []
    for spec in config.documents:
        if not spec.depends_on:
            continue
        down_path = root / spec.path
        if not down_path.is_file():
            # The downstream's own MISSING_DOC drift covers it; nothing to stamp.
            continue
        stamps = stored_upstream_hashes(parse_doc(down_path))
        for edge in spec.depends_on:
            current = _current(edge.doc)
            stamp = stamps.get(edge.doc)
            if current is None:
                status = SuspectStatus.MISSING_UPSTREAM
                detail = f"upstream {edge.doc!r} document file is missing"
            elif stamp is None:
                status = SuspectStatus.UNSTAMPED
                detail = (
                    f"edge to {edge.doc!r} has no baseline — review it, then "
                    f"`cdx resolve --edge {spec.id} {edge.doc}`"
                )
            elif stamp != current:
                status = SuspectStatus.SUSPECT
                detail = (
                    f"upstream {edge.doc!r} changed since last review — re-confirm, "
                    f"then `cdx resolve --edge {spec.id} {edge.doc}`"
                )
            else:
                status = SuspectStatus.OK
                detail = f"upstream {edge.doc!r} unchanged since last review"
            if status is SuspectStatus.OK and not include_ok:
                continue
            out.append(
                SuspectLink(
                    doc_id=spec.id,
                    doc_path=spec.path,
                    upstream_id=edge.doc,
                    type=edge.type,
                    status=status,
                    detail=detail,
                    audience=spec.audience,
                )
            )
    return tuple(sorted(out, key=lambda s: (s.doc_id, s.upstream_id)))


def infer_edges_from_links(
    config: MonitorConfig, root: Path
) -> tuple[InferredEdge, ...]:
    """Suggest doc↔doc edges from Markdown cross-links between managed docs (pure).

    The low-tedium "suggest": rather than make a human draw the graph by hand, scan
    each managed doc's body for relative Markdown links that resolve to ANOTHER
    managed doc, and propose those as edges (author→approve). External links
    (``http(s)://``, ``mailto:``), in-page anchors, self-links, links to
    non-managed paths, and edges already declared in ``depends_on`` are skipped.
    Sorted by ``(doc_id, upstream_id)``; each pair suggested at most once.
    """
    path_to_id = _path_to_id(config)
    out: list[InferredEdge] = []
    seen: set[tuple[str, str]] = set()
    for spec in config.documents:
        down_path = root / spec.path
        if not down_path.is_file():
            continue
        declared = {edge.doc for edge in spec.depends_on}
        doc_dir = posixpath.dirname(spec.path)
        body = parse_doc(down_path).body
        for target in _MD_LINK.findall(body):
            link = target.split("#", 1)[0].strip()
            if not link or "://" in link or link.startswith("mailto:"):
                continue
            resolved = posixpath.normpath(posixpath.join(doc_dir, link))
            upstream_id = path_to_id.get(resolved)
            if upstream_id is None or upstream_id == spec.id:
                continue
            if upstream_id in declared:
                continue
            key = (spec.id, upstream_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(InferredEdge(doc_id=spec.id, upstream_id=upstream_id, via=link))
    return tuple(sorted(out, key=lambda e: (e.doc_id, e.upstream_id)))


def _reverse_reachable(
    config: MonitorConfig, origins: set[str], *, transitive: bool = True
) -> set[str]:
    """Documents reverse-reachable from ``origins`` along ``depends_on`` (pure, K10).

    The shared traversal behind :func:`impacted_by` (one origin) and
    :func:`propagate_suspect` (the whole suspect frontier). A node is reachable when
    it — directly, or transitively when ``transitive`` — declares a dependency on an
    origin. Cycle-safe (each node visited once) and EXCLUDES the origins themselves.
    The returned set is order-independent, so callers that sort it get a deterministic
    result regardless of frontier pop order.
    """
    # Reverse adjacency: upstream id -> the set of downstreams that depend on it.
    rev: dict[str, set[str]] = {}
    for doc in config.documents:
        for edge in doc.depends_on:
            rev.setdefault(edge.doc, set()).add(doc.id)
    reached: set[str] = set()
    frontier = sorted(node for origin in origins for node in rev.get(origin, set()))
    while frontier:
        node = frontier.pop()
        if node in reached or node in origins:
            continue  # cycle-safe: never revisit, never include an origin
        reached.add(node)
        if transitive:
            frontier.extend(rev.get(node, set()))
    return reached


def impacted_by(
    config: MonitorConfig, upstream_id: str, *, transitive: bool = True
) -> tuple[str, ...]:
    """The blast radius of changing ``upstream_id`` — its dependents (pure, K1/K10).

    The PROACTIVE complement to :func:`detect_suspect_links`: before editing a
    document, ask which downstream documents declare a dependency on it and would
    need re-review. Walks the REVERSE of the ``depends_on`` graph from
    ``upstream_id`` (via :func:`_reverse_reachable`). ``transitive`` (the default)
    follows the whole chain — if ``a`` depends_on ``b`` depends_on ``c``, changing
    ``c`` impacts both ``b`` and ``a`` — and is cycle-safe; ``transitive=False``
    returns only the DIRECT dependents. Returns the impacted document ids sorted
    (K10), excluding ``upstream_id`` itself. Loud (K8) when ``upstream_id`` is not a
    managed document.

    Pure over the declared config graph (no file reads, no clock) and independent of
    ``docdeps.enabled`` — the dependency graph exists whether or not suspect-link
    detection is switched on.
    """
    ids = {doc.id for doc in config.documents}
    if upstream_id not in ids:
        raise DriftError(
            f"unknown document id {upstream_id!r} — not a managed document"
        )
    return tuple(
        sorted(_reverse_reachable(config, {upstream_id}, transitive=transitive))
    )


def propagate_suspect(
    config: MonitorConfig, direct: Sequence[SuspectLink]
) -> tuple[SuspectLink, ...]:
    """The transitive blast radius of the direct suspect links — ADVISORY (pure, K10).

    The HYBRID complement to :func:`detect_suspect_links`: detection stays the pure
    Doorstop *direct wavefront* (only an edge whose own upstream body moved is SUSPECT,
    and only that gates ``cdx check``). Propagation looks one hop further — a document
    whose upstream is *itself* pending review (directly suspect, or transitively so)
    will need re-confirming once that upstream is updated — and returns those edges as
    :data:`SuspectStatus.SUSPECT_TRANSITIVE` links: an EAGER, read-only advisory that
    surfaces the whole closure NOW without minting a drift (a transitive edge has no
    changed upstream body to stamp, so it must never gate — K1/K7).

    Derived purely from ``direct`` + the declared graph. The origins are the documents
    DIRECTLY flagged (``SUSPECT`` / ``MISSING_UPSTREAM``; ``UNSTAMPED`` is excluded — a
    never-reviewed edge is not a *change*). Every document reverse-reachable from those
    origins gets one advisory link per declared edge to a still-pending upstream. EDGES
    already present in ``direct`` with a non-OK status are omitted (they are reported
    there), so the advisory and the direct report never overlap — even when a document
    is directly flagged on one edge AND transitively pending on another. The exclusion
    is per-EDGE, not per-document, so that second edge is never dropped. Returns () when
    nothing is directly flagged. Sorted by ``(doc_id, upstream_id)`` (K10).
    """
    flagged = {
        link.doc_id
        for link in direct
        if link.status in (SuspectStatus.SUSPECT, SuspectStatus.MISSING_UPSTREAM)
    }
    if not flagged:
        return ()
    reachable = _reverse_reachable(config, flagged, transitive=True)
    pending = flagged | reachable  # every doc that is or will become suspect
    # Exclude exactly the EDGES already in the direct report (edge granularity, not
    # whole-document): a doc can be directly flagged on one edge and transitively
    # pending on another — the second edge belongs in neither report under a doc skip.
    already_edges = {
        (link.doc_id, link.upstream_id)
        for link in direct
        if link.status is not SuspectStatus.OK
    }
    specs_by_id = {doc.id: doc for doc in config.documents}
    out: list[SuspectLink] = []
    for doc_id in reachable:
        spec = specs_by_id[doc_id]
        for edge in spec.depends_on:
            if edge.doc not in pending:
                continue  # this upstream is fine; only pending ones explain the doc
            if (spec.id, edge.doc) in already_edges:
                continue  # this exact edge is already in the direct report
            out.append(
                SuspectLink(
                    doc_id=spec.id,
                    doc_path=spec.path,
                    upstream_id=edge.doc,
                    type=edge.type,
                    status=SuspectStatus.SUSPECT_TRANSITIVE,
                    detail=(
                        f"upstream {edge.doc!r} is itself pending review — re-confirm "
                        f"this edge once {edge.doc!r} is updated"
                    ),
                    audience=spec.audience,
                )
            )
    return tuple(sorted(out, key=lambda s: (s.doc_id, s.upstream_id)))


def stamp_edges(
    config: MonitorConfig, root: Path, downstream_id: str, *, only: str | None = None
) -> tuple[str, ...]:
    """Write/refresh the baseline stamp(s) for a downstream doc's edges (IMPURE).

    The one writer for Pillar B — called only by the mutation commands
    (``link`` / ``resolve --edge`` / ``monitor --apply``), never by ``check``. For
    each edge (or just ``only`` when given) it recomputes the upstream's current
    fingerprint and, if it differs from the stored stamp, writes it into the
    downstream's ``cdm.upstream_hashes``. Idempotent (K7): an unchanged baseline is
    not rewritten. Returns the upstream ids actually (re)stamped, sorted. Loud
    (K8) if the downstream document or file is missing.
    """
    spec = next((d for d in config.documents if d.id == downstream_id), None)
    if spec is None:
        raise DriftError(f"unknown document id {downstream_id!r}")
    down_path = root / spec.path
    if not down_path.is_file():
        raise DriftError(
            f"document {downstream_id!r} file {spec.path!r} is missing — "
            "cannot stamp its dependency edges"
        )
    specs_by_id = {doc.id: doc for doc in config.documents}
    doc = parse_doc(down_path)
    meta = doc.meta
    existing = stored_upstream_hashes(doc)
    changed: list[str] = []
    for edge in spec.depends_on:
        if only is not None and edge.doc != only:
            continue
        up_path = root / specs_by_id[edge.doc].path
        if not up_path.is_file():
            continue  # cannot baseline a missing upstream
        current = upstream_fingerprint(parse_doc(up_path))
        if existing.get(edge.doc) != current:
            meta = set_upstream_hash(meta, edge.doc, current)
            changed.append(edge.doc)
    if changed:
        down_path.write_text(render_doc(meta, doc.body), encoding="utf-8")
    return tuple(sorted(changed))


def render_deps_text(
    links: Sequence[SuspectLink],
    *,
    suspect_only: bool = False,
    transitive: Sequence[SuspectLink] = (),
) -> str:
    """A deterministic plain-text dependency report (K10) — the ``cdx deps`` view.

    Groups edges under their downstream document. ``suspect_only`` drops OK edges
    from the listing (the ``--suspect`` view). Pass ``include_ok=True`` links for
    the full graph; the default (attention-only) links render just the problems.
    ``transitive`` (the ``cdx deps --transitive`` advisory from
    :func:`propagate_suspect`) is rendered as a clearly-labelled separate section that
    states it does NOT gate ``cdx check`` — so a reviewer never mistakes the eager
    blast radius for the (direct-only) gate.
    """
    shown = [
        link for link in links if not (suspect_only and link.status is SuspectStatus.OK)
    ]
    by_doc: dict[str, list[SuspectLink]] = {}
    for link in shown:
        by_doc.setdefault(link.doc_id, []).append(link)
    n_suspect = sum(1 for link in shown if link.status is not SuspectStatus.OK)
    lines = [
        f"# Dependencies — {len(by_doc)} document(s), {n_suspect} edge(s) need review",
        "",
    ]
    for doc_id in sorted(by_doc):
        lines.append(f"  {doc_id}:")
        for link in sorted(by_doc[doc_id], key=lambda link_: link_.upstream_id):
            lines.append(
                f"    → {link.upstream_id} [{link.type.value}] "
                f"{link.status.value} — {link.detail}"
            )
    if transitive:
        by_t: dict[str, list[SuspectLink]] = {}
        for link in transitive:
            by_t.setdefault(link.doc_id, []).append(link)
        lines.append("")
        lines.append(
            f"  advisory — {len(transitive)} edge(s) across {len(by_t)} document(s) "
            "transitively suspect (pending wavefront; does NOT gate `cdx check`):"
        )
        for doc_id in sorted(by_t):
            lines.append(f"    {doc_id}:")
            for link in sorted(by_t[doc_id], key=lambda link_: link_.upstream_id):
                lines.append(
                    f"      → {link.upstream_id} [{link.type.value}] — {link.detail}"
                )
    return "\n".join(lines)


def render_impact_text(upstream_id: str, impacted: Sequence[str]) -> str:
    """A deterministic plain-text blast-radius report (K10) — ``cdx deps --impact``.

    Lists the documents that (transitively) depend on ``upstream_id`` and would need
    re-review if it changed; an empty radius reads as an explicit "safe to change".
    """
    if not impacted:
        return f"# nothing depends on {upstream_id!r} — safe to change"
    lines = [
        f"# {len(impacted)} document(s) depend on {upstream_id!r} — "
        "review them after changing it:"
    ]
    lines.extend(f"  → {doc_id}" for doc_id in impacted)
    return "\n".join(lines)
