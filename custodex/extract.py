"""Audience-aware code surface extraction (K0, K3, K10).

The surface a document depends on is derived purely from the abstract syntax
tree of its code references — the target module is **never imported** (K0), so
extraction is side-effect free and works on code that wouldn't even import.

Each reference is reduced to a tuple of :class:`Symbol` facts (functions,
classes, methods, module-level variables) carrying a readable signature, a
public/private flag, and a docstring. :func:`build_document_surface` then
applies the document's sub-file selection and its **audience filter** (K3):

* ``user-guide`` keeps only public symbols and hashes *only* their signatures,
  so editing a docstring/comment or a private symbol never moves the hash.
* ``eng-guide`` keeps every symbol and folds docstrings into the hash, so an
  internal/docstring edit *does* move the hash.

``surface_hash`` is a deterministic sha256 prefix over a sorted, clock-free
payload (K10), so identical inputs always produce identical hashes.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from .config import Audience, CodeRef, DocumentSpec
from .errors import ExtractionError

__all__ = [
    "Symbol",
    "Record",
    "anchor_id",
    "SurfaceFingerprint",
    "DocumentSurface",
    "Extractor",
    "PythonAstExtractor",
    "ShellExtractor",
    "register_extractor",
    "get_extractor",
    "extract_file",
    "extract_json_records",
    "extract_switches",
    "extract_argparse_records",
    "build_document_surface",
]

SymbolKind = Literal["function", "class", "method", "variable"]

# Frozen + extra="forbid": surfaces are immutable, normalized snapshots (K10).
_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


def anchor_id(qualified_name: str) -> str:
    """Return a stable ``sha256[:16]`` identity for a symbol's qualified name (P4).

    The anchor is derived from the qualified name ONLY — never the line number — so
    it is invariant under a pure code move/reorder and identifies the symbol a
    managed region is bound to. A rename changes the anchor (it is a different
    symbol identity). Deterministic (K10): depends only on the name.
    """
    return hashlib.sha256(qualified_name.encode("utf-8")).hexdigest()[:16]


class Symbol(BaseModel):
    """One extracted code fact: a function, class, method, or module variable."""

    model_config = _MODEL_CONFIG

    name: str
    kind: SymbolKind
    signature: str
    lineno: int
    end_lineno: int
    is_public: bool  # name does not start with "_"
    docstring: str | None
    # Positional parameter names (functions/methods only). Used for
    # ``arg_signature`` selection; deliberately NOT part of surface_hash (the
    # signature string already captures parameter changes for hashing).
    arg_names: tuple[str, ...] = ()
    # Body-AST digest for functions/methods (``None`` for class/variable). Feeds
    # the OPT-IN body tier of ``surface_hash`` (P-01); insensitive to comments,
    # formatting and the docstring, so it moves only on an implementation change.
    body_hash: str | None = None

    @property
    def anchor_id(self) -> str:
        """Stable, lineno-free identity of this symbol (P4) — see :func:`anchor_id`."""
        return anchor_id(self.name)


class Record(BaseModel):
    """One non-Python surface fact: a JSON row or a CLI switch.

    Generic and reusable (K0): ``name`` identifies the row/switch, ``kind`` is a
    free label (e.g. ``"flag"``, ``"switch"``), and ``fields`` is a sorted tuple
    of ``(key, value)`` pairs — both projected from the source by config.
    """

    model_config = _MODEL_CONFIG

    name: str
    kind: str
    fields: tuple[tuple[str, str], ...] = ()


def _hash_payload(payload: dict[str, object]) -> str:
    """Deterministic ``sha256[:16]`` over a sorted, clock-free JSON payload (K10)."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class SurfaceFingerprint(BaseModel):
    """A tiered fingerprint of a code surface (P2).

    ``composite`` IS :meth:`DocumentSurface.surface_hash` — the single identity
    stored in ``cdm.fingerprint`` (unchanged across P2, so no re-baseline). The
    three per-tier digests are DIAGNOSTIC: they let drift report WHICH tier moved
    without affecting the identity. ``signature`` (the structural surface:
    signature-only symbols + ``records``) is always present; ``docstring`` is
    ``None`` unless the audience folds docstrings in (eng-guide); ``body`` is
    ``None`` unless the opt-in body tier is on and a function/method contributes
    a body digest. Frozen + ``extra="forbid"``: an immutable, normalized snapshot.
    """

    model_config = _MODEL_CONFIG

    signature: str
    docstring: str | None
    body: str | None
    composite: str

    def drifted_against(self, other: SurfaceFingerprint) -> tuple[str, ...]:
        """Return the tier name(s) whose digest differs from ``other``, sorted (K10).

        A ``None`` tier (absent for this audience/flag) compares equal to ``None``
        and unequal to a present digest, so turning a tier on/off registers as a
        move of that tier.
        """
        moved: list[str] = []
        if self.signature != other.signature:
            moved.append("signature")
        if self.docstring != other.docstring:
            moved.append("docstring")
        if self.body != other.body:
            moved.append("body")
        return tuple(sorted(moved))


class DocumentSurface(BaseModel):
    """The audience-filtered, selected surface a document is graded against."""

    model_config = _MODEL_CONFIG

    doc_id: str
    audience: Audience
    symbols: tuple[Symbol, ...]
    records: tuple[Record, ...] = ()

    def surface_hash(self, *, include_body: bool = False) -> str:
        """Return a stable ``sha256[:16]`` over an audience-normalized payload.

        Deterministic (K10): symbols/records are sorted, keys are sorted, and no
        wall-clock or absolute path enters the digest. For ``user-guide`` the
        payload excludes docstrings (so a docstring/comment edit does not move
        the hash); ``eng-guide`` includes them. The audience itself is part of
        the payload so the two audiences never collide. Records (CLI switches,
        JSON rows) are externally-visible by nature and are hashed for both
        audiences.

        ``include_body`` (P-01, opt-in via ``MonitorConfig.fingerprint_body_tier``)
        folds each function/method's body-AST digest into the hash so an
        implementation change is detectable. It follows the same additive-key
        discipline as ``records``: the ``body_hash`` key only enters the payload
        when the tier is on AND a symbol has one, so with ``include_body=False``
        (the default) the digest is byte-identical to the pre-P1 contract for
        every audience — previously-stored fingerprints stay valid. The body tier
        is NEVER applied to ``user-guide``: a body change is a non-event for the
        externally-visible API (K3), so user-guide bytes never move under the flag.
        """
        return self.fingerprint(include_body=include_body).composite

    def fingerprint(self, *, include_body: bool = False) -> SurfaceFingerprint:
        """Return the tiered :class:`SurfaceFingerprint` for this surface (P2).

        ``composite`` is byte-identical to :meth:`surface_hash` (the unchanged
        identity); the per-tier digests are diagnostic. The ``signature`` tier
        hashes the structural surface (signature-only symbols + ``records``) so a
        records-only change is attributed to it; ``docstring`` and ``body`` are the
        orthogonal additive tiers, ``None`` when the audience/flag excludes them.
        Deterministic (K10): every payload is sorted and clock-free, and the
        composite payload is constructed exactly as the pre-P2 hash was, so stored
        ``cdm.fingerprint`` values stay valid.
        """
        include_docstrings = self.audience is Audience.ENG_GUIDE
        include_body_tier = include_body and self.audience is not Audience.USER_GUIDE

        items: list[dict[str, object]] = []
        sig_items: list[dict[str, object]] = []
        doc_items: list[dict[str, object]] = []
        body_items: list[dict[str, object]] = []
        for sym in self.symbols:
            base: dict[str, object] = {
                "name": sym.name,
                "kind": sym.kind,
                "signature": sym.signature,
                "is_public": sym.is_public,
            }
            entry = dict(base)
            if include_docstrings:
                entry["docstring"] = sym.docstring
                doc_items.append({"name": sym.name, "docstring": sym.docstring})
            if include_body_tier and sym.body_hash is not None:
                entry["body_hash"] = sym.body_hash
                body_items.append({"name": sym.name, "body_hash": sym.body_hash})
            items.append(entry)
            sig_items.append(base)
        # Sort by the same key used for symbol ordering so the payload is
        # independent of insertion order.
        items.sort(key=lambda e: (str(e["name"]),))
        sig_items.sort(key=lambda e: (str(e["name"]),))
        doc_items.sort(key=lambda e: (str(e["name"]),))
        body_items.sort(key=lambda e: (str(e["name"]),))

        # Backward compatible (K10): the ``records`` key only enters the payload
        # when present, so a symbols-only surface hashes exactly as it did before
        # records existed. Records are part of the externally-visible structural
        # surface, so they fold into the signature tier.
        records_payload: list[dict[str, object]] | None = None
        if self.records:
            records_payload = [
                {"name": r.name, "kind": r.kind, "fields": [list(f) for f in r.fields]}
                for r in sorted(self.records, key=lambda r: (r.kind, r.name))
            ]

        composite_payload: dict[str, object] = {
            "audience": self.audience.value,
            "symbols": items,
        }
        sig_payload: dict[str, object] = {
            "audience": self.audience.value,
            "symbols": sig_items,
        }
        if records_payload is not None:
            composite_payload["records"] = records_payload
            sig_payload["records"] = records_payload

        docstring = (
            _hash_payload({"docstrings": doc_items}) if include_docstrings else None
        )
        body = (
            _hash_payload({"bodies": body_items})
            if include_body_tier and body_items
            else None
        )
        return SurfaceFingerprint(
            signature=_hash_payload(sig_payload),
            docstring=docstring,
            body=body,
            composite=_hash_payload(composite_payload),
        )


def _is_public(name: str) -> bool:
    """A name is public when it does not start with an underscore.

    Dunder methods such as ``__init__`` are part of a class's surface, so we
    treat them as public (documented) members rather than private internals.
    """
    leaf = name.rsplit(".", 1)[-1]
    if leaf.startswith("__") and leaf.endswith("__"):
        return True
    return not leaf.startswith("_")


def _format_args(args: ast.arguments) -> str:
    """Reconstruct a readable parameter list from an AST ``arguments`` node."""
    parts: list[str] = []

    # Positional-only params (PEP 570) are followed by a bare "/".
    posonly = list(getattr(args, "posonlyargs", []))
    positional = posonly + list(args.args)
    # Defaults align to the tail of posonly+args.
    defaults = list(args.defaults)
    n_no_default = len(positional) - len(defaults)
    for i, arg in enumerate(positional):
        text = arg.arg
        if arg.annotation is not None:
            text += f": {ast.unparse(arg.annotation)}"
        if i >= n_no_default:
            default = defaults[i - n_no_default]
            sep = " = " if arg.annotation is not None else "="
            text += f"{sep}{ast.unparse(default)}"
        parts.append(text)
        if posonly and i == len(posonly) - 1:
            parts.append("/")

    if args.vararg is not None:
        text = "*" + args.vararg.arg
        if args.vararg.annotation is not None:
            text += f": {ast.unparse(args.vararg.annotation)}"
        parts.append(text)
    elif args.kwonlyargs:
        # A bare "*" separates positional from keyword-only params.
        parts.append("*")

    for arg, kw_default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        text = arg.arg
        if arg.annotation is not None:
            text += f": {ast.unparse(arg.annotation)}"
        if kw_default is not None:
            sep = " = " if arg.annotation is not None else "="
            text += f"{sep}{ast.unparse(kw_default)}"
        parts.append(text)

    if args.kwarg is not None:
        text = "**" + args.kwarg.arg
        if args.kwarg.annotation is not None:
            text += f": {ast.unparse(args.kwarg.annotation)}"
        parts.append(text)

    return ", ".join(parts)


def _func_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef, display_name: str
) -> str:
    """Build ``def name(args) -> ret`` (or ``async def ...``) for a function."""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    sig = f"{prefix} {display_name}({_format_args(node.args)})"
    if node.returns is not None:
        sig += f" -> {ast.unparse(node.returns)}"
    return sig


def _class_signature(node: ast.ClassDef) -> str:
    """Build ``class Name(Base, ...)`` for a class definition."""
    bases = [ast.unparse(b) for b in node.bases]
    bases += [f"{kw.arg}={ast.unparse(kw.value)}" for kw in node.keywords if kw.arg]
    inner = f"({', '.join(bases)})" if bases else ""
    return f"class {node.name}{inner}"


def _positional_names(args: ast.arguments) -> tuple[str, ...]:
    """The positional-or-keyword parameter names of a function, in order.

    Positional-only + normal positional params, excluding ``*args``/``**kw`` and
    keyword-only params — the list ``arg_signature`` matches against.
    """
    posonly = list(getattr(args, "posonlyargs", []))
    return tuple(a.arg for a in posonly + list(args.args))


def _body_ast_hash(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Return a ``sha256[:16]`` digest of a function/method's body AST (K10).

    The leading docstring statement is stripped so the body tier stays orthogonal
    to the docstring tier. Each remaining statement is rendered with
    :func:`ast.dump` with ``include_attributes=False`` — line/column positions are
    dropped, so the digest is insensitive to formatting, comments and line moves
    and moves only when the body's *structure* changes. Deterministic: the digest
    depends only on the parsed tree, never on the clock or source layout.
    """
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]  # drop the docstring statement
    blob = "\x00".join(ast.dump(stmt, include_attributes=False) for stmt in body)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _func_symbol(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    name: str,
    display_name: str,
    kind: SymbolKind,
) -> Symbol:
    return Symbol(
        name=name,
        kind=kind,
        signature=_func_signature(node, display_name),
        lineno=node.lineno,
        end_lineno=node.end_lineno or node.lineno,
        is_public=_is_public(name),
        docstring=ast.get_docstring(node),
        arg_names=_positional_names(node.args),
        body_hash=_body_ast_hash(node),
    )


#: Variable values longer than this (or spanning lines) are elided in the
#: signature to ``...`` — a 2 KB string constant should not become a doc cell.
_MAX_VALUE_LEN = 48


def _value_repr(node: ast.expr) -> str:
    """Render a variable's value, eliding long or multi-line values to ``...``.

    Short scalars render verbatim (``1``, ``"x"``, ``(1, 2)``) so the value is
    visible and stable; anything long or multi-line collapses to ``...`` so a
    large constant (e.g. a template string) does not bloat the symbol table.
    The elision is deterministic (K10) — it depends only on the source text.
    """
    text = ast.unparse(node)
    if "\n" in text or len(text) > _MAX_VALUE_LEN:
        return "..."
    return text


def _variable_symbols(
    node: ast.Assign | ast.AnnAssign,
) -> list[Symbol]:
    """Build variable Symbols for a module-level (annotated) assignment."""
    out: list[Symbol] = []
    end = node.end_lineno or node.lineno
    if isinstance(node, ast.AnnAssign):
        if not isinstance(node.target, ast.Name):
            return out
        name = node.target.id
        ann = ast.unparse(node.annotation)
        if node.value is not None:
            sig = f"{name}: {ann} = {_value_repr(node.value)}"
        else:
            sig = f"{name}: {ann}"
        out.append(
            Symbol(
                name=name,
                kind="variable",
                signature=sig,
                lineno=node.lineno,
                end_lineno=end,
                is_public=_is_public(name),
                docstring=None,
            )
        )
        return out

    value = _value_repr(node.value)
    for target in node.targets:
        if not isinstance(target, ast.Name):
            continue
        out.append(
            Symbol(
                name=target.id,
                kind="variable",
                signature=f"{target.id} = {value}",
                lineno=node.lineno,
                end_lineno=end,
                is_public=_is_public(target.id),
                docstring=None,
            )
        )
    return out


def _extract_python_symbols(path: Path) -> list[Symbol]:
    """Extract the symbol surface of one Python file via ``ast`` only (K0).

    Captures module-level functions (``def``/``async def``), classes and their
    methods (named ``Class.method``, kind ``method``), and module-level
    (annotated) assignments (kind ``variable``). The target module is parsed,
    never imported, so this is pure and side-effect free.

    Raises :class:`ExtractionError` (K8) if ``path`` cannot be read or contains
    a syntax error.
    """
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise ExtractionError(f"Code reference not found: {path}") from exc
    except OSError as exc:
        raise ExtractionError(f"Cannot read code reference {path}: {exc}") from exc

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise ExtractionError(f"Syntax error in code reference {path}: {exc}") from exc

    symbols: list[Symbol] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            symbols.append(
                _func_symbol(
                    node, name=node.name, display_name=node.name, kind="function"
                )
            )
        elif isinstance(node, ast.ClassDef):
            symbols.append(
                Symbol(
                    name=node.name,
                    kind="class",
                    signature=_class_signature(node),
                    lineno=node.lineno,
                    end_lineno=node.end_lineno or node.lineno,
                    is_public=_is_public(node.name),
                    docstring=ast.get_docstring(node),
                )
            )
            for child in node.body:
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    qual = f"{node.name}.{child.name}"
                    symbols.append(
                        _func_symbol(
                            child,
                            name=qual,
                            display_name=child.name,
                            kind="method",
                        )
                    )
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            symbols.extend(_variable_symbols(node))

    return symbols


# --------------------------------------------------------------------------- #
# Shell symbol extraction (P-05): regex over sh/bash, stdlib only (K0)         #
# --------------------------------------------------------------------------- #

#: A sh/bash function-definition header: ``name() {`` (POSIX) or
#: ``function name {`` / ``function name() {`` (bash). The opening brace must sit
#: on the header line (the conventional style); braces inside quotes/here-docs
#: are a best-effort limitation (see ``.project/slices/P-05.md``).
_SHELL_DEF_RE = re.compile(
    r"[ \t]*"
    r"(?:function[ \t]+(?P<fname>[A-Za-z_]\w*)[ \t]*(?:\([ \t]*\))?"
    r"|(?P<pname>[A-Za-z_]\w*)[ \t]*\([ \t]*\))"
    r"[ \t]*\{"
)


def _shell_block_end(lines: list[str], start_idx: int, start_col: int) -> int:
    """Return the 0-based line index where the brace opened at ``start_col`` closes.

    Brace-depth scan from just after the opening ``{`` (depth already 1).
    Best-effort: braces inside quotes/here-docs are not special-cased; an
    unbalanced block falls back to the header line (K10 — deterministic).
    """
    depth = 1
    for j in range(start_idx, len(lines)):
        for ch in lines[j][start_col if j == start_idx else 0 :]:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return j
    return start_idx


def _shell_docstring(lines: list[str], header_idx: int) -> str | None:
    """The contiguous ``#`` comment block directly above ``header_idx``.

    Walks UP from the header collecting comment lines (one leading ``# ``
    stripped, trailing whitespace normalized) until a blank/non-comment line;
    the ``#!`` shebang is never documentation. ``None`` when there is none.
    """
    collected: list[str] = []
    j = header_idx - 1
    while j >= 0:
        stripped = lines[j].lstrip()
        if stripped.startswith("#!") or not stripped.startswith("#"):
            break
        text = stripped[1:]
        if text.startswith(" "):
            text = text[1:]
        collected.append(text.rstrip())
        j -= 1
    if not collected:
        return None
    collected.reverse()
    return "\n".join(collected)


def _extract_shell_symbols(path: Path) -> list[Symbol]:
    """Extract sh/bash function definitions via regex only — import-free (K0, P5).

    Recognizes ``name() { … }`` and ``function name { … }`` headers; the script
    is parsed as text, never sourced or executed. The docstring is the leading
    ``#`` comment block (shebang excluded); ``body_hash`` is ``None`` (the opt-in
    body tier is Python-AST-only). Deterministic (K10).

    Raises :class:`ExtractionError` (K8) if ``path`` cannot be read.
    """
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise ExtractionError(f"Code reference not found: {path}") from exc
    except OSError as exc:
        raise ExtractionError(f"Cannot read code reference {path}: {exc}") from exc

    lines = source.splitlines()
    symbols: list[Symbol] = []
    for idx, line in enumerate(lines):
        match = _SHELL_DEF_RE.match(line)
        if match is None:
            continue
        name = match.group("fname") or match.group("pname")
        end_idx = _shell_block_end(lines, idx, match.end())
        symbols.append(
            Symbol(
                name=name,
                kind="function",
                signature=f"{name}()",
                lineno=idx + 1,
                end_lineno=end_idx + 1,
                is_public=_is_public(name),
                docstring=_shell_docstring(lines, idx),
            )
        )
    return symbols


# --------------------------------------------------------------------------- #
# Pluggable extractor seam (P-01, K0)                                          #
# --------------------------------------------------------------------------- #


@runtime_checkable
class Extractor(Protocol):
    """Pluggable code-surface extractor for one language family (K0).

    An extractor turns one source file into a list of :class:`Symbol` facts via
    static analysis only — it MUST NOT import or execute the target (K0). The
    engine holds no target-specific knowledge; supporting a new language is a new
    registration, never an edit to the engine's control flow.
    """

    language: str

    def extract(self, path: Path) -> list[Symbol]: ...


class PythonAstExtractor:
    """The default extractor: Python symbols via ``ast``, import-free (K0)."""

    language = "python"

    def extract(self, path: Path) -> list[Symbol]:
        return _extract_python_symbols(path)


class ShellExtractor:
    """The first real non-Python extractor: sh/bash functions via regex (P5, K0).

    Uses only the stdlib ``re`` module — no heavy parser, so the core dependency
    surface is unchanged and the offline test gate is intact (K0/K4). Registered
    by default (below) for ``.sh``/``.bash``, so a new language is a *registration*,
    never an engine edit.
    """

    language = "shell"

    def extract(self, path: Path) -> list[Symbol]:
        return _extract_shell_symbols(path)


# language -> extractor. Resolution is by language string only; no target- or
# path-specific branching lives here (K0). P-01 ships the Python default; other
# languages register through :func:`register_extractor` (P-03).
_EXTRACTORS: dict[str, Extractor] = {"python": PythonAstExtractor()}

# suffix -> language, for resolving a ``symbols`` ref whose ``lang`` is ``auto``
# (P3). Extractors self-describe their extensions via ``register_extractor``; the
# engine holds no language list of its own beyond the Python default (K0).
_SYMBOL_LANG_BY_SUFFIX: dict[str, str] = {".py": "python"}


def register_extractor(extractor: Extractor, *, suffixes: tuple[str, ...] = ()) -> None:
    """Register (or override) the extractor for ``extractor.language`` (K0).

    ``suffixes`` (P3) additionally maps each file extension (e.g. ``".rs"``) to
    ``extractor.language`` so a ``symbols`` ref with ``lang: auto`` resolves to
    this extractor by file suffix. Registering a new language is the ONLY step to
    support it — no engine control flow changes (proves K0).
    """
    _EXTRACTORS[extractor.language] = extractor
    for suffix in suffixes:
        _SYMBOL_LANG_BY_SUFFIX[suffix] = extractor.language


def get_extractor(language: str) -> Extractor:
    """Resolve the extractor for ``language``; loud on an unknown one (K8)."""
    try:
        return _EXTRACTORS[language]
    except KeyError:
        raise ExtractionError(
            f"no extractor registered for language {language!r}"
        ) from None


# P5: ship the shell extractor as a DEFAULT registration — proves K0 (a new
# language is a registration, not an engine edit). A `.sh`/`.bash` symbols ref
# with `lang: auto` (or `lang: shell`) now resolves to it.
register_extractor(ShellExtractor(), suffixes=(".sh", ".bash"))


def extract_file(path: Path) -> list[Symbol]:
    """Extract one Python file's symbol surface via the default extractor.

    A thin, behaviour-preserving wrapper over the registered ``python`` extractor
    so existing callers are unchanged. Raises :class:`ExtractionError` (K8) if
    ``path`` cannot be read or contains a syntax error.
    """
    return get_extractor("python").extract(path)


# --------------------------------------------------------------------------- #
# JSON record projection (generic list-of-dict, K0)
# --------------------------------------------------------------------------- #


def extract_json_records(
    path: Path, *, records_key: str, name_field: str
) -> list[Record]:
    """Project a JSON file's list of dict rows into :class:`Record`\\ s.

    ``records_key`` names the list-valued top-level key, or ``"*"`` for the sole
    list-valued top-level key. Each row's ``name_field`` becomes the record name
    (falling back to ``"?"``); the remaining keys become sorted ``fields``.
    Raises :class:`ExtractionError` (K8) on read/parse errors or a missing /
    ambiguous / non-list key.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except FileNotFoundError as exc:
        raise ExtractionError(f"Code reference not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionError(
            f"Cannot parse JSON code reference {path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ExtractionError(f"JSON reference {path} must be an object at top level")

    if records_key == "*":
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        if len(list_keys) != 1:
            raise ExtractionError(
                f"JSON reference {path}: '*' needs exactly one list-valued top-level "
                f"key, found {len(list_keys)}"
            )
        key = list_keys[0]
    else:
        if records_key not in data or not isinstance(data[records_key], list):
            raise ExtractionError(
                f"JSON reference {path}: no list-valued key {records_key!r}"
            )
        key = records_key

    records: list[Record] = []
    for row in data[key]:
        if not isinstance(row, dict):
            continue
        name = str(row.get(name_field, "?"))
        fields = tuple(
            sorted((str(k), str(v)) for k, v in row.items() if k != name_field)
        )
        records.append(Record(name=name, kind="record", fields=fields))
    return sorted(records, key=lambda r: r.name)


# --------------------------------------------------------------------------- #
# CLI switch extraction — python / shell / tcl (generic, K0)
# --------------------------------------------------------------------------- #

_SWITCHLIKE = re.compile(r"^--?[A-Za-z][\w-]*$")


def _switch_strings(node: ast.AST) -> list[str]:
    """Switch-like string literals reachable directly from ``node``."""
    out: list[str] = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if _SWITCHLIKE.match(node.value):
            out.append(node.value)
    elif isinstance(node, ast.Tuple | ast.List | ast.Set):
        for elt in node.elts:
            out += _switch_strings(elt)
    return out


def _is_argvish(node: ast.AST) -> bool:
    """True if ``node`` refers to a per-arg loop variable or ``sys.argv``."""
    if isinstance(node, ast.Name) and node.id in ("arg", "a", "argv"):
        return True
    if isinstance(node, ast.Attribute) and node.attr == "argv":
        return True
    if isinstance(node, ast.Subscript):
        return _is_argvish(node.value)
    return False


def _py_switches(text: str, path: Path) -> set[str]:
    """Switches from a python tool: argparse options + a manual argv loop."""
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        raise ExtractionError(f"Syntax error in code reference {path}: {exc}") from exc
    toks: set[str] = set()
    for node in ast.walk(tree):
        # argparse: add_argument("-x", "--xx", ...)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            for a in node.args:
                toks.update(_switch_strings(a))
        # manual loop: arg == "-x" / arg in ("-h","--help") / "-h" in sys.argv
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            collections = [
                o
                for o in node.comparators
                if isinstance(o, ast.Tuple | ast.List | ast.Set)
            ]
            all_switchlike = bool(collections) and all(
                isinstance(e, ast.Constant) and _SWITCHLIKE.match(str(e.value))
                for c in collections
                for e in c.elts
            )
            if any(_is_argvish(o) for o in operands) or all_switchlike:
                for o in operands:
                    toks.update(_switch_strings(o))
    return toks


_TCL_ARGV_BLOCK = re.compile(
    r"switch\s+-regexp\s+--\s+\$arg\s*\{(.*?)\n\s*\}\s*\n\s*\}", re.DOTALL
)
_TCL_SWITCH = re.compile(r"\n\s*\^(-\w[\w-]*)")
_TCL_REGEXP_CLASS = re.compile(r"regexp\s*\{\s*\^\\?-\+?\[([A-Za-z]+)\]")


def _tcl_switches(text: str) -> set[str]:
    """Switches a tcl tool matches on ``$argv`` (best-effort, generic)."""
    m = _TCL_ARGV_BLOCK.search(text)
    block = m.group(1) if m else text
    toks = set(_TCL_SWITCH.findall(block))
    for chars in _TCL_REGEXP_CLASS.findall(text):
        toks |= {"-" + c for c in chars}
    return toks


_SH_GETOPTS = re.compile(r"getopts\s+\"?:?([A-Za-z:]+)\"?\s+\w+")
_SH_CASE_SWITCH = re.compile(r"(--?[A-Za-z][\w-]*)(?=[)|])")


def _sh_switches(text: str) -> set[str]:
    """Switches from a shell tool: ``getopts`` optstring (authoritative) or case."""
    getopts = _SH_GETOPTS.findall(text)
    if getopts:
        toks: set[str] = set()
        for optstr in getopts:
            toks |= {"-" + c for c in optstr if c.isalpha()}
        return toks
    return set(_SH_CASE_SWITCH.findall(text))


_SUFFIX_LANG = {".py": "python", ".sh": "shell", ".bash": "shell", ".tcl": "tcl"}


def extract_switches(path: Path, *, lang: str = "auto") -> list[Record]:
    """Extract a tool's CLI switch tokens as :class:`Record`\\ s of kind ``switch``.

    ``lang`` selects the parser (``auto`` infers it from the file suffix,
    defaulting to ``shell``). Reusable across projects (K0). Raises
    :class:`ExtractionError` (K8) if the file cannot be read.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise ExtractionError(f"Code reference not found: {path}") from exc
    except OSError as exc:
        raise ExtractionError(f"Cannot read code reference {path}: {exc}") from exc

    resolved = _SUFFIX_LANG.get(path.suffix, "shell") if lang == "auto" else lang
    if resolved == "python":
        toks = _py_switches(text, path)
    elif resolved == "tcl":
        toks = _tcl_switches(text)
    else:
        toks = _sh_switches(text)
    return [Record(name=t, kind="switch") for t in sorted(toks)]


def _const_str(node: ast.expr | None, max_len: int | None = 80) -> str:
    """Best-effort string for an argparse keyword value (collapsed, trimmed).

    Whitespace is collapsed to single spaces. With ``max_len`` set the value is
    elided to ``max_len`` characters (protecting a doc cell from a runaway
    constant); pass ``max_len=None`` to keep prose-like values (e.g. ``help``)
    in full.
    """
    if node is None:
        return ""
    text = str(node.value) if isinstance(node, ast.Constant) else ast.unparse(node)
    text = " ".join(text.split())
    if max_len is None or len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def extract_argparse_records(path: Path) -> list[Record]:
    """Project an argparse CLI's ``add_argument`` calls into option Records.

    Generic and reusable (K0): each ``add_argument`` becomes a Record of kind
    ``option`` whose name is its first long option (or first option string), with
    ``action`` / ``default`` / ``help`` fields. Positional arguments (no leading
    ``-``) are skipped. Raises :class:`ExtractionError` (K8) on read/parse error.
    """
    try:
        tree = ast.parse(
            path.read_text(encoding="utf-8", errors="replace"), filename=str(path)
        )
    except FileNotFoundError as exc:
        raise ExtractionError(f"Code reference not found: {path}") from exc
    except (OSError, SyntaxError) as exc:
        raise ExtractionError(f"Cannot parse code reference {path}: {exc}") from exc

    records: dict[str, Record] = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            continue
        opts = [
            a.value
            for a in node.args
            if isinstance(a, ast.Constant)
            and isinstance(a.value, str)
            and a.value.startswith("-")
        ]
        if not opts:
            continue
        name = next((o for o in opts if o.startswith("--")), opts[0])
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        fields = (
            ("action", _const_str(kw.get("action"))),
            ("default", _const_str(kw.get("default"))),
            ("help", _const_str(kw.get("help"), max_len=None)),  # prose: keep full
        )
        records[name] = Record(name=name, kind="option", fields=fields)
    return sorted(records.values(), key=lambda r: r.name)


def _select(
    symbols: list[Symbol],
    ref_symbols: tuple[str, ...],
    ref_lines: tuple[tuple[int, int], ...],
    ref_names: tuple[str, ...],
) -> list[Symbol]:
    """Apply one CodeRef's sub-file selection to a file's symbols.

    With no selectors the whole file is kept. ``symbols`` matches by name
    (selecting a class name pulls in its methods); ``names`` keeps matching
    ``variable`` symbols; ``lines`` keeps symbols overlapping any 1-based
    inclusive range. A ref may combine selectors; the union is returned.
    """
    if not ref_symbols and not ref_lines and not ref_names:
        return list(symbols)

    selected: dict[tuple[str, int], Symbol] = {}

    if ref_symbols:
        wanted = set(ref_symbols)
        for sym in symbols:
            owner = sym.name.split(".", 1)[0]
            if sym.name in wanted or owner in wanted:
                selected[(sym.name, sym.lineno)] = sym

    if ref_names:
        wanted_vars = set(ref_names)
        for sym in symbols:
            if sym.kind == "variable" and sym.name in wanted_vars:
                selected[(sym.name, sym.lineno)] = sym

    if ref_lines:
        for sym in symbols:
            for start, end in ref_lines:
                if sym.lineno <= end and sym.end_lineno >= start:
                    selected[(sym.name, sym.lineno)] = sym
                    break

    return list(selected.values())


def _symbol_language(ref: CodeRef) -> str:
    """Resolve the extractor language for a ``symbols`` ref (P3, K0).

    An explicit ``ref.lang`` wins; ``auto`` infers from the file suffix via the
    registry's suffix map, defaulting to ``"python"`` (the pre-P3 behaviour for
    every symbol ref). The chosen language is resolved through
    :func:`get_extractor`, so an unregistered one is loud (K8).
    """
    if ref.lang != "auto":
        return ref.lang
    return _SYMBOL_LANG_BY_SUFFIX.get(Path(ref.path).suffix, "python")


def _symbols_for_ref(ref: CodeRef, root: Path) -> list[Symbol]:
    """The selected symbols a ``symbols`` ref contributes, via the registry (P3)."""
    extractor = get_extractor(_symbol_language(ref))
    file_symbols = extractor.extract(root / ref.path)
    if ref.arg_signature:
        wanted = tuple(ref.arg_signature)
        file_symbols = [
            s
            for s in file_symbols
            if s.kind in ("function", "method") and s.arg_names == wanted
        ]
    return _select(file_symbols, ref.symbols, ref.lines, ref.names)


def _records_for_ref(ref: CodeRef, root: Path) -> list[Record]:
    """The records a ``switches`` or ``records`` ref contributes."""
    path = root / ref.path
    if ref.extract == "switches":
        return extract_switches(path, lang=ref.lang)
    # extract == "records": JSON projection, or argparse options for python refs
    if ref.lang == "python" or (ref.lang == "auto" and path.suffix == ".py"):
        return extract_argparse_records(path)
    if ref.json_records is None:
        raise ExtractionError(
            f"code ref {ref.path!r} uses extract='records' but sets no json_records"
        )
    return extract_json_records(
        path, records_key=ref.json_records, name_field=ref.record_name_field
    )


def build_document_surface(doc: DocumentSpec, root: Path) -> DocumentSurface:
    """Build a document's audience-filtered surface from its code refs (K3).

    Each :class:`~custodex.config.CodeRef` contributes either Python
    *symbols* (``extract='symbols'``, optionally narrowed by ``symbols``/
    ``lines``/``names``/``arg_signature``) or *records* (``extract='switches'``
    or ``'records'``). Symbol selections are combined and deduped by
    ``(path, name, lineno)``; records by ``(path, kind, name)``. The audience
    filter drops private symbols for ``user-guide`` (records are always kept).
    Symbols are ordered by ``(name, lineno)`` and records by ``(kind, name)``
    (K10).

    Raises :class:`ExtractionError` (K8) for any unreadable / unparseable ref.
    """
    combined: dict[tuple[str, str, int], Symbol] = {}
    rec_combined: dict[tuple[str, str, str], Record] = {}
    for ref in doc.code_refs:
        if ref.extract == "symbols":
            for sym in _symbols_for_ref(ref, root):
                combined[(ref.path, sym.name, sym.lineno)] = sym
        else:
            for rec in _records_for_ref(ref, root):
                rec_combined[(ref.path, rec.kind, rec.name)] = rec

    symbols = sorted(combined.values(), key=lambda s: (s.name, s.lineno))
    records = sorted(rec_combined.values(), key=lambda r: (r.kind, r.name))

    if doc.audience is Audience.USER_GUIDE:
        # User-guide surface is the externally-visible API only: drop private
        # symbols entirely (their changes are non-events for this audience).
        symbols = [s for s in symbols if s.is_public]

    return DocumentSurface(
        doc_id=doc.id,
        audience=doc.audience,
        symbols=tuple(symbols),
        records=tuple(records),
    )
