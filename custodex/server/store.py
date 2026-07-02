"""The central server's storage seam (E-03 — K6/K10).

A :class:`Store` is the one persistence boundary the routes depend on: E-03 ships
the dict-backed :class:`InMemoryStore`; E-04 swaps in a SQLAlchemy/Postgres store
behind this SAME :class:`Store` Protocol without touching ``app.py`` or the routes.
Stored artifacts are the SHARED, versioned models (``RegistrationPayload`` /
``RepoIdentity`` / ``ReviewRecord``) — no DTOs (K6). Ordering is deterministic:
both list accessors return INSERTION order (K10).

This module imports nothing from ``fastapi`` — it is pure pydantic/stdlib, so a
future non-HTTP consumer (or a test) can use the store directly.
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from ..ownership import Identity
from ..registry import RegistrationPayload
from ..schema import ResolutionRecord, ReviewRecord
from ..sinks import RepoIdentity
from .edits import ConfigEdit, StoredConfigEdit

__all__ = [
    "RegisteredRepo",
    "ConfigDocument",
    "ConfigContextRef",
    "ConfigDocEdge",
    "StoredDocEdge",
    "ConfigCodeRef",
    "SyncRun",
    "Store",
    "InMemoryStore",
    "hash_token",
    "effective_identity",
]


def effective_identity(payload: RegistrationPayload) -> RepoIdentity:
    """Resolve the repo identity a register should store, honoring top-level local_path.

    ``local_path`` may be carried EITHER on the :class:`RepoIdentity` OR at the
    top level of the :class:`RegistrationPayload` (registry.py docs both forms).
    When the identity has no ``local_path`` but the payload does, fold the
    top-level value onto the identity so downstream reads (``get_repo`` /
    ``list_repos`` → the ``/sync`` route) see ONE resolved path. An identity that
    already carries a ``local_path`` always wins (the top-level field is a
    fallback only). Shared by both stores so they stay consistent (K6/K10).
    """
    identity = payload.repo
    if identity.local_path is None and payload.local_path is not None:
        return identity.model_copy(update={"local_path": payload.local_path})
    return identity


def hash_token(token: str) -> str:
    """The ONE token-hash function (sha256 hex) — shared by both stores + the auth dep.

    A per-repo bearer token is stored ONLY as this hash (E-06): the server never keeps
    or returns the plaintext. One definition keeps register-time hashing and
    verify-time hashing in lock-step (K10 — deterministic).
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Frozen + extra="forbid": the stored repo is an audited artifact (mirrors the
# wire models in registry.py/sinks.py); an unexpected key is a loud error (K8).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class RegisteredRepo(BaseModel):
    """A repo the central server knows about (E-03).

    The server-side projection of a :class:`RegistrationPayload`: the SHARED
    :class:`RepoIdentity` plus the optional display fields. Reusing the shared
    identity (not a new model) keeps ONE source of truth across client + server.
    """

    model_config = _MODEL_CONFIG

    repo: RepoIdentity
    default_branch: str | None = None
    description: str | None = None


class ConfigContextRef(BaseModel):
    """One ``context_refs`` entry on a :class:`ConfigDocument` (EDITOR E-03).

    The projection of the on-disk
    :class:`~custodex.config.ContextRef` (``path`` + optional ``note``) —
    a "glance-through" generation reference surfaced in the editable tree, NEVER a
    documented surface or coverage (K6). Frozen + ``extra="forbid"`` (K8).
    """

    model_config = _MODEL_CONFIG

    path: str
    note: str | None = None


class ConfigDocEdge(BaseModel):
    """One doc↔doc dependency edge on a :class:`ConfigDocument` (EPIC B).

    The mirror projection of the on-disk :class:`~custodex.config.DocEdge`: ``doc``
    is the upstream document id this one ``depends_on`` and ``type`` its role
    (depends/refines/implements/verifies, stored as a plain string so a new role
    never needs a migration). Frozen + ``extra="forbid"`` (K8).
    """

    model_config = _MODEL_CONFIG

    doc: str
    type: str = "depends"


class StoredDocEdge(BaseModel):
    """One doc↔doc edge FLATTENED into the reverse-lookup index (B-09).

    The projection of a :class:`ConfigDocument`'s ``depends_on`` into a standalone,
    indexable row: the downstream (``doc_id``) → upstream (``upstream_id``) edge of
    ``type``, scoped by ``(repo_id, sync_kind)`` exactly like the document it came
    from. ``ConfigDocEdge`` carries only ``doc``/``type`` (it lives nested under one
    document, which already supplies the downstream id + scope); ``StoredDocEdge``
    carries the full edge so a reverse query ("which docs depend on X") is answerable
    by indexing ``upstream_id`` alone — the O(1) lookup the SqlStore's
    ``config_doc_edges`` table provides, mirrored derive-on-read by the in-memory
    store. Frozen + ``extra="forbid"`` (K8).
    """

    model_config = _MODEL_CONFIG

    repo_id: str
    doc_id: str  # the downstream (dependent) document
    upstream_id: str  # the document it depends on (the reverse-lookup key)
    type: str = "depends"
    sync_kind: str


def _doc_edges_of(doc: ConfigDocument) -> list[StoredDocEdge]:
    """Flatten one document's ``depends_on`` into :class:`StoredDocEdge` rows (K10).

    The ONE projection both stores share: the SqlStore writes these on
    ``replace_config``; the in-memory store derives them on read — so the indexed
    table and the derived list are byte-identical (K6/K10).
    """
    return [
        StoredDocEdge(
            repo_id=doc.repo_id,
            doc_id=doc.doc_id,
            upstream_id=edge.doc,
            type=edge.type,
            sync_kind=doc.sync_kind,
        )
        for edge in doc.depends_on
    ]


class ConfigDocument(BaseModel):
    """One config document as synced from a repo's ``config/cdmon/`` (Y-01).

    The relationship data the central store persists per sync: which document
    (``doc_id``) lives where (``path``), for whom (``audience``), in which unit
    file, and what region keys it declares. ``sync_kind`` partitions the "git"
    (main baseline) view from the "local" (working-tree) view; ``ref`` pins the
    branch/commit it was synced from. ``context_refs`` carries the document's
    generation-context references (EDITOR E-03 — additive, K6: it round-trips in
    the JSON blob with NO migration, so pre-E-03 rows that lack it still parse and
    default to empty). Frozen + ``extra="forbid"`` — an audited artifact stored as
    the FULL JSON source of truth (K6/K8).
    """

    model_config = _MODEL_CONFIG

    repo_id: str
    doc_id: str
    path: str
    audience: str
    unit: str | None = None
    # EPIC OWN — ownership-of-record + the resolved accountable/durable (additive,
    # K6: rides in the JSON blob, NO migration; pre-OWN rows parse with None).
    # Populated by configsync._build_rows at sync; the GET /ownership route reads
    # these + the LIVE roster through ownership.detect_orphans, so a departure
    # cascades at read time across every repo (no re-sync needed).
    owner: str | None = None
    team: str | None = None
    dri: str | None = None
    accountable: str | None = None
    durable: str | None = None
    # EPIC SLA — last-reviewed stamp + the resolved (audience-aware) SLA, mirrored at
    # sync (additive, K6). GET /staleness grades `reviewed` vs the app clock + the
    # `sla_days` at READ time, so a doc goes stale on the next read with no re-sync.
    reviewed: str | None = None
    sla_days: int | None = None
    region_keys: tuple[str, ...] = ()
    context_refs: tuple[ConfigContextRef, ...] = ()
    # EPIC B — the document's declared doc↔doc dependency edges, mirrored at sync
    # (additive, K6: rides in the full JSON blob, NO migration; pre-EPIC-B rows
    # parse with the empty tuple). The GET /doc-graph route reads these to serve the
    # cross-repo dependency GRAPH; suspect STATUS stays repo-local (the doc files
    # live in the repo, K2), so the hub shows WHO-depends-on-WHAT, not freshness.
    depends_on: tuple[ConfigDocEdge, ...] = ()
    sync_kind: str
    ref: str | None = None
    synced_at: str


class ConfigCodeRef(BaseModel):
    """One code_ref under a :class:`ConfigDocument` (Y-01).

    A document points at one or more code locations (``path`` + the ``symbols``
    it owns there); the child rows of a document, scoped by ``sync_kind``. Frozen
    + ``extra="forbid"`` — the FULL JSON is the stored source of truth (K6/K8).
    """

    model_config = _MODEL_CONFIG

    repo_id: str
    doc_id: str
    path: str
    symbols: tuple[str, ...] = ()
    unit: str | None = None
    sync_kind: str


class SyncRun(BaseModel):
    """One sync invocation summary (Y-01).

    A history row recording a single ``replace_config`` sync: the git/local
    ``sync_kind``, the ref/branch/commit context, how many documents + code_refs
    it persisted, whether the baseline was fully synced, and an opaque ``drift``/
    coverage summary dict (stored verbatim in the JSON column). Frozen +
    ``extra="forbid"`` — an audited artifact stored as the FULL JSON (K6/K8).
    """

    model_config = _MODEL_CONFIG

    repo_id: str
    sync_kind: str
    ref: str | None = None
    branch: str | None = None
    head_commit: str | None = None
    main_commit: str | None = None
    commits_ahead: int = 0
    fully_synced: bool
    document_count: int
    code_ref_count: int
    drift: dict
    started_at: str
    finished_at: str


@runtime_checkable
class Store(Protocol):
    """The persistence boundary the routes depend on (the E-04 seam).

    E-03 implements it in memory; E-04 swaps in a DB-backed store behind the same
    Protocol. ``list_repos`` / ``records_for`` MUST be deterministically ordered
    (K10): insertion order for the in-memory store.
    """

    def add_repo(self, payload: RegistrationPayload) -> None: ...

    def get_repo(self, repo_id: str) -> RegisteredRepo | None: ...

    def list_repos(self) -> list[RegisteredRepo]: ...

    def add_record(self, repo_id: str, record: ReviewRecord) -> None: ...

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
        """Filter via the indexed columns (E-05); re-validate the FULL JSON (K6).

        All filters are AND-combined; ``None`` means "don't filter on this field".
        Ordering is the deterministic insertion order (K10); ``limit``/``offset``
        paginate over that order.
        """
        ...

    def resolutions_for_repo(
        self, repo_id: str, record_id: str | None = None
    ) -> list[ResolutionRecord]: ...

    def add_resolution(self, resolution: ResolutionRecord) -> None:
        """Append a human OUTCOME (F-04 write), linked to a record by ``record_id``.

        Both stores already implement this (an E-04 seed helper); F-04 promotes it onto
        the Protocol so the resolve route persists through the seam (K6 — the SHARED
        :class:`ResolutionRecord` is stored, not a DTO).
        """
        ...

    def coverage_for(self, repo_id: str) -> list[dict]: ...

    def add_coverage_snapshot(
        self, repo_id: str, captured_at: str, snapshot: dict
    ) -> None:
        """Append a coverage SNAPSHOT for a repo (T-02 ingest write).

        Both stores already implement this (an E-04 seed helper); T-02 promotes it
        onto the Protocol so the ``POST /repos/{id}/coverage`` route persists through
        the seam (K6). ``snapshot`` is the opaque JSON wire dict from
        :func:`custodex.coverage.coverage_snapshot`.
        """
        ...

    def add_graph_snapshot(
        self, repo_id: str, captured_at: str, snapshot: dict
    ) -> None:
        """Append a knowledge-graph SNAPSHOT for a repo (AGT-03 ingest write).

        The exact coverage-snapshot pattern: the graph is computed REPO-SIDE
        (where the doc bodies live — K2) and mirrored here as an opaque,
        versioned JSON dict (the :class:`custodex.kgraph.KnowledgeGraph` wire
        shape); the hub never re-derives it.
        """
        ...

    def graph_for(self, repo_id: str) -> dict | None:
        """The LATEST stored graph snapshot for a repo, or ``None`` when none."""
        ...

    def repo_token_hash(self, repo_id: str) -> str | None: ...

    def set_provider_secret(self, repo_id: str, sealed: bytes) -> None:
        """Persist the SEALED (opaque) git provider credential for a repo (GIT-02).

        ``sealed`` is the AES-256-GCM output of
        :meth:`custodex.secrets.SecretBox.seal`. The store keeps OPAQUE
        bytes and NEVER imports ``cryptography`` — sealing/opening happens at the
        route (the crypto-allowed ``[server]`` layer), so the store seam stays pure
        pydantic/stdlib. Parallel to ``repo_token_hash`` (a separate write so the
        reversible provider secret is isolated from the one-way token hash). A
        re-set rotates it in place; a repo that never sets one reads ``None``.
        """
        ...

    def repo_provider_secret(self, repo_id: str) -> bytes | None:
        """The repo's SEALED git provider credential, or ``None`` if unset/unknown."""
        ...

    # --- Y-01: config documents / code-refs / sync runs ---------------------

    def replace_config(
        self,
        repo_id: str,
        sync_kind: str,
        documents: list[ConfigDocument],
        code_refs: list[ConfigCodeRef],
    ) -> None:
        """Atomically REPLACE this repo's ``(repo_id, sync_kind)`` config rows (Y-01).

        Deletes every existing document + code_ref for THIS ``(repo_id, sync_kind)``
        scope ONLY, then inserts the new set — the idempotent upsert primitive a sync
        calls. The OTHER ``sync_kind``'s rows (e.g. "local" vs "git") are never
        touched. New rows are appended in the given order (insertion-order, K10).
        """
        ...

    def config_documents_for(
        self, repo_id: str, sync_kind: str | None = None
    ) -> list[ConfigDocument]:
        """This repo's config documents, optionally filtered by ``sync_kind`` (K10)."""
        ...

    def doc_edges_for(
        self,
        repo_id: str,
        *,
        sync_kind: str | None = None,
        upstream_id: str | None = None,
    ) -> list[StoredDocEdge]:
        """This repo's doc↔doc edges as flat rows (B-09 — the reverse-lookup index).

        The ``depends_on`` of every synced document, flattened into standalone
        :class:`StoredDocEdge` rows. ``sync_kind`` scopes to one synced view;
        ``upstream_id`` filters to the edges pointing AT that document — the O(1)
        "which docs depend on X" reverse query the ``config_doc_edges`` index serves.
        Insertion order: document order then in-document edge order (K10).
        """
        ...

    def code_refs_for(
        self,
        repo_id: str,
        doc_id: str | None = None,
        sync_kind: str | None = None,
    ) -> list[ConfigCodeRef]:
        """This repo's code_refs; optional ``doc_id``/``sync_kind`` filters (K10)."""
        ...

    def add_sync_run(self, run: SyncRun) -> None:
        """Append one :class:`SyncRun` history row (insertion order, K10)."""
        ...

    def latest_sync_run(
        self, repo_id: str, sync_kind: str | None = None
    ) -> SyncRun | None:
        """The MOST-RECENT sync run for this repo (by insertion), or ``None``.

        "Most recent" = the last inserted matching row (K10 — no time sort).
        """
        ...

    def sync_runs_for(
        self, repo_id: str, sync_kind: str | None = None
    ) -> list[SyncRun]:
        """This repo's sync runs, optionally filtered by ``sync_kind`` (K10)."""
        ...

    # --- EDITOR E-03: pending config edits (the staged "ticket" table) ------

    def add_config_edit(
        self, repo_id: str, edit: ConfigEdit, *, edit_id: str, created_at: str
    ) -> None:
        """Stage one typed :class:`ConfigEdit` as a ``pending`` row (insertion order).

        The FULL typed edit is stored as the JSON source of truth (K6); ``edit_id``
        is the ticket handle and ``created_at`` is injected (deterministic, K10).
        """
        ...

    def config_edits_for(
        self, repo_id: str, status: str | None = None
    ) -> list[StoredConfigEdit]:
        """This repo's staged edits, optionally filtered by ``status`` (K10 order)."""
        ...

    def mark_config_edits(
        self, repo_id: str, edit_ids: list[str], status: str, *, at: str
    ) -> None:
        """Flip the named edits to ``status`` and stamp ``applied_at`` = ``at`` (E-06).

        Scoped to this repo; only rows whose ``edit_id`` is in ``edit_ids`` change.
        """
        ...

    # --- EPIC OWN: the central roster (the accountability MIRROR) ------------

    def upsert_identity(self, identity: Identity) -> None:
        """Add or UPDATE a roster identity by ``name`` (insertion order, K10)."""
        ...

    def list_roster(self) -> list[Identity]:
        """Every roster identity in insertion order (K10)."""
        ...

    def mark_identity_departed(self, name: str, *, at: str) -> None:
        """Mark ``name`` departed (active=False, departed_at=at); no-op if unknown.

        The cross-repo cascade: every repo's ``GET /ownership`` recomputes orphans
        against the LIVE roster on READ, so one departure flips every document this
        identity is accountable for. ``at`` is the injected ISO timestamp (K10).
        """
        ...


class InMemoryStore:
    """A dict-backed :class:`Store` — deterministic, no DB (E-03; E-04 adds the DB).

    Repos and records key on ``repo_id``; dicts preserve insertion order so
    ``list_repos`` / ``records_for`` are deterministic (K10). A repeat
    :meth:`add_repo` for the same ``repo_id`` UPDATES in place (no reorder).
    """

    def __init__(self) -> None:
        self._repos: dict[str, RegisteredRepo] = {}
        self._records: dict[str, list[ReviewRecord]] = {}
        self._resolutions: list[ResolutionRecord] = []
        self._coverage: dict[str, list[dict]] = {}
        self._graphs: dict[str, list[dict]] = {}  # AGT-03 graph snapshots
        self._token_hashes: dict[str, str | None] = {}
        # GIT-02: per-repo SEALED (opaque bytes) git provider credential. Kept apart
        # from token_hashes so the reversible secret never mixes with the one-way
        # token hash; set by the route AFTER sealing (the store stores opaque bytes).
        self._provider_secrets: dict[str, bytes] = {}
        # Y-01: insertion-ordered lists (K10); filtered in Python on read.
        self._config_documents: list[ConfigDocument] = []
        self._config_code_refs: list[ConfigCodeRef] = []
        self._sync_runs: list[SyncRun] = []
        # EDITOR E-03: per-repo insertion-ordered pending edits (K10).
        self._config_edits: dict[str, list[StoredConfigEdit]] = {}
        # EPIC OWN: the central roster, keyed by identity name (insertion order, K10).
        self._roster: dict[str, Identity] = {}

    def add_repo(self, payload: RegistrationPayload) -> None:
        repo_id = payload.repo.repo_id
        self._repos[repo_id] = RegisteredRepo(
            repo=effective_identity(payload),
            default_branch=payload.default_branch,
            description=payload.description,
        )
        # The plaintext token is NEVER kept — only its hash (E-06). A re-register that
        # carries a token rotates the hash; one that omits it leaves the prior hash.
        if payload.auth_token is not None:
            self._token_hashes[repo_id] = hash_token(payload.auth_token)
        else:
            self._token_hashes.setdefault(repo_id, None)

    def get_repo(self, repo_id: str) -> RegisteredRepo | None:
        return self._repos.get(repo_id)

    def list_repos(self) -> list[RegisteredRepo]:
        return list(self._repos.values())

    def add_record(self, repo_id: str, record: ReviewRecord) -> None:
        self._records.setdefault(repo_id, []).append(record)

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
        rows = [
            r
            for r in self._records.get(repo_id, [])
            if (verdict is None or r.verdict.value == verdict)
            and (drift_kind is None or r.drift_kind == drift_kind)
            and (audience is None or r.audience == audience)
            and (doc_id is None or r.doc_id == doc_id)
        ]
        end = None if limit is None else offset + limit
        return rows[offset:end]

    def resolutions_for_repo(
        self, repo_id: str, record_id: str | None = None
    ) -> list[ResolutionRecord]:
        record_ids = {r.record_id for r in self._records.get(repo_id, [])}
        return [
            res
            for res in self._resolutions
            if res.record_id in record_ids
            and (record_id is None or res.record_id == record_id)
        ]

    def coverage_for(self, repo_id: str) -> list[dict]:
        return list(self._coverage.get(repo_id, []))

    def repo_token_hash(self, repo_id: str) -> str | None:
        return self._token_hashes.get(repo_id)

    def set_provider_secret(self, repo_id: str, sealed: bytes) -> None:
        # Only for a registered repo (parity with SqlStore, which updates an
        # existing row): a dangling secret for an unknown repo is silently ignored.
        if repo_id in self._repos:
            self._provider_secrets[repo_id] = sealed

    def repo_provider_secret(self, repo_id: str) -> bytes | None:
        return self._provider_secrets.get(repo_id)

    # --- Protocol write (F-04) + seed helpers (parity with SqlStore) --------

    def add_resolution(self, resolution: ResolutionRecord) -> None:
        self._resolutions.append(resolution)

    def add_coverage_snapshot(
        self, repo_id: str, captured_at: str, snapshot: dict
    ) -> None:
        self._coverage.setdefault(repo_id, []).append(snapshot)

    def add_graph_snapshot(
        self, repo_id: str, captured_at: str, snapshot: dict
    ) -> None:
        self._graphs.setdefault(repo_id, []).append(snapshot)

    def graph_for(self, repo_id: str) -> dict | None:
        snapshots = self._graphs.get(repo_id)
        return snapshots[-1] if snapshots else None

    # --- Y-01: config documents / code-refs / sync runs ---------------------

    def replace_config(
        self,
        repo_id: str,
        sync_kind: str,
        documents: list[ConfigDocument],
        code_refs: list[ConfigCodeRef],
    ) -> None:
        # Drop ONLY this (repo_id, sync_kind) scope's rows, preserving every other
        # scope's insertion order; then append the new set (K10).
        self._config_documents = [
            d
            for d in self._config_documents
            if not (d.repo_id == repo_id and d.sync_kind == sync_kind)
        ]
        self._config_code_refs = [
            c
            for c in self._config_code_refs
            if not (c.repo_id == repo_id and c.sync_kind == sync_kind)
        ]
        self._config_documents.extend(documents)
        self._config_code_refs.extend(code_refs)

    def config_documents_for(
        self, repo_id: str, sync_kind: str | None = None
    ) -> list[ConfigDocument]:
        return [
            d
            for d in self._config_documents
            if d.repo_id == repo_id and (sync_kind is None or d.sync_kind == sync_kind)
        ]

    def doc_edges_for(
        self,
        repo_id: str,
        *,
        sync_kind: str | None = None,
        upstream_id: str | None = None,
    ) -> list[StoredDocEdge]:
        # Derive the flat edge rows on read from the synced documents (the SqlStore
        # keeps a real indexed table; this in-memory store derives the SAME list).
        out: list[StoredDocEdge] = []
        for d in self._config_documents:
            if d.repo_id != repo_id or (
                sync_kind is not None and d.sync_kind != sync_kind
            ):
                continue
            out.extend(
                edge
                for edge in _doc_edges_of(d)
                if upstream_id is None or edge.upstream_id == upstream_id
            )
        return out

    def code_refs_for(
        self,
        repo_id: str,
        doc_id: str | None = None,
        sync_kind: str | None = None,
    ) -> list[ConfigCodeRef]:
        return [
            c
            for c in self._config_code_refs
            if c.repo_id == repo_id
            and (doc_id is None or c.doc_id == doc_id)
            and (sync_kind is None or c.sync_kind == sync_kind)
        ]

    def add_sync_run(self, run: SyncRun) -> None:
        self._sync_runs.append(run)

    def latest_sync_run(
        self, repo_id: str, sync_kind: str | None = None
    ) -> SyncRun | None:
        matches = self.sync_runs_for(repo_id, sync_kind)
        return matches[-1] if matches else None

    def sync_runs_for(
        self, repo_id: str, sync_kind: str | None = None
    ) -> list[SyncRun]:
        return [
            r
            for r in self._sync_runs
            if r.repo_id == repo_id and (sync_kind is None or r.sync_kind == sync_kind)
        ]

    # --- EDITOR E-03: pending config edits ----------------------------------

    def add_config_edit(
        self, repo_id: str, edit: ConfigEdit, *, edit_id: str, created_at: str
    ) -> None:
        self._config_edits.setdefault(repo_id, []).append(
            StoredConfigEdit(
                edit_id=edit_id,
                status="pending",
                created_at=created_at,
                applied_at=None,
                edit=edit,
            )
        )

    def config_edits_for(
        self, repo_id: str, status: str | None = None
    ) -> list[StoredConfigEdit]:
        return [
            e
            for e in self._config_edits.get(repo_id, [])
            if status is None or e.status == status
        ]

    def mark_config_edits(
        self, repo_id: str, edit_ids: list[str], status: str, *, at: str
    ) -> None:
        targets = set(edit_ids)
        rows = self._config_edits.get(repo_id, [])
        for i, row in enumerate(rows):
            if row.edit_id in targets:
                rows[i] = row.model_copy(update={"status": status, "applied_at": at})

    # --- EPIC OWN: the central roster ---------------------------------------

    def upsert_identity(self, identity: Identity) -> None:
        self._roster[identity.name] = identity

    def list_roster(self) -> list[Identity]:
        return list(self._roster.values())

    def mark_identity_departed(self, name: str, *, at: str) -> None:
        existing = self._roster.get(name)
        if existing is not None:
            self._roster[name] = existing.model_copy(
                update={"active": False, "departed_at": at}
            )
