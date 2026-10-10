"""FM-SPLICE: a front-matter write rewrites only what changed (KEEL-01 F9, F5).

``render_doc(meta, body, source=...)`` splices the new ``meta`` into the
front matter that ``source`` already carries. An entry whose value did not
change keeps its exact bytes (comments, quoting, flow style, folding); only a
changed or new entry is dumped (losing every comment inside it), and the ``cdm``
block is always dumped with its keys sorted (K10). The splice runs only on a
column-0 block mapping with no duplicate, ``<<`` or aliased top-level key (the
spans need it; the parse-back cannot see a mis-cut span) and only when the
result parses back to exactly ``meta``; any other layout is dumped fresh
instead, which is data-exact but not byte-preserving.

Without a source fence (or when the splice is refused) the fresh dump keeps
``meta``'s key order, sorts only ``cdm``, writes non-ASCII text literally
(allow_unicode) and is deterministic across hash seeds.

Features: FEAT-LAYOUT-010, FEAT-LAYOUT-011
"""

from __future__ import annotations

import ast
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from custodex.backends import MockBackend
from custodex.config import (
    Audience,
    MonitorConfig,
    load_config,
    load_config_dir,
    resolve_repo_root,
)
from custodex.docwriter import OVERVIEW_REGION, _author_overview, build_doc_spec
from custodex.errors import DriftError
from custodex.extract import build_document_surface
from custodex.layout import scaffold_doc
from custodex.manifest import (
    parse_doc,
    parse_text,
    regions,
    render_doc,
    set_fingerprint,
    set_region_hash,
    stamp_standard_meta,
)

_REPO = Path(__file__).resolve().parents[2]


def _stamp(meta: dict[str, Any]) -> dict[str, Any]:
    return stamp_standard_meta(meta, schema_version="1.0.0", audience="eng-guide")


# --- the slice's red tests --------------------------------------------------


def test_render_doc_splices_a_sorted_cdm_block_in_place() -> None:
    """Only the changed ``cdm`` entry is rewritten, sorted, where it stood."""
    source = (
        "---\n"
        "title: T  # the title\n"
        "cdm:\n"
        "  fingerprint: old\n"
        "# after cdm\n"
        "tags: [a, b]\n"
        "---\n"
        "body\n"
    )
    meta = {
        "title": "T",
        "cdm": {"schema_version": "1.0.0", "fingerprint": "new", "audience": "x"},
        "tags": ["a", "b"],
    }
    assert render_doc(meta, "body\n", source=source) == (
        "---\n"
        "title: T  # the title\n"
        "cdm:\n"
        "  audience: x\n"
        "  fingerprint: new\n"
        "  schema_version: 1.0.0\n"
        "# after cdm\n"
        "tags: [a, b]\n"
        "---\n"
        "body\n"
    )  # Feature: FEAT-LAYOUT-010


def test_no_frontmatter_doc_plus_unicode() -> None:
    """A doc with no fence gets a fresh, sorted ``cdm`` block written literally (F5)."""
    meta = set_region_hash({}, "résumé", "c" * 16)
    meta = set_fingerprint(meta, "f" * 16)
    expected = (
        "---\n"
        "cdm:\n"
        "  fingerprint: ffffffffffffffff\n"
        "  region_hashes:\n"
        "    résumé: cccccccccccccccc\n"
        "---\n"
        "# Body\n"
    )
    assert render_doc(meta, "# Body\n", source="# Body\n") == expected
    assert render_doc(meta, "# Body\n") == expected  # Feature: FEAT-LAYOUT-011


def _managed_docs() -> list[Path]:
    configs: list[tuple[Path, MonitorConfig]] = []
    for config_dir in (_REPO / "config" / "cdmon", _REPO / "demo" / "config" / "cdmon"):
        configs.append((config_dir, load_config_dir(config_dir)))
    for config_file in (
        _REPO / "examples" / "external-repo" / "cdmon.yaml",
        _REPO / "examples" / "multilang" / "cdmon.yaml",
    ):
        configs.append((config_file.parent, load_config(config_file)))
    paths: set[Path] = set()
    for config_dir, config in configs:
        root = resolve_repo_root(config_dir, config.root)
        for spec in config.documents:
            path = root / spec.path
            if path.is_file():
                paths.add(path)
    return sorted(paths)


def test_dogfood_docs_render_byte_identical() -> None:
    """Every managed doc of the 4 shipped configs re-renders to its own bytes.

    With its own text as the source the result is the stored text (K7). The
    fresh dump (no source) must also reproduce it: these docs carry only the
    engine's ``cdm`` block, so the new dump agrees with every stamp already
    written, and no shipped doc moves when this slice lands.
    """
    docs = _managed_docs()
    assert len(docs) >= 20  # a pass over zero docs proves nothing
    with_front_matter = 0
    for path in docs:
        doc = parse_doc(path)
        assert render_doc(doc.meta, doc.body, source=doc.raw) == doc.raw, path
        if doc.meta:
            with_front_matter += 1
            assert render_doc(doc.meta, doc.body) == doc.raw, path
    assert with_front_matter >= 20  # Feature: FEAT-LAYOUT-011


# The seven doc writers, by (module, enclosing function). Each passes the text it
# parsed as ``source=`` so a write keeps the doc's own front-matter bytes;
# ``scaffold_doc`` writes a brand-new doc and passes ``source=None`` on purpose.
_WRITERS = {
    ("custodex/heal.py", "_corrected"),
    ("custodex/heal.py", "_stamp_region_hashes"),
    ("custodex/layout.py", "scaffold_doc"),
    ("custodex/layout.py", "stamp_doc_meta"),
    ("custodex/docwriter.py", "_author_overview"),
    ("custodex/spmirror.py", "_write_body_preserving_meta"),
    ("custodex/docdeps.py", "stamp_edges"),
}
_NEW_DOC_WRITERS = {("custodex/layout.py", "scaffold_doc")}
# Modules allowed to build a ``---\n`` fence themselves: manifest.render_doc is
# the one managed-doc writer, and okf renders its OKF export concepts, which are
# not managed docs.
_FENCE_MODULES = {"custodex/manifest.py", "custodex/okf.py"}


def _render_doc_calls(tree: ast.AST) -> list[tuple[str, ast.Call]]:
    found: list[tuple[str, ast.Call]] = []

    def visit(node: ast.AST, func: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = func
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                name = child.name
            if isinstance(child, ast.Call):
                callee = child.func
                called = (
                    callee.id
                    if isinstance(callee, ast.Name)
                    else callee.attr
                    if isinstance(callee, ast.Attribute)
                    else None
                )
                if called == "render_doc":
                    found.append((name, child))
            visit(child, name)

    visit(tree, "<module>")
    return found


def _is_body_text(node: ast.expr) -> bool:
    """``doc.body`` / ``body``: text that has already lost its front matter."""
    if isinstance(node, ast.Attribute):
        return node.attr == "body"
    return isinstance(node, ast.Name) and node.id == "body"


def test_every_writer_goes_through_render_doc() -> None:
    """The seven writers call render_doc with the text they parsed as ``source=``.

    A writer that drops ``source=`` (or passes the body, which has no fence)
    brings back the whole-block re-render that KEEL-01 F9 records. No other
    module builds a managed-doc fence by hand.
    """
    writers: set[tuple[str, str]] = set()
    fences: list[str] = []
    for path in sorted((_REPO / "custodex").rglob("*.py")):
        rel = path.relative_to(_REPO).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func, call in _render_doc_calls(tree):
            if rel == "custodex/manifest.py":
                continue
            writers.add((rel, func))
            kwargs = {kw.arg: kw.value for kw in call.keywords}
            assert "source" in kwargs, f"{rel}:{call.lineno} {func} omits source="
            value = kwargs["source"]
            is_none = isinstance(value, ast.Constant) and value.value is None
            assert is_none == ((rel, func) in _NEW_DOC_WRITERS), (rel, func)
            assert not _is_body_text(value), f"{rel}:{call.lineno} passes the body"
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.JoinedStr)
                and node.values
                and isinstance(node.values[0], ast.Constant)
                and str(node.values[0].value).startswith("---\n")
                and rel not in _FENCE_MODULES
            ):
                fences.append(f"{rel}:{node.lineno}")
    assert writers == _WRITERS
    assert fences == []  # Feature: FEAT-LAYOUT-010


def test_the_overview_author_keeps_a_house_front_matter_block(tmp_path: Path) -> None:
    """docwriter's write keeps foreign front matter (behaviour, not just the AST).

    ``cdx write-doc`` hands ``_author_overview`` a freshly scaffolded doc, whose
    fresh dump equals the splice; a doc that already carries house front matter
    is the case that tells ``source=`` from ``source=None``.
    """
    (tmp_path / "gamma.py").write_text('def boost(x):\n    """B."""\n', "utf-8")
    spec = build_doc_spec(
        doc_id="gamma",
        path="gamma.md",
        audience=Audience.ENG_GUIDE,
        code_refs=("gamma.py",),
    )
    surface = build_document_surface(spec, tmp_path)
    house = "---\ntitle: 'Gamma'  # house\ntags: [a, b]\n---\n"
    scaffold = scaffold_doc(spec, surface)
    doc_text = house + parse_text(scaffold).body
    out = _author_overview(
        spec, surface, doc_text, backend=MockBackend(), style_guidance=None
    )
    assert out.startswith(house)
    assert "boost" in regions(parse_text(out))[OVERVIEW_REGION]


# --- the no-change fast path and exact-type equality -----------------------


def test_an_unchanged_meta_keeps_any_layout_verbatim() -> None:
    """With nothing changed, the source block comes back byte for byte (K7)."""
    layouts = [
        "---\n{title: T, tags: [a, b]}\n---\nx\n",  # flow root
        "---\n  title: T\n  draft: true\n---\nx\n",  # indented root
        "---\ntitle: a\ntitle: b\n---\nx\n",  # duplicate keys
        "---\n_d: &b\n  k: 1\n<<: *b\ntitle: T\n---\nx\n",  # merge key
        "---\ntitle: T\n...\n---\nx\n",  # document-end marker
        "---\n# head\ntitle: 'T'  # q\nn: !!float 1\n---\nx\n",
        "---\nloop: &l\n  - *l\n---\nx\n",  # self-reference
        "---\nring: &r\n  next: *r\n---\nx\n",  # self-referencing mapping
    ]
    for source in layouts:
        doc = parse_text(source)
        assert render_doc(doc.meta, doc.body, source=source) == source, source


def test_a_bool_replacing_an_int_is_written_when_nothing_else_changed() -> None:
    """``1`` and ``True`` compare equal in Python; the stored text must still change."""
    source = "---\nflag: 1\n---\nb\n"
    assert render_doc({"flag": True}, "b\n", source=source) == (
        "---\nflag: true\n---\nb\n"
    )


def test_an_equal_value_of_another_type_is_rewritten() -> None:
    source = "---\ncount: 1\nflag: 0\n---\nb\n"
    out = render_doc({"count": 1.0, "flag": False}, "b\n", source=source)
    assert out == "---\ncount: 1.0\nflag: false\n---\nb\n"


def test_a_retyped_value_is_spliced_and_its_neighbours_keep_their_bytes() -> None:
    source = "---\ntags: [a]\ncount: 1\n---\nb\n"
    out = render_doc({"tags": ["a"], "count": 1.0}, "b\n", source=source)
    assert out == "---\ntags: [a]\ncount: 1.0\n---\nb\n"


def test_type_strictness_and_nan_hold_inside_lists() -> None:
    out = render_doc({"v": [1.0]}, "b\n", source="---\nv: [1]\n---\nb\n")
    assert type(parse_text(out).meta["v"][0]) is float
    source = "---\nv: [.nan, 1]\ntitle: T\n---\nb\n"
    doc = parse_text(source)
    assert render_doc(doc.meta, doc.body, source=source) == source


def test_a_value_changed_to_nan_is_written() -> None:
    source = "---\nratio: 0.5\n---\nb\n"
    assert render_doc({"ratio": float("nan")}, "b\n", source=source) == (
        "---\nratio: .nan\n---\nb\n"
    )


def test_a_number_that_replaced_a_nan_is_written() -> None:
    source = "---\nratio: .nan\n---\nb\n"
    assert render_doc({"ratio": 0.5}, "b\n", source=source) == (
        "---\nratio: 0.5\n---\nb\n"
    )


def test_a_tuple_in_meta_matches_its_list_spelling() -> None:
    """A tuple and the list it dumps as are the same data, so the bytes stay."""
    source = "---\ntags: [a, b]\ntitle: T\n---\nx\n"
    assert render_doc({"tags": ("a", "b"), "title": "T"}, "x\n", source=source) == (
        source
    )
    assert render_doc({"tags": ("a", "c")}, "x\n") == "---\ntags:\n- a\n- c\n---\nx\n"


# --- the splice: what is kept, what is replaced -----------------------------


def test_a_removed_entry_is_dropped_and_its_neighbours_kept() -> None:
    source = "---\ntitle: T\ndraft: true\ntags: [a]\n---\nx\n"
    out = render_doc({"title": "T", "tags": ["a"]}, "x\n", source=source)
    assert out == "---\ntitle: T\ntags: [a]\n---\nx\n"


def test_dropping_every_entry_keeps_the_fence_and_its_head_comment() -> None:
    source = "---\n# keep\ntitle: T\n---\nb\n"
    assert render_doc({}, "b\n", source=source) == "---\n# keep\n---\nb\n"


def test_an_empty_meta_keeps_a_comment_only_fence() -> None:
    source = "---\n# only a comment\n---\nb\n"
    assert render_doc({}, "b\n", source=source) == source


def test_an_empty_fence_is_spliced_like_any_other() -> None:
    source = "---\n---\nb\n"
    assert render_doc({}, "b\n", source=source) == source
    assert render_doc({"cdm": {"a": 1}}, "b\n", source=source) == (
        "---\ncdm:\n  a: 1\n---\nb\n"
    )


def test_a_new_key_lands_where_meta_puts_it() -> None:
    source = "---\ntitle: T\ntags: [a]\n---\nb\n"
    out = render_doc({"new": 1, "title": "T", "tags": ["a"]}, "b\n", source=source)
    assert out == "---\nnew: 1\ntitle: T\ntags: [a]\n---\nb\n"


def test_kept_entries_follow_meta_order_when_a_value_changes() -> None:
    """Data-equal meta keeps the source verbatim; otherwise meta's order wins."""
    source = "---\na: [1]\nb: [2]\n---\nx\n"
    assert render_doc({"b": [2], "a": [1]}, "x\n", source=source) == source
    out = render_doc({"b": [2], "a": [1], "cdm": {"f": 1}}, "x\n", source=source)
    assert out == "---\nb: [2]\na: [1]\ncdm:\n  f: 1\n---\nx\n"


def test_a_comment_only_fence_keeps_its_head_comment_when_meta_gains_entries() -> None:
    source = "---\n# house\n---\nb\n"
    assert render_doc({"cdm": {"a": 1}}, "b\n", source=source) == (
        "---\n# house\ncdm:\n  a: 1\n---\nb\n"
    )


def test_a_changed_entry_drops_its_inline_comment() -> None:
    """An inline comment goes with the old value; comment LINES after it stay."""
    source = "---\nowner: TBD  # keep\n# about owner\ntags: [a]\n---\nx\n"
    out = render_doc({"owner": "me", "tags": ["a"]}, "x\n", source=source)
    assert out == "---\nowner: me\n# about owner\ntags: [a]\n---\nx\n"


def test_a_changed_entry_loses_the_comments_inside_it() -> None:
    """A re-dumped entry loses EVERY comment between its key and its last value line.

    That is its inline comment, comment lines inside a nested block and nested
    inline comments; in practice the ``cdm:`` block, which every engine write
    changes. Only the comment and blank lines after the entry stay.
    """
    source = (
        "---\ntitle: T\ncdm:\n  # managed by custodex: do not hand-edit\n"
        "  audience: user-guide  # was user-facing\n  schema_version: '1'\n"
        "# after cdm\n---\nbody\n"
    )
    meta = {"title": "T", "cdm": {"audience": "eng-guide", "schema_version": "1"}}
    out = render_doc(meta, "body\n", source=source)
    assert out == (
        "---\ntitle: T\ncdm:\n  audience: eng-guide\n  schema_version: '1'\n"
        "# after cdm\n---\nbody\n"
    )


def test_a_multi_line_flow_collection_is_replaced_whole() -> None:
    mapping = "---\ncdm: {a: 1,\n  b: 2}\n# keep\ntitle: T\n---\nx\n"
    out = render_doc({"cdm": {"a": 1, "b": 3}, "title": "T"}, "x\n", source=mapping)
    assert out == "---\ncdm:\n  a: 1\n  b: 3\n# keep\ntitle: T\n---\nx\n"
    listing = "---\ntags: [a,\n  b]\n# keep\ntitle: T\n---\nx\n"
    out = render_doc({"tags": ["a", "c"], "title": "T"}, "x\n", source=listing)
    assert out == "---\ntags:\n- a\n- c\n# keep\ntitle: T\n---\nx\n"


def test_a_changed_block_list_keeps_the_comment_after_it() -> None:
    source = "---\ntags:\n- a\n- b\n# about tags\ntitle: T\n---\nx\n"
    out = render_doc({"tags": ["a", "c"], "title": "T"}, "x\n", source=source)
    assert out == "---\ntags:\n- a\n- c\n# about tags\ntitle: T\n---\nx\n"


def test_a_whitespace_only_line_after_a_changed_block_scalar_stays() -> None:
    source = "---\nnote: |\n  old\n \n# c\ntitle: T\n---\nx\n"
    out = render_doc({"note": "new", "title": "T"}, "x\n", source=source)
    assert out == "---\nnote: new\n \n# c\ntitle: T\n---\nx\n"


def test_an_alias_on_the_line_after_its_key_belongs_to_its_entry() -> None:
    source = "---\nbase: &b [k]\nuse:\n  *b\n# after use\ntitle: T\n---\nx\n"
    meta = parse_text(source).meta
    out = render_doc({**meta, "title": "U"}, "x\n", source=source)
    assert out == source.replace("title: T", "title: U")
    out = render_doc({**meta, "use": ["z"]}, "x\n", source=source)
    assert out == "---\nbase: &b [k]\nuse:\n- z\n# after use\ntitle: T\n---\nx\n"


def test_a_new_cdm_entry_spliced_into_a_house_block_is_written_literally() -> None:
    """The first heal of a house block with no ``cdm:`` yet takes the new-entry path."""
    source = "---\ntitle: T\ntags: [a]\n---\nb\n"
    meta = set_region_hash(parse_text(source).meta, "résumé", "c" * 16)
    assert render_doc(meta, "b\n", source=source) == (
        "---\ntitle: T\ntags: [a]\ncdm:\n  region_hashes:\n"
        "    résumé: cccccccccccccccc\n---\nb\n"
    )


def test_a_changed_entry_is_dumped_with_allow_unicode() -> None:
    source = "---\ntitle: Ünïcode\ncdm:\n  region_hashes:\n    a: x\n---\nb\n"
    meta = set_region_hash(parse_text(source).meta, "é", "y")
    assert render_doc(meta, "b\n", source=source) == (
        "---\ntitle: Ünïcode\ncdm:\n  region_hashes:\n    a: x\n    é: y\n---\nb\n"
    )


# --- layouts the splice refuses: a data-exact fresh dump ---------------------


def test_an_indented_root_falls_back_to_a_valid_fresh_dump() -> None:
    """An indented root is re-dumped; dropping a key never corrupts the fence."""
    source = "---\n  title: T\n  draft: true\n---\n# Body\n"
    assert render_doc({"title": "T"}, "# Body\n", source=source) == (
        "---\ntitle: T\n---\n# Body\n"
    )
    assert render_doc({}, "# Body\n", source=source) == "# Body\n"


def test_a_top_level_merge_key_falls_back_data_exact() -> None:
    source = "---\n_defs: &base\n  kind: readme\n<<: *base\ntitle: T\n---\nx\n"
    meta = _stamp(parse_text(source).meta)
    out = render_doc(meta, "x\n", source=source)
    again = parse_text(out)
    assert again.meta == meta
    assert render_doc(again.meta, again.body, source=out) == out  # K7


def test_a_document_end_marker_and_what_follows_it_stay_last() -> None:
    """A ``...`` closes the block: new entries land before it, its trailer stays."""
    source = "---\ntitle: T  # keep\nupdated: 2026-09-02\n...\n# after\n---\nx\n"
    meta = _stamp(parse_text(source).meta)
    out = render_doc(meta, "x\n", source=source)
    assert out == (
        "---\ntitle: T  # keep\nupdated: 2026-09-02\n"
        "cdm:\n  audience: eng-guide\n  schema_version: 1.0.0\n...\n# after\n---\nx\n"
    )
    again = parse_text(out)
    assert again.meta == meta
    assert render_doc(again.meta, again.body, source=out) == out  # K7
    twice = "---\ntitle: T\n... # end\n...\n---\nx\n"  # the first marker cuts
    assert render_doc({"title": "U"}, "x\n", source=twice) == (
        "---\ntitle: U\n... # end\n...\n---\nx\n"
    )


def test_duplicate_top_level_keys_fall_back_to_a_fresh_dump() -> None:
    """Dead duplicate text cannot keep its place, so the block is re-dumped whole.

    Splicing would keep ``kind``'s inline comment but silently delete the first
    ``title`` line and the comment under it; a fresh dump makes the loss uniform
    and documented instead of partial.
    """
    source = (
        "---\ntitle: Draft\n# superseded\nkind: readme  # house\ntitle: Final\n---\nx\n"
    )
    meta = _stamp(parse_text(source).meta)
    assert render_doc(meta, "x\n", source=source) == (
        "---\ntitle: Final\nkind: readme\n"
        "cdm:\n  audience: eng-guide\n  schema_version: 1.0.0\n---\nx\n"
    )
    quoted = '---\ntags: [a]\ndup: a\n"dup": b\n---\nx\n'  # same key, other spelling
    out = render_doc({"tags": ["a"], "dup": "b", "cdm": {"f": 1}}, "x\n", source=quoted)
    assert out == "---\ntags:\n- a\ndup: b\ncdm:\n  f: 1\n---\nx\n"


def test_an_alias_into_a_changed_entry_falls_back_data_exact() -> None:
    """``mirror: *c`` points into the ``cdm`` the write replaces: re-dump, same data."""
    source = "---\nbase: &b [1]\ncdm: &c {x: 1}\nmirror: *c\n---\nx\n"
    meta = _stamp(parse_text(source).meta)
    out = render_doc(meta, "x\n", source=source)
    assert parse_text(out).meta == meta
    assert "&b" not in out  # not byte-preserving: the documented fallback
    assert render_doc(parse_text(out).meta, "x\n", source=out) == out  # K7


def test_a_self_referencing_alias_does_not_hang_the_splice() -> None:
    source = "---\ntitle: T  # keep me\ntags: [a, b]\nloop: &l\n  - *l\n---\nx\n"
    out = render_doc(_stamp(parse_text(source).meta), "x\n", source=source)
    assert out == (
        "---\ntitle: T  # keep me\ntags: [a, b]\nloop: &l\n  - *l\n"
        "cdm:\n  audience: eng-guide\n  schema_version: 1.0.0\n---\nx\n"
    )


def test_an_alias_fan_out_stays_fast() -> None:
    """Shared aliases must not blow equality up exponentially (a planted doc)."""
    lines = ["title: T", "l0: &l0 [" + ", ".join(["x"] * 10) + "]"]
    for level in range(1, 7):
        refs = ", ".join([f"*l{level - 1}"] * 10)
        lines.append(f"l{level}: &l{level} [{refs}]")
    source = "---\n" + "\n".join(lines) + "\n---\nx\n"
    meta = parse_text(source).meta
    started = time.perf_counter()
    assert render_doc(meta, "x\n", source=source) == source
    out = render_doc(_stamp(meta), "x\n", source=source)
    assert out.startswith(source[: -len("---\nx\n")])
    assert time.perf_counter() - started < 3.0


def test_a_column_0_flow_root_falls_back_to_a_fresh_dump() -> None:
    """A flow root is never spliced, even when its keys sit at column 0."""
    source = "---\n{\na: 1,\nb: 2\n}\n---\nx\n"
    assert render_doc({"b": 2}, "x\n", source=source) == "---\nb: 2\n---\nx\n"


def test_an_aliased_key_falls_back_to_a_fresh_dump() -> None:
    """``*k :`` re-spells an earlier key; its text has no span of its own.

    The duplicate-key bail refuses this layout first; the aliased-key bail is
    pinned by the value-node case below.
    """
    source = "---\n&k a: 1\nc: 3\n*k : 2\n---\nx\n"
    assert render_doc({"a": 2, "c": 4}, "x\n", source=source) == (
        "---\na: 2\nc: 4\n---\nx\n"
    )


def test_an_aliased_key_naming_a_value_node_falls_back_to_a_fresh_dump() -> None:
    """``*v :`` names a node inside ``a``'s value, so its key sits before ``b``.

    The spans assume keys in source order; without the aliased-key bail this
    splices to YAML that still parses back to ``meta`` (``safe_load`` lets the
    re-spelt key through as a duplicate), so the bail is part of the contract.
    """
    source = "---\na: {\n&v x: 1}\nb: 1 # c\n*v : 2  # keep\n---\nx\n"
    meta = {k: v for k, v in parse_text(source).meta.items() if k != "a"}
    assert meta == {"b": 1, "x": 2}
    assert render_doc(meta, "x\n", source=source) == "---\nb: 1\nx: 2\n---\nx\n"


def test_a_splice_that_parses_to_other_data_falls_back() -> None:
    """A new entry's ``&id001`` would capture a kept entry's ``*id001``."""
    source = "---\nz: &id001 [1]\nw: *id001\n---\nb\n"
    shared = [5]
    meta = {"new": [shared, shared], "w": [1]}
    out = render_doc(meta, "b\n", source=source)
    assert parse_text(out).meta == meta
    assert out == "---\nnew:\n- &id001\n  - 5\n- *id001\nw:\n- 1\n---\nb\n"


def test_the_fresh_cdm_copy_keeps_shared_and_cyclic_values() -> None:
    shared = [1]
    out = render_doc({"cdm": {"b": shared, "a": shared}}, "x\n")
    assert out == "---\ncdm:\n  a: &id001\n  - 1\n  b: *id001\n---\nx\n"
    loop: list[Any] = []
    loop.append(loop)
    out = render_doc({"cdm": {"loop": loop}}, "x\n")
    assert out == "---\ncdm:\n  loop: &id001\n  - *id001\n---\nx\n"


def test_unsortable_keys_and_set_members_keep_a_fixed_order() -> None:
    """Mixed-type keys keep meta's order; mixed-type set members sort by repr."""
    assert render_doc({"cdm": {1: "a", "b": 2}}, "x\n") == (
        "---\ncdm:\n  1: a\n  b: 2\n---\nx\n"
    )
    assert render_doc({"s": {1, "a"}}, "x\n") == (
        "---\ns: !!set\n  a: null\n  1: null\n---\nx\n"
    )


def test_the_fresh_dump_keeps_meta_order_and_sorts_only_cdm() -> None:
    meta = {
        "zeta": {"b": 1, "a": 2},
        "cdm": {"z": 1, "a": {"y": 1, "b": 2}},
        "alpha": 1,
    }
    assert render_doc(meta, "x\n") == (
        "---\nzeta:\n  b: 1\n  a: 2\ncdm:\n  a:\n    b: 2\n    y: 1\n  z: 1\n"
        "alpha: 1\n---\nx\n"
    )


def test_shared_references_in_two_entries_dump_unique_anchors() -> None:
    """One dump call per block: two entries never both get ``&id001``."""
    x, y = [1], [2]
    expected = {"a": [[1], [1]], "b": [[2], [2]]}
    assert parse_text(render_doc({"a": [x, x], "b": [y, y]}, "b\n")).meta == expected
    flow = "---\n{a: &x [1], b: [*x, *x], c: &y [2], d: [*y, *y]}\n---\nb\n"
    meta = _stamp(parse_text(flow).meta)
    assert parse_text(render_doc(meta, "b\n", source=flow)).meta == meta


def test_nel_round_trips_through_every_dump() -> None:
    """allow_unicode would write U+0085 raw, and YAML folds it to a space."""
    meta = {"title": "T", "note": "a\x85b"}
    assert parse_text(render_doc(meta, "b\n")).meta == meta
    source = "---\ntitle: T  # keep\n---\nb\n"
    out = render_doc(meta, "b\n", source=source)
    assert out == '---\ntitle: T  # keep\nnote: "a\\Nb"\n---\nb\n'


def test_a_set_dumps_in_sorted_order_regardless_of_hash_seed() -> None:
    """``!!set`` members follow str hashing; the dump must not (K10).

    Covers both branches of the member sort: sortable members and the repr
    fallback for mixed types.
    """
    script = (
        "from custodex.manifest import render_doc\n"
        "owners = {'alice', 'bob', 'carol', 'dave', 'erin', 'frank'}\n"
        "mixed = {'erin', 'carol', 'alice', 2.5, 1}\n"
        "print(render_doc({'title': 'T', 'owners': owners, 'mixed': mixed},"
        " 'b\\n'), end='')\n"
    )
    outputs = set()
    for seed in ("1", "2", "3", "4"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(_REPO)}
        done = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.add(done.stdout)
    members = "".join(
        f"  {name}: null\n"
        for name in ("alice", "bob", "carol", "dave", "erin", "frank")
    )
    # Mixed types do not sort, so members fall back to repr order: str
    # members (quoted repr) before the numbers.
    mixed = "".join(
        f"  {name}: null\n" for name in ("alice", "carol", "erin", "1", "2.5")
    )
    assert outputs == {
        f"---\ntitle: T\nowners: !!set\n{members}mixed: !!set\n{mixed}---\nb\n"
    }


# --- loud on malformed input (K8) -------------------------------------------


@pytest.mark.parametrize(
    "source",
    ["---\na: [\n---\nb\n", "---\n- a\n- b\n---\nb\n"],
    ids=["malformed", "not-a-mapping"],
)
def test_a_source_whose_front_matter_does_not_parse_raises(source: str) -> None:
    with pytest.raises(DriftError):
        render_doc({"a": 1}, "b\n", source=source)


# --- property: engine writes over random column-0 layouts -------------------

_FOREIGN_ENTRIES = [
    "title: Project Handbook\n",
    "kind: readme  # inline\n",
    "tags: [template, scaffold]\n",
    "tags2:\n- a\n- b\n",
    "summary: >-\n  A house-style summary — with\n  an em dash.\n",
    "note: |\n  line one\n  line two\n",
    "updated: '2026-09-02'\n",
    "at: 2026-09-25T08:09:49.344Z\n",
    'quoted: "a: b # c"\n',
    "nested:\n  b: 1\n  a: [x, y]\n",
    "flowmap: {b: 1, a: 2}\n",
    "empty:\n",
    "canonical: yes\n",
    "multi: plain text\n  that folds\n",
]
_CDM_ENTRIES = [
    "",
    "cdm:\n  fingerprint: old\n",
    "cdm: {audience: user-guide, fingerprint: old}\n",
    "cdm:\n  region_hashes:\n    a: x\n  audience: eng-guide\n",
]
_GAPS = ["", "\n", "# a comment\n", "  # indented comment\n"]
_TRAILERS = ["", "", "...\n", "...\n# after the marker\n"]


def _random_source(rng: random.Random) -> str:
    keys = rng.sample(_FOREIGN_ENTRIES, rng.randint(0, 6))
    cdm = rng.choice(_CDM_ENTRIES)
    if cdm:
        keys.insert(rng.randint(0, len(keys)), cdm)
    head = rng.choice(_GAPS)
    trailer = rng.choice(_TRAILERS) if keys else ""  # a bare ``...`` does not parse
    entries = "".join(k + rng.choice(_GAPS) for k in keys)
    return "---\n" + head + entries + trailer + "---\nx\n"


def _engine_write(rng: random.Random, meta: dict[str, Any]) -> dict[str, Any]:
    choice = rng.randrange(4)
    if choice == 0:
        return _stamp(meta)
    if choice == 1:
        return set_fingerprint(meta, rng.choice(["new", "old"]))
    if choice == 2:
        return set_region_hash(meta, rng.choice(["a", "é-region"]), "h" * 8)
    return dict(meta)


def test_engine_writes_keep_every_foreign_line_over_random_layouts() -> None:
    """400 seeded layouts: data-exact, K7, and every non-cdm line kept in order."""
    rng = random.Random(20261010)
    for _ in range(400):
        source = _random_source(rng)
        doc = parse_text(source)
        meta = _engine_write(rng, doc.meta)
        out = render_doc(meta, doc.body, source=source)
        again = parse_text(out)
        assert again.meta == meta, source
        assert again.body == doc.body, source
        assert render_doc(again.meta, again.body, source=out) == out, source
        if meta == doc.meta:
            assert out == source, source
        foreign = _foreign_lines(source)
        assert _foreign_lines(out) == foreign, (source, out)


def _foreign_lines(text: str) -> list[str]:
    """The front-matter lines outside the top-level ``cdm`` entry."""
    fm = text.split("---\n")[1]
    kept: list[str] = []
    in_cdm = False
    for line in fm.splitlines(keepends=True):
        if line.startswith("cdm:"):
            in_cdm = True
            continue
        if (
            in_cdm
            and line.startswith((" ", "\n"))
            and not line.lstrip().startswith("#")
        ):
            continue
        in_cdm = False
        kept.append(line)
    return kept
