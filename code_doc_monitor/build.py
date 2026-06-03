"""Render managed Markdown docs to derived HTML twins (``cdmon build``).

Reusable + offline (K0): a small, dependency-free Markdown renderer (the package
depends only on pydantic/typer/pyyaml) turns each ``html: true`` document's body
into an HTML twin. The twin embeds the body's source hash
(``<meta name="code-doc-md-sha256">``) so the layout standard's twin check
(:func:`code_doc_monitor.layout.lint_html_twin`) recognises it as derived and
current. Output is deterministic (K10): same Markdown in, same HTML out.

The renderer is intentionally small — it covers the constructs managed docs use
(headings, paragraphs, GFM tables, ``-``/``1.`` lists, blockquotes, fenced code,
inline code/bold/links, rules) and rewrites intra-guide ``X.md`` links to their
``X.html`` twins. CDM region markers are stripped; the generated region tables
they fence are kept.
"""

from __future__ import annotations

import html as _html
import os
import re
from pathlib import Path

from .config import DocumentSpec, MonitorConfig
from .layout import html_twin_path, md_source_hash
from .manifest import parse_doc

__all__ = ["render_markdown", "build"]

_CDM_MARKER = re.compile(r"^\s*<!-- CDM:(?:BEGIN|END) \S+ -->\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_HR = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
_ULI = re.compile(r"^[-*+]\s+")
_OLI = re.compile(r"^\d+\.\s+")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")

_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    """A deterministic GitHub-style anchor id for a heading's text."""
    return _SLUG_STRIP.sub("-", text.lower()).strip("-") or "section"


def _md_href_to_html(target: str) -> str:
    """Rewrite an intra-guide ``X.md`` link to its ``X.html`` twin."""
    if "://" in target or target.startswith("#"):
        return target
    base, _, frag = target.partition("#")
    if base.endswith(".md"):
        base = base[:-3] + ".html"
        return base + (f"#{frag}" if frag else "")
    return target


def _inline(text: str) -> str:
    """Render inline Markdown (links/bold/code) over HTML-escaped text."""
    out = _html.escape(text, quote=False)

    def _link(m: re.Match[str]) -> str:
        href = _html.escape(_md_href_to_html(m.group(2)), quote=True)
        return f'<a href="{href}">{m.group(1)}</a>'

    out = _CODE.sub(r"<code>\1</code>", out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _LINK.sub(_link, out)
    return out


def _split_row(line: str) -> list[str]:
    """Split a Markdown table row into cells, honouring ``\\|`` escapes."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    cells = _CELL_SPLIT.split(s)
    return [c.strip().replace("\\|", "|").replace("\\\\", "\\") for c in cells]


def _render_table(header: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{_inline(h)}</th>" for h in header)
    out = ["<table>", f"<thead><tr>{th}</tr></thead>", "<tbody>"]
    for row in rows:
        tds = "".join(f"<td>{_inline(c)}</td>" for c in row)
        out.append(f"<tr>{tds}</tr>")
    out += ["</tbody>", "</table>"]
    return "\n".join(out)


def render_markdown(md: str) -> str:
    """Render a Markdown document body to an HTML fragment (deterministic, K10)."""
    lines = [ln for ln in md.split("\n") if not _CDM_MARKER.match(ln)]
    blocks: list[str] = []
    para: list[str] = []
    seen_ids: dict[str, int] = {}  # slug -> count, for deduping anchor ids
    i, n = 0, len(lines)

    def flush() -> None:
        if para:
            text = " ".join(x.strip() for x in para).strip()
            if text:
                blocks.append(f"<p>{_inline(text)}</p>")
            para.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush()
            i += 1
            continue

        if stripped.startswith("```"):
            flush()
            i += 1
            code: list[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # consume closing fence
            escaped = _html.escape("\n".join(code), quote=False)
            blocks.append(f"<pre><code>{escaped}</code></pre>")
            continue

        heading = _HEADING.match(stripped)
        if heading:
            flush()
            level = len(heading.group(1))
            raw = heading.group(2).strip()
            slug = _slug(raw)
            dup = seen_ids.get(slug, 0)
            seen_ids[slug] = dup + 1
            hid = slug if dup == 0 else f"{slug}-{dup}"
            blocks.append(f'<h{level} id="{hid}">{_inline(raw)}</h{level}>')
            i += 1
            continue

        if _HR.match(stripped):
            flush()
            blocks.append("<hr>")
            i += 1
            continue

        if (
            "|" in line
            and i + 1 < n
            and "-" in lines[i + 1]
            and _TABLE_SEP.match(lines[i + 1])
        ):
            flush()
            header = _split_row(line)
            i += 2
            rows: list[list[str]] = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            blocks.append(_render_table(header, rows))
            continue

        if stripped.startswith(">"):
            flush()
            quote: list[str] = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append(f"<blockquote>{_inline(' '.join(quote))}</blockquote>")
            continue

        if _ULI.match(stripped):
            flush()
            items = []
            while i < n and _ULI.match(lines[i].strip()):
                items.append(_inline(_ULI.sub("", lines[i].strip())))
                i += 1
            body = "\n".join(f"<li>{it}</li>" for it in items)
            blocks.append(f"<ul>\n{body}\n</ul>")
            continue

        if _OLI.match(stripped):
            flush()
            items = []
            while i < n and _OLI.match(lines[i].strip()):
                items.append(_inline(_OLI.sub("", lines[i].strip())))
                i += 1
            body = "\n".join(f"<li>{it}</li>" for it in items)
            blocks.append(f"<ol>\n{body}\n</ol>")
            continue

        para.append(line)
        i += 1

    flush()
    return "\n".join(blocks)


_PAGE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="code-doc-md-sha256" content="{md_hash}">
<title>{title}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  margin: 0; color: #1b1b1b; line-height: 1.5; display: flex; }}
nav {{ width: 17rem; flex: none; background: #0f1b2d; color: #cfe;
  padding: 1.2rem 1rem; font-size: 0.9rem; align-self: flex-start;
  position: sticky; top: 0; height: 100vh; overflow-y: auto; }}
nav h2 {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: #6da; margin: 1.1rem 0 0.4rem; }}
nav ul {{ list-style: none; padding-left: 0; margin: 0; }}
nav a {{ display: block; color: #cfe; text-decoration: none; padding: 0.15rem 0; }}
nav a:hover {{ color: #fff; }}
nav a.current {{ color: #fff; font-weight: 600; }}
main {{ flex: 1; min-width: 0; max-width: 56rem; margin: 0 auto; padding: 2rem 3rem; }}
h1, h2, h3 {{ line-height: 1.25; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.95rem; }}
th, td {{ border: 1px solid #d0d4da; padding: 0.4rem 0.6rem; text-align: left;
  vertical-align: top; }}
th {{ background: #eef1f5; }}
code {{ background: #f2f3f5; padding: 0.1rem 0.3rem; border-radius: 3px; }}
pre {{ background: #0f1b2d; color: #e6f0ff; padding: 1rem; border-radius: 6px;
  overflow-x: auto; }}
pre code {{ background: none; color: inherit; padding: 0; }}
blockquote {{ border-left: 4px solid #6da; background: #f4f9f6; margin: 1rem 0;
  padding: 0.6rem 1rem; }}
</style>
</head>
<body>
<nav>{nav}</nav>
<main>
{content}
</main>
</body>
</html>
"""


def _doc_title(body: str, fallback: str) -> str:
    """The first ``#`` heading text, or ``fallback``."""
    for line in body.split("\n"):
        m = _HEADING.match(line.strip())
        if m:
            return m.group(2).strip()
    return fallback


def _nav(html_docs: list[tuple[DocumentSpec, str]], current: DocumentSpec) -> str:
    """Build a sidebar linking every built doc, relative to ``current``.

    Entries use each doc's ``nav_label`` (falling back to its title) and are
    grouped under ``nav_section`` headings, preserving config order. When no doc
    declares a section the sidebar is a single flat list (backward compatible).
    """
    here = os.path.dirname(html_twin_path(current.path))

    def link(spec: DocumentSpec, title: str) -> str:
        twin = html_twin_path(spec.path)
        rel = os.path.relpath(twin, start=here) if here else twin
        rel = Path(rel).as_posix()
        label = _html.escape(spec.nav_label or title, quote=False)
        href = _html.escape(rel, quote=True)
        cls = ' class="current"' if spec.id == current.id else ""
        return f'<li><a href="{href}"{cls}>{label}</a></li>'

    if not any(spec.nav_section for spec, _ in html_docs):
        items = [link(spec, title) for spec, title in html_docs]
        return "<ul>\n" + "\n".join(items) + "\n</ul>"

    # Group by section, preserving first-seen section order and config order
    # within each group. Section-less docs (nav_section is None) are top-level
    # entries: they render first, in one headingless list, above the sections.
    groups: list[tuple[str | None, list[str]]] = []
    pos: dict[str | None, int] = {}
    for spec, title in html_docs:
        sec = spec.nav_section
        if sec not in pos:
            pos[sec] = len(groups)
            groups.append((sec, []))
        groups[pos[sec]][1].append(link(spec, title))

    groups.sort(key=lambda g: g[0] is not None)  # None group first; stable otherwise
    out: list[str] = []
    for sec, items in groups:
        if sec is not None:
            out.append(f"<h2>{_html.escape(sec, quote=False)}</h2>")
        out.append("<ul>\n" + "\n".join(items) + "\n</ul>")
    return "\n".join(out)


def build(config: MonitorConfig, config_dir: Path) -> list[Path]:
    """Render every ``html: true`` doc to its ``.html`` twin; return written paths.

    ``root = config_dir / config.root``. Each twin embeds the Markdown body's
    source hash so :func:`code_doc_monitor.layout.lint_html_twin` recognises it
    as derived and current. Missing source docs are skipped (``check`` owns
    existence). Deterministic (K10).
    """
    root = config_dir / config.root
    specs = [s for s in config.documents if s.html]

    titled: list[tuple[DocumentSpec, str]] = []
    bodies: dict[str, str] = {}
    for spec in specs:
        md_path = root / spec.path
        if not md_path.is_file():
            continue
        body = parse_doc(md_path).body
        bodies[spec.id] = body
        titled.append((spec, _doc_title(body, spec.id)))

    written: list[Path] = []
    for spec, title in titled:
        body = bodies[spec.id]
        page = _PAGE.format(
            md_hash=md_source_hash(body),
            title=_html.escape(title, quote=False),
            nav=_nav(titled, spec),
            content=render_markdown(body),
        )
        out_path = root / html_twin_path(spec.path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(page, encoding="utf-8")
        written.append(out_path)
    return written
