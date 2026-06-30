"""EPIC B (B-07) — the per-repo GET /doc-graph view (read-time, both stores).

The central hub mirrors each document's declared doc↔doc edges (the `depends_on`
graph) as an additive field on the synced ConfigDocument — it rides in the full
JSON blob, so NO migration and it round-trips through BOTH the in-memory and the
SQL store. Suspect STATUS stays repo-local (the doc files live in the repo, K2);
the hub serves the cross-repo dependency GRAPH. Offline (K4), deterministic (K10).

Features: FEAT-DOCDEPS-007
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")
pytest.importorskip("sqlalchemy", reason="the [server] extra is not installed")

from fastapi.testclient import TestClient  # noqa: E402

from custodex.registry import RegistrationPayload  # noqa: E402
from custodex.server import InMemoryStore, create_app  # noqa: E402
from custodex.server.db import SqlStore, create_all, engine_from_url  # noqa: E402
from custodex.server.store import (  # noqa: E402
    ConfigDocEdge,
    ConfigDocument,
    Store,
    StoredDocEdge,
)
from custodex.sinks import RepoIdentity  # noqa: E402

_REPO = "acme/widget"
_NOW = "2026-06-30T00:00:00Z"


def _make_store(kind: str) -> Store:
    if kind == "memory":
        return InMemoryStore()
    engine = engine_from_url("sqlite:///:memory:")
    create_all(engine)
    return SqlStore(engine)


def _register(store: Store) -> None:
    store.add_repo(
        RegistrationPayload(
            repo=RepoIdentity(
                repo_id=_REPO,
                repo_name="widget",
                repo_url="https://example.invalid/acme/widget",
                commit="deadbeef",
            ),
            default_branch="main",
            auth_token=None,
        )
    )


def _doc(
    doc_id: str,
    *,
    depends_on: tuple[ConfigDocEdge, ...] = (),
    sync_kind: str = "git",
) -> ConfigDocument:
    return ConfigDocument(
        repo_id=_REPO,
        doc_id=doc_id,
        path=f"docs/{doc_id}.md",
        audience="eng-guide",
        depends_on=depends_on,
        sync_kind=sync_kind,
        synced_at=_NOW,
    )


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_doc_graph_route_returns_edges(kind: str) -> None:
    store = _make_store(kind)
    _register(store)
    store.replace_config(
        _REPO,
        "git",
        [
            _doc("overview"),
            _doc("api", depends_on=(ConfigDocEdge(doc="overview", type="refines"),)),
        ],
        [],
    )
    client = TestClient(create_app(store, clock=lambda: _NOW))

    body = client.get(f"/repos/{_REPO}/doc-graph").json()
    assert body["edge_count"] == 1
    edge = body["edges"][0]
    assert edge["doc_id"] == "api"
    assert edge["upstream_id"] == "overview"
    assert edge["type"] == "refines"
    assert edge["doc_path"] == "docs/api.md"


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_doc_graph_empty_when_no_edges(kind: str) -> None:
    store = _make_store(kind)
    _register(store)
    store.replace_config(_REPO, "git", [_doc("solo")], [])
    client = TestClient(create_app(store, clock=lambda: _NOW))
    body = client.get(f"/repos/{_REPO}/doc-graph").json()
    assert body == {"edges": [], "edge_count": 0}


def test_doc_graph_unknown_repo_404() -> None:
    store = InMemoryStore()
    client = TestClient(create_app(store, clock=lambda: _NOW))
    assert client.get("/repos/nope/doc-graph").status_code == 404


def test_config_doc_edge_rides_in_json_round_trip() -> None:
    """The edge survives a model_dump → model_validate round-trip (no migration, K6)."""
    doc = _doc("api", depends_on=(ConfigDocEdge(doc="overview"),))
    again = ConfigDocument.model_validate(doc.model_dump())
    assert again.depends_on == (ConfigDocEdge(doc="overview", type="depends"),)


# --------------------------------------------------------------------------- #
# B-09: the config_doc_edges child table — the INDEXED reverse-lookup projection
# of depends_on (both stores; the SqlStore queries the index, the InMemoryStore
# derives from its config documents — same Protocol output, K6/K10).
#
# Feature: FEAT-DOCDEPS-008
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_doc_edges_for_projects_all_edges_in_order(kind: str) -> None:
    store = _make_store(kind)
    _register(store)
    store.replace_config(
        _REPO,
        "git",
        [
            _doc("overview"),
            _doc("api", depends_on=(ConfigDocEdge(doc="overview", type="refines"),)),
            _doc(
                "guide",
                depends_on=(
                    ConfigDocEdge(doc="overview"),
                    ConfigDocEdge(doc="api", type="implements"),
                ),
            ),
        ],
        [],
    )
    edges = store.doc_edges_for(_REPO)
    # document order then in-document edge order (deterministic, K10).
    assert [(e.doc_id, e.upstream_id, e.type) for e in edges] == [
        ("api", "overview", "refines"),
        ("guide", "overview", "depends"),
        ("guide", "api", "implements"),
    ]
    assert all(e.repo_id == _REPO and e.sync_kind == "git" for e in edges)
    # the full StoredDocEdge is returned, not a dict.
    assert edges[0] == StoredDocEdge(
        repo_id=_REPO,
        doc_id="api",
        upstream_id="overview",
        type="refines",
        sync_kind="git",
    )


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_doc_edges_for_reverse_filter_by_upstream(kind: str) -> None:
    """The O(1) reverse lookup: WHO depends on document X (the B-09 raison d'être)."""
    store = _make_store(kind)
    _register(store)
    store.replace_config(
        _REPO,
        "git",
        [
            _doc("overview"),
            _doc("api", depends_on=(ConfigDocEdge(doc="overview"),)),
            _doc("guide", depends_on=(ConfigDocEdge(doc="overview"),)),
        ],
        [],
    )
    rev = store.doc_edges_for(_REPO, upstream_id="overview")
    assert [e.doc_id for e in rev] == ["api", "guide"]
    # a leaf nobody depends on has no dependents.
    assert store.doc_edges_for(_REPO, upstream_id="guide") == []


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_doc_edges_for_scoped_by_sync_kind(kind: str) -> None:
    """Edges are partitioned by (repo_id, sync_kind) exactly like config documents."""
    store = _make_store(kind)
    _register(store)
    store.replace_config(
        _REPO,
        "git",
        [_doc("overview"), _doc("api", depends_on=(ConfigDocEdge(doc="overview"),))],
        [],
    )
    store.replace_config(
        _REPO,
        "local",
        [
            _doc("overview", sync_kind="local"),
            _doc(
                "api",
                depends_on=(ConfigDocEdge(doc="overview", type="refines"),),
                sync_kind="local",
            ),
        ],
        [],
    )
    git_edges = store.doc_edges_for(_REPO, sync_kind="git")
    local_edges = store.doc_edges_for(_REPO, sync_kind="local")
    assert [e.type for e in git_edges] == ["depends"]
    assert [e.type for e in local_edges] == ["refines"]
    # both kinds present when unfiltered.
    assert len(store.doc_edges_for(_REPO)) == 2
    # replacing ONE scope leaves the other intact (atomic per-scope replace).
    store.replace_config(_REPO, "git", [_doc("overview"), _doc("api")], [])
    assert store.doc_edges_for(_REPO, sync_kind="git") == []
    assert len(store.doc_edges_for(_REPO, sync_kind="local")) == 1


def test_doc_edges_for_unknown_repo_is_empty() -> None:
    assert InMemoryStore().doc_edges_for("nope/never") == []


# --------------------------------------------------------------------------- #
# B-10: GET /doc-graph/reverse — the indexed "who depends on X" route over the
# config_doc_edges table (the engine's `cdx deps --impact` does the transitive
# blast radius; this route serves the direct dependents from the hub).
#
# Feature: FEAT-DOCDEPS-008
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_doc_graph_reverse_route_lists_dependents(kind: str) -> None:
    store = _make_store(kind)
    _register(store)
    store.replace_config(
        _REPO,
        "git",
        [
            _doc("overview"),
            _doc("api", depends_on=(ConfigDocEdge(doc="overview", type="refines"),)),
            _doc("guide", depends_on=(ConfigDocEdge(doc="overview"),)),
        ],
        [],
    )
    client = TestClient(create_app(store, clock=lambda: _NOW))
    body = client.get(
        f"/repos/{_REPO}/doc-graph/reverse", params={"doc": "overview"}
    ).json()
    assert body["upstream_id"] == "overview"
    assert body["count"] == 2
    assert [d["doc_id"] for d in body["dependents"]] == ["api", "guide"]
    assert body["dependents"][0]["type"] == "refines"
    # a leaf nobody depends on → empty radius.
    leaf = client.get(
        f"/repos/{_REPO}/doc-graph/reverse", params={"doc": "guide"}
    ).json()
    assert leaf == {
        "upstream_id": "guide",
        "dependents": [],
        "count": 0,
        "transitive": False,
    }


# --------------------------------------------------------------------------- #
# PROP-01: GET /doc-graph/reverse?transitive=true — the blast-radius closure
# served as pure GRAPH reachability over the indexed edge table (never a suspect
# verdict — the doc bodies live in the repo, K2). Cycle-safe, deterministic.
#
# Feature: FEAT-DOCDEPS-010
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_doc_graph_reverse_transitive_closure(kind: str) -> None:
    store = _make_store(kind)
    _register(store)
    # overview ← api ← guide (guide depends_on api depends_on overview).
    store.replace_config(
        _REPO,
        "git",
        [
            _doc("overview"),
            _doc("api", depends_on=(ConfigDocEdge(doc="overview"),)),
            _doc("guide", depends_on=(ConfigDocEdge(doc="api"),)),
        ],
        [],
    )
    client = TestClient(create_app(store, clock=lambda: _NOW))

    def rev(**params: str) -> dict:
        return client.get(f"/repos/{_REPO}/doc-graph/reverse", params=params).json()

    # default: only the DIRECT dependent of overview.
    direct = rev(doc="overview")
    assert [d["doc_id"] for d in direct["dependents"]] == ["api"]
    assert direct["transitive"] is False
    # transitive: the WHOLE blast radius — api AND guide — sorted, with no edge type.
    trans = rev(doc="overview", transitive="true")
    assert [d["doc_id"] for d in trans["dependents"]] == ["api", "guide"]
    assert trans["count"] == 2 and trans["transitive"] is True
    assert "type" not in trans["dependents"][0]  # a closure has no single edge type
    # one-hop agreement: `api`'s single direct dependent equals its full closure, so
    # the indexed query and the BFS return the SAME set.
    assert [d["doc_id"] for d in rev(doc="api")["dependents"]] == ["guide"]
    assert [d["doc_id"] for d in rev(doc="api", transitive="true")["dependents"]] == [
        "guide"
    ]


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_doc_graph_reverse_transitive_is_cycle_safe(kind: str) -> None:
    store = _make_store(kind)
    _register(store)
    # a ↔ b degenerate cycle: the BFS must terminate and exclude the origin.
    store.replace_config(
        _REPO,
        "git",
        [
            _doc("a", depends_on=(ConfigDocEdge(doc="b"),)),
            _doc("b", depends_on=(ConfigDocEdge(doc="a"),)),
        ],
        [],
    )
    client = TestClient(create_app(store, clock=lambda: _NOW))
    trans = client.get(
        f"/repos/{_REPO}/doc-graph/reverse",
        params={"doc": "a", "transitive": "true"},
    ).json()
    assert [d["doc_id"] for d in trans["dependents"]] == ["b"]
    assert trans["count"] == 1 and trans["transitive"] is True


def test_doc_graph_reverse_requires_doc_param() -> None:
    store = InMemoryStore()
    _register(store)
    client = TestClient(create_app(store, clock=lambda: _NOW))
    # `doc` is a required query param — omitting it is a 422 (loud, K8).
    assert client.get(f"/repos/{_REPO}/doc-graph/reverse").status_code == 422


def test_doc_graph_reverse_unknown_repo_404() -> None:
    store = InMemoryStore()
    client = TestClient(create_app(store, clock=lambda: _NOW))
    assert (
        client.get("/repos/nope/doc-graph/reverse", params={"doc": "x"}).status_code
        == 404
    )


# --------------------------------------------------------------------------- #
# Both routes show ONE canonical view (default "git"), honour ?sync_kind, and
# AGREE with each other — even when a doc's depends_on DIVERGES across the git
# and local partitions (the cross-route consistency the review flagged).
#
# Feature: FEAT-DOCDEPS-008
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_graph_routes_canonical_view_and_sync_kind_scope(kind: str) -> None:
    store = _make_store(kind)
    _register(store)
    # `api` depends on `overview` under BOTH partitions but with DIFFERENT types.
    store.replace_config(
        _REPO,
        "git",
        [
            _doc("overview"),
            _doc("api", depends_on=(ConfigDocEdge(doc="overview", type="refines"),)),
        ],
        [],
    )
    store.replace_config(
        _REPO,
        "local",
        [
            _doc("overview", sync_kind="local"),
            _doc(
                "api",
                depends_on=(ConfigDocEdge(doc="overview", type="depends"),),
                sync_kind="local",
            ),
        ],
        [],
    )
    client = TestClient(create_app(store, clock=lambda: _NOW))

    def fwd(**params: str) -> dict:
        return client.get(f"/repos/{_REPO}/doc-graph", params=params).json()

    def rev(**params: str) -> dict:
        return client.get(f"/repos/{_REPO}/doc-graph/reverse", params=params).json()

    # Default (no sync_kind) → the canonical "git" view on BOTH routes.
    fwd_default = fwd()
    rev_default = rev(doc="overview")
    assert [e["type"] for e in fwd_default["edges"]] == ["refines"]
    assert rev_default["count"] == 1
    assert rev_default["dependents"][0]["type"] == "refines"
    # The two routes AGREE on the edge: api→overview exists in BOTH views, same type.
    assert fwd_default["edges"][0]["doc_id"] == "api"
    assert fwd_default["edges"][0]["upstream_id"] == "overview"
    assert rev_default["dependents"][0]["doc_id"] == "api"

    # ?sync_kind=local scopes BOTH routes to the local partition (type=depends).
    assert [e["type"] for e in fwd(sync_kind="local")["edges"]] == ["depends"]
    rev_local = rev(doc="overview", sync_kind="local")
    assert rev_local["dependents"] == [{"doc_id": "api", "type": "depends"}]
    # ?sync_kind=git is identical to the default.
    assert rev(doc="overview", sync_kind="git") == rev_default


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_graph_routes_fall_back_to_local_when_no_git(kind: str) -> None:
    """A LOCAL-only repo (a standalone `cdx serve`, the seeded demo) must not render
    a blank graph under the default: the partition resolver falls back to "local"."""
    store = _make_store(kind)
    _register(store)
    # ONLY the local partition is synced — no "git" rows exist.
    store.replace_config(
        _REPO,
        "local",
        [
            _doc("overview", sync_kind="local"),
            _doc(
                "api",
                depends_on=(ConfigDocEdge(doc="overview", type="depends"),),
                sync_kind="local",
            ),
        ],
        [],
    )
    client = TestClient(create_app(store, clock=lambda: _NOW))
    # The default (no sync_kind) is NOT blank — it resolves to the local partition.
    fwd = client.get(f"/repos/{_REPO}/doc-graph").json()
    assert fwd["edge_count"] == 1
    assert fwd["edges"][0]["doc_id"] == "api"
    rev = client.get(
        f"/repos/{_REPO}/doc-graph/reverse", params={"doc": "overview"}
    ).json()
    assert rev["count"] == 1
    assert rev["dependents"][0]["doc_id"] == "api"
