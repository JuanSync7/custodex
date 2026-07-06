"""AGT-05 — write a NEW doc from code and register it, in one verb (K4/K5/K11).

The doc-writer agent: ``cdx write-doc TARGET`` takes an undocumented source
file to a registered, conformant, ``cdx check``-green document. The skeleton
is the mechanical :func:`~custodex.layout.scaffold_doc` (fingerprint stamped
from the same surface, so the doc is born in-sync); the PROSE — the purpose
blockquote and an ``overview`` region declared ``mode: llm`` — is authored
through the EXISTING Backend seam via a synthetic B-06 authoring request, so
the offline default (MockBackend) writes a deterministic, audience-aware
stand-in (K4/K10) and a real backend writes real prose through the exact same
contract. Because the region is ``mode: llm``, the standing B-06 machinery
keeps it fresh: it re-authors when the surface moves and no-ops when it
doesn't (K7).

Registration follows the AGT-04 lesson's file-authorship rule: a
hand-maintained unit file is NEVER model-round-tripped (that destroys its
comments) — the new document entry is appended to the unit's ``documents:``
block by a bounded TEXTUAL SPLICE, self-validated by a reload, and reverted
on failure (the ``declare_edge`` precedent). Everything is dry-run by default
and applied only on the explicit human verb (K11).
"""

from __future__ import annotations

import posixpath
from pathlib import Path

from .backends import Backend, BackendResult, FixRequest, MockBackend
from .config import (
    Audience,
    CodeRef,
    ConfigBundle,
    DocumentSpec,
    MonitorConfig,
    RegionMode,
    load_bundle,
)
from .drift import Drift, DriftKind
from .errors import ConfigError
from .extract import DocumentSurface, build_document_surface
from .layout import scaffold_doc
from .manifest import parse_text, render_doc, set_region

__all__ = [
    "OVERVIEW_REGION",
    "proposed_doc_id",
    "build_doc_spec",
    "draft_document",
    "unit_snippet",
    "write_and_register",
]

#: The authored-prose region every written doc carries (``mode: llm`` — the
#: B-06 machinery re-authors it when the surface moves, K7).
OVERVIEW_REGION = "overview"


def proposed_doc_id(source_path: str) -> str:
    """A deterministic doc id from a source path: ``pkg/sub/m.py`` → ``pkg-sub-m``."""
    stem = posixpath.normpath(source_path)
    if "." in posixpath.basename(stem):
        stem = stem.rsplit(".", 1)[0]
    return stem.replace("/", "-")


def build_doc_spec(
    *,
    doc_id: str,
    path: str,
    audience: Audience,
    code_refs: tuple[str, ...],
) -> DocumentSpec:
    """The written doc's spec: a ``symbols`` table + the ``llm`` overview region."""
    return DocumentSpec(
        id=doc_id,
        path=path,
        audience=audience,
        region_keys=("symbols", OVERVIEW_REGION),
        region_modes={OVERVIEW_REGION: RegionMode.LLM},
        code_refs=tuple(CodeRef(path=ref) for ref in code_refs),
    )


def _author_overview(
    spec: DocumentSpec,
    surface: DocumentSurface,
    doc_text: str,
    *,
    backend: Backend,
    style_guidance: str | None,
) -> str:
    """Author the overview prose through the Backend seam (a synthetic B-06 ask).

    The request is shaped exactly like the monitor's no-renderer ``llm`` REGION
    drift, so EVERY backend answers it through the standing contract: the mock
    deterministically (K4/K10), a real one with real prose. A non-FIX verdict
    or a missing region body degrades to the scaffold placeholder — the doc is
    still valid; the prose just stays TODO (loud in the CLI output, never a
    crash).
    """
    request = FixRequest(
        drift=Drift(
            kind=DriftKind.REGION,
            doc_id=spec.id,
            doc_path=spec.path,
            detail=(
                f"authoring the {OVERVIEW_REGION!r} prose for a NEW document "
                "(cdx write-doc)"
            ),
            region_id=OVERVIEW_REGION,
            audience=spec.audience,
        ),
        surface=surface,
        doc_text=doc_text,
        doc_spec_id=spec.id,
        region_mode=RegionMode.LLM,
        style_guidance=style_guidance,
    )
    result: BackendResult = backend.propose(request)
    if result.fix is None or result.fix.new_region_body is None:
        return doc_text
    body, _changed = set_region(
        parse_text(doc_text).body, OVERVIEW_REGION, result.fix.new_region_body
    )
    return render_doc(parse_text(doc_text).meta, body)


def draft_document(
    spec: DocumentSpec,
    surface: DocumentSurface,
    *,
    style_guidance: str | None = None,
    backend: Backend | None = None,
    include_body: bool = False,
) -> str:
    """Render the full written doc: scaffold + authored purpose + overview prose.

    Byte-idempotent on the mock path for an unchanged surface (K7): the
    scaffold stamps the same fingerprint, the purpose line is a pure function
    of the spec/surface, and MockBackend's prose is a pure function of the
    surface. With a real backend, re-running does NOT re-author an unchanged
    surface — creation happens once and the B-06 no-drift rule takes over.
    """
    backend = backend or MockBackend()
    text = scaffold_doc(spec, surface, include_body=include_body)
    public = sum(1 for s in surface.symbols if s.is_public)
    refs = ", ".join(f"`{ref.path}`" for ref in spec.code_refs)
    purpose = (
        f"> {spec.audience.value} for {refs} — {public} public symbol(s). "
        "Authored by `cdx write-doc`; refine this line freely (it is yours)."
    )
    # Replace the WHOLE scaffold TODO purpose line (not just its prefix).
    text = "\n".join(
        purpose if line.startswith("> TODO") else line for line in text.split("\n")
    )
    return _author_overview(
        spec, surface, text, backend=backend, style_guidance=style_guidance
    )


def unit_snippet(spec: DocumentSpec, *, indent: int = 2) -> str:
    """The YAML block ``write_and_register`` splices under ``documents:``.

    ``indent`` is the ENTRY indent (the column of ``- id:``): 2 for the
    hand-maintained/template style, 0 for ``dump_unit_file`` output (the
    ``cdx onboard --apply`` / editor-generated style — the PR #20 fresh-review
    composition fix: the splice must match the unit's real indentation or the
    result is invalid YAML).
    """
    pad = " " * indent
    lines = [
        f"{pad}- id: {spec.id}",
        f"{pad}  path: {spec.path}",
        f"{pad}  audience: {spec.audience.value}",
        f'{pad}  region_keys: ["symbols", "overview"]',
        f"{pad}  region_modes:",
        f"{pad}    overview: llm",
        f"{pad}  code_refs:",
    ]
    lines.extend(f"{pad}    - path: {ref.path}" for ref in spec.code_refs)
    return "\n".join(lines)


def _append_document_block(text: str, spec: DocumentSpec) -> str:
    """Append a document entry at the END of the unit's ``documents:`` block.

    A bounded textual splice (the AGT-04 authorship rule: hand-maintained YAML
    is never model-round-tripped), INDENTATION-ADAPTIVE (the docmap locate
    precedent): the first existing ``- id:`` entry's indent decides both where
    the block ends and how the new entry is rendered — a ``dump_unit_file``
    unit (0-indent sequences) and a template unit (2-space) both splice
    validly. The block ends at the first subsequent non-blank line that is
    neither another entry at that indent nor deeper content — trailing blank
    lines stay after the new entry. Loud when the unit has no ``documents:``
    key (K8).
    """
    lines = text.split("\n")
    try:
        start = next(i for i, line in enumerate(lines) if line.rstrip() == "documents:")
    except StopIteration:
        raise ConfigError(
            "unit file has no `documents:` block — add the document by hand"
        ) from None
    entry_indent = 2  # the template default, used only if the block is empty
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            entry_indent = len(lines[j]) - len(lines[j].lstrip())
        break
    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent > entry_indent:
            continue  # a field/nested item of an entry
        if indent == entry_indent and line.lstrip().startswith("- "):
            continue  # another entry
        end = j  # a dedented or sibling key: the block is over
        break
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    lines[end:end] = unit_snippet(spec, indent=entry_indent).split("\n")
    return "\n".join(lines)


def write_and_register(
    config_dir: Path,
    *,
    unit: str,
    spec: DocumentSpec,
    backend: Backend | None = None,
    style_guidance: str | None = None,
    now: str,
) -> Path:
    """Register ``spec`` in ``unit`` and materialize its authored doc (the apply).

    Validates against the LOADED bundle (unknown unit / duplicate doc id /
    existing doc file are loud, K8), splices the new entry into the unit YAML
    (comments preserved; reload-validated, reverted on failure), bumps the
    frontmatter ``updated:`` stamp, then writes the drafted document. The doc
    is born in-sync (the scaffold stamps its fingerprint from the same
    surface), so the very next ``cdx check`` is green — no separate heal step.
    Returns the written doc path.
    """
    bundle: ConfigBundle = load_bundle(config_dir)
    cfg: MonitorConfig = bundle.config
    if any(d.id == spec.id for d in cfg.documents):
        raise ConfigError(f"document id {spec.id!r} already exists")
    stems = {u.frontmatter.unit for u in bundle.units}
    if unit not in stems:
        raise ConfigError(
            f"unknown unit {unit!r} — available: {', '.join(sorted(stems))}"
        )
    root = (config_dir / cfg.root).resolve()
    doc_path = root / spec.path
    if doc_path.is_file():
        raise ConfigError(
            f"document file {spec.path!r} already exists — refusing to overwrite"
        )

    unit_path = config_dir / f"{unit}.yaml"
    original = unit_path.read_text(encoding="utf-8")
    spliced = _append_document_block(original, spec)
    date = now.split("T", 1)[0]
    spliced = "\n".join(
        f'updated: "{date}"' if line.startswith("updated:") else line
        for line in spliced.split("\n")
    )
    unit_path.write_text(spliced, encoding="utf-8")
    try:
        load_bundle(config_dir)  # self-validate; never leave a broken config (K8)
    except ConfigError as exc:  # pragma: no cover - splice bug guard
        unit_path.write_text(original, encoding="utf-8")
        raise ConfigError(
            f"registration splice produced an invalid config ({exc}); "
            f"{unit_path.name} restored — add the document by hand"
        ) from exc

    surface = build_document_surface(spec, root)
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(
        draft_document(
            spec,
            surface,
            style_guidance=style_guidance,
            backend=backend,
            include_body=cfg.fingerprint_body_tier,
        ),
        encoding="utf-8",
    )
    return doc_path
