"""WL-01 — the central per-repo GET /worklist view (both stores, read-time).

The hub serves the accountability JOIN it CAN compute from the mirror — ownership
orphans (vs the live roster) + staleness breaches (vs the app clock) — bucketed by
accountable owner, reusing the same read-time cascade as /ownership + /staleness.
Suspect-link items are repo-local (the hub lacks the doc bodies to hash an upstream,
K2), so the hub worklist OMITS them and flags ``includes_suspect: false``. Parity over
InMemoryStore + SqlStore; offline (K4), deterministic (K10).

Features: FEAT-WORKLIST-001
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")
pytest.importorskip("sqlalchemy", reason="the [server] extra is not installed")

from fastapi.testclient import TestClient  # noqa: E402

from custodex.ownership import Identity  # noqa: E402
from custodex.registry import RegistrationPayload  # noqa: E402
from custodex.server import InMemoryStore, create_app  # noqa: E402
from custodex.server.db import SqlStore, create_all, engine_from_url  # noqa: E402
from custodex.server.store import ConfigDocument, Store  # noqa: E402
from custodex.sinks import RepoIdentity  # noqa: E402

_REPO = "acme/widget"
_NOW = "2026-06-19T00:00:00Z"


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
    owner: str | None = None,
    team: str | None = None,
    dri: str | None = None,
    accountable: str | None = None,
    durable: str | None = None,
    reviewed: str | None = None,
) -> ConfigDocument:
    return ConfigDocument(
        repo_id=_REPO,
        doc_id=doc_id,
        path=f"docs/{doc_id}.md",
        audience="eng-guide",
        owner=owner,
        team=team,
        dri=dri,
        accountable=accountable,
        durable=durable,
        reviewed=reviewed,
        sync_kind="git",
        synced_at=_NOW,
    )


def _seed(store: Store) -> None:
    _register(store)
    store.replace_config(
        _REPO,
        "git",
        [
            # alice's doc is STALE (reviewed long ago); alice stays active.
            _doc(
                "stale-doc",
                owner="alice",
                accountable="alice",
                durable="alice",
                reviewed="2020-01-01",
            ),
            # bob's doc is fresh, but bob DEPARTS → it becomes an ownership orphan.
            _doc(
                "orphan-doc",
                owner="bob",
                team="bob",
                dri="bob",
                accountable="bob",
                durable="bob",
                reviewed="2026-06-18",
            ),
        ],
        [],
    )
    store.upsert_identity(Identity(name="alice", active=True))
    store.upsert_identity(Identity(name="bob", active=True))
    store.mark_identity_departed("bob", at=_NOW)


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_worklist_joins_orphan_and_stale_omits_suspect(kind: str) -> None:
    store = _make_store(kind)
    _seed(store)
    body = (
        TestClient(create_app(store, clock=lambda: _NOW))
        .get(f"/repos/{_REPO}/worklist")
        .json()
    )

    # K2: the hub cannot compute suspect status → omitted, and it says so honestly.
    assert body["includes_suspect"] is False
    assert all(
        item["reason"] != "suspect"
        for owner in body["owners"]
        for item in owner["items"]
    )
    by_owner = {o["accountable"]: o for o in body["owners"]}
    # alice (active) carries her STALE doc; bob (departed) carries the ORPHAN doc.
    assert "stale" in {i["reason"] for i in by_owner["alice"]["items"]}
    assert "orphan" in {i["reason"] for i in by_owner["bob"]["items"]}
    assert body["item_count"] == 2 and body["doc_count"] == 2


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_worklist_owner_filter(kind: str) -> None:
    store = _make_store(kind)
    _seed(store)
    body = (
        TestClient(create_app(store, clock=lambda: _NOW))
        .get(f"/repos/{_REPO}/worklist", params={"owner": "alice"})
        .json()
    )
    assert [o["accountable"] for o in body["owners"]] == ["alice"]
    assert body["item_count"] == 1


def test_worklist_unknown_repo_is_404() -> None:
    client = TestClient(create_app(InMemoryStore()))
    assert client.get("/repos/nope/worklist").status_code == 404
