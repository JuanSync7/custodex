"""Layout Standard: structure lint, html pairing, scaffold, fix (CDM-08). TDD (K9).

Covers the pure surface of :mod:`custodex.layout` — every issue code, the
md/html hash helpers, the html-twin pairing rule, the scaffolder (which must
produce a doc that passes its own linter), and the front-matter auto-fix.

Features: FEAT-LAYOUT-001, FEAT-LAYOUT-002, FEAT-LAYOUT-003, FEAT-LAYOUT-004
Features: FEAT-LAYOUT-005, FEAT-LAYOUT-006, FEAT-LAYOUT-007
"""

from __future__ import annotations

from pathlib import Path

from custodex.config import Audience, CodeRef, DocumentSpec
from custodex.extract import build_document_surface
from custodex.layout import (
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
from custodex.manifest import parse_text

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
    from custodex.config import MonitorConfig
    from custodex.layout import lint_config

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
    from custodex.config import Audience as A
    from custodex.config import MonitorConfig
    from custodex.layout import lint_config

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
    from custodex.config import Audience as A
    from custodex.config import MonitorConfig
    from custodex.layout import lint_config

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


def test_index_coverage_respects_index_template_audience_kind(tmp_path: Path) -> None:
    """An index whose index region pins a `kind` audience need only link the
    documents that index actually renders — a sibling of another audience (e.g. a
    user-guide README under an eng-guide index) is NOT required (FEAT-CONFIGV2-016).

    This aligns INDEX_INCOMPLETE with what ``render_index`` emits (it filters by
    ``template.kind``): the eng-only api-index renders only eng-guide docs, so it
    is not flagged for omitting a user-guide doc the engine never lists there.
    """
    from custodex.config import Audience as A
    from custodex.config import MonitorConfig, RegionColumn, RegionTemplate
    from custodex.layout import _index_coverage_issues

    idx = DocumentSpec(
        id="index",
        path="index.md",
        audience=A.ENG_GUIDE,
        index=True,
        region_keys=("api-index",),
    )
    eng = DocumentSpec(id="eng", path="api/eng.md", audience=A.ENG_GUIDE)
    readme = DocumentSpec(id="readme", path="README.md", audience=A.USER_GUIDE)
    template = RegionTemplate(
        source="index",
        kind="eng-guide",
        columns=(RegionColumn(header="Document", field="title"),),
    )
    cfg = MonitorConfig(
        root=".",
        documents=(idx, eng, readme),
        region_templates={"api-index": template},
    )

    # The index links only the eng doc (not the user-guide README).
    _write_index(tmp_path, "- [eng](api/eng.md)")
    issues = _index_coverage_issues(cfg, tmp_path)
    assert [i.code for i in issues] == [], (
        "an eng-guide-scoped index must not be flagged for omitting a user-guide doc"
    )

    # If the index also forgets a same-audience (eng-guide) sibling, that IS flagged.
    eng2 = DocumentSpec(id="eng2", path="api/eng2.md", audience=A.ENG_GUIDE)
    cfg2 = MonitorConfig(
        root=".",
        documents=(idx, eng, eng2, readme),
        region_templates={"api-index": template},
    )
    issues2 = _index_coverage_issues(cfg2, tmp_path)
    assert [i.doc_id for i in issues2] == ["index"]
    assert "'eng2'" in issues2[0].detail


def test_index_coverage_requires_all_when_template_kind_is_none(tmp_path: Path) -> None:
    """An index whose index region renders ALL audiences (``kind`` is None) keeps
    the original target-agnostic rule: every other document must be linked,
    regardless of audience (back-compat with the pre-FEAT-CONFIGV2-016 behavior)."""
    from custodex.config import Audience as A
    from custodex.config import MonitorConfig, RegionColumn, RegionTemplate
    from custodex.layout import LayoutCode as LC
    from custodex.layout import _index_coverage_issues

    idx = DocumentSpec(
        id="index",
        path="index.md",
        audience=A.ENG_GUIDE,
        index=True,
        region_keys=("all-index",),
    )
    eng = DocumentSpec(id="eng", path="api/eng.md", audience=A.ENG_GUIDE)
    readme = DocumentSpec(id="readme", path="README.md", audience=A.USER_GUIDE)
    template = RegionTemplate(
        source="index",
        kind=None,  # renders every audience -> index must link every doc
        columns=(RegionColumn(header="Document", field="title"),),
    )
    cfg = MonitorConfig(
        root=".",
        documents=(idx, eng, readme),
        region_templates={"all-index": template},
    )

    _write_index(tmp_path, "- [eng](api/eng.md)")  # forgets the README
    issues = [
        i
        for i in _index_coverage_issues(cfg, tmp_path)
        if i.code is LC.INDEX_INCOMPLETE
    ]
    assert [i.doc_id for i in issues] == ["index"]
    assert "'readme'" in issues[0].detail


# --- B-05: per-region authority STATE surface (region_states) -----------------


def _fm(*, hashes: dict[str, str] | None = None) -> str:
    lines = [
        "---",
        "cdm:",
        "  schema_version: 1.0.0",
        "  audience: eng-guide",
        "  fingerprint: x",
    ]
    if hashes:
        lines.append("  region_hashes:")
        lines.extend(f"    {k}: {v}" for k, v in hashes.items())
    lines.append("---")
    return "\n".join(lines) + "\n"


def _region(rid: str, body: str) -> str:
    return f"<!-- CDM:BEGIN {rid} -->\n{body}\n<!-- CDM:END {rid} -->\n"


def _doc_with_region(rid: str, body: str, *, fm: str | None = None) -> object:
    head = fm if fm is not None else _fm()
    return parse_text(head + "# T\n\n> P.\n\n" + _region(rid, body))


def test_region_states_default_mode_is_generated() -> None:
    from custodex.blocks import known_region_ids
    from custodex.config import RegionMode
    from custodex.layout import region_states

    spec = _spec(region_keys=("symbols",))  # no region_modes -> generated
    doc = _doc_with_region("symbols", "body")
    known = known_region_ids(None)
    states = region_states(doc, spec, known=known)  # type: ignore[arg-type]
    assert len(states) == 1
    st = states[0]
    assert st.doc_id == "guide"
    assert st.region_id == "symbols"
    assert st.mode is RegionMode.GENERATED
    assert st.has_renderer is True
    assert st.locked is False
    assert st.advisory is False


def test_region_states_human_is_advisory() -> None:
    from custodex.blocks import known_region_ids
    from custodex.config import RegionMode
    from custodex.layout import region_states

    spec = _spec(region_keys=("symbols",), region_modes={"symbols": RegionMode.HUMAN})
    doc = _doc_with_region("symbols", "human prose")
    known = known_region_ids(None)
    st = region_states(doc, spec, known=known)[0]  # type: ignore[arg-type]
    assert st.mode is RegionMode.HUMAN
    assert st.advisory is True
    # human is advisory but not "locked" (locked is the llm-seeded human edit).
    assert st.locked is False


def test_region_states_llm_seeded_lock_state_tracks_hash() -> None:
    from custodex.blocks import known_region_ids
    from custodex.config import RegionMode
    from custodex.layout import region_states
    from custodex.manifest import region_body_hash

    body = "seeded then edited"
    known = known_region_ids(None)
    spec = _spec(
        region_keys=("symbols",), region_modes={"symbols": RegionMode.LLM_SEEDED}
    )
    # A DIFFERENT stored hash -> region_is_locked() reports it human-edited.
    stale = _fm(hashes={"symbols": "deadbeefdeadbeef"})
    locked_doc = _doc_with_region("symbols", body, fm=stale)
    st = region_states(locked_doc, spec, known=known)[0]  # type: ignore[arg-type]
    assert st.mode is RegionMode.LLM_SEEDED
    assert st.locked is True
    assert st.advisory is True  # a locked llm-seeded region is human-owned

    # A MATCHING stored hash -> unlocked (engine still owns it).
    matching = _fm(hashes={"symbols": region_body_hash(body)})
    unlocked_doc = _doc_with_region("symbols", body, fm=matching)
    st2 = region_states(unlocked_doc, spec, known=known)[0]  # type: ignore[arg-type]
    assert st2.locked is False
    assert st2.advisory is False


def test_region_states_llm_interim_has_no_renderer() -> None:
    """A pure-`llm` region with no built-in renderer is reported has_renderer=False
    (interim rule: behaves like generated; B-06 will add prose authoring)."""
    from custodex.blocks import known_region_ids
    from custodex.config import RegionMode
    from custodex.layout import region_states

    spec = _spec(region_keys=("intro",), region_modes={"intro": RegionMode.LLM})
    doc = _doc_with_region("intro", "prose")
    known = known_region_ids(None)
    st = region_states(doc, spec, known=known)[0]  # type: ignore[arg-type]
    assert st.mode is RegionMode.LLM
    assert st.has_renderer is False
    assert st.advisory is False  # interim llm is engine-owned, not human-owned


def test_region_states_ordered_by_region_keys_and_skips_undeclared() -> None:
    from custodex.blocks import known_region_ids
    from custodex.layout import region_states

    spec = _spec(region_keys=("symbols", "intro"))
    body = (
        "# T\n\n> P.\n\n"
        + _region("intro", "i")
        + "\n"
        + _region("symbols", "s")
        + "\n"
        + _region("stray", "x")
    )
    doc = parse_text(_fm() + body)
    known = known_region_ids(None)
    states = region_states(doc, spec, known=known)  # type: ignore[arg-type]
    # ordered by region_keys (symbols, intro), undeclared "stray" skipped.
    assert [s.region_id for s in states] == ["symbols", "intro"]


def test_config_region_states_across_docs(tmp_path: Path) -> None:
    from custodex.config import Audience as A
    from custodex.config import CodeRef, MonitorConfig, RegionMode
    from custodex.layout import config_region_states

    (tmp_path / "mod.py").write_text(_MODULE, encoding="utf-8")
    (tmp_path / "a.md").write_text(
        _fm() + "# A\n\n> P.\n\n" + _region("symbols", "b"), encoding="utf-8"
    )
    spec = DocumentSpec(
        id="a",
        path="a.md",
        audience=A.ENG_GUIDE,
        code_refs=(CodeRef(path="mod.py"),),
        region_keys=("symbols",),
        region_modes={"symbols": RegionMode.HUMAN},
    )
    # also a missing doc -> skipped, no crash
    missing = DocumentSpec(id="m", path="missing.md", audience=A.ENG_GUIDE)
    cfg = MonitorConfig(root=".", documents=(spec, missing))
    states = config_region_states(cfg, tmp_path)
    assert [(s.doc_id, s.region_id, s.mode.value) for s in states] == [
        ("a", "symbols", "human")
    ]


def test_config_region_states_skips_malformed_doc(tmp_path: Path) -> None:
    from custodex.config import Audience as A
    from custodex.config import MonitorConfig
    from custodex.layout import config_region_states

    # An unterminated region -> parse_doc -> regions() raises DriftError, which
    # config_region_states swallows (lint_doc reports the structural issue).
    (tmp_path / "bad.md").write_text(
        _fm() + "# T\n\n> P.\n\n<!-- CDM:BEGIN x -->\nunterminated\n",
        encoding="utf-8",
    )
    spec = DocumentSpec(
        id="bad", path="bad.md", audience=A.ENG_GUIDE, region_keys=("x",)
    )
    cfg = MonitorConfig(root=".", documents=(spec,))
    assert config_region_states(cfg, tmp_path) == []
