"""The ``cdx wiki`` regeneration engine (EPIC R, R-08 — the close-out slice).

The single entry point that renders ALL of EPIC R's derived artifacts from their
single sources (the catalog yaml + the tests' docstrings + the source AST) to a
canonical set of repo-relative paths:

```
feature-doc/FEATURES.md          ← featurecatalog.render_features_md(load_catalog)
feature-doc/wiki/TEST_WIKI.md    ← testwiki.render_test_wiki_md(collect_tests(tests))
feature-doc/wiki/SOURCE_WIKI.md  ← srcindex.render_source_wiki_md(build_source_index)
feature-doc/wiki/TRACEABILITY.md ← traceability.render_matrix_md(build_matrix)
```

:data:`WIKI_TARGETS` (path → render thunk) is the SINGLE source of the output
set, so ``cdx wiki`` and ``cdx wiki --check`` can never diverge. Each thunk
takes a repo root and returns markdown; :func:`regenerate` renders every target,
compares it to disk, and either writes the changed ones (write mode) or reports
the stale ones (check mode — the CI freshness gate, K8).

Pure-ish and deterministic (no clock, sorted output — K10); idempotent (a second
write is a no-op — K7); loud on a render error (a :class:`CatalogError` /
:class:`InventoryError` propagates — K8); no new dependency (K0). The catalog +
``known_modules`` are computed once per :func:`regenerate` call so a single load
feeds the three catalog-dependent renders.
"""

from __future__ import annotations

import pkgutil
from collections.abc import Callable
from pathlib import Path

from .featurecatalog import FeatureCatalog, load_catalog, render_features_md
from .srcindex import build_source_index, render_source_wiki_md
from .testwiki import collect_tests, render_test_wiki_md
from .traceability import build_matrix, render_matrix_md

__all__ = [
    "WIKI_TARGETS",
    "regenerate",
]

# Repo-relative source locations the renders read from.
_CATALOG_DIR = Path("feature-doc") / "catalog"
_TESTS_DIR = Path("tests")
_DEMO_DIR = Path("demo")
_PKG_DIR = Path("custodex")


def _known_modules() -> set[str]:
    """Top-level modules under ``custodex`` (the catalog typo guard).

    Mirrors :func:`custodex.cli._known_modules` so a feature naming a
    module the package does not ship is a loud :class:`CatalogError` at load (K8).
    """
    from . import __path__ as pkg_path

    return {m.name for m in pkgutil.iter_modules(pkg_path)}


def _load_catalog(repo_root: Path) -> FeatureCatalog:
    """Load the golden catalog under ``repo_root`` with the module typo guard."""
    return load_catalog(repo_root / _CATALOG_DIR, known_modules=_known_modules())


def _render_features(repo_root: Path) -> str:
    """Render ``feature-doc/FEATURES.md`` from the golden catalog."""
    return render_features_md(_load_catalog(repo_root))


def _render_test_wiki(repo_root: Path) -> str:
    """Render ``feature-doc/wiki/TEST_WIKI.md`` from the tests' docstrings (K1)."""
    return render_test_wiki_md(collect_tests(repo_root / _TESTS_DIR))


def _render_source_wiki(repo_root: Path) -> str:
    """Render ``feature-doc/wiki/SOURCE_WIKI.md`` from the source AST + catalog."""
    index = build_source_index(repo_root / _PKG_DIR, _load_catalog(repo_root))
    return render_source_wiki_md(index)


def _render_traceability(repo_root: Path) -> str:
    """Render ``feature-doc/wiki/TRACEABILITY.md`` from the catalog × evidence."""
    matrix = build_matrix(
        _load_catalog(repo_root),
        tests_root=repo_root / _TESTS_DIR,
        demo_root=repo_root / _DEMO_DIR,
    )
    return render_matrix_md(matrix)


# The SINGLE source of the wiki output set: repo-relative path → render thunk.
# Each thunk takes a repo root and returns the byte-stable markdown for that path.
WIKI_TARGETS: dict[Path, Callable[[Path], str]] = {
    Path("feature-doc/FEATURES.md"): _render_features,
    Path("feature-doc/wiki/TEST_WIKI.md"): _render_test_wiki,
    Path("feature-doc/wiki/SOURCE_WIKI.md"): _render_source_wiki,
    Path("feature-doc/wiki/TRACEABILITY.md"): _render_traceability,
}


def regenerate(repo_root: Path, *, write: bool) -> list[tuple[str, bool]]:
    """Render every wiki target under ``repo_root``; write or report staleness.

    For each :data:`WIKI_TARGETS` entry the thunk is rendered and compared to the
    on-disk file. In WRITE mode a changed (or missing) target is written (parents
    created) and reported ``True``; an already-identical file is left untouched and
    reported ``False`` — so a second run is a no-op (idempotent, K7). In CHECK mode
    (``write=False``) NOTHING is written: a target is reported ``True`` (stale) when
    the on-disk file is missing or differs from the fresh render — the CI freshness
    gate (K8). Returns ``[(repo_relative_posix_path, changed_or_stale)]`` sorted by
    path (deterministic — K10). A render error (bad catalog/package) propagates loud
    (K8).
    """
    results: list[tuple[str, bool]] = []
    for rel_path in sorted(WIKI_TARGETS, key=lambda p: p.as_posix()):
        rendered = WIKI_TARGETS[rel_path](repo_root)
        target = repo_root / rel_path
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        differs = current != rendered
        if write and differs:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8")
        results.append((rel_path.as_posix(), differs))
    return results
