"""A private, faithful copy of the repo's wiki inputs and outputs (TEST-WIKI-HYGIENE).

``cdx wiki`` resolves everything relative to the cwd, so a test that runs it in
WRITE mode from the real repo root writes the real ``feature-doc/``. A
write-then-restore fixture is still a write: a concurrent reader, an editor or a
killed run sees the corrupted wiki, and a restore hides that it happened.
:func:`copy_wiki_repo` gives such a test its own tree instead.

The copied dirs are derived from :mod:`custodex.wiki` itself: every module-level
``_<NAME>_DIR`` constant (the convention its render inputs follow) plus the
:data:`~custodex.wiki.WIKI_TARGETS` keys, so a new input declared that way is
copied with no edit here. An input the renders reach any other way (an inline
``Path("docs")`` joined onto the repo root, or read relative to the cwd) is NOT
picked up by the derivation; the backstop for that is
``tests/system/test_wiki_cli_hygiene.py``, which pins that every render on the
copy (run from the copy) equals the render on the real tree (run from the real
tree). The dirs are COPIED, never symlinked:
the renders only read them today, but a link would let any future write under the
copy reach the real tree.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path, PurePath
from typing import Any

from custodex import wiki as _wiki
from tests._repo import REPO_ROOT

__all__ = ["WIKI_REPO_DIRS", "copy_wiki_repo"]

# A module-level render-input constant in custodex.wiki: ``_CATALOG_DIR`` etc.
_DIR_CONSTANT = re.compile(r"_[A-Z0-9_]*[A-Z0-9]_DIR")


def _top_dir(name: str, rel: object) -> str:
    """The top-level repo dir of ``rel``; loud unless it is a relative in-repo Path."""
    if (
        not isinstance(rel, PurePath)
        or rel.is_absolute()
        or not rel.parts
        or ".." in rel.parts
    ):
        raise ValueError(f"{name}={rel!r} is not a relative Path inside the repo")
    return rel.parts[0]


def _wiki_repo_dirs(module: Any) -> tuple[str, ...]:
    """The top-level dirs ``module``'s renders read from or write to, sorted (K10).

    Every module-level ``_<NAME>_DIR`` constant plus every ``WIKI_TARGETS`` key.
    A constant that is not a relative in-repo Path, or a module that yields no
    dir at all, raises ``ValueError``: dropping it would leave an input uncopied.
    """
    found = {
        _top_dir(name, value)
        for name, value in vars(module).items()
        if _DIR_CONSTANT.fullmatch(name)
    }
    found |= {_top_dir(f"WIKI_TARGETS[{rel!r}]", rel) for rel in module.WIKI_TARGETS}
    if not found:
        raise ValueError(f"{module!r} declares no render inputs to copy")
    return tuple(sorted(found))


# The top-level repo dirs the wiki renders read from or write to.
WIKI_REPO_DIRS: tuple[str, ...] = _wiki_repo_dirs(_wiki)

# Build and tool caches: never render inputs, so copying them only costs time.
_IGNORE = shutil.ignore_patterns(
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"
)


def copy_wiki_repo(dst: Path, *, src: Path = REPO_ROOT) -> Path:
    """Copy :data:`WIKI_REPO_DIRS` from ``src`` into a NEW directory ``dst``.

    ``dst`` must not exist yet (``FileExistsError`` otherwise), so a copy never
    merges into or overwrites an existing tree; its parent must exist. Symlinks
    are followed and copied as plain files; a dangling one (an editor lock such as
    ``.#x.py``) is skipped, as the test and evidence scans skip anything that is
    not a file. Returns ``dst``.
    """
    dst.mkdir()
    for name in WIKI_REPO_DIRS:
        shutil.copytree(
            src / name, dst / name, ignore=_IGNORE, ignore_dangling_symlinks=True
        )
    return dst
