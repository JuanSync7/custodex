"""Document Layout Standard — structure linting + scaffolding (K0, K7, K10).

Where :mod:`drift` grades a doc's *content* against the code surface, this
module grades a doc's *shape* against the Layout Standard (``docs/LAYOUT_STANDARD.md``):
the canonical anchor order (front matter → title → purpose → prose → regions),
the managed front-matter schema (``cdm.schema_version`` / ``audience`` /
``fingerprint``), the ``CDM:BEGIN/END`` marker grammar, and the HTML-twin
pairing rule (1:1 path, embedded source hash, derived-not-edited).

Everything here is **pure** (string/Doc-in, issue-out): :func:`lint_config` does
the file reads, the rest is side-effect free. :func:`scaffold_doc` renders a
fully-conformant, in-sync document; :func:`stamp_doc_meta` is the front-matter
auto-fix used by ``cdmon lint --fix``.
"""

from __future__ import annotations

import hashlib
import os
import re
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .blocks import expected_region
from .config import DocumentSpec, MonitorConfig
from .errors import DriftError
from .extract import DocumentSurface
from .manifest import (
    Doc,
    parse_doc,
    regions,
    render_doc,
    set_fingerprint,
    stamp_standard_meta,
)

__all__ = [
    "LAYOUT_VERSION",
    "LayoutCode",
    "LayoutIssue",
    "md_source_hash",
    "embedded_md_hash",
    "lint_doc",
    "lint_html_twin",
    "lint_config",
    "scaffold_doc",
    "stamp_doc_meta",
    "html_twin_path",
]

#: The Layout Standard version a conformant doc declares in ``cdm.schema_version``.
LAYOUT_VERSION = "1.0.0"

# Accept this project's meta name and helium's documented alias (§4).
_MD_HASH_RE = re.compile(
    r"(?:code-doc|helium-docs)-md-sha256[\"'][^>]*?content=[\"']([0-9a-f]+)"
)


class LayoutCode(str, Enum):
    """One structural rule a document can violate (see LAYOUT_STANDARD.md §5)."""

    MISSING_FRONT_MATTER = "MISSING_FRONT_MATTER"
    MISSING_SCHEMA_VERSION = "MISSING_SCHEMA_VERSION"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    MISSING_AUDIENCE = "MISSING_AUDIENCE"
    AUDIENCE_MISMATCH = "AUDIENCE_MISMATCH"
    MISSING_FINGERPRINT = "MISSING_FINGERPRINT"
    MISSING_TITLE = "MISSING_TITLE"
    MISSING_PURPOSE = "MISSING_PURPOSE"
    UNDECLARED_REGION = "UNDECLARED_REGION"
    MISSING_REGION = "MISSING_REGION"
    MALFORMED_STRUCTURE = "MALFORMED_STRUCTURE"
    HTML_MISSING = "HTML_MISSING"
    HTML_NOT_DERIVED = "HTML_NOT_DERIVED"
    HTML_STALE = "HTML_STALE"
    INDEX_INCOMPLETE = "INDEX_INCOMPLETE"


class LayoutIssue(BaseModel):
    """One structural violation (data, never an exception)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str
    doc_path: str
    code: LayoutCode
    detail: str


def md_source_hash(md_text: str) -> str:
    """Deterministic sha256 prefix of Markdown text (CRLF-normalized) (K10).

    Matches helium's algorithm so the embedded HTML hash is portable across both
    projects: line endings are normalized to ``\\n`` and the first 16 hex chars
    of the sha256 digest are returned.
    """
    normalized = md_text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def embedded_md_hash(html: str) -> str | None:
    """Return the Markdown source hash embedded in ``html``, or ``None``.

    Looks for a ``<meta name="code-doc-md-sha256" content="…">`` tag (or
    helium's ``helium-docs-md-sha256`` alias). Returns the hash string, or
    ``None`` when no such tag is present.
    """
    match = _MD_HASH_RE.search(html)
    return match.group(1) if match else None


def _cdm_meta(doc: Doc) -> dict[str, object]:
    """The ``cdm:`` mapping from a doc's front matter ({} when absent)."""
    cdm = doc.meta.get("cdm")
    return cdm if isinstance(cdm, dict) else {}


def _structure_issues(spec: DocumentSpec, body: str) -> list[LayoutIssue]:
    """Title + purpose anchor checks on the doc body (§1)."""
    issues: list[LayoutIssue] = []
    lines = body.split("\n")
    # First non-blank line must be an H1 title.
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines) or not re.match(r"^#\s+\S", lines[idx]):
        issues.append(
            LayoutIssue(
                doc_id=spec.id,
                doc_path=spec.path,
                code=LayoutCode.MISSING_TITLE,
                detail="first non-blank body line is not an `# ` H1 title",
            )
        )
        return issues  # without a title, the purpose anchor is undefined
    # Next non-blank line must be a `>` blockquote purpose.
    idx += 1
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines) or not re.match(r"^>\s*\S", lines[idx]):
        issues.append(
            LayoutIssue(
                doc_id=spec.id,
                doc_path=spec.path,
                code=LayoutCode.MISSING_PURPOSE,
                detail="no `>` blockquote purpose line follows the title",
            )
        )
    return issues


def lint_doc(doc: Doc, spec: DocumentSpec) -> list[LayoutIssue]:
    """Validate one parsed document against the Layout Standard (pure).

    Checks the front-matter schema (§2), the title/purpose anchors (§1), and the
    region grammar / declaration consistency (§3). Returns one
    :class:`LayoutIssue` per violation; an empty list means conformant.
    """
    issues: list[LayoutIssue] = []

    def add(code: LayoutCode, detail: str) -> None:
        issues.append(
            LayoutIssue(doc_id=spec.id, doc_path=spec.path, code=code, detail=detail)
        )

    # --- front matter (§2) ----------------------------------------------------
    if not doc.meta:
        add(LayoutCode.MISSING_FRONT_MATTER, "no `---` YAML front matter")
    else:
        cdm = _cdm_meta(doc)
        sv = cdm.get("schema_version")
        if sv is None:
            add(LayoutCode.MISSING_SCHEMA_VERSION, "`cdm.schema_version` is absent")
        elif str(sv) != LAYOUT_VERSION:
            add(
                LayoutCode.SCHEMA_VERSION_MISMATCH,
                f"`cdm.schema_version` is {sv!r}, expected {LAYOUT_VERSION!r}",
            )
        aud = cdm.get("audience")
        if aud is None:
            add(LayoutCode.MISSING_AUDIENCE, "`cdm.audience` is absent")
        elif str(aud) != spec.audience.value:
            add(
                LayoutCode.AUDIENCE_MISMATCH,
                f"`cdm.audience` is {aud!r}, expected {spec.audience.value!r}",
            )
        if cdm.get("fingerprint") is None:
            add(LayoutCode.MISSING_FINGERPRINT, "`cdm.fingerprint` is absent")

    # --- title + purpose (§1) -------------------------------------------------
    issues.extend(_structure_issues(spec, doc.body))

    # --- regions (§3) ---------------------------------------------------------
    try:
        present = set(regions(doc))
    except DriftError as exc:
        add(LayoutCode.MALFORMED_STRUCTURE, str(exc))
        return issues
    declared = set(spec.region_keys)
    for extra in sorted(present - declared):
        add(
            LayoutCode.UNDECLARED_REGION,
            f"region {extra!r} is present but not declared in region_keys",
        )
    for missing in sorted(declared - present):
        add(
            LayoutCode.MISSING_REGION,
            f"declared region {missing!r} is absent from the document",
        )
    return issues


def html_twin_path(md_path: str) -> str:
    """The HTML twin path for a Markdown path: same stem, ``.html`` suffix (§4)."""
    return Path(md_path).with_suffix(".html").as_posix()


def lint_html_twin(
    md_body: str, html_text: str | None, *, doc_id: str, html_path: str
) -> list[LayoutIssue]:
    """Validate a declared HTML twin against the Markdown body (§4, pure).

    ``html_text`` is the twin's content, or ``None`` when the file is absent.
    Flags ``HTML_MISSING`` (no file), ``HTML_NOT_DERIVED`` (no embedded hash),
    or ``HTML_STALE`` (embedded hash ≠ current Markdown body hash).
    """
    if html_text is None:
        return [
            LayoutIssue(
                doc_id=doc_id,
                doc_path=html_path,
                code=LayoutCode.HTML_MISSING,
                detail="declared HTML twin file is absent",
            )
        ]
    embedded = embedded_md_hash(html_text)
    if embedded is None:
        return [
            LayoutIssue(
                doc_id=doc_id,
                doc_path=html_path,
                code=LayoutCode.HTML_NOT_DERIVED,
                detail="HTML twin has no embedded `*-md-sha256` source hash",
            )
        ]
    current = md_source_hash(md_body)
    if embedded != current:
        return [
            LayoutIssue(
                doc_id=doc_id,
                doc_path=html_path,
                code=LayoutCode.HTML_STALE,
                detail=f"embedded hash {embedded!r} != current body hash {current!r}",
            )
        ]
    return []


def _index_link_targets(index_spec: DocumentSpec, target: DocumentSpec) -> set[str]:
    """Acceptable relative link strings from ``index_spec`` to ``target``.

    A link to either the target's ``.md`` source or — when it has one — its
    ``.html`` twin counts as coverage, since either is a valid navigation target.
    """
    here = os.path.dirname(index_spec.path)

    def rel(p: str) -> str:
        return Path(os.path.relpath(p, start=here) if here else p).as_posix()

    wanted = {rel(target.path)}
    if target.html:
        wanted.add(rel(html_twin_path(target.path)))
    return wanted


def _index_coverage_issues(config: MonitorConfig, root: Path) -> list[LayoutIssue]:
    """Check that every ``index: true`` doc links every other document (K0).

    A purely structural, target-agnostic rule: a landing page declared as an
    index must reference each sibling doc (by its ``.md`` or ``.html`` link), so
    adding a doc to the config without linking it from the index is caught. A
    missing or malformed index doc is left to the other lint/check passes.
    """
    issues: list[LayoutIssue] = []
    for spec in config.documents:
        if not spec.index:
            continue
        doc_path = root / spec.path
        if not doc_path.is_file():
            continue  # existence is `cdmon check`'s gate (MISSING_DOC)
        try:
            body = parse_doc(doc_path).body
        except DriftError:
            continue  # malformed structure is reported by lint_doc
        for target in config.documents:
            if target.id == spec.id:
                continue
            wanted = _index_link_targets(spec, target)
            if not any(link in body for link in wanted):
                issues.append(
                    LayoutIssue(
                        doc_id=spec.id,
                        doc_path=spec.path,
                        code=LayoutCode.INDEX_INCOMPLETE,
                        detail=(
                            f"index does not link document {target.id!r} "
                            f"(expected a link to {sorted(wanted)[0]!r})"
                        ),
                    )
                )
    return issues


def lint_config(config: MonitorConfig, config_dir: Path) -> list[LayoutIssue]:
    """Lint every existing document in ``config`` against the standard.

    ``root = config_dir / config.root``. Missing doc files are left to
    ``cdmon check`` (existence is its gate); malformed front matter is reported
    as ``MALFORMED_STRUCTURE`` rather than raised. Reads files; otherwise pure.
    """
    root = config_dir / config.root
    issues: list[LayoutIssue] = []
    for spec in config.documents:
        doc_path = root / spec.path
        if not doc_path.is_file():
            continue
        try:
            doc = parse_doc(doc_path)
        except DriftError as exc:
            issues.append(
                LayoutIssue(
                    doc_id=spec.id,
                    doc_path=spec.path,
                    code=LayoutCode.MALFORMED_STRUCTURE,
                    detail=str(exc),
                )
            )
            continue
        issues.extend(lint_doc(doc, spec))
        if spec.html:
            html_rel = html_twin_path(spec.path)
            html_file = root / html_rel
            html_text = (
                html_file.read_text(encoding="utf-8") if html_file.is_file() else None
            )
            issues.extend(
                lint_html_twin(doc.body, html_text, doc_id=spec.id, html_path=html_rel)
            )
    issues.extend(_index_coverage_issues(config, root))
    return issues


def scaffold_doc(spec: DocumentSpec, surface: DocumentSurface) -> str:
    """Render a fully-conformant, in-sync document for ``spec`` (pure).

    Front matter carries the standard's static keys (``schema_version`` /
    ``audience``) plus the current ``fingerprint``; the body has a title, a
    placeholder purpose blockquote, and each declared region filled from the
    code surface. The result passes both :func:`lint_doc` and ``cdmon check``.
    """
    meta = stamp_standard_meta(
        {}, schema_version=LAYOUT_VERSION, audience=spec.audience.value
    )
    meta = set_fingerprint(meta, surface.surface_hash())
    parts = [
        f"# {spec.id}",
        "",
        f"> TODO: one-line purpose describing what `{spec.id}` covers.",
        "",
    ]
    for key in spec.region_keys:
        rendered = expected_region(key, surface)
        inner = rendered if rendered is not None else f"TODO: content for {key!r}"
        parts.extend(
            [f"<!-- CDM:BEGIN {key} -->", inner, f"<!-- CDM:END {key} -->", ""]
        )
    return render_doc(meta, "\n".join(parts))


def stamp_doc_meta(doc: Doc, spec: DocumentSpec) -> str:
    """Return ``doc`` rewritten with the standard's static front-matter keys.

    The front-matter auto-fix behind ``cdmon lint --fix``: sets
    ``cdm.schema_version`` and ``cdm.audience`` (preserving ``fingerprint`` and
    the body). Cannot fix structural issues (title/purpose/regions/html) — those
    need authoring.
    """
    meta = stamp_standard_meta(
        doc.meta, schema_version=LAYOUT_VERSION, audience=spec.audience.value
    )
    return render_doc(meta, doc.body)
