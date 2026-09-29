"""The stdlib SCIP reader → symbol↔symbol reference edges (EPIC CIX, CIX-02).

SCIP is a CONSUMED format, never a dependency (⟨R⟩3, pinned in
``ARCHITECTURE §EPIC CIX``): a human runs an indexer (scip-python et al.) and
hands the ``.scip`` file to ``cdx scip`` (K11 — custodex never shells out to
an indexer). This module decodes the protobuf wire format with the standard
library alone — varints and LEN walking, packed AND unpacked repeated int32,
the deprecated ``range``/``enclosing_range`` fields AND the typed range
fields 8–11 (typed wins when both are present) — no ``protobuf`` package
(K0). Malformed wire bytes raise a typed :class:`ExtractionError` (K8);
individually odd SYMBOLS (locals, parameters, unresolvable targets) are
data, not errors — they tally into ``XrefSet.unmapped``, the honesty
counter.

The projection joins the EXISTING entity universe — edges mint the id scheme
``symbol <posix-path>#<Class.method>`` (entities.py) with PUBLIC endpoints
only, so REFERENCES edges land on the same nodes DOCUMENTS/MENTIONS edges
already touch. Reference attribution is span containment: a reference
occurrence in document D belongs to the narrowest code-index symbol span in
D that contains it (scip-python emits ``enclosing_range`` only on
definitions, never ``enclosing_symbol``). The per-language ``coverage`` map
records which languages actually have reference data, so an absent edge is
never misread as an absent call.

Stamps are provenance, never identity (⟨R⟩2): the idempotent writer compares
content only (K7); no wall-clock, no absolute path, sorted everywhere (K10).

The INPUT PIN is content, not a stamp: ``XrefSet.input_digests`` records the
code-index ``content_digest`` of every file the join could vouch for — never
a file whose index spans disagree with the tree at join time — and
``input_languages`` the languages it speaks for. Both enter the writer's
compare, so a re-run with identical inputs writes nothing, while a re-join
against changed code re-pins. Consumers (``cdx impact``/``graph``) compare
the pin to the code they read the edges against
(:func:`unknown_caller_files`) and say "caller data unknown for N file(s)"
instead of presenting stale edges as complete (⟨R⟩3's honesty contract).
"""

from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping
from pathlib import Path
from string import ascii_letters, digits
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, ValidationError

from .codeindex import GENERATED_BY, CodeIndex, IndexedFile, IndexedSymbol
from .errors import ExtractionError, SchemaError

__all__ = [
    "IMPACT_REMEDY",
    "XREFS_PATH",
    "ScipDocument",
    "ScipIndex",
    "ScipOccurrence",
    "XrefEdge",
    "XrefSet",
    "build_xrefs",
    "caller_currency_note",
    "read_scip",
    "read_xrefs",
    "scip_symbol_to_dotted",
    "unknown_caller_files",
    "write_xrefs",
]

# Frozen + extra="forbid": decoded snapshots are immutable (K10).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

#: The artifact, beside the code index (config_dir-anchored).
XREFS_PATH = Path(".cdmon") / "xrefs.json"

#: SymbolRole bit: definition occurrences are attribution anchors, not refs.
_ROLE_DEFINITION = 0x1

#: The provenance stamps — the ONLY fields the idempotent writer ignores
#: (⟨R⟩2); every other field, the input pin included, is content (K7).
_STAMPS = frozenset({"generated_by", "source_sha"})


class ScipOccurrence(BaseModel):
    """One decoded occurrence, range normalized to 4 ints (0-based, half-open)."""

    model_config = _MODEL_CONFIG

    symbol: str
    roles: int
    start_line: int
    start_char: int
    end_line: int
    end_char: int


class ScipDocument(BaseModel):
    """One decoded document (an indexed source file)."""

    model_config = _MODEL_CONFIG

    relative_path: str
    language: str
    occurrences: tuple[ScipOccurrence, ...]


class ScipIndex(BaseModel):
    """The decoded subset of a SCIP index custodex consumes."""

    model_config = _MODEL_CONFIG

    tool_name: str
    tool_version: str
    project_root: str
    documents: tuple[ScipDocument, ...]


class XrefEdge(BaseModel):
    """One symbol→symbol reference edge in the entity id scheme."""

    model_config = _MODEL_CONFIG

    source: str  # "symbol <path>#<name>" — the referencing symbol
    target: str  # "symbol <path>#<name>" — the referenced symbol
    count: int  # occurrence tally (provenance weight, never a float)


class XrefSet(BaseModel):
    """The versioned xrefs artifact (additive schema — K6)."""

    model_config = _MODEL_CONFIG

    schema_version: str = "1.0.0"
    generated_by: str
    tool: str  # "<tool_name>/<tool_version>" — which indexer produced the facts
    #: Injected provenance; NEVER hashed or compared (⟨R⟩2).
    source_sha: str | None = None
    #: language → producer — the honesty map: absent language = no reference
    #: data, NOT no references.
    coverage: dict[str, str]
    #: Reference occurrences whose TARGET did not resolve to an indexed
    #: public symbol (out-of-universe imports, stdlib, renames) — the honesty
    #: counter.
    unmapped: int
    edges: tuple[XrefEdge, ...]  # sorted (source, target) (K10)
    #: Reference occurrences whose TARGET resolved to a public symbol but
    #: whose SOURCE could not be attributed to a public symbol: it lies inside
    #: no indexed symbol span (module-level code, or code-index spans stale
    #: against the .scip), or — in a file whose index entry disagreed with
    #: the tree (unvouched) — inside a private span or its own target's span,
    #: which a stale span cannot tell apart from design. The attribution drop
    #: counter (additive, K6).
    unattributed: int = 0
    #: The INPUT PIN (content, never a stamp — it enters the writer's
    #: compare): ``path → content_digest`` of every code-index file this join
    #: can vouch for — each file a SCIP document joined, plus each
    #: same-language file with no public symbol (it can source no edge) —
    #: EXCEPT a file whose index entry disagreed with the tree at join time
    #: (its spans may have dropped the refs). ``None`` = an artifact written
    #: before the pin existed: currency unknown. Sorted by path (K10).
    input_digests: dict[str, str] | None = None
    #: The code-index languages of the files a SCIP document joined — the
    #: languages the pin speaks for, recorded at build time so a consumer
    #: never re-derives them from pinned paths that may have moved. Sorted
    #: (K10); ``()`` = no document joined, so the pin vouches for nothing.
    input_languages: tuple[str, ...] = ()


# --------------------------------------------------------------- wire decode


class _Field(NamedTuple):
    number: int
    wire_type: int
    value: int | bytes


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ExtractionError("truncated varint in SCIP index")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 70:
            raise ExtractionError("oversized varint in SCIP index")


def _fields(buf: bytes) -> Iterator[_Field]:
    """Walk one message's fields; unknown fields are the caller's to skip."""
    pos = 0
    while pos < len(buf):
        tag, pos = _read_varint(buf, pos)
        number, wire_type = tag >> 3, tag & 0x7
        if wire_type == 0:
            value, pos = _read_varint(buf, pos)
            yield _Field(number, 0, value)
        elif wire_type == 2:
            length, pos = _read_varint(buf, pos)
            if pos + length > len(buf):
                raise ExtractionError("truncated LEN field in SCIP index")
            yield _Field(number, 2, buf[pos : pos + length])
            pos += length
        elif wire_type == 1:
            if pos + 8 > len(buf):
                raise ExtractionError("truncated I64 field in SCIP index")
            yield _Field(number, 1, buf[pos : pos + 8])
            pos += 8
        elif wire_type == 5:
            if pos + 4 > len(buf):
                raise ExtractionError("truncated I32 field in SCIP index")
            yield _Field(number, 5, buf[pos : pos + 4])
            pos += 4
        else:
            raise ExtractionError(
                f"unsupported protobuf wire type {wire_type} in SCIP index"
            )


def _packed_ints(value: int | bytes) -> list[int]:
    """A packed repeated int32 payload OR one unpacked element."""
    if isinstance(value, int):
        return [value]
    out: list[int] = []
    pos = 0
    while pos < len(value):
        item, pos = _read_varint(value, pos)
        out.append(item)
    return out


def _bytes_str(value: int | bytes, what: str) -> str:
    if not isinstance(value, bytes):
        raise ExtractionError(f"malformed {what} in SCIP index")
    return value.decode("utf-8", errors="replace")


def _normalize_range(raw: list[int]) -> tuple[int, int, int, int]:
    """3 elements = [line, start, end] (single-line); 4 = [sl, sc, el, ec]."""
    if len(raw) == 3:
        return raw[0], raw[1], raw[0], raw[2]
    if len(raw) == 4:
        return raw[0], raw[1], raw[2], raw[3]
    raise ExtractionError(
        f"SCIP occurrence range must have 3 or 4 elements, got {len(raw)}"
    )


def _decode_typed_range(buf: bytes, *, multi_line: bool) -> tuple[int, int, int, int]:
    """SingleLineRange{line=1,start=2,end=3} / MultiLineRange{1..4}."""
    values = {f.number: f.value for f in _fields(buf) if f.wire_type == 0}
    ints = {k: v for k, v in values.items() if isinstance(v, int)}
    if multi_line:
        return ints.get(1, 0), ints.get(2, 0), ints.get(3, 0), ints.get(4, 0)
    line = ints.get(1, 0)
    return line, ints.get(2, 0), line, ints.get(3, 0)


def _decode_occurrence(buf: bytes) -> ScipOccurrence | None:
    symbol = ""
    roles = 0
    deprecated_range: list[int] = []
    typed: tuple[int, int, int, int] | None = None
    for field in _fields(buf):
        if field.number == 1:
            deprecated_range.extend(_packed_ints(field.value))
        elif field.number == 2 and field.wire_type == 2:
            symbol = _bytes_str(field.value, "occurrence symbol")
        elif (
            field.number == 3 and field.wire_type == 0 and isinstance(field.value, int)
        ):
            roles = field.value
        elif field.number == 8 and field.wire_type == 2:
            assert isinstance(field.value, bytes)
            typed = _decode_typed_range(field.value, multi_line=False)
        elif field.number == 9 and field.wire_type == 2:
            assert isinstance(field.value, bytes)
            typed = _decode_typed_range(field.value, multi_line=True)
        # enclosing_range (7) / typed enclosing (10, 11) / the rest: skipped —
        # attribution is span containment against the code index (⟨R⟩3).
    if not symbol:
        return None
    if typed is not None:
        sl, sc, el, ec = typed  # typed_range takes precedence over range
    elif deprecated_range:
        sl, sc, el, ec = _normalize_range(deprecated_range)
    else:
        return None
    return ScipOccurrence(
        symbol=symbol,
        roles=roles,
        start_line=sl,
        start_char=sc,
        end_line=el,
        end_char=ec,
    )


def _decode_document(buf: bytes) -> ScipDocument:
    relative_path = ""
    language = ""
    occurrences: list[ScipOccurrence] = []
    for field in _fields(buf):
        if field.number == 1 and field.wire_type == 2:
            relative_path = _bytes_str(field.value, "document path")
        elif field.number == 2 and field.wire_type == 2:
            assert isinstance(field.value, bytes)
            occ = _decode_occurrence(field.value)
            if occ is not None:
                occurrences.append(occ)
        elif field.number == 4 and field.wire_type == 2:
            language = _bytes_str(field.value, "document language")
    return ScipDocument(
        relative_path=relative_path,
        language=language,
        occurrences=tuple(occurrences),
    )


def _decode_metadata(buf: bytes) -> tuple[str, str, str]:
    tool_name = ""
    tool_version = ""
    project_root = ""
    for field in _fields(buf):
        if field.number == 2 and field.wire_type == 2:
            assert isinstance(field.value, bytes)
            for sub in _fields(field.value):
                if sub.number == 1 and sub.wire_type == 2:
                    tool_name = _bytes_str(sub.value, "tool name")
                elif sub.number == 2 and sub.wire_type == 2:
                    tool_version = _bytes_str(sub.value, "tool version")
        elif field.number == 3 and field.wire_type == 2:
            project_root = _bytes_str(field.value, "project root")
    return tool_name, tool_version, project_root


def read_scip(path: Path) -> ScipIndex:
    """Decode a SCIP index file (stdlib wire walk; malformed ⇒ loud, K8)."""
    if not path.is_file():
        raise ExtractionError(f"SCIP index not found: {path}")
    raw = path.read_bytes()
    tool_name = ""
    tool_version = ""
    project_root = ""
    documents: list[ScipDocument] = []
    for field in _fields(raw):
        if field.number == 1 and field.wire_type == 2:
            assert isinstance(field.value, bytes)
            tool_name, tool_version, project_root = _decode_metadata(field.value)
        elif field.number == 2 and field.wire_type == 2:
            assert isinstance(field.value, bytes)
            documents.append(_decode_document(field.value))
        # external_symbols (3) and unknown fields: skipped.
    return ScipIndex(
        tool_name=tool_name,
        tool_version=tool_version,
        project_root=project_root,
        documents=tuple(documents),
    )


# ------------------------------------------------------------ symbol grammar

_IDENT_CHARS = frozenset("_+-$" + ascii_letters + digits)

#: Descriptor suffix → does its name join the dotted path?
_JOINING = {"namespace", "type", "term", "method", "meta", "macro"}


def _read_name(symbol: str, pos: int) -> tuple[str, int] | None:
    """One descriptor name: simple identifier or backticked (`` doubled)."""
    if pos < len(symbol) and symbol[pos] == "`":
        pos += 1
        out: list[str] = []
        while pos < len(symbol):
            if symbol[pos] == "`":
                if pos + 1 < len(symbol) and symbol[pos + 1] == "`":
                    out.append("`")
                    pos += 2
                    continue
                return "".join(out), pos + 1
            out.append(symbol[pos])
            pos += 1
        return None  # unterminated backtick
    end = pos
    while end < len(symbol) and symbol[end] in _IDENT_CHARS:
        end += 1
    if end == pos:
        return None
    return symbol[pos:end], end


def _parse_descriptors(descriptors: str) -> list[tuple[str, str]] | None:
    """``[(name, kind), …]`` per the SCIP grammar; ``None`` on malformed."""
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(descriptors):
        char = descriptors[pos]
        if char == "(":  # parameter descriptor: '(' name ')'
            named = _read_name(descriptors, pos + 1)
            if named is None:
                return None
            name, pos = named
            if pos >= len(descriptors) or descriptors[pos] != ")":
                return None
            out.append((name, "parameter"))
            pos += 1
            continue
        if char == "[":  # type-parameter descriptor: '[' name ']'
            named = _read_name(descriptors, pos + 1)
            if named is None:
                return None
            name, pos = named
            if pos >= len(descriptors) or descriptors[pos] != "]":
                return None
            out.append((name, "type_parameter"))
            pos += 1
            continue
        named = _read_name(descriptors, pos)
        if named is None:
            return None
        name, pos = named
        if pos >= len(descriptors):
            return None  # a descriptor always has a suffix
        suffix = descriptors[pos]
        if suffix == "(":  # method: name '(' disambiguator? ').'
            close = descriptors.find(").", pos)
            if close == -1:
                return None
            out.append((name, "method"))
            pos = close + 2
        elif suffix == "/":
            out.append((name, "namespace"))
            pos += 1
        elif suffix == "#":
            out.append((name, "type"))
            pos += 1
        elif suffix == ".":
            out.append((name, "term"))
            pos += 1
        elif suffix == ":":
            out.append((name, "meta"))
            pos += 1
        elif suffix == "!":
            out.append((name, "macro"))
            pos += 1
        else:
            return None
    return out


def _split_prefix(symbol: str, count: int) -> tuple[list[str], str]:
    """Split ``count`` space-separated fields (double space = escaped space)."""
    parts: list[str] = []
    current: list[str] = []
    pos = 0
    while pos < len(symbol) and len(parts) < count:
        char = symbol[pos]
        if char == " ":
            if pos + 1 < len(symbol) and symbol[pos + 1] == " ":
                current.append(" ")
                pos += 2
                continue
            parts.append("".join(current))
            current = []
            pos += 1
            continue
        current.append(char)
        pos += 1
    return parts, symbol[pos:]


def scip_symbol_to_dotted(symbol: str) -> str | None:
    """A global SCIP symbol → Python dotted name (``None`` = not a code fact).

    ``local …`` ids, parameters, type parameters, and malformed symbols map
    to ``None`` — they are data to skip, never errors (the loud path is the
    WIRE, not the symbol grammar). The module marker meta descriptor
    (``__init__:``) is dropped, so a module symbol maps to its dotted module
    name.
    """
    if symbol.startswith("local ") or symbol == "local":
        return None
    parts, descriptors = _split_prefix(symbol, 4)
    if len(parts) < 4 or not descriptors:
        return None
    parsed = _parse_descriptors(descriptors)
    if parsed is None or not parsed:
        return None
    if parsed[-1][1] in ("parameter", "type_parameter"):
        return None
    names = [name for name, kind in parsed if kind in _JOINING]
    if parsed[-1] == ("__init__", "meta"):
        names = names[:-1]  # the module marker, not a symbol
    if not names:
        return None
    return ".".join(names)


# -------------------------------------------------------------- the xref join


def _module_map(index: CodeIndex) -> dict[str, str]:
    """Dotted module name → repo-relative path, from the code index."""
    out: dict[str, str] = {}
    for file in index.files:
        if not file.path.endswith(".py"):
            continue
        module = file.path[: -len(".py")]
        if module.endswith("/__init__"):
            module = module[: -len("/__init__")]
        out[module.replace("/", ".")] = file.path
    return out


def _resolve_module(module: str, module_map: dict[str, str]) -> str | None:
    """Exact match, else a UNIQUE suffix match (the scip-python
    project-root-relative naming quirk: ``src.foo.bar`` vs ``foo.bar``)."""
    path = module_map.get(module)
    if path is not None:
        return path
    candidates = {
        p
        for m, p in module_map.items()
        if module.endswith("." + m) or m.endswith("." + module)
    }
    if len(candidates) == 1:
        return next(iter(candidates))
    return None


def _narrowest_span(
    symbols: tuple[IndexedSymbol, ...], line: int
) -> IndexedSymbol | None:
    """The narrowest symbol span containing 1-based ``line`` (None = toplevel).

    THE attribution rule: :func:`build_xrefs` credits a reference to this
    symbol. A tie (``A = B = x``, a one-line class) goes to the FIRST
    symbol in the index's sorted ``(name, lineno)`` order — never
    extraction order (K10).
    """
    best: IndexedSymbol | None = None
    for sym in symbols:
        if sym.lineno <= line <= sym.end_lineno and (
            best is None
            or (sym.end_lineno - sym.lineno) < (best.end_lineno - best.lineno)
        ):
            best = sym
    return best


def build_xrefs(
    scip: ScipIndex,
    index: CodeIndex,
    *,
    generated_by: str = GENERATED_BY,
    source_sha: str | None = None,
    tree_digests: Mapping[str, tuple[str, str]] | None = None,
    tree_index: CodeIndex | None = None,
) -> XrefSet:
    """Project a decoded SCIP index onto the entity universe (pure, K10).

    ``unmapped`` counts reference occurrences whose TARGET did not resolve to
    an indexed public symbol; module references (imports) are out of scope,
    not failures. ``unattributed`` counts resolved public references whose
    SOURCE position falls inside no indexed span (module-level code, or a
    code index whose spans are stale against the .scip) — counted, never
    silently lost. A private enclosing symbol or a self-edge stays out of
    the universe by design (the private-target symmetry) — in a VOUCHED
    file; in an unvouched one the span may be stale, so those drops are
    counted too. ``input_digests`` pins the code index content the join
    vouches for (see :class:`XrefSet`).

    The vouch — is ``index``'s entry for a file what the tree gives? —
    narrows the pin, never the edges: a file it fails is NOT pinned,
    because references are attributed through the index's spans and stale
    spans silently drop or misattribute them, so every consumer reports it
    "caller data unknown". Two independent checks, each skipped when
    ``None``, and a file must pass every one given:

    * ``tree_index`` — a fresh :func:`~custodex.codeindex.build_code_index`
      of the tree the .scip is presumed to describe: the WHOLE entry must
      be equal (symbols and spans included), so a span drift over
      identical bytes is caught (the exact check).
    * ``tree_digests`` — ``path → (language, content_digest)``
      (:func:`~custodex.codeindex.file_digests`), the extraction-free
      fallback for a tree that does not extract: content only.

    Neither given = the index IS the tree (an in-memory build).
    """
    module_map = _module_map(index)
    files_by_path = {f.path: f for f in index.files}
    fresh = None if tree_index is None else {f.path: f for f in tree_index.files}
    tool = f"{scip.tool_name}/{scip.tool_version}" if scip.tool_name else "unknown"

    def vouched(file: IndexedFile) -> bool:
        """The index entry matches the tree, so its spans are current."""
        return (fresh is None or fresh.get(file.path) == file) and (
            tree_digests is None
            or tree_digests.get(file.path) == (file.language, file.content_digest)
        )

    def resolve_target(dotted: str) -> tuple[str, str] | None:
        """Longest module split whose remainder names an indexed symbol."""
        parts = dotted.split(".")
        for cut in range(len(parts) - 1, 0, -1):
            module = ".".join(parts[:cut])
            path = _resolve_module(module, module_map)
            if path is None:
                continue
            qualname = ".".join(parts[cut:])
            if any(s.name == qualname for s in files_by_path[path].symbols):
                return path, qualname
        return None

    counts: dict[tuple[str, str], int] = {}
    unmapped = 0
    unattributed = 0
    joined: set[str] = set()
    pins: dict[str, str] = {}
    coverage: dict[str, str] = {}
    for document in scip.documents:
        doc_path = document.relative_path
        file = files_by_path.get(doc_path)
        if file is None:
            # The scip run may have used a different root; a unique suffix
            # match recovers it, anything else stays out of the join.
            candidates = [
                p for p in files_by_path if p.endswith("/" + doc_path) or p == doc_path
            ]
            if len(candidates) != 1:
                continue
            doc_path = candidates[0]
            file = files_by_path[doc_path]
        language = document.language or file.language
        coverage.setdefault(language, tool)
        joined.add(doc_path)
        trusted = vouched(file)
        if trusted:
            pins[doc_path] = file.content_digest
        for occ in document.occurrences:
            if occ.roles & _ROLE_DEFINITION:
                continue  # definitions anchor attribution, they are not refs
            dotted = scip_symbol_to_dotted(occ.symbol)
            if dotted is None:
                continue  # locals/parameters — never code-surface facts
            # Symbol resolution FIRST; module classification only on failure.
            # The fuzzy suffix rule exists to recover the scip-python
            # project-root prefix quirk — consulted eagerly it eats real
            # references whose dotted name happens to suffix-match an
            # unrelated module (adversarial-review finding: `app.config` vs
            # a root config.py).
            resolved = resolve_target(dotted)
            if resolved is None:
                if _resolve_module(dotted, module_map) is None:
                    unmapped += 1  # unresolved target — the honesty counter
                continue  # else: a bare module reference (import)
            target_path, target_name = resolved
            target_file = files_by_path[target_path]
            target_sym = next(
                (s for s in target_file.symbols if s.name == target_name), None
            )
            if target_sym is None or not target_sym.is_public:
                continue  # out of the public entity universe by design
            source_sym = _narrowest_span(file.symbols, occ.start_line + 1)
            if source_sym is None:
                unattributed += 1  # no enclosing span — counted, never lost
                continue
            source_id = f"symbol {doc_path}#{source_sym.name}"
            target_id = f"symbol {target_path}#{target_sym.name}"
            if not source_sym.is_public or source_id == target_id:
                # A private context and a self-edge (recursion) are out of
                # the universe BY DESIGN — but only spans that match the
                # tree can say so: in an unvouched file the span may be a
                # stale artefact, so the drop is counted, never lost.
                if not trusted:
                    unattributed += 1
                continue
            counts[(source_id, target_id)] = counts.get((source_id, target_id), 0) + 1

    edges = tuple(
        XrefEdge(source=source, target=target, count=count)
        for (source, target), count in sorted(counts.items())
    )
    # A same-language file with no public symbol can source no edge whatever
    # its references, so its (empty) caller data is KNOWN at this content —
    # pin it too (when vouched); a public-symbol file with no SCIP document
    # stays unpinned (no reference data ⇒ unknown, never "no callers").
    # The languages come from the JOINED documents, vouched or not: a stale
    # file's language is still covered by this run.
    languages = {files_by_path[path].language for path in joined}
    for indexed in index.files:
        if (
            indexed.path not in joined
            and indexed.language in languages
            and not any(s.is_public for s in indexed.symbols)
            and vouched(indexed)
        ):
            pins[indexed.path] = indexed.content_digest
    return XrefSet(
        generated_by=generated_by,
        tool=tool,
        source_sha=source_sha,
        coverage=dict(sorted(coverage.items())),
        unmapped=unmapped,
        edges=edges,
        unattributed=unattributed,
        input_digests=dict(sorted(pins.items())),
        input_languages=tuple(sorted(languages)),
    )


def unknown_caller_files(
    xrefs: XrefSet,
    current: Mapping[str, tuple[str, str]],
    *,
    edited: Collection[str] = (),
) -> tuple[str, ...] | None:
    """Files whose caller data ``xrefs`` cannot vouch for (pure, sorted — K10).

    ``current`` is ``path → (language, content_digest)`` for the code the
    edges are read against (a stored index's projection, or
    :func:`~custodex.codeindex.file_digests` over the tree). A file is
    unknown when it is in a covered language (``input_languages``, recorded
    at build time — so a package move still lists the new paths) and the
    pin does not hold it at that digest — changed, never joined, or
    unvouched at join time — or when a pinned file is gone, or when it
    sources an edge the pin does not hold (joined through spans the join
    could not vouch for — e.g. deleted from the tree before it ran — so
    its REFERENCES are shown although no listing holds it). Other languages
    are the ``coverage`` map's honesty, not this check's. NO covered
    language (no SCIP document joined the index — e.g. a mismatched project
    root) vouches for nothing, so every listed file the pin does not hold is
    unknown. ``None`` = the artifact carries no pin, so currency is
    unknowable.

    ``edited`` names files of ``current`` modified LATER (``cdx impact``
    passes every file its diff modifies): the stored xrefs cannot hold
    their outgoing references at the edited content, so even a file the
    pin holds at ``current`` is unknown — under the SAME covered-language
    rule, and whether or not the edit changed a reference (no stored fact
    can say which edits did).
    """
    pins = xrefs.input_digests
    if pins is None:
        return None
    covered = set(xrefs.input_languages)
    changed_since = set(edited)
    unknown = {path for path in pins if path not in current}
    unknown.update({_entity_path(e.source) for e in xrefs.edges}.difference(pins))
    unknown.update(
        path
        for path, (language, digest) in current.items()
        if (language in covered or not covered)
        and (pins.get(path) != digest or path in changed_since)
    )
    return tuple(sorted(unknown))


def _entity_path(entity_id: str) -> str:
    """``symbol <path>#<name>`` → ``<path>`` (a path may hold ``#``, a
    qualname never does — so split at the LAST one)."""
    return entity_id.split(" ", 1)[1].rpartition("#")[0]


#: The default remedy — right for `cdx graph`, which judges the TREE: bring
#: every artifact current (UI copy, not a knob).
_REFRESH_REMEDY = (
    "bring the code index current, re-run the indexer, then `cdx scip --write`"
)

#: `cdx impact`'s remedy. Impact diffs the STORED code index against the
#: tree, so refreshing that index resets the very baseline it reports on:
#: the advice is to re-join only (UI copy, not a knob).
IMPACT_REMEDY = (
    "re-run the indexer on this tree, then `cdx scip --write`; do NOT run "
    "`cdx codeindex --write` until you have reviewed this impact — it resets "
    "the baseline this report diffs against; a file with a pending edit "
    "stays unknown until the change lands"
)


def caller_currency_note(
    unknown: tuple[str, ...] | None, *, remedy: str = _REFRESH_REMEDY
) -> str | None:
    """The ONE honesty line ``cdx impact``/``graph`` print (``None`` = current).

    ``unknown`` is :func:`unknown_caller_files`' result: ``None`` (no input
    pin) and a non-empty tuple each yield a note; ``()`` yields none. The
    facts are shared and state only what is known — the stored xrefs do
    not hold these files' current outgoing references — never that a
    reference changed (an honest over-report); ``remedy`` — the
    parenthesised advice closing both notes — is the calling verb's own.
    """
    if unknown is None:
        return (
            "caller data currency unknown — the xrefs artifact carries no "
            f"input pin ({remedy})"
        )
    if not unknown:
        return None
    return (
        f"caller data unknown for {len(unknown)} file(s) whose current "
        "outgoing references are not in the stored xrefs (changed, added or "
        "never indexed since the join ran, or stale in the code index when it "
        "ran — listed whether or not a reference changed): "
        f"{', '.join(unknown)} ({remedy})"
    )


# ---------------------------------------------------------- artifact read/write


def read_xrefs(cdmon_dir: Path) -> XrefSet | None:
    """Read the stored xrefs (missing file ⇒ ``None``; corrupt ⇒ loud, K8)."""
    path = cdmon_dir / XREFS_PATH.name
    if not path.is_file():
        return None
    try:
        return XrefSet.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, ValueError) as exc:
        raise SchemaError(f"corrupt xrefs artifact {path}: {exc}") from exc


def write_xrefs(xrefs: XrefSet, cdmon_dir: Path) -> bool:
    """The stamp-blind idempotent writer (⟨R⟩2/K7) — mirror of the code index's."""
    path = cdmon_dir / XREFS_PATH.name
    if path.is_file():
        try:
            existing = XrefSet.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, ValueError):
            existing = None
        # Everything but the two stamps is CONTENT — the input pin included
        # (it is an input, not a stamp — ⟨R⟩2 applies to _STAMPS only):
        # identical inputs skip (K7); a re-join against changed code re-pins.
        if existing is not None and existing.model_dump(
            exclude=set(_STAMPS)
        ) == xrefs.model_dump(exclude=set(_STAMPS)):
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xrefs.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return True
