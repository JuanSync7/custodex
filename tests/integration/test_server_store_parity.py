"""Store-parity HTTP integration suite — every route through BOTH Store backends.

The central server is a thin FastAPI shell over the ``Store`` Protocol
(``custodex.server.store``), which has TWO production implementations: the
in-process
:class:`~custodex.server.InMemoryStore` and the persistent
:class:`~custodex.server.db.SqlStore` (E-04, Postgres-first; SQLite for the
offline gate, K4). ``test_server.py`` exercises every route through ``TestClient`` —
but only over ``InMemoryStore``; ``test_db.py`` exercises ``SqlStore`` — but mostly
through DIRECT store-method calls, not through HTTP. That left the HTTP↔DB boundary
(serialization, the DI seam, the auth guard, the JSON column round-trip) untested for
10 of the 13 routes.

This module closes that gap: EVERY test here is PARAMETRIZED over both stores via the
``client`` fixture, so the SAME request/response contract is asserted against the
in-memory store AND the real SQLite-backed DB store through the actual FastAPI app. A
bug that only manifests over real DB I/O (a missing index, a transaction boundary, a
JSON column that doesn't round-trip a tuple, a filter pushed down wrong) now fails the
offline gate. It is the "proper full integration test" the two-implementation seam
demands.

Gated on the ``[server]`` extra (fastapi + sqlalchemy); SKIPS without it, like
``test_server.py``/``test_db.py``. ``.venv`` has both, so it RUNS here. Fully offline
and deterministic (K4/K10): in-memory SQLite, injected timestamps, the mock backend.

Features: FEAT-SERVER-005, FEAT-SERVER-006, FEAT-SERVER-002, FEAT-SERVER-003
Features: FEAT-SERVER-004, FEAT-SERVER-008, FEAT-RECORD-006, FEAT-RECORD-010
Features: FEAT-COVERAGE-010, FEAT-PR-009
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")
pytest.importorskip(
    "sqlalchemy", reason="the [server] extra (sqlalchemy) is not installed"
)

from fastapi.testclient import TestClient  # noqa: E402

from custodex.registry import RegistrationPayload  # noqa: E402
from custodex.schema import (  # noqa: E402
    ProposedFix,
    Resolution,
    ResolutionRecord,
    ReviewRecord,
    Verdict,
)
from custodex.server import InMemoryStore, create_app  # noqa: E402
from custodex.server.db import (  # noqa: E402
    SqlStore,
    create_all,
    engine_from_url,
)
from custodex.server.store import Store  # noqa: E402
from custodex.sinks import IngestEnvelope, RepoIdentity  # noqa: E402

_REPO = "acme/widget"
_TOKEN = "s3cret-token"  # the per-repo bearer token the suite registers with
_NOW = "2026-06-05T00:00:00Z"


# --------------------------------------------------------------------------- #
# shared builders (mirror test_server.py / test_db.py so shapes match exactly)
# --------------------------------------------------------------------------- #
def _identity(repo_id: str = _REPO) -> RepoIdentity:
    return RepoIdentity(
        repo_id=repo_id,
        repo_name="widget",
        repo_url="https://example.invalid/acme/widget",
        commit="deadbeef",
    )


def _registration(repo_id: str = _REPO, auth_token: str | None = _TOKEN) -> dict:
    return RegistrationPayload(
        repo=_identity(repo_id),
        default_branch="main",
        description="the widget service",
        auth_token=auth_token,
    ).model_dump(mode="json")


def _record(
    repo_id: str = _REPO,
    *,
    record_id: str = "abc123def456",
    doc_id: str = "pipeline",
    audience: str = "eng-guide",
    drift_kind: str = "REGION",
    verdict: Verdict = Verdict.FIX,
    detected_at: str = _NOW,
    resolved_at: str = "2026-06-05T00:00:30Z",
) -> ReviewRecord:
    return ReviewRecord(
        record_id=record_id,
        doc_id=doc_id,
        doc_path=f"docs/api/{doc_id}.md",
        audience=audience,
        drift_kind=drift_kind,
        drift_detail="signature moved",
        cause="public signature changed",
        verdict=verdict,
        fix=ProposedFix(rationale="regenerate the region"),
        surface_hash="0" * 16,
        backend_kind="mock",
        detected_at=detected_at,
        resolved_at=resolved_at,
        config_snapshot={"repo_id": repo_id},
        source_sha="cafebabe",
    )


def _envelope(record: ReviewRecord, repo_id: str = _REPO) -> dict:
    return IngestEnvelope(repo=_identity(repo_id), record=record).model_dump(
        mode="json"
    )


def _resolution(
    record_id: str = "abc123def456",
    resolution: Resolution = Resolution.ACCEPTED,
    resolved_at: str = "2026-06-05T01:00:00Z",
) -> dict:
    return ResolutionRecord(
        record_id=record_id,
        resolution=resolution,
        resolved_by="alice",
        resolved_at=resolved_at,
        note="reviewed",
    ).model_dump(mode="json")


def _coverage_snapshot(ratio: float = 0.9) -> dict:
    """A minimal config-driven coverage snapshot dict (the T-02 wire shape)."""
    return {
        "schema_version": "1.0.0",
        "captured_at": _NOW,
        "ratio": ratio,
        "percent_files": 50.0,
        "percent_public_symbols": ratio * 100.0,
        "documented": 1,
        "undocumented": 1,
        "waived": 0,
        "files": [
            {
                "path": "documented.py",
                "language": "python",
                "owners": ["eng"],
                "status": "documented",
                "waived_reason": None,
            },
            {
                "path": "gap.py",
                "language": "python",
                "owners": [],
                "status": "undocumented",
                "waived_reason": None,
            },
        ],
    }


# --------------------------------------------------------------------------- #
# the parametrized client — the SAME contract over EACH Store implementation
# --------------------------------------------------------------------------- #
def _make_store(kind: str) -> Store:
    if kind == "memory":
        return InMemoryStore()
    engine = engine_from_url("sqlite:///:memory:")
    create_all(engine)
    return SqlStore(engine)


@pytest.fixture(params=["memory", "sql"])
def client(request: pytest.FixtureRequest) -> Iterator[TestClient]:
    """A TestClient over a fresh FastAPI app, once per Store implementation.

    Every test using this fixture runs TWICE — once over ``InMemoryStore`` and once
    over ``SqlStore`` (in-memory SQLite) — so the HTTP↔store boundary is asserted
    identically for both backends (K4: no socket, no real DB driver).
    """
    store = _make_store(request.param)
    with TestClient(create_app(store)) as test_client:
        yield test_client


def _register(
    client: TestClient, repo_id: str = _REPO, token: str | None = _TOKEN
) -> None:
    resp = client.post("/repos", json=_registration(repo_id, token))
    assert resp.status_code == 201, resp.text


def _auth(token: str = _TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def test_register_repo_round_trips_through_either_store(client: TestClient) -> None:
    resp = client.post("/repos", json=_registration())
    assert resp.status_code == 201
    assert resp.json() == {"repo_id": _REPO}

    listed = client.get("/repos")
    assert listed.status_code == 200
    repos = listed.json()
    assert [r["repo"]["repo_id"] for r in repos] == [_REPO]
    # the token is never echoed back in plaintext (E-06).
    assert "auth_token" not in repos[0]
    assert "s3cret" not in listed.text


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_add_repo_honors_top_level_local_path_on_both_stores(kind: str) -> None:
    """Y-02 parity: a top-level ``local_path`` (no identity ``local_path``) is folded
    onto the stored identity by BOTH stores, so ``get_repo``/``list_repos`` expose it.

    registry.py documents that ``local_path`` may ride EITHER the identity OR the
    payload top level; the ``/sync`` route reads ``repo.repo.local_path``. A repo
    registered with only the top-level field must therefore still be syncable —
    identically over InMemoryStore and SqlStore.
    """
    store = _make_store(kind)
    payload = RegistrationPayload(
        repo=_identity(),  # NO local_path on the identity
        default_branch="main",
        local_path="/srv/checkouts/widget",  # carried at the TOP level only
        auth_token=None,
    )
    store.add_repo(payload)

    got = store.get_repo(_REPO)
    assert got is not None
    assert got.repo.local_path == "/srv/checkouts/widget"
    assert store.list_repos()[0].repo.local_path == "/srv/checkouts/widget"


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_add_repo_identity_local_path_wins_over_top_level(kind: str) -> None:
    """An identity that already carries ``local_path`` is authoritative; the
    top-level field is a FALLBACK only (backward compatible)."""
    store = _make_store(kind)
    identity = _identity().model_copy(update={"local_path": "/on/identity"})
    store.add_repo(
        RegistrationPayload(
            repo=identity,
            local_path="/top/level/ignored",
            auth_token=None,
        )
    )
    got = store.get_repo(_REPO)
    assert got is not None
    assert got.repo.local_path == "/on/identity"


def test_reregister_with_token_requires_the_token(client: TestClient) -> None:
    _register(client)
    # The EXISTING-token proof for an authorized rotation rides the Authorization
    # header; the body's auth_token is the NEW (rotated) token.
    assert client.post("/repos", json=_registration()).status_code == 401
    assert (
        client.post("/repos", json=_registration(), headers=_auth("wrong")).status_code
        == 403
    )
    # with the right existing token in the header it rotates to a new body token.
    assert (
        client.post(
            "/repos",
            json=_registration(auth_token="rotated"),
            headers=_auth(_TOKEN),
        ).status_code
        == 201
    )


# --------------------------------------------------------------------------- #
# ingest  (POST /ingest) — the primary write path + auth matrix
# --------------------------------------------------------------------------- #
def test_ingest_record_round_trips_byte_for_byte(client: TestClient) -> None:
    _register(client)
    rec = _record()
    env = _envelope(rec)
    resp = client.post("/ingest", json=env, headers=_auth())
    assert resp.status_code == 202
    assert resp.json() == {"record_id": rec.record_id}

    got = client.get(f"/repos/{_REPO}/records")
    assert got.status_code == 200
    body = got.json()
    assert len(body) == 1
    # through the JSON column (SqlStore) AND the shared schema, identical both ways.
    assert ReviewRecord.model_validate(body[0]) == rec
    assert body[0] == env["record"]


def test_ingest_auth_matrix(client: TestClient) -> None:
    # unknown repo → 404 (loud, before any token check, K8).
    assert (
        client.post("/ingest", json=_envelope(_record()), headers=_auth()).status_code
        == 404
    )
    _register(client)
    # missing token → 401, wrong token → 403, right token → 202.
    assert client.post("/ingest", json=_envelope(_record())).status_code == 401
    assert (
        client.post(
            "/ingest", json=_envelope(_record()), headers=_auth("nope")
        ).status_code
        == 403
    )
    assert (
        client.post("/ingest", json=_envelope(_record()), headers=_auth()).status_code
        == 202
    )


@pytest.mark.parametrize(
    ("query", "expected_ids"),
    [
        ("verdict=ESCALATE", {"rec-escalate"}),
        ("drift_kind=HASH", {"rec-hash"}),
        ("audience=user-guide", {"rec-hash"}),
        ("doc_id=alpha", {"rec-fix", "rec-escalate"}),
        ("limit=1", {"rec-fix"}),
        ("offset=2", {"rec-hash"}),
    ],
)
def test_record_filters_are_applied_at_the_store(
    client: TestClient, query: str, expected_ids: set[str]
) -> None:
    # Filters must behave identically whether resolved in Python (InMemoryStore) or
    # pushed to indexed columns / SQL (SqlStore) — this is the key DB-pushdown risk.
    _register(client)
    records = [
        _record(record_id="rec-fix", doc_id="alpha", verdict=Verdict.FIX),
        _record(
            record_id="rec-escalate",
            doc_id="alpha",
            verdict=Verdict.ESCALATE,
            detected_at="2026-06-05T00:01:00Z",
        ),
        _record(
            record_id="rec-hash",
            doc_id="beta",
            drift_kind="HASH",
            audience="user-guide",
            verdict=Verdict.INVALIDATE,
            detected_at="2026-06-05T00:02:00Z",
        ),
    ]
    for rec in records:
        assert (
            client.post("/ingest", json=_envelope(rec), headers=_auth()).status_code
            == 202
        )
    got = client.get(f"/repos/{_REPO}/records?{query}")
    assert got.status_code == 200
    assert {r["record_id"] for r in got.json()} == expected_ids


# --------------------------------------------------------------------------- #
# resolutions  (POST/GET /repos/{id}/resolutions) — the dashboard write path
# --------------------------------------------------------------------------- #
def test_resolution_round_trips_and_enforces_record_link(client: TestClient) -> None:
    _register(client)
    client.post("/ingest", json=_envelope(_record()), headers=_auth())

    # a resolution referencing an unknown record_id is a loud 404 (K8).
    bad = client.post(
        f"/repos/{_REPO}/resolutions",
        json=_resolution(record_id="ghost"),
        headers=_auth(),
    )
    assert bad.status_code == 404

    ok = client.post(f"/repos/{_REPO}/resolutions", json=_resolution(), headers=_auth())
    assert ok.status_code == 202
    assert ok.json() == {"record_id": "abc123def456"}

    listed = client.get(f"/repos/{_REPO}/resolutions")
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert ResolutionRecord.model_validate(body[0]) == ResolutionRecord.model_validate(
        _resolution()
    )
    # filterable by record_id through either store.
    assert (
        client.get(f"/repos/{_REPO}/resolutions?record_id=abc123def456").json() == body
    )
    assert client.get(f"/repos/{_REPO}/resolutions?record_id=ghost").json() == []


def test_resolution_auth_matrix(client: TestClient) -> None:
    assert (
        client.post(
            f"/repos/{_REPO}/resolutions", json=_resolution(), headers=_auth()
        ).status_code
        == 404  # unknown repo first
    )
    _register(client)
    client.post("/ingest", json=_envelope(_record()), headers=_auth())
    assert (
        client.post(f"/repos/{_REPO}/resolutions", json=_resolution()).status_code
        == 401
    )
    assert (
        client.post(
            f"/repos/{_REPO}/resolutions", json=_resolution(), headers=_auth("nope")
        ).status_code
        == 403
    )


# --------------------------------------------------------------------------- #
# coverage  (POST/GET /repos/{id}/coverage) — config-driven snapshot ingest
# --------------------------------------------------------------------------- #
def test_coverage_snapshot_round_trips_with_file_list(client: TestClient) -> None:
    _register(client)
    resp = client.post(
        f"/repos/{_REPO}/coverage", json=_coverage_snapshot(), headers=_auth()
    )
    assert resp.status_code == 202
    assert resp.json() == {"repo_id": _REPO}

    got = client.get(f"/repos/{_REPO}/coverage")
    assert got.status_code == 200
    snaps = got.json()
    assert len(snaps) == 1
    latest = snaps[-1]
    # the FULL config-driven file list survives the JSON column round-trip.
    statuses = {f["path"]: f["status"] for f in latest["files"]}
    assert statuses == {"documented.py": "documented", "gap.py": "undocumented"}
    assert latest["ratio"] == 0.9


def test_coverage_snapshots_preserve_insertion_order(client: TestClient) -> None:
    _register(client)
    for ratio in (0.5, 0.7, 0.95):
        assert (
            client.post(
                f"/repos/{_REPO}/coverage",
                json=_coverage_snapshot(ratio),
                headers=_auth(),
            ).status_code
            == 202
        )
    ratios = [s["ratio"] for s in client.get(f"/repos/{_REPO}/coverage").json()]
    assert ratios == [0.5, 0.7, 0.95]  # newest LAST, order preserved by both stores


def test_coverage_auth_matrix(client: TestClient) -> None:
    assert (
        client.post(
            f"/repos/{_REPO}/coverage", json=_coverage_snapshot(), headers=_auth()
        ).status_code
        == 404  # unknown repo
    )
    _register(client)
    assert (
        client.post(f"/repos/{_REPO}/coverage", json=_coverage_snapshot()).status_code
        == 401
    )
    assert (
        client.post(
            f"/repos/{_REPO}/coverage",
            json=_coverage_snapshot(),
            headers=_auth("nope"),
        ).status_code
        == 403
    )


# --------------------------------------------------------------------------- #
# computed views  (GET /status, /health, /telemetry) over real store reads
# --------------------------------------------------------------------------- #
def test_status_aggregates_records_resolutions_and_coverage(client: TestClient) -> None:
    _register(client)
    client.post("/ingest", json=_envelope(_record(record_id="r1")), headers=_auth())
    client.post(
        "/ingest",
        json=_envelope(_record(record_id="r2", verdict=Verdict.ESCALATE)),
        headers=_auth(),
    )
    client.post(
        f"/repos/{_REPO}/resolutions", json=_resolution(record_id="r1"), headers=_auth()
    )
    client.post(
        f"/repos/{_REPO}/coverage", json=_coverage_snapshot(0.8), headers=_auth()
    )

    status = client.get(f"/repos/{_REPO}/status").json()
    assert status["total_records"] == 2
    assert status["by_verdict"]["FIX"] == 1
    assert status["by_verdict"]["ESCALATE"] == 1
    assert status["escalations"] == 1
    assert status["unresolved"] == 1  # r2 has no resolution
    assert status["coverage_ratio"] == 0.8


def test_status_coverage_ratio_is_none_when_snapshot_ratio_not_numeric(
    client: TestClient,
) -> None:
    # A coverage snapshot whose `ratio` is missing/non-numeric must NOT crash the
    # status view — coverage_ratio falls back to None, identically on both stores.
    _register(client)
    snap = _coverage_snapshot()
    snap["ratio"] = "n/a"  # non-numeric — older/partial snapshot shape
    assert (
        client.post(f"/repos/{_REPO}/coverage", json=snap, headers=_auth()).status_code
        == 202
    )
    assert client.get(f"/repos/{_REPO}/status").json()["coverage_ratio"] is None


def test_health_metrics_computed_over_either_store(client: TestClient) -> None:
    _register(client)
    # detected at :00, resolved at :30 → mttr 30s; one escalation, one override.
    client.post(
        "/ingest",
        json=_envelope(_record(record_id="r1", resolved_at="2026-06-05T00:00:30Z")),
        headers=_auth(),
    )
    client.post(
        "/ingest",
        json=_envelope(_record(record_id="r2", verdict=Verdict.ESCALATE)),
        headers=_auth(),
    )
    client.post(
        f"/repos/{_REPO}/resolutions",
        json=_resolution(record_id="r1", resolution=Resolution.ACCEPTED),
        headers=_auth(),
    )
    client.post(
        f"/repos/{_REPO}/resolutions",
        json=_resolution(record_id="r2", resolution=Resolution.OVERRIDDEN),
        headers=_auth(),
    )
    health = client.get(f"/repos/{_REPO}/health").json()
    assert health["total"] == 2
    assert health["escalations"] == 1
    assert health["resolved"] == 2
    assert health["overrides"] == 1
    assert health["escalation_rate"] == pytest.approx(0.5)


def test_telemetry_surfaces_worst_shapes_over_either_store(client: TestClient) -> None:
    _register(client)
    client.post(
        "/ingest",
        json=_envelope(_record(record_id="r1", drift_kind="REGION")),
        headers=_auth(),
    )
    client.post(
        "/ingest",
        json=_envelope(
            _record(record_id="r2", drift_kind="HASH", verdict=Verdict.ESCALATE)
        ),
        headers=_auth(),
    )
    tele = client.get(f"/repos/{_REPO}/telemetry").json()
    shapes = {(s["drift_kind"], s["audience"]): s for s in tele["shapes"]}
    assert ("HASH", "eng-guide") in shapes
    # the all-escalate HASH shape sorts worst-first.
    assert tele["shapes"][0]["drift_kind"] == "HASH"


# --------------------------------------------------------------------------- #
# read-route 404s on an unknown repo (the loud-unknown policy) — every view
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "path",
    [
        "/repos/ghost/records",
        "/repos/ghost/resolutions",
        "/repos/ghost/coverage",
        "/repos/ghost/status",
        "/repos/ghost/health",
        "/repos/ghost/telemetry",
    ],
)
def test_unknown_repo_is_404_on_every_read_route(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


# --------------------------------------------------------------------------- #
# the full vertical: ticketed record + coverage, ingested and read back, on each store
# --------------------------------------------------------------------------- #
def test_full_ticket_and_coverage_vertical_over_either_store(
    client: TestClient,
) -> None:
    from custodex.config import Audience
    from custodex.drift import Drift, DriftKind
    from custodex.ticket import build_ticket

    _register(client)

    # a record carrying a structured DriftTicket (T-01), built deterministically.
    drift = Drift(
        kind=DriftKind.REGION,
        doc_id="pipeline",
        doc_path="docs/api/pipeline.md",
        detail="region 'symbols' drifted",
        region_id="symbols",
        healable=True,
        audience=Audience.ENG_GUIDE,
    )
    ticket = build_ticket(
        drift=drift,
        verdict=Verdict.FIX,
        cause="public signature changed",
        fix=ProposedFix(rationale="regenerate the region", region_id="symbols"),
        surface=_FakeSurface(),
        ticket_id="CDM-abc123def456",
    )
    rec = _record().model_copy(update={"ticket": ticket})
    assert (
        client.post("/ingest", json=_envelope(rec), headers=_auth()).status_code == 202
    )
    client.post(
        f"/repos/{_REPO}/coverage", json=_coverage_snapshot(0.9), headers=_auth()
    )

    # the ticket survives the round trip through the store (JSON column for SqlStore).
    got = client.get(f"/repos/{_REPO}/records").json()
    assert len(got) == 1
    rt = got[0]["ticket"]
    assert rt["ticket_id"] == "CDM-abc123def456"
    assert rt["severity"] == "medium"
    assert rt["affected_symbols"] == ["compute", "render"]
    assert [c["text"] for c in rt["acceptance_criteria"]]  # checklist preserved

    # and the coverage ratio flows into the computed status view.
    assert client.get(f"/repos/{_REPO}/status").json()["coverage_ratio"] == 0.9


class _FakeSurface:
    """A minimal DocumentSurface stand-in exposing the public-symbol names
    build_ticket reads (``surface.symbols`` with ``.name``/``.is_public``)."""

    class _Sym:
        def __init__(self, name: str, is_public: bool) -> None:
            self.name = name
            self.is_public = is_public

    symbols = (
        _Sym("compute", True),
        _Sym("render", True),
        _Sym("_helper", False),
    )
