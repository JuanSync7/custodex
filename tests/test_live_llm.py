"""Real-LLM end-to-end test — the ONLY test that may spawn a live backend.

This is deliberately quarantined from the default offline suite (K4): it is
marked ``live_llm`` and ``addopts`` excludes that marker, so a bare ``pytest``
never touches a network or an LLM. CI opts in explicitly with ``-m live_llm``
(see ``.gitlab-ci.yml``'s ``tests:live-llm`` job).

The backend is taken from the **config file**, resolved through the same
``make_backend`` path as production — set ``backend.kind`` in the fixture config
via ``CDMON_LIVE_BACKEND`` (``claude-code`` by default, or ``api``). The test
skips when the configured backend's prerequisite is absent (the ``claude`` CLI
for ``claude-code``; ``ANTHROPIC_API_KEY`` for ``api``) or when it is ``mock``
(not a real LLM).

What it proves: a realistic code change raises BOTH a HASH and a REGION drift,
and ``monitor --apply``, driven by a *real* LLM, self-heals the document in a
single pass. This is the scenario that a real ``claude -p`` reply (filling both
fix shapes at once) exposed — the regression that the offline
``test_apply_fix_prefers_whole_doc_when_both_shapes_present`` and
``test_both_shapes_fix_self_heals_in_one_pass`` lock down at the unit/monitor
level, verified here against a live model.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from code_doc_monitor.config import load_config
from code_doc_monitor.extract import build_document_surface
from code_doc_monitor.heal import regenerate_regions
from code_doc_monitor.monitor import Monitor
from code_doc_monitor.schema import Verdict

pytestmark = pytest.mark.live_llm

_LIVE = os.environ.get("CDMON_LIVE_LLM") == "1"
_BACKEND = os.environ.get("CDMON_LIVE_BACKEND", "claude-code")

_CODE_V1 = '''\
"""A tiny module the doc describes."""


def add(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b


def mul(a: int, b: int) -> int:
    """Return the product of two integers."""
    return a * b
'''

_DOC_STUB = """\
# tiny module — engineering reference

> Auto-maintained by code-doc-monitor. The prose is human; the table below is
> generated from the code and kept in sync.

<!-- CDM:BEGIN symbols -->
PLACEHOLDER
<!-- CDM:END symbols -->
"""

_CONFIG = """\
version: "1.0.0"
root: "."
backend:
  kind: {kind}
documents:
  - id: api
    path: docs/api.md
    audience: eng-guide
    region_keys: [symbols]
    code_refs:
      - path: mod.py
"""


def _prerequisite_available(kind: str) -> bool:
    """Whether the configured real backend can actually run in this environment."""
    if kind == "claude-code":
        return shutil.which("claude") is not None
    if kind == "api":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    return False  # "mock" is not a real LLM


def _build_repo(tmp_path: Path, kind: str) -> tuple[Path, Path]:
    """Write a config-driven fixture repo, healed to a clean baseline."""
    root = tmp_path
    (root / "mod.py").write_text(_CODE_V1, encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "api.md").write_text(_DOC_STUB, encoding="utf-8")
    cfg_path = root / "cdmon.yaml"
    cfg_path.write_text(_CONFIG.format(kind=kind), encoding="utf-8")

    # Sync the doc to the code deterministically (no LLM) for a clean start.
    cfg = load_config(cfg_path)
    spec = cfg.documents[0]
    regenerate_regions(root / spec.path, build_document_surface(spec, root))
    return root, cfg_path


@pytest.mark.skipif(not _LIVE, reason="set CDMON_LIVE_LLM=1 to run the real-LLM test")
def test_real_llm_self_heals_in_one_pass(tmp_path: Path) -> None:
    if not _prerequisite_available(_BACKEND):
        pytest.skip(
            f"backend {_BACKEND!r} prerequisite unavailable "
            "(need the `claude` CLI for claude-code, or $ANTHROPIC_API_KEY for api)"
        )

    root, cfg_path = _build_repo(tmp_path, _BACKEND)
    cfg = load_config(cfg_path)
    # The backend is whatever the CONFIG FILE says — resolved via make_backend.
    assert cfg.backend.kind == _BACKEND
    monitor = Monitor(cfg, cfg_path.parent)

    # Clean baseline, then a realistic code change -> BOTH a HASH and a REGION
    # drift (a new public function the symbol table is missing).
    assert monitor.check().ok
    (root / "mod.py").write_text(
        _CODE_V1 + '\n\ndef sub(a: int, b: int) -> int:\n    """Difference."""\n'
        "    return a - b\n",
        encoding="utf-8",
    )
    assert not monitor.check().ok

    # The REAL LLM judges each drift; --apply writes its proposed fix.
    result = monitor.run(apply=True)

    assert result.handled, "the live backend was never asked to judge a drift"
    assert any(h.result.verdict is Verdict.FIX for h in result.handled)
    # Single-pass self-heal: nothing left over (the both-shapes regression).
    assert result.remaining == (), (
        "real-LLM monitor --apply left residual drift: "
        f"{[(d.doc_id, d.kind.value) for d in result.remaining]}"
    )
    # And a fresh detect confirms the document is back in sync.
    assert monitor.check().ok
