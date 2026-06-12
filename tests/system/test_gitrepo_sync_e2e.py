"""GIT-06 system e2e — the git-sync flow works against ANY real git repo.

The earlier ``test_demo_gitsync_e2e.py`` proved clone-on-demand sync for the
demo over a single-commit ``file://`` origin. This generalizes that proof: the
SAME server flow is driven over several DIFFERENT real git repos — the live
``demo/`` tree, a minimal one-unit repo, and a two-unit repo whose default
branch is ``trunk`` (not ``main``) — each materialized with an AUTHENTIC
multi-commit history (via :mod:`tests._gitrepo`), with NO network (real ``git``
over ``file://``, EDR-safe). What holds for one repo holds for all of them:

1. **clone-on-demand sync** surfaces the repo's documents + a coverage snapshot,
   resolves the real default-branch commit, and reports the right branch;
2. **resync sees an upstream change** — a new undocumented source file committed
   to the origin appears as ``undocumented`` after a re-sync;
3. **docs-PR on upstream drift** clones, heals, and opens a PR (injected
   transport) carrying the healed doc — for any repo shape.

Plus: the materialized repos carry a REAL multi-commit history (depth > 1);
git-MODE sync reads the default-branch baseline even when HEAD is on a feature
branch; clone-on-demand persists identically across BOTH Store backends; and
``scripts/demo_as_git.py`` builds a repo the server can actually sync.

Features: FEAT-GITSYNC-001, FEAT-GITSYNC-005, FEAT-CONFIGV2-012
Features: FEAT-SERVER-006, FEAT-PR-005
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests._gitrepo import GitRepo, file_url, repo_from_tree
from tests._repo import REPO_ROOT

pytest.importorskip("fastapi", reason="the [server] extra is not installed")

from fastapi.testclient import TestClient  # noqa: E402

from code_doc_monitor.registry import RegistrationPayload  # noqa: E402
from code_doc_monitor.server import InMemoryStore, create_app  # noqa: E402
from code_doc_monitor.sinks import RepoIdentity  # noqa: E402

_NOW = "2026-06-11T00:00:00Z"
_DEMO = REPO_ROOT / "demo"

# A believable history applied to ANY tree: each step stages whatever it names
# that exists, building real commits; the catch-all in repo_from_tree sweeps the
# rest. So every materialized origin has depth > 1 (a genuine project history).
_HISTORY = (
    (
        "chore: project scaffolding",
        ("LICENSE", ".gitignore", ".editorconfig", "pyproject.toml"),
    ),
    ("feat: implementation", ("src", "pkg", "alpha", "beta")),
    (
        "docs: documentation + cdmon adoption",
        ("docs", "config", "README.md", "CHANGELOG.md", "templates"),
    ),
    ("test: unit tests", ("tests",)),
)


# --------------------------------------------------------------------------- #
# Synthetic repo builders — small valid dir-layout trees, healed before commit.
# --------------------------------------------------------------------------- #


def _heal(config_dir: Path) -> None:
    """Regenerate the managed doc regions so the tree is in sync before commit."""
    from typer.testing import CliRunner

    from code_doc_monitor.cli import app

    result = CliRunner().invoke(
        app, ["monitor", "--config", str(config_dir), "--apply"]
    )
    assert result.exit_code == 0, result.output


_DOC_STUB = (
    "# {title}\n\nProse.\n\n<!-- CDM:BEGIN symbols -->\nPLACEHOLDER\n"
    "<!-- CDM:END symbols -->\n"
)
_IGNORE_YAML = (
    '---\ncdmon-config-version: "2.0.0"\nsource: "manual"\nupdated: "2026-06-11"\n'
    '---\ngitignore: false\npatterns:\n  - "*.log"\n'
)


def _minimal_tree(root: Path) -> Path:
    """A one-unit repo: ``pkg/calc.py`` documented whole-file by ``api-guide``."""
    cfg = root / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "index.yaml").write_text(
        '---\ncdmon-config-version: "2.0.0"\nrepo: minimal\ngenerated-by: cdmon\n'
        'updated: "2026-06-11"\n---\nroot: "../.."\nversion: "2.0.0"\n'
        "apply_default: false\nbackend: {kind: mock}\ncentral: {sink: none}\n"
        "units:\n  - file: core.yaml\nignore: ignore.yaml\n",
        encoding="utf-8",
    )
    (cfg / "core.yaml").write_text(
        '---\ncdmon-config-version: "2.0.0"\nunit: core\ntitle: "Core"\n'
        'owner: eng\ncreated: "2026-06-11"\nupdated: "2026-06-11"\n---\n'
        'dir-covered:\n  - pkg\nsource-files-format:\n  - ".py"\n'
        "documents:\n  - id: api-guide\n    path: docs/api.md\n"
        "    audience: eng-guide\n    region_keys: [symbols]\n"
        "    code_refs:\n      - path: pkg/calc.py\n",
        encoding="utf-8",
    )
    (cfg / "ignore.yaml").write_text(_IGNORE_YAML, encoding="utf-8")
    (root / "pkg").mkdir()
    (root / "pkg" / "calc.py").write_text(
        'def add(a, b):\n    """Add two numbers."""\n    return a + b\n',
        encoding="utf-8",
    )
    (root / "docs").mkdir()
    (root / "docs" / "api.md").write_text(
        _DOC_STUB.format(title="API guide"), encoding="utf-8"
    )
    (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (root / "README.md").write_text("# minimal\n", encoding="utf-8")
    _heal(cfg)
    return root


def _multiunit_tree(root: Path) -> Path:
    """A two-unit repo (alpha + beta), each owning its own package + doc."""
    cfg = root / "config" / "cdmon"
    cfg.mkdir(parents=True)
    (cfg / "index.yaml").write_text(
        '---\ncdmon-config-version: "2.0.0"\nrepo: multi\ngenerated-by: cdmon\n'
        'updated: "2026-06-11"\n---\nroot: "../.."\nversion: "2.0.0"\n'
        "apply_default: false\nbackend: {kind: mock}\ncentral: {sink: none}\n"
        "units:\n  - file: alpha.yaml\n  - file: beta.yaml\nignore: ignore.yaml\n",
        encoding="utf-8",
    )
    for unit, doc in (("alpha", "alpha-api"), ("beta", "beta-api")):
        (cfg / f"{unit}.yaml").write_text(
            f'---\ncdmon-config-version: "2.0.0"\nunit: {unit}\ntitle: "{unit}"\n'
            f'owner: eng\ncreated: "2026-06-11"\nupdated: "2026-06-11"\n---\n'
            f'dir-covered:\n  - {unit}\nsource-files-format:\n  - ".py"\n'
            f"documents:\n  - id: {doc}\n    path: docs/{unit}.md\n"
            f"    audience: eng-guide\n    region_keys: [symbols]\n"
            f"    code_refs:\n      - path: {unit}/core.py\n",
            encoding="utf-8",
        )
        (root / unit).mkdir()
        (root / unit / "core.py").write_text(
            f'def run_{unit}(x):\n    """Run the {unit} step."""\n    return x\n',
            encoding="utf-8",
        )
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs" / f"{unit}.md").write_text(
            _DOC_STUB.format(title=f"{unit} API"), encoding="utf-8"
        )
    (cfg / "ignore.yaml").write_text(_IGNORE_YAML, encoding="utf-8")
    (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (root / "README.md").write_text("# multi\n", encoding="utf-8")
    _heal(cfg)
    return root


@dataclass(frozen=True)
class RepoCase:
    """One repo shape to drive the full git-sync flow over."""

    name: str
    default_branch: str
    build: Callable[[Path], Path]
    doc_ids: frozenset[str]
    covered_new_file: str  # a new .py under a covered dir (resync test)
    drift_file: str  # a whole-file-documented source to drift (docs-PR test)


_CASES = (
    RepoCase(
        name="demo",
        default_branch="main",
        build=lambda root: _DEMO,  # the live demo tree (copied by repo_from_tree)
        doc_ids=frozenset({"core-api", "getting-started", "readme", "io-api"}),
        covered_new_file="src/taskflow/core/extra.py",
        drift_file="src/taskflow/core/model.py",
    ),
    RepoCase(
        name="minimal",
        default_branch="main",
        build=_minimal_tree,
        doc_ids=frozenset({"api-guide"}),
        covered_new_file="pkg/extra.py",
        drift_file="pkg/calc.py",
    ),
    RepoCase(
        name="multiunit-trunk",
        default_branch="trunk",  # NOT "main" — proves the branch param flows through
        build=_multiunit_tree,
        doc_ids=frozenset({"alpha-api", "beta-api"}),
        covered_new_file="alpha/extra.py",
        drift_file="alpha/core.py",
    ),
)
_CASE_IDS = [c.name for c in _CASES]


def _origin_for(case: RepoCase, tmp_path: Path) -> GitRepo:
    """Build ``case``'s tree, then materialize it as a real git origin with history.

    The demo case's ``build`` ignores its arg and returns the live ``demo/`` dir;
    synthetic builds create a fresh tree under ``tmp_path``. ``repo_from_tree``
    copies whichever tree into the origin (never carrying a nested ``.git``).
    """
    src = case.build(tmp_path / "src")
    return repo_from_tree(
        src,
        tmp_path / "origin",
        history=_HISTORY,
        default_branch=case.default_branch,
    )


def _register(client: TestClient, origin: GitRepo, *, branch: str) -> str:
    repo_id = f"acme/{origin.path.parent.name}"
    payload = RegistrationPayload(
        repo=RepoIdentity(
            repo_id=repo_id,
            provider="github",
            remote_url=file_url(origin),  # a repo the server does NOT hold locally
            default_branch=branch,
        ),
        default_branch=branch,
    )
    assert (
        client.post("/repos", json=payload.model_dump(mode="json")).status_code == 201
    )
    return repo_id


def _cov_files(snapshot: dict) -> dict[str, str]:
    return {f["path"]: f["status"] for f in snapshot["files"]}


class _FakeTransport:
    def __init__(self) -> None:
        self.plans: list[Any] = []

    def submit(self, plan: Any) -> dict:
        self.plans.append(plan)
        return {"html_url": "https://provider/pr/1", "number": 1}


# --------------------------------------------------------------------------- #
# 1. clone-on-demand sync surfaces docs + coverage, over ANY repo shape.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_clone_on_demand_sync_surfaces_docs_and_coverage(
    case: RepoCase, tmp_path: Path
) -> None:
    origin = _origin_for(case, tmp_path)
    assert origin.commit_count() > 1, "the origin has an authentic multi-commit history"
    assert origin.current_branch() == case.default_branch

    client = TestClient(create_app(InMemoryStore(), clock=lambda: _NOW))
    repo_id = _register(client, origin, branch=case.default_branch)

    resp = client.post(f"/repos/{repo_id}/sync", json={"mode": "local"})
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["branch"] == case.default_branch
    assert run["main_commit"] == origin.head()  # the real default-branch tip
    assert run["document_count"] == len(case.doc_ids)

    docs = client.get(
        f"/repos/{repo_id}/documents", params={"sync_kind": "local"}
    ).json()
    assert {d["document"]["doc_id"] for d in docs} == set(case.doc_ids)
    cov = client.get(f"/repos/{repo_id}/coverage").json()
    assert len(cov) == 1 and cov[0]["captured_at"] == _NOW


# --------------------------------------------------------------------------- #
# 2. a new undocumented file committed upstream is seen on re-sync, any repo.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_resync_sees_new_upstream_file(case: RepoCase, tmp_path: Path) -> None:
    origin = _origin_for(case, tmp_path)
    client = TestClient(create_app(InMemoryStore(), clock=lambda: _NOW))
    repo_id = _register(client, origin, branch=case.default_branch)

    client.post(f"/repos/{repo_id}/sync", json={"mode": "local"})
    before = client.get(f"/repos/{repo_id}/coverage").json()[-1]["percent_files"]

    # Commit a NEW undocumented source file to the origin (under a covered dir).
    origin.commit_files(
        f"feat: add {case.covered_new_file}",
        {
            case.covered_new_file: (
                'def brand_new(x):\n    """Undocumented public symbol."""\n'
                "    return x\n"
            )
        },
    )

    client.post(f"/repos/{repo_id}/sync", json={"mode": "local"})
    snap = client.get(f"/repos/{repo_id}/coverage").json()[-1]
    files = _cov_files(snap)
    assert files.get(case.covered_new_file) == "undocumented"
    assert snap["percent_files"] <= before  # a new undocumented file can't raise %


# --------------------------------------------------------------------------- #
# 3. docs-PR on upstream drift opens a PR carrying the healed doc, any repo.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_docs_pr_after_upstream_drift_opens_pr(case: RepoCase, tmp_path: Path) -> None:
    origin = _origin_for(case, tmp_path)
    # Drift a whole-file-documented symbol upstream so its managed region goes
    # stale, then commit — the docs-PR heal must regenerate it into a patch.
    drift = origin.path / case.drift_file
    drift.write_text(
        drift.read_text(encoding="utf-8") + "\n\ndef newly_added_public(a, b):\n"
        '    """A new documented-surface symbol."""\n'
        "    return a + b\n",
        encoding="utf-8",
    )
    origin.add(case.drift_file)
    origin.commit(f"feat: drift {case.drift_file}")

    fake = _FakeTransport()
    client = TestClient(
        create_app(
            InMemoryStore(),
            clock=lambda: _NOW,
            pr_transport_factory=lambda provider, url, token: fake,
        )
    )
    repo_id = _register(client, origin, branch=case.default_branch)

    resp = client.post(f"/repos/{repo_id}/docs-pr", json={})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["opened"] is True
    assert body["changed_paths"]  # at least the drifted doc was healed
    assert len(fake.plans) == 1


# --------------------------------------------------------------------------- #
# Store parity — clone-on-demand persists identically on memory AND SQL.
# --------------------------------------------------------------------------- #


@pytest.fixture(params=["memory", "sql"])
def store(request: pytest.FixtureRequest) -> Any:
    if request.param == "memory":
        return InMemoryStore()
    pytest.importorskip("sqlalchemy", reason="the [server] extra is not installed")
    from code_doc_monitor.server.db import SqlStore, create_all, engine_from_url

    engine = engine_from_url("sqlite:///:memory:")
    create_all(engine)
    return SqlStore(engine)


def test_clone_on_demand_demo_sync_is_store_parity(store: Any, tmp_path: Path) -> None:
    origin = repo_from_tree(_DEMO, tmp_path / "origin", history=_HISTORY)
    client = TestClient(create_app(store, clock=lambda: _NOW))
    repo_id = _register(client, origin, branch="main")

    assert (
        client.post(f"/repos/{repo_id}/sync", json={"mode": "local"}).status_code == 201
    )
    docs = client.get(
        f"/repos/{repo_id}/documents", params={"sync_kind": "local"}
    ).json()
    assert {d["document"]["doc_id"] for d in docs} == {
        "core-api",
        "getting-started",
        "readme",
        "io-api",
    }
    cov = client.get(f"/repos/{repo_id}/coverage").json()[-1]
    assert cov["percent_files"] == 80.0  # the demo's pinned coverage, off a real clone


# --------------------------------------------------------------------------- #
# git-MODE sync reads the default-branch baseline even from a feature branch.
# --------------------------------------------------------------------------- #


def test_git_mode_sync_reads_default_branch_over_authentic_history(
    tmp_path: Path,
) -> None:
    from code_doc_monitor.configsync import run_sync

    origin = repo_from_tree(_minimal_tree(tmp_path / "src"), tmp_path / "repo")
    main_tip = origin.head()

    # Move HEAD onto a feature branch that is 1 commit AHEAD of main.
    origin.checkout_new_branch("feature/extra")
    origin.commit_files(
        "feat: work in progress",
        {"pkg/wip.py": 'def wip():\n    """WIP."""\n    return 1\n'},
    )
    assert origin.commits_ahead("HEAD", "main") == 1

    # git mode materializes the DEFAULT branch in a throwaway worktree and reads
    # it — so the baseline ref is main's tip, NOT the feature-branch HEAD.
    result = run_sync(
        origin.path, "minimal", mode="git", default_branch="main", now=_NOW
    )
    assert result.run.ref == main_tip
    assert result.run.main_commit == main_tip
    assert result.run.commits_ahead == 1  # HEAD (feature) is ahead of main
    # The default-branch tree was healed before commit → no drift at the baseline.
    assert result.run.fully_synced is True


# --------------------------------------------------------------------------- #
# scripts/demo_as_git.py — materializes a repo the server can actually sync.
# --------------------------------------------------------------------------- #


def _load_demo_as_git() -> Any:
    """Import ``scripts/demo_as_git.py`` by path (it lives outside the package)."""
    import sys

    path = REPO_ROOT / "scripts" / "demo_as_git.py"
    spec = importlib.util.spec_from_file_location("demo_as_git", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_as_git"] = module
    spec.loader.exec_module(module)
    return module


def test_demo_as_git_materializes_a_syncable_repo(tmp_path: Path) -> None:
    """``materialize`` builds a real multi-commit git repo + bare origin the
    clone-on-demand server can sync — the demo's pinned 80% coverage off git."""
    demo_as_git = _load_demo_as_git()
    paths = demo_as_git.materialize(tmp_path / "out")

    assert paths["work"].is_dir() and (paths["origin"]).is_dir()
    # An authentic history (one commit per DEMO_HISTORY step that has files).
    work = GitRepo(path=paths["work"])
    assert work.commit_count() == len(demo_as_git.DEMO_HISTORY)

    client = TestClient(create_app(InMemoryStore(), clock=lambda: _NOW))
    payload = RegistrationPayload(
        repo=RepoIdentity(
            repo_id="demo-taskflow",
            provider="github",
            remote_url=f"file://{paths['origin']}",
            default_branch="main",
        ),
        default_branch="main",
    )
    assert (
        client.post("/repos", json=payload.model_dump(mode="json")).status_code == 201
    )
    resp = client.post("/repos/demo-taskflow/sync", json={"mode": "local"})
    assert resp.status_code == 201, resp.text

    docs = client.get(
        "/repos/demo-taskflow/documents", params={"sync_kind": "local"}
    ).json()
    assert {d["document"]["doc_id"] for d in docs} == {
        "core-api",
        "getting-started",
        "readme",
        "io-api",
    }
    cov = client.get("/repos/demo-taskflow/coverage").json()[-1]
    assert cov["percent_files"] == 80.0
    assert "src/taskflow/core/scheduler.py" in {
        f["path"] for f in cov["files"] if f["status"] == "undocumented"
    }
