"""AGT-03 — the unified knowledge-graph artifact (`kgraph.py`).

One deterministic fold of the existing detectors into typed, provenance-
tiered nodes/edges (base facts; derived queries recompute): DOCUMENTS /
DEPENDS_ON / OWNED_BY declared, MENTIONS / LINKS_TO / PART_OF resolved,
per-doc unresolved counts as the rot signal, SECTION names as slugs only
(K2-safe for the hub snapshot), and the resilient registry underneath.

Features: FEAT-KGRAPH-001, FEAT-KGRAPH-002
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custodex.config import (
    Audience,
    CodeRef,
    CoverageConfig,
    DocEdge,
    DocumentSpec,
    MonitorConfig,
)
from custodex.errors import DriftError
from custodex.kgraph import (
    EdgeKind,
    EdgeTier,
    NodeKind,
    build_graph,
    graph_neighbors,
    rank_centrality,
    render_graph_text,
)

ALPHA_PY = 'def solve_widget(x):\n    """Doc."""\n    return x\n'
BETA_PY = "def helper_fn(y):\n    return y\n"


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _fixture(tmp_path: Path) -> tuple[MonitorConfig, Path]:
    _write(tmp_path, "alpha.py", ALPHA_PY)
    _write(tmp_path, "beta.py", BETA_PY)
    _write(
        tmp_path,
        "docs/guide.md",
        "# Guide\n\n## Usage\n\nCall `helper_fn` and `gone_fn` — see "
        "[api](api.md) and [site](https://x.example/d).\n",
    )
    _write(tmp_path, "docs/api.md", "# API\n\nReference.\n")
    cfg = MonitorConfig(
        documents=(
            DocumentSpec(
                id="guide",
                path="docs/guide.md",
                audience=Audience.ENG_GUIDE,
                owner="mei",
            ),
            DocumentSpec(
                id="api",
                path="docs/api.md",
                audience=Audience.ENG_GUIDE,
                code_refs=(CodeRef(path="alpha.py"), CodeRef(path="beta.py")),
                owner="ravi",
                depends_on=(DocEdge(doc="guide"),),
            ),
        ),
        coverage=CoverageConfig(include=("**/*.py",), exclude=()),
    )
    return cfg, tmp_path


def _edge_set(g, kind):
    return {(e.source, e.target) for e in g.edges if e.kind is kind}


class TestBuildGraph:
    def test_every_edge_kind_with_right_tier(self, tmp_path: Path) -> None:
        cfg, root = _fixture(tmp_path)
        g = build_graph(cfg, root)
        assert ("doc docs/api.md", "doc docs/guide.md") in _edge_set(
            g, EdgeKind.DEPENDS_ON
        )
        assert ("doc docs/api.md", "symbol alpha.py#solve_widget") in _edge_set(
            g, EdgeKind.DOCUMENTS
        )
        assert ("doc docs/guide.md", "symbol beta.py#helper_fn") in _edge_set(
            g, EdgeKind.MENTIONS
        )
        assert ("doc docs/guide.md", "doc docs/api.md") in _edge_set(
            g, EdgeKind.LINKS_TO
        )
        assert ("doc docs/guide.md", "url https://x.example/d") in _edge_set(
            g, EdgeKind.LINKS_TO
        )
        assert ("section docs/guide.md#usage", "doc docs/guide.md") in _edge_set(
            g, EdgeKind.PART_OF
        )
        assert ("doc docs/guide.md", "owner mei") in _edge_set(g, EdgeKind.OWNED_BY)
        tiers = {e.kind: e.tier for e in g.edges}
        assert tiers[EdgeKind.DEPENDS_ON] is EdgeTier.DECLARED
        assert tiers[EdgeKind.MENTIONS] is EdgeTier.RESOLVED

    def test_unresolved_counts_are_the_rot_signal(self, tmp_path: Path) -> None:
        cfg, root = _fixture(tmp_path)
        g = build_graph(cfg, root)
        assert g.unresolved == {"guide": 1}  # `gone_fn`

    def test_section_names_are_slugs_never_raw_text(self, tmp_path: Path) -> None:
        cfg, root = _fixture(tmp_path)
        g = build_graph(cfg, root)
        sections = [n for n in g.nodes if n.kind is NodeKind.SECTION]
        assert sections and all(n.name == n.name.lower() for n in sections)
        assert all(" " not in n.name for n in sections)

    def test_rebuild_is_byte_identical(self, tmp_path: Path) -> None:
        cfg, root = _fixture(tmp_path)
        a = build_graph(cfg, root)
        b = build_graph(cfg, root)
        assert a.model_dump_json() == b.model_dump_json()

    def test_unparseable_source_warns_but_builds(self, tmp_path: Path) -> None:
        cfg, root = _fixture(tmp_path)
        _write(root, "broken.py", "def broken(:\n")
        g = build_graph(cfg, root)
        assert any("broken.py" in w for w in g.warnings)
        assert g.nodes  # the graph still built


class TestDerivedQueries:
    def test_neighbors_in_and_out(self, tmp_path: Path) -> None:
        cfg, root = _fixture(tmp_path)
        g = build_graph(cfg, root)
        edges = graph_neighbors(g, "doc docs/api.md")
        kinds = {e.kind for e in edges}
        # api is DEPENDS_ON source, DOCUMENTS source, LINKS_TO target, OWNED_BY source
        assert EdgeKind.DEPENDS_ON in kinds
        assert EdgeKind.DOCUMENTS in kinds
        assert EdgeKind.LINKS_TO in kinds

    def test_neighbors_depth_two_reaches_further(self, tmp_path: Path) -> None:
        cfg, root = _fixture(tmp_path)
        g = build_graph(cfg, root)
        one = graph_neighbors(g, "owner mei", depth=1)
        two = graph_neighbors(g, "owner mei", depth=2)
        assert len(two) > len(one)

    def test_neighbors_unknown_node_is_loud(self, tmp_path: Path) -> None:
        cfg, root = _fixture(tmp_path)
        g = build_graph(cfg, root)
        with pytest.raises(DriftError, match="ghost"):
            graph_neighbors(g, "ghost")

    def test_rank_centrality_undocumented_gap_tops(self, tmp_path: Path) -> None:
        cfg, root = _fixture(tmp_path)
        # gamma.py's function is mentioned twice but covered by NO doc.
        _write(root, "gamma.py", "def hot_gap(z):\n    return z\n")
        _write(
            root,
            "docs/guide.md",
            "# Guide\n\nCall `hot_gap` then `hot_gap` again; also `helper_fn`.\n",
        )
        g = build_graph(cfg, root)
        ranked = rank_centrality(g, undocumented_only=True)
        assert ranked and ranked[0][0] == "symbol gamma.py#hot_gap"
        # helper_fn IS documented (api covers beta.py) → excluded here...
        assert all(node != "symbol beta.py#helper_fn" for node, _ in ranked)
        # ...but present in the unfiltered ranking.
        assert any(node == "symbol beta.py#helper_fn" for node, _ in rank_centrality(g))


class TestRender:
    def test_summary_and_focus_views(self, tmp_path: Path) -> None:
        cfg, root = _fixture(tmp_path)
        g = build_graph(cfg, root)
        summary = render_graph_text(g)
        assert "node(s)" in summary and "rot signal" in summary
        focus = render_graph_text(g, focus="doc docs/api.md")
        assert "doc docs/api.md" in focus and "—documents" in focus
