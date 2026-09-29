"""The persisted code-side index (EPIC CIX, CIX-01 — K1/K6/K7/K8/K10).

Everything under ``.cdmon/`` today is doc-side or join-side; the code surface
is recomputed on every run and thrown away. This module persists it:
``.cdmon/code-index.json`` holds every file in the COVERAGE universe (the
exact ``cdx coverage`` scan — :func:`~custodex.inventory.discover_files` over
``coverage.include``/``exclude``, so index scope can never diverge from
coverage scope, K0) with a content digest, and every extracted symbol with
its span and per-tier digests (signature / docstring / body). That makes the
surface *diffable*: :func:`diff_code_index` attributes a tree change to the
exact symbols that moved, per tier — the input for surgical doc updates
instead of full re-extractions.

Two contracts, pinned in ``ARCHITECTURE §EPIC CIX``:

* **The index is a projection, never a truth (⟨R⟩1).** It is regenerable from
  the tree at any time; deleting it changes no behavior anywhere.
* **Stamps are provenance, never identity (⟨R⟩2).** ``generated_by`` and
  ``source_sha`` ride ON the artifact but enter no digest and no comparison:
  :func:`write_code_index` compares ``files`` content only, so an unchanged
  tree writes zero bytes (K7) and the surviving ``source_sha`` reads "content
  unchanged since" (the ``index.yaml`` ``updated:``/N-06 analog). No
  wall-clock and no absolute path anywhere in the artifact (K10 — the
  inventory's absolute ``root`` deliberately does not cross into it).

The module is pure except the ONE isolated writer, called only by
``cdx codeindex --write`` — never by ``check`` (K1). Digests follow the
``sha256[:16]`` convention of ``extract.py``; ``sig_digest`` reuses
``extract._hash_payload`` so it is byte-identical to the DIG-01
``cdm.symbol_sigs`` values (one identity scheme, never two).
"""

from __future__ import annotations

import hashlib
import posixpath
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from . import __version__
from .config import MonitorConfig
from .errors import ExtractionError, SchemaError
from .extract import _hash_payload
from .inventory import (
    CodeFile,
    FileSymbols,
    Inventory,
    discover_files,
    discover_symbols,
)

if TYPE_CHECKING:  # imported for typing only — scip.py imports this module
    from .scip import XrefSet

__all__ = [
    "CODE_INDEX_PATH",
    "GENERATED_BY",
    "UNREADABLE_DIGEST",
    "CodeIndex",
    "CodeIndexDiff",
    "DocImpact",
    "FileDelta",
    "ImpactReport",
    "IndexedFile",
    "IndexedSymbol",
    "build_code_index",
    "diff_code_index",
    "file_digests",
    "impact_report",
    "index_in_sync",
    "read_code_index",
    "stale_paths",
    "unsynced_paths",
    "write_code_index",
]

# Frozen + extra="forbid": the index is an immutable, normalized snapshot (K10).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

#: The artifact, beside the review/resolutions logs (config_dir-anchored,
#: the ``graph.json`` precedent).
CODE_INDEX_PATH = Path(".cdmon") / "code-index.json"

#: The producer stamp written into new artifacts (provenance, never identity).
GENERATED_BY = f"custodex/{__version__}"

#: The :func:`file_digests` digest of a coverage file that could not be read
#: (a dangling symlink, a permission error). Not hex, so it never equals a
#: real ``sha256[:16]``: the file reads as STALE / "caller data unknown"
#: instead of aborting a read-only check (a semantic constant, not a knob).
UNREADABLE_DIGEST = "unreadable"


def _digest(data: bytes) -> str:
    """The repo-wide ``sha256[:16]`` digest convention (extract.py:112)."""
    return hashlib.sha256(data).hexdigest()[:16]


class IndexedSymbol(BaseModel):
    """One symbol: span + per-tier digests (never the raw docstring/body)."""

    model_config = _MODEL_CONFIG

    name: str
    kind: str
    signature: str
    lineno: int
    end_lineno: int
    is_public: bool
    #: ``extract.anchor_id(name)`` — the lineno-free identity (P4).
    anchor: str
    #: ``_hash_payload({name, kind, signature, is_public})`` — byte-identical
    #: to the DIG-01 ``cdm.symbol_sigs`` value for this symbol.
    sig_digest: str
    #: ``sha256[:16]`` of the docstring; ``None`` when the symbol has none.
    doc_digest: str | None = None
    #: ``Symbol.body_hash`` carried through (``None`` for class/variable).
    body_digest: str | None = None


class IndexedFile(BaseModel):
    """One file in the coverage universe: content digest + its symbols."""

    model_config = _MODEL_CONFIG

    path: str  # repo-relative POSIX (inventory convention)
    language: str
    #: ``sha256[:16]`` of the file BYTES — content, never mtime (SP-RF1).
    content_digest: str
    symbols: tuple[IndexedSymbol, ...]  # sorted (name, lineno) (K10)


class CodeIndex(BaseModel):
    """The versioned artifact (additive schema — K6)."""

    model_config = _MODEL_CONFIG

    schema_version: str = "1.0.0"
    generated_by: str
    #: Injected provenance (``--ref`` / ``$CI_COMMIT_SHA``); NEVER hashed or
    #: compared — reads "content unchanged since this SHA" (⟨R⟩2).
    source_sha: str | None = None
    files: tuple[IndexedFile, ...]  # sorted by path (K10)


class FileDelta(BaseModel):
    """One changed file; symbol names sorted per bucket (K10).

    A ``modified`` delta with every bucket empty is honest information: the
    file's bytes moved but its extracted surface did not (a comment or
    formatting change).
    """

    model_config = _MODEL_CONFIG

    path: str
    status: Literal["added", "removed", "modified"]
    symbols_added: tuple[str, ...] = ()
    symbols_removed: tuple[str, ...] = ()
    sigs_changed: tuple[str, ...] = ()
    docs_changed: tuple[str, ...] = ()
    bodies_changed: tuple[str, ...] = ()


class CodeIndexDiff(BaseModel):
    """Every file-level delta between two indexes (empty tuple = in sync)."""

    model_config = _MODEL_CONFIG

    files: tuple[FileDelta, ...]  # only files with a delta, sorted by path


def _coverage_inventory(config: MonitorConfig, root: Path) -> Inventory:
    """The ONE scan both the index and the currency listing fold (⟨R⟩1)."""
    return discover_files(
        root, include=config.coverage.include, exclude=config.coverage.exclude
    )


def _file_symbols(inv: Inventory, code_file: CodeFile, root: Path) -> FileSymbols:
    """``discover_symbols`` for ONE file, every extraction failure typed (K8).

    The extractor types the parser's SyntaxError, but two ValueErrors
    escape it untyped: Python 3.10's parser (the supported floor) raises
    one for a NUL byte, and a file that PARSES can still fail rendering —
    ``ast.unparse`` of a hex literal past the int-to-str digit limit
    (Python 3.11+, 3.10.7+) raises one. Either would escape `cdx
    codeindex`/`impact` as a traceback and bypass `cdx scip`'s content
    fallback. One file at a time, so the error names it.
    """
    try:
        (entry,) = discover_symbols(
            inv.model_copy(update={"files": (code_file,)}), root
        ).files
    except ValueError as exc:
        raise ExtractionError(
            f"Cannot extract code reference {code_file.path}: {exc}"
        ) from exc
    return entry


def build_code_index(
    config: MonitorConfig,
    root: Path,
    *,
    generated_by: str = GENERATED_BY,
    source_sha: str | None = None,
) -> CodeIndex:
    """Fold the coverage universe into a :class:`CodeIndex` (pure, K10).

    The scan is EXACTLY the ``cdx coverage`` inventory —
    ``discover_files(root, include=config.coverage.include,
    exclude=config.coverage.exclude)`` + ``discover_symbols`` — so the index
    universe never diverges from the coverage universe (⟨R⟩1). Symbol
    extraction failures propagate as the extractor's own typed errors (an
    extraction ValueError too — see :func:`_file_symbols`), and a file whose
    bytes cannot be read (a dangling symlink, a permission error — including
    a file no extractor opens) is the same typed
    :class:`~custodex.errors.ExtractionError` (K8), never a bare OSError.
    """
    inv = _coverage_inventory(config, root)
    files: list[IndexedFile] = []
    for code_file in inv.files:
        file_symbols = _file_symbols(inv, code_file, root)
        try:
            raw = (root / file_symbols.path).read_bytes()
        except OSError as exc:
            raise ExtractionError(
                f"Cannot read code reference {file_symbols.path}: {exc}"
            ) from exc
        symbols = tuple(
            IndexedSymbol(
                name=s.name,
                kind=s.kind,
                signature=s.signature,
                lineno=s.lineno,
                end_lineno=s.end_lineno,
                is_public=s.is_public,
                anchor=s.anchor_id,
                sig_digest=_hash_payload(
                    {
                        "name": s.name,
                        "kind": s.kind,
                        "signature": s.signature,
                        "is_public": s.is_public,
                    }
                ),
                doc_digest=(
                    None
                    if s.docstring is None
                    else _digest(s.docstring.encode("utf-8"))
                ),
                body_digest=s.body_hash,
            )
            for s in sorted(file_symbols.symbols, key=lambda s: (s.name, s.lineno))
        )
        files.append(
            IndexedFile(
                path=file_symbols.path,
                language=file_symbols.language,
                content_digest=_digest(raw),
                symbols=symbols,
            )
        )
    files.sort(key=lambda f: f.path)
    return CodeIndex(
        generated_by=generated_by, source_sha=source_sha, files=tuple(files)
    )


def file_digests(config: MonitorConfig, root: Path) -> dict[str, tuple[str, str]]:
    """``path → (language, content_digest)`` over the coverage universe (pure).

    The cheap currency listing: the SAME scan and the SAME digest as
    :func:`build_code_index` (so it equals the ``(language, content_digest)``
    projection of a fresh index) but no symbol extraction — what a consumer
    needs to judge an xrefs input pin against the tree
    (:func:`~custodex.scip.unknown_caller_files`). Sorted by path (K10).

    TOTAL over the scan, like ``entities.build_registry``: a file that cannot
    be read (a dangling symlink such as an editor lock file, a permission
    error) is listed with :data:`UNREADABLE_DIGEST`, so it reads as STALE /
    "caller data unknown" and never aborts `cdx graph` or `cdx scip`.
    """
    listing: dict[str, tuple[str, str]] = {}
    for f in _coverage_inventory(config, root).files:
        try:
            digest = _digest((root / f.path).read_bytes())
        except OSError:
            digest = UNREADABLE_DIGEST
        listing[f.path] = (f.language, digest)
    return listing


def _projection(index: CodeIndex) -> dict[str, tuple[str, str]]:
    """``path → (language, content_digest)`` — the :func:`file_digests` shape."""
    return {f.path: (f.language, f.content_digest) for f in index.files}


def stale_paths(
    index: CodeIndex, listing: Mapping[str, tuple[str, str]]
) -> tuple[str, ...]:
    """Files where ``index`` disagrees with a tree ``listing`` (pure, sorted).

    ``listing`` is :func:`file_digests` over the tree: a path is stale when
    it was changed, added or removed since the index was built. ``()`` =
    the index's content matches the tree. The cheap, extraction-free check
    behind ``cdx scip``'s STALE warning when the tree cannot be extracted
    (otherwise :func:`unsynced_paths` against a fresh build is the exact
    check) — it never needs to parse the tree, so an unparseable file is
    named, not a verification failure.
    """
    indexed = _projection(index)
    return tuple(
        sorted(
            path
            for path in indexed.keys() | listing.keys()
            if indexed.get(path) != listing.get(path)
        )
    )


def unsynced_paths(stored: CodeIndex, current: CodeIndex) -> tuple[str, ...]:
    """Files whose WHOLE entry differs between two indexes (pure, sorted).

    :func:`index_in_sync` per file: added, removed, or any field of the
    entry — symbols and spans over identical bytes included, not just
    ``content_digest``. ``()`` = the file entries agree.
    ``cdx scip`` names these in its STALE warning when a fresh build of the
    tree is possible (the exact form of :func:`stale_paths`).
    """
    before = {f.path: f for f in stored.files}
    after = {f.path: f for f in current.files}
    return tuple(
        sorted(
            path
            for path in before.keys() | after.keys()
            if before.get(path) != after.get(path)
        )
    )


def index_in_sync(stored: CodeIndex, current: CodeIndex) -> bool:
    """The stamp-blind content compare (⟨R⟩2) — ``schema_version`` + ``files``.

    The one definition of "the stored index matches a rebuild": backs
    :func:`write_code_index`'s skip and ``cdx codeindex --check``.
    ``generated_by``/``source_sha`` never enter it.
    """
    return (
        stored.schema_version == current.schema_version
        and stored.files == current.files
    )


def read_code_index(cdmon_dir: Path) -> CodeIndex | None:
    """Read the stored index (missing file ⇒ ``None``; corrupt ⇒ loud, K8)."""
    path = cdmon_dir / CODE_INDEX_PATH.name
    if not path.is_file():
        return None
    try:
        return CodeIndex.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, ValueError) as exc:
        raise SchemaError(f"corrupt code index {path}: {exc}") from exc


def write_code_index(index: CodeIndex, cdmon_dir: Path) -> bool:
    """The module's ONE impure function — the stamp-blind idempotent writer.

    Compares ``schema_version`` + ``files`` only (⟨R⟩2): identical content
    under a new ``source_sha``/``generated_by`` writes nothing and the stored
    stamp survives as "content unchanged since". A corrupt existing artifact
    is replaced, not raised — the artifact is regenerable by contract (⟨R⟩1);
    loud corruption errors belong to the read path. Returns ``True`` iff
    bytes were written (K7).
    """
    path = cdmon_dir / CODE_INDEX_PATH.name
    if path.is_file():
        try:
            existing = CodeIndex.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, ValueError):
            existing = None
        if existing is not None and index_in_sync(existing, index):
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(index.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return True


def _names(symbols: tuple[IndexedSymbol, ...]) -> tuple[str, ...]:
    """Distinct symbol names, sorted (a name can repeat across linenos)."""
    return tuple(sorted({s.name for s in symbols}))


def _grouped(symbols: tuple[IndexedSymbol, ...]) -> dict[str, list[IndexedSymbol]]:
    """name → occurrences (input already (name, lineno)-sorted, K10)."""
    out: dict[str, list[IndexedSymbol]] = {}
    for sym in symbols:
        out.setdefault(sym.name, []).append(sym)
    return out


def _file_delta(old: IndexedFile, new: IndexedFile) -> FileDelta:
    """Per-symbol tier attribution for one modified file (pure, sorted).

    A qualified name can legitimately repeat in one file (`typing.overload`
    stacks, try/except fallback defs) — comparison is per-name DIGEST
    MULTISETS, so a change to ANY duplicate occurrence flags the name
    (adversarial-review finding: a name-keyed dict silently kept only the
    last occurrence, reporting a breaking overload change as cosmetic).
    """
    old_by = _grouped(old.symbols)
    new_by = _grouped(new.symbols)
    sigs: list[str] = []
    docs: list[str] = []
    bodies: list[str] = []
    for name in sorted(old_by.keys() & new_by.keys()):
        a, b = old_by[name], new_by[name]
        if sorted(s.sig_digest for s in a) != sorted(s.sig_digest for s in b):
            sigs.append(name)
        if sorted(s.doc_digest or "" for s in a) != sorted(
            s.doc_digest or "" for s in b
        ):
            docs.append(name)
        if sorted(s.body_digest or "" for s in a) != sorted(
            s.body_digest or "" for s in b
        ):
            bodies.append(name)
    return FileDelta(
        path=new.path,
        status="modified",
        symbols_added=tuple(sorted(new_by.keys() - old_by.keys())),
        symbols_removed=tuple(sorted(old_by.keys() - new_by.keys())),
        sigs_changed=tuple(sigs),
        docs_changed=tuple(docs),
        bodies_changed=tuple(bodies),
    )


def diff_code_index(old: CodeIndex, new: CodeIndex) -> CodeIndexDiff:
    """Attribute every change between two indexes to files and symbols.

    Pure and sorted (K10). ``content_digest`` equality short-circuits an
    unchanged file — the SP-RF1 rule: the skip key is content, never
    metadata.
    """
    old_by = {f.path: f for f in old.files}
    new_by = {f.path: f for f in new.files}
    deltas: list[FileDelta] = []
    for path in sorted(old_by.keys() | new_by.keys()):
        before = old_by.get(path)
        after = new_by.get(path)
        if before is None:
            assert after is not None  # membership of the union
            deltas.append(
                FileDelta(
                    path=path, status="added", symbols_added=_names(after.symbols)
                )
            )
        elif after is None:
            deltas.append(
                FileDelta(
                    path=path, status="removed", symbols_removed=_names(before.symbols)
                )
            )
        elif before.content_digest != after.content_digest:
            deltas.append(_file_delta(before, after))
    return CodeIndexDiff(files=tuple(deltas))


# ------------------------------------------------- CIX-03: the impact join


class DocImpact(BaseModel):
    """One affected document: which changed symbols reach it, and how."""

    model_config = _MODEL_CONFIG

    doc_id: str
    #: Changed symbols this doc covers (entity ids, sorted).
    direct: tuple[str, ...] = ()
    #: Changed symbols reaching this doc through ONE xref hop: the doc covers
    #: a CALLER of the changed symbol (entity ids of the changed symbols).
    via_callers: tuple[str, ...] = ()


class ImpactReport(BaseModel):
    """The diff→docs surgical join (pure, sorted — K10)."""

    model_config = _MODEL_CONFIG

    deltas: tuple[FileDelta, ...]
    docs: tuple[DocImpact, ...]  # sorted by doc_id
    #: True only when ``via_callers`` is backed by CURRENT xrefs: an artifact
    #: was supplied, it carries an input pin, the pin matches the stored
    #: baseline for every covered file, and the diff modifies no covered
    #: file. False otherwise — missing callers are then ABSENCE OF DATA,
    #: never absence of callers (the honesty flag).
    callers_available: bool
    #: Files whose caller data the xrefs cannot vouch for — covered-language
    #: files changed, added or removed in the baseline since the xrefs join,
    #: plus EVERY covered file this diff modifies: its outgoing references
    #: are not in the stored xrefs (``scip.unknown_caller_files``). Listed
    #: whether or not a reference actually changed. Sorted (K10); additive
    #: (K6).
    callers_unknown: tuple[str, ...] = ()


def _changed_entity_ids(diff: CodeIndexDiff) -> tuple[str, ...]:
    """Every changed symbol as an entity id (added/removed/tier buckets)."""
    ids: set[str] = set()
    for delta in diff.files:
        for name in (
            *delta.symbols_added,
            *delta.symbols_removed,
            *delta.sigs_changed,
            *delta.docs_changed,
            *delta.bodies_changed,
        ):
            ids.add(f"symbol {delta.path}#{name}")
    return tuple(sorted(ids))


def impact_report(
    config: MonitorConfig,
    root: Path,
    stored: CodeIndex,
    current: CodeIndex,
    xrefs: XrefSet | None,
) -> ImpactReport:
    """Join a code-index diff to the docs it affects (pure — K1/K10).

    ``direct``: the doc covers the changed symbol itself — surviving symbols
    join through :func:`docmap.symbol_owners` (public entity universe);
    added/removed symbols fall back to a file-level join (any doc whose
    ``code_refs`` name the file), because selection-aware attribution needs a
    surface that no longer (or does not yet) exist. ``via_callers``: the doc
    covers a CALLER of the changed symbol — one xref hop, never transitive
    (the ``deps --transitive`` advisory precedent; a closure belongs to a
    later slice).

    Caller currency is judged against ``stored`` — the baseline the diff
    starts from: a pin that lags the baseline (the index refreshed, the
    indexer not re-run) lists the lagging files in ``callers_unknown`` and
    clears ``callers_available``. EVERY file the diff modifies is listed
    too, whatever the edit: the stored xrefs were joined before it, so its
    outgoing references are not in them — a new call can land anywhere
    (a body, a class field, a decorator, an import, a type parameter) and
    no stored fact can say whether one did. No edit is exempted by
    reasoning about which symbol digest moved: that is a precision claim
    over data the xrefs do not hold. Over-reporting an edit that adds no
    reference is the accepted cost; the file stays unknown until the
    change lands and the xrefs are re-joined against it. An ADDED file is
    not an edit of this kind: it can source edges only from its own
    symbols, all in ``symbols_added``, so the doc covering such a caller is
    already ``direct`` through the same owners join; a removed file's
    symbols reach no current doc.
    """
    from .docmap import symbol_owners  # local: docmap is heavier than needed here
    from .scip import unknown_caller_files  # local: scip imports this module

    diff = diff_code_index(stored, current)
    changed = _changed_entity_ids(diff)
    owners = symbol_owners(config, root)
    file_docs: dict[str, set[str]] = {}
    for spec in config.documents:
        for ref in spec.code_refs:
            file_docs.setdefault(posixpath.normpath(ref.path), set()).add(spec.id)
    # The file-level fallback is for symbols the owners join CANNOT see
    # because they no longer (or do not yet) exist — added/removed ONLY.
    # A surviving symbol absent from the owners map is PRIVATE, and private
    # changes must never fabricate direct doc impact (adversarial-review
    # finding; the docmap public-universe contract).
    added_removed = {
        f"symbol {delta.path}#{name}"
        for delta in diff.files
        for name in (*delta.symbols_added, *delta.symbols_removed)
    }

    direct: dict[str, set[str]] = {}
    for entity_id in changed:
        path = entity_id.split(" ", 1)[1].split("#", 1)[0]
        doc_ids = owners.get(entity_id)
        if doc_ids is None:
            doc_ids = (
                file_docs.get(path, set()) if entity_id in added_removed else set()
            )
        for doc_id in doc_ids:
            direct.setdefault(doc_id, set()).add(entity_id)

    via: dict[str, set[str]] = {}
    if xrefs is not None:
        changed_set = set(changed)
        for edge in xrefs.edges:
            if edge.target not in changed_set:
                continue
            for doc_id in owners.get(edge.source, set()):
                via.setdefault(doc_id, set()).add(edge.target)

    docs = tuple(
        DocImpact(
            doc_id=doc_id,
            direct=tuple(sorted(direct.get(doc_id, ()))),
            via_callers=tuple(sorted(via.get(doc_id, ()))),
        )
        for doc_id in sorted(direct.keys() | via.keys())
    )
    unknown = (
        None
        if xrefs is None
        else unknown_caller_files(
            xrefs,
            _projection(stored),
            edited=[d.path for d in diff.files if d.status == "modified"],
        )
    )
    return ImpactReport(
        deltas=diff.files,
        docs=docs,
        callers_available=unknown == (),
        callers_unknown=unknown or (),
    )
