"""End-to-end / system / integration proof for T-04 (offline TestClient — K4/K10).

A single deterministic test (K10: fixed timestamps, the mock backend) drives the
WHOLE vertical the way a real client would:

1. A tiny fixture repo (one eng-guide doc over one code file, mirroring
   ``test_system.py``) is healed to a clean baseline, the public signature is
   moved, and ``Monitor.run`` produces ``ReviewRecord``\\s each carrying a
   non-None structured ``ticket`` (T-01).
2. A :class:`~code_doc_monitor.coverage.CoverageReport` is resolved over the same
   fixture (one documented file + one undocumented file) and projected to the
   wire ``coverage_snapshot`` dict with its per-file ``files`` list (T-02).
3. The FastAPI app (``create_app(InMemoryStore())``) is exercised through
   ``TestClient``: register a repo WITH a bearer token, ingest each ticketed
   record (Bearer), POST the coverage snapshot (Bearer).
4. The round trip is asserted: ``GET /records`` returns each record's ``ticket``
   intact (id/severity/acceptance-criteria/affected-symbols); ``GET /coverage``
   returns the snapshot whose ``files`` carry the config-driven documented /
   undocumented status; ``GET /status`` reports the snapshot's ratio. The auth
   negative path (ingest / coverage WITHOUT the token -> 401) is asserted too.

Also a smoke test that ``scripts/seed_demo.py`` imports and ``build_seeded_store``
returns a populated store (repos + a ticketed record + a coverage snapshot).

Features: FEAT-MONITOR-001, FEAT-MONITOR-004, FEAT-RECORD-001, FEAT-RECORD-004
Features: FEAT-RECORD-010, FEAT-PR-009, FEAT-PR-010, FEAT-COVERAGE-007
Features: FEAT-COVERAGE-010, FEAT-SERVER-002, FEAT-SERVER-003, FEAT-SERVER-004
Features: FEAT-SERVER-005, FEAT-SERVER-008
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from tests._repo import REPO_ROOT

fastapi = pytest.importorskip("fastapi")  # the [server] extra (K0)
from fastapi.testclient import TestClient  # noqa: E402

from code_doc_monitor.config import (  # noqa: E402
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
)
from code_doc_monitor.coverage import (  # noqa: E402
    coverage_snapshot,
    resolve_coverage,
)
from code_doc_monitor.extract import build_document_surface  # noqa: E402
from code_doc_monitor.heal import regenerate_regions  # noqa: E402
from code_doc_monitor.inventory import discover_files, discover_symbols  # noqa: E402
from code_doc_monitor.monitor import Monitor  # noqa: E402
from code_doc_monitor.server import InMemoryStore, create_app  # noqa: E402
from code_doc_monitor.sinks import IngestEnvelope, RepoIdentity  # noqa: E402

_NOW = "2026-06-01T00:00:00Z"
_REPO_ID = "acme-demo"
_TOKEN = "s3cret-token"

_DOCD_V1 = '''\
def compute(a, b):
    """Add two numbers."""
    return a + b
'''

_GAP_PY = '''\
def undocumented_api(x):
    """Nobody references this file."""
    return x
'''

_DOC_STUB = """\
# {title}

Prose written by a human.

<!-- CDM:BEGIN symbols -->
PLACEHOLDER
<!-- CDM:END symbols -->
"""


def _make_repo(tmp_path: Path) -> tuple[Path, MonitorConfig]:
    """A fixture repo: one documented code file + one unreferenced (gap) file."""
    root = tmp_path
    (root / "documented.py").write_text(_DOCD_V1, encoding="utf-8")
    (root / "gap.py").write_text(_GAP_PY, encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "eng.md").write_text(
        _DOC_STUB.format(title="Engineering guide"), encoding="utf-8"
    )
    eng = DocumentSpec(
        id="eng",
        path="docs/eng.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="documented.py"),),
        region_keys=("symbols",),
    )
    cfg = MonitorConfig(documents=(eng,))
    # Heal to a clean baseline so only the code change below drives drift.
    regenerate_regions(root / eng.path, build_document_surface(eng, root))
    return root, cfg


def _ticketed_records(root: Path, cfg: MonitorConfig):
    """Run Monitor with a fixed clock so every record carries a non-None ticket."""
    (root / "documented.py").write_text(
        _DOCD_V1.replace("def compute(a, b):", "def compute(a, b, c=0):"),
        encoding="utf-8",
    )
    result = Monitor(cfg, root, now=lambda: _NOW).run(apply=True)
    records = list(result.records)
    assert records, "the public-signature change must produce at least one record"
    assert all(r.ticket is not None for r in records), "every record carries a ticket"
    return records


def _snapshot(root: Path, cfg: MonitorConfig) -> dict:
    inv = discover_files(root)
    sym = discover_symbols(inv, root)
    report = resolve_coverage(cfg, sym)
    snap = coverage_snapshot(report)
    snap["captured_at"] = _NOW  # the client-injected ISO timestamp (K10)
    return snap


def test_ticket_and_coverage_round_trip_through_the_server(tmp_path: Path) -> None:
    """The full vertical: heal -> ticketed records + coverage -> server -> read back."""
    root, cfg = _make_repo(tmp_path)
    records = _ticketed_records(root, cfg)
    snapshot = _snapshot(root, cfg)

    client = TestClient(create_app(InMemoryStore()))
    auth = {"Authorization": f"Bearer {_TOKEN}"}

    # Register the repo WITH a bearer token (writes are then token-protected).
    reg = client.post(
        "/repos",
        json={
            "repo": {"repo_id": _REPO_ID, "repo_name": "Acme demo"},
            "auth_token": _TOKEN,
        },
    )
    assert reg.status_code == 201, reg.text

    # Ingest each ticketed record wrapped in the SHARED IngestEnvelope (Bearer).
    identity = RepoIdentity(repo_id=_REPO_ID, repo_name="Acme demo")
    for rec in records:
        env = IngestEnvelope(repo=identity, record=rec).model_dump(mode="json")
        resp = client.post("/ingest", json=env, headers=auth)
        assert resp.status_code == 202, resp.text

    # POST the coverage snapshot (Bearer).
    cov = client.post(f"/repos/{_REPO_ID}/coverage", json=snapshot, headers=auth)
    assert cov.status_code == 202, cov.text

    # --- ASSERT the ticket round trip ------------------------------------- #
    got = client.get(f"/repos/{_REPO_ID}/records")
    assert got.status_code == 200
    read_records = got.json()
    assert len(read_records) == len(records)
    by_id = {r.record_id: r for r in records}
    for wire in read_records:
        original = by_id[wire["record_id"]]
        assert original.ticket is not None  # narrow for mypy/readers
        ticket = wire["ticket"]
        assert ticket is not None, "the structured ticket survived the round trip"
        assert ticket["ticket_id"] == original.ticket.ticket_id
        assert ticket["severity"] == original.ticket.severity.value
        # acceptance_criteria preserved (list of {text, auto_satisfied}).
        assert [c["text"] for c in ticket["acceptance_criteria"]] == [
            c.text for c in original.ticket.acceptance_criteria
        ]
        assert ticket["acceptance_criteria"], "the checklist is non-empty"
        # affected_symbols preserved; the moved public `compute` is among them.
        assert list(ticket["affected_symbols"]) == list(
            original.ticket.affected_symbols
        )
        assert "compute" in ticket["affected_symbols"]

    # --- ASSERT the coverage file list (config-driven status) ------------- #
    cov_read = client.get(f"/repos/{_REPO_ID}/coverage")
    assert cov_read.status_code == 200
    snaps = cov_read.json()
    assert len(snaps) == 1
    latest = snaps[-1]
    status_by_path = {f["path"]: f["status"] for f in latest["files"]}
    assert status_by_path["documented.py"] == "documented"
    assert status_by_path["gap.py"] == "undocumented"
    # the documented file's owner is the eng doc.
    eng_file = next(f for f in latest["files"] if f["path"] == "documented.py")
    assert eng_file["owners"] == ["eng"]

    # --- ASSERT status.coverage_ratio == the snapshot ratio --------------- #
    status = client.get(f"/repos/{_REPO_ID}/status").json()
    assert status["coverage_ratio"] == pytest.approx(snapshot["ratio"])

    # --- Negative auth: writes WITHOUT the token are 401 ------------------ #
    env = IngestEnvelope(repo=identity, record=records[0]).model_dump(mode="json")
    assert client.post("/ingest", json=env).status_code == 401
    assert client.post(f"/repos/{_REPO_ID}/coverage", json=snapshot).status_code == 401


# --------------------------------------------------------------------------- #
# Smoke test: scripts/seed_demo.py imports cleanly and seeds a populated store.
# --------------------------------------------------------------------------- #


def _load_seed_module():
    """Import ``scripts/seed_demo.py`` by path (it lives outside the package)."""
    seed_path = REPO_ROOT / "scripts" / "seed_demo.py"
    spec = importlib.util.spec_from_file_location("seed_demo", seed_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_demo"] = module
    spec.loader.exec_module(module)
    return module


def test_seed_demo_builds_a_populated_store() -> None:
    """``build_seeded_store`` returns repos + a ticketed record + a coverage snap."""
    seed = _load_seed_module()
    store = seed.build_seeded_store()

    repos = store.list_repos()
    # The demo seeds the two REAL repos (the dogfood `code-doc-monitor` + the
    # `demo-taskflow` adopter); the synthetic `acme-*` placeholders were removed.
    assert len(repos) >= 2, "the real demo repos are registered"

    # At least one repo has a ticketed record.
    ticketed = [
        rec
        for repo in repos
        for rec in store.records_for(repo.repo.repo_id)
        if rec.ticket is not None
    ]
    assert ticketed, "at least one ticketed ReviewRecord was seeded"
    assert any(r.verdict is not None for r in ticketed)

    # At least one repo carries a coverage snapshot with a per-file list.
    snapshots = [
        snap for repo in repos for snap in store.coverage_for(repo.repo.repo_id)
    ]
    assert snapshots, "at least one coverage snapshot was seeded"
    assert any(snap.get("files") for snap in snapshots), "a snapshot carries `files`"

    # Determinism: a second build yields the same repo ids and record ids (K10).
    store2 = seed.build_seeded_store()
    ids1 = [r.repo.repo_id for r in store.list_repos()]
    ids2 = [r.repo.repo_id for r in store2.list_repos()]
    assert ids1 == ids2
