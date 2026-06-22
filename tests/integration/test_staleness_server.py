"""EPIC SLA (SLA-03) — the per-repo GET /staleness view (read-time, both stores).

The synced documents carry `reviewed` + the resolved `sla_days`; the route grades them
against the app clock at READ time (so a doc goes stale on the next read with no
re-sync), deduped by doc_id, FRESH omitted unless asked. Offline (K4), deterministic.

Features: FEAT-STALENESS-005, FEAT-STALENESS-006
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")
pytest.importorskip("sqlalchemy", reason="the [server] extra is not installed")

from fastapi.testclient import TestClient  # noqa: E402

from code_doc_monitor.registry import RegistrationPayload  # noqa: E402
from code_doc_monitor.server import InMemoryStore, create_app  # noqa: E402
from code_doc_monitor.server.db import (  # noqa: E402
    SqlStore,
    create_all,
    engine_from_url,
)
from code_doc_monitor.server.store import ConfigDocument, Store  # noqa: E402
from code_doc_monitor.sinks import RepoIdentity  # noqa: E402

_REPO = "acme/widget"
_NOW = "2026-06-22T00:00:00Z"


def _make_store(kind: str) -> Store:
    if kind == "memory":
        return InMemoryStore()
    engine = engine_from_url("sqlite:///:memory:")
    create_all(engine)
    return SqlStore(engine)


def _register(store: Store) -> None:
    store.add_repo(
        RegistrationPayload(
            repo=RepoIdentity(
                repo_id=_REPO,
                repo_name="widget",
                repo_url="https://example.invalid/acme/widget",
                commit="deadbeef",
            ),
            default_branch="main",
            auth_token=None,
        )
    )


def _doc(
    doc_id: str,
    *,
    reviewed: str | None,
    sla_days: int = 90,
    sync_kind: str = "git",
) -> ConfigDocument:
    return ConfigDocument(
        repo_id=_REPO,
        doc_id=doc_id,
        path=f"docs/{doc_id}.md",
        audience="eng-guide",
        reviewed=reviewed,
        sla_days=sla_days,
        sync_kind=sync_kind,
        synced_at=_NOW,
    )


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_staleness_route_grades_at_read_time(kind: str) -> None:
    store = _make_store(kind)
    _register(store)
    store.replace_config(
        _REPO,
        "git",
        [
            _doc("a-stale", reviewed="2026-01-01"),  # 172 days ago > 90
            _doc("b-fresh", reviewed="2026-06-20"),  # 2 days ago < 90
            _doc("c-never", reviewed=None),  # no stamp
        ],
        [],
    )
    client = TestClient(create_app(store, clock=lambda: _NOW))

    body = client.get(f"/repos/{_REPO}/staleness").json()
    statuses = {f["doc_id"]: f["status"] for f in body["findings"]}
    assert statuses == {
        "a-stale": "stale",
        "c-never": "never_reviewed",
    }  # fresh omitted
    assert body["stale_count"] == 2
    assert body["now"] == _NOW
    # the stale finding carries the age + sla
    stale = next(f for f in body["findings"] if f["doc_id"] == "a-stale")
    assert stale["age_days"] == 172 and stale["sla_days"] == 90

    # include_fresh surfaces every doc (sorted by doc_id)
    full = client.get(f"/repos/{_REPO}/staleness?include_fresh=true").json()
    assert [f["doc_id"] for f in full["findings"]] == ["a-stale", "b-fresh", "c-never"]


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_staleness_dedups_doc_across_sync_kinds(kind: str) -> None:
    store = _make_store(kind)
    _register(store)
    store.replace_config(_REPO, "git", [_doc("d", reviewed=None)], [])
    store.replace_config(
        _REPO, "local", [_doc("d", reviewed=None, sync_kind="local")], []
    )
    client = TestClient(create_app(store, clock=lambda: _NOW))
    body = client.get(f"/repos/{_REPO}/staleness").json()
    assert [f["doc_id"] for f in body["findings"]] == ["d"]  # deduped


def test_staleness_unknown_repo_is_404() -> None:
    client = TestClient(create_app(InMemoryStore(), clock=lambda: _NOW))
    assert client.get("/repos/nope/staleness").status_code == 404
