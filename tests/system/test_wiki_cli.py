"""System tests for ``cdx wiki`` + the traceability CI gate (EPIC R, R-08).

These exercise the CLI end to end. The tests that run ``cdx wiki`` in WRITE mode
(or corrupt a wiki on purpose) run on a private copy of the repo
(:func:`tests._wikirepo.copy_wiki_repo`), so the real tree is never written, not
even transiently. Only the read-only gates (``cdx trace --fail-on-gap`` and
``cdx wiki --check``) run on the real tree. ``test_wiki_cli_hygiene.py`` pins both
the copy's faithfulness and that this module never writes the repo it runs in.

Features: FEAT-REFERENCE-007
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from custodex.cli import app
from custodex.wiki import WIKI_TARGETS
from tests._repo import REPO_ROOT
from tests._wikirepo import copy_wiki_repo


@pytest.fixture
def in_repo_root(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run the CLI from the real repo root, for READ-ONLY commands only.

    ``cdx`` resolves paths relative to cwd. A write-mode command belongs on
    :func:`wiki_repo` instead.
    """
    monkeypatch.chdir(REPO_ROOT)
    yield


@pytest.fixture
def wiki_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run the CLI from a private copy of the repo; return the copy's root."""
    root = copy_wiki_repo(tmp_path / "repo")
    monkeypatch.chdir(root)
    return root


def test_wiki_then_check_is_idempotent(wiki_repo: Path) -> None:
    """``cdx wiki`` then ``cdx wiki --check`` both exit 0 (idempotent, K7).

    Features: FEAT-REFERENCE-007
    """
    runner = CliRunner()
    wrote = runner.invoke(app, ["wiki"])
    assert wrote.exit_code == 0, wrote.output

    checked = runner.invoke(app, ["wiki", "--check"])
    assert checked.exit_code == 0, checked.output
    assert "fresh" in checked.output


def test_wiki_run_twice_is_a_noop(wiki_repo: Path) -> None:
    """A second ``cdx wiki`` reports every target unchanged (idempotent, K7).

    Features: FEAT-REFERENCE-007
    """
    runner = CliRunner()
    runner.invoke(app, ["wiki"])
    second = runner.invoke(app, ["wiki"])
    assert second.exit_code == 0, second.output
    assert "wrote" not in second.output
    assert second.output.count("unchanged") == len(WIKI_TARGETS)


def test_check_fails_after_a_wiki_is_touched(wiki_repo: Path) -> None:
    """After appending a byte to a wiki, ``cdx wiki --check`` exits nonzero (K8).

    Features: FEAT-REFERENCE-007
    """
    runner = CliRunner()
    runner.invoke(app, ["wiki"])  # ensure fresh

    touched = wiki_repo / "feature-doc" / "wiki" / "TRACEABILITY.md"
    touched.write_text(touched.read_text(encoding="utf-8") + "x", encoding="utf-8")

    checked = runner.invoke(app, ["wiki", "--check"])
    assert checked.exit_code == 1, checked.output
    assert "TRACEABILITY.md" in checked.output


def test_wiki_repo_is_a_copy_outside_the_real_tree(wiki_repo: Path) -> None:
    """The write tests' repo is a private copy outside the real tree, and the cwd.

    Features: FEAT-REFERENCE-007
    """
    assert not wiki_repo.resolve().is_relative_to(REPO_ROOT.resolve())
    assert Path.cwd().resolve() == wiki_repo.resolve()


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
    runner = CliRunner()
    result = runner.invoke(app, ["wiki", "--check"])
    assert result.exit_code == 0, result.output


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
