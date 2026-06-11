"""The feature ⇄ demo/test/source traceability engine (EPIC R, R-03).

Proves the 1:1 mapping the golden reference promises: every catalogued *feature*
has at least one demo AND at least one test. Reads the catalog
(:func:`code_doc_monitor.featurecatalog.load_catalog`) and scans evidence files
for an **inline feature-tag convention** — the single source of truth lives at
the test/demo itself (no duplication): a line of the form
``Feature: <id>[, <id>...]`` or ``Features: <id> ...`` (case-insensitive marker)
anywhere in a ``.py``/``.md`` file (a docstring, a comment, or a Markdown line).
A bare mention of a ``FEAT-id`` in prose (no ``Feature:`` marker) is NOT a
reference — the marker disambiguates evidence from description (the catalog
itself, and prose like this docstring, name ids without tagging them).

Pure and deterministic (no clock, sorted output — K10); never imports or executes
a scanned file — every file is read as text (K1); no new dependency (pydantic is
already core — K0). An ``unknown ref`` (a tagged id absent from the catalog) is a
LOUD reported gap (K8), and makes the matrix incomplete. The catalog's
``Feature.demos``/``tests`` slots are an OPTIONAL secondary source filled by
later slices; this inline scan is the primary, drift-free evidence.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict

from .featurecatalog import FeatureCatalog

__all__ = [
    "FEATURE_REF_RE",
    "EvidenceKind",
    "FeatureRef",
    "TraceMatrix",
    "build_matrix",
    "render_matrix_md",
    "scan_refs",
]

# A well-formed feature id (``FEAT-<SUBSYSTEM>-<NNN>``) anywhere in a string.
FEATURE_REF_RE: Final = re.compile(r"\bFEAT-[A-Z][A-Z0-9]*-\d{3}\b")

# A tag line: the case-insensitive marker ``Feature(s):`` then one or more ids
# (comma/space separated). Capturing only the id run lets a bare ``FEAT-id`` in
# prose (no marker) stay out of the matrix — the marker is what makes it evidence.
_TAG_RE: Final = re.compile(r"(?im)\bFeatures?:\s*(?P<ids>FEAT-[A-Z0-9 ,\-]+)")

_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)

_DEFAULT_SUFFIXES: Final = (".py", ".md")


class EvidenceKind(str, Enum):
    """What kind of artifact a :class:`FeatureRef` was found in."""

    TEST = "test"
    DEMO = "demo"
    SOURCE = "source"


class FeatureRef(BaseModel):
    """One inline ``Feature:`` tag found in an evidence file.

    Frozen + ``extra="forbid"``: an immutable scan result; an unknown key is a
    bug we want to fail loud on (K8), not silently absorb.
    """

    model_config = _MODEL_CONFIG

    feature_id: str
    path: str  # repo-relative, posix
    kind: EvidenceKind
    line: int  # 1-based


class TraceMatrix(BaseModel):
    """An immutable cross of the catalog ids against the scanned evidence refs."""

    model_config = ConfigDict(frozen=True)

    catalog_ids: tuple[str, ...]  # sorted
    refs: tuple[FeatureRef, ...]  # sorted by (path, line, feature_id)

    def _paths_for(self, fid: str, kind: EvidenceKind) -> tuple[str, ...]:
        """Sorted, de-duplicated evidence paths tagging ``fid`` with ``kind`` (K10)."""
        return tuple(
            sorted(
                {r.path for r in self.refs if r.feature_id == fid and r.kind is kind}
            )
        )

    def tests_for(self, fid: str) -> tuple[str, ...]:
        """Sorted test paths tagging ``fid`` (empty when none — a gap)."""
        return self._paths_for(fid, EvidenceKind.TEST)

    def demos_for(self, fid: str) -> tuple[str, ...]:
        """Sorted demo paths tagging ``fid`` (empty when none — a gap)."""
        return self._paths_for(fid, EvidenceKind.DEMO)

    def features_without_test(self) -> tuple[str, ...]:
        """Catalogued ids with NO test evidence, sorted (K10)."""
        return tuple(fid for fid in self.catalog_ids if not self.tests_for(fid))

    def features_without_demo(self) -> tuple[str, ...]:
        """Catalogued ids with NO demo evidence, sorted (K10)."""
        return tuple(fid for fid in self.catalog_ids if not self.demos_for(fid))

    def unknown_refs(self) -> tuple[FeatureRef, ...]:
        """Refs whose tagged id is NOT in the catalog — a loud gap (K8)."""
        known = set(self.catalog_ids)
        return tuple(r for r in self.refs if r.feature_id not in known)

    def is_complete(self) -> bool:
        """True iff no feature lacks a test or demo and no unknown ref exists (K8)."""
        return (
            not self.features_without_test()
            and not self.features_without_demo()
            and not self.unknown_refs()
        )


def _scan_text(text: str, path: str, kind: EvidenceKind) -> list[FeatureRef]:
    """Parse ``Feature:`` tags out of one file's ``text`` into refs (pure, K1)."""
    refs: list[FeatureRef] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for marker in _TAG_RE.finditer(line):
            for fid in FEATURE_REF_RE.findall(marker.group("ids")):
                refs.append(
                    FeatureRef(feature_id=fid, path=path, kind=kind, line=lineno)
                )
    return refs


def scan_refs(
    root: Path,
    kind: EvidenceKind,
    *,
    suffixes: tuple[str, ...] = _DEFAULT_SUFFIXES,
) -> list[FeatureRef]:
    """Scan ``root`` recursively for inline ``Feature:`` tags → sorted refs (K10).

    Every file under ``root`` whose suffix is in ``suffixes`` (default
    ``.py``/``.md``) is read as TEXT — never imported or executed (K1) — and its
    ``Feature(s): <id>...`` tag lines parsed into :class:`FeatureRef` records with
    a repo-relative posix ``path`` and a 1-based ``line``. A bare ``FEAT-id`` with
    no marker is prose, not a reference, and is ignored. A missing ``root`` yields
    an empty list (an un-scanned tree is simply no evidence, not an error). Results
    are sorted by ``(path, line, feature_id)`` so the scan is deterministic (K10).
    """
    if not root.is_dir():
        return []
    refs: list[FeatureRef] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        refs.extend(_scan_text(text, rel, kind))
    refs.sort(key=lambda r: (r.path, r.line, r.feature_id))
    return refs


def build_matrix(
    catalog: FeatureCatalog,
    *,
    tests_root: Path,
    demo_root: Path,
    source_root: Path | None = None,
) -> TraceMatrix:
    """Cross the catalog ids against scanned test/demo/(optional source) evidence.

    Scans ``tests_root`` (TEST), ``demo_root`` (DEMO), and — when given —
    ``source_root`` (SOURCE), then combines the refs with the catalog's sorted ids
    into a :class:`TraceMatrix`. Pure: it reads files as text only (K1) and the
    result is fully sorted (K10). A tagged id absent from the catalog lands in
    :meth:`TraceMatrix.unknown_refs` (a loud gap, K8).
    """
    refs: list[FeatureRef] = []
    refs.extend(scan_refs(tests_root, EvidenceKind.TEST))
    refs.extend(scan_refs(demo_root, EvidenceKind.DEMO))
    if source_root is not None:
        refs.extend(scan_refs(source_root, EvidenceKind.SOURCE))
    refs.sort(key=lambda r: (r.path, r.line, r.feature_id))
    catalog_ids = tuple(sorted(f.id for f in catalog.features))
    return TraceMatrix(catalog_ids=catalog_ids, refs=tuple(refs))


def render_matrix_md(matrix: TraceMatrix) -> str:
    """Render the traceability wiki — per-feature demo/test columns + gaps (K10).

    Pure and byte-stable: the same matrix in, byte-identical Markdown out (no
    clock, no environment). A per-feature table marks each id's test/demo
    coverage, followed by a **Gaps** section listing every feature missing a test
    or a demo and every unknown ref (a tagged id not in the catalog — a loud gap,
    K8).
    """
    without_test = set(matrix.features_without_test())
    without_demo = set(matrix.features_without_demo())
    complete = matrix.is_complete()

    lines: list[str] = [
        "# code-doc-monitor — feature traceability",
        "",
        (
            "Generated from the golden catalog crossed against inline `Feature:` "
            "tags in `tests/` + `demo/` — **do not hand-edit**. Run `cdmon trace` "
            "(R-07 `cdmon wiki`) to regenerate."
        ),
        "",
        f"**{len(matrix.catalog_ids)} features** — "
        f"{'COMPLETE' if complete else 'INCOMPLETE'} "
        "(every feature needs >=1 test AND >=1 demo).",
        "",
        "| Feature | Tests | Demos |",
        "|---------|-------|-------|",
    ]
    for fid in matrix.catalog_ids:
        tests = matrix.tests_for(fid)
        demos = matrix.demos_for(fid)
        tcell = ", ".join(tests) if tests else "— MISSING"
        dcell = ", ".join(demos) if demos else "— MISSING"
        lines.append(f"| `{fid}` | {tcell} | {dcell} |")
    lines.append("")
    lines.append("## Gaps")
    lines.append("")
    if complete:
        lines.append("None — every feature has at least one test and one demo.")
    else:
        for fid in sorted(without_test):
            lines.append(f"- `{fid}` — no test evidence")
        for fid in sorted(without_demo):
            lines.append(f"- `{fid}` — no demo evidence")
        for ref in matrix.unknown_refs():
            lines.append(
                f"- `{ref.feature_id}` — unknown ref tagged in "
                f"{ref.path}:{ref.line} ({ref.kind.value}) but not in the catalog"
            )
    return "\n".join(lines).rstrip("\n") + "\n"
