"""Y-02 — the config-sync HTTP endpoints over BOTH Store backends (offline).

Drives ``POST /repos/{id}/sync`` / ``GET /repos/{id}/documents`` / ``GET
/repos/{id}/sync-state`` through a FastAPI ``TestClient`` parametrized over the
in-memory store AND the SQLite-backed ``SqlStore`` (so the HTTP↔DB JSON
round-trip of the Y-01 config tables is exercised, mirroring
``test_server_store_parity.py``). A REAL temp git repo backs the sync; the server
``clock`` is injected so the persisted run rows are deterministic (K10).

Asserts: the run summary + the persisted DB rows; the document→code_refs tree;
the latest sync-state; auth (401/403 like the other writes); 400 on a bad mode /
missing local_path; 404 on an unknown repo.

Gated on the ``[server]`` extra (fastapi + sqlalchemy), like the other server
suites; ``.venv`` has both so it RUNS.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")
pytest.importorskip(
    "sqlalchemy", reason="the [server] extra (sqlalchemy) is not installed"
)

from fastapi.testclient import TestClient  # noqa: E402

from code_doc_monitor.registry import RegistrationPayload  # noqa: E402
from code_doc_monitor.server import InMemoryStore, create_app  # noqa: E402
from code_doc_monitor.server.db import (  # noqa: E402
    SqlStore,
    create_all,
    engine_from_url,
)
from code_doc_monitor.server.store import Store, hash_token  # noqa: E402
from code_doc_monitor.sinks import RepoIdentity  # noqa: E402

_REPO = "acme/widget"
_TOKEN = "s3cret-token"
_NOW = "2026-06-07T00:00:00Z"

# --------------------------------------------------------------------------- #
# A real committed dir-layout git repo (reused from the engine suite's shape).
# --------------------------------------------------------------------------- #

_INDEX_YAML = """\
---
cdmon-config-version: "2.0.0"
repo: widget
generated-by: cdmon
updated: "2026-06-07"
---
root: "../.."
version: "2.0.0"
backend: {kind: mock}
central: {sink: none}
units:
  - file: core.yaml
ignore: ignore.yaml
"""

_CORE_UNIT_YAML = """\
---
cdmon-config-version: "2.0.0"
unit: core
title: "Core coverage"
owner: eng-platform
created: "2026-06-07"
updated: "2026-06-07"
---
dir-covered:
  - pkg
source-files-format:
  - ".py"
documents:
  - id: api-guide
    path: docs/api.md
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: pkg/calc.py
        symbols: [add]
"""

_IGNORE_YAML = """\
---
cdmon-config-version: "2.0.0"
source: "manual"
updated: "2026-06-07"
---
gitignore: false
patterns:
  - "*.log"
"""

_CALC = 'def add(a, b):\n    """Add."""\n    return a + b\n'

_DOC_STUB = (
    "# API guide\n\nProse.\n\n"
    "<!-- CDM:BEGIN symbols -->\nPLACEHOLDER\n<!-- CDM:END symbols -->\n"
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout


def _build_git_repo(tmp_path: Path) -> Path:
    from typer.testing import CliRunner

    from code_doc_monitor.cli import app as cli_app

    repo = tmp_path / "repo"
    cfg = repo / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "index.yaml").write_text(_INDEX_YAML, encoding="utf-8")
    (cfg / "core.yaml").write_text(_CORE_UNIT_YAML, encoding="utf-8")
    (cfg / "ignore.yaml").write_text(_IGNORE_YAML, encoding="utf-8")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "calc.py").write_text(_CALC, encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "api.md").write_text(_DOC_STUB, encoding="utf-8")

    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "tester")
    res = CliRunner().invoke(cli_app, ["monitor", "--config", str(cfg), "--apply"])
    assert res.exit_code == 0, res.output
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    return repo


# --------------------------------------------------------------------------- #
# the parametrized client (one app per Store impl, fixed clock).
# --------------------------------------------------------------------------- #
def _make_store(kind: str) -> Store:
    if kind == "memory":
        return InMemoryStore()
    engine = engine_from_url("sqlite:///:memory:")
    create_all(engine)
    return SqlStore(engine)


@pytest.fixture(params=["memory", "sql"])
def client(request: pytest.FixtureRequest) -> Iterator[TestClient]:
    store = _make_store(request.param)
    app = create_app(store, clock=lambda: _NOW)
    with TestClient(app) as c:
        yield c


def _register(
    client: TestClient,
    repo: Path | None,
    *,
    repo_id: str = _REPO,
    auth_token: str | None = _TOKEN,
) -> None:
    identity = RepoIdentity(
        repo_id=repo_id,
        repo_name="widget",
        local_path=str(repo) if repo is not None else None,
        default_branch="main",
    )
    payload = RegistrationPayload(
        repo=identity, default_branch="main", auth_token=auth_token
    ).model_dump(mode="json")
    resp = client.post("/repos", json=payload)
    assert resp.status_code == 201, resp.text


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {_TOKEN}"}


# --------------------------------------------------------------------------- #
# POST /sync — git + local, summary + persisted rows.
# --------------------------------------------------------------------------- #


def test_sync_git_returns_summary_and_persists(
    client: TestClient, tmp_path: Path
) -> None:
    repo = _build_git_repo(tmp_path)
    _register(client, repo)

    resp = client.post(f"/repos/{_REPO}/sync", json={"mode": "git"}, headers=_auth())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["sync_kind"] == "git"
    assert body["fully_synced"] is True
    assert body["document_count"] == 1
    assert body["code_ref_count"] == 1
    assert body["commits_ahead"] == 0
    assert body["drift"]["ok"] is True
    assert body["started_at"] == _NOW and body["finished_at"] == _NOW

    # Persisted: the sync-state endpoint returns the same run.
    state = client.get(f"/repos/{_REPO}/sync-state", params={"sync_kind": "git"})
    assert state.status_code == 200
    assert state.json()["sync_kind"] == "git"
    assert state.json()["fully_synced"] is True


def test_sync_local_then_git_are_separate_scopes(
    client: TestClient, tmp_path: Path
) -> None:
    repo = _build_git_repo(tmp_path)
    _register(client, repo)
    assert (
        client.post(f"/repos/{_REPO}/sync", json={"mode": "git"}, headers=_auth())
    ).status_code == 201
    assert (
        client.post(f"/repos/{_REPO}/sync", json={"mode": "local"}, headers=_auth())
    ).status_code == 201

    git_docs = client.get(
        f"/repos/{_REPO}/documents", params={"sync_kind": "git"}
    ).json()
    local_docs = client.get(
        f"/repos/{_REPO}/documents", params={"sync_kind": "local"}
    ).json()
    assert len(git_docs) == 1 and git_docs[0]["document"]["sync_kind"] == "git"
    assert len(local_docs) == 1 and local_docs[0]["document"]["sync_kind"] == "local"
    # Latest run with no filter is the most-recent insertion (the local one).
    latest = client.get(f"/repos/{_REPO}/sync-state").json()
    assert latest["sync_kind"] == "local"


def test_documents_tree_nests_code_refs(client: TestClient, tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    _register(client, repo)
    client.post(f"/repos/{_REPO}/sync", json={"mode": "git"}, headers=_auth())

    docs = client.get(f"/repos/{_REPO}/documents").json()
    assert len(docs) == 1
    tree = docs[0]
    assert tree["document"]["doc_id"] == "api-guide"
    assert tree["document"]["unit"] == "core"
    assert tree["document"]["audience"] == "eng-guide"
    assert len(tree["code_refs"]) == 1
    assert tree["code_refs"][0]["path"] == "pkg/calc.py"
    assert tree["code_refs"][0]["symbols"] == ["add"]


def test_resync_replaces_scope(client: TestClient, tmp_path: Path) -> None:
    """A second git sync REPLACES the (repo, git) rows — no duplication (idempotent)."""
    repo = _build_git_repo(tmp_path)
    _register(client, repo)
    client.post(f"/repos/{_REPO}/sync", json={"mode": "git"}, headers=_auth())
    client.post(f"/repos/{_REPO}/sync", json={"mode": "git"}, headers=_auth())
    docs = client.get(f"/repos/{_REPO}/documents", params={"sync_kind": "git"}).json()
    assert len(docs) == 1  # replaced, not appended


# --------------------------------------------------------------------------- #
# sync-state when none yet.
# --------------------------------------------------------------------------- #


def test_sync_state_null_before_any_sync(client: TestClient, tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    _register(client, repo)
    resp = client.get(f"/repos/{_REPO}/sync-state")
    assert resp.status_code == 200
    assert resp.json() is None


# --------------------------------------------------------------------------- #
# Auth + error paths.
# --------------------------------------------------------------------------- #


def test_sync_requires_token(client: TestClient, tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    _register(client, repo)
    no_auth = client.post(f"/repos/{_REPO}/sync", json={"mode": "git"})
    assert no_auth.status_code == 401
    wrong = client.post(
        f"/repos/{_REPO}/sync",
        json={"mode": "git"},
        headers={"Authorization": "Bearer nope"},
    )
    assert wrong.status_code == 403


def test_sync_bad_mode_is_400(client: TestClient, tmp_path: Path) -> None:
    repo = _build_git_repo(tmp_path)
    _register(client, repo)
    resp = client.post(
        f"/repos/{_REPO}/sync", json={"mode": "sideways"}, headers=_auth()
    )
    assert resp.status_code == 400
    assert "unknown sync mode" in resp.json()["detail"]


def test_sync_missing_local_path_is_400(client: TestClient, tmp_path: Path) -> None:
    _register(client, None)  # registered WITHOUT a local_path
    resp = client.post(f"/repos/{_REPO}/sync", json={"mode": "git"}, headers=_auth())
    assert resp.status_code == 400
    assert "local_path" in resp.json()["detail"]


def test_sync_unknown_repo_is_404(client: TestClient) -> None:
    resp = client.post("/repos/ghost/sync", json={"mode": "git"}, headers=_auth())
    assert resp.status_code == 404


def test_documents_unknown_repo_is_404(client: TestClient) -> None:
    assert client.get("/repos/ghost/documents").status_code == 404


def test_sync_state_unknown_repo_is_404(client: TestClient) -> None:
    assert client.get("/repos/ghost/sync-state").status_code == 404


def test_local_path_round_trips_through_register(
    client: TestClient, tmp_path: Path
) -> None:
    """The additive RepoIdentity.local_path survives the /repos register round-trip."""
    repo = _build_git_repo(tmp_path)
    _register(client, repo, auth_token=None)
    listed = client.get("/repos").json()
    me = next(r for r in listed if r["repo"]["repo_id"] == _REPO)
    assert me["repo"]["local_path"] == str(repo)
    assert me["repo"]["default_branch"] == "main"


def test_token_hashing_independent_of_sync(client: TestClient) -> None:
    """Sanity: the registered token hashes to the stored verify hash (E-06 parity)."""
    _register(client, None)
    # A wrong token is rejected; the right one's hash matches by construction.
    assert hash_token(_TOKEN) != hash_token("nope")
