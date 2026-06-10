"""Tests for the central FastAPI server (E-03, offline TestClient — K0/K4/K6/K10).

The server ingests repo registrations (``RegistrationPayload``) + review records
(``IngestEnvelope``) over the SHARED, versioned schemas — NO hand-written DTOs
(K6). It is exercised entirely with FastAPI's ``TestClient`` (no socket, K4) over
a DI'd in-memory store (the ``Store`` Protocol seam E-04 swaps for a DB).

The whole module is gated on the optional ``[server]`` extra: if ``fastapi`` is
not importable the file SKIPS, so the core suite still passes without the extra
(mirrors how the optional ``[agent]`` extra is handled). ``.venv`` HAS fastapi so
these tests RUN here.

Features: FEAT-SERVER-001, FEAT-SERVER-002, FEAT-SERVER-003, FEAT-SERVER-004
Features: FEAT-SERVER-005, FEAT-SERVER-008, FEAT-SERVER-015, FEAT-SERVER-019
Features: FEAT-RECORD-010, FEAT-RECORD-006
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")

from fastapi.testclient import TestClient  # noqa: E402

from code_doc_monitor.schema import (  # noqa: E402
    ProposedFix,
    ReviewRecord,
    Verdict,
)
from code_doc_monitor.server import InMemoryStore, create_app  # noqa: E402
from code_doc_monitor.sinks import IngestEnvelope, RepoIdentity  # noqa: E402


def _identity(repo_id: str = "acme/widget") -> RepoIdentity:
    return RepoIdentity(
        repo_id=repo_id,
        repo_name="widget",
        repo_url="https://example.invalid/acme/widget",
        commit="deadbeef",
    )


def _registration(repo_id: str = "acme/widget", auth_token: str | None = None) -> dict:
    body: dict = {
        "repo": _identity(repo_id).model_dump(mode="json"),
        "default_branch": "main",
        "description": "the widget service",
    }
    if auth_token is not None:
        body["auth_token"] = auth_token
    return body


def _record(
    repo_id: str = "acme/widget",
    *,
    record_id: str = "abc123def456",
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


def _envelope(repo_id: str = "acme/widget") -> dict:
    return IngestEnvelope(repo=_identity(repo_id), record=_record(repo_id)).model_dump(
        mode="json"
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(InMemoryStore()))


def test_health_is_open_and_ok(client: TestClient) -> None:
    # Unauthenticated liveness probe (ops/k8s) — always 200, no token.
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_root_landing_points_at_docs(client: TestClient) -> None:
    # The bare URL is a friendly landing, not the confusing 404 FastAPI gives `/`.
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "code-doc-monitor central server"
    assert body["docs"] == "/docs"
    assert "/health" in body["endpoints"]


def test_serves_dashboard_spa_when_static_dir_is_mounted(tmp_path: Path) -> None:
    # A single-origin deploy: FastAPI serves the built SPA at `/` and its assets
    # at `/assets`, on the SAME app as the API. The hash-routed SPA never shadows
    # the API routes, which stay reachable.
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>drift console</title>", encoding="utf-8"
    )
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

    app = create_app(InMemoryStore(), static_dir=dist)
    spa = TestClient(app)

    # `/` now returns the SPA shell (HTML), not the JSON landing.
    root = spa.get("/")
    assert root.status_code == 200
    assert "drift console" in root.text
    assert root.headers["content-type"].startswith("text/html")

    # Assets are served from the mounted dir.
    asset = spa.get("/assets/app.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text

    # The API still works on the same app (reads open).
    assert spa.get("/health").json() == {"status": "ok"}
    assert spa.get("/repos").json() == []


def test_static_dir_without_index_falls_back_to_json_landing(tmp_path: Path) -> None:
    # A static_dir that has NOT been built (no index.html) must not break the app:
    # no SPA is mounted and `/` returns the JSON landing, API intact.
    empty = tmp_path / "dist"
    empty.mkdir()
    client = TestClient(create_app(InMemoryStore(), static_dir=empty))

    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["service"] == "code-doc-monitor central server"
    assert client.get("/assets/anything.js").status_code == 404  # nothing mounted
    assert client.get("/health").json() == {"status": "ok"}


def test_static_dir_with_index_but_no_assets_serves_spa_without_mount(
    tmp_path: Path,
) -> None:
    # index.html present but no assets/ dir (a bundleless build): the SPA shell is
    # still served at `/`, the /assets mount is simply skipped.
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        "<!doctype html><title>console</title>", encoding="utf-8"
    )
    client = TestClient(create_app(InMemoryStore(), static_dir=dist))

    root = client.get("/")
    assert root.status_code == 200
    assert "console" in root.text
    assert root.headers["content-type"].startswith("text/html")
    assert client.get("/assets/app.js").status_code == 404  # not in the build
    assert client.get("/repos").json() == []  # API intact


def test_serves_astro_underscore_assets_dir(tmp_path: Path) -> None:
    # EPIC ASTRO: the built site's assets live under `_astro/` (Astro's default),
    # served by the single catch-all StaticFiles mount — while the API routes
    # (declared first) still win, proven by /health, /openapi.json and /repos.
    dist = tmp_path / "dist"
    (dist / "_astro").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><div id='root'></div>", encoding="utf-8"
    )
    (dist / "_astro" / "island.abc123.js").write_text(
        "console.log('island')", encoding="utf-8"
    )
    client = TestClient(create_app(InMemoryStore(), static_dir=dist))

    assert client.get("/").status_code == 200
    asset = client.get("/_astro/island.abc123.js")
    assert asset.status_code == 200
    assert "island" in asset.text
    # The catch-all mount is LAST, so real API paths are never shadowed:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/repos").json() == []


def test_default_static_dir_resolves_frontend_dist(tmp_path: Path) -> None:
    # EPIC ASTRO (ASTRO-04): `_default_static_dir` resolves the built
    # `frontend/dist` Astro app, or None when it has not been built.
    from code_doc_monitor.server.app import _default_static_dir

    assert _default_static_dir(tmp_path) is None  # not built

    frontend = tmp_path / "frontend" / "dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    assert _default_static_dir(tmp_path) == frontend


def _seed_wiki(wiki_dir: Path, *, sections: tuple[str, ...]) -> None:
    """Write fixture wiki markdown into ``wiki_dir`` for the named section ids.

    Mirrors the committed ``feature-doc/`` layout: ``FEATURES.md`` at the root,
    the rest under ``wiki/``. Each file carries a heading and a markdown table so
    the rendered HTML is assertable (``<h1``/``<table``). Only the requested
    sections are written so a test can prove a missing file is omitted.
    """
    layout = {
        "features": ("FEATURES.md", "# Feature Reference\n"),
        "traceability": ("wiki/TRACEABILITY.md", "# Traceability Matrix\n"),
        "tests": ("wiki/TEST_WIKI.md", "# Test Wiki\n"),
        "source": ("wiki/SOURCE_WIKI.md", "# Source Wiki\n"),
    }
    table = "\n| Feature | Test |\n| --- | --- |\n| FEAT-X | t_x |\n"
    for sec in sections:
        relpath, heading = layout[sec]
        path = wiki_dir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(heading + table, encoding="utf-8")


def test_wiki_serves_all_committed_sections_rendered(tmp_path: Path) -> None:
    # GET /wiki renders the four committed wikis to HTML in deterministic order
    # (features, traceability, tests, source) via the engine's own render_markdown
    # (no new dep, K0). Each section's html carries rendered markup (a heading +
    # a table), and the ids/titles are the WIKI_SECTIONS contract.
    wiki_dir = tmp_path / "feature-doc"
    _seed_wiki(wiki_dir, sections=("features", "traceability", "tests", "source"))
    client = TestClient(create_app(InMemoryStore(), wiki_dir=wiki_dir))

    resp = client.get("/wiki")
    assert resp.status_code == 200
    body = resp.json()
    sections = body["sections"]
    assert [s["id"] for s in sections] == [
        "features",
        "traceability",
        "tests",
        "source",
    ]
    assert [s["title"] for s in sections] == [
        "Feature Reference",
        "Traceability Matrix",
        "Test Wiki",
        "Source Wiki",
    ]
    for s in sections:
        assert "<h1" in s["html"]  # heading rendered
        assert "<table" in s["html"]  # table rendered
        assert set(s) == {"id", "title", "html"}  # exact contract


def test_wiki_omits_a_missing_section_file(tmp_path: Path) -> None:
    # Only FEATURES.md present → exactly one section; the absent wiki/*.md files
    # are SKIPPED (not empty placeholders), preserving order over what exists.
    wiki_dir = tmp_path / "feature-doc"
    _seed_wiki(wiki_dir, sections=("features",))
    client = TestClient(create_app(InMemoryStore(), wiki_dir=wiki_dir))

    body = client.get("/wiki").json()
    assert [s["id"] for s in body["sections"]] == ["features"]


def test_wiki_empty_dir_yields_empty_sections(tmp_path: Path) -> None:
    # A wiki_dir that exists but holds no wiki files → a graceful empty payload,
    # not a crash (K8). The exact frontend contract: {"sections": []}.
    empty = tmp_path / "feature-doc"
    empty.mkdir()
    client = TestClient(create_app(InMemoryStore(), wiki_dir=empty))
    assert client.get("/wiki").json() == {"sections": []}


def test_wiki_nonexistent_dir_yields_empty_sections(tmp_path: Path) -> None:
    # An explicit wiki_dir pointing at a dir that does not exist → empty payload
    # (graceful for a non-cdmon repo with no feature-doc/, K8) — never a 500.
    missing = tmp_path / "feature-doc"  # never created
    client = TestClient(create_app(InMemoryStore(), wiki_dir=missing))
    assert client.get("/wiki").json() == {"sections": []}


def test_wiki_absent_feature_doc_yields_empty_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The live default path on a NON-cdmon repo: create_app left to auto-resolve
    # wiki_dir, but feature-doc/ is absent so _wiki_dir() is None → the route
    # returns {"sections": []} (graceful, K8) instead of 500ing. Drives the
    # default-None resolution AND the _load_wiki_sections(None) branch end-to-end.
    from code_doc_monitor.server import app as app_module

    monkeypatch.setattr(app_module, "_wiki_dir", lambda: None)
    client = TestClient(create_app(InMemoryStore()))  # no wiki_dir → auto-resolve
    assert client.get("/wiki").json() == {"sections": []}


def test_wiki_is_public_no_auth(tmp_path: Path) -> None:
    # GLOBAL + public like /config/templates: no Authorization header → 200.
    wiki_dir = tmp_path / "feature-doc"
    _seed_wiki(wiki_dir, sections=("features",))
    client = TestClient(create_app(InMemoryStore(), wiki_dir=wiki_dir))

    resp = client.get("/wiki")  # no headers at all
    assert resp.status_code == 200
    assert resp.json()["sections"][0]["id"] == "features"


def test_register_ingest_read_round_trip(client: TestClient) -> None:
    # Register a repo.
    reg = client.post("/repos", json=_registration())
    assert reg.status_code == 201
    assert reg.json() == {"repo_id": "acme/widget"}

    # Ingest a record under it.
    env = _envelope()
    ing = client.post("/ingest", json=env)
    assert ing.status_code == 202
    assert ing.json() == {"record_id": "abc123def456"}

    # Read it back — it round-trips through the SHARED schema byte-for-byte.
    got = client.get("/repos/acme%2Fwidget/records")
    assert got.status_code == 200
    body = got.json()
    assert len(body) == 1
    assert ReviewRecord.model_validate(body[0]) == _record()
    assert body[0] == env["record"]


def test_list_repos(client: TestClient) -> None:
    assert client.get("/repos").json() == []
    client.post("/repos", json=_registration("a/one"))
    client.post("/repos", json=_registration("b/two"))
    repos = client.get("/repos").json()
    assert [r["repo"]["repo_id"] for r in repos] == ["a/one", "b/two"]
    assert repos[0]["default_branch"] == "main"
    assert repos[0]["description"] == "the widget service"


def test_records_for_unknown_repo_is_404(client: TestClient) -> None:
    resp = client.get("/repos/nope/records")
    assert resp.status_code == 404


def test_empty_store_lists_are_empty(client: TestClient) -> None:
    assert client.get("/repos").json() == []
    client.post("/repos", json=_registration())
    assert client.get("/repos/acme%2Fwidget/records").json() == []


def test_ingest_unknown_repo_is_404(client: TestClient) -> None:
    # Policy: registration is explicit (E-02) — ingest never auto-registers.
    resp = client.post("/ingest", json=_envelope("never/registered"))
    assert resp.status_code == 404
    assert "never/registered" in resp.text


def test_malformed_registration_body_is_422(client: TestClient) -> None:
    # Missing the required `repo` -> pydantic validation against the shared schema.
    resp = client.post("/repos", json={"default_branch": "main"})
    assert resp.status_code == 422


def test_malformed_ingest_body_is_422(client: TestClient) -> None:
    bad = _envelope()
    del bad["record"]["verdict"]  # drop a required ReviewRecord field
    resp = client.post("/ingest", json=bad)
    assert resp.status_code == 422


def test_extra_field_rejected_by_shared_schema(client: TestClient) -> None:
    # The shared models are extra="forbid" — an unexpected key is a 422 (K8).
    body = _registration()
    body["surprise"] = "boom"
    resp = client.post("/repos", json=body)
    assert resp.status_code == 422


def test_create_app_defaults_to_in_memory_store() -> None:
    # No store injected -> a default InMemoryStore (so prod can omit it pre-E-04).
    client = TestClient(create_app())
    client.post("/repos", json=_registration())
    repos = client.get("/repos").json()
    assert [r["repo"]["repo_id"] for r in repos] == ["acme/widget"]


def test_in_memory_store_repeat_register_updates_in_place() -> None:
    store = InMemoryStore()
    from code_doc_monitor.registry import RegistrationPayload

    store.add_repo(RegistrationPayload(repo=_identity(), description="v1"))
    store.add_repo(RegistrationPayload(repo=_identity(), description="v2"))
    repos = store.list_repos()
    assert len(repos) == 1
    assert repos[0].description == "v2"


def test_records_preserve_insertion_order() -> None:
    store = InMemoryStore()
    from code_doc_monitor.registry import RegistrationPayload

    store.add_repo(RegistrationPayload(repo=_identity()))
    r1 = _record()
    r2 = _record().model_copy(update={"record_id": "second000000"})
    store.add_record("acme/widget", r1)
    store.add_record("acme/widget", r2)
    assert [r.record_id for r in store.records_for("acme/widget")] == [
        "abc123def456",
        "second000000",
    ]


# --------------------------------------------------------------------------- #
# E-05 — filtered query API (InMemoryStore via TestClient)
# --------------------------------------------------------------------------- #


def _seed_mixed(client: TestClient, repo_id: str = "acme/widget") -> None:
    """Register a repo and ingest a deterministic mix of records for filter tests."""
    client.post("/repos", json=_registration(repo_id))
    specs = [
        dict(
            record_id="r0aaaaaaaaaa",
            doc_id="pipeline",
            audience="eng-guide",
            drift_kind="REGION",
            verdict=Verdict.FIX,
            detected_at="2026-06-01T00:00:00Z",
        ),
        dict(
            record_id="r1bbbbbbbbbb",
            doc_id="pipeline",
            audience="user-guide",
            drift_kind="SURFACE",
            verdict=Verdict.INVALIDATE,
            detected_at="2026-06-02T00:00:00Z",
        ),
        dict(
            record_id="r2cccccccccc",
            doc_id="overview",
            audience="eng-guide",
            drift_kind="REGION",
            verdict=Verdict.ESCALATE,
            detected_at="2026-06-03T00:00:00Z",
        ),
        dict(
            record_id="r3dddddddddd",
            doc_id="overview",
            audience="eng-guide",
            drift_kind="SURFACE",
            verdict=Verdict.FIX,
            detected_at="2026-06-04T00:00:00Z",
        ),
    ]
    for spec in specs:
        rec = _record(repo_id, **spec)  # type: ignore[arg-type]
        env = IngestEnvelope(repo=_identity(repo_id), record=rec).model_dump(
            mode="json"
        )
        assert client.post("/ingest", json=env).status_code == 202


def test_records_filter_by_verdict(client: TestClient) -> None:
    _seed_mixed(client)
    got = client.get("/repos/acme%2Fwidget/records", params={"verdict": "FIX"}).json()
    assert {r["record_id"] for r in got} == {"r0aaaaaaaaaa", "r3dddddddddd"}
    assert all(r["verdict"] == "FIX" for r in got)


def test_records_filter_by_drift_kind_and_audience(client: TestClient) -> None:
    _seed_mixed(client)
    got = client.get(
        "/repos/acme%2Fwidget/records",
        params={"drift_kind": "REGION", "audience": "eng-guide"},
    ).json()
    assert {r["record_id"] for r in got} == {"r0aaaaaaaaaa", "r2cccccccccc"}


def test_records_filter_by_doc_id(client: TestClient) -> None:
    _seed_mixed(client)
    got = client.get(
        "/repos/acme%2Fwidget/records", params={"doc_id": "overview"}
    ).json()
    assert {r["record_id"] for r in got} == {"r2cccccccccc", "r3dddddddddd"}


def test_records_pagination_is_deterministic(client: TestClient) -> None:
    _seed_mixed(client)
    page1 = client.get(
        "/repos/acme%2Fwidget/records", params={"limit": 2, "offset": 0}
    ).json()
    page2 = client.get(
        "/repos/acme%2Fwidget/records", params={"limit": 2, "offset": 2}
    ).json()
    assert [r["record_id"] for r in page1] == ["r0aaaaaaaaaa", "r1bbbbbbbbbb"]
    assert [r["record_id"] for r in page2] == ["r2cccccccccc", "r3dddddddddd"]


def test_records_filtered_revalidate_to_shared_schema(client: TestClient) -> None:
    _seed_mixed(client)
    got = client.get(
        "/repos/acme%2Fwidget/records", params={"verdict": "ESCALATE"}
    ).json()
    assert len(got) == 1
    # Re-validates byte-for-byte to the SHARED schema (K6), not a DTO.
    assert ReviewRecord.model_validate(got[0]).verdict == Verdict.ESCALATE


def test_records_bad_pagination_is_422(client: TestClient) -> None:
    client.post("/repos", json=_registration())
    assert (
        client.get("/repos/acme%2Fwidget/records", params={"limit": 0}).status_code
        == 422
    )
    assert (
        client.get("/repos/acme%2Fwidget/records", params={"offset": -1}).status_code
        == 422
    )


def test_status_summary(client: TestClient) -> None:
    _seed_mixed(client)
    st = client.get("/repos/acme%2Fwidget/status").json()
    assert st["repo_id"] == "acme/widget"
    assert st["total_records"] == 4
    assert st["by_verdict"] == {"FIX": 2, "INVALIDATE": 1, "ESCALATE": 1}
    assert st["escalations"] == 1
    assert st["unresolved"] == 4  # no resolutions seeded
    assert st["last_detected_at"] == "2026-06-04T00:00:00Z"
    assert st["coverage_ratio"] is None


def test_status_with_resolutions_and_coverage() -> None:
    # Drive an InMemoryStore directly so we can seed resolutions + a coverage snapshot
    # (their store helpers) and exercise the status aggregate's resolved/coverage paths.
    from code_doc_monitor.schema import Resolution, ResolutionRecord

    store = InMemoryStore()
    client = TestClient(create_app(store))
    _seed_mixed(client)
    store.add_resolution(
        ResolutionRecord(
            record_id="r0aaaaaaaaaa",
            resolution=Resolution.ACCEPTED,
            resolved_at="2026-06-05T00:00:00Z",
        )
    )
    store.add_coverage_snapshot("acme/widget", "2026-06-05T00:00:00Z", {"ratio": 0.75})
    st = client.get("/repos/acme%2Fwidget/status").json()
    assert st["unresolved"] == 3  # one of the four is now resolved
    assert st["coverage_ratio"] == 0.75
    # the resolutions endpoint now returns the seeded resolution
    res = client.get("/repos/acme%2Fwidget/resolutions").json()
    assert [r["record_id"] for r in res] == ["r0aaaaaaaaaa"]
    cov = client.get("/repos/acme%2Fwidget/coverage").json()
    assert cov == [{"ratio": 0.75}]


def test_status_unknown_repo_is_404(client: TestClient) -> None:
    assert client.get("/repos/nope/status").status_code == 404


def test_resolutions_and_coverage_unknown_repo_is_404(client: TestClient) -> None:
    assert client.get("/repos/nope/resolutions").status_code == 404
    assert client.get("/repos/nope/coverage").status_code == 404


def test_resolutions_endpoint_empty_for_seeded_repo(client: TestClient) -> None:
    client.post("/repos", json=_registration())
    assert client.get("/repos/acme%2Fwidget/resolutions").json() == []
    assert client.get("/repos/acme%2Fwidget/coverage").json() == []


# --------------------------------------------------------------------------- #
# E-06 — per-repo bearer auth on writes (reads open)
# --------------------------------------------------------------------------- #


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_ingest_requires_token_when_registered_with_one(client: TestClient) -> None:
    client.post("/repos", json=_registration(auth_token="s3cret"))
    env = _envelope()
    # right token -> 202
    assert client.post("/ingest", json=env, headers=_auth("s3cret")).status_code == 202
    # wrong token -> 403
    assert client.post("/ingest", json=env, headers=_auth("nope")).status_code == 403
    # missing token -> 401
    assert client.post("/ingest", json=env).status_code == 401


def test_ingest_unknown_repo_is_404_even_with_token(client: TestClient) -> None:
    resp = client.post(
        "/ingest", json=_envelope("never/registered"), headers=_auth("x")
    )
    assert resp.status_code == 404


def test_ingest_open_when_repo_registered_without_token(client: TestClient) -> None:
    client.post("/repos", json=_registration())  # no auth_token
    assert client.post("/ingest", json=_envelope()).status_code == 202


def test_auth_token_never_returned_on_reads(client: TestClient) -> None:
    client.post("/repos", json=_registration(auth_token="s3cret"))
    repos = client.get("/repos").json()
    assert "auth_token" not in repos[0]
    assert "auth_token" not in repos[0].get("repo", {})


def test_reads_are_open_no_token_needed(client: TestClient) -> None:
    client.post("/repos", json=_registration(auth_token="s3cret"))
    # GET endpoints need no Authorization header.
    assert client.get("/repos/acme%2Fwidget/records").status_code == 200
    assert client.get("/repos/acme%2Fwidget/status").status_code == 200


def test_reregister_existing_repo_with_token_requires_token(client: TestClient) -> None:
    client.post("/repos", json=_registration(auth_token="s3cret"))
    # re-register WITHOUT the token -> 401
    assert client.post("/repos", json=_registration()).status_code == 401
    # re-register WITH the wrong token -> 403
    assert (
        client.post("/repos", json=_registration(), headers=_auth("wrong")).status_code
        == 403
    )
    # re-register WITH the right token -> 201
    assert (
        client.post(
            "/repos", json=_registration(auth_token="rotated"), headers=_auth("s3cret")
        ).status_code
        == 201
    )


# --------------------------------------------------------------------------- #
# F-04 — resolve write path (POST /repos/{id}/resolutions, token-protected)
# --------------------------------------------------------------------------- #


def _resolution(
    record_id: str = "abc123def456",
    *,
    resolution: str = "accepted",
    resolved_at: str = "2026-06-05T01:00:00Z",
    resolved_text: str | None = None,
    note: str | None = None,
) -> dict:
    from code_doc_monitor.schema import Resolution, ResolutionRecord

    return ResolutionRecord(
        record_id=record_id,
        resolution=Resolution(resolution),
        resolved_text=resolved_text,
        resolved_by="alice",
        resolved_at=resolved_at,
        note=note,
    ).model_dump(mode="json")


def test_post_resolution_persists_and_reflects(client: TestClient) -> None:
    client.post("/repos", json=_registration())
    client.post("/ingest", json=_envelope())
    resp = client.post("/repos/acme%2Fwidget/resolutions", json=_resolution())
    assert resp.status_code == 202
    assert resp.json() == {"record_id": "abc123def456"}
    # The new resolution now reads back through the resolutions endpoint.
    got = client.get("/repos/acme%2Fwidget/resolutions").json()
    assert [r["record_id"] for r in got] == ["abc123def456"]
    assert got[0]["resolution"] == "accepted"


def test_post_resolution_unknown_repo_is_404(client: TestClient) -> None:
    resp = client.post("/repos/never%2Fregistered/resolutions", json=_resolution())
    assert resp.status_code == 404


def test_post_resolution_unknown_record_is_404(client: TestClient) -> None:
    client.post("/repos", json=_registration())
    client.post("/ingest", json=_envelope())
    resp = client.post(
        "/repos/acme%2Fwidget/resolutions", json=_resolution("not_a_record")
    )
    assert resp.status_code == 404
    assert "not_a_record" in resp.text


def test_post_resolution_auth_matrix(client: TestClient) -> None:
    client.post("/repos", json=_registration(auth_token="s3cret"))
    client.post("/ingest", json=_envelope(), headers=_auth("s3cret"))
    body = _resolution()
    # right token -> 202
    assert (
        client.post(
            "/repos/acme%2Fwidget/resolutions", json=body, headers=_auth("s3cret")
        ).status_code
        == 202
    )
    # wrong token -> 403
    assert (
        client.post(
            "/repos/acme%2Fwidget/resolutions", json=body, headers=_auth("nope")
        ).status_code
        == 403
    )
    # missing token -> 401
    assert client.post("/repos/acme%2Fwidget/resolutions", json=body).status_code == 401


def test_post_resolution_malformed_body_is_422(client: TestClient) -> None:
    client.post("/repos", json=_registration())
    client.post("/ingest", json=_envelope())
    bad = _resolution()
    del bad["resolution"]  # drop a required ResolutionRecord field
    resp = client.post("/repos/acme%2Fwidget/resolutions", json=bad)
    assert resp.status_code == 422


def test_post_resolution_open_when_repo_has_no_token(client: TestClient) -> None:
    client.post("/repos", json=_registration())  # no auth_token
    client.post("/ingest", json=_envelope())
    assert (
        client.post("/repos/acme%2Fwidget/resolutions", json=_resolution()).status_code
        == 202
    )


# --------------------------------------------------------------------------- #
# F-05 — RepoHealth (computed metrics view)
# --------------------------------------------------------------------------- #


def test_health_unknown_repo_is_404(client: TestClient) -> None:
    assert client.get("/repos/nope/health").status_code == 404


def test_health_empty_repo_is_zeroed(client: TestClient) -> None:
    client.post("/repos", json=_registration())
    h = client.get("/repos/acme%2Fwidget/health").json()
    assert h["repo_id"] == "acme/widget"
    assert h["total"] == 0
    assert h["escalations"] == 0
    assert h["escalation_rate"] == 0.0
    assert h["unresolved"] == 0
    assert h["overrides"] == 0
    assert h["resolved"] == 0
    assert h["mttr_seconds"] is None


def test_health_metrics_arithmetic_exact(client: TestClient) -> None:
    # Seed 4 records (1 ESCALATE) and resolve two with KNOWN detected→resolved deltas
    # so the escalation_rate and mttr_seconds are exact (K10 determinism).
    store = InMemoryStore()
    client = TestClient(create_app(store))
    _seed_mixed(client)  # r0..r3, detected 2026-06-01..04; r2 is the ESCALATE
    from code_doc_monitor.schema import Resolution, ResolutionRecord

    # r0 detected 06-01T00:00:00Z, resolved 60s later -> 60.0
    store.add_resolution(
        ResolutionRecord(
            record_id="r0aaaaaaaaaa",
            resolution=Resolution.ACCEPTED,
            resolved_at="2026-06-01T00:01:00Z",
        )
    )
    # r1 detected 06-02T00:00:00Z, resolved 120s later (an override) -> 120.0
    store.add_resolution(
        ResolutionRecord(
            record_id="r1bbbbbbbbbb",
            resolution=Resolution.OVERRIDDEN,
            resolved_text="rewrote it",
            resolved_at="2026-06-02T00:02:00Z",
        )
    )
    h = client.get("/repos/acme%2Fwidget/health").json()
    assert h["total"] == 4
    assert h["escalations"] == 1
    assert h["escalation_rate"] == 0.25
    assert h["resolved"] == 2
    assert h["unresolved"] == 2
    assert h["overrides"] == 1
    # mean of 60s and 120s
    assert h["mttr_seconds"] == 90.0


def test_health_mttr_none_when_no_resolutions(client: TestClient) -> None:
    _seed_mixed(client)
    h = client.get("/repos/acme%2Fwidget/health").json()
    assert h["resolved"] == 0
    assert h["mttr_seconds"] is None
    assert h["escalation_rate"] == 0.25  # 1 of 4 records is ESCALATE


# --------------------------------------------------------------------------- #
# H-01 — RepoTelemetry (per-shape underperformer view, worst-first)
# --------------------------------------------------------------------------- #


def test_telemetry_unknown_repo_is_404(client: TestClient) -> None:
    assert client.get("/repos/nope/telemetry").status_code == 404


def test_telemetry_empty_repo(client: TestClient) -> None:
    client.post("/repos", json=_registration())
    t = client.get("/repos/acme%2Fwidget/telemetry").json()
    assert t["repo_id"] == "acme/widget"
    assert t["shapes"] == []
    assert t["promotion_candidates"] == []


def _seed_shapes(store: InMemoryStore, client: TestClient) -> None:
    """Seed a deterministic mix exercising escalation_rate / override_rate ordering.

    Shapes (drift_kind, audience):
      (REGION, eng-guide): 2 records, 1 ESCALATE, 1 FIX (overridden) -> esc .5 / ovr .5
      (SURFACE, eng-guide): 1 record, FIX, overridden                -> esc 0  / ovr 1.0
      (HASH, user-guide):  2 records, both INVALIDATE, unresolved    -> esc 0  / ovr 0
    """
    client.post("/repos", json=_registration())
    specs = [
        dict(
            record_id="re0000000000",
            drift_kind="REGION",
            audience="eng-guide",
            verdict=Verdict.ESCALATE,
            detected_at="2026-06-01T00:00:00Z",
        ),
        dict(
            record_id="re1111111111",
            drift_kind="REGION",
            audience="eng-guide",
            verdict=Verdict.FIX,
            detected_at="2026-06-02T00:00:00Z",
        ),
        dict(
            record_id="rs2222222222",
            drift_kind="SURFACE",
            audience="eng-guide",
            verdict=Verdict.FIX,
            detected_at="2026-06-03T00:00:00Z",
        ),
        dict(
            record_id="rh3333333333",
            drift_kind="HASH",
            audience="user-guide",
            verdict=Verdict.INVALIDATE,
            detected_at="2026-06-04T00:00:00Z",
        ),
        dict(
            record_id="rh4444444444",
            drift_kind="HASH",
            audience="user-guide",
            verdict=Verdict.INVALIDATE,
            detected_at="2026-06-05T00:00:00Z",
        ),
    ]
    for spec in specs:
        rec = _record("acme/widget", **spec)  # type: ignore[arg-type]
        env = IngestEnvelope(repo=_identity(), record=rec).model_dump(mode="json")
        assert client.post("/ingest", json=env).status_code == 202
    from code_doc_monitor.schema import Resolution, ResolutionRecord

    # one REGION/eng record overridden, the SURFACE/eng record overridden
    store.add_resolution(
        ResolutionRecord(
            record_id="re1111111111",
            resolution=Resolution.OVERRIDDEN,
            resolved_text="rewrote",
            resolved_at="2026-06-02T01:00:00Z",
        )
    )
    store.add_resolution(
        ResolutionRecord(
            record_id="rs2222222222",
            resolution=Resolution.OVERRIDDEN,
            resolved_text="rewrote",
            resolved_at="2026-06-03T01:00:00Z",
        )
    )


def test_telemetry_rates_and_worst_first_ordering() -> None:
    store = InMemoryStore()
    client = TestClient(create_app(store))
    _seed_shapes(store, client)
    t = client.get("/repos/acme%2Fwidget/telemetry").json()
    shapes = t["shapes"]
    # worst-first: escalation_rate desc, then override_rate desc, then key asc.
    # REGION/eng esc .5 first; then SURFACE/eng (esc 0, ovr 1.0); then HASH/user (0,0).
    assert [(s["drift_kind"], s["audience"]) for s in shapes] == [
        ("REGION", "eng-guide"),
        ("SURFACE", "eng-guide"),
        ("HASH", "user-guide"),
    ]
    region = shapes[0]
    assert region["count"] == 2
    assert region["escalations"] == 1
    assert region["escalation_rate"] == 0.5
    assert region["overrides"] == 1
    assert region["override_rate"] == 0.5
    surface = shapes[1]
    assert surface["count"] == 1
    assert surface["escalation_rate"] == 0.0
    assert surface["override_rate"] == 1.0
    hashs = shapes[2]
    assert hashs["count"] == 2
    assert hashs["escalation_rate"] == 0.0
    assert hashs["override_rate"] == 0.0


def test_telemetry_promotion_candidates() -> None:
    # 3 HASH/user-guide records on one doc, all INVALIDATED -> a promotion candidate.
    store = InMemoryStore()
    client = TestClient(create_app(store))
    client.post("/repos", json=_registration())
    from code_doc_monitor.schema import Resolution, ResolutionRecord

    for i in range(3):
        rec = _record(
            "acme/widget",
            record_id=f"p{i}0000000000",
            doc_id="pipeline",
            audience="user-guide",
            drift_kind="HASH",
            verdict=Verdict.INVALIDATE,
            detected_at=f"2026-06-0{i + 1}T00:00:00Z",
        )
        env = IngestEnvelope(repo=_identity(), record=rec).model_dump(mode="json")
        client.post("/ingest", json=env)
        store.add_resolution(
            ResolutionRecord(
                record_id=f"p{i}0000000000",
                resolution=Resolution.INVALIDATED,
                resolved_at=f"2026-06-0{i + 1}T01:00:00Z",
            )
        )
    t = client.get("/repos/acme%2Fwidget/telemetry").json()
    cands = t["promotion_candidates"]
    assert len(cands) == 1
    assert cands[0]["doc_id"] == "pipeline"
    assert cands[0]["drift_kind"] == "HASH"
    assert cands[0]["audience"] == "user-guide"
    assert cands[0]["resolution"] == "invalidated"
    assert cands[0]["count"] == 3


# --------------------------------------------------------------------------- #
# T-02 — POST /repos/{id}/coverage ingest (token-protected like resolve)
# --------------------------------------------------------------------------- #


def _snapshot(*, captured_at: str = "2026-06-05T00:00:00Z", ratio: float = 0.8) -> dict:
    return {
        "schema_version": "1.0.0",
        "captured_at": captured_at,
        "percent_files": 100.0,
        "percent_public_symbols": ratio * 100,
        "ratio": ratio,
        "documented": 1,
        "undocumented": 0,
        "waived": 0,
        "files": [
            {
                "path": "src/a.py",
                "language": "python",
                "owners": ["D1"],
                "status": "documented",
                "waived_reason": None,
            }
        ],
    }


def test_post_coverage_persists_and_reads_back(client: TestClient) -> None:
    client.post("/repos", json=_registration())
    resp = client.post("/repos/acme%2Fwidget/coverage", json=_snapshot())
    assert resp.status_code == 202
    assert resp.json() == {"repo_id": "acme/widget"}
    cov = client.get("/repos/acme%2Fwidget/coverage").json()
    assert isinstance(cov, list)
    assert cov[-1]["files"][0]["path"] == "src/a.py"
    assert cov[-1]["captured_at"] == "2026-06-05T00:00:00Z"


def test_post_coverage_status_reflects_ratio(client: TestClient) -> None:
    client.post("/repos", json=_registration())
    client.post("/repos/acme%2Fwidget/coverage", json=_snapshot(ratio=0.42))
    st = client.get("/repos/acme%2Fwidget/status").json()
    assert st["coverage_ratio"] == 0.42


def test_post_coverage_unknown_repo_is_404(client: TestClient) -> None:
    resp = client.post("/repos/never%2Fregistered/coverage", json=_snapshot())
    assert resp.status_code == 404


def test_post_coverage_auth_matrix(client: TestClient) -> None:
    client.post("/repos", json=_registration(auth_token="s3cret"))
    body = _snapshot()
    # right token -> 202
    assert (
        client.post(
            "/repos/acme%2Fwidget/coverage", json=body, headers=_auth("s3cret")
        ).status_code
        == 202
    )
    # wrong token -> 403
    assert (
        client.post(
            "/repos/acme%2Fwidget/coverage", json=body, headers=_auth("nope")
        ).status_code
        == 403
    )
    # missing token -> 401
    assert client.post("/repos/acme%2Fwidget/coverage", json=body).status_code == 401


def test_post_coverage_open_when_repo_has_no_token(client: TestClient) -> None:
    client.post("/repos", json=_registration())  # no auth_token
    assert (
        client.post("/repos/acme%2Fwidget/coverage", json=_snapshot()).status_code
        == 202
    )


def test_telemetry_works_on_sqlstore() -> None:
    # The view computes from records_for + resolutions_for_repo, so SqlStore works too.
    from code_doc_monitor.server.db import SqlStore, create_all, engine_from_url

    engine = engine_from_url("sqlite:///:memory:")
    create_all(engine)
    store = SqlStore(engine)
    client = TestClient(create_app(store))
    _seed_shapes(store, client)  # type: ignore[arg-type]
    t = client.get("/repos/acme%2Fwidget/telemetry").json()
    assert [(s["drift_kind"], s["audience"]) for s in t["shapes"]] == [
        ("REGION", "eng-guide"),
        ("SURFACE", "eng-guide"),
        ("HASH", "user-guide"),
    ]
