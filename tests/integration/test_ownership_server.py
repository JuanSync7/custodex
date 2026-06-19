"""EPIC OWN (OWN-04) — the central roster MIRROR + per-repo /ownership view.

Both-stores parity (InMemoryStore + SqlStore over in-memory SQLite) over the actual
FastAPI app: roster CRUD, admin-token auth (a GLOBAL token, never a per-repo token),
and the cross-repo orphan CASCADE — marking a person departed once flips every
document they are accountable for, on the NEXT read of ``GET /ownership``. The owner
fields ride in the existing config_documents JSON column (additive, K6). Fully
offline (K4), deterministic (K10).

Features: FEAT-OWNERSHIP-005, FEAT-OWNERSHIP-006, FEAT-OWNERSHIP-007
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")
pytest.importorskip(
    "sqlalchemy", reason="the [server] extra (sqlalchemy) is not installed"
)

from fastapi.testclient import TestClient  # noqa: E402

from code_doc_monitor.ownership import Identity  # noqa: E402
from code_doc_monitor.registry import RegistrationPayload  # noqa: E402
from code_doc_monitor.server import InMemoryStore, create_app  # noqa: E402
from code_doc_monitor.server.db import (  # noqa: E402
    SqlStore,
    create_all,
    engine_from_url,
)
from code_doc_monitor.server.store import ConfigDocument, Store  # noqa: E402
from code_doc_monitor.sinks import RepoIdentity  # noqa: E402

_REPO = "acme/widget"
_NOW = "2026-06-19T00:00:00Z"


def _make_store(kind: str) -> Store:
    if kind == "memory":
        return InMemoryStore()
    engine = engine_from_url("sqlite:///:memory:")
    create_all(engine)
    return SqlStore(engine)


def _register(store: Store, repo_id: str = _REPO) -> None:
    store.add_repo(
        RegistrationPayload(
            repo=RepoIdentity(
                repo_id=repo_id,
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
    sync_kind: str = "git",
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
        sync_kind=sync_kind,
        synced_at=_NOW,
    )


# ── roster CRUD through the Store seam (both backends) ───────────────────────


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_roster_upsert_list_and_mark_departed(kind: str) -> None:
    store = _make_store(kind)
    store.upsert_identity(Identity(name="alice"))
    store.upsert_identity(Identity(name="platform", kind="team"))
    assert [i.name for i in store.list_roster()] == ["alice", "platform"]  # K10 order
    # upsert UPDATES in place (no reorder, no duplicate)
    store.upsert_identity(Identity(name="alice", email="a@x.io"))
    assert [i.name for i in store.list_roster()] == ["alice", "platform"]
    assert store.list_roster()[0].email == "a@x.io"
    # mark departed flips active + stamps departed_at; an unknown name is a no-op
    store.mark_identity_departed("alice", at=_NOW)
    alice = next(i for i in store.list_roster() if i.name == "alice")
    assert alice.active is False and alice.departed_at == _NOW
    store.mark_identity_departed("ghost", at=_NOW)  # no raise


# ── HTTP routes (both backends) ──────────────────────────────────────────────


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_roster_routes_round_trip(kind: str) -> None:
    client = TestClient(create_app(_make_store(kind)))
    r = client.post("/admin/roster", json={"name": "alice", "kind": "person"})
    assert r.status_code == 201, r.text
    assert r.json() == {"name": "alice"}
    listed = client.get("/roster")
    assert listed.status_code == 200
    assert [i["name"] for i in listed.json()] == ["alice"]


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_mark_departed_route_and_404(kind: str) -> None:
    client = TestClient(create_app(_make_store(kind)))
    client.post("/admin/roster", json={"name": "dana"})
    r = client.post("/admin/roster/dana/departed")
    assert r.status_code == 200 and r.json()["departed"] is True
    assert client.get("/roster").json()[0]["active"] is False
    assert client.post("/admin/roster/ghost/departed").status_code == 404


# ── admin-token auth (a GLOBAL token, NOT per-repo) ──────────────────────────


def test_admin_routes_require_admin_token() -> None:
    client = TestClient(create_app(InMemoryStore(), admin_token="s3cret-admin"))
    assert client.post("/admin/roster", json={"name": "x"}).status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert (
        client.post("/admin/roster", json={"name": "x"}, headers=bad).status_code == 403
    )
    ok = {"Authorization": "Bearer s3cret-admin"}
    assert (
        client.post("/admin/roster", json={"name": "x"}, headers=ok).status_code == 201
    )
    assert client.get("/roster").status_code == 200  # reads stay open


def test_admin_routes_open_when_no_token_configured() -> None:
    client = TestClient(create_app(InMemoryStore()))  # no admin token
    assert client.post("/admin/roster", json={"name": "x"}).status_code == 201


# ── the per-repo /ownership view + the cross-repo cascade ────────────────────


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_ownership_view_and_departure_cascade(kind: str) -> None:
    store = _make_store(kind)
    _register(store)
    store.replace_config(
        _REPO,
        "git",
        [
            _doc(
                "core-api",
                owner="platform",
                team="platform",
                dri="dana",
                accountable="dana",
                durable="platform",
            )
        ],
        [],
    )
    store.upsert_identity(Identity(name="dana", active=True))
    store.upsert_identity(Identity(name="platform", kind="team", active=True))
    client = TestClient(create_app(store))

    body = client.get(f"/repos/{_REPO}/ownership").json()
    assert body["orphan_count"] == 0
    assert {o["doc_id"]: o["accountable"] for o in body["owners"]} == {
        "core-api": "dana"
    }
    assert body["findings"] == []

    # ONE write cascades: core-api becomes a DRI-vacant orphan on the NEXT read.
    store.mark_identity_departed("dana", at=_NOW)
    body2 = client.get(f"/repos/{_REPO}/ownership").json()
    assert body2["orphan_count"] == 1
    assert body2["findings"][0]["doc_id"] == "core-api"
    assert body2["findings"][0]["status"] == "orphan_dri_vacant"


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_config_document_round_trips_ownership(kind: str) -> None:
    """owner/team/dri + accountable/durable ride in the JSON column (additive, K6)."""
    store = _make_store(kind)
    _register(store)
    store.replace_config(
        _REPO,
        "git",
        [_doc("d", owner="o", team="t", dri="p", accountable="p", durable="t")],
        [],
    )
    [got] = store.config_documents_for(_REPO, "git")
    assert (got.owner, got.team, got.dri) == ("o", "t", "p")
    assert (got.accountable, got.durable) == ("p", "t")


def test_ownership_unknown_repo_is_404() -> None:
    client = TestClient(create_app(InMemoryStore()))
    assert client.get("/repos/nope/ownership").status_code == 404
