"""Depth-independent repo-root locator for the test suite (R-05).

The test files were physically reorganized into boundary directories
(``tests/{unit,integration,system,smoke}/``) by slice R-05. A test that hard-codes
``Path(__file__).resolve().parents[1]`` breaks the moment its file moves a level
deeper. ``REPO_ROOT`` searches upward for the directory containing
``pyproject.toml`` instead, so the repo-root anchor is independent of how deeply
the test file is nested under ``tests/``.
"""

from __future__ import annotations

from pathlib import Path


def _find_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("repo root (pyproject.toml) not found")


REPO_ROOT = _find_root()
