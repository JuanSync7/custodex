"""A minimal deterministic ``.docx`` builder for the spmirror test suites.

Builds a real WordprocessingML zip (the shape Word writes) from a list of
``(style, text)`` paragraphs so tests can pin the ``docx-text`` converter
contract WITHOUT a python-docx dependency (K0/K4: stdlib only, offline).

The knobs exist to prove container-churn invariance: ``zip_date`` and
``reverse_order`` and ``extra_member`` change the ZIP CONTAINER without
changing ``word/document.xml`` — a Word re-save with unchanged words.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)


def _paragraph_xml(style: str | None, text: str) -> str:
    ppr = ""
    if style == "list":
        ppr = (
            '<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>'
        )
    elif style:
        ppr = f'<w:pPr><w:pStyle w:val="{escape(style)}"/></w:pPr>'
    return f"<w:p>{ppr}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>"


def document_xml(paragraphs: list[tuple[str | None, str]]) -> str:
    """The ``word/document.xml`` payload for ``paragraphs``."""
    body = "".join(_paragraph_xml(style, text) for style, text in paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W}"><w:body>{body}</w:body></w:document>'
    )


def build_docx(
    dest: Path,
    paragraphs: list[tuple[str | None, str]],
    *,
    zip_date: tuple[int, int, int, int, int, int] = (2026, 1, 1, 0, 0, 0),
    extra_member: str | None = None,
    reverse_order: bool = False,
) -> None:
    """Write a minimal real docx zip to ``dest`` (parents created)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    members: list[tuple[str, str]] = [
        ("[Content_Types].xml", _CONTENT_TYPES),
        ("word/document.xml", document_xml(paragraphs)),
    ]
    if extra_member is not None:
        members.append(("docProps/core.xml", extra_member))
    if reverse_order:
        members.reverse()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in members:
            info = zipfile.ZipInfo(name, date_time=zip_date)
            zf.writestr(info, payload)
