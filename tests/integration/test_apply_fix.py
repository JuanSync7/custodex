"""EDITOR E-07 — the one-click "apply the LLM's proposed fix" engine + route.

Two halves, all offline + deterministic (K10), operating on a COPY of the demo
(the checked-in demo is NEVER mutated):

* **Engine** (:func:`custodex.generate.apply_record_fix`, no server):
  induce a real drift on a documented source file (add a public method to the
  demo's ``engine.py``), run :class:`Monitor` over the temp copy WITHOUT applying
  to obtain a real :class:`ReviewRecord` with a ``FIX`` verdict + a ``fix``, then
  call :func:`apply_record_fix` and assert it applied, the diff is non-empty, and
  ``cdx check`` is now clean. A SECOND apply of the same record is a no-op (empty
  diff, ``applied=False``, K7). A record with no applicable fix is a loud K8 error.
* **Route** (a ``TestClient`` over BOTH stores, against a temp demo git copy): a
  token-protected repo whose ``local_path`` is the temp copy ingests the drift
  record; ``POST .../records/{id}/apply-fix`` makes the fix live (201), the diff is
  non-empty, an ``accepted`` resolution now exists, and the post-apply sync run is
  fully-synced. A repo without ``local_path`` → 409; an unknown record → 404; a
  record without a fix → 409; missing/invalid token → 401/403 (mirrors ``/sync``).

Features: FEAT-SERVER-013, FEAT-SERVER-004, FEAT-SERVER-005
Features: FEAT-CONFIGV2-013, FEAT-CONFIGV2-012, FEAT-HEAL-008
Features: FEAT-MONITOR-003, FEAT-MONITOR-004, FEAT-RECORD-006
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from custodex.config import load_config_dir
from custodex.errors import CodeDocMonitorError
from custodex.generate import apply_record_fix
from custodex.monitor import Monitor
from custodex.schema import ReviewRecord, Verdict
from custodex.sinks import NullSink
from tests._repo import REPO_ROOT

_NOW = "2026-06-08T00:00:00Z"
_ENGINE = "src/taskflow/core/engine.py"

_DEMO = REPO_ROOT / "demo"

# A module-level public function appended to the demo's `engine.py`. It drifts
# ONLY `core-api` (whose code_refs cover engine.py WHOLE-file) — NOT
# `getting-started`, which symbol-selects only the `Engine` type — so the induced
# drift is isolated to one document and one record's fix heals it completely.
_NEW_METHOD = (
    "\n\ndef brand_new_engine_helper(x: int) -> int:\n"
    '    """A new module-level helper public to the engine API."""\n'
    "    return x\n"
)


def _copy_demo(dest: Path) -> Path:
    repo = dest / "repo"
    shutil.copytree(_DEMO, repo)
    return repo


def _induce_drift(repo: Path) -> None:
    """Add a public method to the demo's documented ``engine.py`` (drifts core-api)."""
    engine = repo / "src" / "taskflow" / "core" / "engine.py"
    engine.write_text(
        engine.read_text(encoding="utf-8") + _NEW_METHOD, encoding="utf-8"
    )


def _check_clean(config_dir: Path) -> int:
    from typer.testing import CliRunner

    from custodex.cli import app as cli_app

    res = CliRunner().invoke(cli_app, ["check", "--config", str(config_dir)])
    return res.exit_code


def _fix_record(repo: Path) -> ReviewRecord:
    """A real whole-doc FIX ReviewRecord from running Monitor (apply=False).

    The induced engine.py edit yields TWO drifts on the same doc — a HASH
    (whole-doc) drift and a REGION drift. The HASH record's fix carries
    ``new_doc_text`` (the full corrected document, which also refreshes the
    fingerprint), so applying it alone clears BOTH; a region-only fix would leave
    the stale fingerprint behind. We deterministically pick that whole-doc fix.
    """
    config_dir = repo / "config" / "cdmon"
    cfg = load_config_dir(config_dir)
    monitor = Monitor(cfg, config_dir, now=lambda: _NOW, sink=NullSink())
    result = monitor.run(apply=False)
    fix_records = [
        r
        for r in result.records
        if r.verdict is Verdict.FIX and r.fix and r.fix.new_doc_text is not None
    ]
    assert fix_records, "expected a whole-doc FIX record from the induced drift"
    return fix_records[0]


# --------------------------------------------------------------------------- #
# Engine — offline, on a demo copy.
# --------------------------------------------------------------------------- #


def test_apply_record_fix_heals_and_is_idempotent(tmp_path: Path) -> None:
    repo = _copy_demo(tmp_path)
    config_dir = repo / "config" / "cdmon"
    assert _check_clean(config_dir) == 0  # copy starts clean

    _induce_drift(repo)
    assert _check_clean(config_dir) != 0  # drift detected

    record = _fix_record(repo)

    result = apply_record_fix(repo, record, now=_NOW)
    assert result.applied is True
    assert result.diff != ""
    assert result.doc_path == record.doc_path
    assert _check_clean(config_dir) == 0  # the doc is now in sync

    # K7: re-applying the SAME record is a no-op (empty diff, applied=False).
    again = apply_record_fix(repo, record, now=_NOW)
    assert again.applied is False
    assert again.diff == ""


def test_apply_record_fix_no_fix_is_loud(tmp_path: Path) -> None:
    repo = _copy_demo(tmp_path)
    _induce_drift(repo)
    record = _fix_record(repo)

    # Strip the fix (a non-applicable record) → loud K8 error from the engine.
    no_fix = record.model_copy(update={"fix": None})
    with pytest.raises(CodeDocMonitorError):
        apply_record_fix(repo, no_fix, now=_NOW)

    # A non-FIX verdict (INVALIDATE) with a fix is equally not applicable.
    not_fix_verdict = record.model_copy(update={"verdict": Verdict.INVALIDATE})
    with pytest.raises(CodeDocMonitorError):
        apply_record_fix(repo, not_fix_verdict, now=_NOW)


# --------------------------------------------------------------------------- #
# Route — TestClient over BOTH stores, against a temp demo git copy.
# --------------------------------------------------------------------------- #

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")
pytest.importorskip(
    "sqlalchemy", reason="the [server] extra (sqlalchemy) is not installed"
)

from fastapi.testclient import TestClient  # noqa: E402

from custodex.registry import RegistrationPayload  # noqa: E402
from custodex.server import InMemoryStore, create_app  # noqa: E402
from custodex.server.db import (  # noqa: E402
    SqlStore,
    create_all,
    engine_from_url,
)
from custodex.server.store import Store  # noqa: E402
from custodex.sinks import RepoIdentity  # noqa: E402

_REPO = "acme/widget"
_NO_LOCAL_REPO = "acme/central-only"
_TOKEN = "s3cret-token"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True
    )


def _demo_git_repo(tmp_path: Path) -> Path:
    repo = _copy_demo(tmp_path)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "tester")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    return repo


def _make_store(kind: str) -> Store:
    if kind == "memory":
        return InMemoryStore()
    engine = engine_from_url("sqlite:///:memory:")
    create_all(engine)
    return SqlStore(engine)


@pytest.fixture(params=["memory", "sql"])
def store(request: pytest.FixtureRequest) -> Store:
    return _make_store(request.param)


@pytest.fixture
def client(store: Store) -> Iterator[TestClient]:
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


def _ingest_drift_record(store: Store, repo: Path) -> ReviewRecord:
    """Induce a drift, harvest its FIX record, and ingest it into the store."""
    _induce_drift(repo)
    record = _fix_record(repo)
    store.add_record(_REPO, record)
    return record


def test_apply_fix_route_makes_fix_live(
    client: TestClient, store: Store, tmp_path: Path
) -> None:
    repo = _demo_git_repo(tmp_path)
    _register(client, repo)
    record = _ingest_drift_record(store, repo)

    resp = client.post(
        f"/repos/{_REPO}/records/{record.record_id}/apply-fix",
        json={},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["applied"] is True
    assert body["diff"] != ""
    assert body["doc_path"] == record.doc_path
    assert body["sync_run"]["fully_synced"] is True

    # An `accepted` resolution now links the record.
    resolutions = client.get(
        f"/repos/{_REPO}/resolutions", params={"record_id": record.record_id}
    ).json()
    assert len(resolutions) == 1
    assert resolutions[0]["resolution"] == "accepted"
    assert resolutions[0]["record_id"] == record.record_id


def test_apply_fix_route_unknown_record_is_404(
    client: TestClient, tmp_path: Path
) -> None:
    repo = _demo_git_repo(tmp_path)
    _register(client, repo)
    resp = client.post(
        f"/repos/{_REPO}/records/does-not-exist/apply-fix",
        json={},
        headers=_auth(),
    )
    assert resp.status_code == 404, resp.text


def test_apply_fix_route_record_without_fix_is_409(
    client: TestClient, store: Store, tmp_path: Path
) -> None:
    repo = _demo_git_repo(tmp_path)
    _register(client, repo)
    _induce_drift(repo)
    record = _fix_record(repo)
    # Ingest the record with its fix stripped → not applicable.
    no_fix = record.model_copy(update={"fix": None})
    store.add_record(_REPO, no_fix)

    resp = client.post(
        f"/repos/{_REPO}/records/{record.record_id}/apply-fix",
        json={},
        headers=_auth(),
    )
    assert resp.status_code == 409, resp.text


def test_apply_fix_route_repo_without_local_path_is_409(
    client: TestClient, store: Store
) -> None:
    _register(client, None, repo_id=_NO_LOCAL_REPO)
    # Ingest any record id; the local_path guard fires before record lookup.
    resp = client.post(
        f"/repos/{_NO_LOCAL_REPO}/records/whatever/apply-fix",
        json={},
        headers=_auth(),
    )
    assert resp.status_code == 409, resp.text


def test_apply_fix_route_requires_token(
    client: TestClient, store: Store, tmp_path: Path
) -> None:
    repo = _demo_git_repo(tmp_path)
    _register(client, repo)
    record = _ingest_drift_record(store, repo)

    no_auth = client.post(
        f"/repos/{_REPO}/records/{record.record_id}/apply-fix", json={}
    )
    assert no_auth.status_code == 401

    wrong = client.post(
        f"/repos/{_REPO}/records/{record.record_id}/apply-fix",
        json={},
        headers={"Authorization": "Bearer nope"},
    )
    assert wrong.status_code == 403


def test_apply_fix_route_unknown_repo_is_404(client: TestClient) -> None:
    resp = client.post("/repos/nope/records/x/apply-fix", json={}, headers=_auth())
    assert resp.status_code == 404
