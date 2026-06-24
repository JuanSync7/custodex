"""GIT-02 — provider identity fields + the sealed-secret Store seam (Store-parity).

Every test runs over BOTH ``InMemoryStore`` AND ``SqlStore`` (the same contract,
K6) so the two stores stay in lock-step. ``provider``/``remote_url`` ride on the
shared :class:`RepoIdentity` (inside the payload JSON → NO migration). The sealed
``provider_secret`` is OPAQUE ``bytes`` the route persists via
:meth:`Store.set_provider_secret` and reads back via
:meth:`Store.repo_provider_secret` (parallel to ``repo_token_hash``); the store
never sees plaintext and never imports ``cryptography``. The WRITE-ONLY plaintext
``RegistrationPayload.provider_secret`` must never reach the stored repo
projection (the SqlStore payload-JSON sanitize is asserted in ``test_db.py``).

Features: FEAT-SERVER-003, FEAT-SERVER-006
"""

from __future__ import annotations

from typing import Any

import pytest

from custodex.registry import RegistrationPayload
from custodex.sinks import RepoIdentity


@pytest.fixture(params=["memory", "sql"])
def store(request: pytest.FixtureRequest) -> Any:
    """A fresh Store of each kind — proves InMemoryStore/SqlStore parity (K6)."""
    if request.param == "memory":
        from custodex.server.store import InMemoryStore

        return InMemoryStore()
    pytest.importorskip("sqlalchemy", reason="the [server] extra is not installed")
    from custodex.server.db import SqlStore, create_all, engine_from_url

    engine = engine_from_url("sqlite:///:memory:")
    create_all(engine)
    return SqlStore(engine)


def _payload(
    repo_id: str = "acme/widget",
    *,
    provider: str | None = None,
    remote_url: str | None = None,
    provider_secret: str | None = None,
) -> RegistrationPayload:
    return RegistrationPayload(
        repo=RepoIdentity(repo_id=repo_id, provider=provider, remote_url=remote_url),
        default_branch="main",
        provider_secret=provider_secret,
    )


def test_provider_and_remote_url_round_trip_on_identity(store: Any) -> None:
    store.add_repo(_payload(provider="github", remote_url="https://github.com/o/r.git"))
    got = store.get_repo("acme/widget")
    assert got is not None
    assert got.repo.provider == "github"
    assert got.repo.remote_url == "https://github.com/o/r.git"


def test_provider_secret_round_trips_as_opaque_bytes(store: Any) -> None:
    store.add_repo(_payload())
    assert store.repo_provider_secret("acme/widget") is None  # unset → None
    sealed = b"\x00sealed-bytes\xff\x10"
    store.set_provider_secret("acme/widget", sealed)
    assert store.repo_provider_secret("acme/widget") == sealed


def test_provider_secret_none_for_unknown_repo(store: Any) -> None:
    assert store.repo_provider_secret("nope/never") is None


def test_set_provider_secret_rotates_in_place(store: Any) -> None:
    store.add_repo(_payload())
    store.set_provider_secret("acme/widget", b"first")
    store.set_provider_secret("acme/widget", b"second")
    assert store.repo_provider_secret("acme/widget") == b"second"


def test_registered_repo_projection_has_no_provider_secret(store: Any) -> None:
    # The plaintext provider_secret is WRITE-ONLY: RegisteredRepo never carries it.
    store.add_repo(_payload(provider_secret="PLAINTEXT-TOKEN"))
    got = store.get_repo("acme/widget")
    assert got is not None
    assert "provider_secret" not in got.model_dump()


def test_set_provider_secret_on_unknown_repo_is_noop(store: Any) -> None:
    # Setting a secret for a repo that was never registered is silently ignored
    # by BOTH stores (the route always registers first) — no crash, reads None.
    store.set_provider_secret("nope/never", b"dangling")
    assert store.repo_provider_secret("nope/never") is None


def test_provider_secret_independent_of_identity_fields(store: Any) -> None:
    # A repo registered WITHOUT provider/remote_url can still carry a sealed secret
    # (the seam is orthogonal to the identity fields).
    store.add_repo(_payload())
    store.set_provider_secret("acme/widget", b"sealed")
    got = store.get_repo("acme/widget")
    assert got is not None
    assert got.repo.provider is None
    assert store.repo_provider_secret("acme/widget") == b"sealed"
