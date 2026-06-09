"""EDITOR E-04 — ``GET /repos/{id}/config/editable`` the editable config tree.

Two surfaces over a :class:`TestClient`:

* the STANDALONE app pointed at the shipped ``demo/`` (a real on-disk dir-layout
  repo with the deliberate ``scheduler.py`` gap, the ignored ``notes.log``, the
  two units ``core``/``io``, and the vendored writing templates) — exercises the
  full working-tree-derived computation (undocumented / ignored / unit_files /
  doc_styles);
* a CENTRAL-only repo registered with NO ``local_path`` whose config rows are
  seeded via ``replace_config`` — exercises the K8 robustness path: the stored
  documents (with code_refs + context_refs) still render, the disk-derived lists
  are empty, and the route never raises.

Plus the unknown-repo 404 (matching the other routes' ``_require_known_repo``).
Offline + deterministic (K10).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="the [server] extra (fastapi) is not installed")

from fastapi.testclient import TestClient  # noqa: E402

from code_doc_monitor.registry import RegistrationPayload  # noqa: E402
from code_doc_monitor.server.app import create_app  # noqa: E402
from code_doc_monitor.server.standalone import build_standalone_app  # noqa: E402
from code_doc_monitor.server.store import (  # noqa: E402
    ConfigCodeRef,
    ConfigContextRef,
    ConfigDocument,
    InMemoryStore,
)
from code_doc_monitor.sinks import RepoIdentity  # noqa: E402

_NOW = "2026-06-08T00:00:00Z"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEMO_DIR = _REPO_ROOT / "demo"


# --------------------------------------------------------------------------- #
# Standalone app over the shipped demo — the full working-tree computation.
# --------------------------------------------------------------------------- #


def _demo_tree() -> dict:
    app = build_standalone_app(_DEMO_DIR, now=_NOW)
    client = TestClient(app)
    resp = client.get("/repos/demo-taskflow/config/editable")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_demo_returns_documents_with_code_refs() -> None:
    body = _demo_tree()
    assert body["repo_id"] == "demo-taskflow"
    assert body["sync_kind"] == "local"  # defaulted

    docs = {d["document"]["doc_id"]: d for d in body["documents"]}
    assert {"core-api", "getting-started", "io-api"} <= set(docs)

    # core-api references model.py + engine.py (whole-file code_refs).
    core_refs = {r["path"] for r in docs["core-api"]["code_refs"]}
    assert "src/taskflow/core/model.py" in core_refs
    assert "src/taskflow/core/engine.py" in core_refs

    # getting-started carries symbol-selective code_refs.
    gs_refs = {r["path"]: r["symbols"] for r in docs["getting-started"]["code_refs"]}
    assert gs_refs["src/taskflow/core/model.py"] == ["Task"]

    # context_refs is present on every document (defaults to [] in the demo,
    # which has not yet vendored any — E-12 adds them).
    for d in body["documents"]:
        assert "context_refs" in d["document"]


def test_demo_undocumented_files_contains_the_deliberate_gap() -> None:
    body = _demo_tree()
    undoc = body["undocumented_files"]
    # scheduler.py is in-scope (under core's dir-covered, a .py file) but linked
    # by NO document — the deliberate unlinked gap.
    assert "src/taskflow/core/scheduler.py" in undoc
    # documented files must NOT appear in the gap list.
    assert "src/taskflow/core/model.py" not in undoc
    assert "src/taskflow/io/storage.py" not in undoc
    # sorted + deterministic.
    assert undoc == sorted(undoc)


def test_demo_ignored_files_includes_notes_log() -> None:
    body = _demo_tree()
    ignored = body["ignored_files"]
    # notes.log sits under the core dir but the *.log ignore glob removes it.
    assert "src/taskflow/core/notes.log" in ignored
    assert ignored == sorted(ignored)


def test_demo_unit_files_are_the_two_units() -> None:
    body = _demo_tree()
    assert body["unit_files"] == ["core", "io"]


def test_demo_doc_styles_list_the_vendored_template_stems() -> None:
    body = _demo_tree()
    styles = body["doc_styles"]
    assert styles["document_type"] == [
        "api-reference",
        "explanation",
        "how-to",
        "tutorial",
    ]
    assert styles["tone"] == ["formal", "friendly", "precise"]
    assert styles["writing_style"] == ["concise", "narrative", "reference-dense"]
    assert styles["vocabulary"] == ["engine-domain", "general"]


# --------------------------------------------------------------------------- #
# Central-only repo (no local_path) — the K8 robustness path.
# --------------------------------------------------------------------------- #


def _central_store() -> InMemoryStore:
    store = InMemoryStore()
    store.add_repo(
        RegistrationPayload(
            repo=RepoIdentity(
                repo_id="central-only",
                repo_name="central-only",
                # NO local_path: this is a central-mirror-only repo.
            ),
            description="central-only repo, no working tree",
        )
    )
    doc = ConfigDocument(
        repo_id="central-only",
        doc_id="guide",
        path="docs/guide.md",
        audience="user-guide",
        unit="core",
        region_keys=("symbols",),
        context_refs=(
            ConfigContextRef(path="docs/api/core-api.md", note="full reference"),
        ),
        sync_kind="local",
        synced_at=_NOW,
    )
    ref = ConfigCodeRef(
        repo_id="central-only",
        doc_id="guide",
        path="src/pkg/model.py",
        symbols=("Task",),
        unit="core",
        sync_kind="local",
    )
    store.replace_config("central-only", "local", [doc], [ref])
    return store


def test_central_only_repo_returns_documents_with_empty_disk_parts() -> None:
    client = TestClient(create_app(_central_store()))
    resp = client.get("/repos/central-only/config/editable")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["repo_id"] == "central-only"
    assert body["sync_kind"] == "local"
    # the stored document still renders, with its code_refs + context_refs.
    (doc,) = body["documents"]
    assert doc["document"]["doc_id"] == "guide"
    assert doc["code_refs"][0]["path"] == "src/pkg/model.py"
    assert doc["document"]["context_refs"][0]["path"] == "docs/api/core-api.md"

    # disk-derived parts are empty (no local_path → no working-tree scan), no 500.
    assert body["undocumented_files"] == []
    assert body["ignored_files"] == []
    assert body["unit_files"] == []
    assert body["doc_styles"] == {
        "document_type": [],
        "tone": [],
        "writing_style": [],
        "vocabulary": [],
    }


def test_unknown_repo_is_404() -> None:
    client = TestClient(create_app(InMemoryStore()))
    resp = client.get("/repos/nope/config/editable")
    assert resp.status_code == 404, resp.text
