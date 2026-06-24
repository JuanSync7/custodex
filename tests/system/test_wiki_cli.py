"""System tests for ``cdx wiki`` + the traceability CI gate (EPIC R, R-08).

These exercise the CLI end to end on the REAL repo tree. The wiki files are
snapshotted before any mutation and restored after, so the suite leaves the tree
byte-identical (and fresh).

Features: FEAT-REFERENCE-007
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from custodex.cli import app

REPO_ROOT = Path(__file__).resolve().parents[2]

_WIKI_PATHS = (
    Path("feature-doc/FEATURES.md"),
    Path("feature-doc/wiki/TEST_WIKI.md"),
    Path("feature-doc/wiki/SOURCE_WIKI.md"),
    Path("feature-doc/wiki/TRACEABILITY.md"),
)


@pytest.fixture
def in_repo_root(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run the CLI from the repo root (``cdx`` resolves paths relative to cwd)."""
    monkeypatch.chdir(REPO_ROOT)
    yield


@pytest.fixture
def restore_wikis() -> Iterator[None]:
    """Snapshot the four wiki files and restore them verbatim after the test."""
    snapshot: dict[Path, str | None] = {}
    for rel in _WIKI_PATHS:
        p = REPO_ROOT / rel
        snapshot[p] = p.read_text(encoding="utf-8") if p.is_file() else None
    try:
        yield
    finally:
        for p, original in snapshot.items():
            if original is None:
                if p.is_file():
                    p.unlink()
            else:
                p.write_text(original, encoding="utf-8")


def test_wiki_then_check_is_idempotent(in_repo_root: None, restore_wikis: None) -> None:
    """``cdx wiki`` then ``cdx wiki --check`` both exit 0 (idempotent, K7).

    Features: FEAT-REFERENCE-007
    """
    runner = CliRunner()
    wrote = runner.invoke(app, ["wiki"])
    assert wrote.exit_code == 0, wrote.output

    checked = runner.invoke(app, ["wiki", "--check"])
    assert checked.exit_code == 0, checked.output
    assert "fresh" in checked.output


def test_wiki_run_twice_is_a_noop(in_repo_root: None, restore_wikis: None) -> None:
    """A second ``cdx wiki`` reports every target unchanged (idempotent, K7).

    Features: FEAT-REFERENCE-007
    """
    runner = CliRunner()
    runner.invoke(app, ["wiki"])
    second = runner.invoke(app, ["wiki"])
    assert second.exit_code == 0, second.output
    assert "wrote" not in second.output
    assert second.output.count("unchanged") == len(_WIKI_PATHS)


def test_check_fails_after_a_wiki_is_touched(
    in_repo_root: None, restore_wikis: None
) -> None:
    """After appending a byte to a wiki, ``cdx wiki --check`` exits nonzero (K8).

    Features: FEAT-REFERENCE-007
    """
    runner = CliRunner()
    runner.invoke(app, ["wiki"])  # ensure fresh

    touched = REPO_ROOT / "feature-doc" / "wiki" / "TRACEABILITY.md"
    touched.write_text(touched.read_text(encoding="utf-8") + "x", encoding="utf-8")

    checked = runner.invoke(app, ["wiki", "--check"])
    assert checked.exit_code == 1, checked.output
    assert "TRACEABILITY.md" in checked.output


def test_trace_fail_on_gap_passes_on_the_real_tree(in_repo_root: None) -> None:
    """``cdx trace --fail-on-gap`` exits 0 on the real tree — the completeness gate.

    Features: FEAT-REFERENCE-007
    """
    runner = CliRunner()
    result = runner.invoke(app, ["trace", "--fail-on-gap"])
    assert result.exit_code == 0, result.output
    assert "COMPLETE" in result.output


def test_committed_wikis_are_fresh_through_the_cli(in_repo_root: None) -> None:
    """``cdx wiki --check`` exits 0 on the committed tree (no mutation).

    Features: FEAT-REFERENCE-007
    """
    # Skip if a concurrent test left a snapshot mid-flight (defensive only).
    assert os.path.isdir(REPO_ROOT / "feature-doc")
    runner = CliRunner()
    result = runner.invoke(app, ["wiki", "--check"])
    assert result.exit_code == 0, result.output


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
