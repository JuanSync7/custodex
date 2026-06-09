"""M-03 — the demo walkthrough drives the detect -> heal loop end to end (offline).

``demo/walkthrough.py`` copies the checked-in demo into a tempdir, induces real
drift, then runs ``cdmon`` through its core loop on the COPY: detect drift, heal
with the mock backend, re-check clean, show the review log, show the
``scheduler.py`` coverage gap, and pass ``doctor``. This test runs it as a
subprocess (offline, deterministic — the mock backend, no network) and asserts
it exits 0 AND its output shows every stage of the loop. It also asserts the
canonical demo on disk is NOT mutated (K1).

Features: FEAT-CLI-005, FEAT-CLI-007, FEAT-CLI-014, FEAT-CLI-015, FEAT-CLI-017
Features: FEAT-DRIFT-001, FEAT-MONITOR-003, FEAT-HEAL-001, FEAT-HEAL-008
Features: FEAT-BACKENDS-003, FEAT-RECORD-007, FEAT-COVERAGE-007, FEAT-QUALITY-008
Features: FEAT-CONFIGV2-013, FEAT-SERVER-012, FEAT-SERVER-013
"""

from __future__ import annotations

import subprocess
import sys

from tests._repo import REPO_ROOT

_REPO_ROOT = REPO_ROOT
_DEMO_DIR = _REPO_ROOT / "demo"
_WALKTHROUGH = _DEMO_DIR / "walkthrough.py"
_ENGINE = _DEMO_DIR / "src" / "taskflow" / "core" / "engine.py"


def test_walkthrough_runs_the_full_heal_loop() -> None:
    engine_before = _ENGINE.read_text(encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(_WALKTHROUGH)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    out = proc.stdout

    assert proc.returncode == 0, proc.stdout + proc.stderr

    # The loop is visible in order: drift detected -> healed -> clean again.
    assert "drift detected (cdmon check exit 1)" in out
    assert "FIX" in out  # the recorded verdict in the heal step / review log
    assert "clean (cdmon check exit 0)" in out
    # The review log step ran and reported recorded records.
    assert '"by_verdict"' in out
    # The real coverage gap surfaces.
    assert "src/taskflow/core/scheduler.py" in out
    # Doctor preflight passes.
    assert "PASS  config" in out
    assert "doctor PASS" in out

    # EDITOR E-12 [7/8]: the apply-fix engine section runs, prints a unified diff,
    # heals the doc, and proves a second call is an idempotent no-op (K7).
    assert "[7/8]" in out
    assert "Apply-fix engine" in out
    assert "--- unified diff for docs/api/core-api.md ---" in out
    assert "apply-fix: doc healed from the proposed fix" in out
    assert "apply-fix idempotent: second call is a no-op (empty diff)" in out

    # EDITOR E-12 [8/8]: link → generate closes the coverage gap live — scheduler.py
    # starts unlinked and ends documented.
    assert "[8/8]" in out
    assert "Link → generate" in out
    assert "scheduler.py starts UNLINKED" in out
    assert (
        "link → generate: scheduler.py is now documented — coverage gap closed live"
        in out
    )
    assert "-> apply-fix -> link->generate" in out  # the final DONE banner

    # K1: the walkthrough operated on a COPY and left the canonical demo intact.
    assert _ENGINE.read_text(encoding="utf-8") == engine_before
    assert "is_complete" not in _ENGINE.read_text(encoding="utf-8")
    assert "brand_new_engine_helper" not in _ENGINE.read_text(encoding="utf-8")
