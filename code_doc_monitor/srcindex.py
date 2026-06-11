"""The source index + source wiki engine (EPIC R, R-07).

Indexes every public symbol of a package and ties each TOP-LEVEL module to the
catalog features it implements — the inverse of :attr:`Feature.modules` — so the
source wiki and the traceability SOURCE view provably cover the whole public
surface. The deferred R-02 "no orphan public capability" check is finally
realizable here: :meth:`SourceIndex.modules_without_feature` lists every public
module with zero catalog features (a golden-reference gap), and
:meth:`SourceIndex.features_without_module_match` catches a catalog feature naming
a module the package no longer has.

Reuses :func:`code_doc_monitor.inventory.discover_files`/``discover_symbols`` (no
AST re-impl — K0) and :mod:`code_doc_monitor.featurecatalog`. Pure (K1 — the only
target touch is the AST inventory that already exists), dependency-free (K0),
deterministic (sorted modules + symbols, byte-stable render — K10), and loud on a
bad package root via inventory's :class:`code_doc_monitor.errors.InventoryError`
(K8).

**Module-name mapping.** Inventory yields paths relative to ``pkg_root`` — a
top-level file ``extract.py`` and subpackage files ``agent/graph.py``,
``server/app.py``. The catalog's ``Feature.modules`` use TOP-LEVEL names
(``extract``, ``agent``, ``server``), so a file is folded into the first path
component (its stem for a top-level file): ``agent/graph.py`` → ``agent``,
``server/app.py`` → ``server``, ``extract.py`` → ``extract``. Public symbols are
aggregated per top-level module. The package's own top-level ``__init__.py`` is a
pure re-export aggregator (its ``__all__``/``__version__`` are not a documentable
surface of their own — every symbol it re-exports lives in its home module), so it
is skipped — matching the spirit of the ``__init__`` coverage waivers in
``config/cdmon/index.yaml``. A subpackage ``__init__.py`` (e.g. ``agent/``) folds
into its top-level module (``agent``) and is kept.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, PrivateAttr

from .featurecatalog import FeatureCatalog
from .inventory import discover_files, discover_symbols

__all__ = [
    "ModuleIndex",
    "SourceIndex",
    "build_source_index",
    "render_source_wiki_md",
]

# Frozen + extra="forbid": a source index is an immutable, normalized snapshot
# (K10); an unknown field is a programming error, not a silent pass.
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class ModuleIndex(BaseModel):
    """One top-level module's public surface + the features that implement it."""

    model_config = _MODEL_CONFIG

    module: str  # top-level module name (e.g. "extract")
    path: str  # repo-relative posix path of a representative file
    public_symbols: tuple[str, ...]  # sorted public symbol names (from inventory)
    features: tuple[str, ...]  # sorted catalog feature ids whose `modules` name this


class SourceIndex(BaseModel):
    """The package's public surface crossed with the golden catalog (K10)."""

    model_config = ConfigDict(frozen=True)

    modules: tuple[ModuleIndex, ...]  # sorted by module name

    # The catalog join (feature id -> its declared modules) captured at build
    # time, so the completeness accessors reason about the catalog without
    # re-reading it. A private attr — not part of the serialized surface.
    _feature_modules: dict[str, tuple[str, ...]] = PrivateAttr(default_factory=dict)

    def features_without_module_match(self) -> tuple[str, ...]:
        """Catalog feature ids naming a module absent from the package (K8).

        Should be EMPTY for the real tree — a non-empty result means the catalog
        references a module the package no longer ships (drift). Sorted, deduped.
        """
        present = {m.module for m in self.modules}
        return tuple(
            sorted(
                fid
                for fid, mods in self._feature_modules.items()
                if not (set(mods) & present)
            )
        )

    def modules_without_feature(self) -> tuple[str, ...]:
        """Public modules with NO catalog feature — the orphan check (R-02).

        Sorted module names. EMPTY iff every public module maps to >=1 feature.
        """
        return tuple(m.module for m in self.modules if not m.features)


def _top_level_module(rel_path: str) -> str | None:
    """Fold a repo-relative file path into its top-level module name.

    ``agent/graph.py`` → ``agent``; ``extract.py`` → ``extract``. The package's
    own top-level ``__init__.py`` is a pure re-export aggregator and yields
    ``None`` (skipped — its symbols are documented in their home modules).
    """
    parts = Path(rel_path).parts
    if len(parts) == 1:
        stem = Path(parts[0]).stem
        if stem == "__init__":
            return None  # the package's own re-export aggregator
        return stem
    return parts[0]


def build_source_index(pkg_root: Path, catalog: FeatureCatalog) -> SourceIndex:
    """Inventory ``pkg_root`` and join each top-level module to its catalog features.

    Reuses :func:`inventory.discover_files`/``discover_symbols`` over ``pkg_root``
    (no AST re-impl — K0), folds every python file into its top-level module (see
    the module docstring), aggregates that module's PUBLIC symbol names, and joins
    each module to the sorted catalog feature ids whose ``modules`` name it. Pure
    (K1), deterministic (sorted modules + symbols — K10). A missing/invalid
    ``pkg_root`` raises a loud :class:`InventoryError` via inventory (K8).
    """
    inventory = discover_files(pkg_root)
    symbols = discover_symbols(inventory, pkg_root)

    # module name -> (representative path, set of public symbol names)
    public_by_module: dict[str, set[str]] = {}
    path_by_module: dict[str, str] = {}
    for file_symbols in symbols.files:
        module = _top_level_module(file_symbols.path)
        if module is None:
            continue
        bucket = public_by_module.setdefault(module, set())
        for sym in file_symbols.symbols:
            # A module's public surface is its TOP-LEVEL public names; a method
            # name is qualified (``Class.method``) and belongs to its class, not
            # the module surface — so only dot-free public names are counted.
            if sym.is_public and "." not in sym.name:
                bucket.add(sym.name)
        # The representative path is the lexicographically-smallest file of the
        # module (deterministic — K10); inventory.files is already path-sorted.
        if module not in path_by_module:
            path_by_module[module] = file_symbols.path

    # feature id -> its declared modules; and module -> features that name it.
    feature_modules: dict[str, tuple[str, ...]] = {
        f.id: f.modules for f in catalog.features
    }
    features_by_module: dict[str, list[str]] = {}
    for fid, mods in feature_modules.items():
        for mod in mods:
            features_by_module.setdefault(mod, []).append(fid)

    modules = tuple(
        ModuleIndex(
            module=module,
            path=path_by_module[module],
            public_symbols=tuple(sorted(public_by_module[module])),
            features=tuple(sorted(features_by_module.get(module, ()))),
        )
        for module in sorted(public_by_module)
    )

    index = SourceIndex(modules=modules)
    # Capture the catalog join for the completeness accessors (private attr —
    # not part of the serialized surface).
    object.__setattr__(index, "_feature_modules", feature_modules)
    return index


def render_source_wiki_md(index: SourceIndex) -> str:
    """Render the source wiki — per-module path, symbols, features + a summary (K10).

    Pure and byte-stable: the same index in, byte-identical Markdown out (no clock,
    no environment). Each module lists its representative path, its public symbols,
    and the catalog features that implement it; a closing **Coverage** section
    counts the modules and names any orphan (un-catalogued) module — the deferred
    R-02 "no orphan public capability" report.
    """
    orphans = index.modules_without_feature()
    lines: list[str] = [
        "# code-doc-monitor — source wiki",
        "",
        (
            "Generated from the package inventory crossed against the golden "
            "catalog — **do not hand-edit**. Run `cdmon wiki` (R-08) to regenerate."
        ),
        "",
        f"**{len(index.modules)} public modules**, "
        f"{len(orphans)} without a catalogued feature.",
        "",
    ]

    for m in index.modules:
        syms = ", ".join(f"`{s}`" for s in m.public_symbols) or "—"
        feats = ", ".join(f"`{f}`" for f in m.features) or "— NONE"
        lines.append(f"## `{m.module}`")
        lines.append("")
        lines.append(f"- Path: `{m.path}`")
        lines.append(f"- Public symbols: {syms}")
        lines.append(f"- Implemented by: {feats}")
        lines.append("")

    lines.append("## Coverage")
    lines.append("")
    if not orphans:
        lines.append("None — every public module maps to at least one catalog feature.")
    else:
        lines.append("Modules with NO catalog feature (orphan public capability):")
        for module in orphans:
            lines.append(f"- `{module}`")

    return "\n".join(lines).rstrip("\n") + "\n"
