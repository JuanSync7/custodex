"""Tests for the SQLAlchemy DB store + Alembic migrations (E-04 — K0/K4/K6/K9/K10).

The DEFAULT offline suite runs the WHOLE store contract on in-memory / temp-file
**SQLite** (K4/K9 — SQLite is stdlib, no driver). The SAME contract is also marked
``@pytest.mark.pg`` to run against ``$CDMON_DATABASE_URL`` Postgres in CI; that
marker is DESELECTED by default (``addopts = -m "not live_llm and not pg"``), so it
never runs (nor connects) in the offline gate.

The whole module is gated on the optional ``[server]`` extra (sqlalchemy): if
sqlalchemy is not importable the file SKIPS, mirroring ``test_server.py``. ``.venv``
HAS sqlalchemy so these tests RUN here.

Features: FEAT-SERVER-005, FEAT-SERVER-006, FEAT-SERVER-007
Features: FEAT-SERVER-004, FEAT-RECORD-002
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests._repo import REPO_ROOT

pytest.importorskip(
    "sqlalchemy", reason="the [server] extra (sqlalchemy) is not installed"
)

from sqlalchemy import inspect  # noqa: E402

from custodex.registry import RegistrationPayload  # noqa: E402
from custodex.schema import (  # noqa: E402
    ProposedFix,
    Resolution,
    ResolutionRecord,
    ReviewRecord,
    Verdict,
)
from custodex.server.db import (  # noqa: E402
    SqlStore,
    create_all,
    engine_from_url,
)
from custodex.sinks import RepoIdentity  # noqa: E402

# --------------------------------------------------------------------------- #
# shared fixtures / builders (mirror test_server.py's shared schema instances)
# --------------------------------------------------------------------------- #


def _identity(repo_id: str = "acme/widget") -> RepoIdentity:
    return RepoIdentity(
        repo_id=repo_id,
        repo_name="widget",
        repo_url="https://example.invalid/acme/widget",
        commit="deadbeef",
    )


def _payload(
    repo_id: str = "acme/widget",
    description: str = "the widget service",
    auth_token: str | None = None,
) -> RegistrationPayload:
    return RegistrationPayload(
        repo=_identity(repo_id),
        default_branch="main",
        description=description,
        auth_token=auth_token,
    )


def _record(
    repo_id: str = "acme/widget",
    record_id: str = "abc123def456",
    *,
    doc_id: str = "pipeline",
    audience: str = "eng-guide",
    drift_kind: str = "REGION",
    verdict: Verdict = Verdict.FIX,
    detected_at: str = "2026-06-05T00:00:00Z",
) -> ReviewRecord:
    return ReviewRecord(
        record_id=record_id,
        doc_id=doc_id,
        doc_path="docs/api/pipeline.md",
        audience=audience,
        drift_kind=drift_kind,
        drift_detail="signature moved",
        cause="public signature changed",
        verdict=verdict,
        fix=ProposedFix(rationale="regenerate the region"),
        surface_hash="0" * 16,
        backend_kind="mock",
        detected_at=detected_at,
        resolved_at="2026-06-05T00:00:01Z",
        config_snapshot={"repo_id": repo_id},
        source_sha="cafebabe",
    )


def _resolution(record_id: str = "abc123def456") -> ResolutionRecord:
    return ResolutionRecord(
        record_id=record_id,
        resolution=Resolution.ACCEPTED,
        resolved_by="alice",
        resolved_at="2026-06-05T01:00:00Z",
        note="merged as-is",
    )


@pytest.fixture
def store() -> SqlStore:
    """A fresh SqlStore over an in-memory SQLite engine (K4)."""
    engine = engine_from_url("sqlite:///:memory:")
    create_all(engine)
    return SqlStore(engine)


# --------------------------------------------------------------------------- #
# Store Protocol contract (identical behavior to InMemoryStore)
# --------------------------------------------------------------------------- #


def test_sql_store_satisfies_store_protocol(store: SqlStore) -> None:
    from custodex.server.store import Store

    assert isinstance(store, Store)


def test_add_get_list_repos(store: SqlStore) -> None:
    assert store.list_repos() == []
    assert store.get_repo("acme/widget") is None

    store.add_repo(_payload())
    got = store.get_repo("acme/widget")
    assert got is not None
    assert got.repo == _identity()
    assert got.default_branch == "main"
    assert got.description == "the widget service"
    assert [r.repo.repo_id for r in store.list_repos()] == ["acme/widget"]


def test_repeat_add_repo_updates_in_place(store: SqlStore) -> None:
    store.add_repo(_payload(description="v1"))
    store.add_repo(_payload(description="v2"))
    repos = store.list_repos()
    assert len(repos) == 1
    assert repos[0].description == "v2"


def test_list_repos_insertion_order(store: SqlStore) -> None:
    store.add_repo(_payload("a/one"))
    store.add_repo(_payload("b/two"))
    store.add_repo(_payload("c/three"))
    assert [r.repo.repo_id for r in store.list_repos()] == ["a/one", "b/two", "c/three"]


def test_add_record_and_records_for(store: SqlStore) -> None:
    store.add_repo(_payload())
    store.add_record("acme/widget", _record())
    got = store.records_for("acme/widget")
    assert len(got) == 1
    # FULL ReviewRecord round-trips through the JSON column byte-for-byte (K6).
    assert got[0] == _record()


def test_records_preserve_insertion_order(store: SqlStore) -> None:
    store.add_repo(_payload())
    store.add_record("acme/widget", _record(record_id="first0000000"))
    store.add_record("acme/widget", _record(record_id="second000000"))
    store.add_record("acme/widget", _record(record_id="third0000000"))
    assert [r.record_id for r in store.records_for("acme/widget")] == [
        "first0000000",
        "second000000",
        "third0000000",
    ]


def test_records_for_unknown_repo_is_empty(store: SqlStore) -> None:
    assert store.records_for("nope/never") == []


def test_full_review_record_round_trips_including_additive_field(
    store: SqlStore,
) -> None:
    store.add_repo(_payload())
    rec = _record()
    # source_sha is the C-05 ADDITIVE field — it must survive the JSON column (K6).
    assert rec.source_sha == "cafebabe"
    store.add_record("acme/widget", rec)
    (back,) = store.records_for("acme/widget")
    assert back == rec
    assert back.source_sha == "cafebabe"
    assert back.model_dump() == rec.model_dump()


# --------------------------------------------------------------------------- #
# resolutions + coverage snapshots (store methods; endpoints land in E-05)
# --------------------------------------------------------------------------- #


def test_resolutions_crud(store: SqlStore) -> None:
    assert store.resolutions_for("abc123def456") == []
    store.add_resolution(_resolution())
    got = store.resolutions_for("abc123def456")
    assert len(got) == 1
    assert got[0] == _resolution()


def test_resolutions_insertion_order(store: SqlStore) -> None:
    r1 = _resolution()
    r2 = ResolutionRecord(
        record_id="abc123def456",
        resolution=Resolution.OVERRIDDEN,
        resolved_text="rewrote it",
        resolved_at="2026-06-05T02:00:00Z",
    )
    store.add_resolution(r1)
    store.add_resolution(r2)
    got = store.resolutions_for("abc123def456")
    assert [r.resolution for r in got] == [Resolution.ACCEPTED, Resolution.OVERRIDDEN]


def test_coverage_snapshots_crud(store: SqlStore) -> None:
    assert store.coverage_snapshots_for("acme/widget") == []
    snap = {"files": 3, "covered": 2, "ratio": 0.66}
    store.add_coverage_snapshot("acme/widget", "2026-06-05T00:00:00Z", snap)
    got = store.coverage_snapshots_for("acme/widget")
    assert got == [snap]


# --------------------------------------------------------------------------- #
# E-05 filtered records / status aggregation / E-06 token hash (SqlStore)
# --------------------------------------------------------------------------- #


def _seed_mixed(store: SqlStore, repo_id: str = "acme/widget") -> None:
    store.add_repo(_payload(repo_id))
    store.add_record(
        repo_id,
        _record(
            repo_id,
            "r0aaaaaaaaaa",
            doc_id="pipeline",
            audience="eng-guide",
            drift_kind="REGION",
            verdict=Verdict.FIX,
            detected_at="2026-06-01T00:00:00Z",
        ),
    )
    store.add_record(
        repo_id,
        _record(
            repo_id,
            "r1bbbbbbbbbb",
            doc_id="pipeline",
            audience="user-guide",
            drift_kind="SURFACE",
            verdict=Verdict.INVALIDATE,
            detected_at="2026-06-02T00:00:00Z",
        ),
    )
    store.add_record(
        repo_id,
        _record(
            repo_id,
            "r2cccccccccc",
            doc_id="overview",
            audience="eng-guide",
            drift_kind="REGION",
            verdict=Verdict.ESCALATE,
            detected_at="2026-06-03T00:00:00Z",
        ),
    )


def test_sql_records_filter_by_indexed_columns(store: SqlStore) -> None:
    _seed_mixed(store)
    fix = store.records_for("acme/widget", verdict="FIX")
    assert [r.record_id for r in fix] == ["r0aaaaaaaaaa"]
    eng = store.records_for("acme/widget", audience="eng-guide")
    assert {r.record_id for r in eng} == {"r0aaaaaaaaaa", "r2cccccccccc"}
    region = store.records_for("acme/widget", drift_kind="REGION", doc_id="overview")
    assert [r.record_id for r in region] == ["r2cccccccccc"]


def test_sql_records_pagination(store: SqlStore) -> None:
    _seed_mixed(store)
    page = store.records_for("acme/widget", limit=2, offset=1)
    assert [r.record_id for r in page] == ["r1bbbbbbbbbb", "r2cccccccccc"]


def test_sql_records_filter_revalidates_full_schema(store: SqlStore) -> None:
    _seed_mixed(store)
    (rec,) = store.records_for("acme/widget", verdict="ESCALATE")
    assert rec == _record(
        "acme/widget",
        "r2cccccccccc",
        doc_id="overview",
        audience="eng-guide",
        drift_kind="REGION",
        verdict=Verdict.ESCALATE,
        detected_at="2026-06-03T00:00:00Z",
    )


def test_sql_resolutions_for_repo(store: SqlStore) -> None:
    _seed_mixed(store)
    assert store.resolutions_for_repo("acme/widget") == []
    store.add_resolution(_resolution("r0aaaaaaaaaa"))
    store.add_resolution(_resolution("r2cccccccccc"))
    got = store.resolutions_for_repo("acme/widget")
    assert {r.record_id for r in got} == {"r0aaaaaaaaaa", "r2cccccccccc"}
    # filtered to a single record
    one = store.resolutions_for_repo("acme/widget", record_id="r0aaaaaaaaaa")
    assert [r.record_id for r in one] == ["r0aaaaaaaaaa"]


def test_sql_resolutions_for_repo_with_no_records_is_empty(store: SqlStore) -> None:
    # A repo with no records short-circuits to [] (the resolution scope is empty).
    store.add_repo(_payload())
    assert store.resolutions_for_repo("acme/widget") == []


def test_sql_coverage_for(store: SqlStore) -> None:
    store.add_repo(_payload())
    assert store.coverage_for("acme/widget") == []
    store.add_coverage_snapshot("acme/widget", "2026-06-05T00:00:00Z", {"ratio": 0.5})
    assert store.coverage_for("acme/widget") == [{"ratio": 0.5}]


def test_sql_token_hash_stored_and_retrieved(store: SqlStore) -> None:
    import hashlib

    store.add_repo(_payload(auth_token="s3cret"))
    expected = hashlib.sha256(b"s3cret").hexdigest()
    assert store.repo_token_hash("acme/widget") == expected
    # a repo without a token has no hash
    store.add_repo(_payload("b/two"))
    assert store.repo_token_hash("b/two") is None
    # auth_token is NEVER round-tripped into the read projection
    got = store.get_repo("acme/widget")
    assert got is not None
    assert "auth_token" not in got.model_dump()


def test_sql_reregister_can_rotate_token(store: SqlStore) -> None:
    import hashlib

    store.add_repo(_payload(auth_token="first"))
    store.add_repo(_payload(auth_token="second"))
    assert store.repo_token_hash("acme/widget") == hashlib.sha256(b"second").hexdigest()


def test_sql_provider_secret_plaintext_never_in_stored_payload(store: SqlStore) -> None:
    """The WRITE-ONLY plaintext provider_secret must never reach the JSON
    column (GIT-02)."""
    from sqlalchemy import select

    from custodex.server.db import RepoRow

    payload = RegistrationPayload(
        repo=_identity(), default_branch="main", provider_secret="PLAINTEXT-XYZ"
    )
    store.add_repo(payload)
    with store._session() as session:
        row = session.scalars(
            select(RepoRow).where(RepoRow.repo_id == "acme/widget")
        ).first()
        assert row is not None
        assert "provider_secret" not in row.payload  # sanitized from the JSON
        assert "PLAINTEXT-XYZ" not in str(row.payload)  # belt-and-braces
    # …and the read projection never exposes it either.
    got = store.get_repo("acme/widget")
    assert got is not None
    assert "provider_secret" not in got.model_dump()


# --------------------------------------------------------------------------- #
# real persistence across store instances sharing one file engine (not a dict)
# --------------------------------------------------------------------------- #


def test_persistence_across_store_instances(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'cdmon.db'}"
    engine = engine_from_url(url)
    create_all(engine)

    writer = SqlStore(engine)
    writer.add_repo(_payload())
    writer.add_record("acme/widget", _record())

    # A SECOND store on the SAME engine sees the persisted data (proves it's a DB,
    # not an in-memory dict).
    reader = SqlStore(engine)
    assert [r.repo.repo_id for r in reader.list_repos()] == ["acme/widget"]
    assert reader.records_for("acme/widget") == [_record()]

    # And a brand-new engine on the same FILE re-reads it (true on-disk persistence).
    reopened = SqlStore(engine_from_url(url))
    assert reopened.records_for("acme/widget") == [_record()]


# --------------------------------------------------------------------------- #
# Alembic migration up/down round-trip on a temp SQLite DB
# --------------------------------------------------------------------------- #


def _alembic_config(url: str):  # type: ignore[no-untyped-def]
    from alembic.config import Config

    root = REPO_ROOT
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_alembic_migration_up_then_down(tmp_path: Path) -> None:
    from alembic import command

    db = tmp_path / "migrate.db"
    url = f"sqlite:///{db}"
    cfg = _alembic_config(url)
    engine = engine_from_url(url)

    tables = {"repos", "records", "resolutions", "coverage_snapshots"}

    # upgrade head -> all four tables exist + the E-06 token_hash column on repos.
    command.upgrade(cfg, "head")
    present = set(inspect(engine).get_table_names())
    assert tables <= present
    repo_cols = {c["name"] for c in inspect(engine).get_columns("repos")}
    assert "token_hash" in repo_cols

    # downgrade to 0001 (the pre-E-06 schema) -> the column is dropped, tables remain.
    command.downgrade(cfg, "0001_initial")
    repo_cols_0001 = {c["name"] for c in inspect(engine).get_columns("repos")}
    assert "token_hash" not in repo_cols_0001
    assert tables <= set(inspect(engine).get_table_names())

    # downgrade base -> the tables are dropped again.
    command.downgrade(cfg, "base")
    present_after = set(inspect(engine).get_table_names())
    assert not (tables & present_after)


def test_alembic_migration_0003_config_sync_up_then_down(tmp_path: Path) -> None:
    """0003 (Y-01) creates config_documents/config_code_refs/sync_runs; down drops."""
    from alembic import command

    db = tmp_path / "migrate_0003.db"
    url = f"sqlite:///{db}"
    cfg = _alembic_config(url)
    engine = engine_from_url(url)

    y01_tables = {"config_documents", "config_code_refs", "sync_runs"}

    # upgrade to 0002 -> the Y-01 tables do NOT exist yet (additive 0003 adds them).
    command.upgrade(cfg, "0002_token_hash")
    assert not (y01_tables & set(inspect(engine).get_table_names()))

    # upgrade head (through 0003) -> all three Y-01 tables exist with their key columns.
    command.upgrade(cfg, "head")
    present = set(inspect(engine).get_table_names())
    assert y01_tables <= present
    doc_cols = {c["name"] for c in inspect(engine).get_columns("config_documents")}
    assert {"repo_id", "doc_id", "sync_kind", "document"} <= doc_cols
    run_cols = {c["name"] for c in inspect(engine).get_columns("sync_runs")}
    assert {"repo_id", "sync_kind", "fully_synced", "run"} <= run_cols

    # downgrade to 0002 -> the three Y-01 tables are dropped; pre-Y-01 tables remain.
    command.downgrade(cfg, "0002_token_hash")
    after = set(inspect(engine).get_table_names())
    assert not (y01_tables & after)
    assert {"repos", "records", "resolutions", "coverage_snapshots"} <= after


def test_alembic_migration_0004_config_edits_up_then_down(tmp_path: Path) -> None:
    """0004 (EDITOR E-03) creates config_edits; down drops it, leaving 0003 intact."""
    from alembic import command

    db = tmp_path / "migrate_0004.db"
    url = f"sqlite:///{db}"
    cfg = _alembic_config(url)
    engine = engine_from_url(url)

    # upgrade to 0003 -> config_edits does NOT exist yet (additive 0004 adds it).
    command.upgrade(cfg, "0003_config_sync")
    assert "config_edits" not in set(inspect(engine).get_table_names())

    # upgrade head (through 0004) -> the table exists with its key columns.
    command.upgrade(cfg, "head")
    assert "config_edits" in set(inspect(engine).get_table_names())
    cols = {c["name"] for c in inspect(engine).get_columns("config_edits")}
    assert {
        "id",
        "repo_id",
        "edit_id",
        "status",
        "created_at",
        "applied_at",
        "edit",
    } <= cols

    # downgrade to 0003 -> config_edits dropped; the Y-01 tables remain.
    command.downgrade(cfg, "0003_config_sync")
    after = set(inspect(engine).get_table_names())
    assert "config_edits" not in after
    assert {"config_documents", "config_code_refs", "sync_runs"} <= after


def test_alembic_migration_0005_provider_secret_up_then_down(tmp_path: Path) -> None:
    """0005 (GIT-02) adds repos.provider_secret; down drops it, leaving repos intact."""
    from alembic import command

    db = tmp_path / "migrate_0005.db"
    url = f"sqlite:///{db}"
    cfg = _alembic_config(url)
    engine = engine_from_url(url)

    # upgrade to 0004 -> repos has token_hash but NOT yet provider_secret.
    command.upgrade(cfg, "0004_config_edits")
    cols = {c["name"] for c in inspect(engine).get_columns("repos")}
    assert "token_hash" in cols
    assert "provider_secret" not in cols

    # upgrade head (through 0005) -> the provider_secret column exists.
    command.upgrade(cfg, "head")
    cols = {c["name"] for c in inspect(engine).get_columns("repos")}
    assert "provider_secret" in cols

    # downgrade to 0004 -> the column is dropped; the repos table remains.
    command.downgrade(cfg, "0004_config_edits")
    cols = {c["name"] for c in inspect(engine).get_columns("repos")}
    assert "provider_secret" not in cols
    assert "repos" in set(inspect(engine).get_table_names())


# --------------------------------------------------------------------------- #
# E-03 server contract re-run against create_app(SqlStore(...)) — Protocol swap
# is transparent (the routes/app are untouched).
# --------------------------------------------------------------------------- #


def test_server_round_trip_against_sql_store(store: SqlStore) -> None:
    fastapi = pytest.importorskip("fastapi")  # noqa: F841
    from fastapi.testclient import TestClient

    from custodex.server import create_app

    client = TestClient(create_app(store))

    reg = client.post("/repos", json=_payload().model_dump(mode="json"))
    assert reg.status_code == 201
    assert reg.json() == {"repo_id": "acme/widget"}

    from custodex.sinks import IngestEnvelope

    env = IngestEnvelope(repo=_identity(), record=_record()).model_dump(mode="json")
    ing = client.post("/ingest", json=env)
    assert ing.status_code == 202
    assert ing.json() == {"record_id": "abc123def456"}

    got = client.get("/repos/acme%2Fwidget/records")
    assert got.status_code == 200
    body = got.json()
    assert len(body) == 1
    # round-trips through the JSON column AND the shared schema, byte-for-byte.
    assert ReviewRecord.model_validate(body[0]) == _record()
    assert body[0] == env["record"]

    # unknown repo policy still holds against the DB store.
    assert (
        client.post(
            "/ingest",
            json={**env, "repo": _identity("never/here").model_dump(mode="json")},
        ).status_code
        == 404
    )
    assert client.get("/repos/never%2Fhere/records").status_code == 404


def test_server_lists_against_sql_store(store: SqlStore) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from custodex.server import create_app

    client = TestClient(create_app(store))
    assert client.get("/repos").json() == []
    client.post("/repos", json=_payload("a/one").model_dump(mode="json"))
    client.post("/repos", json=_payload("b/two").model_dump(mode="json"))
    repos = client.get("/repos").json()
    assert [r["repo"]["repo_id"] for r in repos] == ["a/one", "b/two"]


# --------------------------------------------------------------------------- #
# the `pg` marker: same contract against real Postgres — SKIPPED by default
# --------------------------------------------------------------------------- #

_PG_URL = os.environ.get("CDMON_DATABASE_URL", "")
_IS_PG = _PG_URL.startswith("postgresql")


@pytest.mark.pg
@pytest.mark.skipif(not _IS_PG, reason="CDMON_DATABASE_URL is not a Postgres URL")
def test_sql_store_contract_on_postgres() -> None:
    # The real-PG path runs only in the `tests:pg` CI job (K4, like live_llm); the
    # offline gate runs this exact contract on SQLite, so this is deselected here.
    engine = engine_from_url(_PG_URL)
    create_all(engine)
    pg = SqlStore(engine)
    pg.add_repo(_payload("pg/repo"))
    pg.add_record("pg/repo", _record("pg/repo"))
    assert [r.repo.repo_id for r in pg.list_repos()] == ["pg/repo"]
    (back,) = pg.records_for("pg/repo")
    assert back == _record("pg/repo")


def test_alembic_migration_0006_roster_up_then_down(tmp_path: Path) -> None:
    """0006 (OWN-04) creates the roster table; down drops it (the rest remain).

    Features: FEAT-OWNERSHIP-005
    """
    from alembic import command

    db = tmp_path / "migrate_0006.db"
    url = f"sqlite:///{db}"
    cfg = _alembic_config(url)
    engine = engine_from_url(url)

    # upgrade to 0005 -> the roster table does NOT exist yet (additive 0006 adds it).
    command.upgrade(cfg, "0005_provider_secret")
    assert "roster" not in set(inspect(engine).get_table_names())

    # upgrade head (through 0006) -> the roster table exists with its key columns.
    command.upgrade(cfg, "head")
    assert "roster" in set(inspect(engine).get_table_names())
    cols = {c["name"] for c in inspect(engine).get_columns("roster")}
    assert {"id", "name", "kind", "active", "identity"} <= cols

    # downgrade to 0005 -> the roster table is dropped; the rest remain.
    command.downgrade(cfg, "0005_provider_secret")
    after = set(inspect(engine).get_table_names())
    assert "roster" not in after
    assert {"repos", "config_documents"} <= after


def test_alembic_migration_0007_doc_edges_up_then_down(tmp_path: Path) -> None:
    """0007 (B-09) creates config_doc_edges (the reverse-lookup index); down drops it.

    Features: FEAT-DOCDEPS-008
    """
    from alembic import command

    db = tmp_path / "migrate_0007.db"
    url = f"sqlite:///{db}"
    cfg = _alembic_config(url)
    engine = engine_from_url(url)

    # upgrade to 0006 -> config_doc_edges does NOT exist yet (additive 0007 adds it).
    command.upgrade(cfg, "0006_roster_and_ownership")
    assert "config_doc_edges" not in set(inspect(engine).get_table_names())

    # upgrade head (through 0007) -> the table exists with its key columns.
    command.upgrade(cfg, "head")
    assert "config_doc_edges" in set(inspect(engine).get_table_names())
    cols = {c["name"] for c in inspect(engine).get_columns("config_doc_edges")}
    assert {
        "id",
        "repo_id",
        "doc_id",
        "upstream_id",
        "sync_kind",
        "type",
        "edge",
    } <= cols
    # the reverse-lookup column is indexed (the whole point of the table).
    indexed = {
        col
        for ix in inspect(engine).get_indexes("config_doc_edges")
        for col in ix["column_names"]
    }
    assert "upstream_id" in indexed

    # downgrade to 0006 -> config_doc_edges dropped; the rest remain.
    command.downgrade(cfg, "0006_roster_and_ownership")
    after = set(inspect(engine).get_table_names())
    assert "config_doc_edges" not in after
    assert {"config_documents", "roster"} <= after


def test_alembic_migration_0008_graph_snapshots_up_then_down(tmp_path: Path) -> None:
    """0008 (AGT-03) creates graph_snapshots; down drops it, leaving 0007 intact."""
    from alembic import command

    db = tmp_path / "migrate_0008.db"
    url = f"sqlite:///{db}"
    cfg = _alembic_config(url)
    engine = engine_from_url(url)

    # upgrade to 0007 -> graph_snapshots does NOT exist yet (additive 0008).
    command.upgrade(cfg, "0007_doc_edges")
    assert "graph_snapshots" not in set(inspect(engine).get_table_names())

    # upgrade head (through 0008) -> the table exists with its key columns.
    command.upgrade(cfg, "head")
    assert "graph_snapshots" in set(inspect(engine).get_table_names())
    cols = {c["name"] for c in inspect(engine).get_columns("graph_snapshots")}
    assert {"id", "repo_id", "captured_at", "snapshot"} <= cols

    # downgrade to 0007 -> dropped; the doc-edges table remains.
    command.downgrade(cfg, "0007_doc_edges")
    after = set(inspect(engine).get_table_names())
    assert "graph_snapshots" not in after
    assert "config_doc_edges" in after
