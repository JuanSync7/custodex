"""Seed a live (or in-memory) central server with realistic demo data (T-04).

This is a small, committed launcher that makes the live instance on :33333 SHOW
the T-01 structured ticket and the T-02 config-driven coverage file list, so a
human can see the whole vertical working.

It is stdlib + ``code_doc_monitor`` only (no new dependency, K0) and is
DETERMINISTIC (K10: fixed timestamps, the mock backend, a frozen tmp fixture):

* :func:`build_seeded_store` registers a few demo repos and, for each, ingests
  several **ticketed** :class:`~code_doc_monitor.schema.ReviewRecord`\\s produced
  by running :class:`~code_doc_monitor.monitor.Monitor` over a tiny fixture repo
  with an injected clock (so each record carries a non-None ``ticket``). It also
  attaches a REAL coverage snapshot built from THIS repo's own
  ``resolve_coverage(load_config_dir("config/cdmon"))`` for one repo, so the dogfood
  file list renders. It is import-safe (no server launch, no network) so a test
  can call it directly.
* :func:`create_seeded_app` wraps that store in the FastAPI app (with the built
  dashboard SPA mounted when present), and :func:`main` launches uvicorn on
  ``0.0.0.0:33333`` serving it.

Run as a script (``python scripts/seed_demo.py``) to launch the seeded server;
import it (``from seed_demo import build_seeded_store``) to get the store alone.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from code_doc_monitor.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
    load_config_dir,
    resolve_repo_root,
)
from code_doc_monitor.configsync import SyncResult, run_sync
from code_doc_monitor.coverage import coverage_snapshot, resolve_coverage
from code_doc_monitor.drift import Drift, DriftKind
from code_doc_monitor.errors import CodeDocMonitorError
from code_doc_monitor.extract import DocumentSurface, build_document_surface
from code_doc_monitor.heal import regenerate_regions
from code_doc_monitor.inventory import discover_files, discover_symbols
from code_doc_monitor.monitor import Monitor
from code_doc_monitor.registry import RegistrationPayload
from code_doc_monitor.schema import ProposedFix, ReviewRecord, Verdict, new_record_id
from code_doc_monitor.server import InMemoryStore
from code_doc_monitor.sinks import RepoIdentity
from code_doc_monitor.ticket import build_ticket

# This repo's root (two levels up from scripts/seed_demo.py).
_REPO_ROOT = Path(__file__).resolve().parents[1]

# The self-contained adopter demo repo (CONFIG-V2 §6): registered live so the
# central dashboard's Sync button works against it on :33333.
_DEMO_DIR = _REPO_ROOT / "demo"
_DEMO_REPO_ID = "demo-taskflow"

# A fixed wall-clock so every seeded record/ticket id is reproducible (K10).
_NOW = "2026-06-01T00:00:00Z"

_DEMO_TOKEN = "demo-token"  # the per-repo bearer token every demo repo mints

# The REAL repos shown in the dashboard. The synthetic ``acme-*`` placeholders
# were removed — every row now maps to a real repo on disk. The dogfood
# ``code-doc-monitor`` row gets this repo's own real coverage snapshot attached;
# the self-contained adopter demo (``demo-taskflow``) is registered separately
# below (``_register_demo_taskflow``) with its ``local_path`` so its Sync button
# operates on the real ``demo/`` working tree.
_DEMO_REPOS: tuple[tuple[str, str, str], ...] = (
    ("code-doc-monitor", "code-doc-monitor", "This very repo (dogfood)"),
)

_DOCD_V1 = '''\
def compute(a, b):
    """Add two numbers."""
    return a + b


def render(value):
    """Render a value to text."""
    return str(value)
'''

_GAP_PY = '''\
def undocumented_api(x):
    """An unreferenced public surface (a coverage gap)."""
    return x
'''

_DOC_STUB = """\
# {title}

Prose written by a human.

<!-- CDM:BEGIN symbols -->
PLACEHOLDER
<!-- CDM:END symbols -->
"""


def _fixture_records(root: Path) -> list[ReviewRecord]:
    """Build a tiny repo under ``root``, drift it, and return ticketed records.

    Mirrors the e2e fixture: one eng-guide doc over ``documented.py`` plus an
    unreferenced ``gap.py``. The doc is healed to a clean baseline, then the
    public signature of ``compute`` moves so ``Monitor.run`` produces records
    each carrying a non-None structured ticket (T-01). The clock is injected so
    the run is deterministic (K10).
    """
    (root / "documented.py").write_text(_DOCD_V1, encoding="utf-8")
    (root / "gap.py").write_text(_GAP_PY, encoding="utf-8")
    (root / "docs").mkdir()
    eng = DocumentSpec(
        id="eng",
        path="docs/eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="documented.py"),),
        region_keys=("symbols",),
    )
    (root / eng.path).write_text(
        _DOC_STUB.format(title="Engineering guide"), encoding="utf-8"
    )
    cfg = MonitorConfig(documents=(eng,))
    regenerate_regions(root / eng.path, build_document_surface(eng, root))

    # Move the public signature so every audience drifts -> ticketed records.
    (root / "documented.py").write_text(
        _DOCD_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )
    result = Monitor(cfg, root, now=lambda: _NOW).run(apply=True)
    return list(result.records)


def _synth_record(
    *,
    surface: DocumentSurface,
    drift: Drift,
    verdict: Verdict,
    cause: str,
    fix: ProposedFix | None,
) -> ReviewRecord:
    """Synthesize one ticketed :class:`ReviewRecord` from a hand-built drift (K10).

    Used to demonstrate the ticket SEVERITY range the mock backend rarely emits
    in a single fixture run (an ESCALATE → HIGH, an INVALIDATE → LOW), so the
    dashboard shows every ticket shape + its distinct acceptance checklist.
    """
    surface_hash = surface.surface_hash()
    record_id = new_record_id(drift.doc_id, surface_hash, _NOW)
    ticket = build_ticket(
        drift=drift,
        verdict=verdict,
        cause=cause,
        fix=fix,
        surface=surface,
        ticket_id=f"CDM-{record_id}",
    )
    return ReviewRecord(
        record_id=record_id,
        doc_id=drift.doc_id,
        doc_path=drift.doc_path,
        audience=drift.audience,
        drift_kind=drift.kind.value,
        drift_detail=drift.detail,
        cause=cause,
        verdict=verdict,
        fix=fix,
        surface_hash=surface_hash,
        backend_kind="mock",
        detected_at=_NOW,
        resolved_at=_NOW,
        config_snapshot={"backend": "mock", "root": "."},
        ticket=ticket,
    )


def _varied_records(surface: DocumentSurface) -> list[ReviewRecord]:
    """Two extra ticketed records spanning the HIGH (escalate) + LOW (invalidate)
    severities, so the seeded board shows the full ticket range, not just MEDIUM."""
    escalate = _synth_record(
        surface=surface,
        drift=Drift(
            kind=DriftKind.UNHEALABLE,
            doc_id="eng",
            doc_path="docs/eng.md",
            detail=(
                "managed region 'design-notes' has no known renderer; cannot auto-heal"
            ),
            region_id="design-notes",
            healable=False,
            audience=Audience.ENG_GUIDE,
        ),
        verdict=Verdict.ESCALATE,
        cause=(
            "the mock backend cannot remediate this hand-written region "
            "automatically; a human reviewer is needed"
        ),
        fix=None,
    )
    invalidate = _synth_record(
        surface=surface,
        drift=Drift(
            kind=DriftKind.HASH,
            doc_id="guide",
            doc_path="docs/guide.md",
            detail="fingerprint moved due to a docstring-only change",
            healable=True,
            audience=Audience.USER_GUIDE,
        ),
        verdict=Verdict.INVALIDATE,
        cause=(
            "the change is to a docstring and does not affect this "
            "user-guide's public surface"
        ),
        fix=None,
    )
    return [escalate, invalidate]


def _fixture_snapshot(root: Path) -> dict:
    """A coverage snapshot over the tmp fixture (one documented + one gap file)."""
    eng = DocumentSpec(
        id="eng",
        path="docs/eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="documented.py"),),
        region_keys=("symbols",),
    )
    cfg = MonitorConfig(documents=(eng,))
    inv = discover_files(root)
    sym = discover_symbols(inv, root)
    snap = coverage_snapshot(resolve_coverage(cfg, sym))
    snap["captured_at"] = _NOW
    return snap


def _dogfood_sync() -> SyncResult | None:
    """ONE sync of THIS repo (dogfood), reused for BOTH its coverage snapshot AND
    its 12-document mapping — so the (filesystem-bound) work happens a SINGLE time
    at startup, not twice.

    Prefers **git** mode: it reads a CLEAN ``git worktree`` of tracked files, so it
    never walks the heavyweight UNTRACKED trees in the live checkout
    (``frontend/node_modules`` ~330MB, ``.venv/``) that a working-tree scan would
    traverse. Falls back to **local** mode when git is unavailable (e.g. a CI
    detached-HEAD checkout with no local ``main`` ref; there those untracked trees
    are typically absent, so the walk stays cheap). Returns the full
    :class:`~code_doc_monitor.configsync.SyncResult` (its ``coverage`` wire
    snapshot is already stamped ``captured_at = _NOW``), or ``None`` if the config
    is absent / both modes fail. Best-effort: never raises (seeding must not break
    the launch, K8/K10).
    """
    if not (_REPO_ROOT / "config" / "cdmon" / "index.yaml").is_file():
        return None
    for mode in ("git", "local"):
        try:
            return run_sync(
                _REPO_ROOT,
                "code-doc-monitor",
                mode=mode,
                default_branch="main",
                now=_NOW,
            )
        except CodeDocMonitorError:
            continue  # git unavailable (e.g. CI detached HEAD) → try local
    return None


# A drift induced on a THROWAWAY copy of the demo so the seeded board shows the
# demo's OWN detect→heal history (real records over core-api + getting-started),
# not just generic fixture records. Adding a public method to `Engine` moves the
# documented surface, so both docs that reference engine.py drift then heal.
_DEMO_DRIFT_ANCHOR = "    def run(self, runner: Runner) -> tuple[str, ...]:"
_DEMO_DRIFT_INSERT = '''\
    def reset(self) -> None:
        """Reset every task in the graph back to :attr:`Status.PENDING`."""
        for task in self.graph.tasks.values():
            task.status = Status.PENDING

    def run(self, runner: Runner) -> tuple[str, ...]:'''


def _demo_snapshot() -> dict | None:
    """A REAL coverage snapshot from the demo's own ``config/cdmon`` (M-03).

    Shows the demo's deliberate gap (``scheduler.py`` undocumented → ~80% file
    coverage) on the dashboard Coverage page. Best-effort: returns ``None`` if the
    demo config/scan is unavailable (seeding must never raise, K8/K10).
    """
    config_dir = _DEMO_DIR / "config" / "cdmon"
    if not (config_dir / "index.yaml").is_file():
        return None
    try:
        cfg = load_config_dir(config_dir)
        root = resolve_repo_root(config_dir, cfg.root)
        inv = discover_files(
            root, include=cfg.coverage.include, exclude=cfg.coverage.exclude
        )
        sym = discover_symbols(inv, root)
        snap = coverage_snapshot(resolve_coverage(cfg, sym))
    except Exception:  # noqa: BLE001 — seeding is best-effort; never break the launch
        return None
    snap["captured_at"] = _NOW
    return snap


def _demo_records() -> list[ReviewRecord]:
    """Real ticketed records from the demo's OWN docs (M-03).

    Copies the demo into a throwaway dir, induces one drift (a new public method
    on ``Engine``), and runs :class:`Monitor` over the demo's CONFIG-V2 layout so
    the heal produces records on ``core-api`` + ``getting-started`` — the demo's
    actual detect→heal loop, visible on the repo's drift timeline. Deterministic
    (injected ``now``) and best-effort (returns ``[]`` on any failure, K8/K10).
    """
    config_dir = _DEMO_DIR / "config" / "cdmon"
    if not (config_dir / "index.yaml").is_file():
        return []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "demo"
            shutil.copytree(_DEMO_DIR, copy)
            engine = copy / "src" / "taskflow" / "core" / "engine.py"
            text = engine.read_text(encoding="utf-8")
            if _DEMO_DRIFT_ANCHOR not in text:
                return []
            engine.write_text(
                text.replace(_DEMO_DRIFT_ANCHOR, _DEMO_DRIFT_INSERT, 1),
                encoding="utf-8",
            )
            copy_config = copy / "config" / "cdmon"
            cfg = load_config_dir(copy_config)
            result = Monitor(cfg, copy_config, now=lambda: _NOW).run(apply=True)
            return list(result.records)
    except Exception:  # noqa: BLE001 — seeding is best-effort; never break the launch
        return []


def _register_demo_taskflow(store: InMemoryStore) -> None:
    """Register + pre-sync the ``demo-taskflow`` adopter repo (CONFIG-V2 §6, M-02).

    Registers the demo OPEN (NO ``auth_token``) with its ``local_path`` set to
    ``<repo>/demo`` and ``default_branch="main"``, so the central dashboard's
    Sync button works against it token-less. Then runs ONE local
    :func:`run_sync` against the working tree (git mode would need the demo
    committed to ``main``) and persists the rows
    (``replace_config`` + ``add_sync_run``), so the Documents relationship view +
    sync-state are populated on first load. Deterministic (``_NOW``) and
    best-effort: a missing/unreadable demo never breaks the launch (K10/K8).
    """
    if not (_DEMO_DIR / "config" / "cdmon" / "index.yaml").is_file():
        return  # the demo content is absent — skip gracefully (import-safe).

    store.add_repo(
        RegistrationPayload(
            repo=RepoIdentity(
                repo_id=_DEMO_REPO_ID,
                repo_name="Taskflow (demo)",
                local_path=str(_DEMO_DIR),
                default_branch="main",
            ),
            description="Self-contained CONFIG-V2 adopter demo (taskflow)",
            # NO auth_token: the demo repo's sync/writes are OPEN.
        )
    )
    try:
        local = run_sync(
            _DEMO_DIR,
            _DEMO_REPO_ID,
            mode="local",
            default_branch="main",
            now=_NOW,
        )
    except CodeDocMonitorError:
        # Seeding is best-effort: never break the launch over a demo sync error.
        return
    store.replace_config(
        _DEMO_REPO_ID, "local", list(local.documents), list(local.code_refs)
    )
    store.add_sync_run(local.run)
    # Mirror the same config projection under the "git" partition too, so the
    # demo's documents (incl. the monitored README, FEAT-CONFIGV2-016) show on
    # BOTH default views: the Documents page (defaults to "git") and the Mapping
    # page (defaults to "local"). The demo isn't a git repo in the seed, so this
    # reuses the local projection (identical: documents/code_refs come from
    # config/cdmon, not the scan) re-stamped — no second sync. The repo's real
    # Sync button still performs a fresh sync on demand.
    store.replace_config(
        _DEMO_REPO_ID,
        "git",
        [d.model_copy(update={"sync_kind": "git"}) for d in local.documents],
        [c.model_copy(update={"sync_kind": "git"}) for c in local.code_refs],
    )
    store.add_sync_run(local.run.model_copy(update={"sync_kind": "git"}))

    # Make the repo's pages SHOW content on first click: the demo's own heal
    # records (drift timeline + tickets) and its real coverage snapshot (the
    # scheduler.py gap on the Coverage page). Both are best-effort (M-03).
    for rec in _demo_records():
        store.add_record(_DEMO_REPO_ID, rec)
    snapshot = _demo_snapshot()
    if snapshot is not None:
        store.add_coverage_snapshot(_DEMO_REPO_ID, _NOW, snapshot)


def build_seeded_store() -> InMemoryStore:
    """Build an :class:`InMemoryStore` populated with the demo data (import-safe).

    Deterministic (K10) and side-effect-free beyond a throwaway tempdir used to
    synthesize ticketed records. Registers every :data:`_DEMO_REPOS` entry with a
    bearer token, ingests the ticketed records for each, and attaches a coverage
    snapshot per repo — the dogfood repo gets THIS repo's real
    ``resolve_coverage`` snapshot when available, the rest a fixture snapshot.
    Finally registers the OPEN ``demo-taskflow`` adopter repo with its
    ``local_path`` and pre-syncs it locally so the dashboard shows its Documents
    relationship view + a token-less Sync button (M-02, CONFIG-V2 §6).
    """
    store = InMemoryStore()

    # Synthesize ticketed records + a fixture snapshot ONCE in a throwaway dir.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        records = _fixture_records(tmp_root)
        fixture_snapshot = _fixture_snapshot(tmp_root)
        # Add HIGH (escalate) + LOW (invalidate) tickets so the board shows the
        # full severity range alongside the MEDIUM fixes the run produced.
        eng = DocumentSpec(
            id="eng",
            path="docs/eng.md",
            audience=Audience.ENG_GUIDE,
            code_refs=(CodeRef(path="documented.py"),),
            region_keys=("symbols",),
        )
        records = records + _varied_records(build_document_surface(eng, tmp_root))

    # ONE dogfood sync, reused below for BOTH the coverage snapshot (in the loop)
    # and the document mapping — computed a single time, not twice (the sync is
    # filesystem-bound on a large repo, so doing it once matters at startup).
    dogfood = _dogfood_sync()
    dogfood_snapshot = dogfood.coverage if dogfood is not None else None

    for repo_id, repo_name, description in _DEMO_REPOS:
        # The dogfood repo IS this checkout: give it a local_path + default branch
        # so its dashboard Sync button actually works. Prefer "Sync (main)" (git
        # mode) — it reads a CLEAN `git worktree` of tracked files in ~1s; "Sync
        # (local)" walks the whole working tree (incl. .venv/, node_modules, caches)
        # and is far slower, so the browser fetch can time out on a big repo.
        local_path = str(_REPO_ROOT) if repo_id == "code-doc-monitor" else None
        identity = RepoIdentity(
            repo_id=repo_id,
            repo_name=repo_name,
            local_path=local_path,
            default_branch="main",
        )
        store.add_repo(
            RegistrationPayload(
                repo=identity,
                description=description,
                auth_token=_DEMO_TOKEN,
                default_branch="main",
            )
        )
        for rec in records:
            store.add_record(repo_id, rec)
        is_dogfood = repo_id == "code-doc-monitor" and dogfood_snapshot is not None
        snapshot = dogfood_snapshot if is_dogfood else fixture_snapshot
        store.add_coverage_snapshot(repo_id, _NOW, snapshot)

    # The CONFIG-V2 adopter demo: registered OPEN with its local_path + pre-synced
    # so the dashboard shows its Documents view + a working Sync button (M-02).
    _register_demo_taskflow(store)
    # The dogfood repo's full document mapping (incl. the monitored README,
    # FEAT-CONFIGV2-016). It is synced ONCE (git preferred — it reads a clean
    # worktree, avoiding a working-tree walk of node_modules/.venv), then MIRRORED
    # under the OTHER Source partition so the README + every doc shows on BOTH
    # default views with no second sync: the Documents page (defaults to "git")
    # and the Mapping page (defaults to "local"). The mirror reuses the identical
    # config projection (documents/code_refs come from config/cdmon, not the
    # filesystem scan, so they are the same in either mode), re-stamped only with
    # the partition's sync_kind/ref.
    if dogfood is not None:
        store.replace_config(
            "code-doc-monitor",
            dogfood.run.sync_kind,
            list(dogfood.documents),
            list(dogfood.code_refs),
        )
        store.add_sync_run(dogfood.run)
        mirror = "local" if dogfood.run.sync_kind != "local" else "git"
        mirror_ref = "local" if mirror == "local" else dogfood.run.ref
        store.replace_config(
            "code-doc-monitor",
            mirror,
            [
                d.model_copy(update={"sync_kind": mirror, "ref": mirror_ref})
                for d in dogfood.documents
            ],
            [c.model_copy(update={"sync_kind": mirror}) for c in dogfood.code_refs],
        )
        store.add_sync_run(
            dogfood.run.model_copy(update={"sync_kind": mirror, "ref": mirror_ref})
        )

    return store


def _default_static_dir() -> Path | None:
    """Re-export the package's built-SPA locator so the launch matches prod."""
    from code_doc_monitor.server.app import _default_static_dir as locator

    return locator()


def create_seeded_app() -> object:
    """The FastAPI app over a freshly seeded store, with the SPA mounted if built."""
    from code_doc_monitor.server import create_app

    return create_app(build_seeded_store(), static_dir=_default_static_dir())


def main() -> None:  # pragma: no cover — the real uvicorn launch leaf (K4)
    import uvicorn

    uvicorn.run(create_seeded_app(), host="0.0.0.0", port=33333)


if __name__ == "__main__":  # pragma: no cover — server launch entrypoint
    main()
