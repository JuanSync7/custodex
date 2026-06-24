"""Tests for custodex.registry (E-02 — repo registration client).

A repo announces itself to the central server via an INJECTED transport, so
tests never touch the network (K4) and HTTP uses the stdlib only (K0). The
payload is the SHARED, versioned :class:`RegistrationPayload` (K6); a missing
url/repo_id is a loud, typed error (K8). TDD (K9).

Features: FEAT-SERVER-017
"""

from __future__ import annotations

import pytest

from custodex.config import CentralConfig
from custodex.errors import SchemaError
from custodex.registry import (
    HttpRegisterTransport,
    RegistrationPayload,
    register_repo,
    repo_identity_from_config,
)
from custodex.sinks import RepoIdentity


def _repo() -> RepoIdentity:
    return RepoIdentity(
        repo_id="acme/widget",
        repo_name="widget",
        repo_url="https://git.example/acme/widget",
        commit="deadbeef",
    )


class FakeTransport:
    """An injected stand-in for a register transport: captures payloads, no net."""

    def __init__(self, response: dict | None = None) -> None:
        self.payloads: list[RegistrationPayload] = []
        self._response = response if response is not None else {"ok": True}

    def register(self, payload: RegistrationPayload) -> dict:
        self.payloads.append(payload)
        return self._response


# --- register_repo: payload shape + transport seam ---------------------------


def test_register_repo_submits_repo_identified_payload() -> None:
    transport = FakeTransport(response={"id": 7})
    out = register_repo(_repo(), url="https://central.example", transport=transport)

    assert out == {"id": 7}
    assert len(transport.payloads) == 1
    payload = transport.payloads[0]
    assert payload.schema_version == "1.0.0"
    assert payload.repo.repo_id == "acme/widget"
    assert payload.repo.commit == "deadbeef"


def test_register_repo_carries_optional_display_fields() -> None:
    transport = FakeTransport()
    register_repo(
        _repo(),
        url="https://central.example",
        transport=transport,
        default_branch="main",
        description="the widget repo",
    )
    payload = transport.payloads[0]
    assert payload.default_branch == "main"
    assert payload.description == "the widget repo"


def test_register_repo_dry_run_returns_payload_without_calling() -> None:
    transport = FakeTransport()
    out = register_repo(
        _repo(),
        url="https://central.example",
        transport=transport,
        dry_run=True,
    )
    # The transport is NEVER called on a dry run.
    assert transport.payloads == []
    # The returned payload dict carries the repo identity + schema version.
    assert out is not None
    assert out["schema_version"] == "1.0.0"
    assert out["repo"]["repo_id"] == "acme/widget"


def test_register_repo_missing_url_is_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    # K8: an http registration with no url is a loud, typed error (default
    # transport would be built, but the url is validated first).
    with pytest.raises(SchemaError):
        register_repo(_repo(), url="")


# --- default transport: lazy build + bearer + missing-env --------------------


def test_http_register_transport_lazy_build_posts_to_repos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When no http leaf is injected, register() builds a stdlib leaf lazily; we
    # stub its request() so the lazy-build branch runs with NO real network (K4).
    import custodex.registry as registry_mod

    posted: list[tuple[str, str, dict | None, str]] = []

    def fake_request(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        posted.append((method, url, body, token))
        return {"ok": True}

    monkeypatch.setenv("CDM_TOKEN", "s3cret")
    monkeypatch.setattr(registry_mod._UrllibRegisterHttp, "request", fake_request)
    transport = HttpRegisterTransport("https://central.example/", auth_env="CDM_TOKEN")
    out = transport.register(RegistrationPayload(repo=_repo()))

    assert out == {"ok": True}
    assert len(posted) == 1
    method, url, body, token = posted[0]
    assert method == "POST"
    assert url == "https://central.example/repos"  # trailing slash normalized
    assert body is not None and body["repo"]["repo_id"] == "acme/widget"
    assert token == "s3cret"  # bearer read from the env at register time


def test_http_register_transport_no_token_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custodex.registry as registry_mod

    seen: list[str] = []

    def fake_request(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        seen.append(token)
        return {}

    monkeypatch.delenv("CDM_TOKEN", raising=False)
    monkeypatch.setattr(registry_mod._UrllibRegisterHttp, "request", fake_request)
    transport = HttpRegisterTransport("https://central.example", auth_env="CDM_TOKEN")
    transport.register(RegistrationPayload(repo=_repo()))
    assert seen == [""]  # no token -> empty bearer (no Authorization header)


def test_register_repo_default_transport_lazy_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # register_repo with transport=None builds the default HttpRegisterTransport
    # and submits through it (the leaf stubbed so there is NO network, K4).
    import custodex.registry as registry_mod

    posted: list[str] = []

    def fake_request(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        posted.append(url)
        return {"registered": True}

    monkeypatch.setattr(registry_mod._UrllibRegisterHttp, "request", fake_request)
    out = register_repo(_repo(), url="https://central.example")
    assert out == {"registered": True}
    assert posted == ["https://central.example/repos"]


# --- repo_identity_from_config: shared helper (de-dups make_sink) -------------


def test_repo_identity_from_config_builds_identity() -> None:
    cfg = CentralConfig(
        sink="http",
        url="https://central.example",
        repo_id="acme/widget",
        repo_name="widget",
        repo_url="https://git.example/acme/widget",
        repo_commit="cafef00d",
    )
    identity = repo_identity_from_config(cfg)
    assert identity.repo_id == "acme/widget"
    assert identity.repo_name == "widget"
    assert identity.commit == "cafef00d"


def test_repo_identity_from_config_commit_falls_back_to_ci_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CI_COMMIT_SHA", "abc123")
    cfg = CentralConfig(sink="http", url="https://central.example", repo_id="r")
    assert repo_identity_from_config(cfg).commit == "abc123"


def test_repo_identity_from_config_missing_repo_id_is_loud() -> None:
    # K8: no repo_id -> loud, typed error (you can't register an anonymous repo).
    with pytest.raises(SchemaError):
        repo_identity_from_config(CentralConfig(sink="http", url="https://c.example"))


def test_registration_payload_forbids_unknown_keys() -> None:
    # K8: the wire payload is strict — an unexpected key is a loud error.
    with pytest.raises(Exception):  # noqa: B017,PT011 — pydantic ValidationError
        RegistrationPayload(repo=_repo(), bogus="x")  # type: ignore[call-arg]
