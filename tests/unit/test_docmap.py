"""AGT-02 — entity-based edge suggestions + accept/reject verbs (`docmap.py`).

The provenance-tiered upgrade of Pillar B's mapping aid: RESOLVED_LINK (prose
links via the AGT-01 mention layer — machine regions can no longer mint
suggestions) and SHARED_SYMBOL (downstream mentions a symbol EXACTLY ONE
upstream covers), with the review-hardened exclusions (declared / self /
rejected / index-downstream), the comment-preserving textual splice behind
`cdx link`, and the durable rejection verdict file.

Features: FEAT-DOCMAP-001, FEAT-DOCMAP-002, FEAT-DOCMAP-003
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custodex.config import (
    Audience,
    CodeRef,
    CoverageConfig,
    DocEdge,
    DocEdgeType,
    DocumentSpec,
    MonitorConfig,
    load_bundle,
)
from custodex.docmap import (
    EdgeRejection,
    ScoredEdge,
    SuggestionTier,
    churn_note,
    declare_edge,
    read_rejections,
    reject_edge,
    render_suggestions_text,
    suggest_edges,
)
from custodex.errors import ConfigError, SchemaError

ALPHA_PY = 'def solve_widget(x):\n    """Doc."""\n    return x\n'


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _spec(doc_id: str, path: str, **kw) -> DocumentSpec:
    return DocumentSpec(id=doc_id, path=path, audience=Audience.ENG_GUIDE, **kw)


def _config(*specs: DocumentSpec) -> MonitorConfig:
    return MonitorConfig(
        documents=tuple(specs),
        coverage=CoverageConfig(include=("**/*.py",), exclude=()),
    )


def _fixture(tmp_path: Path) -> Path:
    _write(tmp_path, "alpha.py", ALPHA_PY)
    # B covers solve_widget via code_refs; A mentions it in prose; C links B.
    _write(tmp_path, "docs/a.md", "# A\n\nUses `solve_widget` heavily.\n")
    _write(tmp_path, "docs/b.md", "# B\n\nThe API reference.\n")
    _write(tmp_path, "docs/c.md", "# C\n\nSee [the api](b.md) for details.\n")
    return tmp_path


def _three_doc_config() -> MonitorConfig:
    return _config(
        _spec("a", "docs/a.md"),
        _spec("b", "docs/b.md", code_refs=(CodeRef(path="alpha.py"),)),
        _spec("c", "docs/c.md"),
    )


class TestSuggestEdges:
    def test_link_and_symbol_rules_fire(self, tmp_path: Path) -> None:
        root = _fixture(tmp_path)
        edges = suggest_edges(_three_doc_config(), root)
        assert [(e.doc_id, e.upstream_id, e.tier) for e in edges] == [
            ("a", "b", SuggestionTier.SHARED_SYMBOL),
            ("c", "b", SuggestionTier.RESOLVED_LINK),
        ]
        shared, linked = edges
        assert shared.via is None
        assert shared.evidence == ("symbol alpha.py#solve_widget",)
        assert shared.score == 1
        assert linked.via == "b.md"

    def test_declared_edge_is_excluded(self, tmp_path: Path) -> None:
        root = _fixture(tmp_path)
        cfg = _config(
            _spec("a", "docs/a.md", depends_on=(DocEdge(doc="b"),)),
            _spec("b", "docs/b.md", code_refs=(CodeRef(path="alpha.py"),)),
            _spec("c", "docs/c.md", depends_on=(DocEdge(doc="b"),)),
        )
        assert suggest_edges(cfg, root) == ()

    def test_rejected_pair_is_excluded(self, tmp_path: Path) -> None:
        root = _fixture(tmp_path)
        rejections = (
            EdgeRejection(doc_id="a", upstream_id="b", rejected_at="2026-07-02"),
        )
        edges = suggest_edges(_three_doc_config(), root, rejections=rejections)
        assert [(e.doc_id, e.upstream_id) for e in edges] == [("c", "b")]

    def test_index_downstream_is_excluded(self, tmp_path: Path) -> None:
        # The index page's links are MANDATED by the INDEX_INCOMPLETE lint —
        # the review measured 13/13 pure noise on the dogfood corpus.
        root = _fixture(tmp_path)
        cfg = _config(
            _spec("a", "docs/a.md"),
            _spec("b", "docs/b.md", code_refs=(CodeRef(path="alpha.py"),)),
            _spec("c", "docs/c.md", index=True),
        )
        edges = suggest_edges(cfg, root)
        assert [(e.doc_id, e.upstream_id) for e in edges] == [("a", "b")]

    def test_self_coverage_yields_no_self_edge(self, tmp_path: Path) -> None:
        root = _fixture(tmp_path)
        _write(root, "docs/b.md", "# B\n\nThe `solve_widget` reference.\n")
        cfg = _config(
            _spec("b", "docs/b.md", code_refs=(CodeRef(path="alpha.py"),)),
        )
        assert suggest_edges(cfg, root) == ()

    def test_multi_covered_symbol_is_excluded(self, tmp_path: Path) -> None:
        # solve_widget covered by BOTH b and d → ambiguous ownership: no edge.
        root = _fixture(tmp_path)
        _write(root, "docs/d.md", "# D\n\nAlso a reference.\n")
        cfg = _config(
            _spec("a", "docs/a.md"),
            _spec("b", "docs/b.md", code_refs=(CodeRef(path="alpha.py"),)),
            _spec("d", "docs/d.md", code_refs=(CodeRef(path="alpha.py"),)),
        )
        assert suggest_edges(cfg, root) == ()

    def test_machine_region_link_mints_no_suggestion(self, tmp_path: Path) -> None:
        # The legacy infer_edges_from_links scanned the RAW body; docmap goes
        # through the mention layer, so a generated cross-link cannot suggest.
        root = _fixture(tmp_path)
        _write(
            root,
            "docs/c.md",
            "# C\n\n<!-- CDM:BEGIN nav -->\n[api](b.md)\n<!-- CDM:END nav -->\n",
        )
        edges = suggest_edges(_three_doc_config(), root)
        assert [(e.doc_id, e.upstream_id) for e in edges] == [("a", "b")]

    def test_pair_found_by_both_rules_merges_at_link_tier(self, tmp_path: Path) -> None:
        root = _fixture(tmp_path)
        _write(
            root,
            "docs/a.md",
            "# A\n\nUses `solve_widget` — see [the api](b.md).\n",
        )
        edges = suggest_edges(_three_doc_config(), root)
        a_b = next(e for e in edges if e.doc_id == "a")
        assert a_b.tier is SuggestionTier.RESOLVED_LINK
        assert a_b.via == "b.md"
        assert set(a_b.evidence) == {"b.md", "symbol alpha.py#solve_widget"}
        assert a_b.score == 2

    def test_deterministic_double_run(self, tmp_path: Path) -> None:
        root = _fixture(tmp_path)
        cfg = _three_doc_config()
        assert suggest_edges(cfg, root) == suggest_edges(cfg, root)


class TestChurnNoteAndRender:
    def test_churn_note_for_code_tracked_upstream(self, tmp_path: Path) -> None:
        note = churn_note(_three_doc_config(), "b")
        assert "code-tracked" in note and "SUSPECT" in note and "prose" in note

    def test_churn_note_under_prose_baseline(self) -> None:
        cfg = _three_doc_config().model_copy(deep=True)
        prose_cfg = MonitorConfig(
            **{
                **cfg.model_dump(),
                "docdeps": {**cfg.docdeps.model_dump(), "baseline": "prose"},
            }
        )
        note = churn_note(prose_cfg, "b")
        assert "will NOT trip" in note

    def test_churn_note_empty_for_prose_only_upstream(self) -> None:
        assert churn_note(_three_doc_config(), "c") == ""

    def test_render_includes_yaml_tier_and_note(self, tmp_path: Path) -> None:
        root = _fixture(tmp_path)
        cfg = _three_doc_config()
        edges = suggest_edges(cfg, root)
        notes = {e.upstream_id: churn_note(cfg, e.upstream_id) for e in edges}
        text = render_suggestions_text(edges, notes=notes)
        assert "- doc: b" in text
        assert "shared_symbol" in text and "resolved_link" in text
        assert "code-tracked" in text
        assert render_suggestions_text(()) == "# no new doc↔doc edges suggested"


_UNIT_TEXT = """\
---
cdmon-config-version: "2.0.0"
unit: core
title: "core docs"
owner: eng
created: "2026-07-01"
updated: "2026-07-01"
---
# A load-bearing comment the splice MUST preserve.
dir-covered:
  - src
source-files-format:
  - .py
documents:
  # Comment above a: preserved.
  - id: a
    path: docs/a.md
    audience: eng-guide
  - id: b
    path: docs/b.md
    audience: eng-guide
    # Comment inside b's entry: preserved.
    depends_on:
      - doc: a
  - id: c
    path: docs/c.md
    audience: eng-guide
"""

_INDEX_TEXT = """\
---
cdmon-config-version: "2.0.0"
repo: t
generated-by: cdx
updated: "2026-07-01"
---
root: "../.."
version: "2.0.0"
backend: {kind: mock}
units:
  - file: core.yaml
"""


def _bundle_dir(tmp_path: Path) -> Path:
    cfg_dir = tmp_path / "config" / "cdmon"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "index.yaml").write_text(_INDEX_TEXT, encoding="utf-8")
    (cfg_dir / "core.yaml").write_text(_UNIT_TEXT, encoding="utf-8")
    for rel in ("docs/a.md", "docs/b.md", "docs/c.md"):
        _write(tmp_path, rel, f"# {rel}\n\nProse.\n")
    return cfg_dir


class TestDeclareEdge:
    def test_splice_adds_edge_and_preserves_every_comment(self, tmp_path: Path) -> None:
        cfg_dir = _bundle_dir(tmp_path)
        declare_edge(cfg_dir, "a", "c", now="2026-07-02T10:00:00Z")
        text = (cfg_dir / "core.yaml").read_text(encoding="utf-8")
        assert "# A load-bearing comment the splice MUST preserve." in text
        assert "# Comment above a: preserved." in text
        assert "# Comment inside b's entry: preserved." in text
        assert 'updated: "2026-07-02"' in text
        bundle = load_bundle(cfg_dir)
        a = next(d for d in bundle.config.documents if d.id == "a")
        assert a.depends_on == (DocEdge(doc="c"),)

    def test_splice_extends_existing_depends_on(self, tmp_path: Path) -> None:
        cfg_dir = _bundle_dir(tmp_path)
        declare_edge(
            cfg_dir, "b", "c", type=DocEdgeType.REFINES, now="2026-07-02T10:00:00Z"
        )
        bundle = load_bundle(cfg_dir)
        b = next(d for d in bundle.config.documents if d.id == "b")
        assert b.depends_on == (
            DocEdge(doc="a"),
            DocEdge(doc="c", type=DocEdgeType.REFINES),
        )

    def test_unknown_ids_self_edge_and_duplicate_are_loud(self, tmp_path: Path) -> None:
        cfg_dir = _bundle_dir(tmp_path)
        with pytest.raises(ConfigError, match="ghost"):
            declare_edge(cfg_dir, "a", "ghost", now="2026-07-02")
        with pytest.raises(ConfigError, match="itself"):
            declare_edge(cfg_dir, "a", "a", now="2026-07-02")
        with pytest.raises(ConfigError, match="already declared"):
            declare_edge(cfg_dir, "b", "a", now="2026-07-02")


class TestRejections:
    def test_reject_round_trips_and_appends(self, tmp_path: Path) -> None:
        cdmon = tmp_path / ".cdmon"
        reject_edge(cdmon, "a", "b", now="2026-07-02T10:00:00Z", by="me", note="n")
        reject_edge(cdmon, "c", "b", now="2026-07-02T11:00:00Z")
        rejections = read_rejections(cdmon)
        assert [(r.doc_id, r.upstream_id) for r in rejections] == [
            ("a", "b"),
            ("c", "b"),
        ]
        assert rejections[0].rejected_by == "me"

    def test_missing_file_means_no_rejections(self, tmp_path: Path) -> None:
        assert read_rejections(tmp_path / ".cdmon") == ()

    def test_corrupt_line_is_loud(self, tmp_path: Path) -> None:
        cdmon = tmp_path / ".cdmon"
        cdmon.mkdir()
        (cdmon / "edge-rejections.jsonl").write_text("not json\n", encoding="utf-8")
        with pytest.raises(SchemaError, match="line 1"):
            read_rejections(cdmon)


class TestJsonShapeGuard:
    def test_scorededge_keys_are_superset_of_legacy(self) -> None:
        """K6: the legacy --suggest items carried {doc_id, upstream_id, via}."""
        edge = ScoredEdge(
            doc_id="a",
            upstream_id="b",
            via=None,
            tier=SuggestionTier.SHARED_SYMBOL,
            evidence=("symbol x.py#f",),
            score=1,
        )
        assert {"doc_id", "upstream_id", "via"} <= set(edge.model_dump(mode="json"))


class TestResilienceAndSpliceEdges:
    def test_missing_broken_and_private_refs_are_skipped(self, tmp_path: Path) -> None:
        # A missing code_ref, an unparseable one, and a private-only module all
        # contribute nothing — the advisory pass never dies on a bad ref.
        root = _fixture(tmp_path)
        _write(root, "broken.py", "def broken(:\n")
        _write(root, "private.py", "def _hidden():\n    return 1\n")
        cfg = _config(
            _spec("a", "docs/a.md"),
            _spec(
                "b",
                "docs/b.md",
                code_refs=(
                    CodeRef(path="alpha.py"),
                    CodeRef(path="gone.py"),
                    CodeRef(path="broken.py"),
                    CodeRef(path="private.py"),
                ),
            ),
            _spec("c", "docs/c.md"),
        )
        edges = suggest_edges(cfg, root)
        assert [(e.doc_id, e.upstream_id) for e in edges] == [
            ("a", "b"),
            ("c", "b"),
        ]

    def test_self_link_and_unresolved_mentions_suggest_nothing(
        self, tmp_path: Path
    ) -> None:
        root = _fixture(tmp_path)
        _write(
            root,
            "docs/c.md",
            "# C\n\nSee [me](c.md) and `totally_unknown_fn` today.\n",
        )
        cfg = _three_doc_config()
        edges = suggest_edges(cfg, root)
        assert [(e.doc_id, e.upstream_id) for e in edges] == [("a", "b")]

    def test_splice_on_last_document_with_typed_edge(self, tmp_path: Path) -> None:
        # `c` is the LAST entry in the unit (block runs to EOF) and the edge
        # carries a non-default type → the `type:` line is emitted.
        cfg_dir = _bundle_dir(tmp_path)
        declare_edge(
            cfg_dir, "c", "a", type=DocEdgeType.VERIFIES, now="2026-07-02T10:00:00Z"
        )
        bundle = load_bundle(cfg_dir)
        c = next(d for d in bundle.config.documents if d.id == "c")
        assert c.depends_on == (DocEdge(doc="a", type=DocEdgeType.VERIFIES),)
