"""Idempotent, region-only healing of documents (K7).

Healing only ever touches a document's **managed regions** and its
front-matter fingerprint — it never authors prose (K2). Both entry points are
idempotent (K7): re-running with no underlying change writes nothing and
returns ``False``.

* :func:`regenerate_regions` rewrites every known managed region from the code
  surface and refreshes the fingerprint — used by ``monitor`` to auto-close
  ``REGION``/``HASH`` drift.
* :func:`apply_fix` applies a backend-proposed fix. The fix object lives in
  ``schema.py`` (``ProposedFix``), which is built by a *later* slice (CDM-04),
  so we must NOT import it. Instead it is typed structurally via a
  :class:`Protocol`: any object exposing ``region_id`` / ``new_region_body`` /
  ``new_doc_text`` attributes works. A region-body fix sets that one region; a
  whole-doc fix overwrites the file.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

from .blocks import expected_region, known_region_ids
from .config import RegionTemplate
from .extract import DocumentSurface
from .manifest import (
    Doc,
    parse_doc,
    parse_text,
    regions,
    render_doc,
    set_fingerprint,
    set_region,
)

__all__ = ["ProposedFixLike", "regenerate_regions", "apply_fix", "render_corrected"]

_Templates = Mapping[str, RegionTemplate] | None


def _corrected(doc: Doc, surface: DocumentSurface, templates: _Templates = None) -> str:
    """The fully-corrected document text for ``doc`` given ``surface``.

    Regenerates every known managed region (K2) — built-in plus any config
    ``templates`` — and refreshes the ``cdm.fingerprint``; all other bytes are
    preserved (K7). Pure — no I/O.
    """
    known = known_region_ids(templates)
    body = doc.body
    for region_id in regions(doc):
        if region_id not in known:
            continue
        template = templates.get(region_id) if templates else None
        expected = expected_region(region_id, surface, template)
        if expected is None:
            continue
        body, _ = set_region(body, region_id, expected)
    meta = set_fingerprint(doc.meta, surface.surface_hash())
    return render_doc(meta, body)


def render_corrected(
    doc_text: str, surface: DocumentSurface, templates: _Templates = None
) -> str:
    """Return the corrected full document text (regions + fingerprint) from text.

    This is what a backend returns as a whole-doc ``FIX`` for ``HASH`` drift: the
    document rewritten so its managed regions and fingerprint match the current
    code surface. Reuses the same region/fingerprint logic as
    :func:`regenerate_regions`, so a backend FIX and an engine heal agree.
    """
    return _corrected(parse_text(doc_text), surface, templates)


@runtime_checkable
class ProposedFixLike(Protocol):
    """Structural type for a fix (mirrors schema.ProposedFix, not imported).

    ``schema.py`` is built in a later slice (CDM-04); typing the fix as a
    Protocol keeps this module free of that forward dependency while still
    giving mypy real attribute checks.
    """

    region_id: str | None
    new_region_body: str | None
    new_doc_text: str | None


def regenerate_regions(
    doc_path: Path, surface: DocumentSurface, templates: _Templates = None
) -> bool:
    """Rewrite known managed regions from ``surface`` and refresh the fingerprint.

    Touches only managed regions whose id the engine can render (built-in or a
    config ``templates`` entry) and the ``cdm.fingerprint`` front-matter value;
    all other bytes are preserved (K7). Returns ``True`` only if the file
    changed, so a second call with no code change returns ``False`` (K7).
    """
    doc = parse_doc(doc_path)
    new_text = _corrected(doc, surface, templates)
    if new_text == doc.raw:
        return False
    doc_path.write_text(new_text, encoding="utf-8")
    return True


def apply_fix(doc_path: Path, fix: ProposedFixLike) -> bool:
    """Apply a proposed fix to ``doc_path``; return ``True`` if it changed.

    A region-shaped fix (``region_id`` + ``new_region_body``) replaces just that
    region (K7). A whole-doc fix (``new_doc_text``) overwrites the file. An
    empty fix is a no-op. Idempotent: re-applying an already-applied fix returns
    ``False``.

    When a fix carries BOTH shapes — which a real LLM may do for a HASH drift,
    returning the regenerated region *and* the full corrected document — the
    whole-doc text wins: it is the authoritative full result and the only shape
    that also refreshes the front-matter fingerprint. Applying just the region
    would leave a stale fingerprint and a residual HASH drift, so the loop would
    not close in one pass. The prompt steers a backend to fill exactly one shape
    per drift; this precedence is the safety net for when it fills both.
    """
    region_id = getattr(fix, "region_id", None)
    new_region_body = getattr(fix, "new_region_body", None)
    new_doc_text = getattr(fix, "new_doc_text", None)

    if new_doc_text is not None:
        existing = doc_path.read_text(encoding="utf-8") if doc_path.is_file() else None
        if existing == new_doc_text:
            return False
        doc_path.write_text(new_doc_text, encoding="utf-8")
        return True

    if region_id is not None and new_region_body is not None:
        current = doc_path.read_text(encoding="utf-8")
        updated, changed = set_region(current, region_id, new_region_body)
        if changed:
            doc_path.write_text(updated, encoding="utf-8")
        return changed

    return False
