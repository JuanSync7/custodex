"""EPIC SVR (SVR-01) — operator runtime settings model + loader + env overlay.

Pure, offline, deterministic (K10): defaults reproduce today's server behavior
(back-compat, K6), malformed input is a loud ConfigError (K8), env overrides the file
(env wins), and SECRETS are never modelled — only their presence is reported.

Features: FEAT-SETTINGS-001, FEAT-SETTINGS-002, FEAT-SETTINGS-003
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from custodex.errors import ConfigError
from custodex.settings import (
    DEFAULT_SETTINGS_PATH,
    Settings,
    load_settings,
    resolve_settings,
    secret_presence,
    settings_from_env,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_SETTINGS = _REPO_ROOT / "config" / "settings.yaml"


# ── defaults reproduce today's behavior (back-compat) ────────────────────────


def test_defaults_match_todays_server_behavior() -> None:
    s = Settings()
    assert (s.server.host, s.server.port) == ("0.0.0.0", 33333)
    assert s.server.log_level == "info"
    assert s.server.trusted_hosts == ("*",)  # TrustedHost OFF
    assert s.server.cors.allow_origins == ()  # CORS OFF
    assert s.server.rate_limit.requests_per_minute is None  # no limit
    assert s.server.git.allowed_hosts == ("github.com", "gitlab.com")
    assert s.server.git.allow_file_scheme is True
    assert s.server.git.clone_timeout_seconds is None
    assert s.version == "1.0.0"


def test_models_are_frozen_and_forbid_extra() -> None:
    s = Settings()
    with pytest.raises(ValidationError):  # frozen — assignment is rejected
        s.server.host = "10.0.0.1"  # type: ignore[misc]
    with pytest.raises(ValidationError):  # extra="forbid"
        Settings(server={"bogus": 1})


# ── the shipped config/settings.yaml round-trips to the defaults ─────────────


def test_repo_settings_file_loads_and_equals_defaults() -> None:
    """The committed config/settings.yaml must encode exactly the built-in defaults,
    so an operator who never touches it gets identical behavior."""
    assert _REPO_SETTINGS.is_file(), _REPO_SETTINGS
    loaded = load_settings(_REPO_SETTINGS)
    assert loaded == Settings()


# ── loud on malformed input (K8) ─────────────────────────────────────────────


def test_unsupported_suffix_is_loud(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigError, match="Unsupported settings suffix"):
        load_settings(p)


def test_missing_file_is_loud(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Cannot read settings file"):
        load_settings(tmp_path / "nope.yaml")


def test_malformed_yaml_is_loud(tmp_path: Path) -> None:
    p = tmp_path / "settings.yaml"
    p.write_text("server: {host: :", encoding="utf-8")
    with pytest.raises(ConfigError, match="Malformed settings file"):
        load_settings(p)


def test_non_mapping_top_level_is_loud(tmp_path: Path) -> None:
    p = tmp_path / "settings.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must contain a mapping"):
        load_settings(p)


def test_unknown_key_is_loud(tmp_path: Path) -> None:
    p = tmp_path / "settings.yaml"
    p.write_text("server:\n  prt: 9000\n", encoding="utf-8")  # typo'd key
    with pytest.raises(ConfigError, match="Invalid settings"):
        load_settings(p)


@pytest.mark.parametrize(
    "body",
    [
        "server:\n  port: 70000\n",  # out of range
        "server:\n  host: ''\n",  # empty host
        "server:\n  rate_limit:\n    requests_per_minute: 0\n",  # not positive
        "server:\n  git:\n    clone_timeout_seconds: -3\n",  # not positive
    ],
)
def test_invalid_values_are_loud(tmp_path: Path, body: str) -> None:
    p = tmp_path / "settings.yaml"
    p.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid settings"):
        load_settings(p)


def test_empty_file_is_defaults(tmp_path: Path) -> None:
    p = tmp_path / "settings.yaml"
    p.write_text("", encoding="utf-8")
    assert load_settings(p) == Settings()


# ── env overlay (env wins; injectable; loud on bad value) ────────────────────


def test_env_overrides_file_values() -> None:
    base = Settings()
    env = {
        "CDMON_SERVER_HOST": "127.0.0.1",
        "CDMON_SERVER_PORT": "8080",
        "CDMON_SERVER_LOG_LEVEL": "warning",
        "CDMON_TRUSTED_HOSTS": "cdmon.example.com, localhost",
        "CDMON_CORS_ORIGINS": "https://app.example.com",
        "CDMON_RATE_LIMIT_RPM": "120",
        "CDMON_ALLOWED_GIT_HOSTS": "ghe.corp.io , gitlab.corp.io",
        "CDMON_GIT_CLONE_TIMEOUT": "30",
    }
    s = settings_from_env(base, env)
    assert (s.server.host, s.server.port) == ("127.0.0.1", 8080)
    assert s.server.log_level == "warning"
    assert s.server.trusted_hosts == ("cdmon.example.com", "localhost")
    assert s.server.cors.allow_origins == ("https://app.example.com",)
    assert s.server.rate_limit.requests_per_minute == 120
    assert s.server.git.extra_allowed_hosts == ("ghe.corp.io", "gitlab.corp.io")
    assert s.server.git.clone_timeout_seconds == 30


def test_env_empty_or_absent_is_a_noop() -> None:
    base = Settings()
    assert settings_from_env(base, {}) == base
    assert settings_from_env(base, {"CDMON_SERVER_HOST": ""}) == base  # empty == unset


def test_env_bad_int_is_loud() -> None:
    with pytest.raises(ConfigError, match="CDMON_SERVER_PORT must be an integer"):
        settings_from_env(Settings(), {"CDMON_SERVER_PORT": "notaport"})


def test_env_value_is_revalidated() -> None:
    # an env-supplied port out of range must still trip the model validator (K8)
    with pytest.raises(ConfigError, match="Invalid settings from environment"):
        settings_from_env(Settings(), {"CDMON_SERVER_PORT": "99999"})


# ── resolve_settings: file → env → defaults ──────────────────────────────────


def test_resolve_absent_file_is_defaults(tmp_path: Path) -> None:
    assert resolve_settings(tmp_path / "absent.yaml", env={}) == Settings()


def test_resolve_layers_file_then_env(tmp_path: Path) -> None:
    p = tmp_path / "settings.yaml"
    p.write_text("server:\n  port: 5000\n  log_level: debug\n", encoding="utf-8")
    # file sets port=5000, log_level=debug; env overrides port to 6000
    s = resolve_settings(p, env={"CDMON_SERVER_PORT": "6000"})
    assert s.server.port == 6000  # env wins
    assert s.server.log_level == "debug"  # from file


def test_default_settings_path_is_under_config() -> None:
    assert str(DEFAULT_SETTINGS_PATH) == "config/settings.yaml"


# ── secret presence (never the value) ────────────────────────────────────────


def test_secret_presence_reports_only_booleans() -> None:
    assert secret_presence({}) == {
        "admin_token_configured": False,
        "database_url_set": False,
        "secret_key_set": False,
    }
    present = secret_presence(
        {
            "CDMON_ADMIN_TOKEN": "s3cret",
            "CDMON_DATABASE_URL": "postgresql://u:p@h/db",
            "CDMON_SECRET_KEY": "key",
        }
    )
    assert present == {
        "admin_token_configured": True,
        "database_url_set": True,
        "secret_key_set": True,
    }
    # the actual secret values never appear in the presence report
    assert "s3cret" not in str(present)


def test_non_utf8_file_is_loud(tmp_path: Path) -> None:
    # a mis-encoded settings file is "unreadable" → a typed ConfigError, not a raw
    # UnicodeDecodeError escaping the loader (K8).
    p = tmp_path / "settings.yaml"
    p.write_bytes(b"\xff\xfe\x00not utf-8")
    with pytest.raises(ConfigError, match="Cannot read settings file"):
        load_settings(p)


def test_env_degenerate_csv_is_loud() -> None:
    # a non-empty env value that parses to NO items is operator error, not a silent
    # empty list (an empty trusted_hosts would reject every Host) (K8).
    with pytest.raises(ConfigError, match="CDMON_TRUSTED_HOSTS has no values"):
        settings_from_env(Settings(), {"CDMON_TRUSTED_HOSTS": " , , "})
