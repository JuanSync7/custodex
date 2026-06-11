"""Store-parity suite for the Y-01 config/code-ref/sync-run persistence layer.

The central store gained six methods (``replace_config`` + the document/code-ref/
sync-run reads) with TWO implementations behind the SAME ``Store`` Protocol: the
dict-backed :class:`~code_doc_monitor.server.store.InMemoryStore` and the
SQLAlchemy :class:`~code_doc_monitor.server.db.SqlStore` (Postgres-first; SQLite for
the offline gate, K4). This module asserts byte-for-byte PARITY: every test is
PARAMETRIZED over both backends via the ``store`` fixture, so the SAME behavior is
proven for in-memory AND the real SQLite-backed DB store — covering replace
insert+REPLACE (no stragglers; the other ``sync_kind`` untouched), the filters,
``latest_sync_run`` recency, empty results, and the JSON round-trip of the tuple
fields (``region_keys``/``symbols``) and the opaque ``drift`` dict.

Gated on the ``[server]`` extra (sqlalchemy); SKIPS without it. Fully offline and
deterministic (K4/K10): in-memory SQLite, injected timestamps.

Features: FEAT-SERVER-005, FEAT-SERVER-006, FEAT-SERVER-009
Features: FEAT-SERVER-010, FEAT-SERVER-011
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "sqlalchemy", reason="the [server] extra (sqlalchemy) is not installed"
)

from code_doc_monitor.server.db import (  # noqa: E402
    SqlStore,
    create_all,
    engine_from_url,
)
from code_doc_monitor.server.edits import (  # noqa: E402
    AddCodeRefEdit,
    CreateDocEdit,
    EditCodeRef,
    EditContextRef,
    EditDocStyle,
    SetContextRefsEdit,
    SetDocStyleEdit,
)
from code_doc_monitor.server.store import (  # noqa: E402
    ConfigCodeRef,
    ConfigContextRef,
    ConfigDocument,
    InMemoryStore,
    Store,
    SyncRun,
)

_REPO = "acme/widget"
_NOW = "2026-06-07T00:00:00Z"


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #
def _doc(
    doc_id: str,
    *,
    repo_id: str = _REPO,
    sync_kind: str = "git",
    audience: str = "eng-guide",
    unit: str | None = "foundation",
    region_keys: tuple[str, ...] = (),
    ref: str | None = "main",
    synced_at: str = _NOW,
) -> ConfigDocument:
    return ConfigDocument(
        repo_id=repo_id,
        doc_id=doc_id,
        path=f"docs/api/{doc_id}.md",
        audience=audience,
        unit=unit,
        region_keys=region_keys,
        sync_kind=sync_kind,
        ref=ref,
        synced_at=synced_at,
    )


def _ref(
    doc_id: str,
    *,
    repo_id: str = _REPO,
    sync_kind: str = "git",
    path: str = "src/mod.py",
    symbols: tuple[str, ...] = (),
    unit: str | None = "foundation",
) -> ConfigCodeRef:
    return ConfigCodeRef(
        repo_id=repo_id,
        doc_id=doc_id,
        path=path,
        symbols=symbols,
        unit=unit,
        sync_kind=sync_kind,
    )


def _run(
    *,
    repo_id: str = _REPO,
    sync_kind: str = "git",
    ref: str | None = "main",
    branch: str | None = "main",
    head_commit: str | None = "deadbeef",
    main_commit: str | None = "deadbeef",
    commits_ahead: int = 0,
    fully_synced: bool = True,
    document_count: int = 1,
    code_ref_count: int = 1,
    drift: dict | None = None,
    started_at: str = _NOW,
    finished_at: str = "2026-06-07T00:00:05Z",
) -> SyncRun:
    return SyncRun(
        repo_id=repo_id,
        sync_kind=sync_kind,
        ref=ref,
        branch=branch,
        head_commit=head_commit,
        main_commit=main_commit,
        commits_ahead=commits_ahead,
        fully_synced=fully_synced,
        document_count=document_count,
        code_ref_count=code_ref_count,
        drift=drift if drift is not None else {"region": 0, "kinds": ["REGION"]},
        started_at=started_at,
        finished_at=finished_at,
    )


# --------------------------------------------------------------------------- #
# the parametrized store fixture — the SAME contract over EACH implementation
# --------------------------------------------------------------------------- #
def _make_store(kind: str) -> Store:
    if kind == "memory":
        return InMemoryStore()
    engine = engine_from_url("sqlite:///:memory:")
    create_all(engine)
    return SqlStore(engine)


@pytest.fixture(params=["memory", "sql"])
def store(request: pytest.FixtureRequest) -> Store:
    """A fresh Store per implementation; every test runs over BOTH (K4)."""
    return _make_store(request.param)


# --------------------------------------------------------------------------- #
# replace_config — insert
# --------------------------------------------------------------------------- #
def test_replace_config_inserts_documents_and_code_refs(store: Store) -> None:
    docs = [_doc("alpha", region_keys=("symbols", "usage")), _doc("beta")]
    refs = [
        _ref("alpha", symbols=("compute", "render")),
        _ref("alpha", path="src/other.py", symbols=("helper",)),
        _ref("beta"),
    ]
    store.replace_config(_REPO, "git", docs, refs)

    assert store.config_documents_for(_REPO) == docs
    assert store.code_refs_for(_REPO) == refs


def test_replace_config_round_trips_tuple_fields(store: Store) -> None:
    # region_keys / symbols are tuples — they must survive the JSON column round-trip
    # as tuples (the model re-validates them), not as lists.
    doc = _doc("alpha", region_keys=("symbols", "usage", "examples"))
    ref = _ref("alpha", symbols=("compute", "render", "load"))
    store.replace_config(_REPO, "git", [doc], [ref])

    got_doc = store.config_documents_for(_REPO)[0]
    got_ref = store.code_refs_for(_REPO)[0]
    assert got_doc.region_keys == ("symbols", "usage", "examples")
    assert got_ref.symbols == ("compute", "render", "load")
    assert isinstance(got_doc.region_keys, tuple)
    assert isinstance(got_ref.symbols, tuple)


# --------------------------------------------------------------------------- #
# replace_config — REPLACE (no stragglers; other sync_kind untouched)
# --------------------------------------------------------------------------- #
def test_replace_config_replaces_with_no_stragglers(store: Store) -> None:
    store.replace_config(
        _REPO,
        "git",
        [_doc("alpha"), _doc("beta"), _doc("gamma")],
        [_ref("alpha"), _ref("beta"), _ref("gamma")],
    )
    # second sync with FEWER rows must leave NO stragglers from the first.
    store.replace_config(_REPO, "git", [_doc("alpha")], [_ref("alpha")])

    assert [d.doc_id for d in store.config_documents_for(_REPO)] == ["alpha"]
    assert [c.doc_id for c in store.code_refs_for(_REPO)] == ["alpha"]


def test_replace_config_does_not_touch_other_sync_kind(store: Store) -> None:
    store.replace_config(_REPO, "git", [_doc("alpha", sync_kind="git")], [])
    store.replace_config(
        _REPO,
        "local",
        [_doc("beta", sync_kind="local")],
        [_ref("beta", sync_kind="local")],
    )
    # replacing "git" must leave the "local" scope's rows intact.
    store.replace_config(_REPO, "git", [_doc("alpha2", sync_kind="git")], [])

    git_docs = [d.doc_id for d in store.config_documents_for(_REPO, "git")]
    local_docs = [d.doc_id for d in store.config_documents_for(_REPO, "local")]
    assert git_docs == ["alpha2"]
    assert local_docs == ["beta"]
    assert [c.doc_id for c in store.code_refs_for(_REPO, sync_kind="local")] == ["beta"]


def test_replace_config_does_not_touch_other_repo(store: Store) -> None:
    store.replace_config("other/repo", "git", [_doc("x", repo_id="other/repo")], [])
    store.replace_config(_REPO, "git", [_doc("alpha")], [])
    store.replace_config(_REPO, "git", [_doc("alpha2")], [])

    assert [d.doc_id for d in store.config_documents_for("other/repo")] == ["x"]


# --------------------------------------------------------------------------- #
# filters
# --------------------------------------------------------------------------- #
def test_config_documents_for_filters_by_sync_kind(store: Store) -> None:
    store.replace_config(_REPO, "git", [_doc("alpha", sync_kind="git")], [])
    store.replace_config(_REPO, "local", [_doc("beta", sync_kind="local")], [])

    assert [d.doc_id for d in store.config_documents_for(_REPO, "git")] == ["alpha"]
    assert [d.doc_id for d in store.config_documents_for(_REPO, "local")] == ["beta"]
    assert {d.doc_id for d in store.config_documents_for(_REPO)} == {"alpha", "beta"}


def test_code_refs_for_filters_by_doc_id_and_sync_kind(store: Store) -> None:
    store.replace_config(
        _REPO,
        "git",
        [_doc("alpha"), _doc("beta")],
        [_ref("alpha"), _ref("alpha", path="src/two.py"), _ref("beta")],
    )
    store.replace_config(
        _REPO,
        "local",
        [_doc("alpha", sync_kind="local")],
        [_ref("alpha", sync_kind="local")],
    )

    assert len(store.code_refs_for(_REPO, doc_id="alpha", sync_kind="git")) == 2
    assert len(store.code_refs_for(_REPO, doc_id="beta")) == 1
    assert len(store.code_refs_for(_REPO, sync_kind="local")) == 1
    assert len(store.code_refs_for(_REPO)) == 4


# --------------------------------------------------------------------------- #
# empty results
# --------------------------------------------------------------------------- #
def test_empty_results_on_unknown_repo(store: Store) -> None:
    assert store.config_documents_for("ghost") == []
    assert store.code_refs_for("ghost") == []
    assert store.sync_runs_for("ghost") == []
    assert store.latest_sync_run("ghost") is None


def test_empty_results_on_unmatched_filter(store: Store) -> None:
    store.replace_config(_REPO, "git", [_doc("alpha")], [_ref("alpha")])
    assert store.config_documents_for(_REPO, "local") == []
    assert store.code_refs_for(_REPO, doc_id="ghost") == []
    assert store.latest_sync_run(_REPO, "local") is None


# --------------------------------------------------------------------------- #
# sync runs — add / latest (recency) / list
# --------------------------------------------------------------------------- #
def test_add_sync_run_and_sync_runs_for_preserve_insertion_order(store: Store) -> None:
    runs = [
        _run(sync_kind="git", head_commit="c1"),
        _run(sync_kind="local", head_commit="c2", commits_ahead=2, fully_synced=False),
        _run(sync_kind="git", head_commit="c3"),
    ]
    for r in runs:
        store.add_sync_run(r)

    assert store.sync_runs_for(_REPO) == runs
    assert [r.head_commit for r in store.sync_runs_for(_REPO, "git")] == ["c1", "c3"]


def test_latest_sync_run_is_most_recent_by_insertion(store: Store) -> None:
    store.add_sync_run(_run(sync_kind="git", head_commit="c1"))
    store.add_sync_run(_run(sync_kind="local", head_commit="c2"))
    store.add_sync_run(_run(sync_kind="git", head_commit="c3"))

    # latest overall = last inserted; latest per-kind = last inserted of that kind.
    assert store.latest_sync_run(_REPO).head_commit == "c3"
    assert store.latest_sync_run(_REPO, "git").head_commit == "c3"
    assert store.latest_sync_run(_REPO, "local").head_commit == "c2"


def test_sync_run_round_trips_opaque_drift_dict(store: Store) -> None:
    drift = {
        "region": 3,
        "hash": 1,
        "kinds": ["REGION", "HASH"],
        "nested": {"by_audience": {"eng-guide": 2}},
    }
    run = _run(drift=drift, fully_synced=False, commits_ahead=4)
    store.add_sync_run(run)

    got = store.latest_sync_run(_REPO)
    assert got == run
    assert got.drift == drift
    assert got.fully_synced is False
    assert got.commits_ahead == 4


# --------------------------------------------------------------------------- #
# explicit cross-backend equivalence (the parity guarantee, both stores at once)
# --------------------------------------------------------------------------- #
def test_inmemory_and_sql_return_identical_results() -> None:
    mem = _make_store("memory")
    sql = _make_store("sql")

    docs = [_doc("alpha", region_keys=("a", "b")), _doc("beta", sync_kind="git")]
    refs = [_ref("alpha", symbols=("x", "y")), _ref("beta")]
    runs = [_run(head_commit="c1"), _run(sync_kind="local", head_commit="c2")]

    for s in (mem, sql):
        s.replace_config(_REPO, "git", docs, refs)
        for r in runs:
            s.add_sync_run(r)

    assert mem.config_documents_for(_REPO) == sql.config_documents_for(_REPO)
    assert mem.code_refs_for(_REPO, doc_id="alpha") == sql.code_refs_for(
        _REPO, doc_id="alpha"
    )
    assert mem.sync_runs_for(_REPO) == sql.sync_runs_for(_REPO)
    assert mem.latest_sync_run(_REPO) == sql.latest_sync_run(_REPO)
    assert mem.latest_sync_run(_REPO, "git") == sql.latest_sync_run(_REPO, "git")


# --------------------------------------------------------------------------- #
# EDITOR E-03: ConfigDocument.context_refs round-trips through BOTH stores
# (additive K6 — the field lives in the JSON blob; a doc carrying it must
# survive replace_config → config_documents_for unchanged on memory AND sql).
# --------------------------------------------------------------------------- #
def test_config_document_context_refs_round_trip(store: Store) -> None:
    doc = _doc("alpha").model_copy(
        update={
            "context_refs": (
                ConfigContextRef(path="docs/api/core-api.md", note="full reference"),
                ConfigContextRef(path="src/engine.py"),  # note=None
            )
        }
    )
    store.replace_config(_REPO, "git", [doc], [])

    got = store.config_documents_for(_REPO)[0]
    assert got == doc
    assert got.context_refs == doc.context_refs
    assert got.context_refs[0].note == "full reference"
    assert got.context_refs[1].note is None
    assert isinstance(got.context_refs, tuple)


def test_config_document_without_context_refs_defaults_empty(store: Store) -> None:
    # A doc built with no context_refs (the pre-E-03 shape) defaults to () and still
    # round-trips — the additive field never breaks the existing parity (K6).
    doc = _doc("beta")
    store.replace_config(_REPO, "git", [doc], [])
    assert store.config_documents_for(_REPO)[0].context_refs == ()


# --------------------------------------------------------------------------- #
# EDITOR E-03: config_edits store-parity (add / list / status filter / mark /
# insertion order / unknown-repo), parametrized over BOTH stores.
# --------------------------------------------------------------------------- #
def _create_doc_edit(doc_id: str = "guide") -> CreateDocEdit:
    return CreateDocEdit(
        unit="core",
        doc_id=doc_id,
        path=f"docs/guide/{doc_id}.md",
        audience="user-guide",
        code_refs=(EditCodeRef(path="src/m.py", symbols=("Task",), lines="1-40"),),
        context_refs=(EditContextRef(path="docs/api/core-api.md", note="ref"),),
        doc_style=EditDocStyle(tone="friendly"),
    )


def test_add_config_edit_then_config_edits_for_returns_it(store: Store) -> None:
    edit = _create_doc_edit()
    store.add_config_edit(_REPO, edit, edit_id="e1", created_at=_NOW)

    rows = store.config_edits_for(_REPO)
    assert len(rows) == 1
    row = rows[0]
    assert row.edit_id == "e1"
    assert row.status == "pending"
    assert row.created_at == _NOW
    assert row.applied_at is None
    assert row.edit == edit  # the typed union re-validates byte-for-byte


def test_config_edits_for_status_filter(store: Store) -> None:
    store.add_config_edit(_REPO, _create_doc_edit("a"), edit_id="e1", created_at=_NOW)
    store.add_config_edit(_REPO, _create_doc_edit("b"), edit_id="e2", created_at=_NOW)
    store.mark_config_edits(_REPO, ["e1"], "applied", at="2026-06-08T00:00:00Z")

    assert [r.edit_id for r in store.config_edits_for(_REPO, "pending")] == ["e2"]
    assert [r.edit_id for r in store.config_edits_for(_REPO, "applied")] == ["e1"]
    assert [r.edit_id for r in store.config_edits_for(_REPO)] == ["e1", "e2"]
    assert store.config_edits_for(_REPO, "discarded") == []


def test_mark_config_edits_flips_status_and_stamps_applied_at(store: Store) -> None:
    store.add_config_edit(_REPO, _create_doc_edit("a"), edit_id="e1", created_at=_NOW)
    store.add_config_edit(_REPO, _create_doc_edit("b"), edit_id="e2", created_at=_NOW)
    at = "2026-06-08T12:00:00Z"
    store.mark_config_edits(_REPO, ["e1", "e2"], "applied", at=at)

    rows = store.config_edits_for(_REPO)
    assert all(r.status == "applied" for r in rows)
    assert all(r.applied_at == at for r in rows)
    # created_at is preserved (only status + applied_at change).
    assert all(r.created_at == _NOW for r in rows)


def test_mark_config_edits_only_targets_named_ids(store: Store) -> None:
    store.add_config_edit(_REPO, _create_doc_edit("a"), edit_id="e1", created_at=_NOW)
    store.add_config_edit(_REPO, _create_doc_edit("b"), edit_id="e2", created_at=_NOW)
    store.mark_config_edits(_REPO, ["e2"], "discarded", at=_NOW)

    by_id = {r.edit_id: r for r in store.config_edits_for(_REPO)}
    assert by_id["e1"].status == "pending"
    assert by_id["e1"].applied_at is None
    assert by_id["e2"].status == "discarded"


def test_config_edits_preserve_insertion_order(store: Store) -> None:
    for i in range(5):
        store.add_config_edit(
            _REPO, _create_doc_edit(f"d{i}"), edit_id=f"e{i}", created_at=_NOW
        )
    assert [r.edit_id for r in store.config_edits_for(_REPO)] == [
        "e0",
        "e1",
        "e2",
        "e3",
        "e4",
    ]


def test_config_edits_for_unknown_repo_is_empty(store: Store) -> None:
    # Matches the sibling unknown-repo behavior: an empty list, never a raise (K8 is
    # loud on bad DATA, but an unknown repo_id is just "no rows" per-repo keying).
    assert store.config_edits_for("ghost") == []
    # mark on an unknown repo / unknown id is a quiet no-op (nothing matches).
    store.mark_config_edits("ghost", ["nope"], "applied", at=_NOW)
    assert store.config_edits_for("ghost") == []


def test_config_edits_scoped_per_repo(store: Store) -> None:
    store.add_config_edit(_REPO, _create_doc_edit("a"), edit_id="e1", created_at=_NOW)
    store.add_config_edit(
        "other/repo", _create_doc_edit("b"), edit_id="e2", created_at=_NOW
    )
    assert [r.edit_id for r in store.config_edits_for(_REPO)] == ["e1"]
    assert [r.edit_id for r in store.config_edits_for("other/repo")] == ["e2"]


def test_config_edits_all_action_payloads_round_trip(store: Store) -> None:
    # Each action variant of the tagged union must survive the JSON round-trip on
    # both stores via the discriminator.
    edits = [
        _create_doc_edit("create"),
        AddCodeRefEdit(unit="core", doc_id="d", ref=EditCodeRef(path="src/x.py")),
        SetContextRefsEdit(
            unit="core",
            doc_id="d",
            context_refs=(EditContextRef(path="docs/ref.md", note="n"),),
        ),
        SetDocStyleEdit(doc_id="d", doc_style=EditDocStyle(vocabulary="precise")),
    ]
    for i, e in enumerate(edits):
        store.add_config_edit(_REPO, e, edit_id=f"e{i}", created_at=_NOW)
    got = [r.edit for r in store.config_edits_for(_REPO)]
    assert got == edits


def test_inmemory_and_sql_config_edits_identical() -> None:
    mem = _make_store("memory")
    sql = _make_store("sql")
    edits = [_create_doc_edit("a"), _create_doc_edit("b")]
    for s in (mem, sql):
        for i, e in enumerate(edits):
            s.add_config_edit(_REPO, e, edit_id=f"e{i}", created_at=_NOW)
        s.mark_config_edits(_REPO, ["e0"], "applied", at="2026-06-08T00:00:00Z")

    assert mem.config_edits_for(_REPO) == sql.config_edits_for(_REPO)
    assert mem.config_edits_for(_REPO, "pending") == sql.config_edits_for(
        _REPO, "pending"
    )
