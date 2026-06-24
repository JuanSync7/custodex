"""Short-lived provider-token minting — GitHub App / GitLab OAuth (GIT-05, PHASE 2).

PHASE 1 stores a per-repo PAT sealed at rest and replays it. PHASE 2 stores a
LONGER-LIVED credential (a GitHub App private key, or a GitLab OAuth refresh
token) and mints a SHORT-LIVED access token from it on each operation — so the hot
token is never persisted (recovering most of the at-rest invariant PHASE 1
weakened). The minted token is just a string, so the existing
``{GitHub,GitLab}Transport.from_repo(remote_url, token)`` + the
:mod:`custodex.gitfetch` clone seam are reused VERBATIM — only the
credential SOURCE changes (a mint step before the token is used).

* **GitHub App** — sign a short RS256 JWT with the App private key (``iss`` = the
  App id), then exchange it at ``POST /app/installations/{id}/access_tokens`` for
  an installation token. RS256 is the one thing the stdlib CANNOT do, so this is
  the single use of ``cryptography`` beyond :mod:`custodex.secrets` — lazy
  imported, behind the ``[server]`` extra, never pulled by the engine core (K0).
* **GitLab OAuth** — exchange a refresh token at the OAuth ``token`` endpoint for a
  fresh access token (a plain stdlib JSON POST — no crypto).

The HTTP exchange is one INJECTED leaf (:class:`_TokenExchangeHttp`, K4); tests
drive a fake and a generated test RSA key, so no network and no real provider are
touched. The clock (``now`` epoch seconds) is injected for the JWT ``iat``/``exp``
(K10). Every failure is a loud :class:`~custodex.errors.TransportError` (K8).
"""

from __future__ import annotations

import base64
import json
from typing import Protocol

from .errors import TransportError

__all__ = [
    "github_app_jwt",
    "mint_github_installation_token",
    "mint_gitlab_oauth_token",
    "mint_provider_token",
]

# GitHub caps the App JWT lifetime at 10 minutes; use 9 to allow clock skew.
_JWT_TTL_SECONDS = 540
_JWT_BACKDATE_SECONDS = 60  # iat slightly in the past to tolerate skew


class _TokenExchangeHttp(Protocol):
    """The injected token-exchange leaf: one JSON request → parsed JSON response.

    Distinct from the PR/register leaves (which take a bearer ``token`` kwarg)
    because the exchange auth varies by provider (a JWT for GitHub, a form/JSON
    grant for GitLab) — so the caller passes the full ``headers``.
    """

    def request(
        self, method: str, url: str, *, body: dict | None, headers: dict[str, str]
    ) -> dict: ...


class _UrllibTokenExchangeHttp:
    """A stdlib-only token-exchange client (no ``requests``, K0). Not used in tests."""

    def request(
        self, method: str, url: str, *, body: dict | None, headers: dict[str, str]
    ) -> dict:
        import urllib.request  # pragma: no cover

        data = (  # pragma: no cover
            json.dumps(body).encode("utf-8") if body is not None else None
        )
        req = urllib.request.Request(  # pragma: no cover
            url, data=data, headers=headers, method=method
        )
        with urllib.request.urlopen(req) as resp:  # noqa: S310  # pragma: no cover
            raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}  # pragma: no cover


def _b64url(raw: bytes) -> str:
    """Base64url WITHOUT padding (the JWT segment encoding)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def github_app_jwt(app_id: str, private_key_pem: str, *, now: int) -> str:
    """A short RS256 JWT for a GitHub App (``iss`` = ``app_id``), signed with the PEM.

    ``now`` (epoch seconds, injected — K10) sets ``iat`` (back-dated 60s for skew)
    and ``exp`` (+9 min). RS256 signing uses ``cryptography`` (lazy, the K0
    asterisk). The result is ``base64url(header).base64url(payload).base64url(sig)``.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iat": now - _JWT_BACKDATE_SECONDS,
        "exp": now + _JWT_TTL_SECONDS,
        "iss": app_id,
    }
    header_seg = _b64url(json.dumps(header).encode("utf-8"))
    payload_seg = _b64url(json.dumps(payload).encode("utf-8"))
    signing_input = f"{header_seg}.{payload_seg}"
    try:
        key = serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"), password=None
        )
    except (ValueError, TypeError) as exc:
        raise TransportError(f"invalid GitHub App private key: {exc}") from exc
    if not isinstance(key, RSAPrivateKey):  # RS256 requires an RSA key (K8)
        raise TransportError("GitHub App private key must be an RSA key (RS256)")
    signature = key.sign(
        signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256()
    )
    return f"{signing_input}.{_b64url(signature)}"


def mint_github_installation_token(
    app_id: str,
    private_key_pem: str,
    installation_id: str,
    *,
    now: int,
    http: _TokenExchangeHttp | None = None,
    api_url: str = "https://api.github.com",
) -> str:
    """Mint a short-lived GitHub App INSTALLATION token (loud on a bad exchange, K8)."""
    jwt = github_app_jwt(app_id, private_key_pem, now=now)
    client = http if http is not None else _UrllibTokenExchangeHttp()
    resp = client.request(
        "POST",
        f"{api_url.rstrip('/')}/app/installations/{installation_id}/access_tokens",
        body=None,
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/vnd.github+json",
        },
    )
    token = resp.get("token")
    if not token:
        raise TransportError("GitHub installation token exchange returned no 'token'")
    return str(token)


def mint_gitlab_oauth_token(
    token_url: str,
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    http: _TokenExchangeHttp | None = None,
) -> str:
    """Exchange a GitLab OAuth refresh token for a fresh access token (loud, K8)."""
    client = http if http is not None else _UrllibTokenExchangeHttp()
    resp = client.request(
        "POST",
        token_url,
        body={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        headers={"Content-Type": "application/json"},
    )
    token = resp.get("access_token")
    if not token:
        raise TransportError("GitLab OAuth exchange returned no 'access_token'")
    return str(token)


def mint_provider_token(
    provider_kind: str,
    secret_material: str,
    *,
    now: int,
    http: _TokenExchangeHttp | None = None,
) -> str:
    """Mint a short-lived token from a sealed credential blob, by ``provider_kind``.

    ``secret_material`` is the opened (decrypted) credential — a JSON object whose
    shape depends on ``provider_kind``: ``github-app`` →
    ``{app_id, installation_id, private_key_pem, api_url?}``; ``gitlab-oauth`` →
    ``{token_url, client_id, client_secret, refresh_token}``. An unknown kind or a
    malformed blob is a loud :class:`TransportError` (K8). (``"token"``/None is NOT
    handled here — the route uses the opened secret directly for the PHASE-1 path.)
    """
    try:
        cred = json.loads(secret_material)
    except (ValueError, TypeError) as exc:
        raise TransportError(
            f"provider credential for {provider_kind!r} is not valid JSON"
        ) from exc
    try:
        if provider_kind == "github-app":
            return mint_github_installation_token(
                cred["app_id"],
                cred["private_key_pem"],
                cred["installation_id"],
                now=now,
                http=http,
                api_url=cred.get("api_url", "https://api.github.com"),
            )
        if provider_kind == "gitlab-oauth":
            return mint_gitlab_oauth_token(
                cred["token_url"],
                client_id=cred["client_id"],
                client_secret=cred["client_secret"],
                refresh_token=cred["refresh_token"],
                http=http,
            )
    except KeyError as exc:
        raise TransportError(
            f"provider credential for {provider_kind!r} is missing field {exc}"
        ) from exc
    raise TransportError(f"unknown provider_kind for token minting: {provider_kind!r}")
