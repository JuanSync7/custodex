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

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from .errors import DriftError

__all__ = [
    "Doc",
    "parse_doc",
    "regions",
    "set_region",
    "stored_fingerprint",
    "set_fingerprint",
    "stamp_standard_meta",
    "render_doc",
    "parse_text",
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
    matter block is prepended. Used by :mod:`code_doc_monitor.heal` to write a
    doc back after refreshing the fingerprint.
    """
    if not meta:
        return body
    fm = yaml.safe_dump(meta, sort_keys=True, default_flow_style=False)
    return f"---\n{fm}---\n{body}"
