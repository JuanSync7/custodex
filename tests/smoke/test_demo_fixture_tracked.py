"""The demo fixture files the suite depends on must be GIT-TRACKED.

PR #20 fresh-review must-fix: ``demo/src/taskflow/core/notes.log`` was created
on the dev tree but swallowed by ``demo/.gitignore``'s ``*.log`` — so
``test_demo_ignored_files_includes_notes_log`` (and DEMO-010's "present"
claim) held only on trees that happened to carry the untracked file, and every
CLEAN checkout ran the suite red. The same checkout-variance class the mention
layer was fixed for (``frontend/dist``). This lint pins the fixtures to git so
the suite can never silently depend on untracked state again.

Features: FEAT-CONFIGV2-017
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from tests._repo import REPO_ROOT

#: Demo files that are DELIBERATELY ignore-matched (that is their point — they
#: demo the ignore/coverage split) yet load-bearing for the suite: each must be
#: force-tracked (`git add -f`) or a fresh clone runs red.
_LOAD_BEARING = ("demo/src/taskflow/core/notes.log",)


def test_load_bearing_demo_fixtures_are_git_tracked() -> None:
    if shutil.which("git") is None:  # pragma: no cover - CI always has git
        pytest.skip("git not available")
    for rel in _LOAD_BEARING:
        assert (REPO_ROOT / rel).is_file(), f"{rel} missing from the tree"
        proc = subprocess.run(  # noqa: S603,S607 - fixed argv, no shell
            ["git", "-C", str(REPO_ROOT), "ls-files", "--error-unmatch", rel],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, (
            f"{rel} is NOT git-tracked — the suite depends on it; "
            "force-track it (git add -f) or a clean checkout runs red"
        )
