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
from custodex.server.store import ConfigDocEdge, ConfigDocument, Store  # noqa: E402
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


def _doc(doc_id: str, *, depends_on: tuple[ConfigDocEdge, ...] = ()) -> ConfigDocument:
    return ConfigDocument(
        repo_id=_REPO,
        doc_id=doc_id,
        path=f"docs/{doc_id}.md",
        audience="eng-guide",
        depends_on=depends_on,
        sync_kind="git",
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
