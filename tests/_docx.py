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


def wrap_document(body_xml: str, *, xml_prolog: str | None = None) -> str:
    """Wrap raw ``w:body`` inner XML into a full ``word/document.xml``.

    ``xml_prolog`` overrides the leading ``<?xml ...?>`` (declaration +
    anything before the root) so a test can inject a DTD, a long comment
    prefix, or a UTF-16 declaration.
    """
    prolog = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        if xml_prolog is None
        else xml_prolog
    )
    return (
        f'{prolog}<w:document xmlns:w="{_W}"><w:body>{body_xml}</w:body></w:document>'
    )


def run(*children: str) -> str:
    """A ``w:p`` whose single run contains the given raw run-children XML."""
    return f"<w:p><w:r>{''.join(children)}</w:r></w:p>"


def text_run(text: str) -> str:
    return f"<w:t>{escape(text)}</w:t>"


def build_docx(
    dest: Path,
    paragraphs: list[tuple[str | None, str]],
    *,
    zip_date: tuple[int, int, int, int, int, int] = (2026, 1, 1, 0, 0, 0),
    extra_member: str | None = None,
    reverse_order: bool = False,
) -> None:
    """Write a minimal real docx zip to ``dest`` (parents created)."""
    build_docx_raw(
        dest,
        document_xml(paragraphs),
        zip_date=zip_date,
        extra_member=extra_member,
        reverse_order=reverse_order,
    )


def build_docx_raw(
    dest: Path,
    document_xml_content: str | bytes,
    *,
    parts: dict[str, str] | None = None,
    zip_date: tuple[int, int, int, int, int, int] = (2026, 1, 1, 0, 0, 0),
    extra_member: str | None = None,
    reverse_order: bool = False,
) -> None:
    """Write a docx whose ``word/document.xml`` is given verbatim.

    ``document_xml_content`` may be ``bytes`` (to inject a non-UTF-8
    encoding). ``parts`` adds extra named zip members (e.g.
    ``word/footnotes.xml``) to exercise the lossy-part detector.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc_bytes = (
        document_xml_content
        if isinstance(document_xml_content, bytes)
        else document_xml_content.encode("utf-8")
    )
    members: list[tuple[str, str | bytes]] = [
        ("[Content_Types].xml", _CONTENT_TYPES),
        ("word/document.xml", doc_bytes),
    ]
    for name, payload in (parts or {}).items():
        members.append((name, payload))
    if extra_member is not None:
        members.append(("docProps/core.xml", extra_member))
    if reverse_order:
        members.reverse()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in members:
            info = zipfile.ZipInfo(name, date_time=zip_date)
            # A bare ZipInfo defaults to ZIP_STORED; set DEFLATED explicitly so
            # fixtures mirror how Word actually writes (and so a bomb fixture
            # genuinely compresses small).
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, payload)
