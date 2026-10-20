"""Repo registration client — offline by default (K0, K4, K6, K8).

A repo announces itself to the central monitoring server (an explicit
``cdx register``) before/while reporting, sending its identity. This is
CLIENT-SIDE only: the server ``/repos`` endpoint is E-03, which consumes
:class:`RegistrationPayload` directly — ONE shared, versioned schema, no DTOs
(K6). :class:`RepoIdentity` is reused from :mod:`custodex.sinks` (the
same wire identity as :class:`~custodex.sinks.IngestEnvelope`), not a new
identity model.

Mirrors :mod:`custodex.sinks` / :mod:`custodex.pr`: the HTTP
transport is INJECTED (any object with a ``register`` method) so tests exercise a
fake and never touch the network (K4); when none is injected a stdlib-only
:class:`HttpRegisterTransport` is built lazily (no ``requests``, K0) whose single
real ``urlopen`` is the only ``# pragma: no cover`` leaf. A missing ``url`` /
``repo_id`` is a loud, typed :class:`SchemaError` (K8).
"""

from __future__ import annotations

import json
import os
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from .config import CentralConfig
from .errors import SchemaError
from .sinks import RepoIdentity

__all__ = [
    "RegistrationPayload",
    "RegisterTransport",
    "bearer_token_problem",
    "token_from_env",
    "HttpRegisterTransport",
    "HttpSyncTransport",
    "repo_identity_from_config",
    "register_repo",
    "sync_repo_remote",
]

# Frozen + extra="forbid": the registration payload is an immutable, audited wire
# artifact and an unexpected key is a loud error, not a silent pass (K6, K8).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

# SRV-TOKEN: the ONE bearer-token charset rule, applied wherever a bearer is SET.
# Part of it is forced: both server verifiers strip the presented bearer, so a
# padded token can never match, and HTTP clients cannot send CR/LF, NUL or
# characters outside latin-1, so such a token would lock the repo. The rest is
# POLICY: inner whitespace and other non-ASCII CAN be presented today, but are
# excluded so every token fits one RFC 6750-style grammar (printable ASCII, no
# whitespace). A validity rule, not a knob.
_BEARER_CHARSET = frozenset(chr(c) for c in range(0x21, 0x7F))
_BEARER_RULE = (
    "a bearer token must be printable ASCII with no whitespace (0x21-0x7E), "
    "e.g. `openssl rand -hex 32`"
)
# The dry-run mask for a write-only token (the same mask gitfetch redacts with).
_REDACTED = "***"


def bearer_token_problem(token: str) -> str | None:
    """Why ``token`` cannot be a bearer token, or ``None`` when it can (SRV-TOKEN).

    The shared rule for every place a bearer is SET: the admin reset route, the
    admin token at app build, :func:`token_from_env` and :func:`register_repo`.
    The phrase never quotes the token (it is a secret).
    """
    if not token.strip():
        return f"is empty (or only whitespace); {_BEARER_RULE}"
    if token != token.strip():
        return f"has leading/trailing whitespace; {_BEARER_RULE}"
    if not set(token) <= _BEARER_CHARSET:
        return f"contains whitespace, control or non-ASCII characters; {_BEARER_RULE}"
    return None


def token_from_env(var: str, *, what: str = "the bearer token") -> str:
    """Read a bearer token from ``$var``; loud :class:`SchemaError` if unusable (K8).

    Asking for a token must never degrade to an OPEN register, so an unset
    variable or one failing :func:`bearer_token_problem` raises, naming ``$var``
    but never its value.
    """
    value = os.environ.get(var)
    if value is None:
        raise SchemaError(f"{what} is read from ${var}, which is not set")
    problem = bearer_token_problem(value)
    if problem is not None:
        raise SchemaError(f"{what} in ${var} {problem}")
    return value


class RegistrationPayload(BaseModel):
    """The versioned client->server registration wire format (K6).

    Wraps a :class:`~custodex.sinks.RepoIdentity` with optional display
    fields. This is the ONE schema both this client and the E-03 ``/repos`` server
    use — no separate DTOs. ``schema_version`` is additive across versions (K6).
    """

    model_config = _MODEL_CONFIG

    schema_version: str = "1.0.0"
    repo: RepoIdentity
    default_branch: str | None = None
    description: str | None = None
    # Y-02 (ADDITIVE, K6): the repo's local filesystem path the central server
    # reads ``config/cdmon/`` + source from for a sync. Mirrors
    # :attr:`RepoIdentity.local_path` so a register call may carry it either on
    # the identity or at the top level; the server resolves it from the stored
    # identity. Default None keeps pre-Y-02 payloads valid.
    local_path: str | None = None
    # E-06 per-repo bearer auth (ADDITIVE, K6): a WRITE-ONLY plaintext token the
    # client mints at register. The server hashes it (sha256) onto the repo row and
    # NEVER stores or returns the plaintext (RegisteredRepo omits it; the stored
    # payload JSON is sanitized of it). Default None keeps pre-E-06 payloads valid and
    # leaves that repo's writes open. Appended LAST so field order is untouched.
    auth_token: str | None = None
    # GIT-02 per-repo PROVIDER credential (ADDITIVE, K6): a WRITE-ONLY plaintext git
    # PAT/project-token the client mints at register so the central server can clone
    # + open docs-PRs against this repo (EPIC GIT). Unlike ``auth_token`` (which the
    # server hashes — it is only ever COMPARED), a git credential must be REPLAYED,
    # so the server SEALS it at rest (AES-256-GCM, ``secrets.py``) and never stores
    # or returns the plaintext: it is excluded from the stored payload JSON and from
    # RegisteredRepo. Default None keeps pre-GIT-02 payloads valid (a repo synced
    # only by ``local_path`` carries no provider secret). Appended LAST.
    provider_secret: str | None = None


@runtime_checkable
class RegisterTransport(Protocol):
    """Something that can register a repo from a :class:`RegistrationPayload`."""

    def register(self, payload: RegistrationPayload) -> dict: ...


class _RegisterHttp(Protocol):
    """The injected HTTP leaf: one JSON request -> parsed JSON response."""

    def request(
        self, method: str, url: str, *, body: dict | None, token: str
    ) -> dict: ...


class _UrllibRegisterHttp:
    """A stdlib-only JSON client (no ``requests``, K0). Never used in tests."""

    def request(  # pragma: no cover — the real network leaf, never hit in tests (K4)
        self, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        import urllib.request

        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req) as resp:  # noqa: S310 (url from trusted config)
            raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


class HttpRegisterTransport:
    """POST a :class:`RegistrationPayload` to ``<url>/repos`` (K0, K4, K6).

    The HTTP ``http`` leaf is injected (any object with a ``request(method, url,
    *, body, token)`` method) so tests never hit the network. If ``http is None``
    at register time a stdlib-only :class:`_UrllibRegisterHttp` is built lazily
    (K0). The bearer token, when ``auth_env`` is set and present in the
    environment, is read at register time (the same env seam as
    :class:`~custodex.sinks.HttpSink`) so a rotated token is picked up
    without rebuilding.
    """

    def __init__(
        self,
        url: str,
        auth_env: str | None = None,
        *,
        http: _RegisterHttp | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._auth_env = auth_env
        self._http = http

    def register(self, payload: RegistrationPayload) -> dict:
        http = self._http
        if http is None:
            http = self._http = _UrllibRegisterHttp()
        token = ""
        if self._auth_env:
            token = os.environ.get(self._auth_env) or ""
        return http.request(
            "POST",
            f"{self._url}/repos",
            body=payload.model_dump(mode="json"),
            token=token,
        )


class HttpSyncTransport:
    """POST ``{mode}`` to ``<url>/repos/{repo_id}/sync`` (Y-03; K0, K4, K6, K8).

    The CLIENT side of the Y-02 ``POST /repos/{id}/sync`` route. It reuses the
    EXACT same stdlib HTTP+auth seam as :class:`HttpRegisterTransport` — the
    injected ``request(method, url, *, body, token)`` leaf (a lazily-built
    :class:`_UrllibRegisterHttp` when none is given, K0) and the bearer token read
    from ``auth_env`` at call time — so a remote ``cdx sync`` is mocked in tests
    identically to ``cdx register`` (no network, K4). The server replies with the
    :class:`~custodex.server.store.SyncRun` summary as JSON, returned
    verbatim.
    """

    def __init__(
        self,
        url: str,
        auth_env: str | None = None,
        *,
        http: _RegisterHttp | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._auth_env = auth_env
        self._http = http

    def sync(self, repo_id: str, *, mode: str) -> dict:
        http = self._http
        if http is None:
            http = self._http = _UrllibRegisterHttp()
        token = ""
        if self._auth_env:
            token = os.environ.get(self._auth_env) or ""
        return http.request(
            "POST",
            f"{self._url}/repos/{repo_id}/sync",
            body={"mode": mode},
            token=token,
        )


def sync_repo_remote(
    repo_id: str,
    *,
    mode: str,
    url: str,
    auth_env: str | None = None,
    transport: HttpSyncTransport | None = None,
) -> dict:
    """Trigger a remote config sync for ``repo_id`` and return the run summary.

    POSTs ``{mode}`` to ``<url>/repos/{repo_id}/sync`` through the INJECTED
    ``transport`` — or, when ``transport is None``, a default
    :class:`HttpSyncTransport` built from ``url``/``auth_env`` (reusing the
    register HTTP+auth seam, K0/K4) — and returns the server's
    :class:`~custodex.server.store.SyncRun` JSON. A missing/empty ``url``
    is a loud, typed :class:`SchemaError` (K8).
    """
    if transport is None:
        if not url:
            raise SchemaError(
                "a remote sync requires a central 'url' — pass --remote URL"
            )
        transport = HttpSyncTransport(url, auth_env)
    return transport.sync(repo_id, mode=mode)


def repo_identity_from_config(cfg: CentralConfig) -> RepoIdentity:
    """Build a :class:`RepoIdentity` from a central config; loud if ``repo_id`` is
    missing (K8).

    The SHARED identity build (de-dups :func:`custodex.sinks.make_sink`):
    ``repo_id``/``repo_name``/``repo_url`` from config plus ``commit`` from
    ``cfg.repo_commit`` else the CI-injected ``$CI_COMMIT_SHA``. A repo cannot be
    registered (or report records) anonymously, so a missing ``repo_id`` is a
    loud, typed :class:`SchemaError`.
    """
    if not cfg.repo_id:
        raise SchemaError(
            "repo registration requires a 'repo_id' (which repo is announcing "
            "itself) — set central.repo_id in the config"
        )
    commit = cfg.repo_commit or os.environ.get("CI_COMMIT_SHA")
    return RepoIdentity(
        repo_id=cfg.repo_id,
        repo_name=cfg.repo_name,
        repo_url=cfg.repo_url,
        commit=commit,
    )


def register_repo(
    identity: RepoIdentity,
    *,
    url: str,
    auth_env: str | None = None,
    transport: RegisterTransport | None = None,
    dry_run: bool = False,
    default_branch: str | None = None,
    description: str | None = None,
    auth_token: str | None = None,
    rotate: bool = False,
) -> dict | None:
    """Register ``identity`` with the central server; return its response.

    Builds a deterministic :class:`RegistrationPayload`. ``dry_run`` returns the
    payload as a dict WITHOUT calling the transport (so no url/env is required to
    inspect what would be sent). Otherwise the payload is submitted via the
    INJECTED ``transport`` — or, when ``transport is None``, a default
    :class:`HttpRegisterTransport` built from ``url``/``auth_env`` (lazily building
    its stdlib leaf, K0) — and the server response is returned. A missing/empty
    ``url`` on the real submit path is a loud, typed :class:`SchemaError` (K8).

    SRV-TOKEN: ``auth_token`` registers the repo token-protected; ``rotate=True``
    rotates it to ``auth_token`` while the transport presents the CURRENT token
    from ``$auth_env``. When ``$auth_env`` already holds ``auth_token`` the
    rotation is done, and the call is an ordinary protected re-register (K7).
    :func:`_check_token_request` refuses an unusable request BEFORE anything is
    sent (a dry run too). A dry run shows the token as ``***``.
    Every register re-sends the whole registration (fields left unset reset).
    """
    _check_token_request(
        auth_env=auth_env,
        auth_token=auth_token,
        rotate=rotate,
        default_transport=transport is None,
    )
    payload = RegistrationPayload(
        repo=identity,
        default_branch=default_branch,
        description=description,
        auth_token=auth_token,
    )
    if dry_run:
        shown = payload.model_dump(mode="json")
        if shown["auth_token"] is not None:
            shown["auth_token"] = _REDACTED
        return shown
    if transport is None:
        if not url:
            raise SchemaError(
                "repo registration requires a central 'url' — set central.url "
                "in the config"
            )
        transport = HttpRegisterTransport(url, auth_env)
    return transport.register(payload)


def _check_token_request(
    *,
    auth_env: str | None,
    auth_token: str | None,
    rotate: bool,
    default_transport: bool,
) -> None:
    """Refuse a token register/rotation that cannot work, before sending (K8).

    - a supplied ``auth_token`` must pass :func:`bearer_token_problem`;
    - a rotation needs the new token and a configured ``auth_env`` whose value is
      a usable CURRENT bearer. When that bearer already IS the new token, the
      rotation has happened and this is a plain protected re-register (K7: a
      re-run converges; the server still verifies that bearer);
    - a protected register through the DEFAULT transport needs ``$auth_env`` to
      hold EXACTLY ``auth_token`` (no stripping): the next register and the http
      sink present ``$auth_env``, so anything else locks the repo out of its own
      writes. An injected transport owns its bearer, so it is not checked.
    """
    if auth_token is not None:
        problem = bearer_token_problem(auth_token)
        if problem is not None:
            raise SchemaError(f"the new repo token {problem}")
    if rotate:
        if auth_token is None:
            raise SchemaError("a token rotation needs the new token (auth_token)")
        if not auth_env:
            raise SchemaError(
                "a token rotation presents the repo's current token from "
                "central.auth_env, which is not configured — set central.auth_env "
                "to the variable holding the current token"
            )
        token_from_env(auth_env, what="the current repo token (central.auth_env)")
        return
    if auth_token is None or not default_transport:
        return
    lockout = "a token-protected register would lock the repo out of its own writes"
    if not auth_env:
        raise SchemaError(
            f"{lockout}: the next register and the http sink present the bearer "
            "from central.auth_env, which is not configured — set central.auth_env "
            "to the variable holding this token"
        )
    held = os.environ.get(auth_env)
    if held == auth_token:
        return
    if held is None:
        why = "which is not set"
    else:
        problem = bearer_token_problem(held)
        why = (
            f"which {problem}"
            if problem is not None
            else ("which holds a different token")
        )
    raise SchemaError(
        f"{lockout}: the next register and the http sink present the bearer from "
        f"${auth_env} (central.auth_env), {why}. For a NEW repo, put this token "
        f"in ${auth_env} and register with --auth-token-env {auth_env}; to CHANGE "
        f"an already-protected repo's token, keep its CURRENT token in "
        f"${auth_env} and rotate instead with --rotate-to-env VAR (VAR holding "
        "the new token)"
    )
