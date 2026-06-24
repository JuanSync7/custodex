"""Ownership resolver — the heart of EPIC A coverage (A-03, pure — K0/K1/K10).

Crosses a :class:`~custodex.inventory.SymbolInventory` (every file and
its extracted symbols) with a :class:`~custodex.config.MonitorConfig`'s
document ``code_refs`` to decide, losslessly, what is **documented** versus an
**undocumented gap** — at both file and symbol granularity.

It is pure (K1): it touches no filesystem (the inventory already carries every
:class:`~custodex.extract.Symbol`) and adds no dependency (K0). Symbol
selection is **not re-implemented**: it reuses the private
:func:`custodex.extract._select`, so whole-file (empty selectors),
``symbols`` (a class name pulls in its methods), ``lines``-overlap and ``names``
semantics all come for free and stay consistent with extraction.

Two deliberate rules:

* **Ownership ignores audience.** A ``code_ref`` "covers" the symbol it points
  at regardless of the document's audience — audience governs the *hash/surface*
  (``build_document_surface``), not whether the code is *referenced*. So a
  ``user-guide`` ref over a file still owns that file's private symbols (they
  are tracked, never counted as a gap).
* **The gap-% universe is PUBLIC symbols only.** Private symbols are tracked
  losslessly in :attr:`CoverageReport.symbols` but are excluded from
  :attr:`CoverageReport.percent_public_symbols` and the
  :attr:`CoverageReport.undocumented_symbols` gap basket — they are not
  documentation targets.

All output is deterministic (K10): files sorted by ``path``, symbols by
``(path, name, kind)``, and ``owners`` sorted + deduped.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from .config import CodeRef, MonitorConfig, WaiverEntry
from .extract import Symbol, _select
from .inventory import SymbolInventory, _translate

__all__ = [
    "OwnedFile",
    "OwnedSymbol",
    "CoverageReport",
    "OwnerSuggestion",
    "resolve_coverage",
    "suggest_owners",
    "coverage_snapshot",
]

# Frozen + extra="forbid": a coverage report is an immutable, normalized
# snapshot (K10); an unknown field is a programming error, not a silent pass.
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class OwnedFile(BaseModel):
    """One inventory file plus the doc ids that reference it (``()`` == gap).

    ``waived_reason`` is set (A-04) iff a ``config.coverage.waive`` entry matched
    this *unowned* file: it then leaves the gap basket and enters
    :attr:`CoverageReport.waived_files`, carrying its justification.
    """

    model_config = _MODEL_CONFIG

    path: str  # repo-relative POSIX, matches FileSymbols.path
    language: str
    owners: tuple[str, ...]  # doc ids whose code_refs name this path; sorted, deduped
    waived_reason: str | None = None  # set iff a waiver matched this unowned file


class OwnedSymbol(BaseModel):
    """One inventory symbol plus the doc ids whose code_refs select it.

    ``waived_reason`` is set (A-04) iff a ``config.coverage.waive`` entry matched
    this *unowned, public* symbol: it then leaves the gap basket and enters
    :attr:`CoverageReport.waived_symbols`, carrying its justification.
    """

    model_config = _MODEL_CONFIG

    path: str  # owning file's path
    name: str  # qualified for methods (Class.method)
    kind: str  # function / class / method / variable
    is_public: bool  # extract.Symbol.is_public (leaf-name rule)
    owners: tuple[str, ...]  # doc ids selecting this symbol; sorted, deduped
    waived_reason: str | None = None  # set iff a waiver matched this unowned symbol


class CoverageReport(BaseModel):
    """The lossless file- and symbol-level ownership cross of config × inventory.

    :attr:`files` and :attr:`symbols` carry **every** inventory file/symbol
    (losslessness), sorted deterministically. The derived baskets and
    percentages restrict the *gap* metric to public symbols (private symbols are
    tracked but never a documentation target).
    """

    model_config = _MODEL_CONFIG

    files: tuple[OwnedFile, ...]  # ALL files, sorted by path
    symbols: tuple[OwnedSymbol, ...]  # ALL symbols, sorted by (path, name, kind)

    @property
    def documented_files(self) -> tuple[OwnedFile, ...]:
        """Files referenced by at least one document."""
        return tuple(f for f in self.files if f.owners)

    @property
    def undocumented_files(self) -> tuple[OwnedFile, ...]:
        """Files unreferenced AND not waived (the file-level gap basket).

        A waived file (``waived_reason`` set) is reclassified out of the gap and
        into :attr:`waived_files` (A-04).
        """
        return tuple(f for f in self.files if not f.owners and f.waived_reason is None)

    @property
    def waived_files(self) -> tuple[OwnedFile, ...]:
        """Unreferenced files an explicit waiver excused (A-04)."""
        return tuple(f for f in self.files if f.waived_reason is not None)

    @property
    def documented_symbols(self) -> tuple[OwnedSymbol, ...]:
        """Public symbols owned by at least one document."""
        return tuple(s for s in self.symbols if s.is_public and s.owners)

    @property
    def undocumented_symbols(self) -> tuple[OwnedSymbol, ...]:
        """Public, unowned, non-waived symbols — the symbol-level gap basket.

        Private symbols are excluded: they are tracked in :attr:`symbols` but
        are not documentation targets, so they never count as gaps. A waived
        public symbol (``waived_reason`` set) is reclassified into
        :attr:`waived_symbols` (A-04).
        """
        return tuple(
            s
            for s in self.symbols
            if s.is_public and not s.owners and s.waived_reason is None
        )

    @property
    def waived_symbols(self) -> tuple[OwnedSymbol, ...]:
        """Public, unowned symbols an explicit waiver excused (A-04)."""
        return tuple(
            s for s in self.symbols if s.is_public and s.waived_reason is not None
        )

    @property
    def percent_files(self) -> float:
        """``100 * documented / (total - waived)`` files; ``100.0`` if universe empty.

        Waived files leave BOTH the numerator and the denominator (A-04), so a
        fully-waived-or-documented repo reports 100%.
        """
        universe = len(self.files) - len(self.waived_files)
        if universe == 0:
            return 100.0
        return len(self.documented_files) / universe * 100

    @property
    def percent_public_symbols(self) -> float:
        """``100 * documented_public / (public - waived)``; ``100.0`` if universe empty.

        The universe is PUBLIC symbols only (private symbols are not doc
        targets), minus waived public symbols (A-04). A repo with zero public,
        non-waived symbols is vacuously 100% covered (no zero-division).
        """
        public = [s for s in self.symbols if s.is_public]
        universe = [s for s in public if s.waived_reason is None]
        if not universe:
            return 100.0
        documented = sum(1 for s in universe if s.owners)
        return documented / len(universe) * 100


def _sorted_owners(owners: set[str]) -> tuple[str, ...]:
    """Sorted, deduped doc ids (K10)."""
    return tuple(sorted(owners))


def _waiver_reason(
    waivers: tuple[tuple[re.Pattern[str], WaiverEntry], ...],
    path: str,
    symbol: str | None,
) -> str | None:
    """First matching waiver's reason for ``(path, symbol)``, else ``None`` (A-04).

    A *file* query passes ``symbol=None`` and matches only whole-file waivers
    (the entry's ``symbol`` is ``None``). A *symbol* query passes the symbol's
    name and matches either a whole-file waiver (entry ``symbol is None``) or an
    exact-name waiver. Waivers are tried in config order so the first stated
    justification wins, deterministically (K10).
    """
    for pattern, entry in waivers:
        if pattern.match(path) is None:
            continue
        if entry.symbol is None:
            return entry.reason
        if symbol is not None and entry.symbol == symbol:
            return entry.reason
    return None


def resolve_coverage(config: MonitorConfig, inv: SymbolInventory) -> CoverageReport:
    """Resolve file- and symbol-level ownership of ``inv`` by ``config`` documents.

    Pure (K1) and dependency-free (K0): every fact comes from the inventory and
    the config; symbol selection reuses :func:`extract._select`. A **file is
    owned** iff some document's ``code_ref.path`` equals the file's ``path``; a
    **symbol is owned** iff some ``code_ref`` on that file selects it (by
    ``(name, lineno)`` membership of ``_select``'s result over the file's full
    symbol list). Ownership ignores audience; ``arg_signature`` is not applied
    (it narrows a *surface*, not ownership). Output is deterministic (K10).

    A-04 (additive): ``config.coverage.waive`` is then folded in. An *unowned*
    file/symbol whose path matches a waiver glob (reusing :func:`inventory._translate`)
    — and, for a symbol, whose name matches the entry's ``symbol`` (``None`` ⇒
    whole-file) — is stamped with that entry's ``reason`` and reclassified out of
    the gap basket into the waived basket. Only unowned (and, for symbols,
    public) items are waivable: a waiver on an already-documented or private
    item is inert; a waiver matching nothing is silently inert. With the default
    empty ``waive`` the report is identical to the A-03 path.
    """
    # Group every code_ref by the file path it points at, remembering the doc id.
    # (doc_id, ref) pairs let one ref attribute a single owner to its selection.
    refs_by_path: dict[str, list[tuple[str, CodeRef]]] = {}
    for doc in config.documents:
        for ref in doc.code_refs:
            refs_by_path.setdefault(ref.path, []).append((doc.id, ref))

    # Pre-compile each waiver's path glob once (K0 — reuse inventory's translation).
    waivers: tuple[tuple[re.Pattern[str], WaiverEntry], ...] = tuple(
        (_translate(entry.path), entry) for entry in config.coverage.waive
    )

    files: list[OwnedFile] = []
    symbols: list[OwnedSymbol] = []

    for file_symbols in inv.files:
        path = file_symbols.path
        path_refs = refs_by_path.get(path, [])

        # File-level ownership: any doc that names this path owns the file.
        file_owners = {doc_id for doc_id, _ref in path_refs}
        # A waiver only excuses an UNOWNED (gap) file (documented wins).
        file_waiver = _waiver_reason(waivers, path, None) if not file_owners else None
        files.append(
            OwnedFile(
                path=path,
                language=file_symbols.language,
                owners=_sorted_owners(file_owners),
                waived_reason=file_waiver,
            )
        )

        # Symbol-level ownership: a ref owns each symbol its _select picks out.
        # Keyed by (name, lineno) — unique per symbol within a file (K10).
        full: list[Symbol] = list(file_symbols.symbols)
        owners_by_symbol: dict[tuple[str, int], set[str]] = {}
        for doc_id, ref in path_refs:
            selected = _select(full, ref.symbols, ref.lines, ref.names)
            for sym in selected:
                owners_by_symbol.setdefault((sym.name, sym.lineno), set()).add(doc_id)

        for sym in full:
            owners = owners_by_symbol.get((sym.name, sym.lineno), set())
            # Only an UNOWNED, PUBLIC symbol is waivable (private symbols are not
            # doc targets; documented symbols win).
            sym_waiver = (
                _waiver_reason(waivers, path, sym.name)
                if (sym.is_public and not owners)
                else None
            )
            symbols.append(
                OwnedSymbol(
                    path=path,
                    name=sym.name,
                    kind=sym.kind,
                    is_public=sym.is_public,
                    owners=_sorted_owners(owners),
                    waived_reason=sym_waiver,
                )
            )

    files.sort(key=lambda f: f.path)
    symbols.sort(key=lambda s: (s.path, s.name, s.kind))
    return CoverageReport(files=tuple(files), symbols=tuple(symbols))


def coverage_snapshot(report: CoverageReport) -> dict:
    """The deterministic, JSON-safe wire shape the server stores + the dashboard reads.

    A PURE (K1), dependency-free (K0) projection of a :class:`CoverageReport` into
    plain JSON-safe primitives (T-02). Carries the full per-file list (so the
    dashboard can render every file documented / undocumented / waived with its
    owning doc ids) PLUS the FILE basket counts and percentages the existing
    coverage view already shows. ``ratio`` = ``percent_public_symbols / 100`` is
    kept for back-compat: ``server/app.py::_compute_status`` reads ``snapshot["ratio"]``
    for ``RepoStatus.coverage_ratio``. Output is deterministic (K10): ``report.files``
    is already path-sorted and ``owners`` is sorted + deduped upstream.
    """
    return {
        "schema_version": "1.0.0",
        "percent_files": report.percent_files,
        "percent_public_symbols": report.percent_public_symbols,
        "ratio": report.percent_public_symbols / 100,
        "documented": len(report.documented_files),
        "undocumented": len(report.undocumented_files),
        "waived": len(report.waived_files),
        "files": [
            {
                "path": f.path,
                "language": f.language,
                "owners": list(f.owners),
                "status": (
                    "documented"
                    if f.owners
                    else ("waived" if f.waived_reason else "undocumented")
                ),
                "waived_reason": f.waived_reason,
            }
            for f in report.files
        ],
    }


class OwnerSuggestion(BaseModel):
    """A deterministic gap→owner suggestion (A-07).

    Emitted for each PUBLIC, unowned, non-waived symbol gap. ``suggested_doc_id``
    is either an **existing** doc id (when that doc already owns a sibling symbol
    in the same file) or a **proposed new** doc id derived from the file path
    (when the file is entirely unowned). ``name`` is the gap symbol's name; the
    ``None`` shape (a whole-file suggestion) is defined but not currently emitted
    for symbol gaps.
    """

    model_config = _MODEL_CONFIG

    path: str  # the gap's file path
    name: str | None  # symbol name; None == whole-file suggestion
    suggested_doc_id: str  # an existing doc id, or a proposed new one
    is_new_doc: bool  # True => suggested_doc_id is a proposal
    reason: str  # why this owner was suggested


def _proposed_doc_id(path: str) -> str:
    """Derive a new doc id from a file path (A-07 scheme; deterministic, K10).

    ``pkg/sub/mod.py`` -> ``pkg-sub-mod``: drop a ``.py``/``.pyi`` suffix, then
    replace path separators with ``-``. The full path keeps ids unique across
    same-named modules in different packages and yields a filesystem/id-safe
    token.
    """
    stem = path
    for suffix in (".pyi", ".py"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem.replace("/", "-")


def suggest_owners(
    report: CoverageReport, config: MonitorConfig
) -> tuple[OwnerSuggestion, ...]:
    """Suggest a deterministic owner for every public symbol gap (A-07).

    A PURE, deterministic heuristic (Decision 1: NOT routed through the
    ``Backend`` Protocol — no LLM, no I/O, no new dependency; K0/K10). Only
    :attr:`CoverageReport.undocumented_symbols` (public, unowned, non-waived) are
    considered — private and waived gaps are never suggested.

    For each gap's file:

    * **Sibling-owned** — if any document already owns *another* symbol in that
      file, suggest the **lowest** such doc id, ``is_new_doc=False``.
    * **Fully-unowned** — else, propose a new doc id via :func:`_proposed_doc_id`,
      grouping all of that file's gaps under it, ``is_new_doc=True``.

    Output is sorted by ``(path, name)`` (K10). ``config`` is accepted for
    symmetry with :func:`resolve_coverage` and future config-driven naming; the
    current heuristic derives everything from ``report``.
    """
    _ = config  # reserved for future config-driven naming; heuristic uses report
    # Per file: the sorted set of doc ids that own at least one symbol there.
    owners_by_file: dict[str, list[str]] = {}
    for sym in report.symbols:
        if sym.owners:
            owners_by_file.setdefault(sym.path, [])
            for doc_id in sym.owners:
                if doc_id not in owners_by_file[sym.path]:
                    owners_by_file[sym.path].append(doc_id)

    suggestions: list[OwnerSuggestion] = []
    for sym in report.undocumented_symbols:
        sibling_owners = owners_by_file.get(sym.path, [])
        if sibling_owners:
            suggested = min(sibling_owners)
            suggestions.append(
                OwnerSuggestion(
                    path=sym.path,
                    name=sym.name,
                    suggested_doc_id=suggested,
                    is_new_doc=False,
                    reason=f"sibling symbols already in {suggested}",
                )
            )
        else:
            suggestions.append(
                OwnerSuggestion(
                    path=sym.path,
                    name=sym.name,
                    suggested_doc_id=_proposed_doc_id(sym.path),
                    is_new_doc=True,
                    reason=f"no doc references {sym.path}",
                )
            )

    suggestions.sort(key=lambda s: (s.path, s.name or ""))
    return tuple(suggestions)
