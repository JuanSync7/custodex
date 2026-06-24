"""EDITOR E-05 — ``POST/GET /repos/{id}/config/edits`` the staged-ticket routes.

A :class:`TestClient` parametrized over BOTH store impls (InMemoryStore + SqlStore
over an in-memory SQLite), with a fixed ``clock`` so the derived ``edit_id`` and the
``created_at`` stamp are deterministic (K10). Exercises:

* POST a ``create_doc`` edit on a token-protected repo → 201 + an ``edit_id``; the
  GET list then shows it ``pending``; ``?status=pending`` includes it and
  ``?status=applied`` excludes it;
* each of the 5 actions round-trips through the union (POST → GET);
* a malformed body (unknown ``action`` / a stray field) → 422 (loud, no 500);
* token enforcement mirrors ``/sync``: missing → 401, wrong → 403, OPEN repo → open;
* edit_id determinism: same body + fixed clock ⇒ same id;
* unknown repo → 404 on both routes.

Offline + deterministic (K10).

Features: FEAT-SERVER-011, FEAT-SERVER-004, FEAT-SERVER-005
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")
pytest.importorskip(
    "sqlalchemy", reason="the [server] extra (sqlalchemy) is not installed"
)

from fastapi.testclient import TestClient  # noqa: E402

from custodex.registry import RegistrationPayload  # noqa: E402
from custodex.server import InMemoryStore, create_app  # noqa: E402
from custodex.server.db import (  # noqa: E402
    SqlStore,
    create_all,
    engine_from_url,
)
from custodex.server.store import Store  # noqa: E402
from custodex.sinks import RepoIdentity  # noqa: E402

_REPO = "acme/widget"
_OPEN_REPO = "acme/open"
_TOKEN = "s3cret-token"
_NOW = "2026-06-08T00:00:00Z"


def _make_store(kind: str) -> Store:
    if kind == "memory":
        return InMemoryStore()
    engine = engine_from_url("sqlite:///:memory:")
    create_all(engine)
    return SqlStore(engine)


@pytest.fixture(params=["memory", "sql"])
def client(request: pytest.FixtureRequest) -> Iterator[TestClient]:
    store = _make_store(request.param)
    app = create_app(store, clock=lambda: _NOW)
    with TestClient(app) as c:
        yield c


def _register(
    client: TestClient,
    *,
    repo_id: str = _REPO,
    auth_token: str | None = _TOKEN,
) -> None:
    identity = RepoIdentity(
        repo_id=repo_id,
        repo_name="widget",
        local_path=None,
        default_branch="main",
    )
    payload = RegistrationPayload(
        repo=identity, default_branch="main", auth_token=auth_token
    ).model_dump(mode="json")
    resp = client.post("/repos", json=payload)
    assert resp.status_code == 201, resp.text


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {_TOKEN}"}


# A representative payload for each of the 5 union actions. -------------------- #
_CREATE_DOC = {
    "action": "create_doc",
    "unit": "core",
    "doc_id": "getting-started",
    "path": "docs/guide/getting-started.md",
    "audience": "user-guide",
    "code_refs": [{"path": "src/calc.py", "symbols": ["add"], "lines": None}],
    "context_refs": [{"path": "docs/api/core.md", "note": "the full reference"}],
    "doc_style": {"document_type": "guide", "tone": "neutral"},
}
_ADD_CODE_REF = {
    "action": "add_code_ref",
    "unit": "core",
    "doc_id": "getting-started",
    "ref": {"path": "src/engine.py", "symbols": ["run"]},
}
_REMOVE_CODE_REF = {
    "action": "remove_code_ref",
    "unit": "core",
    "doc_id": "getting-started",
    "path": "src/calc.py",
}
_SET_CONTEXT_REFS = {
    "action": "set_context_refs",
    "unit": "core",
    "doc_id": "getting-started",
    "context_refs": [{"path": "src/engine.py", "note": "scheduling semantics"}],
}
_SET_DOC_STYLE = {
    "action": "set_doc_style",
    "doc_id": "getting-started",
    "doc_style": {"writing_style": "concise", "vocabulary": "technical"},
}
_REASSIGN_OWNER = {  # EPIC OWN (FEAT-OWNERSHIP-008): the orphan fix, config = truth
    "action": "reassign_owner",
    "unit": "core",
    "doc_id": "getting-started",
    "owner": "platform-team",
    "team": "platform-team",
    "dri": "alice",
}
_ALL_ACTIONS = [
    _CREATE_DOC,
    _ADD_CODE_REF,
    _REMOVE_CODE_REF,
    _SET_CONTEXT_REFS,
    _SET_DOC_STYLE,
    _REASSIGN_OWNER,
]


# --------------------------------------------------------------------------- #
# Happy path: POST stages pending, GET round-trips + status filter.
# --------------------------------------------------------------------------- #


def test_post_stages_pending_and_get_lists_it(client: TestClient) -> None:
    _register(client)
    resp = client.post(
        f"/repos/{_REPO}/config/edits", json=_CREATE_DOC, headers=_auth()
    )
    assert resp.status_code == 201, resp.text
    edit_id = resp.json()["edit_id"]
    assert edit_id.startswith("edit-")

    listing = client.get(f"/repos/{_REPO}/config/edits")
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["edit_id"] == edit_id
    assert row["status"] == "pending"
    assert row["created_at"] == _NOW
    assert row["applied_at"] is None
    assert row["edit"]["action"] == "create_doc"
    assert row["edit"]["doc_id"] == "getting-started"


def test_status_filter_includes_pending_excludes_applied(client: TestClient) -> None:
    _register(client)
    client.post(f"/repos/{_REPO}/config/edits", json=_CREATE_DOC, headers=_auth())

    pending = client.get(f"/repos/{_REPO}/config/edits", params={"status": "pending"})
    assert pending.status_code == 200
    assert len(pending.json()) == 1

    applied = client.get(f"/repos/{_REPO}/config/edits", params={"status": "applied"})
    assert applied.status_code == 200
    assert applied.json() == []


@pytest.mark.parametrize("body", _ALL_ACTIONS)
def test_each_action_round_trips(client: TestClient, body: dict) -> None:
    _register(client)
    resp = client.post(f"/repos/{_REPO}/config/edits", json=body, headers=_auth())
    assert resp.status_code == 201, resp.text
    edit_id = resp.json()["edit_id"]

    rows = client.get(f"/repos/{_REPO}/config/edits").json()
    assert [r["edit_id"] for r in rows] == [edit_id]
    assert rows[0]["edit"]["action"] == body["action"]


def test_insertion_order_preserved(client: TestClient) -> None:
    _register(client)
    ids = []
    for body in _ALL_ACTIONS:
        resp = client.post(f"/repos/{_REPO}/config/edits", json=body, headers=_auth())
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["edit_id"])
    rows = client.get(f"/repos/{_REPO}/config/edits").json()
    assert [r["edit_id"] for r in rows] == ids


# --------------------------------------------------------------------------- #
# Malformed bodies → 422 (loud pydantic validation, never 500).
# --------------------------------------------------------------------------- #


def test_unknown_action_is_422(client: TestClient) -> None:
    _register(client)
    resp = client.post(
        f"/repos/{_REPO}/config/edits",
        json={"action": "frobnicate", "unit": "core", "doc_id": "x"},
        headers=_auth(),
    )
    assert resp.status_code == 422, resp.text


def test_extra_field_is_422(client: TestClient) -> None:
    _register(client)
    body = {**_ADD_CODE_REF, "surprise": "value"}
    resp = client.post(f"/repos/{_REPO}/config/edits", json=body, headers=_auth())
    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- #
# Token enforcement — mirrors POST /sync (401 missing / 403 wrong / open repo).
# --------------------------------------------------------------------------- #


def test_post_requires_token(client: TestClient) -> None:
    _register(client)
    no_auth = client.post(f"/repos/{_REPO}/config/edits", json=_CREATE_DOC)
    assert no_auth.status_code == 401

    wrong = client.post(
        f"/repos/{_REPO}/config/edits",
        json=_CREATE_DOC,
        headers={"Authorization": "Bearer nope"},
    )
    assert wrong.status_code == 403


def test_open_repo_posts_token_less(client: TestClient) -> None:
    _register(client, repo_id=_OPEN_REPO, auth_token=None)
    resp = client.post(f"/repos/{_OPEN_REPO}/config/edits", json=_CREATE_DOC)
    assert resp.status_code == 201, resp.text
    rows = client.get(f"/repos/{_OPEN_REPO}/config/edits").json()
    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# edit_id determinism + unknown repo.
# --------------------------------------------------------------------------- #


def test_edit_id_is_deterministic_under_fixed_clock(client: TestClient) -> None:
    _register(client)
    first = client.post(
        f"/repos/{_REPO}/config/edits", json=_CREATE_DOC, headers=_auth()
    ).json()["edit_id"]
    second = client.post(
        f"/repos/{_REPO}/config/edits", json=_CREATE_DOC, headers=_auth()
    ).json()["edit_id"]
    assert first == second


def test_post_unknown_repo_is_404(client: TestClient) -> None:
    resp = client.post("/repos/nope/config/edits", json=_CREATE_DOC, headers=_auth())
    assert resp.status_code == 404


def test_get_unknown_repo_is_404(client: TestClient) -> None:
    resp = client.get("/repos/nope/config/edits")
    assert resp.status_code == 404
