"""The SQLAlchemy 2.0 DB store — Postgres-first, offline SQLite (E-04 — K0/K6/K10).

:class:`SqlStore` swaps the E-03 ``InMemoryStore`` for a real SQLAlchemy store behind
the SAME :class:`~code_doc_monitor.server.store.Store` Protocol — ``app.py`` and the
routes are UNTOUCHED. It is Postgres-first in prod, but
the default offline suite runs the SAME contract on in-memory/temp-file **SQLite**
(K4/K9 — SQLite is stdlib, no driver), with a ``pg`` pytest marker for real Postgres.

**"Indexed columns + full JSON" hybrid (K6 additivity).** Each record / resolution row
stores the FULL shared pydantic model in a JSON column (``JSONB`` on Postgres, JSON on
SQLite via :func:`_json_type`) — so an ADDED schema field round-trips with NO migration
(old rows still parse) — ALONGSIDE indexed scalar columns mirroring the queryable fields
(``repo_id``/``doc_id``/``verdict``/``drift_kind``/``audience``/``detected_at``/
``source_sha``) for E-05's SQL filters. The JSON is the source of truth on READ (the
pydantic model is re-validated from it); the scalar columns are a derived, indexed
projection written on INSERT.

This module imports ``sqlalchemy`` (the ``[server]`` extra). ``import code_doc_monitor``
core does NOT import it (the lazy ``[server]`` boundary holds — it is imported only from
the server subpackage / tests), so the core dependency surface is unchanged (K0).
"""

from __future__ import annotations

from pydantic import TypeAdapter
from sqlalchemy import (
    JSON,
    Boolean,
    Integer,
    LargeBinary,
    StaticPool,
    String,
    create_engine,
    delete,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)
from sqlalchemy.types import TypeEngine

from ..ownership import Identity
from ..registry import RegistrationPayload
from ..schema import ResolutionRecord, ReviewRecord
from .edits import ConfigEdit, StoredConfigEdit
from .store import (
    ConfigCodeRef,
    ConfigDocument,
    RegisteredRepo,
    SyncRun,
    effective_identity,
    hash_token,
)

__all__ = ["Base", "SqlStore", "engine_from_url", "create_all"]


def _json_type() -> TypeEngine[dict]:
    """A portable JSON column type: ``JSONB`` on Postgres, ``JSON`` elsewhere (SQLite).

    The single source of truth for the JSON column type used by both the models and
    the Alembic migration, so dev/test SQLite and prod Postgres stay in lock-step.
    """
    return JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """The declarative base; ``Base.metadata`` feeds both ``create_all`` and Alembic."""


class RepoRow(Base):
    """A registered repo — the FULL :class:`RegistrationPayload` JSON (K6 additive).

    ``RegisteredRepo`` is rebuilt from ``payload`` on read, so an added display field
    round-trips without a migration. The surrogate ``id`` PK is the insertion-order key
    (K10); ``repo_id`` is the unique business key listing/lookup go through.
    """

    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    payload: Mapped[dict] = mapped_column(_json_type())
    # E-06: sha256 hash of the per-repo bearer token (never the plaintext). Nullable so
    # pre-E-06 rows / token-less repos keep writes open.
    token_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    # GIT-02: AES-256-GCM SEALED bytes of the per-repo git provider credential (never
    # the plaintext; opaque to the store — sealed/opened at the route). Nullable so
    # pre-GIT-02 rows / local-only repos carry none. Added by Alembic 0005.
    provider_secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class RecordRow(Base):
    """A review record — FULL :class:`ReviewRecord` JSON + indexed query columns.

    ``record`` is the source of truth (re-validated on read); the scalar columns are a
    derived, indexed projection for E-05 filters. ``id`` is the surrogate PK and the
    insertion-order key (K10).
    """

    __tablename__ = "records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(String, index=True)
    record_id: Mapped[str] = mapped_column(String, index=True)
    doc_id: Mapped[str] = mapped_column(String, index=True)
    verdict: Mapped[str] = mapped_column(String, index=True)
    drift_kind: Mapped[str] = mapped_column(String, index=True)
    audience: Mapped[str] = mapped_column(String, index=True)
    detected_at: Mapped[str] = mapped_column(String, index=True)
    source_sha: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    record: Mapped[dict] = mapped_column(_json_type())


class ResolutionRow(Base):
    """A human outcome — FULL :class:`ResolutionRecord` JSON + indexed ``record_id``."""

    __tablename__ = "resolutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(String, index=True)
    resolution: Mapped[str] = mapped_column(String, index=True)
    resolved_at: Mapped[str] = mapped_column(String, index=True)
    resolution_json: Mapped[dict] = mapped_column(_json_type())


class CoverageSnapshotRow(Base):
    """A coverage snapshot for a repo — an opaque JSON payload (E-04 stores it)."""

    __tablename__ = "coverage_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(String, index=True)
    captured_at: Mapped[str] = mapped_column(String, index=True)
    snapshot: Mapped[dict] = mapped_column(_json_type())


class ConfigDocumentRow(Base):
    """A synced config document — FULL :class:`ConfigDocument` JSON + indexed (Y-01).

    ``document`` is the source of truth (re-validated on read); the scalar columns are
    an indexed projection for the relationship queries. ``id`` is the surrogate PK and
    the insertion-order key (K10). Scoped/replaced per ``(repo_id, sync_kind)``.
    """

    __tablename__ = "config_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(String, index=True)
    doc_id: Mapped[str] = mapped_column(String, index=True)
    sync_kind: Mapped[str] = mapped_column(String, index=True)
    path: Mapped[str] = mapped_column(String)
    audience: Mapped[str] = mapped_column(String)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    ref: Mapped[str | None] = mapped_column(String, nullable=True)
    synced_at: Mapped[str] = mapped_column(String)
    document: Mapped[dict] = mapped_column(_json_type())


class ConfigCodeRefRow(Base):
    """A code_ref under a document — FULL :class:`ConfigCodeRef` JSON + indexed (Y-01).

    ``code_ref`` is the source of truth; the scalar columns index the relationship
    filters (``repo_id``/``doc_id``/``sync_kind``). ``id`` is the surrogate insertion-
    order PK (K10). Replaced together with documents per ``(repo_id, sync_kind)``.
    """

    __tablename__ = "config_code_refs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(String, index=True)
    doc_id: Mapped[str] = mapped_column(String, index=True)
    sync_kind: Mapped[str] = mapped_column(String, index=True)
    path: Mapped[str] = mapped_column(String)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    code_ref: Mapped[dict] = mapped_column(_json_type())


class SyncRunRow(Base):
    """One sync invocation summary — FULL :class:`SyncRun` JSON + indexed cols (Y-01).

    ``run`` is the source of truth (the opaque ``drift`` dict round-trips inside it);
    the scalar columns mirror the queryable fields. ``id`` is the surrogate insertion-
    order PK (K10) — ``latest_sync_run`` is the highest matching ``id``.
    """

    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(String, index=True)
    sync_kind: Mapped[str] = mapped_column(String, index=True)
    ref: Mapped[str | None] = mapped_column(String, nullable=True)
    branch: Mapped[str | None] = mapped_column(String, nullable=True)
    head_commit: Mapped[str | None] = mapped_column(String, nullable=True)
    main_commit: Mapped[str | None] = mapped_column(String, nullable=True)
    commits_ahead: Mapped[int] = mapped_column(Integer)
    fully_synced: Mapped[bool] = mapped_column(Boolean)
    run: Mapped[dict] = mapped_column(_json_type())


class ConfigEditRow(Base):
    """A staged pending config edit — FULL typed JSON + indexed cols (EDITOR E-03).

    The "mapping ticket" table: ``edit`` is the FULL :class:`ConfigEdit` JSON (the
    source of truth, re-validated through the discriminated union on read, K6), and
    the scalar columns index the lifecycle queries (``repo_id``/``edit_id``/
    ``status``). ``id`` is the surrogate insertion-order PK (K10);
    ``applied_at`` is stamped when :meth:`SqlStore.mark_config_edits` flips a row.
    """

    __tablename__ = "config_edits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(String, index=True)
    edit_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[str] = mapped_column(String)
    applied_at: Mapped[str | None] = mapped_column(String, nullable=True)
    edit: Mapped[dict] = mapped_column(_json_type())


class RosterRow(Base):
    """One central roster identity — FULL :class:`Identity` JSON + indexed cols.

    The accountability MIRROR (OWN-04; it never owns a document — config does):
    ``identity`` is the source of truth (re-validated on read, K6), ``name`` is the
    unique business key, and ``active`` is the indexed flag the orphan cascade reads.
    Added by Alembic 0006. ``id`` is the surrogate insertion-order PK (K10).
    """

    __tablename__ = "roster"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    active: Mapped[bool] = mapped_column(Boolean, index=True)
    identity: Mapped[dict] = mapped_column(_json_type())


# The discriminated-union validator reused on every config-edit READ (K6 — the JSON
# blob is the source of truth; an unknown action / stray field is a loud K8 error).
_CONFIG_EDIT_ADAPTER: TypeAdapter[ConfigEdit] = TypeAdapter(ConfigEdit)


def engine_from_url(url: str) -> Engine:
    """Build a SQLAlchemy 2.0 :class:`Engine` from a database URL.

    ``sqlite:///:memory:`` / ``sqlite:///<file>`` for the offline suite (K4);
    ``postgresql+psycopg://...`` (``$CDMON_DATABASE_URL``) in prod / the ``pg`` job.

    In-memory SQLite needs a :class:`StaticPool` (+ ``check_same_thread=False``) so
    every session/connection shares the ONE in-memory database — otherwise each new
    connection gets a fresh, empty DB and ``create_all`` would be invisible to the
    store's sessions (and to FastAPI's TestClient thread). File-backed SQLite and
    Postgres use the normal pool.
    """
    if url in ("sqlite://", "sqlite:///:memory:"):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(url)


def create_all(engine: Engine) -> None:
    """Create all tables on ``engine`` (dev/tests). Prod uses the Alembic migration.

    Both derive from the SAME ``Base.metadata`` — one source of truth for the schema.
    """
    Base.metadata.create_all(engine)


class SqlStore:
    """A SQLAlchemy-backed :class:`~code_doc_monitor.server.store.Store` (E-04).

    Implements the E-03 ``Store`` Protocol (so ``create_app(SqlStore(engine))`` is a
    transparent swap) PLUS resolution + coverage-snapshot methods (endpoints land in
    E-05). One :class:`Session` per call via a ``sessionmaker``. Listing is
    deterministic (K10): repos by insertion order, records/resolutions by surrogate id.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory = sessionmaker(bind=engine)

    def _session(self) -> Session:
        return self._session_factory()

    # --- Store Protocol -----------------------------------------------------

    def add_repo(self, payload: RegistrationPayload) -> None:
        """UPSERT a repo on ``repo_id`` (a repeat register UPDATES in place, K10).

        The per-repo bearer token (E-06) is NEVER persisted as plaintext: it is
        stripped from the stored payload JSON and kept only as a sha256 hash on
        ``token_hash``. A re-register that carries a token ROTATES the hash; one that
        omits it leaves the existing hash untouched (so reads stay simple).
        """
        repo_id = payload.repo.repo_id
        # Sanitize: neither the plaintext bearer token (E-06) nor the plaintext git
        # provider credential (GIT-02) ever reaches the JSON column. The provider
        # secret is persisted SEPARATELY as sealed bytes via set_provider_secret.
        data = payload.model_dump(
            mode="json", exclude={"auth_token", "provider_secret"}
        )
        token_hash = (
            hash_token(payload.auth_token) if payload.auth_token is not None else None
        )
        with self._session() as session, session.begin():
            row = session.scalars(
                select(RepoRow).where(RepoRow.repo_id == repo_id)
            ).first()
            if row is None:
                session.add(
                    RepoRow(repo_id=repo_id, payload=data, token_hash=token_hash)
                )
            else:
                row.payload = data  # update in place; the surrogate id is preserved
                if token_hash is not None:  # rotate only when a new token is supplied
                    row.token_hash = token_hash

    def get_repo(self, repo_id: str) -> RegisteredRepo | None:
        with self._session() as session:
            row = session.scalars(
                select(RepoRow).where(RepoRow.repo_id == repo_id)
            ).first()
            if row is None:
                return None
            return _registered_repo(row)

    def list_repos(self) -> list[RegisteredRepo]:
        with self._session() as session:
            rows = session.scalars(select(RepoRow).order_by(RepoRow.id)).all()
            return [_registered_repo(r) for r in rows]

    def add_record(self, repo_id: str, record: ReviewRecord) -> None:
        """Persist a record: the FULL JSON (K6) + the indexed scalar projection."""
        with self._session() as session, session.begin():
            session.add(
                RecordRow(
                    repo_id=repo_id,
                    record_id=record.record_id,
                    doc_id=record.doc_id,
                    verdict=record.verdict.value,
                    drift_kind=record.drift_kind,
                    audience=record.audience,
                    detected_at=record.detected_at,
                    source_sha=record.source_sha,
                    record=record.model_dump(mode="json"),
                )
            )

    def records_for(
        self,
        repo_id: str,
        *,
        verdict: str | None = None,
        drift_kind: str | None = None,
        audience: str | None = None,
        doc_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ReviewRecord]:
        """Filter via the INDEXED scalar columns (E-05); re-validate the FULL JSON (K6).

        WHERE clauses hit the indexed columns; the JSON column is still the source of
        truth on read. ORDER BY the surrogate ``id`` gives deterministic insertion
        order (K10); ``limit``/``offset`` paginate over it.
        """
        stmt = select(RecordRow).where(RecordRow.repo_id == repo_id)
        if verdict is not None:
            stmt = stmt.where(RecordRow.verdict == verdict)
        if drift_kind is not None:
            stmt = stmt.where(RecordRow.drift_kind == drift_kind)
        if audience is not None:
            stmt = stmt.where(RecordRow.audience == audience)
        if doc_id is not None:
            stmt = stmt.where(RecordRow.doc_id == doc_id)
        stmt = stmt.order_by(RecordRow.id).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        with self._session() as session:
            rows = session.scalars(stmt).all()
            return [ReviewRecord.model_validate(r.record) for r in rows]

    def resolutions_for_repo(
        self, repo_id: str, record_id: str | None = None
    ) -> list[ResolutionRecord]:
        """Resolutions for this repo's records (E-05); optionally one record's only.

        Resolutions link to records by ``record_id``; this scopes them to the repo via
        the repo's record ids (ORDER BY the resolution surrogate id, K10).
        """
        with self._session() as session:
            rec_ids = session.scalars(
                select(RecordRow.record_id).where(RecordRow.repo_id == repo_id)
            ).all()
            if not rec_ids:
                return []
            stmt = select(ResolutionRow).where(ResolutionRow.record_id.in_(rec_ids))
            if record_id is not None:
                stmt = stmt.where(ResolutionRow.record_id == record_id)
            rows = session.scalars(stmt.order_by(ResolutionRow.id)).all()
            return [ResolutionRecord.model_validate(r.resolution_json) for r in rows]

    def coverage_for(self, repo_id: str) -> list[dict]:
        """All coverage snapshots for a repo (latest last, K10) — the E-04 read."""
        return self.coverage_snapshots_for(repo_id)

    def repo_token_hash(self, repo_id: str) -> str | None:
        """The repo's stored sha256 token hash (E-06), or ``None`` if open/unknown."""
        with self._session() as session:
            return session.scalars(
                select(RepoRow.token_hash).where(RepoRow.repo_id == repo_id)
            ).first()

    def set_provider_secret(self, repo_id: str, sealed: bytes) -> None:
        """Store the SEALED git provider credential bytes on the repo row (GIT-02).

        Updates the existing row in place (the route registers the repo first); a
        re-set rotates it. Opaque bytes — the store never opens them (K6 isolation
        of the reversible secret from the one-way token hash).
        """
        with self._session() as session, session.begin():
            row = session.scalars(
                select(RepoRow).where(RepoRow.repo_id == repo_id)
            ).first()
            if row is not None:
                row.provider_secret = sealed

    def repo_provider_secret(self, repo_id: str) -> bytes | None:
        """The repo's SEALED provider credential bytes, or ``None`` if unset/unknown."""
        with self._session() as session:
            return session.scalars(
                select(RepoRow.provider_secret).where(RepoRow.repo_id == repo_id)
            ).first()

    # --- E-04 extras (endpoints in E-05) ------------------------------------

    def add_resolution(self, resolution: ResolutionRecord) -> None:
        with self._session() as session, session.begin():
            session.add(
                ResolutionRow(
                    record_id=resolution.record_id,
                    resolution=resolution.resolution.value,
                    resolved_at=resolution.resolved_at,
                    resolution_json=resolution.model_dump(mode="json"),
                )
            )

    def resolutions_for(self, record_id: str) -> list[ResolutionRecord]:
        with self._session() as session:
            rows = session.scalars(
                select(ResolutionRow)
                .where(ResolutionRow.record_id == record_id)
                .order_by(ResolutionRow.id)
            ).all()
            return [ResolutionRecord.model_validate(r.resolution_json) for r in rows]

    def add_coverage_snapshot(
        self, repo_id: str, captured_at: str, snapshot: dict
    ) -> None:
        with self._session() as session, session.begin():
            session.add(
                CoverageSnapshotRow(
                    repo_id=repo_id, captured_at=captured_at, snapshot=snapshot
                )
            )

    def coverage_snapshots_for(self, repo_id: str) -> list[dict]:
        with self._session() as session:
            rows = session.scalars(
                select(CoverageSnapshotRow)
                .where(CoverageSnapshotRow.repo_id == repo_id)
                .order_by(CoverageSnapshotRow.id)
            ).all()
            return [r.snapshot for r in rows]

    # --- Y-01: config documents / code-refs / sync runs ---------------------

    def replace_config(
        self,
        repo_id: str,
        sync_kind: str,
        documents: list[ConfigDocument],
        code_refs: list[ConfigCodeRef],
    ) -> None:
        """Atomically REPLACE this ``(repo_id, sync_kind)`` scope's config rows (Y-01).

        ONE transaction: DELETE every existing document + code_ref for THIS scope
        (the other ``sync_kind`` is untouched), then INSERT the new set in order. The
        FULL pydantic JSON is the source of truth; scalar columns are the indexed
        projection (K6). Insertion order is the surrogate ``id`` (K10).
        """
        with self._session() as session, session.begin():
            session.execute(
                delete(ConfigDocumentRow).where(
                    ConfigDocumentRow.repo_id == repo_id,
                    ConfigDocumentRow.sync_kind == sync_kind,
                )
            )
            session.execute(
                delete(ConfigCodeRefRow).where(
                    ConfigCodeRefRow.repo_id == repo_id,
                    ConfigCodeRefRow.sync_kind == sync_kind,
                )
            )
            for doc in documents:
                session.add(
                    ConfigDocumentRow(
                        repo_id=doc.repo_id,
                        doc_id=doc.doc_id,
                        sync_kind=doc.sync_kind,
                        path=doc.path,
                        audience=doc.audience,
                        unit=doc.unit,
                        ref=doc.ref,
                        synced_at=doc.synced_at,
                        document=doc.model_dump(mode="json"),
                    )
                )
            for ref in code_refs:
                session.add(
                    ConfigCodeRefRow(
                        repo_id=ref.repo_id,
                        doc_id=ref.doc_id,
                        sync_kind=ref.sync_kind,
                        path=ref.path,
                        unit=ref.unit,
                        code_ref=ref.model_dump(mode="json"),
                    )
                )

    def config_documents_for(
        self, repo_id: str, sync_kind: str | None = None
    ) -> list[ConfigDocument]:
        stmt = select(ConfigDocumentRow).where(ConfigDocumentRow.repo_id == repo_id)
        if sync_kind is not None:
            stmt = stmt.where(ConfigDocumentRow.sync_kind == sync_kind)
        with self._session() as session:
            rows = session.scalars(stmt.order_by(ConfigDocumentRow.id)).all()
            return [ConfigDocument.model_validate(r.document) for r in rows]

    def code_refs_for(
        self,
        repo_id: str,
        doc_id: str | None = None,
        sync_kind: str | None = None,
    ) -> list[ConfigCodeRef]:
        stmt = select(ConfigCodeRefRow).where(ConfigCodeRefRow.repo_id == repo_id)
        if doc_id is not None:
            stmt = stmt.where(ConfigCodeRefRow.doc_id == doc_id)
        if sync_kind is not None:
            stmt = stmt.where(ConfigCodeRefRow.sync_kind == sync_kind)
        with self._session() as session:
            rows = session.scalars(stmt.order_by(ConfigCodeRefRow.id)).all()
            return [ConfigCodeRef.model_validate(r.code_ref) for r in rows]

    def add_sync_run(self, run: SyncRun) -> None:
        """Persist one :class:`SyncRun`: the FULL JSON (K6) + the indexed projection."""
        with self._session() as session, session.begin():
            session.add(
                SyncRunRow(
                    repo_id=run.repo_id,
                    sync_kind=run.sync_kind,
                    ref=run.ref,
                    branch=run.branch,
                    head_commit=run.head_commit,
                    main_commit=run.main_commit,
                    commits_ahead=run.commits_ahead,
                    fully_synced=run.fully_synced,
                    run=run.model_dump(mode="json"),
                )
            )

    def latest_sync_run(
        self, repo_id: str, sync_kind: str | None = None
    ) -> SyncRun | None:
        stmt = select(SyncRunRow).where(SyncRunRow.repo_id == repo_id)
        if sync_kind is not None:
            stmt = stmt.where(SyncRunRow.sync_kind == sync_kind)
        with self._session() as session:
            row = session.scalars(stmt.order_by(SyncRunRow.id.desc())).first()
            return None if row is None else SyncRun.model_validate(row.run)

    def sync_runs_for(
        self, repo_id: str, sync_kind: str | None = None
    ) -> list[SyncRun]:
        stmt = select(SyncRunRow).where(SyncRunRow.repo_id == repo_id)
        if sync_kind is not None:
            stmt = stmt.where(SyncRunRow.sync_kind == sync_kind)
        with self._session() as session:
            rows = session.scalars(stmt.order_by(SyncRunRow.id)).all()
            return [SyncRun.model_validate(r.run) for r in rows]

    # --- EDITOR E-03: pending config edits ----------------------------------

    def add_config_edit(
        self, repo_id: str, edit: ConfigEdit, *, edit_id: str, created_at: str
    ) -> None:
        """Stage one typed :class:`ConfigEdit` as a ``pending`` row (K6 JSON + K10).

        The FULL typed edit is dumped to the JSON column (the source of truth);
        ``repo_id``/``edit_id``/``status`` are the indexed projection.
        """
        with self._session() as session, session.begin():
            session.add(
                ConfigEditRow(
                    repo_id=repo_id,
                    edit_id=edit_id,
                    status="pending",
                    created_at=created_at,
                    applied_at=None,
                    edit=_CONFIG_EDIT_ADAPTER.dump_python(edit, mode="json"),
                )
            )

    def config_edits_for(
        self, repo_id: str, status: str | None = None
    ) -> list[StoredConfigEdit]:
        """This repo's staged edits in insertion order (K10); optional status filter.

        The typed edit is re-validated through the discriminated union on read (K6).
        """
        stmt = select(ConfigEditRow).where(ConfigEditRow.repo_id == repo_id)
        if status is not None:
            stmt = stmt.where(ConfigEditRow.status == status)
        with self._session() as session:
            rows = session.scalars(stmt.order_by(ConfigEditRow.id)).all()
            return [
                StoredConfigEdit(
                    edit_id=r.edit_id,
                    status=r.status,
                    created_at=r.created_at,
                    applied_at=r.applied_at,
                    edit=_CONFIG_EDIT_ADAPTER.validate_python(r.edit),
                )
                for r in rows
            ]

    def mark_config_edits(
        self, repo_id: str, edit_ids: list[str], status: str, *, at: str
    ) -> None:
        """Flip the named edits to ``status`` and stamp ``applied_at`` = ``at`` (E-06).

        Scoped to this repo; only rows whose ``edit_id`` is in ``edit_ids`` change.
        A no-op when ``edit_ids`` is empty (the ``in_`` would match nothing).
        """
        if not edit_ids:
            return
        with self._session() as session, session.begin():
            rows = session.scalars(
                select(ConfigEditRow).where(
                    ConfigEditRow.repo_id == repo_id,
                    ConfigEditRow.edit_id.in_(edit_ids),
                )
            ).all()
            for row in rows:
                row.status = status
                row.applied_at = at

    # --- EPIC OWN: the central roster ---------------------------------------

    def upsert_identity(self, identity: Identity) -> None:
        """UPSERT a roster identity on ``name`` (a repeat UPDATES in place, K10)."""
        data = identity.model_dump(mode="json")
        with self._session() as session, session.begin():
            row = session.scalars(
                select(RosterRow).where(RosterRow.name == identity.name)
            ).first()
            if row is None:
                session.add(
                    RosterRow(
                        name=identity.name,
                        kind=identity.kind,
                        active=identity.active,
                        identity=data,
                    )
                )
            else:
                row.kind = identity.kind
                row.active = identity.active
                row.identity = data

    def list_roster(self) -> list[Identity]:
        with self._session() as session:
            rows = session.scalars(select(RosterRow).order_by(RosterRow.id)).all()
            return [Identity.model_validate(r.identity) for r in rows]

    def mark_identity_departed(self, name: str, *, at: str) -> None:
        with self._session() as session, session.begin():
            row = session.scalars(
                select(RosterRow).where(RosterRow.name == name)
            ).first()
            if row is None:
                return  # unknown name -> no-op (the route 404s before calling)
            updated = Identity.model_validate(row.identity).model_copy(
                update={"active": False, "departed_at": at}
            )
            row.active = False
            row.identity = updated.model_dump(mode="json")


def _registered_repo(row: RepoRow) -> RegisteredRepo:
    """Rebuild a :class:`RegisteredRepo` from a repo row's FULL payload JSON (K6).

    ``local_path`` may have been carried at the payload top level rather than on
    the identity; :func:`effective_identity` folds it onto the resolved identity
    so a SqlStore read exposes the SAME path as an InMemoryStore read (parity).
    This resolves at read time, so rows stored before the fix benefit too.
    """
    payload = RegistrationPayload.model_validate(row.payload)
    return RegisteredRepo(
        repo=effective_identity(payload),
        default_branch=payload.default_branch,
        description=payload.description,
    )
