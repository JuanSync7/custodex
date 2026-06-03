"""Layout Standard: structure lint, html pairing, scaffold, fix (CDM-08). TDD (K9).

Covers the pure surface of :mod:`code_doc_monitor.layout` — every issue code, the
md/html hash helpers, the html-twin pairing rule, the scaffolder (which must
produce a doc that passes its own linter), and the front-matter auto-fix.
"""

from __future__ import annotations

from pathlib import Path

from code_doc_monitor.config import Audience, CodeRef, DocumentSpec
from code_doc_monitor.extract import build_document_surface
from code_doc_monitor.layout import (
    LAYOUT_VERSION,
    LayoutCode,
    embedded_md_hash,
    html_twin_path,
    lint_doc,
    lint_html_twin,
    md_source_hash,
    scaffold_doc,
    stamp_doc_meta,
)
from code_doc_monitor.manifest import parse_text

# --- a tiny target module so surfaces resolve against real AST ----------------

_MODULE = '''\
"""A sample module."""


def greet(name: str) -> str:
    return f"hi {name}"
'''


def _spec(**kw: object) -> DocumentSpec:
    base: dict[str, object] = dict(
        id="guide",
        path="docs/guide.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="mod.py"),),
        region_keys=("symbols",),
    )
    base.update(kw)
    return DocumentSpec(**base)  # type: ignore[arg-type]


def _surface(tmp_path: Path, spec: DocumentSpec) -> object:
    (tmp_path / "mod.py").write_text(_MODULE, encoding="utf-8")
    return build_document_surface(spec, tmp_path)


# --- hash helpers -------------------------------------------------------------


def test_md_source_hash_is_stable_and_crlf_normalized() -> None:
    assert md_source_hash("a\nb\n") == md_source_hash("a\r\nb\r\n")
    assert len(md_source_hash("x")) == 16
    assert md_source_hash("x") != md_source_hash("y")


def test_embedded_md_hash_reads_both_meta_names() -> None:
    h = "0123456789abcdef"
    cdm = f'<meta name="code-doc-md-sha256" content="{h}">'
    helium = f'<meta name="helium-docs-md-sha256" content="{h}" />'
    assert embedded_md_hash(cdm) == h
    assert embedded_md_hash(helium) == h
    assert embedded_md_hash("<html>no hash here</html>") is None


# --- scaffold round-trips through the linter ----------------------------------


def test_scaffold_doc_passes_lint_and_is_in_sync(tmp_path: Path) -> None:
    spec = _spec()
    surface = _surface(tmp_path, spec)
    text = scaffold_doc(spec, surface)
    doc = parse_text(text, tmp_path / spec.path)
    assert lint_doc(doc, spec) == []
    # front matter carries all three managed keys
    cdm = doc.meta["cdm"]
    assert cdm["schema_version"] == LAYOUT_VERSION
    assert cdm["audience"] == "eng-guide"
    assert cdm["fingerprint"] == surface.surface_hash()


# --- front-matter rules -------------------------------------------------------


def test_lint_flags_missing_front_matter() -> None:
    doc = parse_text("# Title\n\n> Purpose.\n")
    codes = {i.code for i in lint_doc(doc, _spec(region_keys=()))}
    assert LayoutCode.MISSING_FRONT_MATTER in codes


def test_lint_flags_each_missing_managed_key() -> None:
    doc = parse_text("---\ncdm:\n  other: 1\n---\n# T\n\n> P.\n")
    codes = {i.code for i in lint_doc(doc, _spec(region_keys=()))}
    assert LayoutCode.MISSING_SCHEMA_VERSION in codes
    assert LayoutCode.MISSING_AUDIENCE in codes
    assert LayoutCode.MISSING_FINGERPRINT in codes


def test_lint_flags_version_and_audience_mismatch() -> None:
    fm = (
        "---\ncdm:\n  schema_version: '9.9.9'\n"
        "  audience: user-guide\n  fingerprint: abc\n---\n"
    )
    doc = parse_text(fm + "# T\n\n> P.\n")
    codes = {i.code for i in lint_doc(doc, _spec(region_keys=()))}  # spec eng-guide
    assert LayoutCode.SCHEMA_VERSION_MISMATCH in codes
    assert LayoutCode.AUDIENCE_MISMATCH in codes


# --- title / purpose anchors --------------------------------------------------


def _good_fm() -> str:
    return (
        f"---\ncdm:\n  schema_version: '{LAYOUT_VERSION}'\n"
        "  audience: eng-guide\n  fingerprint: abc\n---\n"
    )


def test_lint_flags_missing_title() -> None:
    doc = parse_text(_good_fm() + "no heading here\n")
    codes = {i.code for i in lint_doc(doc, _spec(region_keys=()))}
    assert LayoutCode.MISSING_TITLE in codes


def test_lint_flags_missing_purpose() -> None:
    doc = parse_text(_good_fm() + "# Title\n\njust prose, no blockquote\n")
    codes = {i.code for i in lint_doc(doc, _spec(region_keys=()))}
    assert LayoutCode.MISSING_PURPOSE in codes


# --- region declaration consistency ------------------------------------------


def test_lint_flags_undeclared_region() -> None:
    body = "# T\n\n> P.\n\n<!-- CDM:BEGIN extra -->\nx\n<!-- CDM:END extra -->\n"
    doc = parse_text(_good_fm() + body)
    codes = {i.code for i in lint_doc(doc, _spec(region_keys=()))}
    assert LayoutCode.UNDECLARED_REGION in codes


def test_lint_flags_missing_declared_region() -> None:
    doc = parse_text(_good_fm() + "# T\n\n> P.\n")
    codes = {i.code for i in lint_doc(doc, _spec(region_keys=("symbols",)))}
    assert LayoutCode.MISSING_REGION in codes


def test_lint_flags_malformed_structure() -> None:
    body = "# T\n\n> P.\n\n<!-- CDM:BEGIN a -->\nunterminated\n"
    doc = parse_text(_good_fm() + body)
    codes = {i.code for i in lint_doc(doc, _spec(region_keys=("a",)))}
    assert LayoutCode.MALFORMED_STRUCTURE in codes


# --- html twin pairing --------------------------------------------------------


def test_html_twin_path_maps_suffix() -> None:
    assert html_twin_path("docs/x/guide.md") == "docs/x/guide.html"


def test_lint_html_twin_missing_not_derived_and_stale() -> None:
    body = "# T\n\n> P.\n"
    h = md_source_hash(body)
    # missing file
    miss = lint_html_twin(body, None, doc_id="g", html_path="g.html")
    assert miss[0].code == LayoutCode.HTML_MISSING
    # present but no embedded hash
    nd = lint_html_twin(body, "<html>no hash</html>", doc_id="g", html_path="g.html")
    assert nd[0].code == LayoutCode.HTML_NOT_DERIVED
    # stale embedded hash
    stale_html = '<meta name="code-doc-md-sha256" content="deadbeefdeadbeef">'
    st = lint_html_twin(body, stale_html, doc_id="g", html_path="g.html")
    assert st[0].code == LayoutCode.HTML_STALE
    # in sync -> no issues
    fresh = f'<meta name="code-doc-md-sha256" content="{h}">'
    assert lint_html_twin(body, fresh, doc_id="g", html_path="g.html") == []


# --- front-matter auto-fix ----------------------------------------------------


def test_stamp_doc_meta_fills_static_keys_and_preserves_fingerprint() -> None:
    doc = parse_text("---\ncdm:\n  fingerprint: keepme\n---\n# T\n\n> P.\n")
    spec = _spec(region_keys=())
    fixed = parse_text(stamp_doc_meta(doc, spec))
    cdm = fixed.meta["cdm"]
    assert cdm["schema_version"] == LAYOUT_VERSION
    assert cdm["audience"] == "eng-guide"
    assert cdm["fingerprint"] == "keepme"  # untouched
    assert lint_doc(fixed, spec) == []  # now conformant


# --- lint_config edge cases (missing file, malformed front matter) -----------


def test_lint_config_skips_missing_doc_and_reports_malformed(tmp_path: Path) -> None:
    from code_doc_monitor.config import MonitorConfig
    from code_doc_monitor.layout import lint_config

    (tmp_path / "mod.py").write_text(_MODULE, encoding="utf-8")
    # doc A: file is absent -> lint skips it (check owns existence).
    spec_a = _spec(id="a", path="a.md", region_keys=())
    # doc B: front matter is a non-mapping -> MALFORMED_STRUCTURE.
    spec_b = _spec(id="b", path="b.md", region_keys=())
    (tmp_path / "b.md").write_text("---\n- just\n- a list\n---\n# T\n\n> P.\n", "utf-8")
    cfg = MonitorConfig(root=".", documents=(spec_a, spec_b))

    codes = {(i.doc_id, i.code) for i in lint_config(cfg, tmp_path)}
    assert ("a", LayoutCode.MISSING_TITLE) not in {(d, c) for d, c in codes}
    assert ("b", LayoutCode.MALFORMED_STRUCTURE) in codes


def test_lint_flags_missing_title_on_empty_body() -> None:
    doc = parse_text(_good_fm())  # front matter only, no body
    codes = {i.code for i in lint_doc(doc, _spec(region_keys=()))}
    assert LayoutCode.MISSING_TITLE in codes


def test_scaffold_unknown_region_emits_todo(tmp_path: Path) -> None:
    spec = _spec(region_keys=("symbols", "mystery"))
    surface = _surface(tmp_path, spec)
    text = scaffold_doc(spec, surface)
    assert "<!-- CDM:BEGIN mystery -->" in text
    assert "TODO: content for 'mystery'" in text


# --- index coverage (b): a landing page must link every other doc -------------


def _write_index(tmp_path: Path, body_links: str) -> None:
    (tmp_path / "index.md").write_text(
        f"---\ncdm:\n  schema_version: 1.0.0\n  audience: user-guide\n"
        f"  fingerprint: x\n---\n# Index\n\n> Landing page.\n\n{body_links}\n",
        encoding="utf-8",
    )


def test_index_coverage_flags_unlinked_doc(tmp_path: Path) -> None:
    from code_doc_monitor.config import Audience as A
    from code_doc_monitor.config import MonitorConfig
    from code_doc_monitor.layout import lint_config

    idx = DocumentSpec(
        id="index", path="index.md", audience=A.USER_GUIDE, index=True, html=True
    )
    a = DocumentSpec(id="a", path="plugins/a.md", audience=A.USER_GUIDE, html=True)
    b = DocumentSpec(id="b", path="plugins/b.md", audience=A.USER_GUIDE, html=True)
    cfg = MonitorConfig(root=".", documents=(idx, a, b))

    # links a (.md) but forgets b -> exactly one INDEX_INCOMPLETE, naming b.
    _write_index(tmp_path, "- [a](plugins/a.md)")
    all_issues = lint_config(cfg, tmp_path)
    issues = [i for i in all_issues if i.code == LayoutCode.INDEX_INCOMPLETE]
    assert [i.doc_id for i in issues] == ["index"]
    assert "'b'" in issues[0].detail


def test_index_coverage_accepts_md_or_html_links(tmp_path: Path) -> None:
    from code_doc_monitor.config import Audience as A
    from code_doc_monitor.config import MonitorConfig
    from code_doc_monitor.layout import lint_config

    idx = DocumentSpec(
        id="index", path="index.md", audience=A.USER_GUIDE, index=True, html=True
    )
    a = DocumentSpec(id="a", path="plugins/a.md", audience=A.USER_GUIDE, html=True)
    b = DocumentSpec(id="b", path="plugins/b.md", audience=A.USER_GUIDE, html=True)
    cfg = MonitorConfig(root=".", documents=(idx, a, b))

    # a linked by .md, b linked by its .html twin -> both count, no issue.
    _write_index(tmp_path, "- [a](plugins/a.md)\n- [b](plugins/b.html)")
    codes = {i.code for i in lint_config(cfg, tmp_path)}
    assert LayoutCode.INDEX_INCOMPLETE not in codes
