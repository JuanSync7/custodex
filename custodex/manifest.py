"""Documents with machine-managed regions + a fingerprint (K2, K7, K8).

A document is *prose* authored by a human plus zero or more **managed regions**
delimited by ``<!-- CDM:BEGIN <id> -->`` / ``<!-- CDM:END <id> -->`` markers and
an optional YAML front matter block holding ``cdm: {fingerprint: <hash>}``.

The region bodies and the fingerprint are derived from the code surface (K2) —
this module only *parses* and *edits* them, never authoring prose. Region
editing is byte-exact outside the markers (K7) and malformed region structure
raises a loud :class:`DriftError` (K8). The whole module is pure: callers do the
file I/O for :func:`parse_doc`; everything else is string-in/string-out.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from .errors import DriftError
from .extract import SurfaceFingerprint

__all__ = [
    "Doc",
    "parse_doc",
    "regions",
    "set_region",
    "stored_fingerprint",
    "set_fingerprint",
    "stored_fingerprint_tiers",
    "set_fingerprint_tiers",
    "stamp_standard_meta",
    "render_doc",
    "parse_text",
    "region_body_hash",
    "stored_region_hash",
    "set_region_hash",
    "stored_region_anchors",
    "set_region_anchors",
    "stored_symbol_sigs",
    "set_symbol_sigs",
    "region_is_locked",
    "stored_upstream_hashes",
    "set_upstream_hash",
    "drop_upstream_hash",
]

# A front-matter block is a leading "---\n ... \n---\n" fence.
_FM_RE = re.compile(r"\A---\n(.*?\n)?---\n", re.DOTALL)

_BEGIN = re.compile(r"^<!-- CDM:BEGIN (\S+) -->\s*$")
_END = re.compile(r"^<!-- CDM:END (\S+) -->\s*$")


class Doc(BaseModel):
    """A parsed document: its path, front-matter meta, body, and raw text."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    path: Path
    meta: dict[str, Any]
    body: str
    raw: str


def parse_text(raw: str, path: Path | None = None) -> Doc:
    """Split optional YAML front matter from a document's raw text.

    The string-in/string-out twin of :func:`parse_doc` (no file I/O), used when a
    document body is held in memory — e.g. a backend computing the corrected doc
    text from ``FixRequest.doc_text``. ``path`` is recorded for error messages
    and defaults to a sentinel. Malformed (non-mapping) front matter raises
    :class:`DriftError` (K8).
    """
    where = path if path is not None else Path("<memory>")
    match = _FM_RE.match(raw)
    if match is None:
        return Doc(path=where, meta={}, body=raw, raw=raw)

    fm_text = match.group(1) or ""
    body = raw[match.end() :]
    try:
        loaded = yaml.safe_load(fm_text) if fm_text.strip() else {}
    except yaml.YAMLError as exc:
        raise DriftError(f"Malformed YAML front matter in {where}: {exc}") from exc
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise DriftError(
            f"Front matter in {where} must be a mapping, got {type(loaded).__name__}"
        )
    return Doc(path=where, meta=loaded, body=body, raw=raw)


def parse_doc(path: Path) -> Doc:
    """Read ``path`` and split optional YAML front matter from the body.

    ``meta`` is the parsed front-matter mapping (``{}`` when absent); ``body`` is
    everything after the closing ``---`` fence; ``raw`` is the full file text.
    A malformed (non-mapping) front matter raises :class:`DriftError` (K8).
    """
    return parse_text(path.read_text(encoding="utf-8"), path)


def regions(doc: Doc) -> dict[str, str]:
    """Map each managed region id to its body text (between the markers).

    Raises :class:`DriftError` (K8) on malformed structure: an unterminated
    region, a duplicate id, nested regions, an END with no open region, or a
    mismatched END id.
    """
    lines = doc.body.split("\n")
    out: dict[str, str] = {}
    open_id: str | None = None
    open_start = -1
    for idx, line in enumerate(lines):
        begin = _BEGIN.match(line)
        if begin:
            if open_id is not None:
                raise DriftError(
                    f"region {begin.group(1)!r} opened inside still-open region "
                    f"{open_id!r} (line {idx + 1}); regions cannot nest"
                )
            rid = begin.group(1)
            if rid in out:
                raise DriftError(
                    f"duplicate region {rid!r} (line {idx + 1}); an id may appear "
                    "at most once per doc"
                )
            open_id, open_start = rid, idx
            continue
        end = _END.match(line)
        if end:
            if open_id is None:
                raise DriftError(
                    f"CDM:END {end.group(1)!r} with no open region (line {idx + 1})"
                )
            if end.group(1) != open_id:
                raise DriftError(
                    f"CDM:END {end.group(1)!r} does not match open region "
                    f"{open_id!r} (line {idx + 1})"
                )
            out[open_id] = "\n".join(lines[open_start + 1 : idx])
            open_id = None
    if open_id is not None:
        raise DriftError(f"unterminated region {open_id!r}")
    return out


def set_region(body: str, id: str, new: str) -> tuple[str, bool]:
    """Replace region ``id``'s body with ``new``; return ``(text, changed)``.

    Bytes outside the ``CDM:BEGIN``/``CDM:END`` markers are preserved exactly
    (K7). When ``id`` is absent or its body already equals ``new`` the text is
    returned unchanged with ``changed=False``. Structure is validated, so a
    malformed doc raises :class:`DriftError` (K8).
    """
    lines = body.split("\n")
    open_id: str | None = None
    open_start = -1
    span: tuple[int, int] | None = None
    for idx, line in enumerate(lines):
        begin = _BEGIN.match(line)
        if begin:
            if open_id is not None:
                raise DriftError(
                    f"region {begin.group(1)!r} opened inside still-open region "
                    f"{open_id!r} (line {idx + 1}); regions cannot nest"
                )
            open_id, open_start = begin.group(1), idx
            continue
        end = _END.match(line)
        if end:
            if open_id is None:
                raise DriftError(
                    f"CDM:END {end.group(1)!r} with no open region (line {idx + 1})"
                )
            if end.group(1) != open_id:
                raise DriftError(
                    f"CDM:END {end.group(1)!r} does not match open region "
                    f"{open_id!r} (line {idx + 1})"
                )
            if open_id == id:
                span = (open_start, idx)
            open_id = None
    if open_id is not None:
        raise DriftError(f"unterminated region {open_id!r}")

    if span is None:
        return body, False

    start, end_idx = span
    new_lines = new.split("\n")
    current = lines[start + 1 : end_idx]
    if current == new_lines:
        return body, False
    rebuilt = lines[: start + 1] + new_lines + lines[end_idx:]
    return "\n".join(rebuilt), True


def stored_fingerprint(doc: Doc) -> str | None:
    """Return ``meta["cdm"]["fingerprint"]`` if present, else ``None``."""
    cdm = doc.meta.get("cdm")
    if isinstance(cdm, dict):
        fp = cdm.get("fingerprint")
        if isinstance(fp, str):
            return fp
    return None


def set_fingerprint(meta: dict[str, Any], value: str) -> dict[str, Any]:
    """Return a copy of ``meta`` with ``cdm.fingerprint`` set to ``value``."""
    out = dict(meta)
    cdm = dict(out.get("cdm") or {}) if isinstance(out.get("cdm"), dict) else {}
    cdm["fingerprint"] = value
    out["cdm"] = cdm
    return out


def stored_fingerprint_tiers(doc: Doc) -> SurfaceFingerprint | None:
    """Return the per-tier fingerprint from ``cdm.fingerprint_tiers`` (P2), or None.

    None when the block is absent — an OLD doc stamped before P2 carries only the
    composite ``cdm.fingerprint``, so drift falls back to the composite-only
    message. Absent ``docstring``/``body`` sub-keys decode to ``None`` (a
    user-guide / flag-off surface omits them; the round-trip stays faithful).
    """
    cdm = doc.meta.get("cdm")
    if not isinstance(cdm, dict):
        return None
    tiers = cdm.get("fingerprint_tiers")
    if not isinstance(tiers, dict):
        return None
    signature = tiers.get("signature")
    composite = tiers.get("composite")
    if not isinstance(signature, str) or not isinstance(composite, str):
        return None
    docstring = tiers.get("docstring")
    body = tiers.get("body")
    return SurfaceFingerprint(
        signature=signature,
        docstring=docstring if isinstance(docstring, str) else None,
        body=body if isinstance(body, str) else None,
        composite=composite,
    )


def set_fingerprint_tiers(
    meta: dict[str, Any], fp: SurfaceFingerprint
) -> dict[str, Any]:
    """Return a copy of ``meta`` with ``cdm.fingerprint_tiers`` set (P2, additive).

    Additive to the ``cdm:`` mapping — every other key (the composite
    ``fingerprint``, ``region_hashes``, …) is preserved. ``None`` sub-tiers are
    omitted so the front matter stays compact; :func:`stored_fingerprint_tiers`
    decodes a missing sub-key back to ``None``.
    """
    out = dict(meta)
    cdm = dict(out.get("cdm") or {}) if isinstance(out.get("cdm"), dict) else {}
    tiers: dict[str, str] = {"signature": fp.signature, "composite": fp.composite}
    if fp.docstring is not None:
        tiers["docstring"] = fp.docstring
    if fp.body is not None:
        tiers["body"] = fp.body
    cdm["fingerprint_tiers"] = tiers
    out["cdm"] = cdm
    return out


def region_body_hash(body: str) -> str:
    """Deterministic sha256[:16] of a region body, CRLF-normalized (K10).

    Mirrors :func:`custodex.layout.md_source_hash` exactly (line endings
    normalized to ``\\n``, first 16 hex chars of the digest) so a stamped
    per-region hash is portable and stable across runs and platforms. This is
    the basis of the B-03 lock: the engine stamps it when it authors a region,
    and a human edit moves the body's hash away from the stored value.
    """
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def stored_region_hash(doc: Doc, region_id: str) -> str | None:
    """Return ``meta["cdm"]["region_hashes"][region_id]`` if present, else ``None``."""
    cdm = doc.meta.get("cdm")
    if isinstance(cdm, dict):
        hashes = cdm.get("region_hashes")
        if isinstance(hashes, dict):
            value = hashes.get(region_id)
            if isinstance(value, str):
                return value
    return None


def set_region_hash(meta: dict[str, Any], region_id: str, value: str) -> dict[str, Any]:
    """Return a copy of ``meta`` with ``cdm.region_hashes[region_id]`` set.

    Additive to the ``cdm:`` mapping — every other key (including
    ``fingerprint`` and sibling region hashes) is preserved, and because
    :func:`set_fingerprint` copies the whole ``cdm`` map, a stamped region hash
    survives a later fingerprint heal (B-03, zero blast radius).
    """
    out = dict(meta)
    cdm = dict(out.get("cdm") or {}) if isinstance(out.get("cdm"), dict) else {}
    hashes = dict(cdm.get("region_hashes") or {})
    hashes[region_id] = value
    cdm["region_hashes"] = hashes
    out["cdm"] = cdm
    return out


def stored_region_anchors(doc: Doc, region_id: str) -> tuple[str, ...] | None:
    """Return ``cdm.region_anchors[region_id]`` as a tuple, or None (P4).

    None when the region has no stamped anchor set (an OLD doc predating P4), so
    drift falls back to no anchor classification. The stored list is the sorted
    ``anchor_id``s of the symbols the region documents.
    """
    cdm = doc.meta.get("cdm")
    if isinstance(cdm, dict):
        anchors = cdm.get("region_anchors")
        if isinstance(anchors, dict):
            value = anchors.get(region_id)
            if isinstance(value, list) and all(isinstance(a, str) for a in value):
                return tuple(value)
    return None


def set_region_anchors(
    meta: dict[str, Any], region_id: str, anchors: tuple[str, ...]
) -> dict[str, Any]:
    """Return a copy of ``meta`` with ``cdm.region_anchors[region_id]`` set (P4).

    Additive to the ``cdm:`` mapping (like :func:`set_region_hash`) — every other
    key (``fingerprint``, ``fingerprint_tiers``, ``region_hashes``, sibling
    anchors) is preserved, so the anchor set survives later heals. Stored sorted
    for a deterministic, diff-stable front matter (K10).
    """
    out = dict(meta)
    cdm = dict(out.get("cdm") or {}) if isinstance(out.get("cdm"), dict) else {}
    region_anchors = dict(cdm.get("region_anchors") or {})
    region_anchors[region_id] = sorted(anchors)
    cdm["region_anchors"] = region_anchors
    out["cdm"] = cdm
    return out


def stored_symbol_sigs(doc: Doc) -> dict[str, str] | None:
    """Return ``cdm.symbol_sigs`` as an ``{anchor_id: sig_digest}`` mapping (DIG-01).

    The per-symbol signature digests stamped at last heal — the hash of each documented
    symbol's signature payload (name/kind/signature/is_public), keyed by its stable
    ``anchor_id``. Returns ``None`` when the block is ABSENT (a doc predating DIG-01),
    so severity classification degrades to the aggregate-tier behaviour; returns
    ``{}`` when the block is present but empty (a stamped doc with no symbols). The
    None-vs-empty distinction is the back-compat guard (K6/K8).
    """
    cdm = doc.meta.get("cdm")
    if isinstance(cdm, dict):
        sigs = cdm.get("symbol_sigs")
        if isinstance(sigs, dict):
            return {k: v for k, v in sigs.items() if isinstance(v, str)}
    return None


def set_symbol_sigs(meta: dict[str, Any], sigs: dict[str, str]) -> dict[str, Any]:
    """Return a copy of ``meta`` with ``cdm.symbol_sigs`` set (DIG-01, additive).

    Additive to the ``cdm:`` mapping (like :func:`set_region_anchors`) — every other key
    (``fingerprint``, ``fingerprint_tiers``, ``region_hashes``, ``region_anchors``,
    ``upstream_hashes``) is preserved, and because :func:`set_fingerprint` copies the
    whole ``cdm`` map, the per-symbol digests survive a later code↔doc fingerprint heal
    (zero blast radius). Stored with sorted keys for diff-stable front matter (K10).
    """
    out = dict(meta)
    cdm = dict(out.get("cdm") or {}) if isinstance(out.get("cdm"), dict) else {}
    cdm["symbol_sigs"] = {k: sigs[k] for k in sorted(sigs)}
    out["cdm"] = cdm
    return out


def stored_upstream_hashes(doc: Doc) -> dict[str, str]:
    """Return ``cdm.upstream_hashes`` as an ``{upstream_id: hash}`` mapping (EPIC B).

    The per-edge baseline stamps for Pillar B doc↔doc dependencies — the hash of
    each upstream doc's body at the time the downstream edge was last reviewed.
    Empty ``{}`` when the block is absent (a pre-EPIC-B doc, or a doc with no
    ``depends_on``), so callers never special-case None.
    """
    cdm = doc.meta.get("cdm")
    if isinstance(cdm, dict):
        stamps = cdm.get("upstream_hashes")
        if isinstance(stamps, dict):
            return {k: v for k, v in stamps.items() if isinstance(v, str)}
    return {}


def set_upstream_hash(
    meta: dict[str, Any], upstream_id: str, value: str
) -> dict[str, Any]:
    """Return a copy of ``meta`` with ``cdm.upstream_hashes[upstream_id]`` set (EPIC B).

    Additive to the ``cdm:`` mapping (like :func:`set_region_hash`) — every other
    key (``fingerprint``, ``region_hashes``, sibling edge stamps) is preserved, and
    because :func:`set_fingerprint` copies the whole ``cdm`` map, an edge stamp
    survives a later code↔doc fingerprint heal (zero blast radius).
    """
    out = dict(meta)
    cdm = dict(out.get("cdm") or {}) if isinstance(out.get("cdm"), dict) else {}
    stamps = dict(cdm.get("upstream_hashes") or {})
    stamps[upstream_id] = value
    cdm["upstream_hashes"] = stamps
    out["cdm"] = cdm
    return out


def drop_upstream_hash(meta: dict[str, Any], upstream_id: str) -> dict[str, Any]:
    """Return a copy of ``meta`` with the ``upstream_id`` edge stamp removed (EPIC B).

    Used when an edge is deleted from config. Dropping an absent id is a harmless
    no-op (K7). The ``upstream_hashes`` block is left in place (possibly empty) so
    the front-matter shape stays stable.
    """
    out = dict(meta)
    cdm = dict(out.get("cdm") or {}) if isinstance(out.get("cdm"), dict) else {}
    stamps = dict(cdm.get("upstream_hashes") or {})
    stamps.pop(upstream_id, None)
    cdm["upstream_hashes"] = stamps
    out["cdm"] = cdm
    return out


def region_is_locked(doc: Doc, region_id: str, current_body: str) -> bool:
    """The SHARED lock predicate consumed by drift + heal (CDM-07 one truth).

    A region is *locked* iff it carries a stored region hash AND the current
    body's hash differs from it — i.e. a human edited the body since the engine
    last stamped it. With no stored hash a region is never locked (the engine
    still owns it). drift and heal MUST agree by calling this one helper.
    """
    stored = stored_region_hash(doc, region_id)
    if stored is None:
        return False
    return region_body_hash(current_body) != stored


def stamp_standard_meta(
    meta: dict[str, Any], *, schema_version: str, audience: str
) -> dict[str, Any]:
    """Return a copy of ``meta`` with the Layout Standard static keys set.

    Sets ``cdm.schema_version`` and ``cdm.audience`` (the static front-matter
    keys authored by the scaffolder / ``lint --fix``), preserving every other
    key — including ``cdm.fingerprint``, which only :mod:`heal` rewrites.
    """
    out = dict(meta)
    cdm = dict(out.get("cdm") or {}) if isinstance(out.get("cdm"), dict) else {}
    cdm["schema_version"] = schema_version
    cdm["audience"] = audience
    out["cdm"] = cdm
    return out


def render_doc(meta: dict[str, Any], body: str) -> str:
    """Re-render front matter + body to a single document string.

    An empty ``meta`` emits the body verbatim (no fence); otherwise a YAML front
    matter block is prepended. Used by :mod:`custodex.heal` to write a
    doc back after refreshing the fingerprint.
    """
    if not meta:
        return body
    fm = yaml.safe_dump(meta, sort_keys=True, default_flow_style=False)
    return f"---\n{fm}---\n{body}"
