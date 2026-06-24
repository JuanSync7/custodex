"""Operator runtime settings for the central server + standalone serve (K0, K8, K10).

The deployment tunables that used to be hardcoded at the uvicorn leaf (host, port,
log level) plus the hardening knobs that had no home (CORS origins, trusted hosts,
a request rate limit, the git clone timeout and the SSRF host allowlist) live here
in one frozen, versioned model loaded from ``config/settings.yaml``.

This module is CORE — it imports only ``pydantic`` + ``pyyaml`` + stdlib, so
``import custodex`` stays minimal (K0); the ``[server]`` app imports it and
wires the values into FastAPI middleware + the uvicorn launch. SECRETS are NOT
modelled here: the admin token, the database URL and the KEK stay in the environment
(``$CDMON_*``); only their PRESENCE is ever surfaced (:func:`secret_presence`).

Every field defaults to today's behavior, so an absent ``settings.yaml`` is a no-op
(back-compat, K6). Malformed input is a loud :class:`ConfigError` (K8); resolution is
deterministic and clock-free (K10).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .errors import ConfigError

__all__ = [
    "CorsSettings",
    "RateLimitSettings",
    "GitSettings",
    "ServerSettings",
    "Settings",
    "DEFAULT_SETTINGS_PATH",
    "load_settings",
    "settings_from_env",
    "resolve_settings",
    "secret_presence",
]

_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

# config/settings.yaml sits ALONGSIDE config/cdmon/ (never inside it — a stray .yaml
# in config/cdmon/ would be scanned as a coverage unit and trip a loud load error).
DEFAULT_SETTINGS_PATH = Path("config/settings.yaml")


class CorsSettings(BaseModel):
    """Cross-origin policy. An empty ``allow_origins`` == CORS middleware OFF (today's
    same-origin-only behavior); list origins to enable a separately-hosted frontend."""

    model_config = _MODEL_CONFIG

    allow_origins: tuple[str, ...] = ()
    allow_credentials: bool = False
    allow_methods: tuple[str, ...] = ("*",)
    allow_headers: tuple[str, ...] = ("*",)


class RateLimitSettings(BaseModel):
    """A per-process, per-client fixed-window request cap. ``None`` == no limit (today).
    NOT distributed: with N workers the effective limit is N× (see DEPLOY.md)."""

    model_config = _MODEL_CONFIG

    requests_per_minute: int | None = None

    @model_validator(mode="after")
    def _positive(self) -> RateLimitSettings:
        if self.requests_per_minute is not None and self.requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be a positive integer or null")
        return self


class GitSettings(BaseModel):
    """The clone-on-demand / docs-PR SSRF allowlist + clone hardening. Defaults match
    today's ``_check_remote_allowed`` (https to github.com/gitlab.com + ``file://``)."""

    model_config = _MODEL_CONFIG

    allowed_hosts: tuple[str, ...] = ("github.com", "gitlab.com")
    extra_allowed_hosts: tuple[str, ...] = ()  # $CDMON_ALLOWED_GIT_HOSTS overlays here
    allow_file_scheme: bool = True
    clone_timeout_seconds: int | None = None  # None == no timeout (today); a hang guard

    @model_validator(mode="after")
    def _timeout_positive(self) -> GitSettings:
        if self.clone_timeout_seconds is not None and self.clone_timeout_seconds <= 0:
            raise ValueError("clone_timeout_seconds must be a positive integer or null")
        return self


class ServerSettings(BaseModel):
    """The uvicorn launch + HTTP hardening knobs (defaults == the central server today:
    bind 0.0.0.0:33333, no CORS, TrustedHost off via ``["*"]``, no rate limit)."""

    model_config = _MODEL_CONFIG

    host: str = "0.0.0.0"  # central uvicorn bind (was app.py main())
    port: int = 33333  # central uvicorn port (was app.py main())
    log_level: str = "info"  # uvicorn log level
    trusted_hosts: tuple[str, ...] = ("*",)  # ["*"] == TrustedHost middleware OFF
    cors: CorsSettings = CorsSettings()
    rate_limit: RateLimitSettings = RateLimitSettings()
    git: GitSettings = GitSettings()

    @model_validator(mode="after")
    def _host_port_valid(self) -> ServerSettings:
        if not self.host:
            raise ValueError("host must be non-empty")
        if not (0 <= self.port <= 65535):  # 0 == let the OS pick (cdx serve)
            raise ValueError(f"port must be 0..65535, got {self.port}")
        return self


class Settings(BaseModel):
    """The top-level settings document (versioned + additive, K6)."""

    model_config = _MODEL_CONFIG

    version: str = "1.0.0"
    server: ServerSettings = ServerSettings()


def load_settings(path: Path) -> Settings:
    """Load + validate the settings YAML; any failure is a loud ConfigError (K8)."""
    if path.suffix.lower() not in (".yaml", ".yml"):
        raise ConfigError(
            f"Unsupported settings suffix {path.suffix!r} for {path}: use .yaml or .yml"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Cannot read settings file {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Malformed settings file {path}: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"Settings file {path} must contain a mapping at the top level, "
            f"got {type(data).__name__}"
        )
    try:
        return Settings(**data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid settings in {path}:\n{exc}") from exc


def _csv(value: str, name: str) -> list[str]:
    """Parse a comma-separated env value into a stripped, non-empty list.

    A non-empty env value that parses to NO items (e.g. ``","`` or ``" "``) is operator
    error — silently yielding ``[]`` could brick the server (an empty ``trusted_hosts``
    rejects every Host), so it is a loud :class:`ConfigError` (K8).
    """
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        raise ConfigError(f"{name} has no values after splitting on ',': {value!r}")
    return parts


def _int(value: str, name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from exc


def settings_from_env(base: Settings, env: Mapping[str, str] | None = None) -> Settings:
    """Overlay env vars onto a loaded :class:`Settings` (env wins over the file).

    Injectable ``env`` so tests pass a plain dict and never touch the real environment
    (K10). Only NON-secret tunables are overridable here; the secrets
    (``$CDMON_ADMIN_TOKEN`` / ``$CDMON_DATABASE_URL`` / ``$CDMON_SECRET_KEY``) are
    resolved by the server directly and are never modelled. Reconstructs through the
    constructor so validators re-run (``model_copy`` would skip them); a bad value is a
    loud :class:`ConfigError` (K8).
    """
    source = os.environ if env is None else env
    data = base.model_dump()
    srv = data["server"]

    if value := source.get("CDMON_SERVER_HOST"):
        srv["host"] = value
    if value := source.get("CDMON_SERVER_PORT"):
        srv["port"] = _int(value, "CDMON_SERVER_PORT")
    if value := source.get("CDMON_SERVER_LOG_LEVEL"):
        srv["log_level"] = value
    if value := source.get("CDMON_TRUSTED_HOSTS"):
        srv["trusted_hosts"] = _csv(value, "CDMON_TRUSTED_HOSTS")
    if value := source.get("CDMON_CORS_ORIGINS"):
        srv["cors"]["allow_origins"] = _csv(value, "CDMON_CORS_ORIGINS")
    if value := source.get("CDMON_RATE_LIMIT_RPM"):
        srv["rate_limit"]["requests_per_minute"] = _int(value, "CDMON_RATE_LIMIT_RPM")
    if value := source.get("CDMON_ALLOWED_GIT_HOSTS"):
        srv["git"]["extra_allowed_hosts"] = _csv(value, "CDMON_ALLOWED_GIT_HOSTS")
    if value := source.get("CDMON_GIT_CLONE_TIMEOUT"):
        srv["git"]["clone_timeout_seconds"] = _int(value, "CDMON_GIT_CLONE_TIMEOUT")

    try:
        return Settings(**data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid settings from environment:\n{exc}") from exc


def resolve_settings(
    path: Path = DEFAULT_SETTINGS_PATH, env: Mapping[str, str] | None = None
) -> Settings:
    """The server/CLI entrypoint: file (if present) → env overlay → built-in defaults.

    An absent ``settings.yaml`` is not an error — it resolves to the defaults (which
    reproduce today's behavior), with env still overlaid. Deterministic (K10).
    """
    base = load_settings(path) if Path(path).is_file() else Settings()
    return settings_from_env(base, env)


def secret_presence(env: Mapping[str, str] | None = None) -> dict[str, bool]:
    """Report only the PRESENCE of the environment secrets — never their values (K8).

    Surfaced alongside the settings so an operator can confirm the admin token / DB
    URL / KEK are configured without the wire ever carrying the secret.
    """
    source = os.environ if env is None else env
    return {
        "admin_token_configured": bool(source.get("CDMON_ADMIN_TOKEN")),
        "database_url_set": bool(source.get("CDMON_DATABASE_URL")),
        "secret_key_set": bool(source.get("CDMON_SECRET_KEY")),
    }
