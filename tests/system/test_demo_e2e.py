"""M-02 — the demo end-to-end through BOTH the central + standalone apps (offline).

The demo (`demo/`, CONFIG-V2 §6) must be live and functional in every surface:

* **central** — over the SEEDED app (:func:`scripts.seed_demo.build_seeded_store`):
  ``demo-taskflow`` is listed; its Documents relationship tree matches
  ``demo/config/cdmon``; a token-less ``POST /sync {local}`` succeeds + reports
  counts; ``GET /sync-state`` returns the run.
* **standalone** — over :func:`build_standalone_app` pointed at ``demo/``: one
  repo, the same documents tree, a token-less sync, ``GET /`` 200.
* **git-mode (committed fixture)** — a SEPARATE temp git repo that copies the demo
  into a SUBDIR + commits it on ``main``: ``run_sync(mode="git")`` reads the
  default branch correctly through configsync's NEW subdir-awareness, and leaves
  no stray worktree behind (K1).
* **demo CLI smoke** — from ``demo/``, ``cdmon check`` exits 0 and ``cdmon rpt``
  re-renders byte-identical to the committed ``coverage.rpt`` (idempotent, K7),
  with the per-unit waiver fix in place (per-unit ``percent: 100.00``).

Everything is offline + deterministic (an injected ``now``, K10) and asserts
behavior, not line counts.

Features: FEAT-CLI-003, FEAT-CLI-005, FEAT-CONFIG-003, FEAT-CONFIGV2-001
Features: FEAT-CONFIGV2-003, FEAT-CONFIGV2-006, FEAT-CONFIGV2-008
Features: FEAT-CONFIGV2-012, FEAT-QUALITY-001, FEAT-QUALITY-005, FEAT-QUALITY-007
Features: FEAT-SERVER-001, FEAT-SERVER-008, FEAT-SERVER-009, FEAT-SERVER-010
Features: FEAT-SERVER-014, FEAT-SERVER-015
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo import REPO_ROOT

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")

from fastapi.testclient import TestClient  # noqa: E402

from code_doc_monitor.config import load_bundle  # noqa: E402
from code_doc_monitor.configsync import run_sync  # noqa: E402
from code_doc_monitor.report import (  # noqa: E402
    build_coverage_rpt,
    parse_rpt,
    render_rpt,
)
from code_doc_monitor.server.standalone import build_standalone_app  # noqa: E402

_NOW = "2026-06-07T00:00:00Z"

# The repo root (two up from tests/) + the committed demo content.
_REPO_ROOT = REPO_ROOT
_DEMO_DIR = _REPO_ROOT / "demo"

# The eleven code refs the demo's documents reference, in load order (index units
# order, then in-file documents order): core.yaml carries core-api, then the
# user-guide getting-started (symbol-selective refs over the same two core
# files), then the user-guide README (a narrative tracked against model.py,
# FEAT-CONFIGV2-016); io.yaml carries io-api; finally tests.yaml carries the four
# test-docs (FEAT-CONFIGV2-017), one per demo test file (the test→test-doc mirror).
_DEMO_CODE_REFS = (
    "src/taskflow/core/model.py",
    "src/taskflow/core/engine.py",
    "src/taskflow/core/model.py",
    "src/taskflow/core/engine.py",
    "src/taskflow/core/model.py",
    "src/taskflow/io/storage.py",
    "src/taskflow/io/report.py",
    "tests/test_engine.py",
    "tests/test_io.py",
    "tests/test_model.py",
    "tests/test_scheduler.py",
)
_DEMO_DOC_IDS = (
    "core-api",
    "getting-started",
    "readme",
    "io-api",
    "test-engine",
    "test-io",
    "test-model",
    "test-scheduler",
)


# Make scripts/seed_demo importable (it lives outside the package, like the
# launcher does at runtime) — mirrors how seed_demo is consumed in production.
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from seed_demo import build_seeded_store  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True
    )
    return out.stdout


def _no_worktrees(repo: Path) -> None:
    """Assert the repo has exactly its main working tree — no leaked worktrees."""
    listed = _git(repo, "worktree", "list").strip().splitlines()
    assert len(listed) == 1, f"leftover worktrees: {listed!r}"


# --------------------------------------------------------------------------- #
# central — the seeded app lists demo-taskflow + serves its documents + sync.
# --------------------------------------------------------------------------- #


def test_central_seeded_app_lists_demo_taskflow() -> None:
    app = _seeded_app()
    with TestClient(app) as client:
        repos = client.get("/repos").json()
    ids = [r["repo"]["repo_id"] for r in repos]
    assert "demo-taskflow" in ids


def test_central_documents_tree_matches_demo_config() -> None:
    app = _seeded_app()
    with TestClient(app) as client:
        trees = client.get(
            "/repos/demo-taskflow/documents", params={"sync_kind": "local"}
        ).json()
    assert [t["document"]["doc_id"] for t in trees] == list(_DEMO_DOC_IDS)
    # The doc→code_refs relationship tree matches demo/config/cdmon's units.
    refs = tuple(c["path"] for t in trees for c in t["code_refs"])
    assert refs == _DEMO_CODE_REFS
    # Units are attributed.
    by_id = {t["document"]["doc_id"]: t for t in trees}
    assert by_id["core-api"]["document"]["unit"] == "core"
    assert by_id["getting-started"]["document"]["unit"] == "core"
    assert by_id["io-api"]["document"]["unit"] == "io"


def test_central_token_less_local_sync_succeeds_with_counts() -> None:
    app = _seeded_app()
    with TestClient(app) as client:
        # No Authorization header: the demo repo is registered OPEN.
        resp = client.post("/repos/demo-taskflow/sync", json={"mode": "local"})
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["sync_kind"] == "local"
    # The undocumented scheduler.py is a COVERAGE gap, NOT drift, so the demo has
    # NO drift. (Assert drift-clean rather than ``fully_synced``: for a LOCAL sync
    # ``fully_synced`` also requires ``commits_ahead == 0``, which only holds when
    # the OUTER repo is on its default branch — so it is branch-fragile in CI/dev,
    # whereas "the demo has no drift" is the real invariant under test.)
    assert run["drift"]["ok"] is True
    assert run["drift"]["drift_count"] == 0
    assert run["document_count"] == 8
    assert run["code_ref_count"] == 11


def test_central_sync_state_returns_the_run() -> None:
    app = _seeded_app()
    with TestClient(app) as client:
        state = client.get(
            "/repos/demo-taskflow/sync-state", params={"sync_kind": "local"}
        ).json()
    assert state is not None
    assert state["sync_kind"] == "local"
    assert state["document_count"] == 8


def test_central_seeded_demo_has_records_and_coverage() -> None:
    """M-03: clicking demo-taskflow must SHOW content — the seed gives it its own
    heal records (drift timeline) AND a real coverage snapshot with the gap."""
    app = _seeded_app()
    with TestClient(app) as client:
        records = client.get("/repos/demo-taskflow/records").json()
        coverage = client.get("/repos/demo-taskflow/coverage").json()
    # Real heal records over the demo's OWN docs (not the generic fixture docs).
    assert records, "demo-taskflow should have seeded heal records"
    assert {r["doc_id"] for r in records} <= {"core-api", "getting-started"}
    assert all(r["verdict"] == "FIX" for r in records)
    # A coverage snapshot showing the deliberate scheduler.py gap (~88.9% files now
    # that the test→test-doc mirror adds the fully-documented `tests` unit).
    assert coverage, "demo-taskflow should have a seeded coverage snapshot"
    latest = coverage[-1]
    assert latest["percent_files"] == pytest.approx(88.88888888888889)
    undocumented = [f["path"] for f in latest["files"] if f["status"] == "undocumented"]
    assert "src/taskflow/core/scheduler.py" in undocumented


# --------------------------------------------------------------------------- #
# standalone — build_standalone_app(<repo>/demo) serves the same one repo.
# --------------------------------------------------------------------------- #


def test_standalone_demo_app_one_repo_and_documents() -> None:
    app = build_standalone_app(_DEMO_DIR, now=_NOW)
    with TestClient(app) as client:
        repos = client.get("/repos").json()
        assert [r["repo"]["repo_id"] for r in repos] == ["demo-taskflow"]
        trees = client.get(
            "/repos/demo-taskflow/documents", params={"sync_kind": "local"}
        ).json()
    assert [t["document"]["doc_id"] for t in trees] == list(_DEMO_DOC_IDS)
    refs = tuple(c["path"] for t in trees for c in t["code_refs"])
    assert refs == _DEMO_CODE_REFS


def test_demo_getting_started_loads_context_refs() -> None:
    """EDITOR E-12: the demo's `getting-started` doc carries its `context_refs`
    (generation glance-through references) via `load_bundle` — additive (K6),
    distinct from its code_refs, and present in the loaded model."""
    bundle = load_bundle(_DEMO_DIR / "config" / "cdmon")
    spec = next(d for d in bundle.config.documents if d.id == "getting-started")
    refs = {(r.path, r.note) for r in spec.context_refs}
    assert refs == {
        ("docs/api/core-api.md", "the full engine reference"),
        ("src/taskflow/core/engine.py", "scheduling semantics referenced in the tour"),
    }
    # context_refs are NOT code_refs (the documented surface stays symbol-selective).
    assert {r.path for r in spec.code_refs} == {
        "src/taskflow/core/model.py",
        "src/taskflow/core/engine.py",
    }


def test_standalone_editable_tree_shows_context_refs_and_unlinked_scheduler() -> None:
    """EDITOR E-12: the editable tree (the Mapping page read) shows
    `getting-started.context_refs` populated AND `scheduler.py` under
    `undocumented_files` — the unlinked file you link → generate on the page."""
    app = build_standalone_app(_DEMO_DIR, now=_NOW)
    with TestClient(app) as client:
        tree = client.get(
            "/repos/demo-taskflow/config/editable",
            params={"sync_kind": "local"},
        ).json()
    by_id = {d["document"]["doc_id"]: d for d in tree["documents"]}
    gs = by_id["getting-started"]["document"]
    crefs = {(c["path"], c["note"]) for c in gs["context_refs"]}
    assert crefs == {
        ("docs/api/core-api.md", "the full engine reference"),
        ("src/taskflow/core/engine.py", "scheduling semantics referenced in the tour"),
    }
    # The deliberately-unlinked scheduler.py is the live link→generate target.
    assert "src/taskflow/core/scheduler.py" in tree["undocumented_files"]
    # context_refs are additive: the existing doc tree is unaffected.
    assert list(by_id) == list(_DEMO_DOC_IDS)


def test_standalone_demo_token_less_sync_and_root() -> None:
    app = build_standalone_app(_DEMO_DIR, now=_NOW)
    with TestClient(app) as client:
        resp = client.post("/repos/demo-taskflow/sync", json={"mode": "local"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["sync_kind"] == "local"
        root = client.get("/")
    assert root.status_code == 200


# --------------------------------------------------------------------------- #
# git-mode — a committed fixture whose config/cdmon is in a SUBDIR (M-02 #1).
# --------------------------------------------------------------------------- #


def _commit_demo_in_subdir(tmp_path: Path) -> tuple[Path, Path]:
    """Copy the demo into ``<repo>/demo`` of a fresh git repo, commit on ``main``.

    The config thus lives TWO levels under the git toplevel
    (``demo/config/cdmon``) — exactly the subdir layout configsync must handle.
    Returns ``(toplevel, demo_subdir)``.
    """
    top = tmp_path / "outer"
    top.mkdir()
    sub = top / "demo"
    shutil.copytree(_DEMO_DIR, sub)
    _git(top, "init", "-q")
    _git(top, "config", "user.email", "test@example.invalid")
    _git(top, "config", "user.name", "tester")
    _git(top, "add", "-A")
    _git(top, "commit", "-q", "-m", "init")
    _git(top, "branch", "-M", "main")
    return top, sub


def test_git_mode_reads_config_in_subdir(tmp_path: Path) -> None:
    top, sub = _commit_demo_in_subdir(tmp_path)
    result = run_sync(sub, "demo-taskflow", mode="git", default_branch="main", now=_NOW)
    run = result.run
    assert run.sync_kind == "git"
    assert run.document_count == 8
    assert run.code_ref_count == 11
    assert run.commits_ahead == 0
    # The committed demo docs are healed in-sync, so main is fully synced.
    assert run.fully_synced is True
    assert [r.path for r in result.code_refs] == list(_DEMO_CODE_REFS)
    _no_worktrees(top)


def test_git_mode_subdir_leaves_no_worktree(tmp_path: Path) -> None:
    top, sub = _commit_demo_in_subdir(tmp_path)
    run_sync(sub, "demo-taskflow", mode="git", default_branch="main", now=_NOW)
    run_sync(sub, "demo-taskflow", mode="git", default_branch="main", now=_NOW)
    _no_worktrees(top)


def test_git_mode_uncommitted_subdir_is_loud(tmp_path: Path) -> None:
    """A repo whose default branch lacks <rel>/config/cdmon raises a loud SyncError."""
    from code_doc_monitor.errors import SyncError

    top = tmp_path / "outer"
    top.mkdir()
    (top / "readme.md").write_text("hi\n", encoding="utf-8")
    _git(top, "init", "-q")
    _git(top, "config", "user.email", "test@example.invalid")
    _git(top, "config", "user.name", "tester")
    _git(top, "add", "-A")
    _git(top, "commit", "-q", "-m", "init")
    _git(top, "branch", "-M", "main")
    # The demo subdir exists in the WORKING TREE but is not committed to main.
    sub = top / "demo"
    shutil.copytree(_DEMO_DIR, sub)
    with pytest.raises(SyncError, match="config/cdmon"):
        run_sync(sub, "demo-taskflow", mode="git", default_branch="main", now=_NOW)
    _no_worktrees(top)


# --------------------------------------------------------------------------- #
# coverage-on-sync — a sync carries + persists a coverage snapshot of the synced
# tree, so adding a file + syncing surfaces it on the Coverage page (no separate
# POST /coverage ingest needed).
# --------------------------------------------------------------------------- #


def test_local_sync_carries_a_coverage_snapshot(tmp_path: Path) -> None:
    """run_sync's result carries the coverage snapshot of the synced tree (the same
    wire shape the Coverage page reads), stamped with the injected clock (K10), so
    a sync can refresh coverage without a separate POST /coverage ingest."""
    _top, sub = _commit_demo_in_subdir(tmp_path)
    result = run_sync(
        sub, "demo-taskflow", mode="local", default_branch="main", now=_NOW
    )
    snap = result.coverage
    assert snap is not None
    assert snap["captured_at"] == _NOW
    files = {f["path"]: f["status"] for f in snap["files"]}
    # The demo's deliberate gap is visible in the synced snapshot.
    assert files["src/taskflow/core/scheduler.py"] == "undocumented"
    assert files["src/taskflow/core/engine.py"] == "documented"


def test_sync_route_refreshes_coverage_when_a_file_is_added(tmp_path: Path) -> None:
    """POST /sync persists a coverage snapshot of the just-synced tree: dropping a
    new undocumented source file and re-syncing surfaces it on GET /coverage (the
    dashboard Coverage page), with the file percentage dropping."""
    from code_doc_monitor.registry import RegistrationPayload
    from code_doc_monitor.server import InMemoryStore, create_app
    from code_doc_monitor.sinks import RepoIdentity

    _top, sub = _commit_demo_in_subdir(tmp_path)
    store = InMemoryStore()
    store.add_repo(
        RegistrationPayload(
            repo=RepoIdentity(
                repo_id="demo-taskflow",
                repo_name="Taskflow (demo)",
                local_path=str(sub),
                default_branch="main",
            )
        )
    )
    with TestClient(create_app(store)) as client:
        first = client.post("/repos/demo-taskflow/sync", json={"mode": "local"})
        assert first.status_code == 201, first.text
        before = client.get("/repos/demo-taskflow/coverage").json()
        assert len(before) == 1, "the sync should have captured a coverage snapshot"
        pct_before = before[-1]["percent_files"]

        # Drop a brand-new undocumented source file into a covered dir.
        (sub / "src" / "taskflow" / "core" / "extra.py").write_text(
            'def extra():\n    """A newly added public function."""\n    return 1\n',
            encoding="utf-8",
        )
        second = client.post("/repos/demo-taskflow/sync", json={"mode": "local"})
        assert second.status_code == 201, second.text
        after = client.get("/repos/demo-taskflow/coverage").json()
        assert len(after) == 2, "the second sync should append a fresh snapshot"
        files = {f["path"]: f["status"] for f in after[-1]["files"]}
        assert files["src/taskflow/core/extra.py"] == "undocumented"  # NEW file shows
        assert after[-1]["percent_files"] < pct_before  # the gap drags coverage down


# --------------------------------------------------------------------------- #
# demo CLI smoke — `cdmon check` exit 0; `cdmon rpt` matches committed report.
# --------------------------------------------------------------------------- #


def test_demo_cli_check_exit_zero() -> None:
    from typer.testing import CliRunner

    from code_doc_monitor.cli import app

    result = CliRunner().invoke(
        app, ["check", "--config", str(_DEMO_DIR / "config" / "cdmon")]
    )
    assert result.exit_code == 0, result.output


def test_demo_doc_style_exercises_all_four_categories() -> None:
    """The user-guide doc maps every template CATEGORY to a non-default value, so
    all four categories (document-type/tone/writing-style/vocabulary) are
    exercised somewhere in the demo, not just api-reference/precise/etc."""
    from code_doc_monitor.docstyle import load_doc_style

    cfg = _DEMO_DIR / "config" / "cdmon"
    style = load_doc_style(
        cfg / "doc-style.yaml", templates_root=_DEMO_DIR / "templates" / "writing"
    )

    sel = style.style_for("getting-started")
    assert sel.document_type == "tutorial"
    assert sel.tone == "friendly"
    assert sel.writing_style == "narrative"
    assert sel.vocabulary == "general"

    # Every category value the user-guide picks differs from the defaults, so the
    # demo now uses a non-default value in all four categories.
    defaults = style.defaults
    assert sel.document_type != defaults.document_type
    assert sel.tone != defaults.tone
    assert sel.writing_style != defaults.writing_style
    assert sel.vocabulary != defaults.vocabulary


def test_demo_rpt_matches_committed_coverage_report() -> None:
    """Re-rendering the demo report equals the committed file (idempotent, K7) and
    reports the real coverage gap: scheduler.py is undocumented under `core`."""
    cfg = _DEMO_DIR / "config" / "cdmon"
    committed = parse_rpt((cfg / "coverage.rpt").read_text(encoding="utf-8"))

    bundle = load_bundle(cfg)
    from code_doc_monitor.report import report_repo_root

    repo_root = report_repo_root(cfg, bundle)
    rebuilt = build_coverage_rpt(bundle, repo_root, ref=None)

    # The rebuilt report renders byte-identical to the committed file.
    assert render_rpt(rebuilt) == (cfg / "coverage.rpt").read_text(encoding="utf-8")

    # Overall coverage now reflects the one real gap across source + tests: 8 of 9
    # eligible files documented (the 3 __init__.py are waived out of the
    # denominator) = 88.89% (rounded in the .rpt summary).
    assert committed.summary.percent == 88.89
    by_unit = {u.unit: u for u in committed.units}
    # The `core` unit carries the gap (scheduler.py): 2 of 3 documented = 66.67.
    assert by_unit["core"].percent == 66.67
    assert "src/taskflow/core/scheduler.py" in by_unit["core"].uncovered
    # The `io` unit is fully documented; so is the `tests` unit — the test→test-doc
    # mirror (FEAT-CONFIGV2-017) maps every demo test file to a test-doc 1:1.
    assert by_unit["io"].percent == 100.0
    assert by_unit["tests"].percent == 100.0

    # scheduler.py surfaces as undocumented with `core` as its suggested unit.
    gaps = {g.path: g for g in committed.undocumented}
    assert "src/taskflow/core/scheduler.py" in gaps
    assert gaps["src/taskflow/core/scheduler.py"].suggested_unit == "core.yaml"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _seeded_app() -> object:
    """The central app over a freshly seeded store (no SPA mount needed here)."""
    from code_doc_monitor.server import create_app

    return create_app(build_seeded_store())


def test_central_ownership_view_shows_departed_dri_orphan() -> None:
    """OWN-06: the seeded Ownership view flags core-api as a DRI-vacant orphan.

    The seed marks `dana` (core-api's DRI) departed while `demo-team` (the durable
    owner) stays active, so GET /ownership reports a SOFT orphan that a reassignment
    clears. The dogfood repo's docs (owned by the active `cdmon-team`) are clean.

    Features: FEAT-OWNERSHIP-009
    """
    app = _seeded_app()
    with TestClient(app) as client:
        roster = {i["name"]: i["active"] for i in client.get("/roster").json()}
        body = client.get("/repos/demo-taskflow/ownership").json()
        dogfood = client.get("/repos/code-doc-monitor/ownership").json()
    assert roster["dana"] is False and roster["demo-team"] is True
    owners = {o["doc_id"]: o["accountable"] for o in body["owners"]}
    assert owners["core-api"] == "dana"  # core-api's DRI
    assert body["orphan_count"] == 1
    statuses = {f["doc_id"]: f["status"] for f in body["findings"]}
    assert statuses["core-api"] == "orphan_dri_vacant"
    assert dogfood["orphan_count"] == 0  # cdmon-team is active


def test_central_staleness_view_flags_overdue_doc() -> None:
    """SLA-05: the seeded /staleness view flags core-api (reviewed long ago) as STALE
    while a recently-reviewed user-guide (getting-started) is FRESH — graded at READ
    time against an injected clock for determinism.

    Features: FEAT-STALENESS-006
    """
    from code_doc_monitor.server import create_app

    app = create_app(build_seeded_store(), clock=lambda: "2026-06-22T00:00:00Z")
    with TestClient(app) as client:
        body = client.get("/repos/demo-taskflow/staleness").json()
        full = client.get("/repos/demo-taskflow/staleness?include_fresh=true").json()
    statuses = {f["doc_id"]: f["status"] for f in body["findings"]}
    assert statuses["core-api"] == "stale"  # reviewed 2024-06-01, past the 90-day SLA
    assert "getting-started" not in statuses  # fresh → omitted from the default view
    assert body["stale_count"] >= 1
    # include_fresh surfaces the fresh user-guide too
    full_statuses = {f["doc_id"]: f["status"] for f in full["findings"]}
    assert full_statuses["getting-started"] == "fresh"
