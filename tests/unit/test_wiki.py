"""Unit tests for the ``cdmon wiki`` regeneration engine (EPIC R, R-08).

Features: FEAT-REFERENCE-007
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_doc_monitor.traceability import build_matrix
from code_doc_monitor.wiki import WIKI_TARGETS, regenerate

REPO_ROOT = Path(__file__).resolve().parents[2]

_CANONICAL_PATHS = {
    Path("feature-doc/FEATURES.md"),
    Path("feature-doc/wiki/TEST_WIKI.md"),
    Path("feature-doc/wiki/SOURCE_WIKI.md"),
    Path("feature-doc/wiki/TRACEABILITY.md"),
}


def test_wiki_targets_are_exactly_the_four_canonical_paths() -> None:
    """``WIKI_TARGETS`` keys are exactly the four canonical wiki output paths.

    Features: FEAT-REFERENCE-007
    """
    assert set(WIKI_TARGETS) == _CANONICAL_PATHS


def test_wiki_targets_render_to_nonempty_markdown() -> None:
    """Each render thunk produces non-empty markdown over the real repo root.

    Features: FEAT-REFERENCE-007
    """
    for thunk in WIKI_TARGETS.values():
        text = thunk(REPO_ROOT)
        assert text.strip()
        assert text.endswith("\n")


def test_committed_wikis_are_fresh() -> None:
    """``regenerate(write=False)`` over the real repo reports nothing stale.

    The committed artifacts on disk must match a fresh render (R-08 ran
    ``cdmon wiki`` to regenerate them).

    Features: FEAT-REFERENCE-007
    """
    results = regenerate(REPO_ROOT, write=False)
    stale = [path for path, is_stale in results if is_stale]
    assert stale == [], f"committed wikis stale: {stale}"


def test_regenerate_write_then_recheck_is_idempotent(tmp_path: Path) -> None:
    """A first write produces all four; the on-disk render then re-checks fresh (K7).

    Renders against the REAL repo root but writes into an isolated tmp copy of the
    ``feature-doc`` subtree so the test never mutates the committed tree.

    Features: FEAT-REFERENCE-007
    """
    results = regenerate(REPO_ROOT, write=False)
    # All four targets are present and rendered.
    assert sorted(p for p, _ in results) == sorted(
        p.as_posix() for p in _CANONICAL_PATHS
    )

    # Render once, write into a tmp repo seeded with the real source dirs, then
    # confirm a re-check over that tmp repo reports nothing stale (idempotent).
    _seed_repo(tmp_path)
    first = regenerate(tmp_path, write=True)
    assert all(changed for _, changed in first), "fresh tmp repo: all four written"
    second = regenerate(tmp_path, write=True)
    assert not any(changed for _, changed in second), "second write is a no-op (K7)"
    check = regenerate(tmp_path, write=False)
    assert not any(stale for _, stale in check), "check is fresh after a write"


def test_check_mode_lists_exactly_the_mutated_target_as_stale(tmp_path: Path) -> None:
    """After mutating one wiki, check-mode lists exactly that file as stale (K8).

    Features: FEAT-REFERENCE-007
    """
    _seed_repo(tmp_path)
    regenerate(tmp_path, write=True)
    target = Path("feature-doc/wiki/TEST_WIKI.md")
    mutated = tmp_path / target
    mutated.write_text(mutated.read_text(encoding="utf-8") + "\nDRIFT\n", "utf-8")

    results = regenerate(tmp_path, write=False)
    stale = [path for path, is_stale in results if is_stale]
    assert stale == [target.as_posix()]


def test_missing_target_is_stale_in_check_mode(tmp_path: Path) -> None:
    """A missing on-disk target reads as stale in check-mode (K8).

    Features: FEAT-REFERENCE-007
    """
    _seed_repo(tmp_path)
    regenerate(tmp_path, write=True)
    (tmp_path / "feature-doc" / "wiki" / "SOURCE_WIKI.md").unlink()

    results = regenerate(tmp_path, write=False)
    stale = [path for path, is_stale in results if is_stale]
    assert stale == ["feature-doc/wiki/SOURCE_WIKI.md"]


def test_results_are_sorted_by_path() -> None:
    """``regenerate`` returns ``(path, flag)`` tuples sorted by path (K10).

    Features: FEAT-REFERENCE-007
    """
    results = regenerate(REPO_ROOT, write=False)
    paths = [p for p, _ in results]
    assert paths == sorted(paths)


def test_renders_are_deterministic() -> None:
    """Two renders of the same target over the same root are byte-identical (K10).

    Features: FEAT-REFERENCE-007
    """
    for thunk in WIKI_TARGETS.values():
        assert thunk(REPO_ROOT) == thunk(REPO_ROOT)


def test_new_reference_feature_keeps_the_matrix_complete() -> None:
    """FEAT-REFERENCE-007 has a demo + a test, so the matrix stays complete.

    Features: FEAT-REFERENCE-007
    """
    from code_doc_monitor.featurecatalog import load_catalog

    catalog = load_catalog(REPO_ROOT / "feature-doc" / "catalog")
    matrix = build_matrix(
        catalog,
        tests_root=REPO_ROOT / "tests",
        demo_root=REPO_ROOT / "demo",
    )
    assert "FEAT-REFERENCE-007" in matrix.catalog_ids
    assert matrix.is_complete()


def _seed_repo(root: Path) -> None:
    """Seed ``root`` with the source dirs the renders read (catalog/tests/demo/pkg).

    The renders read ``feature-doc/catalog``, ``tests``, ``demo``, and
    ``code_doc_monitor`` relative to the given repo root; symlinking them lets a
    write-mode regenerate target a throwaway ``feature-doc/wiki`` without touching
    the committed tree.
    """
    (root / "feature-doc").mkdir(parents=True, exist_ok=True)
    (root / "feature-doc" / "catalog").symlink_to(REPO_ROOT / "feature-doc" / "catalog")
    (root / "feature-doc" / "FEATURES.md").touch()
    for name in ("tests", "demo", "code_doc_monitor"):
        (root / name).symlink_to(REPO_ROOT / name)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
