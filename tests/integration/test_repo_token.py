"""SRV-TOKEN — the admin repo-token reset, over BOTH Store backends.

A lost per-repo bearer token used to lock a repo's writes for good: a tokenless
re-register keeps the old hash, and nothing short of a DB edit could replace or
clear it. ``POST /admin/repos/{repo_id}/token/reset`` is the recovery path, and
it is built so it can never become a way in:

- it needs the GLOBAL admin token and FAILS CLOSED (403) when none is configured
  (unlike the roster routes, which stay open in offline/dev);
- an unknown repo is a 404 only after admin auth, and before any body check;
- the body names exactly ONE intent: a new ``auth_token``, or the JSON literal
  ``{"open": true}`` — an absent / null / false intent is a 400, so a reset never
  opens a repo implicitly (PD-47), and a truthy stand-in (``1``, ``"yes"``) is 422;
- a token outside the shared bearer rule (printable ASCII 0x21-0x7E, no
  whitespace) is a 400, and the token is never echoed;
- resetting to the stored value is one change (K7), and only the named repo moves.

``Store.set_repo_token_hash`` is pinned directly too. An admin token that breaks
the same bearer rule stops ``create_app`` with a loud ``ConfigError`` (K8).

Every route test runs over ``InMemoryStore`` and ``SqlStore`` (in-memory SQLite),
offline and deterministic (K4/K10).

Features: FEAT-SERVER-020
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")
pytest.importorskip(
    "sqlalchemy", reason="the [server] extra (sqlalchemy) is not installed"
)

from fastapi.testclient import TestClient  # noqa: E402

from custodex.errors import ConfigError  # noqa: E402
from custodex.registry import RegistrationPayload  # noqa: E402
from custodex.schema import ProposedFix, ReviewRecord, Verdict  # noqa: E402
from custodex.server import InMemoryStore, create_app  # noqa: E402
from custodex.server.db import SqlStore, create_all, engine_from_url  # noqa: E402
from custodex.server.store import Store, hash_token  # noqa: E402
from custodex.sinks import IngestEnvelope, RepoIdentity  # noqa: E402

_REPO = "acme/widget"
_OTHER = "acme/gadget"
_TOKEN = "first-token"
_NEW = "second-token"
_ADMIN = "adm1n-secret"
_NOW = "2026-06-05T00:00:00Z"


def _identity(repo_id: str = _REPO) -> RepoIdentity:
    return RepoIdentity(
        repo_id=repo_id,
        repo_name=repo_id.split("/")[-1],
        repo_url=f"https://example.invalid/{repo_id}",
        commit="deadbeef",
    )


def _registration(repo_id: str = _REPO, auth_token: str | None = _TOKEN) -> dict:
    return RegistrationPayload(
        repo=_identity(repo_id), auth_token=auth_token
    ).model_dump(mode="json")


def _envelope(repo_id: str = _REPO, record_id: str = "abc123def456") -> dict:
    record = ReviewRecord(
        record_id=record_id,
        doc_id="pipeline",
        doc_path="docs/api/pipeline.md",
        audience="eng-guide",
        drift_kind="REGION",
        drift_detail="signature moved",
        cause="public signature changed",
        verdict=Verdict.FIX,
        fix=ProposedFix(rationale="regenerate the region"),
        surface_hash="0" * 16,
        backend_kind="mock",
        detected_at=_NOW,
        resolved_at=_NOW,
        config_snapshot={"repo_id": repo_id},
        source_sha="cafebabe",
    )
    return IngestEnvelope(repo=_identity(repo_id), record=record).model_dump(
        mode="json"
    )


def _make_store(kind: str) -> Store:
    if kind == "memory":
        return InMemoryStore()
    engine = engine_from_url("sqlite:///:memory:")
    create_all(engine)
    return SqlStore(engine)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _reset_path(repo_id: str = _REPO) -> str:
    return f"/admin/repos/{repo_id}/token/reset"


@pytest.fixture(params=["memory", "sql"])
def store(request: pytest.FixtureRequest) -> Store:
    return _make_store(request.param)


@pytest.fixture
def client(store: Store, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient over an app WITH an admin token, once per Store backend."""
    monkeypatch.delenv("CDMON_ADMIN_TOKEN", raising=False)
    with TestClient(create_app(store, admin_token=_ADMIN)) as test_client:
        yield test_client


def _register(
    client: TestClient, repo_id: str = _REPO, token: str | None = _TOKEN
) -> None:
    resp = client.post("/repos", json=_registration(repo_id, token))
    assert resp.status_code == 201, resp.text


def _ingest_status(
    client: TestClient, token: str | None, repo_id: str = _REPO, rid: str = "r1"
) -> int:
    headers = _auth(token) if token is not None else {}
    resp = client.post(
        "/ingest", json=_envelope(repo_id, record_id=f"{rid}-{token}"), headers=headers
    )
    return resp.status_code


# --------------------------------------------------------------------------- #
# admin auth — required, and FAIL CLOSED with no admin token configured
# --------------------------------------------------------------------------- #
def test_reset_requires_the_admin_token(client: TestClient, store: Store) -> None:
    _register(client)
    body = {"auth_token": _NEW}
    assert client.post(_reset_path(), json=body).status_code == 401
    assert (
        client.post(_reset_path(), json=body, headers=_auth("wrong")).status_code == 403
    )
    # the repo's OWN token is never an admin token
    assert (
        client.post(_reset_path(), json=body, headers=_auth(_TOKEN)).status_code == 403
    )
    assert store.repo_token_hash(_REPO) == hash_token(_TOKEN)
    ok = client.post(_reset_path(), json=body, headers=_auth(_ADMIN))
    assert ok.status_code == 200, ok.text
    assert store.repo_token_hash(_REPO) == hash_token(_NEW)


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_reset_fails_closed_without_a_configured_admin_token(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CDMON_ADMIN_TOKEN", raising=False)
    store = _make_store(kind)
    client = TestClient(create_app(store))
    _register(client)
    for headers in ({}, _auth("anything"), _auth(_TOKEN)):
        for body in ({"auth_token": _NEW}, {"open": True}):
            resp = client.post(_reset_path(), json=body, headers=headers)
            assert resp.status_code == 403, (headers, body, resp.text)
    assert store.repo_token_hash(_REPO) == hash_token(_TOKEN)
    # back-compat: the roster routes keep their open-in-dev default
    roster = client.post("/admin/roster", json={"name": "alice"})
    assert roster.status_code == 201, roster.text


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_an_empty_admin_token_still_means_not_configured(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CDMON_ADMIN_TOKEN", "")
    store = _make_store(kind)
    client = TestClient(create_app(store))
    _register(client)
    resp = client.post(_reset_path(), json={"open": True}, headers=_auth(""))
    assert resp.status_code == 403
    assert store.repo_token_hash(_REPO) == hash_token(_TOKEN)


def test_reset_unknown_repo_is_404_only_after_admin_auth(client: TestClient) -> None:
    body = {"auth_token": _NEW}
    assert client.post(_reset_path("ghost/repo"), json=body).status_code == 401
    assert (
        client.post(
            _reset_path("ghost/repo"), json=body, headers=_auth("wrong")
        ).status_code
        == 403
    )
    resp = client.post(_reset_path("ghost/repo"), json=body, headers=_auth(_ADMIN))
    assert resp.status_code == 404
    assert "ghost/repo" in resp.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"open": False},
        {"auth_token": " padded"},
        {"auth_token": "a", "open": True},
    ],
    ids=["empty", "open-false", "padded", "both"],
)
def test_unknown_repo_is_404_before_any_body_check(
    client: TestClient, store: Store, body: dict
) -> None:
    resp = client.post(_reset_path("ghost/repo"), json=body, headers=_auth(_ADMIN))
    assert resp.status_code == 404, resp.text
    assert store.get_repo("ghost/repo") is None
    assert store.repo_token_hash("ghost/repo") is None


# --------------------------------------------------------------------------- #
# set a new token
# --------------------------------------------------------------------------- #
def test_reset_rotates_to_the_new_token_and_revokes_the_old(
    client: TestClient, store: Store
) -> None:
    _register(client)
    resp = client.post(_reset_path(), json={"auth_token": _NEW}, headers=_auth(_ADMIN))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"repo_id": _REPO, "protected": True, "changed": True}
    # stored as the sha256 hash, never as plaintext
    assert store.repo_token_hash(_REPO) == hash_token(_NEW)
    assert _ingest_status(client, _TOKEN) == 403
    assert _ingest_status(client, None) == 401
    assert _ingest_status(client, _NEW) == 202


def test_reset_protects_a_repo_registered_open(
    client: TestClient, store: Store
) -> None:
    _register(client, token=None)
    assert store.repo_token_hash(_REPO) is None
    resp = client.post(_reset_path(), json={"auth_token": _NEW}, headers=_auth(_ADMIN))
    assert resp.status_code == 200
    assert resp.json() == {"repo_id": _REPO, "protected": True, "changed": True}
    assert _ingest_status(client, None) == 401
    assert _ingest_status(client, _NEW) == 202


def test_reset_never_echoes_the_token(client: TestClient) -> None:
    _register(client)
    token = "zz-very-distinctive-token-zz"
    resp = client.post(_reset_path(), json={"auth_token": token}, headers=_auth(_ADMIN))
    assert resp.status_code == 200
    assert token not in resp.text
    bad = "zz distinctive bad token zz"
    rejected = client.post(
        _reset_path(), json={"auth_token": bad}, headers=_auth(_ADMIN)
    )
    assert rejected.status_code == 400
    assert bad not in rejected.text


def test_reset_accepts_the_whole_printable_ascii_charset(
    client: TestClient, store: Store
) -> None:
    _register(client)
    token = "".join(chr(c) for c in range(0x21, 0x7F))
    resp = client.post(_reset_path(), json={"auth_token": token}, headers=_auth(_ADMIN))
    assert resp.status_code == 200, resp.text
    assert store.repo_token_hash(_REPO) == hash_token(token)
    assert _ingest_status(client, token) == 202


@pytest.mark.parametrize(
    "token",
    [
        "",
        "   ",
        " lead",
        "trail\n",
        "trail\r\n",
        "inner space",
        "inner\ttab",
        "tok€n",
        "a\nb",
        "a\rb",
        "a\x00b",
        "del\x7f",
    ],
    ids=[
        "empty",
        "blank",
        "lead",
        "trail-lf",
        "trail-crlf",
        "space",
        "tab",
        "non-ascii",
        "lf",
        "cr",
        "nul",
        "del",
    ],
)
def test_reset_rejects_a_token_outside_the_bearer_charset(
    client: TestClient, store: Store, token: str
) -> None:
    _register(client)
    resp = client.post(_reset_path(), json={"auth_token": token}, headers=_auth(_ADMIN))
    assert resp.status_code == 400, resp.text
    assert "printable ASCII" in resp.json()["detail"]
    assert store.repo_token_hash(_REPO) == hash_token(_TOKEN)


# --------------------------------------------------------------------------- #
# clearing — only by an explicit {"open": true}  (PD-47)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "body",
    [{}, {"auth_token": None}, {"open": False}, {"auth_token": None, "open": False}],
    ids=["empty", "null-token", "open-false", "null-and-false"],
)
def test_reset_never_opens_a_repo_implicitly(
    client: TestClient, store: Store, body: dict
) -> None:
    _register(client)
    resp = client.post(_reset_path(), json=body, headers=_auth(_ADMIN))
    assert resp.status_code == 400, resp.text
    assert "implicitly" in resp.json()["detail"]
    assert store.repo_token_hash(_REPO) == hash_token(_TOKEN)
    assert _ingest_status(client, None) == 401


def test_explicit_open_true_clears_the_token(client: TestClient, store: Store) -> None:
    _register(client)
    resp = client.post(_reset_path(), json={"open": True}, headers=_auth(_ADMIN))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"repo_id": _REPO, "protected": False, "changed": True}
    assert store.repo_token_hash(_REPO) is None
    assert _ingest_status(client, None) == 202


def test_a_token_and_open_together_is_a_contradiction(
    client: TestClient, store: Store
) -> None:
    _register(client)
    resp = client.post(
        _reset_path(), json={"auth_token": _NEW, "open": True}, headers=_auth(_ADMIN)
    )
    assert resp.status_code == 400
    assert "not both" in resp.json()["detail"]
    assert store.repo_token_hash(_REPO) == hash_token(_TOKEN)


@pytest.mark.parametrize("token", ["", " "], ids=["empty", "blank"])
def test_an_empty_token_with_open_is_still_a_contradiction(
    client: TestClient, store: Store, token: str
) -> None:
    """An empty/blank token plus open names TWO intents: a 400, never a clear.

    Guards the both-intents check keeping ``is not None``: a truthiness test would
    let ``{"auth_token": "", "open": true}`` fall through and OPEN a protected repo.
    """
    _register(client)
    resp = client.post(
        _reset_path(), json={"auth_token": token, "open": True}, headers=_auth(_ADMIN)
    )
    assert resp.status_code == 400, resp.text
    assert "not both" in resp.json()["detail"]
    assert store.repo_token_hash(_REPO) == hash_token(_TOKEN)


@pytest.mark.parametrize(
    "value",
    [1, 1.0, "true", "TRUE", "1", "y", "yes", "on", "t", 0, "false", "off"],
)
def test_open_must_be_a_json_boolean(
    client: TestClient, store: Store, value: object
) -> None:
    _register(client)
    resp = client.post(_reset_path(), json={"open": value}, headers=_auth(_ADMIN))
    assert resp.status_code == 422, resp.text
    assert store.repo_token_hash(_REPO) == hash_token(_TOKEN)
    assert _ingest_status(client, None) == 401


def test_a_stray_field_is_rejected(client: TestClient, store: Store) -> None:
    _register(client)
    resp = client.post(
        _reset_path(),
        json={"auth_token": _NEW, "clear": True},
        headers=_auth(_ADMIN),
    )
    assert resp.status_code == 422
    assert store.repo_token_hash(_REPO) == hash_token(_TOKEN)


# --------------------------------------------------------------------------- #
# K7 + isolation
# --------------------------------------------------------------------------- #
def test_reset_to_the_same_token_is_one_change(
    client: TestClient, store: Store
) -> None:
    _register(client)
    first = client.post(_reset_path(), json={"auth_token": _NEW}, headers=_auth(_ADMIN))
    again = client.post(_reset_path(), json={"auth_token": _NEW}, headers=_auth(_ADMIN))
    assert first.json()["changed"] is True
    assert again.status_code == 200
    assert again.json() == {"repo_id": _REPO, "protected": True, "changed": False}
    assert store.repo_token_hash(_REPO) == hash_token(_NEW)
    opened = client.post(_reset_path(), json={"open": True}, headers=_auth(_ADMIN))
    reopened = client.post(_reset_path(), json={"open": True}, headers=_auth(_ADMIN))
    assert opened.json() == {"repo_id": _REPO, "protected": False, "changed": True}
    assert reopened.json() == {"repo_id": _REPO, "protected": False, "changed": False}


@pytest.mark.parametrize("target", [_REPO, _OTHER])
def test_a_reset_touches_only_the_named_repo(
    client: TestClient, store: Store, target: str
) -> None:
    tokens = {_REPO: "tok-widget", _OTHER: "tok-gadget"}
    for repo_id, token in tokens.items():
        _register(client, repo_id, token)
    bystander = _OTHER if target == _REPO else _REPO
    resp = client.post(
        _reset_path(target), json={"auth_token": "tok-new"}, headers=_auth(_ADMIN)
    )
    assert resp.status_code == 200
    assert store.repo_token_hash(target) == hash_token("tok-new")
    assert store.repo_token_hash(bystander) == hash_token(tokens[bystander])
    assert _ingest_status(client, tokens[bystander], bystander, "b1") == 202
    assert _ingest_status(client, None, bystander, "b2") == 401
    opened = client.post(
        _reset_path(target), json={"open": True}, headers=_auth(_ADMIN)
    )
    assert opened.status_code == 200
    assert store.repo_token_hash(target) is None
    assert store.repo_token_hash(bystander) == hash_token(tokens[bystander])
    assert _ingest_status(client, None, bystander, "b3") == 401


def test_reregister_after_a_reset_needs_the_new_token(
    client: TestClient, store: Store
) -> None:
    _register(client)
    client.post(_reset_path(), json={"auth_token": _NEW}, headers=_auth(_ADMIN))
    old = client.post("/repos", json=_registration(), headers=_auth(_TOKEN))
    assert old.status_code == 403
    new = client.post(
        "/repos", json=_registration(auth_token=_NEW), headers=_auth(_NEW)
    )
    assert new.status_code == 201
    assert store.repo_token_hash(_REPO) == hash_token(_NEW)


def test_a_reregister_without_a_token_keeps_a_reset_hash(
    client: TestClient, store: Store
) -> None:
    _register(client)
    client.post(_reset_path(), json={"auth_token": _NEW}, headers=_auth(_ADMIN))
    resp = client.post(
        "/repos", json=_registration(auth_token=None), headers=_auth(_NEW)
    )
    assert resp.status_code == 201
    assert store.repo_token_hash(_REPO) == hash_token(_NEW)


# --------------------------------------------------------------------------- #
# Store.set_repo_token_hash — directly, on both stores
# --------------------------------------------------------------------------- #
def test_set_repo_token_hash_reports_whether_it_changed(store: Store) -> None:
    store.add_repo(RegistrationPayload(repo=_identity(), auth_token=_TOKEN))
    assert store.set_repo_token_hash(_REPO, hash_token(_TOKEN)) is False
    assert store.set_repo_token_hash(_REPO, hash_token(_NEW)) is True
    # a fresh-but-equal string is still "no change" (compared by value, K7)
    assert store.set_repo_token_hash(_REPO, hash_token(_NEW)) is False
    assert store.repo_token_hash(_REPO) == hash_token(_NEW)
    assert store.set_repo_token_hash(_REPO, None) is True
    assert store.repo_token_hash(_REPO) is None
    assert store.set_repo_token_hash(_REPO, None) is False
    # the rest of the registration is untouched
    got = store.get_repo(_REPO)
    assert got is not None
    assert got.repo.repo_id == _REPO


def test_set_repo_token_hash_ignores_an_unknown_repo(store: Store) -> None:
    assert store.set_repo_token_hash("ghost/repo", hash_token(_NEW)) is False
    assert store.get_repo("ghost/repo") is None
    assert store.repo_token_hash("ghost/repo") is None
    assert store.list_repos() == []


def test_set_repo_token_hash_touches_only_the_named_repo(store: Store) -> None:
    store.add_repo(RegistrationPayload(repo=_identity(_REPO), auth_token="a"))
    store.add_repo(RegistrationPayload(repo=_identity(_OTHER), auth_token="b"))
    for target, other, other_token in ((_OTHER, _REPO, "a"), (_REPO, _OTHER, "b")):
        assert store.set_repo_token_hash(target, hash_token("z-" + target)) is True
        assert store.repo_token_hash(target) == hash_token("z-" + target)
        assert store.repo_token_hash(other) in (
            hash_token(other_token),
            hash_token("z-" + other),
        )
    assert store.repo_token_hash(_REPO) == hash_token("z-" + _REPO)
    assert store.repo_token_hash(_OTHER) == hash_token("z-" + _OTHER)


# --------------------------------------------------------------------------- #
# the admin token itself must follow the bearer rule (loud at build time, K8)
# --------------------------------------------------------------------------- #
_BAD_ADMIN = {
    "lead": " adm-tok",
    "trail-lf": "adm-tok\n",
    "trail-crlf": "adm-tok\r\n",
    "blank": "   ",
    "space": "adm tok",
    "tab": "adm\ttok",
    "lf": "adm\ntok",
    "cr": "adm\rtok",
    "non-ascii": "adm-t€ken",
}


@pytest.mark.parametrize("source", ["param", "env"])
@pytest.mark.parametrize("case", sorted(_BAD_ADMIN))
def test_an_admin_token_outside_the_bearer_charset_is_a_loud_startup_error(
    source: str, case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = _BAD_ADMIN[case]
    if source == "param":
        monkeypatch.delenv("CDMON_ADMIN_TOKEN", raising=False)
        with pytest.raises(ConfigError) as info:
            create_app(InMemoryStore(), admin_token=value)
        assert "admin_token" in str(info.value)
    else:
        monkeypatch.setenv("CDMON_ADMIN_TOKEN", value)
        with pytest.raises(ConfigError) as info:
            create_app(InMemoryStore())
        assert "CDMON_ADMIN_TOKEN" in str(info.value)
    message = str(info.value)
    assert "printable ASCII" in message
    if value.strip():
        assert value.strip() not in message  # never quotes the token


def test_an_admin_token_with_a_nul_is_a_loud_startup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # (an environment value cannot hold a NUL, so only the param source)
    monkeypatch.delenv("CDMON_ADMIN_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="printable ASCII"):
        create_app(InMemoryStore(), admin_token="adm\x00tok")


def test_a_valid_admin_token_from_the_env_gates_the_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CDMON_ADMIN_TOKEN", "env-admin")
    store = InMemoryStore()
    client = TestClient(create_app(store))
    _register(client)
    assert (
        client.post(
            _reset_path(), json={"open": True}, headers=_auth(_ADMIN)
        ).status_code
        == 403
    )
    ok = client.post(_reset_path(), json={"open": True}, headers=_auth("env-admin"))
    assert ok.status_code == 200
    assert store.repo_token_hash(_REPO) is None
