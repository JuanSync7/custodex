"""Production store selection + persistence — ``store_from_env`` (E-04 launch wiring).

The central server's production launch (``cdx-server`` -> ``server.app:main``) must
PERSIST: a restart cannot lose ingested records. ``store_from_env`` is the seam that
makes that real — it reads ``$CDMON_DATABASE_URL`` and, when set, MIGRATES the schema
to head (Alembic, the prod path) and returns a persistent
:class:`~custodex.server.db.SqlStore`; when unset it falls back to a transient
:class:`InMemoryStore` with a LOUD warning (K8) so an operator is never silently
surprised by vanished data.

These tests use FILE-backed **SQLite** as the offline stand-in for Postgres (K4/K9 —
stdlib, no driver): the SAME migrations + SqlStore that prod runs on Postgres, proven
to persist across store instances AND across a simulated server restart through HTTP.
A single ``pg``-marked test runs the same persistence against a REAL Postgres in the
``tests:pg`` CI job (deselected by default), so the prod driver/JSONB path is covered
too — the offline gate stays Postgres-free.

Gated on the ``[server]`` extra (fastapi + sqlalchemy + alembic); SKIPS without it.

Features: FEAT-SERVER-001, FEAT-SERVER-002, FEAT-SERVER-003, FEAT-SERVER-005
Features: FEAT-SERVER-006, FEAT-SERVER-007, FEAT-SERVER-008
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")
pytest.importorskip(
    "sqlalchemy", reason="the [server] extra (sqlalchemy) is not installed"
)
pytest.importorskip("alembic", reason="the [server] extra (alembic) is not installed")

from sqlalchemy import create_engine, inspect  # noqa: E402

from custodex.registry import RegistrationPayload  # noqa: E402
from custodex.schema import (  # noqa: E402
    ProposedFix,
    ReviewRecord,
    Verdict,
)
from custodex.server import InMemoryStore, store_from_env  # noqa: E402
from custodex.server.db import SqlStore  # noqa: E402
from custodex.sinks import IngestEnvelope, RepoIdentity  # noqa: E402

_ENV = "CDMON_DATABASE_URL"


# --------------------------------------------------------------------------- #
# shared builders
# --------------------------------------------------------------------------- #
def _identity(repo_id: str) -> RepoIdentity:
    return RepoIdentity(repo_id=repo_id, repo_name="widget", commit="deadbeef")


def _payload(repo_id: str, auth_token: str | None = None) -> RegistrationPayload:
    return RegistrationPayload(
        repo=_identity(repo_id), description="svc", auth_token=auth_token
    )


def _record(repo_id: str, record_id: str = "abc123def456") -> ReviewRecord:
    return ReviewRecord(
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
        detected_at="2026-06-05T00:00:00Z",
        resolved_at="2026-06-05T00:00:30Z",
        config_snapshot={"repo_id": repo_id},
        source_sha="cafebabe",
    )


# --------------------------------------------------------------------------- #
# unset -> transient InMemoryStore + a LOUD warning (K8)
# --------------------------------------------------------------------------- #
def test_store_from_env_unset_is_in_memory_and_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    with caplog.at_level(logging.WARNING, logger="custodex.server"):
        store = store_from_env()
    assert isinstance(store, InMemoryStore)
    # the operator is told, loudly, that data is ephemeral.
    assert any(
        "in-memory" in r.message.lower() and "lost on restart" in r.message.lower()
        for r in caplog.records
    )


def test_store_from_env_empty_string_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An exported-but-empty var must not be read as a database URL.
    monkeypatch.setenv(_ENV, "")
    assert isinstance(store_from_env(), InMemoryStore)


# --------------------------------------------------------------------------- #
# set -> persistent SqlStore, schema MIGRATED to head (not create_all)
# --------------------------------------------------------------------------- #
def test_store_from_env_with_url_returns_migrated_sqlstore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    url = f"sqlite:///{tmp_path / 'cdmon.db'}"
    monkeypatch.setenv(_ENV, url)

    store = store_from_env()
    assert isinstance(store, SqlStore)

    insp = inspect(create_engine(url))
    tables = set(insp.get_table_names())
    # the migration path stamps `alembic_version` — create_all would NOT, so this
    # proves prod uses MIGRATIONS, not a bare create_all.
    assert "alembic_version" in tables
    assert {"repos", "records", "resolutions", "coverage_snapshots"} <= tables
    # the E-06 token_hash column from migration 0002 is present (we're at head).
    assert "token_hash" in {c["name"] for c in insp.get_columns("repos")}


def test_store_from_env_is_idempotent_on_an_existing_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # K7: re-selecting the store against an already-migrated DB is a safe no-op and
    # preserves prior data (the migration `upgrade head` is idempotent at head).
    url = f"sqlite:///{tmp_path / 'cdmon.db'}"
    monkeypatch.setenv(_ENV, url)

    first = store_from_env()
    first.add_repo(_payload("acme/widget"))
    first.add_record("acme/widget", _record("acme/widget"))

    second = store_from_env()  # re-run migrations + new SqlStore on the same file
    assert [r.repo.repo_id for r in second.list_repos()] == ["acme/widget"]
    (back,) = second.records_for("acme/widget")
    assert back == _record("acme/widget")


# --------------------------------------------------------------------------- #
# the real point: data SURVIVES a server restart, through HTTP
# --------------------------------------------------------------------------- #
def test_ingested_data_survives_a_restart_through_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fastapi.testclient import TestClient

    from custodex.server import create_app

    url = f"sqlite:///{tmp_path / 'cdmon.db'}"
    monkeypatch.setenv(_ENV, url)

    # --- process 1: register + ingest through the app, then "shut down" ---------
    app1 = create_app(store_from_env())
    with TestClient(app1) as c1:
        assert (
            c1.post(
                "/repos", json=_payload("acme/widget").model_dump(mode="json")
            ).status_code
            == 201
        )
        env = IngestEnvelope(
            repo=_identity("acme/widget"), record=_record("acme/widget")
        ).model_dump(mode="json")
        assert c1.post("/ingest", json=env).status_code == 202

    # --- process 2: a fresh app over a fresh store_from_env() on the SAME db -----
    app2 = create_app(store_from_env())
    with TestClient(app2) as c2:
        repos = c2.get("/repos").json()
        assert [r["repo"]["repo_id"] for r in repos] == ["acme/widget"]
        recs = c2.get("/repos/acme%2Fwidget/records").json()
        assert len(recs) == 1
        assert ReviewRecord.model_validate(recs[0]) == _record("acme/widget")


# --------------------------------------------------------------------------- #
# the `pg` marker: the SAME persistence against a REAL Postgres (CI `tests:pg`)
# --------------------------------------------------------------------------- #
_PG_URL = os.environ.get("CDMON_DATABASE_URL", "")
_IS_PG = _PG_URL.startswith("postgresql")


@pytest.mark.pg
@pytest.mark.skipif(not _IS_PG, reason="CDMON_DATABASE_URL is not a Postgres URL")
def test_store_from_env_persists_to_real_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Runs ONLY in the tests:pg CI job (deselected offline, like live_llm). Reset the
    # CI's throwaway `public` schema first so this migration-based test is independent
    # of the create_all-based pg contract test in test_db.py (either order is safe).
    from sqlalchemy import text

    reset = create_engine(_PG_URL)
    with reset.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    reset.dispose()

    monkeypatch.setenv(_ENV, _PG_URL)
    store = store_from_env()  # migrate head + SqlStore on real Postgres
    assert isinstance(store, SqlStore)
    store.add_repo(_payload("pg/launch"))
    store.add_record("pg/launch", _record("pg/launch"))

    # a brand-new store over the same DB sees the persisted rows (JSONB round-trip).
    reopened = store_from_env()
    assert [r.repo.repo_id for r in reopened.list_repos()] == ["pg/launch"]
    (back,) = reopened.records_for("pg/launch")
    assert back == _record("pg/launch")
