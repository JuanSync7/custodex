"""EPIC SVR (SVR-02/03) — the settings-driven server hardening over the real app.

GET /settings (redacted), CORS / TrustedHost / rate-limit middleware (each added
ONLY when configured so the default app is unchanged), the git SSRF allowlist driven
by settings, and the de-duplicated app version. Fully offline (K4), no socket bound.

Features: FEAT-SETTINGS-004, FEAT-SETTINGS-005, FEAT-SETTINGS-006, FEAT-SETTINGS-007
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from code_doc_monitor.server import app as app_mod  # noqa: E402
from code_doc_monitor.server import create_app  # noqa: E402
from code_doc_monitor.settings import (  # noqa: E402
    CorsSettings,
    GitSettings,
    RateLimitSettings,
    ServerSettings,
    Settings,
)

_FIXED_CLOCK = "2026-06-22T00:00:00+00:00"

_CDMON_ENV = (
    "CDMON_SERVER_HOST",
    "CDMON_SERVER_PORT",
    "CDMON_SERVER_LOG_LEVEL",
    "CDMON_TRUSTED_HOSTS",
    "CDMON_CORS_ORIGINS",
    "CDMON_RATE_LIMIT_RPM",
    "CDMON_ALLOWED_GIT_HOSTS",
    "CDMON_GIT_CLONE_TIMEOUT",
    "CDMON_ADMIN_TOKEN",
    "CDMON_DATABASE_URL",
    "CDMON_SECRET_KEY",
)


@pytest.fixture(autouse=True)
def _hermetic_cdmon_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip the settings/secret CDMON_* env so baseline assertions hold regardless of
    the host (K10); a test that needs one sets it via its own monkeypatch afterward."""
    for name in _CDMON_ENV:
        monkeypatch.delenv(name, raising=False)


# ── GET /settings (open read, redacted) ──────────────────────────────────────


def test_settings_endpoint_reports_settings_and_secret_presence() -> None:
    client = TestClient(create_app(settings=Settings()))
    body = client.get("/settings").json()
    assert body["settings"]["server"]["port"] == 33333
    assert body["settings"]["server"]["host"] == "0.0.0.0"
    assert set(body["secrets"]) == {
        "admin_token_configured",
        "database_url_set",
        "secret_key_set",
    }
    assert body["secrets"] == {
        "admin_token_configured": False,
        "database_url_set": False,
        "secret_key_set": False,
    }


def test_settings_endpoint_never_leaks_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CDMON_ADMIN_TOKEN", "tok-SUPERSECRET")
    monkeypatch.setenv("CDMON_DATABASE_URL", "postgresql://u:PWSECRET@h/db")
    monkeypatch.setenv("CDMON_SECRET_KEY", "KEKSECRET")
    client = TestClient(create_app(settings=Settings()))
    resp = client.get("/settings")
    raw = json.dumps(resp.json())
    # presence flips True, but NONE of the actual secret material appears on the wire
    assert resp.json()["secrets"] == {
        "admin_token_configured": True,
        "database_url_set": True,
        "secret_key_set": True,
    }
    for secret in ("SUPERSECRET", "PWSECRET", "KEKSECRET"):
        assert secret not in raw


# ── middleware added only when configured (default app unchanged) ────────────


def test_default_app_has_no_hardening_middleware() -> None:
    # back-compat: with default settings, none of the SVR middleware is installed.
    app = create_app(settings=Settings())
    names = {m.cls.__name__ for m in app.user_middleware}
    assert "TrustedHostMiddleware" not in names
    assert "CORSMiddleware" not in names
    assert "_RateLimitMiddleware" not in names


def test_trusted_host_allows_listed_rejects_others() -> None:
    s = Settings(server=ServerSettings(trusted_hosts=("good.example.com",)))
    client = TestClient(create_app(settings=s))
    assert (
        client.get("/health", headers={"host": "good.example.com"}).status_code == 200
    )
    assert (
        client.get("/health", headers={"host": "evil.example.com"}).status_code == 400
    )


def test_cors_preflight_only_when_configured() -> None:
    # no CORS by default
    plain = TestClient(create_app(settings=Settings()))
    pre0 = plain.options(
        "/health",
        headers={"Origin": "https://app.x", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in pre0.headers
    # enabled when origins listed
    s = Settings(
        server=ServerSettings(cors=CorsSettings(allow_origins=("https://app.x",)))
    )
    cors = TestClient(create_app(settings=s))
    pre = cors.options(
        "/health",
        headers={"Origin": "https://app.x", "Access-Control-Request-Method": "GET"},
    )
    assert pre.headers.get("access-control-allow-origin") == "https://app.x"


def test_rate_limit_429_after_the_cap() -> None:
    s = Settings(
        server=ServerSettings(rate_limit=RateLimitSettings(requests_per_minute=2))
    )
    # a fixed clock pins all requests into ONE window so the cap is deterministic (K10)
    client = TestClient(create_app(settings=s, clock=lambda: _FIXED_CLOCK))
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 429  # over the cap


# ── git SSRF allowlist driven by settings ────────────────────────────────────


def test_allowlist_from_settings_overrides_baseline() -> None:
    git = GitSettings(extra_allowed_hosts=("ghe.corp.io",))
    hosts = app_mod._allowed_git_hosts(git)
    assert hosts == {"github.com", "gitlab.com", "ghe.corp.io"}
    # an allowlisted host passes; an unlisted one is a loud 400
    app_mod._check_remote_allowed("https://ghe.corp.io/team/proj.git", git=git)
    with pytest.raises(HTTPException):
        app_mod._check_remote_allowed("https://internal.evil/x.git", git=git)


def test_file_scheme_can_be_disabled_by_settings() -> None:
    # default allows file://; settings can forbid it for a shared deployment
    app_mod._check_remote_allowed("file:///srv/mirror/x.git")  # back-compat: allowed
    forbid = GitSettings(allow_file_scheme=False)
    with pytest.raises(HTTPException):
        app_mod._check_remote_allowed("file:///srv/mirror/x.git", git=forbid)


# ── app version de-duplicated (was hardcoded "0.1.0" in two places) ──────────


def test_app_version_is_single_sourced() -> None:
    version = app_mod._app_version()
    app = create_app(settings=Settings())
    assert app.version == version
    landing = TestClient(create_app(settings=Settings())).get("/").json()
    assert landing["version"] == version
