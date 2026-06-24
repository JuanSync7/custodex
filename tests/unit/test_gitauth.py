"""GIT-05 — short-lived provider-token minting (PHASE 2; offline, K4/K8/K10).

Exercises :mod:`custodex.gitauth` with NO network and NO real provider: a
GENERATED test RSA key signs the GitHub App JWT (verified against its own public
key), and an INJECTED fake exchange leaf returns the minted token. Every malformed
input is a loud :class:`TransportError`. The ``cryptography`` import stays lazy and
the engine core never imports ``gitauth`` (the K0 boundary, subprocess-proven).

Features: FEAT-SERVER-006, FEAT-GITSYNC-003
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from typing import Any

import pytest

pytest.importorskip("cryptography", reason="the [server] extra is not installed")

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402

from custodex.errors import TransportError  # noqa: E402
from custodex.gitauth import (  # noqa: E402
    github_app_jwt,
    mint_gitlab_oauth_token,
    mint_provider_token,
)

_NOW = 1_750_000_000  # a fixed epoch (K10)


@pytest.fixture(scope="module")
def rsa_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


class _FakeExchange:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def request(
        self, method: str, url: str, *, body: dict | None, headers: dict[str, str]
    ) -> dict:
        self.calls.append(
            {"method": method, "url": url, "body": body, "headers": headers}
        )
        return self.response


def _b64url_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


# --------------------------------------------------------------------------- #
# github_app_jwt — a real, verifiable RS256 JWT.
# --------------------------------------------------------------------------- #


def test_github_app_jwt_is_verifiable_rs256(rsa_pem: str) -> None:
    jwt = github_app_jwt("123456", rsa_pem, now=_NOW)
    header_b64, payload_b64, sig_b64 = jwt.split(".")

    # the signature verifies against the key's PUBLIC half (RS256 over header.payload).
    pub = serialization.load_pem_private_key(
        rsa_pem.encode(), password=None
    ).public_key()
    pub.verify(
        _b64url_decode(sig_b64),
        f"{header_b64}.{payload_b64}".encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )  # raises InvalidSignature if wrong — no raise == verified

    header = json.loads(_b64url_decode(header_b64))
    payload = json.loads(_b64url_decode(payload_b64))
    assert header == {"alg": "RS256", "typ": "JWT"}
    assert payload["iss"] == "123456"
    assert payload["iat"] == _NOW - 60
    assert payload["exp"] == _NOW + 540


def test_github_app_jwt_loud_on_bad_pem() -> None:
    with pytest.raises(TransportError, match="private key"):
        github_app_jwt("1", "-----BEGIN nonsense-----", now=_NOW)


def test_github_app_jwt_loud_on_non_rsa_key() -> None:
    from cryptography.hazmat.primitives.asymmetric import ec

    ec_pem = (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode("ascii")
    )
    with pytest.raises(TransportError, match="RSA"):
        github_app_jwt("1", ec_pem, now=_NOW)


# --------------------------------------------------------------------------- #
# mint_provider_token — github-app dispatch (mint via the fake exchange).
# --------------------------------------------------------------------------- #


def test_mint_provider_token_github_app(rsa_pem: str) -> None:
    fake = _FakeExchange(
        {"token": "ghs_minted_xyz", "expires_at": "2026-06-10T01:00:00Z"}
    )
    material = json.dumps(
        {"app_id": "42", "installation_id": "99", "private_key_pem": rsa_pem}
    )
    token = mint_provider_token("github-app", material, now=_NOW, http=fake)
    assert token == "ghs_minted_xyz"
    # the JWT was POSTed as a Bearer to the installation access-tokens endpoint.
    (call,) = fake.calls
    assert call["method"] == "POST"
    assert call["url"].endswith("/app/installations/99/access_tokens")
    assert call["headers"]["Authorization"].startswith("Bearer ")


def test_mint_github_app_no_token_is_loud(rsa_pem: str) -> None:
    fake = _FakeExchange({})  # provider returned no token
    material = json.dumps(
        {"app_id": "1", "installation_id": "2", "private_key_pem": rsa_pem}
    )
    with pytest.raises(TransportError, match="no 'token'"):
        mint_provider_token("github-app", material, now=_NOW, http=fake)


def test_mint_github_app_honors_custom_api_url(rsa_pem: str) -> None:
    fake = _FakeExchange({"token": "t"})
    material = json.dumps(
        {
            "app_id": "1",
            "installation_id": "2",
            "private_key_pem": rsa_pem,
            "api_url": "https://ghe.corp/api/v3",
        }
    )
    mint_provider_token("github-app", material, now=_NOW, http=fake)
    assert fake.calls[0]["url"].startswith(
        "https://ghe.corp/api/v3/app/installations/2/"
    )


# --------------------------------------------------------------------------- #
# mint_provider_token — gitlab-oauth dispatch (refresh-token grant).
# --------------------------------------------------------------------------- #


def test_mint_provider_token_gitlab_oauth() -> None:
    fake = _FakeExchange({"access_token": "glpat-fresh", "token_type": "bearer"})
    material = json.dumps(
        {
            "token_url": "https://gitlab.com/oauth/token",
            "client_id": "cid",
            "client_secret": "csecret",
            "refresh_token": "r3fresh",
        }
    )
    token = mint_provider_token("gitlab-oauth", material, now=_NOW, http=fake)
    assert token == "glpat-fresh"
    body = fake.calls[0]["body"]
    assert body["grant_type"] == "refresh_token"
    assert body["refresh_token"] == "r3fresh"
    assert body["client_id"] == "cid"


def test_mint_gitlab_oauth_no_access_token_is_loud() -> None:
    with pytest.raises(TransportError, match="no 'access_token'"):
        mint_gitlab_oauth_token(
            "https://gitlab.com/oauth/token",
            client_id="c",
            client_secret="s",
            refresh_token="r",
            http=_FakeExchange({}),
        )


# --------------------------------------------------------------------------- #
# mint_provider_token — loud on a bad kind / malformed blob / missing field.
# --------------------------------------------------------------------------- #


def test_mint_provider_token_unknown_kind_is_loud(rsa_pem: str) -> None:
    with pytest.raises(TransportError, match="unknown provider_kind"):
        mint_provider_token("smoke-signals", "{}", now=_NOW, http=_FakeExchange({}))


def test_mint_provider_token_bad_json_is_loud() -> None:
    with pytest.raises(TransportError, match="not valid JSON"):
        mint_provider_token("github-app", "{not json", now=_NOW, http=_FakeExchange({}))


def test_mint_provider_token_missing_field_is_loud(rsa_pem: str) -> None:
    material = json.dumps(
        {"app_id": "1", "private_key_pem": rsa_pem}
    )  # no installation_id
    with pytest.raises(TransportError, match="missing field"):
        mint_provider_token("github-app", material, now=_NOW, http=_FakeExchange({}))


# --------------------------------------------------------------------------- #
# K0 boundary — the engine core never imports gitauth; cryptography stays lazy.
# --------------------------------------------------------------------------- #


def test_core_engine_does_not_import_gitauth() -> None:
    code = (
        "import sys, custodex.configsync, custodex.monitor, "
        "custodex.pr;"
        "assert 'custodex.gitauth' not in sys.modules"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_importing_gitauth_is_lazy_no_cryptography() -> None:
    code = "import sys, custodex.gitauth;assert 'cryptography' not in sys.modules"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
