"""Render a managed region's body from a code surface (K2, K10).

The code surface is the single source of truth (K2): a managed region's body is
*derived* from the :class:`~custodex.extract.DocumentSurface`, never the
other way round. Output is deterministic — rows are rendered in the surface's
already-sorted order and every cell is escaped (K10).

Two renderers exist:

* the built-in :func:`symbol_table` (region id ``"symbols"``), and
* config-driven :func:`render_template` tables, declared in
  ``MonitorConfig.region_templates`` and referenced by region id. This keeps the
  engine reusable (K0): the genbuild flag / switch / option tables are just
  configured templates, not engine code.
"""

from __future__ import annotations

from collections.abc import Mapping

from .config import RegionColumn, RegionTemplate
from .extract import DocumentSurface, Record, Symbol

__all__ = [
    "symbol_table",
    "render_template",
    "expected_region",
    "known_region_ids",
    "REGION_KEYS",
]


def _cell(text: str) -> str:
    """Escape a value for a single Markdown table cell."""
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _row(sym: Symbol) -> str:
    return f"| {_cell(sym.name)} | {_cell(sym.kind)} | {_cell(sym.signature)} |"


def symbol_table(surface: DocumentSurface) -> str:
    """Render a deterministic Markdown table of the surface's symbols.

    Columns: symbol, kind, signature. Rows follow the surface's symbol order
    (already sorted by ``(name, lineno)`` in extraction), so identical surfaces
    always render identical tables (K10). An empty surface still renders the
    header so the region is non-empty and stable.
    """
    header = ["| symbol | kind | signature |", "|--------|------|-----------|"]
    rows = [_row(sym) for sym in surface.symbols]
    return "\n".join(header + rows)


def _symbol_cell(col: RegionColumn, sym: Symbol) -> str:
    """One templated cell for a ``symbols``-source row."""
    return _cell(str(getattr(sym, col.field, "")))


def _record_cell(col: RegionColumn, rec: Record) -> str:
    """One templated cell for a ``records``-source row.

    ``name``/``kind`` read the record attributes; any other ``field`` reads the
    record's projected ``fields`` map (missing -> empty cell).
    """
    if col.field in ("name", "kind"):
        return _cell(str(getattr(rec, col.field, "")))
    return _cell(dict(rec.fields).get(col.field, ""))


def render_template(template: RegionTemplate, surface: DocumentSurface) -> str:
    """Render a config-declared table from ``surface`` (deterministic, K10).

    ``source='symbols'`` rows are the surface's symbols (sorted by name);
    ``source='records'`` rows are its records (sorted by ``(kind, name)``),
    optionally filtered to ``template.kind``. With no rows and an ``empty_text``
    the body is just that text; otherwise the header is always emitted so the
    region stays non-empty and stable. ``source='index'`` is rendered by the
    index-aware layer (it needs other documents' surfaces), not here.
    """
    headers = "| " + " | ".join(c.header for c in template.columns) + " |"
    sep = "|" + "|".join("---" for _ in template.columns) + "|"

    if template.source == "symbols":
        sym_rows = list(surface.symbols)
        if not sym_rows and template.empty_text:
            return template.empty_text
        lines = [headers, sep]
        for sym in sym_rows:
            lines.append(
                "| " + " | ".join(_symbol_cell(c, sym) for c in template.columns) + " |"
            )
        return "\n".join(lines)

    rec_rows = [
        r for r in surface.records if template.kind is None or r.kind == template.kind
    ]
    if not rec_rows and template.empty_text:
        return template.empty_text
    lines = [headers, sep]
    for rec in rec_rows:
        lines.append(
            "| " + " | ".join(_record_cell(c, rec) for c in template.columns) + " |"
        )
    return "\n".join(lines)


def expected_region(
    region_id: str,
    surface: DocumentSurface,
    template: RegionTemplate | None = None,
) -> str | None:
    """Return the body region ``region_id`` should hold, or ``None`` if unknown.

    A ``template`` (from config) takes precedence and is rendered against the
    surface. Otherwise the built-in ``"symbols"`` id maps to :func:`symbol_table`
    and any other id returns ``None`` (the caller treats it as unhealable).
    """
    if template is not None:
        return render_template(template, surface)
    if region_id == "symbols":
        return symbol_table(surface)
    return None


#: Built-in region ids the engine can render without a config template.
REGION_KEYS: frozenset[str] = frozenset({"symbols"})


def known_region_ids(
    templates: Mapping[str, RegionTemplate] | None = None,
) -> frozenset[str]:
    """Region ids the engine can render: the built-ins plus any config template."""
    if not templates:
        return REGION_KEYS
    return REGION_KEYS | frozenset(templates)
