"""EDITOR E-06 — the "Generate / make live" engine + ``POST /config/generate``.

Two halves, all offline + deterministic (K10), operating on a COPY of the demo
(the checked-in demo is NEVER mutated):

* **Engine** (:func:`custodex.generate.apply_edits_to_disk`, no server):
  link the demo's intentionally-UNLINKED ``scheduler.py`` to a document, then
  assert the unit yaml gains it on disk, the doc exists, ``cdx check`` is clean,
  the coverage ``undocumented`` gap closes, and a SECOND identical run is a
  byte-identical no-op (K7). Plus ``set_context_refs`` and ``set_doc_style`` land
  on disk and re-load.
* **Route** (a ``TestClient`` over BOTH stores): a repo registered with
  ``local_path`` = a temp demo git copy stages a link edit, ``POST
  /config/generate`` makes it live (200/201), ``undocumented_files`` drops
  ``scheduler.py``, the sync run is fully-synced, the edit flips to ``applied``,
  and the document tree shows the new mapping. A repo WITHOUT ``local_path`` →
  409; missing/invalid token → 401/403 (mirrors ``/sync``).

Features: FEAT-CONFIGV2-013, FEAT-SERVER-012, FEAT-SERVER-011, FEAT-SERVER-004
Features: FEAT-COVERAGE-001, FEAT-CONFIG-003, FEAT-QUALITY-004
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from custodex.config import load_unit_file
from custodex.docstyle import load_doc_style
from custodex.generate import apply_edits_to_disk
from custodex.server.edits import (
    AddCodeRefEdit,
    EditCodeRef,
    EditContextRef,
    EditDocStyle,
    ReassignOwnerEdit,
    SetContextRefsEdit,
    SetDocStyleEdit,
)
from tests._repo import REPO_ROOT

_NOW = "2026-06-08T00:00:00Z"
_SCHEDULER = "src/taskflow/core/scheduler.py"

_DEMO = REPO_ROOT / "demo"


def _copy_demo(dest: Path) -> Path:
    repo = dest / "repo"
    shutil.copytree(_DEMO, repo)
    return repo


def _check_clean(config_dir: Path) -> int:
    from typer.testing import CliRunner

    from custodex.cli import app as cli_app

    res = CliRunner().invoke(cli_app, ["check", "--config", str(config_dir)])
    return res.exit_code


def _undocumented(config_dir: Path) -> set[str]:
    from custodex import inventory
    from custodex.config import (
        effective_coverage,
        load_bundle,
        resolve_repo_root,
    )
    from custodex.coverage import resolve_coverage

    bundle = load_bundle(config_dir)
    root = resolve_repo_root(config_dir, bundle.index.root)
    cov = effective_coverage(bundle, root)
    inv = inventory.discover_files(root, include=cov.include, exclude=cov.exclude)
    sym = inventory.discover_symbols(inv, root)
    report = resolve_coverage(bundle.config, sym)
    return {f.path for f in report.undocumented_files}


# --------------------------------------------------------------------------- #
# Engine — offline, on a demo copy.
# --------------------------------------------------------------------------- #


def test_add_code_ref_links_scheduler_and_closes_gap(tmp_path: Path) -> None:
    repo = _copy_demo(tmp_path)
    config_dir = repo / "config" / "cdmon"

    assert _SCHEDULER in _undocumented(config_dir)

    edit = AddCodeRefEdit(
        unit="core", doc_id="core-api", ref=EditCodeRef(path=_SCHEDULER)
    )
    result = apply_edits_to_disk(repo, [edit], now=_NOW)

    # The unit yaml on disk now lists scheduler.py.
    unit = load_unit_file(config_dir / "core.yaml")
    core_api = next(d for d in unit.documents if d.id == "core-api")
    assert any(r.path == _SCHEDULER for r in core_api.code_refs)
    assert "core" in result.affected_units
    assert "docs/api/core-api.md" in result.affected_docs

    # The doc exists and `cdx check` is clean (no drift).
    assert (repo / "docs" / "api" / "core-api.md").is_file()
    assert _check_clean(config_dir) == 0

    # scheduler.py is no longer an undocumented gap.
    assert _SCHEDULER not in _undocumented(config_dir)


def test_add_code_ref_second_run_is_byte_identical_noop(tmp_path: Path) -> None:
    repo = _copy_demo(tmp_path)
    config_dir = repo / "config" / "cdmon"
    edit = AddCodeRefEdit(
        unit="core", doc_id="core-api", ref=EditCodeRef(path=_SCHEDULER)
    )

    apply_edits_to_disk(repo, [edit], now=_NOW)
    unit_bytes = (config_dir / "core.yaml").read_bytes()
    index_bytes = (config_dir / "index.yaml").read_bytes()
    doc_bytes = (repo / "docs" / "api" / "core-api.md").read_bytes()

    # K7: a SECOND identical run is a byte-identical no-op heal.
    apply_edits_to_disk(repo, [edit], now=_NOW)
    assert (config_dir / "core.yaml").read_bytes() == unit_bytes
    assert (config_dir / "index.yaml").read_bytes() == index_bytes
    assert (repo / "docs" / "api" / "core-api.md").read_bytes() == doc_bytes


def test_create_doc_for_scheduler_closes_gap(tmp_path: Path) -> None:
    from custodex.server.edits import CreateDocEdit

    repo = _copy_demo(tmp_path)
    config_dir = repo / "config" / "cdmon"

    edit = CreateDocEdit(
        unit="core",
        doc_id="scheduler-api",
        path="docs/api/scheduler-api.md",
        audience="eng-guide",
        code_refs=(EditCodeRef(path=_SCHEDULER),),
    )
    apply_edits_to_disk(repo, [edit], now=_NOW)

    unit = load_unit_file(config_dir / "core.yaml")
    assert any(d.id == "scheduler-api" for d in unit.documents)
    assert (repo / "docs" / "api" / "scheduler-api.md").is_file()
    assert _check_clean(config_dir) == 0
    assert _SCHEDULER not in _undocumented(config_dir)


def test_set_context_refs_lands_on_disk(tmp_path: Path) -> None:
    repo = _copy_demo(tmp_path)
    config_dir = repo / "config" / "cdmon"

    edit = SetContextRefsEdit(
        unit="core",
        doc_id="getting-started",
        context_refs=(
            EditContextRef(path="docs/api/core-api.md", note="full reference"),
        ),
    )
    apply_edits_to_disk(repo, [edit], now=_NOW)

    unit = load_unit_file(config_dir / "core.yaml")
    doc = next(d for d in unit.documents if d.id == "getting-started")
    assert [cr.path for cr in doc.context_refs] == ["docs/api/core-api.md"]
    assert doc.context_refs[0].note == "full reference"
    assert _check_clean(config_dir) == 0


def test_set_doc_style_updates_mapping_round_trips(tmp_path: Path) -> None:
    repo = _copy_demo(tmp_path)
    config_dir = repo / "config" / "cdmon"
    templates_root = repo / "templates" / "writing"

    # core-api starts at writing-style=reference-dense; flip just that dimension.
    edit = SetDocStyleEdit(
        doc_id="core-api",
        doc_style=EditDocStyle(writing_style="concise"),
    )
    result = apply_edits_to_disk(repo, [edit], now=_NOW)
    assert result.wrote_doc_style is True

    loaded = load_doc_style(
        config_dir / "doc-style.yaml", templates_root=templates_root
    )
    selection = loaded.style_for("core-api")
    assert selection.writing_style == "concise"
    # The untouched dimensions keep their prior values.
    assert selection.document_type == "api-reference"
    assert selection.tone == "precise"
    assert selection.vocabulary == "engine-domain"


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
_OPEN_REPO = "acme/open"
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


def _stage_link_edit(client: TestClient, repo_id: str = _REPO) -> str:
    body = {
        "action": "add_code_ref",
        "unit": "core",
        "doc_id": "core-api",
        "ref": {"path": _SCHEDULER, "symbols": [], "lines": None},
    }
    resp = client.post(f"/repos/{repo_id}/config/edits", json=body, headers=_auth())
    assert resp.status_code == 201, resp.text
    return resp.json()["edit_id"]


def test_generate_makes_link_live(client: TestClient, tmp_path: Path) -> None:
    repo = _demo_git_repo(tmp_path)
    _register(client, repo)
    edit_id = _stage_link_edit(client)

    resp = client.post(f"/repos/{_REPO}/config/generate", json={}, headers=_auth())
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["applied"] == [edit_id]
    assert _SCHEDULER not in body["undocumented_files"]
    assert body["sync_run"]["fully_synced"] is True

    # The edit is now applied (and out of the pending list).
    applied = client.get(
        f"/repos/{_REPO}/config/edits", params={"status": "applied"}
    ).json()
    assert [e["edit_id"] for e in applied] == [edit_id]
    pending = client.get(
        f"/repos/{_REPO}/config/edits", params={"status": "pending"}
    ).json()
    assert pending == []

    # The freshly-synced document tree shows scheduler.py under core-api.
    docs = client.get(
        f"/repos/{_REPO}/config/editable", params={"sync_kind": "local"}
    ).json()
    core_api = next(
        d for d in docs["documents"] if d["document"]["doc_id"] == "core-api"
    )
    assert _SCHEDULER in [r["path"] for r in core_api["code_refs"]]
    assert _SCHEDULER not in docs["undocumented_files"]


def test_generate_no_pending_is_noop(client: TestClient, tmp_path: Path) -> None:
    repo = _demo_git_repo(tmp_path)
    _register(client, repo)

    resp = client.post(f"/repos/{_REPO}/config/generate", json={}, headers=_auth())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["applied"] == []
    # scheduler.py is still an unlinked gap (nothing was applied).
    assert _SCHEDULER in body["undocumented_files"]


def test_generate_repo_without_local_path_is_409(client: TestClient) -> None:
    _register(client, None, repo_id=_NO_LOCAL_REPO)
    resp = client.post(
        f"/repos/{_NO_LOCAL_REPO}/config/generate", json={}, headers=_auth()
    )
    assert resp.status_code == 409, resp.text


def test_generate_requires_token(client: TestClient, tmp_path: Path) -> None:
    repo = _demo_git_repo(tmp_path)
    _register(client, repo)

    no_auth = client.post(f"/repos/{_REPO}/config/generate", json={})
    assert no_auth.status_code == 401

    wrong = client.post(
        f"/repos/{_REPO}/config/generate",
        json={},
        headers={"Authorization": "Bearer nope"},
    )
    assert wrong.status_code == 403


def test_generate_unknown_repo_is_404(client: TestClient) -> None:
    resp = client.post("/repos/nope/config/generate", json={}, headers=_auth())
    assert resp.status_code == 404


def test_generate_only_selected_edit_ids(client: TestClient, tmp_path: Path) -> None:
    repo = _demo_git_repo(tmp_path)
    _register(client, repo)
    link_id = _stage_link_edit(client)
    # A second pending edit we will NOT select.
    other = client.post(
        f"/repos/{_REPO}/config/edits",
        json={
            "action": "set_context_refs",
            "unit": "core",
            "doc_id": "getting-started",
            "context_refs": [{"path": "docs/api/core-api.md", "note": "ref"}],
        },
        headers=_auth(),
    ).json()["edit_id"]

    resp = client.post(
        f"/repos/{_REPO}/config/generate",
        json={"edit_ids": [link_id]},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["applied"] == [link_id]

    pending = client.get(
        f"/repos/{_REPO}/config/edits", params={"status": "pending"}
    ).json()
    assert [e["edit_id"] for e in pending] == [other]


def test_reassign_owner_lands_on_disk(tmp_path: Path) -> None:
    """A reassign_owner edit rewrites the unit yaml owner; partial + idempotent (K7).

    Features: FEAT-OWNERSHIP-008
    """
    repo = _copy_demo(tmp_path)
    core_yaml = repo / "config" / "cdmon" / "core.yaml"
    # demo core-api is owned by demo-team with dana as DRI; reassign just the DRI.
    edit = ReassignOwnerEdit(unit="core", doc_id="core-api", dri="erin")
    apply_edits_to_disk(repo, [edit], now=_NOW)
    unit = load_unit_file(core_yaml)
    doc = next(d for d in unit.documents if d.id == "core-api")
    assert doc.dri == "erin"  # reassigned
    assert doc.owner == "demo-team"  # partial reassignment keeps owner/team
    assert doc.team == "demo-team"
    # idempotent: a second identical apply is byte-identical (same now).
    before = core_yaml.read_text(encoding="utf-8")
    apply_edits_to_disk(repo, [edit], now=_NOW)
    assert core_yaml.read_text(encoding="utf-8") == before
