"""CDM-11: `cdmon build` renders managed .md docs to derived .html twins.

Reusable + offline (K0): a small stdlib Markdown renderer (no third-party dep),
deterministic output (K10), CDM markers stripped, an embedded source hash that
satisfies the layout standard's twin check, and a nav across the built docs.

Features: FEAT-LAYOUT-008, FEAT-LAYOUT-009, FEAT-LAYOUT-005
"""

from __future__ import annotations

from code_doc_monitor.build import build, render_markdown
from code_doc_monitor.config import (
    Audience,
    CodeRef,
    DocumentSpec,
    MonitorConfig,
    RegionColumn,
    RegionTemplate,
)
from code_doc_monitor.layout import embedded_md_hash, lint_html_twin, md_source_hash
from code_doc_monitor.manifest import parse_doc

# --------------------------------------------------------------------------- #
# render_markdown unit
# --------------------------------------------------------------------------- #


def test_render_headings_paragraph_links_code():
    md = "# Title\n\nSome **bold** and `code` and a [link](https://example.com).\n"
    html = render_markdown(md)
    assert '<h1 id="title">Title</h1>' in html
    assert "<strong>bold</strong>" in html
    assert "<code>code</code>" in html
    assert '<a href="https://example.com">link</a>' in html


def test_render_heading_anchor_ids_slug_and_dedupe():
    md = "# Getting Started\n\n## Plugins\n\ntext\n\n## Plugins\n\nmore\n"
    html = render_markdown(md)
    # slugged, lowercase, hyphenated; deep-linkable
    assert '<h1 id="getting-started">Getting Started</h1>' in html
    # duplicate heading text gets a deduped id
    assert '<h2 id="plugins">Plugins</h2>' in html
    assert '<h2 id="plugins-1">Plugins</h2>' in html


def test_render_table():
    md = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n"
    html = render_markdown(md)
    assert "<table>" in html and "</table>" in html
    assert "<th>A</th>" in html
    assert "<td>1</td>" in html


def test_render_list_and_blockquote():
    md = "> a purpose line\n\n- one\n- two\n"
    html = render_markdown(md)
    assert "<blockquote>" in html
    assert "<ul>" in html and "<li>one</li>" in html


def test_render_strips_cdm_markers_keeps_body():
    md = (
        "# T\n\n<!-- CDM:BEGIN flags -->\n| F | A |\n|---|---|\n| -x | replace |\n"
        "<!-- CDM:END flags -->\n"
    )
    html = render_markdown(md)
    assert "CDM:BEGIN" not in html and "CDM:END" not in html
    assert "<td>-x</td>" in html


def test_render_escapes_html():
    md = "A <script>alert(1)</script> & b\n"
    html = render_markdown(md)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html and "&amp;" in html


def test_render_is_deterministic():
    md = "# T\n\ntext\n\n| A |\n|---|\n| x |\n"
    assert render_markdown(md) == render_markdown(md)


def test_render_fenced_code_block():
    md = "```\ngenbuild --tool ius\n<x>\n```\n"
    html = render_markdown(md)
    assert "<pre><code>" in html
    assert "genbuild --tool ius" in html
    assert "&lt;x&gt;" in html  # escaped inside code


def test_render_ordered_list_and_hr():
    md = "1. first\n2. second\n\n---\n"
    html = render_markdown(md)
    assert "<ol>" in html and "<li>first</li>" in html
    assert "<hr>" in html


def test_render_escaped_pipe_in_table_cell():
    # the region renderer escapes '|' as '\|'; the twin must show a literal '|'
    md = "| Col |\n|---|\n| a \\| b |\n"
    html = render_markdown(md)
    assert "<td>a | b</td>" in html


# --------------------------------------------------------------------------- #
# build end-to-end
# --------------------------------------------------------------------------- #

_FLAG_JSON = """\
{"ius flags translations": [
  {"flag name": "-snapshot_dir", "action": "replace"}
]}
"""


def _cfg() -> MonitorConfig:
    return MonitorConfig(
        version="1.0.0",
        root=".",
        region_templates={
            "flags": RegionTemplate(
                source="records",
                columns=(
                    RegionColumn(header="Flag", field="name"),
                    RegionColumn(header="Action", field="action"),
                ),
            )
        },
        documents=(
            DocumentSpec(
                id="ius",
                path="ius.md",
                audience=Audience.USER_GUIDE,
                html=True,
                region_keys=("flags",),
                code_refs=(
                    CodeRef(
                        path="ius_flags_translation.json",
                        extract="records",
                        lang="json",
                        json_records="*",
                        record_name_field="flag name",
                    ),
                ),
            ),
            DocumentSpec(
                id="core",
                path="core.md",
                audience=Audience.USER_GUIDE,
                html=True,
                code_refs=(),
            ),
        ),
    )


def _write_docs(root):
    (root / "ius_flags_translation.json").write_text(_FLAG_JSON)
    (root / "ius.md").write_text(
        "---\ncdm:\n  fingerprint: x\n---\n\n# IUS\n\n> The IUS plugin.\n\n"
        "See [core](core.md).\n\n"
        "<!-- CDM:BEGIN flags -->\n| Flag | Action |\n|---|---|\n"
        "| -snapshot_dir | replace |\n<!-- CDM:END flags -->\n"
    )
    (root / "core.md").write_text(
        "---\ncdm:\n  fingerprint: y\n---\n\n# Core\n\n> The genbuild command.\n"
    )


def test_build_writes_twins_with_valid_embedded_hash(tmp_path):
    _write_docs(tmp_path)
    written = build(_cfg(), tmp_path)
    assert {p.name for p in written} == {"ius.html", "core.html"}

    ius_html = (tmp_path / "ius.html").read_text()
    # embedded hash matches the md body -> lint_html_twin is clean
    body = parse_doc(tmp_path / "ius.md").body
    assert embedded_md_hash(ius_html) == md_source_hash(body)
    assert lint_html_twin(body, ius_html, doc_id="ius", html_path="ius.html") == []

    # content rendered, markers gone, table kept
    assert "CDM:BEGIN" not in ius_html
    assert "<td>-snapshot_dir</td>" in ius_html
    # intra-guide .md link rewritten to the .html twin
    assert 'href="core.html"' in ius_html
    # nav links to the sibling doc
    assert "core.html" in ius_html


def test_build_skips_missing_source(tmp_path):
    # core.md is never written -> build skips it, writes only ius.html
    (tmp_path / "ius_flags_translation.json").write_text(_FLAG_JSON)
    (tmp_path / "ius.md").write_text(
        "---\ncdm:\n  fingerprint: x\n---\n\n# IUS\n\n> The IUS plugin.\n"
    )
    written = build(_cfg(), tmp_path)
    assert {p.name for p in written} == {"ius.html"}


def test_build_subdir_nav_is_relative(tmp_path):
    (tmp_path / "plugins").mkdir()
    (tmp_path / "core.md").write_text(
        "---\ncdm:\n  fingerprint: y\n---\n\n# Core\n\n> Core.\n"
    )
    (tmp_path / "plugins" / "ius.md").write_text(
        "---\ncdm:\n  fingerprint: x\n---\n\n# IUS\n\n> IUS.\n"
    )
    cfg = MonitorConfig(
        version="1.0.0",
        root=".",
        documents=(
            DocumentSpec(
                id="core",
                path="core.md",
                audience=Audience.USER_GUIDE,
                html=True,
                code_refs=(),
            ),
            DocumentSpec(
                id="ius",
                path="plugins/ius.md",
                audience=Audience.USER_GUIDE,
                html=True,
                code_refs=(),
            ),
        ),
    )
    build(cfg, tmp_path)
    ius_html = (tmp_path / "plugins" / "ius.html").read_text()
    # nav link from plugins/ius.html up to core.html
    assert 'href="../core.html"' in ius_html


def test_build_title_falls_back_to_id(tmp_path):
    (tmp_path / "x.md").write_text(
        "---\ncdm:\n  fingerprint: x\n---\n\nNo heading here, just prose.\n"
    )
    cfg = MonitorConfig(
        version="1.0.0",
        root=".",
        documents=(
            DocumentSpec(
                id="my-doc",
                path="x.md",
                audience=Audience.USER_GUIDE,
                html=True,
                code_refs=(),
            ),
        ),
    )
    build(cfg, tmp_path)
    assert "<title>my-doc</title>" in (tmp_path / "x.html").read_text()


def test_build_nav_groups_by_section_with_short_labels(tmp_path):
    (tmp_path / "plugins").mkdir()
    (tmp_path / "core.md").write_text(
        "---\ncdm:\n  fingerprint: y\n---\n\n# Genbuild Core\n\n> Core.\n"
    )
    (tmp_path / "plugins" / "ius.md").write_text(
        "---\ncdm:\n  fingerprint: x\n---\n\n# IUS Simulation Plugin\n\n> IUS.\n"
    )
    # index.md is section-less (a top-level "home" link) and declared LAST.
    (tmp_path / "index.md").write_text(
        "---\ncdm:\n  fingerprint: z\n---\n\n# Home\n\n> Landing.\n"
    )
    cfg = MonitorConfig(
        version="1.0.0",
        root=".",
        documents=(
            DocumentSpec(
                id="core",
                path="core.md",
                audience=Audience.USER_GUIDE,
                html=True,
                nav_section="Genbuild",
                nav_label="Genbuild core",
                code_refs=(),
            ),
            DocumentSpec(
                id="ius",
                path="plugins/ius.md",
                audience=Audience.USER_GUIDE,
                html=True,
                nav_section="Plugins",
                nav_label="ius",
                code_refs=(),
            ),
            DocumentSpec(
                id="index",
                path="index.md",
                audience=Audience.USER_GUIDE,
                html=True,
                nav_label="Home",
                code_refs=(),
            ),
        ),
    )
    build(cfg, tmp_path)
    core_html = (tmp_path / "core.html").read_text()
    nav = core_html.split("<main>")[0]
    # section headings appear, in config order
    assert nav.index("<h2>Genbuild</h2>") < nav.index("<h2>Plugins</h2>")
    # the section-less doc renders first, above the section headings
    assert nav.index("index.html") < nav.index("<h2>Genbuild</h2>")
    # short labels used, not the page titles
    assert ">Genbuild core</a>" in nav
    assert ">ius</a>" in nav
    assert "IUS Simulation Plugin</a>" not in nav
    # current page is marked
    assert 'class="current"' in core_html


def test_build_flat_nav_when_no_sections(tmp_path):
    _write_docs(tmp_path)
    build(_cfg(), tmp_path)
    core_html = (tmp_path / "core.html").read_text()
    nav_part = core_html.split("<main>")[0]
    # no section headings in the nav; falls back to page titles
    assert "<h2>" not in nav_part
    assert ">IUS</a>" in nav_part


def test_build_only_html_docs(tmp_path):
    _write_docs(tmp_path)
    cfg = _cfg()
    # flip core to html=False -> only ius.html is written
    cfg = cfg.model_copy(
        update={
            "documents": (
                cfg.documents[0],
                cfg.documents[1].model_copy(update={"html": False}),
            )
        }
    )
    written = build(cfg, tmp_path)
    assert {p.name for p in written} == {"ius.html"}
