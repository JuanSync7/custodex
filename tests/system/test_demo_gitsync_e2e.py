"""GIT-04 system e2e — the REAL demo repo, cloned on demand, synced + docs-PR'd.

The user's literal scenario, end to end with NO network and NO local_path: the
central server is handed a repo it does NOT hold on disk (only a ``provider`` +
``remote_url``), clones it on demand from a REAL ``file://`` git origin (the
committed ``demo/`` tree — EDR-safe, no network), and:

1. surfaces the demo's documents (core-api / getting-started / io-api) + a coverage
   snapshot — proving clone-on-demand ``POST /sync`` works for a not-local repo;
2. after a NEW file is committed to the origin, a re-sync SEES it (it appears in
   the refreshed coverage snapshot as undocumented) — "add a file + sync local → I
   see it", now over the clone-on-demand path;
3. after a documented source symbol DRIFTS upstream, ``POST /docs-pr`` clones,
   heals, and opens a PR carrying the healed doc (through an injected transport).

Features: FEAT-CONFIGV2-012, FEAT-SERVER-003
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests._repo import REPO_ROOT

pytest.importorskip("fastapi", reason="the [server] extra is not installed")

from fastapi.testclient import TestClient  # noqa: E402

from code_doc_monitor.registry import RegistrationPayload  # noqa: E402
from code_doc_monitor.server import InMemoryStore, create_app  # noqa: E402
from code_doc_monitor.sinks import RepoIdentity  # noqa: E402

_NOW = "2026-06-10T00:00:00Z"
_REPO = "demo-taskflow"
_DEMO = REPO_ROOT / "demo"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    )


def _demo_origin(tmp_path: Path) -> Path:
    """A real git origin holding a COPY of the committed ``demo/`` tree (on ``main``)."""
    origin = tmp_path / "demo-origin"
    shutil.copytree(_DEMO, origin)
    _git(origin, "init", "-q")
    _git(origin, "config", "user.email", "t@t")
    _git(origin, "config", "user.name", "t")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-q", "-m", "import demo")
    _git(origin, "branch", "-M", "main")
    return origin


def _register(client: TestClient, origin: Path) -> None:
    payload = RegistrationPayload(
        repo=RepoIdentity(
            repo_id=_REPO,
            provider="github",
            remote_url=f"file://{origin}",  # a not-local repo; cloned on demand
            default_branch="main",
        ),
        default_branch="main",
    )
    assert (
        client.post("/repos", json=payload.model_dump(mode="json")).status_code == 201
    )


def _cov_files(snapshot: dict) -> dict[str, str]:
    return {f["path"]: f["status"] for f in snapshot["files"]}


class _FakeTransport:
    def __init__(self) -> None:
        self.plans: list[Any] = []

    def submit(self, plan: Any) -> dict:
        self.plans.append(plan)
        return {"html_url": "https://provider/pr/1"}


def test_demo_clone_on_demand_sync_surfaces_docs_and_coverage(tmp_path: Path) -> None:
    origin = _demo_origin(tmp_path)
    client = TestClient(create_app(InMemoryStore(), clock=lambda: _NOW))
    _register(client, origin)

    resp = client.post(f"/repos/{_REPO}/sync", json={"mode": "local"})
    assert resp.status_code == 201, resp.text

    docs = client.get(f"/repos/{_REPO}/documents", params={"sync_kind": "local"}).json()
    doc_ids = {d["document"]["doc_id"] for d in docs}
    assert {"core-api", "getting-started", "io-api"} <= doc_ids
    cov = client.get(f"/repos/{_REPO}/coverage").json()
    assert len(cov) == 1
    assert cov[0]["captured_at"] == _NOW


def test_demo_add_file_to_origin_then_resync_sees_it(tmp_path: Path) -> None:
    origin = _demo_origin(tmp_path)
    client = TestClient(create_app(InMemoryStore(), clock=lambda: _NOW))
    _register(client, origin)

    # sync #1: baseline coverage of the committed demo.
    client.post(f"/repos/{_REPO}/sync", json={"mode": "local"})
    snap1 = client.get(f"/repos/{_REPO}/coverage").json()[-1]
    before = snap1["percent_files"]

    # add a NEW undocumented source file UPSTREAM (under the core unit's dir-covered)
    # and commit it to the origin.
    new_file = origin / "src" / "taskflow" / "core" / "extra.py"
    new_file.write_text(
        'def brand_new(x):\n    """A new public symbol nobody documents yet."""\n'
        "    return x\n",
        encoding="utf-8",
    )
    _git(origin, "add", "-A")
    _git(origin, "commit", "-q", "-m", "add core/extra.py")

    # sync #2: clone-on-demand re-fetches the updated origin → the new file shows up.
    client.post(f"/repos/{_REPO}/sync", json={"mode": "local"})
    snap2 = client.get(f"/repos/{_REPO}/coverage").json()[-1]
    files = _cov_files(snap2)
    assert "src/taskflow/core/extra.py" in files
    assert files["src/taskflow/core/extra.py"] == "undocumented"
    assert snap2["percent_files"] <= before  # a new undocumented file can't raise %


def test_demo_docs_pr_after_upstream_drift_opens_pr(tmp_path: Path) -> None:
    origin = _demo_origin(tmp_path)
    # Drift a DOCUMENTED symbol upstream so the eng-guide doc goes stale, then commit.
    model = origin / "src" / "taskflow" / "core" / "model.py"
    if model.is_file():
        model.write_text(
            model.read_text(encoding="utf-8") + "\n\ndef newly_added_public(a, b):\n"
            '    """A new documented-surface symbol that drifts core-api."""\n'
            "    return a + b\n",
            encoding="utf-8",
        )
        _git(origin, "add", "-A")
        _git(origin, "commit", "-q", "-m", "drift model.py")

    fake = _FakeTransport()
    client = TestClient(
        create_app(
            InMemoryStore(),
            clock=lambda: _NOW,
            pr_transport_factory=lambda provider, url, token: fake,
        )
    )
    _register(client, origin)

    resp = client.post(f"/repos/{_REPO}/docs-pr", json={})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["opened"] is True
    assert body["changed_paths"]  # at least the drifted eng-guide doc
    assert len(fake.plans) == 1
