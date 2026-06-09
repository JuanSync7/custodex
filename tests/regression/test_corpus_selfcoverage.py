"""H-03 regression corpus — self-coverage & dogfood invariants.

The program's self-improvement guards: engine self-coverage stays at/above the
committed floor, every engine module is OWNED (an UNLISTED `code_doc_monitor/**`
module is detected as a gap — the most likely future self-gate regression per the
H-01/H-04 lesson), and the checked-in dogfood docs stay in sync with the code.

Each case names the lesson id it guards. See ``tests/regression/README.md``.
"""

from __future__ import annotations

from pathlib import Path

from code_doc_monitor import inventory
from code_doc_monitor.config import load_config_dir
from code_doc_monitor.coverage import resolve_coverage
from code_doc_monitor.layout import lint_config
from code_doc_monitor.monitor import Monitor

_ROOT = Path(__file__).resolve().parents[2]
# cdmon's canonical self-config is the CONFIG-V2 dir layout (Z-02 removed the
# redundant single-file root cdmon.yaml).
_CONFIG_DIR = _ROOT / "config" / "cdmon"

# The committed self-coverage floor — the SAME threshold the CI
# `cdmon coverage --fail-under` gate and tests/test_dogfood.py use (H-02).
_COVERAGE_THRESHOLD = 95.0


def _copy_dogfood_tree(dst: Path) -> Path:
    """Copy the engine + docs + dir-layout config + templates into ``dst``.

    The dir layout resolves the repo root via ``config/cdmon`` root="../.." and a
    ``doc-style.yaml`` pointer under ``templates/writing/``, so the copy must carry
    all four trees. Returns the copied ``config/cdmon`` directory.
    """
    import shutil

    dst.mkdir(exist_ok=True)
    shutil.copytree(_ROOT / "code_doc_monitor", dst / "code_doc_monitor")
    shutil.copytree(_ROOT / "docs", dst / "docs")
    shutil.copytree(_ROOT / "config", dst / "config")
    shutil.copytree(_ROOT / "templates", dst / "templates")
    return dst / "config" / "cdmon"


def _dogfood_report() -> object:
    """Resolve the real dogfood coverage report exactly as `cdmon coverage` does."""
    cfg = load_config_dir(_CONFIG_DIR)
    root = _CONFIG_DIR / cfg.root
    inv = inventory.discover_files(
        root,
        include=cfg.coverage.include,
        exclude=cfg.coverage.exclude,
    )
    sym = inventory.discover_symbols(inv, root)
    return resolve_coverage(cfg, sym)


# ---------------------------------------------------------------------------
# [H-02] Self-coverage stays at/above the committed threshold.
# ---------------------------------------------------------------------------


def test_self_coverage_meets_committed_threshold() -> None:
    """[H-02] Engine public-symbol self-coverage stays >= the committed floor.

    Mirrors the CI `cdmon coverage --fail-under 95` gate (and test_dogfood) so the
    self-improvement cannot silently regress: a new undocumented engine symbol
    drops the % below the floor and fails here, in test_dogfood, AND in CI.
    """
    pct = _dogfood_report().percent_public_symbols  # type: ignore[attr-defined]
    assert pct >= _COVERAGE_THRESHOLD, (
        f"engine self-coverage {pct:.1f}% < committed {_COVERAGE_THRESHOLD}%; "
        "document the new public symbols (or waive with a reason in a unit file)"
    )


def test_every_coverage_waiver_carries_a_reason() -> None:
    """[H-02 / A-04] Each coverage waiver justifies itself — losslessness explicit."""
    for sym in _dogfood_report().waived_symbols:  # type: ignore[attr-defined]
        assert sym.waived_reason, f"waived {sym.path}::{sym.name} has no reason"


# ---------------------------------------------------------------------------
# [H-01/H-04] An UNLISTED `code_doc_monitor/**` module is detected as a GAP.
# This is the single most likely future self-gate regression: adding an engine
# module without documenting it must DROP self-coverage / surface a gap.
# ---------------------------------------------------------------------------


def test_unlisted_engine_module_is_detected_as_a_gap(tmp_path: Path) -> None:
    """[H-01/H-04] A brand-new undocumented engine module DROPS self-coverage.

    Copies the real engine + docs + config to a temp tree (so the repo is never
    mutated), drops a NEW public module into `code_doc_monitor/` WITHOUT adding it
    to any unit file, and asserts (a) its public symbol is an undocumented gap and
    (b) self-coverage falls below the committed floor. This is exactly the
    H-01/H-04 finding ("a NEW engine module is itself a doc gap") turned into a
    standing guard.

    BREAK-IT (confirmed bites): if the coverage scan stopped including
    `code_doc_monitor/**/*.py` (e.g. a narrowed `coverage.include`), the new
    module would NOT be scanned → no gap → both assertions red.
    """
    config_dir = _copy_dogfood_tree(tmp_path / "proj")
    cfg = load_config_dir(config_dir)
    root = config_dir / cfg.root

    # Baseline on the copy: at/above the floor and the new symbol absent.
    base = resolve_coverage(
        cfg,
        inventory.discover_symbols(
            inventory.discover_files(
                root, include=cfg.coverage.include, exclude=cfg.coverage.exclude
            ),
            root,
        ),
    )
    base_pct = base.percent_public_symbols  # type: ignore[attr-defined]
    assert base_pct >= _COVERAGE_THRESHOLD

    # Drop an UNLISTED public engine module (not referenced by any doc).
    new_mod = config_dir.parent.parent / "code_doc_monitor" / "brand_new_unlisted.py"
    new_mod.write_text(
        '"""An engine module nobody documented yet."""\n\n\n'
        "def brand_new_public_symbol(x: int) -> int:\n    return x\n",
        encoding="utf-8",
    )

    after = resolve_coverage(
        cfg,
        inventory.discover_symbols(
            inventory.discover_files(
                root, include=cfg.coverage.include, exclude=cfg.coverage.exclude
            ),
            root,
        ),
    )
    # (a) the new public symbol is an undocumented gap (owned by nothing).
    gap_names = {(s.path, s.name) for s in after.undocumented_symbols}  # type: ignore[attr-defined]
    assert any(
        path.endswith("brand_new_unlisted.py") and name == "brand_new_public_symbol"
        for path, name in gap_names
    ), "an unlisted engine module's public symbol must be a detected gap"
    # (b) the gap DROPS self-coverage (the self-gate's `--fail-under` headroom
    #     shrinks toward failure as undocumented engine modules accumulate).
    assert after.percent_public_symbols < base_pct  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# [CDM-07] The dogfood stays in sync (referenced from test_dogfood) + conforms
# to the Layout Standard (CDM-08).
# ---------------------------------------------------------------------------


def test_dogfood_docs_are_in_sync() -> None:
    """[CDM-07] The checked-in docs match the checked-in code (in-sync assertion).

    A thin re-assertion of the dogfood in-sync guard so the corpus indexes it:
    any drift between the engine source and its `docs/api/*` reds here too.
    """
    cfg = load_config_dir(_CONFIG_DIR)
    report = Monitor(cfg, _CONFIG_DIR).check()
    assert report.ok, report.summary()


def test_dogfood_docs_conform_to_layout_standard() -> None:
    """[CDM-08] The checked-in docs satisfy the machine-checked Layout Standard."""
    cfg = load_config_dir(_CONFIG_DIR)
    issues = lint_config(cfg, _ROOT)
    assert issues == [], [f"{i.doc_id}: {i.code.value} — {i.detail}" for i in issues]


def test_dogfood_self_heals_on_a_copy(tmp_path: Path) -> None:
    """[CDM-07] The full self-heal loop works on the real project (on a copy).

    Proves the heal LOOP (not just the in-sync state): a real source edit drifts a
    tracked doc, `monitor --apply` heals it, and `check` returns clean — all on a
    temp copy so the committed repo is never dirtied.
    """
    config_dir = _copy_dogfood_tree(tmp_path / "proj")
    cfg = load_config_dir(config_dir)
    dst = config_dir.parent.parent

    assert Monitor(cfg, config_dir).check().ok  # copy starts clean

    target = dst / "code_doc_monitor" / "config.py"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\n\ndef regression_corpus_helper(x: int) -> int:\n    return x\n",
        encoding="utf-8",
    )
    assert not Monitor(cfg, config_dir).check().ok  # drift detected

    Monitor(cfg, config_dir, now=lambda: "2026-06-01T00:00:00Z").run(apply=True)
    assert Monitor(cfg, config_dir).check().ok  # fully self-healed
