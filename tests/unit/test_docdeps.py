"""EPIC B (B-03): the docdeps pure core — doc↔doc suspect-link detection.

Pins the detection contract (mirrors ownership.py's pure half, K0/K1/K10): the
upstream fingerprint is a normalized hash of the upstream's BODY (so it ignores
the upstream's own churny front-matter), and a downstream edge is classified
OK / SUSPECT / UNSTAMPED / MISSING_UPSTREAM against the baseline stamp stored in
the downstream's ``cdm.upstream_hashes``. Link inference (the low-tedium suggest)
and the stamping writer are covered too.

Features: FEAT-DOCDEPS-002, FEAT-DOCDEPS-003
"""

from __future__ import annotations

from pathlib import Path

from custodex.config import (
    Audience,
    DocDepsConfig,
    DocEdge,
    DocEdgeType,
    DocumentSpec,
    MonitorConfig,
)
from custodex.docdeps import (
    SuspectLink,
    SuspectStatus,
    _reverse_reachable,
    detect_suspect_links,
    impacted_by,
    infer_edges_from_links,
    propagate_suspect,
    render_deps_text,
    render_impact_text,
    stamp_edges,
    upstream_fingerprint,
)
from custodex.errors import DriftError
from custodex.manifest import parse_doc, parse_text, stored_upstream_hashes


def _doc(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _cfg(docs: tuple[DocumentSpec, ...], *, enabled: bool = True) -> MonitorConfig:
    return MonitorConfig(
        root=".", documents=docs, docdeps=DocDepsConfig(enabled=enabled)
    )


# --------------------------------------------------------------------------- #
# upstream_fingerprint — body-only, normalized, deterministic
# --------------------------------------------------------------------------- #
def test_upstream_fingerprint_deterministic_and_short() -> None:
    doc = parse_text("# Title\n\nsome content\n")
    h1 = upstream_fingerprint(doc)
    h2 = upstream_fingerprint(parse_text("# Title\n\nsome content\n"))
    assert h1 == h2
    assert len(h1) == 16


def test_upstream_fingerprint_ignores_front_matter() -> None:
    """Two docs with the SAME body but different front matter hash equal — the
    upstream's own ``cdm.fingerprint`` re-stamp must not trip a suspect link."""
    a = parse_text("---\ncdm:\n  fingerprint: aaaa\n---\n# Body\ntext\n")
    b = parse_text("---\ncdm:\n  fingerprint: bbbb\n---\n# Body\ntext\n")
    assert upstream_fingerprint(a) == upstream_fingerprint(b)


def test_upstream_fingerprint_moves_on_body_change() -> None:
    a = parse_text("# Body\noriginal\n")
    b = parse_text("# Body\nCHANGED\n")
    assert upstream_fingerprint(a) != upstream_fingerprint(b)


# --------------------------------------------------------------------------- #
# detect_suspect_links — the four statuses
# --------------------------------------------------------------------------- #
def _two_doc_cfg() -> tuple[DocumentSpec, ...]:
    return (
        DocumentSpec(id="overview", path="overview.md", audience=Audience.ENG_GUIDE),
        DocumentSpec(
            id="api",
            path="api.md",
            audience=Audience.ENG_GUIDE,
            depends_on=(DocEdge(doc="overview"),),
        ),
    )


def test_unstamped_edge_is_flagged(tmp_path: Path) -> None:
    """A declared edge with no baseline stamp is UNSTAMPED (needs first review)."""
    _doc(tmp_path, "overview.md", "# Overview\nupstream content\n")
    _doc(tmp_path, "api.md", "# API\ndownstream content\n")
    links = detect_suspect_links(_cfg(_two_doc_cfg()), tmp_path)
    assert [(s.doc_id, s.upstream_id, s.status) for s in links] == [
        ("api", "overview", SuspectStatus.UNSTAMPED)
    ]


def test_stamped_then_ok(tmp_path: Path) -> None:
    """After stamping the baseline, the edge is OK (omitted by default)."""
    _doc(tmp_path, "overview.md", "# Overview\nupstream content\n")
    _doc(tmp_path, "api.md", "# API\ndownstream content\n")
    cfg = _cfg(_two_doc_cfg())
    stamp_edges(cfg, tmp_path, "api")
    assert detect_suspect_links(cfg, tmp_path) == ()  # nothing needs attention
    # include_ok surfaces the OK link for the graph view.
    ok = detect_suspect_links(cfg, tmp_path, include_ok=True)
    assert [(s.upstream_id, s.status) for s in ok] == [("overview", SuspectStatus.OK)]


def test_upstream_change_makes_suspect(tmp_path: Path) -> None:
    """Editing the upstream body after stamping flips the edge to SUSPECT."""
    _doc(tmp_path, "overview.md", "# Overview\nupstream content\n")
    _doc(tmp_path, "api.md", "# API\ndownstream content\n")
    cfg = _cfg(_two_doc_cfg())
    stamp_edges(cfg, tmp_path, "api")
    _doc(tmp_path, "overview.md", "# Overview\nUPSTREAM EDITED\n")  # upstream moved
    links = detect_suspect_links(cfg, tmp_path)
    assert len(links) == 1
    assert links[0].status is SuspectStatus.SUSPECT
    assert links[0].upstream_id == "overview"
    assert links[0].audience is Audience.ENG_GUIDE


def test_missing_upstream_file(tmp_path: Path) -> None:
    _doc(tmp_path, "api.md", "# API\ndownstream content\n")  # overview.md absent
    links = detect_suspect_links(_cfg(_two_doc_cfg()), tmp_path)
    assert links[0].status is SuspectStatus.MISSING_UPSTREAM


def test_disabled_returns_empty(tmp_path: Path) -> None:
    _doc(tmp_path, "overview.md", "# o\n")
    _doc(tmp_path, "api.md", "# a\n")
    links = detect_suspect_links(_cfg(_two_doc_cfg(), enabled=False), tmp_path)
    assert links == ()


def test_results_sorted(tmp_path: Path) -> None:
    """Output is sorted by (doc_id, upstream_id) for a deterministic report (K10)."""
    docs = (
        DocumentSpec(id="a", path="a.md", audience=Audience.ENG_GUIDE),
        DocumentSpec(id="b", path="b.md", audience=Audience.ENG_GUIDE),
        DocumentSpec(
            id="zed",
            path="zed.md",
            audience=Audience.ENG_GUIDE,
            depends_on=(DocEdge(doc="b"), DocEdge(doc="a")),
        ),
    )
    for rel in ("a.md", "b.md", "zed.md"):
        _doc(tmp_path, rel, f"# {rel}\n")
    links = detect_suspect_links(_cfg(docs), tmp_path)
    assert [s.upstream_id for s in links] == ["a", "b"]  # sorted within doc 'zed'


# --------------------------------------------------------------------------- #
# stamp_edges — the impure baseline writer (idempotent, per-edge)
# --------------------------------------------------------------------------- #
def test_stamp_edges_writes_baseline_and_is_idempotent(tmp_path: Path) -> None:
    _doc(tmp_path, "overview.md", "# Overview\nupstream\n")
    _doc(tmp_path, "api.md", "# API\ndown\n")
    cfg = _cfg(_two_doc_cfg())
    changed = stamp_edges(cfg, tmp_path, "api")
    assert changed == ("overview",)
    doc = parse_doc(tmp_path / "api.md")
    assert "overview" in stored_upstream_hashes(doc)
    # Re-stamping with no upstream change writes nothing (K7).
    assert stamp_edges(cfg, tmp_path, "api") == ()


def test_stamp_edges_only_one_edge(tmp_path: Path) -> None:
    docs = (
        DocumentSpec(id="o", path="o.md", audience=Audience.ENG_GUIDE),
        DocumentSpec(id="g", path="g.md", audience=Audience.ENG_GUIDE),
        DocumentSpec(
            id="api",
            path="api.md",
            audience=Audience.ENG_GUIDE,
            depends_on=(DocEdge(doc="o"), DocEdge(doc="g")),
        ),
    )
    for rel in ("o.md", "g.md", "api.md"):
        _doc(tmp_path, rel, f"# {rel}\n")
    cfg = _cfg(docs)
    assert stamp_edges(cfg, tmp_path, "api", only="o") == ("o",)
    # only 'o' is stamped; 'g' remains UNSTAMPED.
    suspects = {s.upstream_id: s.status for s in detect_suspect_links(cfg, tmp_path)}
    assert suspects == {"g": SuspectStatus.UNSTAMPED}


# --------------------------------------------------------------------------- #
# infer_edges_from_links — the low-tedium "suggest"
# --------------------------------------------------------------------------- #
def test_infer_edges_from_markdown_links(tmp_path: Path) -> None:
    """A relative md link from one managed doc to another suggests an edge."""
    docs = (
        DocumentSpec(id="overview", path="overview.md", audience=Audience.ENG_GUIDE),
        DocumentSpec(id="api", path="api.md", audience=Audience.ENG_GUIDE),
    )
    _doc(tmp_path, "overview.md", "# Overview\n")
    _doc(tmp_path, "api.md", "# API\n\nSee the [overview](overview.md) for context.\n")
    inferred = infer_edges_from_links(_cfg(docs), tmp_path)
    assert [(e.doc_id, e.upstream_id) for e in inferred] == [("api", "overview")]


def test_infer_skips_already_declared(tmp_path: Path) -> None:
    docs = (
        DocumentSpec(id="overview", path="overview.md", audience=Audience.ENG_GUIDE),
        DocumentSpec(
            id="api",
            path="api.md",
            audience=Audience.ENG_GUIDE,
            depends_on=(DocEdge(doc="overview"),),
        ),
    )
    _doc(tmp_path, "overview.md", "# Overview\n")
    _doc(tmp_path, "api.md", "# API\n[overview](overview.md)\n")
    assert infer_edges_from_links(_cfg(docs), tmp_path) == ()  # already declared


def test_infer_ignores_non_managed_and_external_links(tmp_path: Path) -> None:
    docs = (DocumentSpec(id="api", path="api.md", audience=Audience.ENG_GUIDE),)
    _doc(
        tmp_path,
        "api.md",
        "# API\n[x](https://example.com) [y](untracked.md) [self](api.md)\n",
    )
    assert infer_edges_from_links(_cfg(docs), tmp_path) == ()


# --------------------------------------------------------------------------- #
# render_deps_text — deterministic human view
# --------------------------------------------------------------------------- #
def test_render_deps_text_lists_edges(tmp_path: Path) -> None:
    links = (
        SuspectLink(
            doc_id="api",
            doc_path="api.md",
            upstream_id="overview",
            type=DocEdgeType.DEPENDS,
            status=SuspectStatus.SUSPECT,
            detail="upstream changed",
            audience=Audience.ENG_GUIDE,
        ),
    )
    text = render_deps_text(links)
    assert "api" in text and "overview" in text and "suspect" in text


# --------------------------------------------------------------------------- #
# impacted_by — the proactive blast radius (reverse-reachable dependents)
#
# Feature: FEAT-DOCDEPS-009
# --------------------------------------------------------------------------- #
def _chain_cfg() -> MonitorConfig:
    """a → b → c (a depends_on b, b depends_on c) plus an unrelated `solo`."""
    return _cfg(
        (
            DocumentSpec(id="c", path="c.md", audience=Audience.ENG_GUIDE),
            DocumentSpec(
                id="b",
                path="b.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="c"),),
            ),
            DocumentSpec(
                id="a",
                path="a.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="b"),),
            ),
            DocumentSpec(id="solo", path="solo.md", audience=Audience.ENG_GUIDE),
        )
    )


def test_impacted_by_is_transitive_by_default() -> None:
    # changing c impacts b (direct) and a (transitive through b).
    assert impacted_by(_chain_cfg(), "c") == ("a", "b")


def test_impacted_by_direct_only() -> None:
    assert impacted_by(_chain_cfg(), "c", transitive=False) == ("b",)


def test_impacted_by_leaf_has_empty_radius() -> None:
    # nobody depends on `a` (it is the top of the chain) → safe to change.
    assert impacted_by(_chain_cfg(), "a") == ()
    assert impacted_by(_chain_cfg(), "solo") == ()


def test_impacted_by_unknown_doc_is_loud() -> None:
    import pytest

    with pytest.raises(DriftError, match="unknown document id 'ghost'"):
        impacted_by(_chain_cfg(), "ghost")


def test_impacted_by_is_cycle_safe() -> None:
    # a depends_on b AND b depends_on a (a degenerate cycle) must terminate.
    cyclic = _cfg(
        (
            DocumentSpec(
                id="a",
                path="a.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="b"),),
            ),
            DocumentSpec(
                id="b",
                path="b.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="a"),),
            ),
        )
    )
    assert impacted_by(cyclic, "a") == ("b",)
    assert impacted_by(cyclic, "b") == ("a",)


def test_impacted_by_cycle_with_external_dependent() -> None:
    # a↔b cycle PLUS c→b: changing b must reach a (via the cycle) and c, once each.
    cfg = _cfg(
        (
            DocumentSpec(
                id="a",
                path="a.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="b"),),
            ),
            DocumentSpec(
                id="b",
                path="b.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="a"),),
            ),
            DocumentSpec(
                id="c",
                path="c.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="b"),),
            ),
        )
    )
    assert impacted_by(cfg, "b") == ("a", "c")
    assert impacted_by(cfg, "a") == ("b", "c")


def test_impacted_by_ignores_docdeps_enabled() -> None:
    # the dependency GRAPH exists even when suspect detection is switched off.
    cfg = _cfg(
        (
            DocumentSpec(id="c", path="c.md", audience=Audience.ENG_GUIDE),
            DocumentSpec(
                id="b",
                path="b.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="c"),),
            ),
        ),
        enabled=False,
    )
    assert impacted_by(cfg, "c") == ("b",)


def test_render_impact_text_empty_and_nonempty() -> None:
    assert "safe to change" in render_impact_text("c", ())
    text = render_impact_text("c", ("a", "b"))
    assert "2 document(s)" in text and "→ a" in text and "→ b" in text


# --------------------------------------------------------------------------- #
# _reverse_reachable — characterization: impacted_by delegates to it unchanged
#
# Feature: FEAT-DOCDEPS-010
# --------------------------------------------------------------------------- #
def test_reverse_reachable_matches_impacted_by() -> None:
    """The extracted helper reproduces ``impacted_by`` byte-for-byte (K6/K10).

    Guards the PROP-01 refactor: ``impacted_by`` now delegates to
    ``_reverse_reachable``, so its output must be IDENTICAL on every origin —
    including the cycle and branching graphs the original was characterized on.
    """
    for cfg in (_chain_cfg(),):
        for origin in ("a", "b", "c", "solo"):
            assert impacted_by(cfg, origin) == tuple(
                sorted(_reverse_reachable(cfg, {origin}))
            )
    # direct-only mode delegates too
    assert impacted_by(_chain_cfg(), "c", transitive=False) == tuple(
        sorted(_reverse_reachable(_chain_cfg(), {"c"}, transitive=False))
    )


def test_reverse_reachable_multi_origin_union() -> None:
    """A multi-origin frontier returns the union of each origin's reach, minus
    the origins themselves (the propagate_suspect entry point)."""
    cfg = _chain_cfg()  # a → b → c, plus solo
    # origins {b, c}: reachable from b = {a}; from c = {a, b}; minus origins {b,c} = {a}
    assert _reverse_reachable(cfg, {"b", "c"}) == {"a"}


# --------------------------------------------------------------------------- #
# propagate_suspect — the transitive ADVISORY (HYBRID, read-only, never gates)
#
# Feature: FEAT-DOCDEPS-010
# --------------------------------------------------------------------------- #
def _suspect(
    doc_id: str,
    upstream_id: str,
    status: SuspectStatus = SuspectStatus.SUSPECT,
    audience: Audience = Audience.ENG_GUIDE,
) -> SuspectLink:
    return SuspectLink(
        doc_id=doc_id,
        doc_path=f"{doc_id}.md",
        upstream_id=upstream_id,
        type=DocEdgeType.DEPENDS,
        status=status,
        detail="x",
        audience=audience,
    )


def test_propagate_suspect_flags_transitive_dependents() -> None:
    """In a → b → c, a change to c directly flags b; a is the transitive advisory."""
    cfg = _chain_cfg()
    direct = (_suspect("b", "c"),)  # c changed → b directly suspect
    adv = propagate_suspect(cfg, direct)
    assert [(s.doc_id, s.upstream_id, s.status) for s in adv] == [
        ("a", "b", SuspectStatus.SUSPECT_TRANSITIVE)
    ]


def test_propagate_suspect_multi_hop_sorted() -> None:
    """A deeper chain d ← c ← b ← a: a change to d advises both b and a, sorted."""
    cfg = _cfg(
        (
            DocumentSpec(id="d", path="d.md", audience=Audience.ENG_GUIDE),
            DocumentSpec(
                id="c",
                path="c.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="d"),),
            ),
            DocumentSpec(
                id="b",
                path="b.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="c"),),
            ),
            DocumentSpec(
                id="a",
                path="a.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="b"),),
            ),
        )
    )
    links = propagate_suspect(cfg, (_suspect("c", "d"),))
    assert [(s.doc_id, s.upstream_id) for s in links] == [("a", "b"), ("b", "c")]


def test_propagate_suspect_empty_without_direct_flag() -> None:
    cfg = _chain_cfg()
    assert propagate_suspect(cfg, ()) == ()
    # UNSTAMPED is not a *change* — it never seeds a transitive advisory.
    assert propagate_suspect(cfg, (_suspect("b", "c", SuspectStatus.UNSTAMPED),)) == ()


def test_propagate_suspect_includes_missing_upstream_origin() -> None:
    cfg = _chain_cfg()
    adv = [
        (s.doc_id, s.upstream_id)
        for s in propagate_suspect(
            cfg, (_suspect("b", "c", SuspectStatus.MISSING_UPSTREAM),)
        )
    ]
    assert adv == [("a", "b")]


def test_propagate_suspect_omits_docs_already_directly_flagged() -> None:
    """A doc directly suspect via one edge is not ALSO listed as transitive."""
    cfg = _cfg(
        (
            DocumentSpec(id="c", path="c.md", audience=Audience.ENG_GUIDE),
            DocumentSpec(
                id="b",
                path="b.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="c"),),
            ),
            DocumentSpec(
                id="a",
                path="a.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="b"), DocEdge(doc="c")),
            ),
        )
    )
    # c changed → both a (via a→c) and b (via b→c) are DIRECTLY suspect.
    direct = (_suspect("a", "c"), _suspect("b", "c"))
    assert propagate_suspect(cfg, direct) == ()  # a already reported; no dupe


def test_propagate_suspect_uses_downstream_audience() -> None:
    cfg = _cfg(
        (
            DocumentSpec(id="c", path="c.md", audience=Audience.ENG_GUIDE),
            DocumentSpec(
                id="b",
                path="b.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="c"),),
            ),
            DocumentSpec(
                id="a",
                path="a.md",
                audience=Audience.USER_GUIDE,
                depends_on=(DocEdge(doc="b"),),
            ),
        )
    )
    adv = propagate_suspect(cfg, (_suspect("b", "c"),))
    assert adv[0].doc_id == "a" and adv[0].audience is Audience.USER_GUIDE


def test_propagate_suspect_cycle_safe() -> None:
    """A a↔b cycle terminates and emits the one transitive edge."""
    cfg = _cfg(
        (
            DocumentSpec(
                id="a",
                path="a.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="b"),),
            ),
            DocumentSpec(
                id="b",
                path="b.md",
                audience=Audience.ENG_GUIDE,
                depends_on=(DocEdge(doc="a"),),
            ),
        )
    )
    # b changed → a directly suspect; b is transitively pending (via the cycle).
    links = propagate_suspect(cfg, (_suspect("a", "b"),))
    assert [(s.doc_id, s.upstream_id) for s in links] == [("b", "a")]


def test_render_deps_text_renders_transitive_advisory() -> None:
    direct = (_suspect("b", "c"),)
    trans = (_suspect("a", "b", SuspectStatus.SUSPECT_TRANSITIVE),)
    text = render_deps_text(direct, transitive=trans)
    assert "advisory" in text and "does NOT gate" in text
    assert "→ b" in text  # the transitive edge a → b is shown
