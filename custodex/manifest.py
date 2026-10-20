"""Documents with machine-managed regions + a fingerprint (K2, K7, K8).

A document is *prose* authored by a human plus zero or more **managed regions**
delimited by ``<!-- CDM:BEGIN <id> -->`` / ``<!-- CDM:END <id> -->`` markers and
an optional YAML front matter block holding ``cdm: {fingerprint: <hash>}``.
Writing a doc back (:func:`render_doc`) splices the new front matter into the
block the doc already carries, so an engine write rewrites only the entries it
changed — in practice the ``cdm`` block — and leaves the author's lines alone
(:func:`render_doc` lists the layouts it re-dumps instead).

The region bodies and the fingerprint are derived from the code surface (K2) —
this module only *parses* and *edits* them, never authoring prose. Region
editing is byte-exact outside the markers (K7) and malformed region structure
raises a loud :class:`DriftError` (K8). The whole module is pure: callers do the
file I/O for :func:`parse_doc`; everything else is string-in/string-out.
"""

from __future__ import annotations

import bisect
import hashlib
import math
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

    Rollout is LAZY (the P4 ``region_anchors`` additive-migration pattern): an existing
    doc gains its ``symbol_sigs`` block only on its NEXT drift-driven reheal, so a
    not-yet-stamped doc keeps grading severity from the aggregate tiers
    (:func:`stored_symbol_sigs` returns None ⇒ degrade) until its surface next changes.
    A corpus-wide restamp is deliberately avoided — it would churn the idempotency.
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


def render_doc(meta: dict[str, Any], body: str, *, source: str | None = None) -> str:
    """Render front matter + body to one document string, splicing into ``source``.

    ``source`` is the full text the writer parsed (front matter included), or
    ``None`` for a brand-new doc. When ``source`` opens with a front-matter
    fence, ``meta`` is spliced into that block instead of re-dumping it:

    * a ``meta`` that parses equal to the stored block (exact types, so ``1`` is
      not ``True``; a tuple matches its list) returns the block byte for byte;
    * otherwise each top-level entry whose value did not change keeps its exact
      bytes (comments, quoting, flow style, folding, anchors); a changed entry is
      re-dumped in its place and loses every comment inside it (its inline
      comment, and any comment line or nested inline comment between its key
      and its last value line), while the comment and blank lines after it
      stay; a new entry is dumped where ``meta`` puts it; an entry missing from
      ``meta`` is dropped with the lines after it. Entries follow ``meta``'s
      order. A ``...`` document-end marker and the comment lines after it stay
      last, so new entries land before it. A re-dumped ``cdm`` block has its
      keys sorted; a kept one keeps its bytes, in whatever order they are.
    * two checks decide whether to splice. Before it, the layout must be a
      column-0 block mapping with no duplicate top-level key, no ``<<`` merge key
      and no aliased key: those are what lets each entry be cut out by span
      (``safe_load`` accepts a duplicate key, so the parse-back below cannot
      catch a mis-cut span on its own). After it, the result must parse back to
      exactly ``meta``, which refuses an alias into an entry the write changes
      or drops and a dumped anchor that clashes with a kept one. A layout
      either check refuses gets the fresh dump below, which is data-exact but
      not byte-preserving.

    The fresh dump keeps ``meta``'s key order, writes the ``cdm`` block with its
    keys sorted, writes non-ASCII text literally (``allow_unicode``, falling back
    to escapes when a character would not round-trip, e.g. U+0085), dumps sets in
    sorted order and gives every anchor a unique name (K10); a tuple dumps as a
    list. An empty ``meta`` with no source fence returns the body verbatim (no
    fence).

    Front matter in ``source`` that is malformed YAML or not a mapping raises
    :class:`DriftError` (K8), as :func:`parse_text` does on every read.
    """
    match = _FM_RE.match(source) if source is not None else None
    if source is not None and match is not None:
        parsed = parse_text(source).meta
        spliced = _splice_front_matter(match.group(1) or "", meta, parsed)
        if spliced is not None:
            return f"---\n{spliced}---\n{body}"
    if not meta:
        return body
    return f"---\n{_dump_mapping(_with_sorted_cdm(meta))}---\n{body}"


# --- front-matter splice + deterministic dump (FM-SPLICE) -------------------

_CDM_KEY = "cdm"
_MERGE_TAG = "tag:yaml.org,2002:merge"
# Tokens that close a structure or the stream rather than spell an entry's value:
# they sit at the next key (or past the trailing comments), never on the value.
# (A ``...`` marker is cut off as the trailer before the entries are scanned.)
_NON_CONTENT_TOKENS = (yaml.BlockEndToken, yaml.StreamEndToken)


class _FrontMatterDumper(yaml.SafeDumper):
    """SafeDumper whose output does not depend on the hash seed (K10)."""


def _represent_set(dumper: yaml.SafeDumper, data: Any) -> yaml.Node:
    try:
        members = sorted(data)
    except TypeError:
        members = sorted(data, key=repr)
    return dumper.represent_mapping(
        "tag:yaml.org,2002:set", {member: None for member in members}
    )


_FrontMatterDumper.add_representer(set, _represent_set)


def _same(a: Any, b: Any, seen: set[tuple[int, int]] | None = None) -> bool:
    """Data equality as YAML sees it: exact scalar types, NaN equals NaN.

    ``1 == True`` and ``1 == 1.0`` in Python, but they spell different YAML, so
    scalars must also match in type; a tuple equals the list it dumps as.
    Container pairs are memoised by identity, so shared aliases cost one visit
    and self-references terminate (a pair already in progress counts as equal).
    """
    if seen is None:
        seen = set()
    if isinstance(a, list | tuple) and isinstance(b, list | tuple):
        pair = (id(a), id(b))
        if pair in seen:
            return True
        seen.add(pair)
        return len(a) == len(b) and all(
            _same(x, y, seen) for x, y in zip(a, b, strict=True)
        )
    if isinstance(a, dict) and isinstance(b, dict):
        pair = (id(a), id(b))
        if pair in seen:
            return True
        seen.add(pair)
        return a.keys() == b.keys() and all(_same(a[k], b[k], seen) for k in a)
    if type(a) is not type(b):
        return False
    if isinstance(a, float) and math.isnan(a):
        return math.isnan(b)
    return bool(a == b)


def _sorted_tree(value: Any, memo: dict[int, Any] | None = None) -> Any:
    """A copy of ``value`` with every mapping's keys sorted (cycle-safe).

    Mappings whose keys do not sort keep their order; shared sub-trees stay
    shared in the copy, so the dump still anchors them.
    """
    if memo is None:
        memo = {}
    if id(value) in memo:
        return memo[id(value)]
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        memo[id(value)] = out
        try:
            keys = sorted(value)
        except TypeError:
            keys = list(value)
        for key in keys:
            out[key] = _sorted_tree(value[key], memo)
        return out
    if isinstance(value, list | tuple):
        items: list[Any] = []
        memo[id(value)] = items
        items.extend(_sorted_tree(item, memo) for item in value)
        return items
    return value


def _with_sorted_cdm(meta: dict[str, Any]) -> dict[str, Any]:
    return {k: _sorted_tree(v) if k == _CDM_KEY else v for k, v in meta.items()}


def _dump_mapping(mapping: dict[str, Any]) -> str:
    """Dump ``mapping`` in its own order, non-ASCII literal when it round-trips."""
    text: str = yaml.dump(
        mapping,
        Dumper=_FrontMatterDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    if _same(yaml.safe_load(text), mapping):
        return text
    # A character such as U+0085 (NEL) is written raw under allow_unicode and
    # YAML reads it back as a line break; escaped output round-trips.
    escaped: str = yaml.dump(
        mapping,
        Dumper=_FrontMatterDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=False,
    )
    return escaped


def _entry_spans(
    fm_text: str, root: yaml.MappingNode
) -> tuple[str, dict[Any, tuple[int, int, int]]] | None:
    """Locate each top-level entry: ``(start, content_end, end)`` by key.

    An entry runs from its key's line to the next key's line; its content ends
    at the end of the line holding its last token, and the rest (blank and
    comment lines) is its tail. Returns ``None`` for a layout the splice cannot
    address byte-exactly (a key off column 0, a ``<<`` merge key, an aliased
    key, whose node sits earlier in the text than its own line: an earlier key
    or a node inside an earlier value; or a duplicate key, whose dead earlier
    text has no place to stay). These bails are part of the splice contract,
    not a convenience: the parse-back cannot see a mis-cut span, because
    ``safe_load`` accepts the duplicate key such a cut leaves behind.
    """
    keys: list[Any] = []
    starts: list[int] = []
    constructor = yaml.SafeLoader("")
    for key_node, _value in root.value:
        # A non-scalar key never gets here: parse_text already refused it as an
        # unhashable key.
        if key_node.tag == _MERGE_TAG or key_node.start_mark.column != 0:
            return None
        if starts and key_node.start_mark.index <= starts[-1]:
            return None  # an aliased key: its node lies before its own line
        key = constructor.construct_object(key_node)
        if key in keys:
            return None  # a duplicate key: YAML keeps only the last one
        keys.append(key)
        starts.append(key_node.start_mark.index)
    last_token = list(starts)
    for token in yaml.scan(fm_text, Loader=yaml.SafeLoader):
        if isinstance(token, _NON_CONTENT_TOKENS):
            continue
        # The scanner queues tokens in source order with nondecreasing end
        # marks, so the latest token of an entry is its last one. A token
        # before the first key gets entry -1 and writes the LAST entry's slot,
        # which that entry's own key token (always scanned later) overwrites;
        # ``starts`` is never empty here (a block mapping has an entry).
        entry = bisect.bisect_right(starts, token.start_mark.index) - 1
        last_token[entry] = token.end_mark.index
    spans: dict[Any, tuple[int, int, int]] = {}
    for i, key in enumerate(keys):
        end = starts[i + 1] if i + 1 < len(starts) else len(fm_text)
        content = len(fm_text[: last_token[i]].rstrip())
        newline = fm_text.find("\n", content, end)
        content_end = end if newline < 0 else newline + 1
        spans[key] = (starts[i], content_end, end)
    return fm_text[: starts[0]] if starts else fm_text, spans


def _splice_front_matter(
    fm_text: str, meta: dict[str, Any], parsed: dict[str, Any]
) -> str | None:
    """Splice ``meta`` into the front-matter text ``fm_text`` (parsed: ``parsed``).

    Returns ``None`` when the layout cannot be spliced or the result would not
    parse back to exactly ``meta``; the caller then dumps the block fresh.
    """
    if _same(meta, parsed):
        return fm_text
    fm_text, trailer = _split_document_end(fm_text)
    root = yaml.compose(fm_text, Loader=yaml.SafeLoader)
    if root is None:
        located: tuple[str, dict[Any, tuple[int, int, int]]] | None = (fm_text, {})
    elif not isinstance(root, yaml.MappingNode) or root.flow_style:
        return None
    else:
        located = _entry_spans(fm_text, root)
    if located is None:
        return None
    head, spans = located
    out = [head]
    for key, value in meta.items():
        span = spans.get(key)
        if span is None:
            out.append(_dump_entry(key, value))
            continue
        start, content_end, end = span
        if _same(value, parsed[key]):
            out.append(fm_text[start:end])
        else:
            out.append(_dump_entry(key, value) + fm_text[content_end:end])
    spliced = "".join(out) + trailer
    try:
        back = yaml.safe_load(spliced)
    except yaml.YAMLError:
        return None  # e.g. clashing anchors, or new entries after a ``...``
    if not _same({} if back is None else back, meta):
        return None
    return spliced


def _split_document_end(fm_text: str) -> tuple[str, str]:
    """Split ``fm_text`` at a ``...`` marker: ``(entries, marker + what follows)``.

    Only comments can follow the marker (more content would be a second
    document, which :func:`parse_text` already refused), so the trailer is kept
    verbatim after the spliced entries.
    """
    for token in yaml.scan(fm_text, Loader=yaml.SafeLoader):
        if isinstance(token, yaml.DocumentEndToken):
            cut = token.start_mark.index
            return fm_text[:cut], fm_text[cut:]
    return fm_text, ""


def _dump_entry(key: Any, value: Any) -> str:
    return _dump_mapping({key: _sorted_tree(value) if key == _CDM_KEY else value})
