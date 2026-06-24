"""The test-wiki extractor engine (EPIC R, R-06 Part A).

Turns the test tree into a navigable wiki WITHOUT a second source of truth: a
test's own docstring is the "what it asserts", its directory is the boundary
(from the R-05 reorg), and a ``Feature:``/``Features:`` tag line — in the test
docstring OR inherited from the module docstring — is the feature link. Every
``test_*.py`` is parsed with stdlib :mod:`ast`; the tests are NEVER imported or
executed (K1), so the wiki cannot drift from the tests.

Pure and deterministic (no clock, sorted/source-order output — K10); no new
dependency (stdlib ``ast`` + the existing :mod:`custodex.traceability`
tag regex — K0); loud (:class:`custodex.errors.CatalogError`) ONLY on a
genuinely unparseable test file (K8) — a test with no docstring is robustly an
empty summary, not an error. Rendering is byte-stable (K10): the same modules in
yield byte-identical Markdown out.
"""

from __future__ import annotations

import ast
from enum import Enum
from pathlib import Path
from typing import Final, TypeGuard

from pydantic import BaseModel, ConfigDict

from .errors import CatalogError
from .traceability import _TAG_RE, FEATURE_REF_RE

__all__ = [
    "TestBoundary",
    "TestCase",
    "TestModule",
    "collect_tests",
    "render_test_wiki_md",
]

_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


class TestBoundary(str, Enum):
    """The test layer a module belongs to, resolved from its directory (R-05)."""

    __test__ = False  # not a pytest test class despite the ``Test`` prefix

    UNIT = "unit"
    INTEGRATION = "integration"
    SYSTEM = "system"
    SMOKE = "smoke"
    REGRESSION = "regression"
    UNKNOWN = "unknown"


# Maps a path-part to its boundary; a part not here leaves the boundary UNKNOWN.
_BOUNDARY_BY_DIR: Final[dict[str, TestBoundary]] = {
    b.value: b for b in TestBoundary if b is not TestBoundary.UNKNOWN
}


class TestCase(BaseModel):
    """One collected ``test_*`` function — its docstring is the source of truth.

    Frozen + ``extra="forbid"``: an immutable AST extraction result; an unknown
    key is a bug we want to fail loud on (K8), not silently absorb.
    """

    model_config = _MODEL_CONFIG
    __test__ = False  # not a pytest test class despite the ``Test`` prefix

    nodeid: str  # path::func or path::Class::func
    path: str  # repo-relative posix
    name: str  # function name
    boundary: TestBoundary  # from the path
    summary: str  # first line of the test docstring ("" if none)
    features: tuple[str, ...]  # per-test + inherited module FEAT-ids, sorted+deduped


class TestModule(BaseModel):
    """One parsed ``test_*.py`` file: its boundary, module-level features, cases."""

    model_config = _MODEL_CONFIG
    __test__ = False  # not a pytest test class despite the ``Test`` prefix

    path: str  # repo-relative posix
    boundary: TestBoundary
    module_features: tuple[str, ...]  # the module docstring's `Features:` ids
    cases: tuple[TestCase, ...]


def _feature_ids(docstring: str | None) -> tuple[str, ...]:
    """Extract ``Feature(s):``-tagged FEAT-ids from a docstring (sorted, deduped).

    Reuses the traceability tag convention: a bare ``FEAT-id`` with no marker is
    prose and ignored — only ids on a ``Feature:``/``Features:`` line count.
    """
    if not docstring:
        return ()
    ids: set[str] = set()
    for marker in _TAG_RE.finditer(docstring):
        ids.update(FEATURE_REF_RE.findall(marker.group("ids")))
    return tuple(sorted(ids))


def _summary(docstring: str | None) -> str:
    """The first non-empty line of a docstring, stripped ("" if none)."""
    if not docstring:
        return ""
    for line in docstring.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _boundary_for(rel_parts: tuple[str, ...]) -> TestBoundary:
    """Resolve the boundary from the first known dir in the relative path."""
    for part in rel_parts:
        boundary = _BOUNDARY_BY_DIR.get(part)
        if boundary is not None:
            return boundary
    return TestBoundary.UNKNOWN


def _is_test_func(
    node: ast.stmt,
) -> TypeGuard[ast.FunctionDef | ast.AsyncFunctionDef]:
    """True for a ``def test_*`` / ``async def test_*`` function definition."""
    return isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef)
    ) and node.name.startswith("test_")


def _collect_one(rel: str, source: str) -> TestModule:
    """Parse one test file's source into a :class:`TestModule` (K1 — never exec)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:  # genuinely unparseable file → loud (K8)
        raise CatalogError(f"{rel}: unparseable test file: {exc}") from exc

    rel_parts = tuple(Path(rel).parts)
    boundary = _boundary_for(rel_parts)
    module_features = _feature_ids(ast.get_docstring(tree))

    cases: list[TestCase] = []
    for node in tree.body:  # top-level, in source order (K10)
        if _is_test_func(node):
            cases.append(_make_case(rel, boundary, module_features, node, cls=None))
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:  # class-nested, in source order (K10)
                if _is_test_func(sub):
                    cases.append(
                        _make_case(rel, boundary, module_features, sub, cls=node.name)
                    )

    return TestModule(
        path=rel,
        boundary=boundary,
        module_features=module_features,
        cases=tuple(cases),
    )


def _make_case(
    rel: str,
    boundary: TestBoundary,
    module_features: tuple[str, ...],
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    cls: str | None,
) -> TestCase:
    """Build a :class:`TestCase` from a test function node + its module context."""
    nodeid = f"{rel}::{cls}::{node.name}" if cls else f"{rel}::{node.name}"
    doc = ast.get_docstring(node)
    features = tuple(sorted(set(module_features) | set(_feature_ids(doc))))
    return TestCase(
        nodeid=nodeid,
        path=rel,
        name=node.name,
        boundary=boundary,
        summary=_summary(doc),
        features=features,
    )


def collect_tests(tests_root: Path) -> tuple[TestModule, ...]:
    """Walk ``tests_root`` and AST-parse every ``test_*.py`` into a sorted tuple.

    Each file is read as TEXT and parsed with stdlib :mod:`ast` — never imported
    or executed (K1). Top-level AND class-nested ``def test_*`` functions are
    collected (nodeid ``path::func`` or ``path::Class::func``), with each
    function's docstring summary, the boundary resolved from the directory, and
    the union of its own ``Feature:`` tags with the module docstring's
    ``Features:`` tags (sorted, deduped). Deterministic: modules sorted by path,
    cases in source order within a file (K10). A missing ``tests_root`` yields an
    empty tuple (no tests is not an error); a genuinely unparseable file raises a
    loud :class:`custodex.errors.CatalogError` (K8).
    """
    if not tests_root.is_dir():
        return ()
    modules: list[TestModule] = []
    for path in sorted(tests_root.rglob("test_*.py")):
        if not path.is_file():
            continue
        rel = path.relative_to(tests_root).as_posix()
        source = path.read_text(encoding="utf-8", errors="replace")
        modules.append(_collect_one(rel, source))
    return tuple(modules)


def render_test_wiki_md(modules: tuple[TestModule, ...]) -> str:
    """Render the test wiki — by boundary → module → case + a feature index (K10).

    Pure and byte-stable: the same modules in, byte-identical Markdown out (no
    clock, no environment). Modules are grouped under a heading per boundary (in
    enum order), each module listing its cases with their docstring summary and
    feature links; a closing **Tested by** index maps every referenced feature
    id to the sorted nodeids that tag it.
    """
    lines: list[str] = [
        "# custodex — test wiki",
        "",
        (
            "Generated from the tests' own docstrings + boundary directories — "
            "**do not hand-edit**. Run `cdx wiki` (R-08) to regenerate."
        ),
        "",
        f"**{len(modules)} test modules**, {sum(len(m.cases) for m in modules)} cases.",
        "",
    ]

    by_boundary: dict[TestBoundary, list[TestModule]] = {}
    for m in modules:
        by_boundary.setdefault(m.boundary, []).append(m)

    for boundary in TestBoundary:  # stable enum order (K10)
        group = by_boundary.get(boundary)
        if not group:
            continue
        lines.append(f"## {boundary.value.capitalize()}")
        lines.append("")
        for module in sorted(group, key=lambda m: m.path):
            mfeat = ", ".join(module.module_features) or "—"
            lines.append(f"### `{module.path}`")
            lines.append("")
            lines.append(f"Module features: {mfeat}")
            lines.append("")
            for case in module.cases:
                feats = ", ".join(f"`{f}`" for f in case.features) or "—"
                summary = case.summary or "(no docstring)"
                lines.append(f"- `{case.nodeid}` — {summary} [{feats}]")
            lines.append("")

    # Per-feature "Tested by" index: feature id → sorted nodeids.
    index: dict[str, set[str]] = {}
    for m in modules:
        for c in m.cases:
            for fid in c.features:
                index.setdefault(fid, set()).add(c.nodeid)

    lines.append("## Tested by (feature index)")
    lines.append("")
    if not index:
        lines.append("None — no test tags a catalogued feature yet.")
    else:
        for fid in sorted(index):
            nodeids = ", ".join(sorted(index[fid]))
            lines.append(f"- `{fid}` — {nodeids}")

    return "\n".join(lines).rstrip("\n") + "\n"
