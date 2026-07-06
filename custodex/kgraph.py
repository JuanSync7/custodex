"""AGT-03 — the unified knowledge-graph artifact (pure build — K1/K2/K10).

ONE deterministic fold of the edges Custodex already computes — six modules'
worth of relationships unified into typed nodes and edges with provenance
tiers (base facts only, the Glean split; every derived quantity is recomputed
from them, never stored):

* ``DOCUMENTS`` (declared) — doc → symbol, from the ``code_refs`` coverage join;
* ``DEPENDS_ON`` (declared) — doc → doc, from the docdeps declarations;
* ``MENTIONS`` (resolved) — doc → symbol/path/env, from the AGT-01 mention layer;
* ``LINKS_TO`` (resolved) — doc → doc/url, from resolved prose links;
* ``PART_OF`` (resolved) — section → doc, from the heading entities;
* ``OWNED_BY`` (declared) — doc → owner, the accountable projection (EPIC OWN).

Node identity is the AGT-01 SCIP-style string id (``doc <path>``,
``symbol <path>#<name>``…); a SECTION node's display name is its SLUG — never
raw heading text — so the snapshot the hub mirrors carries no doc-body prose
(K2: the graph is computed REPO-SIDE, where the bodies live, and pushed as an
opaque versioned snapshot exactly like the coverage snapshot; the hub never
re-derives from bodies it does not hold). ``unresolved`` carries the per-doc
unresolved-mention counts — the graph-rot signal, trustworthy because of the
AGT-01 precision rules. The build rides the resilient registry: one
unparseable source file becomes a warning, never an abort.
"""

from __future__ import annotations

import posixpath
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .config import MonitorConfig
from .docmap import symbol_owners
from .entities import EntityKind, build_registry, corpus_entities
from .errors import DriftError
from .ownership import resolve_ownership

__all__ = [
    "NodeKind",
    "EdgeKind",
    "EdgeTier",
    "GraphNode",
    "GraphEdge",
    "KnowledgeGraph",
    "build_graph",
    "graph_neighbors",
    "rank_centrality",
    "render_graph_text",
]

# Frozen + extra="forbid": the graph is an immutable, normalized snapshot (K10).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class NodeKind(str, Enum):
    """The CLOSED node taxonomy (mirrors the entity kinds + OWNER)."""

    DOC = "doc"
    SECTION = "section"
    SYMBOL = "symbol"
    PATH = "path"
    ENV_VAR = "env_var"
    URL = "url"
    OWNER = "owner"


class EdgeKind(str, Enum):
    """The CLOSED edge vocabulary (directional; reverse = a query, not a row)."""

    DOCUMENTS = "documents"  # doc → symbol (code_refs coverage join)
    DEPENDS_ON = "depends_on"  # doc → doc (declared docdeps)
    MENTIONS = "mentions"  # doc → symbol/path/env (mention layer)
    LINKS_TO = "links_to"  # doc → doc/url (resolved prose links)
    PART_OF = "part_of"  # section → doc (heading hierarchy)
    OWNED_BY = "owned_by"  # doc → owner (accountable projection)


class EdgeTier(str, Enum):
    """Provenance: declared-in-config beats resolved-from-prose (never a float)."""

    DECLARED = "declared"
    RESOLVED = "resolved"


class GraphNode(BaseModel):
    """One graph node — SCIP-style string id, closed kind, display name."""

    model_config = _MODEL_CONFIG

    id: str
    kind: NodeKind
    name: str  # a SECTION's name is its slug (K2-safe for the hub snapshot)


class GraphEdge(BaseModel):
    """One directional, provenance-tiered edge between two node ids."""

    model_config = _MODEL_CONFIG

    source: str
    target: str
    kind: EdgeKind
    tier: EdgeTier


class KnowledgeGraph(BaseModel):
    """The unified graph artifact (versioned, additive — K6)."""

    model_config = _MODEL_CONFIG

    schema_version: str = "1.0.0"
    nodes: tuple[GraphNode, ...]  # sorted by id (K10)
    edges: tuple[GraphEdge, ...]  # sorted (source, kind, target) (K10)
    unresolved: dict[str, int]  # doc_id → unresolved-mention count (rot signal)
    warnings: tuple[str, ...]  # registry warnings (unparseable sources)


def build_graph(
    config: MonitorConfig,
    root: Path,
    *,
    unit_owner: dict[str, str] | None = None,
) -> KnowledgeGraph:
    """Fold the existing detectors into ONE typed graph (pure, K1/K10).

    Base facts only: DOCUMENTS/DEPENDS_ON/OWNED_BY are DECLARED (from config
    joins); MENTIONS/LINKS_TO/PART_OF are RESOLVED (from the mention layer).
    Deterministic and byte-identical across runs; derived quantities
    (:func:`graph_neighbors`, :func:`rank_centrality`) recompute from these
    facts and are never stored.
    """
    nodes: dict[str, GraphNode] = {}
    edges: set[tuple[str, str, EdgeKind, EdgeTier]] = set()
    unresolved: dict[str, int] = {}
    node_kind_by_entity = {
        EntityKind.SYMBOL: NodeKind.SYMBOL,
        EntityKind.PATH: NodeKind.PATH,
        EntityKind.ENV_VAR: NodeKind.ENV_VAR,
    }

    doc_node_by_id: dict[str, str] = {}
    for spec in config.documents:
        node_id = f"doc {posixpath.normpath(spec.path)}"
        doc_node_by_id[spec.id] = node_id
        nodes[node_id] = GraphNode(id=node_id, kind=NodeKind.DOC, name=spec.id)

    # DECLARED: doc → doc dependency edges.
    for spec in config.documents:
        for edge in spec.depends_on:
            edges.add(
                (
                    doc_node_by_id[spec.id],
                    doc_node_by_id[edge.doc],
                    EdgeKind.DEPENDS_ON,
                    EdgeTier.DECLARED,
                )
            )

    # DECLARED: doc → symbol coverage edges (the code_refs join, resilient).
    for entity_id, doc_ids in symbol_owners(config, root).items():
        name = entity_id.split("#", 1)[1] if "#" in entity_id else entity_id
        nodes.setdefault(
            entity_id, GraphNode(id=entity_id, kind=NodeKind.SYMBOL, name=name)
        )
        for doc_id in doc_ids:
            edges.add(
                (
                    doc_node_by_id[doc_id],
                    entity_id,
                    EdgeKind.DOCUMENTS,
                    EdgeTier.DECLARED,
                )
            )

    # DECLARED: doc → owner accountability edges (EPIC OWN projection).
    for owner in resolve_ownership(config, unit_owner=unit_owner):
        if owner.accountable is None:
            continue
        owner_node = f"owner {owner.accountable}"
        nodes.setdefault(
            owner_node,
            GraphNode(id=owner_node, kind=NodeKind.OWNER, name=owner.accountable),
        )
        edges.add(
            (
                doc_node_by_id[owner.doc_id],
                owner_node,
                EdgeKind.OWNED_BY,
                EdgeTier.DECLARED,
            )
        )

    # RESOLVED: mentions / links / sections from the AGT-01 layer (one shared
    # registry scan; its warnings ride the artifact — resilience is visible).
    registry = build_registry(config, root)
    results = corpus_entities(config, root, registry=registry)
    doc_id_by_path = {posixpath.normpath(d.path): d.id for d in config.documents}
    warnings = registry.warnings
    for result in results:
        doc_node = doc_node_by_id[result.doc_id]
        n_unresolved = 0
        for section in result.sections:
            nodes.setdefault(
                section.id,
                GraphNode(id=section.id, kind=NodeKind.SECTION, name=section.name),
            )
            edges.add((section.id, doc_node, EdgeKind.PART_OF, EdgeTier.RESOLVED))
        for mention in result.mentions:
            if not mention.resolved or mention.entity_id is None:
                n_unresolved += 1
                continue
            if mention.kind is EntityKind.DOC:
                target_doc = doc_id_by_path.get(mention.entity_id.split(" ", 1)[1])
                if target_doc is None or target_doc == result.doc_id:
                    continue
                edges.add(
                    (
                        doc_node,
                        doc_node_by_id[target_doc],
                        EdgeKind.LINKS_TO,
                        EdgeTier.RESOLVED,
                    )
                )
            elif mention.kind is EntityKind.URL:
                nodes.setdefault(
                    mention.entity_id,
                    GraphNode(
                        id=mention.entity_id,
                        kind=NodeKind.URL,
                        name=mention.entity_id.split(" ", 1)[1],
                    ),
                )
                edges.add(
                    (doc_node, mention.entity_id, EdgeKind.LINKS_TO, EdgeTier.RESOLVED)
                )
            else:
                kind = node_kind_by_entity.get(mention.kind)
                if kind is None:  # pragma: no cover - closed enum, future-proof
                    continue
                nodes.setdefault(
                    mention.entity_id,
                    GraphNode(
                        id=mention.entity_id,
                        kind=kind,
                        name=mention.entity_id.split(" ", 1)[1],
                    ),
                )
                edges.add(
                    (doc_node, mention.entity_id, EdgeKind.MENTIONS, EdgeTier.RESOLVED)
                )
        if n_unresolved:
            unresolved[result.doc_id] = n_unresolved

    return KnowledgeGraph(
        nodes=tuple(sorted(nodes.values(), key=lambda n: n.id)),
        edges=tuple(
            GraphEdge(source=s, target=t, kind=k, tier=tier)
            for s, t, k, tier in sorted(edges, key=lambda e: (e[0], e[2].value, e[1]))
        ),
        unresolved=dict(sorted(unresolved.items())),
        warnings=warnings,
    )


def graph_neighbors(
    g: KnowledgeGraph, node_id: str, *, depth: int = 1
) -> tuple[GraphEdge, ...]:
    """Every edge within ``depth`` hops of ``node_id`` (in AND out) — derived.

    Loud :class:`DriftError` on an unknown node id (K8). Deterministic: the
    result preserves the graph's global edge order (K10).
    """
    known = {n.id for n in g.nodes}
    if node_id not in known:
        raise DriftError(f"unknown graph node {node_id!r}")
    frontier = {node_id}
    seen_nodes = set(frontier)
    picked: set[int] = set()
    for _ in range(max(depth, 0)):
        next_frontier: set[str] = set()
        for i, edge in enumerate(g.edges):
            if i in picked:
                continue
            if edge.source in frontier or edge.target in frontier:
                picked.add(i)
                next_frontier.update((edge.source, edge.target))
        next_frontier -= seen_nodes
        seen_nodes |= next_frontier
        frontier = next_frontier
        if not frontier:
            break
    return tuple(g.edges[i] for i in sorted(picked))


def rank_centrality(
    g: KnowledgeGraph,
    *,
    kind: NodeKind = NodeKind.SYMBOL,
    undocumented_only: bool = False,
) -> tuple[tuple[str, int], ...]:
    """MENTIONS in-degree per ``kind`` node — the what-to-document feed.

    The count is the number of DISTINCT mentioning documents (edges are a
    set, so repeated mentions inside one doc are one edge — a doc cannot vote
    a symbol up twice). ``undocumented_only`` keeps only nodes with NO
    incoming DOCUMENTS edge: widely-mentioned but never-covered code is the
    best-ranked coverage gap (the one DeepWiki idea worth stealing). Sorted
    (-count, id) — K10.
    """
    kinds = {n.id: n.kind for n in g.nodes}
    documented = {e.target for e in g.edges if e.kind is EdgeKind.DOCUMENTS}
    counts: dict[str, int] = {}
    for e in g.edges:
        if e.kind is not EdgeKind.MENTIONS:
            continue
        if kinds.get(e.target) is not kind:
            continue
        if undocumented_only and e.target in documented:
            continue
        counts[e.target] = counts.get(e.target, 0) + 1
    return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def render_graph_text(g: KnowledgeGraph, *, focus: str | None = None) -> str:
    """A deterministic plain-text graph report (K10) — the ``cdx graph`` view."""
    if focus is not None:
        picked = graph_neighbors(g, focus)
        lines = [f"# Graph around {focus!r} — {len(picked)} edge(s)"]
        for e in picked:
            lines.append(f"  {e.source} —{e.kind.value} [{e.tier.value}]→ {e.target}")
        return "\n".join(lines)
    by_kind: dict[str, int] = {}
    for n in g.nodes:
        by_kind[n.kind.value] = by_kind.get(n.kind.value, 0) + 1
    by_edge: dict[str, int] = {}
    for e in g.edges:
        by_edge[e.kind.value] = by_edge.get(e.kind.value, 0) + 1
    rot = sum(g.unresolved.values())
    lines = [
        f"# Knowledge graph — {len(g.nodes)} node(s), {len(g.edges)} edge(s), "
        f"{rot} unresolved mention(s)",
        "  nodes: " + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())),
        "  edges: " + ", ".join(f"{k}={v}" for k, v in sorted(by_edge.items())),
    ]
    if g.unresolved:
        lines.append("  rot signal (unresolved mentions per doc):")
        for doc_id, count in g.unresolved.items():
            lines.append(f"    {doc_id}: {count}")
    return "\n".join(lines)
