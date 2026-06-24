#!/usr/bin/env python
"""A deterministic, offline guided tour of the cdx detect -> heal loop.

Run it from the repo root::

    python demo/walkthrough.py

It copies the checked-in ``demo/`` into a throwaway temp directory (it NEVER
mutates the canonical demo, K1), induces real drift on a tracked source file,
then drives ``cdx`` through its core loop on the COPY:

    1. drift detected   — ``cdx check`` reports drift (exit non-zero)
    2. healed           — ``cdx monitor --apply`` regenerates the region
    3. clean            — ``cdx check`` is clean again (exit 0)
    4. review log       — ``cdx report`` shows the recorded verdict/provenance
    5. coverage gap     — ``cdx rpt`` shows the undocumented ``scheduler.py``
    6. doctor pass      — ``cdx doctor`` preflight passes

It then demonstrates the two EDITOR (E-12) engine actions the Mapping page wires
to buttons, still on the COPY and still offline:

    7. apply-fix       — the ``Apply fix (LLM)`` button's engine
                         (:func:`custodex.generate.apply_record_fix`):
                         induce drift, get a FIX record carrying a ``fix``, apply
                         it (print the unified diff), and prove a second call is an
                         idempotent no-op (K7).
    8. link → generate — the ``Link a file → Generate / make live`` flow
                         (:func:`custodex.generate.apply_edits_to_disk`):
                         stage an ``add_code_ref`` edit linking the deliberately
                         UNLINKED ``scheduler.py`` to ``core-api``, apply it, and
                         show ``cdx rpt`` no longer lists ``scheduler.py`` as
                         undocumented — the coverage gap is closed live.

Everything is offline and deterministic: it uses the demo's built-in ``mock``
backend (no network, no API key) and operates on the working tree (``mode=local``
semantics), so no real git remote is needed. Exits 0 on success.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from custodex.config import load_config_dir
from custodex.generate import apply_edits_to_disk, apply_record_fix
from custodex.monitor import Monitor
from custodex.schema import Verdict
from custodex.server.edits import AddCodeRefEdit, EditCodeRef
from custodex.sinks import NullSink

# The canonical, checked-in demo (this script lives at demo/walkthrough.py).
_DEMO_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _DEMO_DIR.parent

# A public method appended to Engine so the `core-api` `symbols` region drifts.
_DRIFT_METHOD = '''
    def is_complete(self) -> bool:
        """Return True when every task in the graph has a terminal status."""
        return all(task.status.is_terminal for task in self.graph.tasks.values())
'''

# A deterministic clock for the EDITOR engine calls (apply-fix / link->generate).
_NOW = "2026-06-07T00:00:00Z"

# A module-level public function appended to engine.py to drift `core-api` for the
# apply-fix demo. engine.py is WHOLE-file under core-api, so this yields a FIX
# record carrying a whole-doc fix that apply_record_fix can heal in one shot.
_APPLY_FIX_DRIFT = (
    "\n\ndef brand_new_engine_helper(x: int) -> int:\n"
    '    """A new module-level helper public to the engine API."""\n'
    "    return x\n"
)


def _header(step: str, title: str) -> None:
    """Print a clear, human-followable section header."""
    bar = "=" * 70
    print(f"\n{bar}\n{step}  {title}\n{bar}", flush=True)


def _cdmon(
    config_dir: Path, *args: str, config_flag: str = "--config"
) -> subprocess.CompletedProcess[str]:
    """Run ``cdx <args> <config_flag> <config_dir>`` via the in-tree CLI module.

    Uses ``python -m custodex.cli`` with the SAME interpreter that runs
    this script, so it works straight from the activated venv with no network.
    Most commands take ``--config``; ``rpt`` takes ``--config-dir`` instead.
    """
    cmd = [
        sys.executable,
        "-m",
        "custodex.cli",
        *args,
        config_flag,
        str(config_dir),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout, end="", flush=True)
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr, flush=True)
    return proc


def _induce_drift(copy_dir: Path) -> None:
    """Append a public method to ``engine.py`` so ``core-api`` drifts."""
    engine = copy_dir / "src" / "taskflow" / "core" / "engine.py"
    text = engine.read_text(encoding="utf-8")
    engine.write_text(text.rstrip("\n") + "\n" + _DRIFT_METHOD, encoding="utf-8")


def _demo_apply_fix(copy_dir: Path) -> int:
    """EDITOR E-12: the ``Apply fix (LLM)`` button's engine, on the COPY (offline).

    Induce drift on the demo's documented ``engine.py``, run Monitor WITHOUT apply
    to capture a FIX :class:`ReviewRecord` carrying a whole-doc ``fix``, then call
    :func:`apply_record_fix` to heal that one doc — printing the unified diff — and
    prove a second call is an idempotent no-op (K7). Returns an exit code.
    """
    _header("[7/8]", "Apply-fix engine: `apply_record_fix` (the Mapping page button)")
    config_dir = copy_dir / "config" / "cdmon"

    engine = copy_dir / "src" / "taskflow" / "core" / "engine.py"
    engine.write_text(
        engine.read_text(encoding="utf-8") + _APPLY_FIX_DRIFT, encoding="utf-8"
    )
    print(
        "Added a public engine helper → core-api drifts; running Monitor "
        "(apply=False) to get a FIX record carrying a proposed fix",
        flush=True,
    )

    cfg = load_config_dir(config_dir)
    monitor = Monitor(cfg, config_dir, now=lambda: _NOW, sink=NullSink())
    result = monitor.run(apply=False)
    fix_records = [
        r
        for r in result.records
        if r.verdict is Verdict.FIX and r.fix and r.fix.new_doc_text is not None
    ]
    if not fix_records:
        print("UNEXPECTED: no whole-doc FIX record produced", file=sys.stderr)
        return 1
    record = fix_records[0]
    print(
        f"FIX record for doc {record.doc_id!r} (verdict={record.verdict.value}) "
        "carries a proposed fix — applying it to disk",
        flush=True,
    )

    applied = apply_record_fix(copy_dir, record, now=_NOW)
    if not applied.applied or not applied.diff:
        print("UNEXPECTED: apply_record_fix did not change the doc", file=sys.stderr)
        return 1
    print(f"--- unified diff for {applied.doc_path} ---", flush=True)
    print(applied.diff, flush=True)
    print("apply-fix: doc healed from the proposed fix", flush=True)

    again = apply_record_fix(copy_dir, record, now=_NOW)
    if again.applied or again.diff:
        print("UNEXPECTED: second apply was not a no-op", file=sys.stderr)
        return 1
    print("apply-fix idempotent: second call is a no-op (empty diff)", flush=True)
    return 0


def _demo_link_generate(copy_dir: Path) -> int:
    """EDITOR E-12: the ``Link a file → Generate / make live`` flow (offline).

    The demo's ``scheduler.py`` is DELIBERATELY unlinked (the coverage gap shown on
    the Mapping page). Here we stage the edit the ticket form would submit — an
    ``add_code_ref`` linking ``scheduler.py`` to ``core-api`` — apply it with
    :func:`apply_edits_to_disk` (writes the unit yaml + index, scaffolds/heals the
    doc), then show ``cdx rpt`` no longer lists ``scheduler.py`` as undocumented:
    the gap is closed live. Returns an exit code.
    """
    _header("[8/8]", "Link → generate: `apply_edits_to_disk` (close the coverage gap)")
    config_dir = copy_dir / "config" / "cdmon"

    before = _cdmon(config_dir, "rpt", config_flag="--config-dir")
    if "scheduler.py" not in before.stdout:
        print("UNEXPECTED: scheduler.py not reported undocumented", file=sys.stderr)
        return 1
    print(
        "scheduler.py starts UNLINKED (the live Mapping-page coverage gap); "
        "staging an add_code_ref edit linking it to core-api",
        flush=True,
    )

    edit = AddCodeRefEdit(
        unit="core",
        doc_id="core-api",
        ref=EditCodeRef(path="src/taskflow/core/scheduler.py"),
    )
    gen = apply_edits_to_disk(copy_dir, [edit], now=_NOW)
    print(
        f"generated: wrote unit(s) {list(gen.affected_units)}, "
        f"healed doc(s) {list(gen.affected_docs)}",
        flush=True,
    )

    after = _cdmon(config_dir, "rpt", config_flag="--config-dir")
    if after.returncode != 0 or "scheduler.py" in after.stdout:
        print(
            "UNEXPECTED: scheduler.py still undocumented after link→generate",
            file=sys.stderr,
        )
        return 1
    print(
        "link → generate: scheduler.py is now documented — coverage gap closed live",
        flush=True,
    )
    return 0


def run(copy_dir: Path) -> int:
    """Drive the full loop on ``copy_dir`` (a COPY of the demo). Return an exit code."""
    config_dir = copy_dir / "config" / "cdmon"

    _header("[1/6]", "Induce drift: add a public method to engine.py")
    _induce_drift(copy_dir)
    print("Added Engine.is_complete() to src/taskflow/core/engine.py", flush=True)

    _header("[2/6]", "Detect: `cdx check` should report drift")
    check = _cdmon(config_dir, "check")
    if check.returncode == 0:
        print("UNEXPECTED: check found no drift", file=sys.stderr)
        return 1
    print(f"drift detected (cdx check exit {check.returncode})", flush=True)

    _header("[3/6]", "Heal: `cdx monitor --apply` (mock backend, offline)")
    healed = _cdmon(config_dir, "monitor", "--apply")
    if healed.returncode != 0:
        print("UNEXPECTED: heal did not converge", file=sys.stderr)
        return 1
    print("healed: region regenerated from the live code surface", flush=True)

    _header("[4/6]", "Verify: `cdx check` should be clean again")
    reclean = _cdmon(config_dir, "check")
    if reclean.returncode != 0:
        print("UNEXPECTED: drift remains after heal", file=sys.stderr)
        return 1
    print(f"clean (cdx check exit {reclean.returncode})", flush=True)

    _header("[5/6]", "Review log: `cdx report` shows the recorded verdict")
    report = _cdmon(config_dir, "report")
    if report.returncode != 0:
        print("UNEXPECTED: report failed", file=sys.stderr)
        return 1

    _header("[6/6]", "Coverage gap + doctor preflight")
    print("--- coverage gap: `cdx rpt` ---", flush=True)
    rpt = _cdmon(config_dir, "rpt", config_flag="--config-dir")
    if rpt.returncode != 0 or "scheduler.py" not in rpt.stdout:
        print("UNEXPECTED: scheduler.py gap not reported", file=sys.stderr)
        return 1
    print("\n--- doctor preflight: `cdx doctor` ---", flush=True)
    doctor = _cdmon(config_dir, "doctor")
    if doctor.returncode != 0:
        print("UNEXPECTED: doctor did not pass", file=sys.stderr)
        return 1

    # EDITOR (E-12) headline flows: the apply-fix engine then link → generate.
    rc = _demo_apply_fix(copy_dir)
    if rc != 0:
        return rc
    rc = _demo_link_generate(copy_dir)
    if rc != 0:
        return rc

    _header(
        "DONE",
        "drift -> healed -> clean -> review log -> coverage gap -> doctor PASS "
        "-> apply-fix -> link->generate",
    )
    return 0


def main() -> int:
    """Copy the demo to a tempdir and run the loop; the canonical demo is untouched."""
    with tempfile.TemporaryDirectory(prefix="cdmon-walkthrough-") as tmp:
        copy_dir = Path(tmp) / "demo"
        shutil.copytree(_DEMO_DIR, copy_dir)
        return run(copy_dir)


if __name__ == "__main__":
    raise SystemExit(main())
