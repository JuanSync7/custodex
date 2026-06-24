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

from .blocks import REGION_KEYS, expected_region, known_region_ids
from .config import RegionMode, RegionTemplate
from .extract import DocumentSurface
from .manifest import (
    Doc,
    parse_doc,
    parse_text,
    region_body_hash,
    region_is_locked,
    regions,
    render_doc,
    set_fingerprint,
    set_fingerprint_tiers,
    set_region,
    set_region_anchors,
    set_region_hash,
)

__all__ = ["ProposedFixLike", "regenerate_regions", "apply_fix", "render_corrected"]

_Templates = Mapping[str, RegionTemplate] | None
_Modes = Mapping[str, RegionMode] | None


def locked_region_ids(doc: Doc, modes: _Modes) -> frozenset[str]:
    """Region ids the engine must NOT author (B-02/B-03), derived from ``modes``.

    A region is locked when its mode is ``human``, or when its mode is
    ``llm-seeded`` and a human has edited it (the SHARED
    :func:`~custodex.manifest.region_is_locked` predicate diverges). The
    set is empty when ``modes`` is ``None`` — heal then behaves as B-02/EPIC-A.
    """
    if not modes:
        return frozenset()
    out: set[str] = set()
    bodies = regions(doc)
    for region_id, body in bodies.items():
        mode = modes.get(region_id, RegionMode.GENERATED)
        if mode is RegionMode.HUMAN or (
            mode is RegionMode.LLM_SEEDED and region_is_locked(doc, region_id, body)
        ):
            out.add(region_id)
    return frozenset(out)


def _corrected(
    doc: Doc,
    surface: DocumentSurface,
    templates: _Templates = None,
    preserve: frozenset[str] = frozenset(),
    modes: _Modes = None,
    *,
    include_body: bool = False,
) -> str:
    """The fully-corrected document text for ``doc`` given ``surface``.

    Regenerates every known managed region (K2) — built-in plus any config
    ``templates`` — and refreshes the ``cdm.fingerprint``; all other bytes are
    preserved (K7). A region id in ``preserve`` is never regenerated — it is a
    human-owned region whose body the engine must not author (B-02).

    When ``modes`` is given (B-03), heal additionally (a) auto-preserves every
    *locked* region (a ``human`` region, or an ``llm-seeded`` region a human has
    edited — :func:`locked_region_ids`) and (b) STAMPS ``cdm.region_hashes[id]``:
    for a region it authors, the hash of the written body (so a later human edit
    is detectable); for a ``human`` region, the hash of its current body (so its
    review advisory persists across a fingerprint heal until the body changes).
    A locked ``llm-seeded`` region keeps its existing stamp (re-stamping would
    falsely unlock it). Pure — no I/O.
    """
    known = known_region_ids(templates)
    locked = locked_region_ids(doc, modes)
    skip = preserve | locked
    body = doc.body
    meta = dict(doc.meta)
    current_bodies = regions(doc)
    for region_id in current_bodies:
        mode = modes.get(region_id, RegionMode.GENERATED) if modes else None
        if region_id in skip:
            # A human region records its body hash so the advisory persists
            # (B-02 retrofit); a locked llm-seeded region keeps its stamp.
            if mode is RegionMode.HUMAN:
                meta = set_region_hash(
                    meta, region_id, region_body_hash(current_bodies[region_id])
                )
            continue
        if region_id not in known:
            continue
        template = templates.get(region_id) if templates else None
        expected = expected_region(region_id, surface, template)
        if expected is None:
            continue
        body, _ = set_region(body, region_id, expected)
        if region_id in REGION_KEYS:
            # P4: anchor this symbol-table region to the STABLE identities it
            # documents (lineno-free), so drift can tell a symbol add/remove/rename
            # from an internal (body/docstring) change. Stamped whenever the engine
            # authors the region, independent of B-03 mode tracking.
            meta = set_region_anchors(
                meta, region_id, tuple(s.anchor_id for s in surface.symbols)
            )
        if modes is not None:
            # The engine authored this region (generated or unlocked llm-seeded)
            # — stamp the written body so a future human edit diverges (B-03).
            meta = set_region_hash(meta, region_id, region_body_hash(expected))
    # One-shared-truth (P2): compute the tiered fingerprint ONCE and stamp both
    # the composite identity (cdm.fingerprint) and the per-tier digests
    # (cdm.fingerprint_tiers), so detect can report which tier moved.
    fp = surface.fingerprint(include_body=include_body)
    meta = set_fingerprint(meta, fp.composite)
    meta = set_fingerprint_tiers(meta, fp)
    return render_doc(meta, body)


def render_corrected(
    doc_text: str,
    surface: DocumentSurface,
    templates: _Templates = None,
    preserve: frozenset[str] = frozenset(),
    modes: _Modes = None,
    *,
    include_body: bool = False,
) -> str:
    """Return the corrected full document text (regions + fingerprint) from text.

    This is what a backend returns as a whole-doc ``FIX`` for ``HASH`` drift: the
    document rewritten so its managed regions and fingerprint match the current
    code surface. Reuses the same region/fingerprint logic as
    :func:`regenerate_regions`, so a backend FIX and an engine heal agree.
    Region ids in ``preserve`` keep their current body (human-owned, B-02);
    ``modes`` drives the B-03 lock + per-region hash stamping.
    """
    return _corrected(
        parse_text(doc_text),
        surface,
        templates,
        preserve,
        modes,
        include_body=include_body,
    )


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
    doc_path: Path,
    surface: DocumentSurface,
    templates: _Templates = None,
    preserve: frozenset[str] = frozenset(),
    modes: _Modes = None,
    *,
    include_body: bool = False,
) -> bool:
    """Rewrite known managed regions from ``surface`` and refresh the fingerprint.

    Touches only managed regions whose id the engine can render (built-in or a
    config ``templates`` entry) and the ``cdm.fingerprint`` front-matter value;
    all other bytes are preserved (K7). Region ids in ``preserve`` are left
    untouched (human-owned, B-02) — note the fingerprint can still move, so the
    file may change even when every editable region is preserved. ``modes``
    drives the B-03 lock (locked llm-seeded / human regions are auto-preserved)
    and per-region hash stamping. Returns ``True`` only if the file changed, so
    a second call with no change returns ``False`` (K7).
    """
    doc = parse_doc(doc_path)
    new_text = _corrected(
        doc, surface, templates, preserve, modes, include_body=include_body
    )
    if new_text == doc.raw:
        return False
    doc_path.write_text(new_text, encoding="utf-8")
    return True


def _stamp_region_hashes(text: str, modes: _Modes) -> str:
    """Re-render ``text`` with B-03 per-region hashes refreshed from its bodies.

    For a ``generated``/``llm-seeded`` region the engine just authored, and for a
    ``human`` region (advisory persistence), the stamp is set to the hash of the
    body currently in ``text``. A *locked* ``llm-seeded`` region keeps its
    existing stamp (re-stamping to the human body would falsely unlock it).
    Returns ``text`` unchanged when ``modes`` is ``None``.
    """
    if not modes:
        return text
    doc = parse_text(text)
    bodies = regions(doc)
    locked = locked_region_ids(doc, modes)
    meta = dict(doc.meta)
    for region_id, body in bodies.items():
        mode = modes.get(region_id, RegionMode.GENERATED)
        if region_id in locked and mode is RegionMode.LLM_SEEDED:
            # keep the existing stamp; the body is human-owned now (re-stamping it
            # to the human body would falsely unlock the region).
            continue
        meta = set_region_hash(meta, region_id, region_body_hash(body))
    return render_doc(meta, doc.body)


def apply_fix(
    doc_path: Path,
    fix: ProposedFixLike,
    *,
    preserve: frozenset[str] = frozenset(),
    modes: _Modes = None,
) -> bool:
    """Apply a proposed fix to ``doc_path``; return ``True`` if it changed.

    A region-shaped fix (``region_id`` + ``new_region_body``) replaces just that
    region (K7). A whole-doc fix (``new_doc_text``) overwrites the file. An
    empty fix is a no-op. Idempotent: re-applying an already-applied fix returns
    ``False``.

    ``preserve`` names human-owned regions the engine must never author (B-02).
    The guarantee lives HERE, at the write boundary, not in the backend: a
    whole-doc fix has the document's *current* body for every preserved region
    re-injected before the write, so even a backend that returned whole-doc text
    overwriting a human region cannot clobber it. A region-shaped fix targeting a
    preserved id is a no-op (``False``).

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

    # B-03: a *locked* region (human, or an llm-seeded one a human has edited) is
    # auto-added to `preserve` at this write boundary, so even a whole-doc fix
    # cannot clobber it — derived from the doc's CURRENT bodies before any write.
    effective_preserve = preserve
    if modes and doc_path.is_file():
        existing_doc = parse_doc(doc_path)
        effective_preserve = preserve | locked_region_ids(existing_doc, modes)

    if new_doc_text is not None:
        existing = doc_path.read_text(encoding="utf-8") if doc_path.is_file() else None
        result_text = new_doc_text
        if effective_preserve and existing is not None:
            current_regions = regions(parse_text(existing))
            for rid in effective_preserve:
                if rid in current_regions:
                    result_text, _ = set_region(result_text, rid, current_regions[rid])
        result_text = _stamp_region_hashes(result_text, modes)
        if existing == result_text:
            return False
        doc_path.write_text(result_text, encoding="utf-8")
        return True

    if region_id is not None and new_region_body is not None:
        if region_id in effective_preserve:
            return False
        current = doc_path.read_text(encoding="utf-8")
        updated, changed = set_region(current, region_id, new_region_body)
        stamped = _stamp_region_hashes(updated, modes)
        if stamped != current:
            doc_path.write_text(stamped, encoding="utf-8")
            return True
        return False

    return False
