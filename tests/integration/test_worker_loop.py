"""AGT-06 — the server-side worker pass + the default-OFF lifespan loop.

`_run_worker_pass` runs the two pure ticks over every repo with a readable
local working tree and RECONCILES into the store (per-repo error isolation:
one broken repo logs and the pass continues). The loop is armed by the app
lifespan ONLY when `settings.server.workers.enabled` (K4: default OFF) and
shuts down via `threading.Event` (never a bare sleep).

Features: FEAT-WORKERS-002
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi.testclient import TestClient

from custodex.server.app import _run_worker_pass, create_app
from custodex.server.store import InMemoryStore
from custodex.settings import ServerSettings, Settings, WorkerSettings

_NOW = "2026-07-06T12:00:00+00:00"

_UNIT = """\
---
cdmon-config-version: "2.0.0"
unit: core
title: "core docs"
owner: eng
created: "2026-07-01"
updated: "2026-07-01"
---
dir-covered:
  - src
source-files-format:
  - .py
documents:
  - id: guide
    path: docs/guide.md
    audience: eng-guide
    region_keys: []
"""

_INDEX = """\
---
cdmon-config-version: "2.0.0"
repo: t
generated-by: cdx
updated: "2026-07-01"
---
root: "../.."
version: "2.0.0"
backend: {kind: mock}
units:
  - file: core.yaml
"""


def _local_repo(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    cfg_dir = root / "config" / "cdmon"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "index.yaml").write_text(_INDEX, encoding="utf-8")
    (cfg_dir / "core.yaml").write_text(_UNIT, encoding="utf-8")
    src = root / "src"
    src.mkdir()
    (src / "gamma.py").write_text("def hot_gap(z):\n    return z\n", encoding="utf-8")
    docs = root / "docs"
    docs.mkdir()
    # An UNHEALED doc (drift → FIX_DRIFT) whose prose mentions the uncovered
    # symbol (→ DOCUMENT_GAP): both suggesters have something to say.
    (docs / "guide.md").write_text(
        "# Guide\n\nCall `hot_gap` early.\n", encoding="utf-8"
    )
    return root


def _register_local(store: InMemoryStore, repo_id: str, local: Path | None) -> None:
    from custodex.registry import RegistrationPayload
    from custodex.sinks import RepoIdentity

    store.add_repo(
        RegistrationPayload(
            repo=RepoIdentity(
                repo_id=repo_id,
                local_path=str(local) if local is not None else None,
            )
        )
    )


def test_worker_pass_fills_the_inbox_and_isolates_failures(tmp_path: Path) -> None:
    store = InMemoryStore()
    good = _local_repo(tmp_path, "good")
    _register_local(store, "good", good)
    # A repo whose local tree is UNREADABLE garbage: the pass must log and
    # continue, never die (per-repo isolation).
    broken = tmp_path / "broken"
    (broken / "config" / "cdmon").mkdir(parents=True)
    (broken / "config" / "cdmon" / "index.yaml").write_text(
        "not: [valid", encoding="utf-8"
    )
    _register_local(store, "broken", broken)
    # A central-only repo (no local_path): skipped silently.
    _register_local(store, "central-only", None)

    _run_worker_pass(store, _NOW, ("fixes", "docs"))

    good_inbox = store.suggestions_for("good")
    kinds = {s.kind for s in good_inbox}
    assert "fix_drift" in kinds  # the unhealed doc
    assert "document_gap" in kinds  # hot_gap mentioned, uncovered
    assert all(s.source == "worker" and s.recorded_at == _NOW for s in good_inbox)
    assert store.suggestions_for("broken") == []
    assert store.suggestions_for("central-only") == []


def test_worker_pass_respects_the_kinds_setting(tmp_path: Path) -> None:
    store = InMemoryStore()
    _register_local(store, "good", _local_repo(tmp_path, "good"))
    _run_worker_pass(store, _NOW, ("docs",))
    kinds = {s.kind for s in store.suggestions_for("good")}
    assert "document_gap" in kinds and "fix_drift" not in kinds


def test_lifespan_arms_the_loop_only_when_enabled() -> None:
    ran = threading.Event()
    calls = {"n": 0}

    def counting_pass() -> None:
        calls["n"] += 1
        ran.set()

    on = Settings(
        server=ServerSettings(workers=WorkerSettings(enabled=True, interval_seconds=1))
    )
    app = create_app(InMemoryStore(), settings=on, worker_pass=counting_pass)
    with TestClient(app):
        assert ran.wait(timeout=5), "the armed loop never ran a pass"
    assert calls["n"] >= 1
    # After shutdown the loop is STOPPED: no further passes accumulate.
    settled = calls["n"]
    assert not ran.clear() and calls["n"] == settled

    # Default OFF (K4): no pass ever runs.
    calls["n"] = 0
    off_app = create_app(InMemoryStore(), worker_pass=counting_pass)
    with TestClient(off_app):
        pass
    assert calls["n"] == 0
