"""The index-aware layer: render a ``source='index'`` region (K0, K2, K10).

A region whose template ``source`` is ``index`` lists the OTHER documents in the
config — a generated table of links into the doc set — so it cannot be rendered
from a single code surface (:func:`blocks.render_template` defers it here). Each
row is one document; a column's ``field`` selects a synthetic per-doc value:

* ``doc_id``   — the document id;
* ``title``    — the doc's ``#`` H1, rendered as a Markdown link to its HTML twin
  (``html: true``) or its ``.md`` source, so the index is clickable;
* ``summary``  — the doc's leading ``>`` purpose blockquote;
* ``link``     — the bare relative link target;
* ``audience`` — ``user-guide`` / ``eng-guide``;
* ``path``     — the doc's repo-relative path.

The index document itself is excluded; ``template.kind`` optionally filters the
rows to a single audience. Rows follow config order, so the table is
deterministic (K10). This layer reads the indexed docs' bodies (for title /
summary); it is otherwise pure.
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import DocumentSpec, MonitorConfig, RegionTemplate
from .layout import html_twin_path
from .manifest import parse_doc

__all__ = ["INDEX_SOURCE", "render_index"]

#: The ``RegionTemplate.source`` value this layer handles.
INDEX_SOURCE = "index"


def _title_and_summary(body: str) -> tuple[str, str]:
    """Extract the ``#`` title and the leading ``>`` blockquote from a doc body."""
    lines = body.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    title = ""
    if i < len(lines) and lines[i].lstrip().startswith("# "):
        title = lines[i].lstrip()[2:].strip()
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    quote: list[str] = []
    while i < len(lines) and lines[i].lstrip().startswith(">"):
        quote.append(lines[i].lstrip().lstrip(">").strip())
        i += 1
    return title, " ".join(quote).strip()


def _link(index_spec: DocumentSpec, target: DocumentSpec) -> str:
    """Relative link from the index doc to a target's HTML twin (or ``.md``)."""
    target_rel = html_twin_path(target.path) if target.html else target.path
    here = os.path.dirname(index_spec.path)
    rel = os.path.relpath(target_rel, start=here) if here else target_rel
    return Path(rel).as_posix()


def _cell(text: str) -> str:
    """Escape a value for a single Markdown table cell."""
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _fields(
    index_spec: DocumentSpec, target: DocumentSpec, root: Path
) -> dict[str, str]:
    """The synthetic per-doc fields available to an index column."""
    body = ""
    target_path = root / target.path
    if target_path.is_file():
        body = parse_doc(target_path).body
    title, summary = _title_and_summary(body)
    title = title or target.id
    link = _link(index_spec, target)
    return {
        "doc_id": target.id,
        "title": f"[{title}]({link})",
        "summary": summary,
        "link": link,
        "audience": target.audience.value,
        "path": target.path,
    }


def render_index(
    template: RegionTemplate,
    index_spec: DocumentSpec,
    config: MonitorConfig,
    root: Path,
) -> str:
    """Render an ``index`` region: a table over the config's other documents.

    Rows are every document except ``index_spec`` (optionally filtered to
    ``template.kind`` audience), in config order. Each column's ``field`` selects
    a synthetic per-doc value (see the module docstring). With no rows and an
    ``empty_text`` the body is just that text; otherwise the header is always
    emitted so the region stays non-empty and stable (K10).
    """
    targets = [d for d in config.documents if d.id != index_spec.id]
    if template.kind is not None:
        targets = [d for d in targets if d.audience.value == template.kind]

    headers = "| " + " | ".join(c.header for c in template.columns) + " |"
    sep = "|" + "|".join("---" for _ in template.columns) + "|"
    if not targets and template.empty_text:
        return template.empty_text
    lines = [headers, sep]
    for target in targets:
        fields = _fields(index_spec, target, root)
        lines.append(
            "| "
            + " | ".join(_cell(fields.get(c.field, "")) for c in template.columns)
            + " |"
        )
    return "\n".join(lines)
