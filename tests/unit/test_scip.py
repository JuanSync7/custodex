"""CIX-02 — the stdlib SCIP reader, symbol grammar, and xref join (`scip.py`).

The decoder walks real protobuf wire bytes (built by the test-only encoder
in ``tests/_scip.py`` — no protobuf dependency on either side); the mapper
mints the EXISTING entity id scheme so REFERENCES edges join the graph the
other detectors already populate.

Features: FEAT-SCIP-001
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from custodex.codeindex import build_code_index, file_digests
from custodex.config import MonitorConfig
from custodex.errors import ExtractionError, SchemaError
from custodex.kgraph import EdgeKind, EdgeTier, build_graph
from custodex.scip import (
    XREFS_PATH,
    XrefEdge,
    XrefSet,
    build_xrefs,
    caller_currency_note,
    read_scip,
    read_xrefs,
    scip_symbol_to_dotted,
    unknown_caller_files,
    write_xrefs,
)
from tests._scip import (
    document,
    index,
    len_field,
    occurrence,
    packed_field,
    str_field,
    varint_field,
)

_PREFIX = "scip-python python proj 0.1 "

_CALLER = '''"""Caller module."""
from pkg.lib import helper

def caller():
    """Calls helper twice."""
    helper()
    return helper()

def _private_caller():
    return helper()
'''

_LIB = '''"""Lib module."""

def helper():
    """The referenced helper."""
    return 1

class Tool:
    """A class with a method."""

    def run(self):
        """Run."""
        return helper()
'''


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "main.py").write_text(_CALLER, encoding="utf-8")
    (tmp_path / "pkg" / "lib.py").write_text(_LIB, encoding="utf-8")
    return tmp_path


def _code_index(root: Path):
    return build_code_index(
        MonitorConfig(documents=()), root, generated_by="custodex/test"
    )


def _scip_bytes() -> bytes:
    """References inside pkg/main.py + pkg/lib.py to `pkg.lib` symbols."""
    helper = _PREFIX + "`pkg.lib`/helper()."
    main_doc = document(
        "pkg/main.py",
        [
            # import-line module reference — out of the symbol join
            occurrence(_PREFIX + "`pkg.lib`/__init__:", range_=[1, 5, 12]),
            # two references inside caller() (lines 6/7 → 0-based 5/6)
            occurrence(helper, range_=[5, 4, 10]),
            occurrence(helper, range_=[6, 11, 17]),
            # one inside _private_caller (0-based line 9) — private source
            occurrence(helper, range_=[9, 11, 17]),
            # a definition occurrence must never become an edge
            occurrence(_PREFIX + "`pkg.main`/caller().", roles=0x1, range_=[3, 4, 10]),
            # a local — skipped
            occurrence("local 0", range_=[5, 0, 1]),
            # an unresolvable stdlib target — counts into unmapped
            occurrence(
                "scip-python python python-stdlib 3.11 builtins/print().",
                range_=[6, 0, 5],
            ),
        ],
    )
    lib_doc = document(
        "pkg/lib.py",
        [
            # reference to helper from inside Tool.run (0-based line 11)
            occurrence(helper, unpacked_range=[11, 15, 21]),
        ],
    )
    return index([main_doc, lib_doc])


# ------------------------------------------------------------------- decoder


def test_decoder_reads_metadata_documents_and_ranges(tmp_path: Path) -> None:
    raw = tmp_path / "index.scip"
    raw.write_bytes(_scip_bytes())
    decoded = read_scip(raw)
    assert decoded.tool_name == "scip-python"
    assert decoded.tool_version == "0.6.6"
    assert [d.relative_path for d in decoded.documents] == [
        "pkg/main.py",
        "pkg/lib.py",
    ]
    occ = decoded.documents[0].occurrences[1]
    assert (occ.start_line, occ.start_char, occ.end_line, occ.end_char) == (
        5,
        4,
        5,
        10,
    )
    # unpacked repeated int32 decodes identically to packed
    unpacked = decoded.documents[1].occurrences[0]
    assert (unpacked.start_line, unpacked.end_char) == (11, 21)


def test_decoder_handles_typed_ranges_with_precedence(tmp_path: Path) -> None:
    occ = occurrence(
        _PREFIX + "`pkg.lib`/helper().",
        range_=[1, 1, 2],  # deprecated form says line 1...
        single_line=(7, 3, 9),  # ...typed form says line 7 and MUST win
    )
    raw = tmp_path / "typed.scip"
    raw.write_bytes(index([document("pkg/main.py", [occ])]))
    decoded = read_scip(raw)
    got = decoded.documents[0].occurrences[0]
    assert (got.start_line, got.start_char, got.end_line, got.end_char) == (7, 3, 7, 9)

    multi = occurrence(_PREFIX + "`pkg.lib`/helper().", multi_line=(4, 2, 6, 1))
    raw.write_bytes(index([document("pkg/main.py", [multi])]))
    got = read_scip(raw).documents[0].occurrences[0]
    assert (got.start_line, got.start_char, got.end_line, got.end_char) == (4, 2, 6, 1)


def test_decoder_skips_unknown_fields(tmp_path: Path) -> None:
    doc = document("pkg/main.py", [occurrence(_PREFIX + "x.", range_=[0, 0, 1])])
    # splice unknown fields into the Document: field 99 varint + field 98 LEN
    doc += varint_field(99, 7) + str_field(98, "future")
    raw = tmp_path / "future.scip"
    raw.write_bytes(index([doc]))
    decoded = read_scip(raw)
    assert decoded.documents[0].relative_path == "pkg/main.py"


def test_decoder_is_loud_on_malformed_input(tmp_path: Path) -> None:
    raw = tmp_path / "bad.scip"
    raw.write_bytes(b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff")
    with pytest.raises(ExtractionError):
        read_scip(raw)
    raw.write_bytes(str_field(2, "x")[:-1])  # truncated LEN payload
    with pytest.raises(ExtractionError):
        read_scip(raw)
    with pytest.raises(ExtractionError):
        read_scip(tmp_path / "missing.scip")


# ------------------------------------------------------------- symbol grammar


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        (_PREFIX + "`pkg.lib`/__init__:", "pkg.lib"),  # module marker dropped
        (_PREFIX + "simple/__init__:", "simple"),
        (_PREFIX + "`pkg.lib`/helper().", "pkg.lib.helper"),
        (_PREFIX + "`pkg.lib`/Tool#", "pkg.lib.Tool"),
        (_PREFIX + "`pkg.lib`/Tool#run().", "pkg.lib.Tool.run"),
        (_PREFIX + "`pkg.lib`/Tool#static_var.", "pkg.lib.Tool.static_var"),
        (_PREFIX + "`pkg.lib`/Tool#run().(self)", None),  # parameter
        ("local 0", None),
        ("local 2(y)", None),  # the lambda-parameter quirk
        (_PREFIX + "`weird``name`/x.", "weird`name.x"),  # doubled backtick
        ("scip-python python p  q 0.1 mod/f().", "mod.f"),  # escaped space in pkg
        ("garbage", None),
        (_PREFIX + "noSuffix", None),  # descriptor without a suffix
    ],
)
def test_scip_symbol_to_dotted(symbol: str, expected: str | None) -> None:
    assert scip_symbol_to_dotted(symbol) == expected


# ------------------------------------------------------------------ the join


def test_build_xrefs_attribution_and_honesty(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    code_index = _code_index(root)
    raw = tmp_path / "index.scip"
    raw.write_bytes(_scip_bytes())
    xrefs = build_xrefs(
        read_scip(raw), code_index, generated_by="custodex/test", source_sha="abc"
    )
    assert xrefs.tool == "scip-python/0.6.6"
    assert xrefs.coverage == {"python": "scip-python/0.6.6"}
    # print() (stdlib) is the ONE unresolvable target; the import-line module
    # ref, the local, the definition, and the private-source ref are out of
    # scope by design, not failures.
    assert xrefs.unmapped == 1
    assert xrefs.edges == (
        XrefEdge(
            source="symbol pkg/lib.py#Tool.run",
            target="symbol pkg/lib.py#helper",
            count=1,
        ),
        XrefEdge(
            source="symbol pkg/main.py#caller",
            target="symbol pkg/lib.py#helper",
            count=2,  # two occurrences, one edge, tallied
        ),
    )


def test_build_xrefs_recovers_project_root_prefix_quirk(tmp_path: Path) -> None:
    """scip-python may emit src-prefixed dotted names AND doc paths."""
    root = _repo(tmp_path)
    code_index = _code_index(root)
    helper = _PREFIX + "`src.pkg.lib`/helper()."  # extra dotted prefix
    raw = tmp_path / "prefixed.scip"
    raw.write_bytes(
        index([document("pkg/main.py", [occurrence(helper, range_=[5, 4, 10])])])
    )
    xrefs = build_xrefs(read_scip(raw), code_index, generated_by="t")
    assert [e.target for e in xrefs.edges] == ["symbol pkg/lib.py#helper"]
    assert xrefs.unmapped == 0


# ------------------------------------------------------------------- artifact


def test_xrefs_roundtrip_and_stamp_blind_write(tmp_path: Path) -> None:
    cdmon = tmp_path / ".cdmon"
    assert read_xrefs(cdmon) is None
    edges = (XrefEdge(source="symbol a.py#f", target="symbol b.py#g", count=1),)
    first = XrefSet(
        generated_by="custodex/test",
        tool="scip-python/0.6.6",
        source_sha="aaa",
        coverage={"python": "scip-python/0.6.6"},
        unmapped=0,
        edges=edges,
    )
    assert write_xrefs(first, cdmon) is True
    assert read_xrefs(cdmon) == first
    restamped = first.model_copy(update={"source_sha": "bbb"})
    assert write_xrefs(restamped, cdmon) is False  # stamp-blind (K7)
    stored = read_xrefs(cdmon)
    assert stored is not None and stored.source_sha == "aaa"

    (cdmon / XREFS_PATH.name).write_text("{broken", encoding="utf-8")
    with pytest.raises(SchemaError):
        read_xrefs(cdmon)
    assert write_xrefs(first, cdmon) is True  # a corrupt artifact is replaced


# ---------------------------------------------------------------- kgraph fold


def test_kgraph_folds_references_additively(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    config = MonitorConfig(documents=())
    plain = build_graph(config, root)
    assert plain.schema_version == "1.1.0"
    assert all(e.kind is not EdgeKind.REFERENCES for e in plain.edges)

    edges = (
        XrefEdge(
            source="symbol pkg/main.py#caller",
            target="symbol pkg/lib.py#helper",
            count=2,
        ),
    )
    enriched = build_graph(config, root, xrefs=edges)
    refs = [e for e in enriched.edges if e.kind is EdgeKind.REFERENCES]
    assert len(refs) == 1
    assert refs[0].tier is EdgeTier.INDEXED
    assert refs[0].source == "symbol pkg/main.py#caller"
    node_ids = {n.id for n in enriched.nodes}
    assert {"symbol pkg/main.py#caller", "symbol pkg/lib.py#helper"} <= node_ids
    # the default keeps prior content identical (K6): non-REFERENCES edges
    # and pre-existing nodes are unchanged
    assert [e for e in enriched.edges if e.kind is not EdgeKind.REFERENCES] == list(
        plain.edges
    )


# ----------------------------------------------- decoder edge branches (K9)


def test_decoder_skips_i64_and_i32_fields(tmp_path: Path) -> None:
    """Wire types 1 and 5 are skipped structurally (no SCIP field uses them)."""
    occ = occurrence(_PREFIX + "x.", range_=[0, 0, 1])
    doc = document("pkg/main.py", [occ])
    doc += bytes([15 << 3 | 1]) + b"\x00" * 8  # field 15, I64
    doc += bytes([14 << 3 | 5]) + b"\x00" * 4  # field 14, I32
    raw = tmp_path / "fixed.scip"
    raw.write_bytes(index([doc]))
    assert read_scip(raw).documents[0].relative_path == "pkg/main.py"


def test_decoder_rejects_truncated_fixed_fields(tmp_path: Path) -> None:
    raw = tmp_path / "trunc.scip"
    raw.write_bytes(bytes([1 << 3 | 1]) + b"\x00\x00")  # I64 with 2 bytes
    with pytest.raises(ExtractionError):
        read_scip(raw)
    raw.write_bytes(bytes([1 << 3 | 5]) + b"\x00")  # I32 with 1 byte
    with pytest.raises(ExtractionError):
        read_scip(raw)


def test_decoder_rejects_groups_and_oversized_varints(tmp_path: Path) -> None:
    raw = tmp_path / "group.scip"
    raw.write_bytes(bytes([1 << 3 | 3]))  # deprecated SGROUP wire type
    with pytest.raises(ExtractionError):
        read_scip(raw)
    raw.write_bytes(b"\xff" * 11 + b"\x01")  # 12-byte varint
    with pytest.raises(ExtractionError):
        read_scip(raw)


def test_decoder_range_must_have_3_or_4_elements(tmp_path: Path) -> None:
    occ = occurrence(_PREFIX + "x.", range_=[1, 2])
    raw = tmp_path / "shortrange.scip"
    raw.write_bytes(index([document("pkg/main.py", [occ])]))
    with pytest.raises(ExtractionError):
        read_scip(raw)


def test_decoder_symbolless_or_rangeless_occurrences_are_dropped(
    tmp_path: Path,
) -> None:
    no_symbol = packed_field(1, [0, 0, 1])  # range only, no symbol
    no_range = str_field(2, _PREFIX + "x.")  # symbol only, no range
    doc = str_field(1, "pkg/main.py") + len_field(2, no_symbol) + len_field(2, no_range)
    raw = tmp_path / "partial.scip"
    raw.write_bytes(index([doc]))
    assert read_scip(raw).documents[0].occurrences == ()


@pytest.mark.parametrize(
    "symbol",
    [
        _PREFIX + "`unterminated",  # backtick never closed
        _PREFIX + "mod/[T",  # type-parameter never closed
        _PREFIX + "mod/(a",  # parameter never closed
        _PREFIX + "mod/f(",  # method without ').'
        _PREFIX + "f().",  # fine — but check the [T] and macro forms below
    ],
)
def test_grammar_malformed_descriptors_map_to_none_or_names(symbol: str) -> None:
    # the last case is valid; every other is malformed → None
    result = scip_symbol_to_dotted(symbol)
    if symbol.endswith("f()."):
        assert result == "f"
    else:
        assert result is None


def test_grammar_type_parameter_and_macro_descriptors() -> None:
    assert scip_symbol_to_dotted(_PREFIX + "mod/Cls#[T]") is None  # type param
    assert scip_symbol_to_dotted(_PREFIX + "m!") == "m"  # macro joins


def test_reference_wins_over_fuzzy_module_classification(tmp_path: Path) -> None:
    """Adversarial-review pin: `app.config` (a function in app.py) must
    resolve as a REFERENCE even when an unrelated root config.py exists —
    the fuzzy suffix rule is only a fallback for the project-root quirk."""
    (tmp_path / "app.py").write_text(
        "def config():\n    return 1\n\ndef main():\n    return config()\n",
        encoding="utf-8",
    )
    (tmp_path / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
    code_index = _code_index(tmp_path)
    ref = "scip-python python p 1 app/config()."
    raw = tmp_path / "fuzzy.scip"
    raw.write_bytes(index([document("app.py", [occurrence(ref, range_=[3, 11, 17])])]))
    xrefs = build_xrefs(read_scip(raw), code_index, generated_by="t")
    assert [(e.source, e.target) for e in xrefs.edges] == [
        ("symbol app.py#main", "symbol app.py#config")
    ]
    assert xrefs.unmapped == 0


# ------------------------------------- input pin + attribution honesty (xref)


def test_build_xrefs_pins_the_code_index_inputs_it_joined(tmp_path: Path) -> None:
    """The xref set records WHICH code-index content it was attributed
    against — ``{path: content_digest}`` for every file a SCIP document
    joined, plus every same-language file with no public symbol (provably
    edge-free at that content) — so a consumer can tell current caller data
    from stale. An input pin, not a stamp: identical inputs pin identically.
    """
    # Feature: FEAT-SCIP-001
    root = _repo(tmp_path)
    code_index = _code_index(root)
    raw = tmp_path / "index.scip"
    raw.write_bytes(_scip_bytes())
    xrefs = build_xrefs(read_scip(raw), code_index, generated_by="t")
    digests = {f.path: f.content_digest for f in code_index.files}
    # main.py + lib.py were joined (SCIP documents); the empty __init__.py
    # holds no public symbol, so it can source no edge — pinned as known.
    assert xrefs.input_digests == {
        "pkg/__init__.py": digests["pkg/__init__.py"],
        "pkg/lib.py": digests["pkg/lib.py"],
        "pkg/main.py": digests["pkg/main.py"],
    }
    assert list(xrefs.input_digests) == sorted(xrefs.input_digests)  # K10
    # the languages the pin speaks for, recorded at build time (sorted, K10)
    assert xrefs.input_languages == ("python",)
    again = build_xrefs(read_scip(raw), code_index, generated_by="other")
    assert again.input_digests == xrefs.input_digests


def test_build_xrefs_leaves_undocumented_public_files_unpinned(
    tmp_path: Path,
) -> None:
    """A covered-language file WITH public symbols but NO SCIP document has
    no reference data — it must stay out of the pin so every consumer
    reports its caller data as unknown (never as "no callers")."""
    # Feature: FEAT-SCIP-001
    root = _repo(tmp_path)
    code_index = _code_index(root)
    helper = _PREFIX + "`pkg.lib`/helper()."
    raw = tmp_path / "main-only.scip"
    raw.write_bytes(
        index([document("pkg/main.py", [occurrence(helper, range_=[5, 4, 10])])])
    )
    xrefs = build_xrefs(read_scip(raw), code_index, generated_by="t")
    assert xrefs.input_digests is not None
    assert "pkg/lib.py" not in xrefs.input_digests
    assert set(xrefs.input_digests) == {"pkg/__init__.py", "pkg/main.py"}


def test_source_attribution_drops_are_counted_not_lost(tmp_path: Path) -> None:
    """A reference whose TARGET resolved to a public symbol but whose SOURCE
    position lies inside no indexed symbol span (module-level code, or spans
    stale against the .scip) tallies into ``unattributed`` — the drop that
    used to vanish while ``unmapped`` stayed 0 (critic 1.17)."""
    # Feature: FEAT-SCIP-001
    root = _repo(tmp_path)
    code_index = _code_index(root)
    helper = _PREFIX + "`pkg.lib`/helper()."
    raw = tmp_path / "outside.scip"
    raw.write_bytes(
        index(
            [
                document(
                    "pkg/main.py",
                    [
                        occurrence(helper, range_=[5, 4, 10]),  # inside caller()
                        occurrence(helper, range_=[40, 0, 6]),  # beyond every span
                        occurrence(helper, range_=[9, 11, 17]),  # private source
                    ],
                )
            ]
        )
    )
    xrefs = build_xrefs(read_scip(raw), code_index, generated_by="t")
    assert [e.source for e in xrefs.edges] == ["symbol pkg/main.py#caller"]
    assert xrefs.unattributed == 1  # the out-of-span one; private is by design
    assert xrefs.unmapped == 0  # targets all resolved — a different counter


def test_legacy_xrefs_without_a_pin_read_as_unknown(tmp_path: Path) -> None:
    """An artifact written before the input pin existed still validates
    (additive, K6) and reads ``input_digests=None`` — currency UNKNOWN,
    never silently current."""
    # Feature: FEAT-SCIP-001
    cdmon = tmp_path / ".cdmon"
    cdmon.mkdir()
    legacy = {
        "schema_version": "1.0.0",
        "generated_by": "custodex/old",
        "tool": "scip-python/0.6.6",
        "source_sha": None,
        "coverage": {"python": "scip-python/0.6.6"},
        "unmapped": 0,
        "edges": [],
    }
    (cdmon / XREFS_PATH.name).write_text(json.dumps(legacy), encoding="utf-8")
    stored = read_xrefs(cdmon)
    assert stored is not None
    assert stored.input_digests is None
    assert stored.unattributed == 0
    assert unknown_caller_files(stored, {}) is None


def test_write_xrefs_compares_the_input_pin(tmp_path: Path) -> None:
    """K7 + ⟨R⟩2: identical inputs write nothing, but the input pin (and the
    unattributed tally) ARE content — identical edges joined against changed
    code-index content rewrite the artifact, so the pin can never go stale
    behind an "unchanged" (the fit's anti-stamp rule)."""
    # Feature: FEAT-SCIP-001
    cdmon = tmp_path / ".cdmon"
    first = XrefSet(
        generated_by="custodex/test",
        tool="scip-python/0.6.6",
        source_sha="aaa",
        coverage={"python": "scip-python/0.6.6"},
        unmapped=0,
        edges=(),
        input_digests={"a.py": "1111111111111111"},
    )
    assert write_xrefs(first, cdmon) is True
    assert write_xrefs(first, cdmon) is False  # identical inputs: a no-op
    assert write_xrefs(first.model_copy(update={"source_sha": "b"}), cdmon) is False
    # a custodex upgrade (a new producer stamp) alone never rewrites (⟨R⟩2)
    restamped = first.model_copy(update={"generated_by": "custodex/9.9.9"})
    assert write_xrefs(restamped, cdmon) is False
    repinned = first.model_copy(update={"input_digests": {"a.py": "2" * 16}})
    assert write_xrefs(repinned, cdmon) is True
    stored = read_xrefs(cdmon)
    assert stored is not None and stored.input_digests == {"a.py": "2" * 16}
    assert write_xrefs(repinned, cdmon) is False
    recounted = repinned.model_copy(update={"unattributed": 3})
    assert write_xrefs(recounted, cdmon) is True
    # the covered-language set is part of the pin — content, not a stamp
    relanguaged = recounted.model_copy(update={"input_languages": ("python",)})
    assert write_xrefs(relanguaged, cdmon) is True
    assert write_xrefs(relanguaged, cdmon) is False
    stored = read_xrefs(cdmon)
    assert stored is not None and stored.input_languages == ("python",)


def test_unknown_caller_files_compares_the_pin_to_a_listing() -> None:
    """Caller data is unknown for a covered-language file that changed, was
    added, or was removed since the join; other languages are out of the
    SCIP coverage (the ``coverage`` map's honesty, not this check's)."""
    # Feature: FEAT-SCIP-001
    xrefs = XrefSet(
        generated_by="t",
        tool="scip-python/0.6.6",
        coverage={"python": "scip-python/0.6.6"},
        unmapped=0,
        edges=(),
        input_digests={"a.py": "aaaa", "b.py": "bbbb", "gone.py": "cccc"},
        input_languages=("python",),
    )
    current = {
        "a.py": ("python", "aaaa"),  # unchanged → known
        "b.py": ("python", "BBBB"),  # changed since the join
        "new.py": ("python", "nnnn"),  # never joined
        "run.sh": ("shell", "ssss"),  # not a covered language
    }
    assert unknown_caller_files(xrefs, current) == ("b.py", "gone.py", "new.py")
    exact = {
        "a.py": ("python", "aaaa"),
        "b.py": ("python", "bbbb"),
        "gone.py": ("python", "cccc"),
    }
    assert unknown_caller_files(xrefs, exact) == ()
    # a join that matched NO document covers no language and vouches for
    # nothing (never "complete")
    empty = xrefs.model_copy(update={"input_digests": {}, "input_languages": ()})
    assert unknown_caller_files(empty, current) == tuple(sorted(current))
    # a covered language whose every file was unvouched (stale at join time)
    # stays covered: its files are unknown, other languages are not listed
    unvouched = xrefs.model_copy(update={"input_digests": {}})
    assert unknown_caller_files(unvouched, current) == ("a.py", "b.py", "new.py")


def test_caller_currency_note_wording() -> None:
    """ONE wording for impact and graph: silent when current, the count and
    paths when stale, an explicit "unknown" when the artifact has no pin.
    The note states what is known — the stored xrefs do not hold these
    files' current outgoing references — and says plainly that a file is
    listed whether or not a reference actually changed (an honest
    over-report, never a claim that callers changed)."""
    # Feature: FEAT-SCIP-001
    assert caller_currency_note(()) is None
    note = caller_currency_note(("pkg/new.py", "pkg/old.py"))
    assert note is not None
    assert "caller data unknown for 2 file(s)" in note
    assert "pkg/new.py, pkg/old.py" in note
    assert "current outgoing references are not in the stored xrefs" in note
    assert "listed whether or not a reference changed" in note
    legacy = caller_currency_note(None)
    assert legacy is not None and "no input pin" in legacy


def test_kgraph_carries_xref_notes_as_warnings(tmp_path: Path) -> None:
    """A stale-xrefs note rides the graph artifact's ``warnings`` AFTER the
    registry's own (an unparseable source here) so a persisted/serialized
    graph never presents stale REFERENCES as current and its bytes are
    order-stable; the default keeps the fold byte-identical (K6)."""
    # Feature: FEAT-SCIP-001
    root = _repo(tmp_path)
    (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    config = MonitorConfig(documents=())
    plain = build_graph(config, root)
    assert plain.warnings  # the registry warned about broken.py
    noted = build_graph(config, root, xref_notes=("caller data unknown for 1",))
    assert noted.warnings == (*plain.warnings, "caller data unknown for 1")
    assert build_graph(config, root, xref_notes=()) == plain


# ------------------------- the vouch + the covered languages (xref round 1)


def test_a_stale_index_cannot_vouch_for_the_files_it_disagrees_on(
    tmp_path: Path,
) -> None:
    """Review scenario C at the unit: references are attributed through the
    code index's SPANS, so when the index disagrees with the tree for a file
    (``tree_digests`` — :func:`file_digests`), the join cannot vouch for that
    file's caller data. It is left out of the pin — a joined file and an
    edge-free one alike — so every consumer reports it "caller data unknown"
    instead of trusting edges the stale spans may have dropped. The vouch
    narrows the PIN, never the edges; the run still covers the language."""
    # Feature: FEAT-SCIP-001
    root = _repo(tmp_path)
    cfg = MonitorConfig(documents=())
    stored = _code_index(root)
    raw = tmp_path / "index.scip"
    raw.write_bytes(_scip_bytes())
    in_sync = build_xrefs(
        read_scip(raw), stored, generated_by="t", tree_digests=file_digests(cfg, root)
    )
    assert set(in_sync.input_digests or {}) == {
        "pkg/__init__.py",
        "pkg/lib.py",
        "pkg/main.py",
    }  # index == tree: the vouch is transparent

    (root / "pkg" / "main.py").write_text("# shifted\n" + _CALLER, "utf-8")
    (root / "pkg" / "__init__.py").write_text("# touched\n", "utf-8")
    tree = file_digests(cfg, root)
    stale = build_xrefs(read_scip(raw), stored, generated_by="t", tree_digests=tree)
    baseline = {f.path: (f.language, f.content_digest) for f in stored.files}
    assert stale.input_digests == {"pkg/lib.py": baseline["pkg/lib.py"][1]}
    assert stale.input_languages == ("python",)
    assert stale.edges == in_sync.edges  # the pin narrows, the edges do not
    assert unknown_caller_files(stale, baseline) == (
        "pkg/__init__.py",
        "pkg/main.py",
    )

    # every joined file unvouched: an empty pin that still COVERS python
    helper = _PREFIX + "`pkg.lib`/helper()."
    main_only = tmp_path / "main-only.scip"
    main_only.write_bytes(
        index([document("pkg/main.py", [occurrence(helper, range_=[5, 4, 10])])])
    )
    empty = build_xrefs(
        read_scip(main_only), stored, generated_by="t", tree_digests=tree
    )
    assert empty.input_digests == {}
    assert empty.input_languages == ("python",)


def test_covered_languages_survive_a_package_move(tmp_path: Path) -> None:
    """The covered languages are recorded AT BUILD TIME, never re-derived
    from pinned paths that still exist: after a package move (``pkg/`` →
    ``src/pkg/``) no pinned path survives, yet every moved file and every
    new caller is still "caller data unknown" — the per-file list the note
    prints names the new callers, not only the vanished paths."""
    # Feature: FEAT-SCIP-001
    root = _repo(tmp_path)
    cfg = MonitorConfig(documents=())
    raw = tmp_path / "index.scip"
    raw.write_bytes(_scip_bytes())
    xrefs = build_xrefs(read_scip(raw), _code_index(root), generated_by="t")
    (root / "src").mkdir()
    (root / "pkg").rename(root / "src" / "pkg")
    (root / "src" / "pkg" / "extra.py").write_text(
        "def extra():\n    return 1\n", "utf-8"
    )
    assert unknown_caller_files(xrefs, file_digests(cfg, root)) == (
        "pkg/__init__.py",
        "pkg/lib.py",
        "pkg/main.py",
        "src/pkg/__init__.py",
        "src/pkg/extra.py",
        "src/pkg/lib.py",
        "src/pkg/main.py",
    )


def test_private_only_file_is_pinned_as_edge_free(tmp_path: Path) -> None:
    """A covered-language file whose symbols are ALL private can source no
    edge (private sources are out of the universe), so the join pins it as
    known even without a SCIP document — never a permanent "unknown"."""
    # Feature: FEAT-SCIP-001
    root = _repo(tmp_path)
    (root / "pkg" / "_util.py").write_text(
        "def _hidden():\n    return 1\n", encoding="utf-8"
    )
    cfg = MonitorConfig(documents=())
    helper = _PREFIX + "`pkg.lib`/helper()."
    raw = tmp_path / "main-only.scip"
    raw.write_bytes(
        index([document("pkg/main.py", [occurrence(helper, range_=[5, 4, 10])])])
    )
    xrefs = build_xrefs(read_scip(raw), _code_index(root), generated_by="t")
    assert xrefs.input_digests is not None
    assert "pkg/_util.py" in xrefs.input_digests
    assert unknown_caller_files(xrefs, file_digests(cfg, root)) == ("pkg/lib.py",)


def test_edge_free_pin_is_scoped_to_the_joined_languages(tmp_path: Path) -> None:
    """Only same-language edge-free files are pinned: an edge-free file of a
    language the SCIP run never covered stays out of the pin and out of
    ``input_languages``, so that language's later additions are the
    coverage map's honesty, never an "unknown caller" note."""
    # Feature: FEAT-SCIP-001
    root = _repo(tmp_path)
    (root / "run.sh").write_text("echo hi\n", encoding="utf-8")
    cfg = MonitorConfig(
        documents=(), coverage={"include": ("**/*.py", "**/*.sh"), "exclude": ()}
    )
    helper = _PREFIX + "`pkg.lib`/helper()."
    raw = tmp_path / "full.scip"
    raw.write_bytes(
        index(
            [
                document("pkg/__init__.py", []),
                document("pkg/lib.py", []),
                document("pkg/main.py", [occurrence(helper, range_=[5, 4, 10])]),
            ]
        )
    )
    code_index = build_code_index(cfg, root, generated_by="t")
    xrefs = build_xrefs(read_scip(raw), code_index, generated_by="t")
    assert xrefs.input_digests is not None
    assert "run.sh" not in xrefs.input_digests
    assert xrefs.input_languages == ("python",)
    (root / "deploy.sh").write_text("echo deploy\n", encoding="utf-8")
    assert unknown_caller_files(xrefs, file_digests(cfg, root)) == ()


def test_the_vouch_compares_the_whole_index_entry(tmp_path: Path) -> None:
    """The vouch compares the index entry's LANGUAGE as well as its digest:
    the language decides whether spans were extracted at all, so an index
    built by an extension map that classified the file differently (an
    older custodex) cannot vouch for it even over identical bytes."""
    # Feature: FEAT-SCIP-001
    root = _repo(tmp_path)
    cfg = MonitorConfig(documents=())
    built = _code_index(root)
    relabelled = built.model_copy(
        update={
            "files": tuple(
                f.model_copy(update={"language": "unknown", "symbols": ()})
                if f.path == "pkg/lib.py"
                else f
                for f in built.files
            )
        }
    )
    raw = tmp_path / "index.scip"
    raw.write_bytes(_scip_bytes())
    xrefs = build_xrefs(
        read_scip(raw),
        relabelled,
        generated_by="t",
        tree_digests=file_digests(cfg, root),
    )
    assert xrefs.input_digests is not None
    assert "pkg/lib.py" not in xrefs.input_digests  # same bytes, other language
    assert "pkg/main.py" in xrefs.input_digests


# ---------------------------------------- xref round 2 (review + mutation gaps)


def test_an_empty_tree_listing_vouches_for_nothing(tmp_path: Path) -> None:
    """``tree_digests={}`` is a tree with NO coverage file — it is not
    "no tree given" (``None``, the in-memory build): every index entry
    disagrees with it, so the join vouches for nothing, while the run still
    covers python and every file reads "caller data unknown"."""
    # Feature: FEAT-SCIP-001
    root = _repo(tmp_path)
    stored = _code_index(root)
    raw = tmp_path / "index.scip"
    raw.write_bytes(_scip_bytes())
    xrefs = build_xrefs(read_scip(raw), stored, generated_by="t", tree_digests={})
    assert xrefs.input_digests == {}
    assert xrefs.input_languages == ("python",)
    baseline = {f.path: (f.language, f.content_digest) for f in stored.files}
    assert unknown_caller_files(xrefs, baseline) == (
        "pkg/__init__.py",
        "pkg/lib.py",
        "pkg/main.py",
    )


_SEEDED_BUILD = """
import sys
from pathlib import Path
from custodex.codeindex import build_code_index
from custodex.config import MonitorConfig
from custodex.scip import build_xrefs, read_scip, write_xrefs
root, cdmon = Path(sys.argv[1]), Path(sys.argv[2])
cfg = MonitorConfig(
    documents=(), coverage={"include": ("**/*.py", "**/*.ts"), "exclude": ()}
)
xrefs = build_xrefs(
    read_scip(root / "multi.scip"),
    build_code_index(cfg, root, generated_by="t"),
    generated_by="t",
)
print(",".join(xrefs.input_languages))
print(write_xrefs(xrefs, cdmon))
"""


def test_input_languages_are_sorted_across_a_multi_language_join(
    tmp_path: Path,
) -> None:
    """A join that covers two languages records them SORTED, whatever the
    interpreter's string-hash seed: set iteration order varies with
    ``PYTHONHASHSEED``, and an unsorted tuple would make ``write_xrefs``
    rewrite identical input on the next run (K7) and the artifact bytes
    differ between runs (K10). Each seed runs in its own interpreter."""
    # Feature: FEAT-SCIP-001
    (tmp_path / "repo").mkdir()
    root = _repo(tmp_path / "repo")
    (root / "web.ts").write_text("export const x = 1;\n", encoding="utf-8")
    helper = _PREFIX + "`pkg.lib`/helper()."
    (root / "multi.scip").write_bytes(
        index(
            [
                document("pkg/main.py", [occurrence(helper, range_=[5, 4, 10])]),
                document("web.ts", []),
                document("pkg/lib.py", []),
            ]
        )
    )
    cdmon = tmp_path / ".cdmon"
    runs = []
    for seed in ("0", "1", "2", "3"):
        done = subprocess.run(
            [sys.executable, "-c", _SEEDED_BUILD, str(root), str(cdmon)],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        runs.append(done.stdout.split())
        if seed == "0":
            first_bytes = (cdmon / XREFS_PATH.name).read_bytes()
    assert runs[0] == ["python,unknown", "True"]
    assert runs[1:] == [["python,unknown", "False"]] * 3  # byte-stable (K7)
    assert (cdmon / XREFS_PATH.name).read_bytes() == first_bytes


def test_write_xrefs_treats_coverage_and_tool_as_content(tmp_path: Path) -> None:
    """Only the two provenance stamps are ignored by the idempotent writer
    (⟨R⟩2): the ``coverage`` map and the ``tool`` that produced the facts
    are CONTENT — a new coverage map or a new indexer version rewrites the
    artifact once (the tool is observable on its own only when no document
    joined, since the coverage values carry it otherwise), then is a no-op
    again (K7)."""
    # Feature: FEAT-SCIP-001
    cdmon = tmp_path / ".cdmon"
    first = XrefSet(
        generated_by="custodex/test",
        tool="scip-python/0.6.6",
        coverage={"python": "scip-python/0.6.6"},
        unmapped=0,
        edges=(),
        input_digests={},
        input_languages=("python",),
    )
    assert write_xrefs(first, cdmon) is True
    recovered = first.model_copy(update={"coverage": {"Python": first.tool}})
    assert write_xrefs(recovered, cdmon) is True
    stored = read_xrefs(cdmon)
    assert stored is not None and stored.coverage == {"Python": "scip-python/0.6.6"}
    assert write_xrefs(recovered, cdmon) is False

    bare = first.model_copy(update={"coverage": {}})
    assert write_xrefs(bare, cdmon) is True
    upgraded = bare.model_copy(update={"tool": "scip-python/0.7.0"})
    assert write_xrefs(upgraded, cdmon) is True
    stored = read_xrefs(cdmon)
    assert stored is not None and stored.tool == "scip-python/0.7.0"
    assert write_xrefs(upgraded, cdmon) is False


_RENAMED_BEFORE = '''"""Caller module."""
from pkg.lib import helper

def _priv():
    """Was private when indexed."""
    return helper()
'''


def test_stale_private_and_self_drops_are_counted(tmp_path: Path) -> None:
    """In a file whose index entry disagrees with the tree (unvouched), a
    reference that lands in a stale PRIVATE span, or in a stale span of its
    own target (a self-edge), cannot be told apart from a drift artefact —
    so it is COUNTED as ``unattributed``, never silently lost. In a vouched
    file the same drops are by design (private context, recursion) and stay
    uncounted."""
    # Feature: FEAT-SCIP-001
    root = _repo(tmp_path)
    cfg = MonitorConfig(documents=())
    main = root / "pkg" / "main.py"
    main.write_text(_RENAMED_BEFORE, encoding="utf-8")
    stored = _code_index(root)  # indexed while the caller was `_priv`
    helper = _PREFIX + "`pkg.lib`/helper()."
    raw = tmp_path / "index.scip"
    raw.write_bytes(
        index(
            [
                # 0-based line 5 = `return helper()` inside `_priv`/`main_entry`
                document("pkg/main.py", [occurrence(helper, range_=[5, 11, 17])]),
                # 0-based line 4 = `return 1` inside helper's own span
                document("pkg/lib.py", [occurrence(helper, range_=[4, 11, 17])]),
            ]
        )
    )
    vouched = build_xrefs(
        read_scip(raw), stored, generated_by="t", tree_digests=file_digests(cfg, root)
    )
    assert vouched.edges == () and vouched.unattributed == 0  # by design

    main.write_text(_RENAMED_BEFORE.replace("def _priv", "def main_entry"), "utf-8")
    lib = root / "pkg" / "lib.py"
    lib.write_text(_LIB + "# edited\n", encoding="utf-8")
    stale = build_xrefs(
        read_scip(raw), stored, generated_by="t", tree_digests=file_digests(cfg, root)
    )
    assert stale.edges == ()
    assert stale.unattributed == 2  # the private drop + the self drop
    assert stale.input_digests is not None
    assert {"pkg/main.py", "pkg/lib.py"}.isdisjoint(stale.input_digests)


# ----------------------------------------------- xref round 4 (review + gaps)

#: The provenance stamps, spelled out independently of ``scip._STAMPS``: a
#: field moved into the stamp set — or a new field — breaks the census below.
_STAMP_FIELDS = {"generated_by", "source_sha"}

#: One older value per CONTENT field: an artifact on disk holding it must be
#: rewritten by an otherwise identical join.
_OLDER_CONTENT: dict[str, object] = {
    "schema_version": "0.9.0",
    "tool": "scip-python/0.6.5",
    "coverage": {},
    "unmapped": 1,
    "edges": (XrefEdge(source="symbol a.py#f", target="symbol b.py#g", count=1),),
    "unattributed": 1,
    "input_digests": {"a.py": "2" * 16},
    "input_languages": (),
}


def _content_base() -> XrefSet:
    return XrefSet(
        generated_by="custodex/test",
        tool="scip-python/0.6.6",
        source_sha="aaa",
        coverage={"python": "scip-python/0.6.6"},
        unmapped=0,
        edges=(),
        input_digests={"a.py": "1" * 16},
        input_languages=("python",),
    )


def test_the_content_census_covers_every_field_but_the_stamps() -> None:
    """Every ``XrefSet`` field is either one of the two provenance stamps or
    enrolled in the content census, so a newly added field is checked by
    :func:`test_every_non_stamp_field_is_content` automatically."""
    # Feature: FEAT-SCIP-001
    assert set(_OLDER_CONTENT) == set(XrefSet.model_fields) - _STAMP_FIELDS


@pytest.mark.parametrize("field", sorted(_OLDER_CONTENT))
def test_every_non_stamp_field_is_content(tmp_path: Path, field: str) -> None:
    """ "Everything but ``_STAMPS`` is content" (K7, ⟨R⟩2), field by field:
    an artifact on disk that differs from a new join ONLY in this field is
    rewritten exactly once and then left alone, and the stored field takes
    the new value — the honesty counters (``unmapped``) never go stale and
    an older ``schema_version`` is upgraded rather than kept forever."""
    # Feature: FEAT-SCIP-001
    base = _content_base()
    older = base.model_copy(update={field: _OLDER_CONTENT[field]})
    assert getattr(older, field) != getattr(base, field)
    cdmon = tmp_path / ".cdmon"
    assert write_xrefs(older, cdmon) is True
    assert write_xrefs(base, cdmon) is True  # this field alone rewrites…
    assert write_xrefs(base, cdmon) is False  # …once (K7)
    stored = read_xrefs(cdmon)
    assert stored is not None
    assert getattr(stored, field) == getattr(base, field)


def test_a_suffix_recovered_document_is_pinned_at_its_index_path(
    tmp_path: Path,
) -> None:
    """A SCIP run from another root names documents ``main.py`` /
    ``lib.py``; the join recovers them to ``pkg/main.py`` / ``pkg/lib.py``
    by unique suffix, and the PIN must use those index paths too — keyed by
    the raw SCIP path, every recovered file would read "caller data
    unknown" forever beside phantom pins for paths that never existed."""
    # Feature: FEAT-SCIP-001
    root = _repo(tmp_path)
    cfg = MonitorConfig(documents=())
    helper = _PREFIX + "`pkg.lib`/helper()."
    raw = tmp_path / "other-root.scip"
    raw.write_bytes(
        index(
            [
                document("main.py", [occurrence(helper, range_=[5, 4, 10])]),
                document("lib.py", []),
            ]
        )
    )
    xrefs = build_xrefs(
        read_scip(raw),
        _code_index(root),
        generated_by="t",
        tree_digests=file_digests(cfg, root),
    )
    assert set(xrefs.input_digests or {}) == {
        "pkg/__init__.py",
        "pkg/lib.py",
        "pkg/main.py",
    }
    assert [(e.source, e.target) for e in xrefs.edges] == [
        ("symbol pkg/main.py#caller", "symbol pkg/lib.py#helper")
    ]
    assert unknown_caller_files(xrefs, file_digests(cfg, root)) == ()


def test_unknown_caller_files_names_unpinned_edge_sources() -> None:
    """An edge whose SOURCE file the pin does not hold was joined through
    spans the join could not vouch for (the file was stale — e.g. deleted
    from the tree — when it ran). Once that file is gone from the listing
    too, only its edges remain: it is still reported unknown, so `cdx
    graph` never shows those REFERENCES as current. The path is everything
    before the LAST ``#`` — a path may hold one, a qualname never does."""
    # Feature: FEAT-SCIP-001
    xrefs = XrefSet(
        generated_by="t",
        tool="scip-python/0.6.6",
        coverage={"python": "scip-python/0.6.6"},
        unmapped=0,
        edges=(
            XrefEdge(
                source="symbol pkg/old.py#old_entry",
                target="symbol pkg/lib.py#helper",
                count=1,
            ),
            XrefEdge(
                source="symbol pkg/.#lock.py#Lock.run",
                target="symbol pkg/lib.py#helper",
                count=1,
            ),
        ),
        input_digests={"pkg/lib.py": "1" * 16},
        input_languages=("python",),
    )
    listing = {"pkg/lib.py": ("python", "1" * 16)}
    assert unknown_caller_files(xrefs, listing) == ("pkg/.#lock.py", "pkg/old.py")
    held = xrefs.model_copy(
        update={
            "input_digests": {
                "pkg/.#lock.py": "3" * 16,
                "pkg/lib.py": "1" * 16,
                "pkg/old.py": "2" * 16,
            }
        }
    )
    current = {
        **listing,
        "pkg/.#lock.py": ("python", "3" * 16),
        "pkg/old.py": ("python", "2" * 16),
    }
    assert unknown_caller_files(held, current) == ()


def test_a_fresh_build_vouches_by_the_whole_entry(tmp_path: Path) -> None:
    """``tree_index`` (a fresh :func:`build_code_index` of the tree) is the
    exact vouch: a file is pinned only when its WHOLE stored entry — spans
    and symbols, not just bytes — equals the fresh one. A stored index whose
    spans drifted over identical bytes (an extractor change) passes the
    content-only ``tree_digests`` check but not this one, and in the
    unvouched file even a private-span drop is counted. The two checks
    compose: given both, a file must pass both."""
    # Feature: FEAT-SCIP-001
    root = _repo(tmp_path)
    cfg = MonitorConfig(documents=())
    fresh = _code_index(root)
    drifted = fresh.model_copy(
        update={
            "files": tuple(
                f.model_copy(
                    update={
                        "symbols": tuple(
                            s.model_copy(update={"end_lineno": s.lineno})
                            if s.name == "caller"
                            else s
                            for s in f.symbols
                        )
                    }
                )
                if f.path == "pkg/main.py"
                else f
                for f in fresh.files
            )
        }
    )
    raw = tmp_path / "index.scip"
    raw.write_bytes(_scip_bytes())
    scip = read_scip(raw)
    by_content = build_xrefs(
        scip, drifted, generated_by="t", tree_digests=file_digests(cfg, root)
    )
    assert "pkg/main.py" in (by_content.input_digests or {})  # bytes agree
    by_entry = build_xrefs(scip, drifted, generated_by="t", tree_index=fresh)
    assert set(by_entry.input_digests or {}) == {"pkg/__init__.py", "pkg/lib.py"}
    assert by_entry.edges == by_content.edges  # the vouch narrows the pin only
    assert by_entry.unattributed == by_content.unattributed + 1
    exact = build_xrefs(scip, fresh, generated_by="t", tree_index=fresh)
    assert set(exact.input_digests or {}) == {
        "pkg/__init__.py",
        "pkg/lib.py",
        "pkg/main.py",
    }
    both = build_xrefs(scip, fresh, generated_by="t", tree_index=fresh, tree_digests={})
    assert both.input_digests == {}


def test_caller_currency_note_takes_the_verbs_remedy() -> None:
    """The note's facts are shared, its REMEDY is per verb: `cdx graph`
    judges the tree, so "bring the code index current…" is right for it
    (the default); `cdx impact` passes its own, because refreshing the
    code index would reset the very baseline it diffs against."""
    # Feature: FEAT-SCIP-001
    default = caller_currency_note(("pkg/a.py",))
    assert default is not None and "bring the code index current" in default
    own = caller_currency_note(("pkg/a.py",), remedy="re-run the indexer")
    assert own is not None
    assert own.endswith(": pkg/a.py (re-run the indexer)")
    assert "bring the code index current" not in own
    pre_pin = caller_currency_note(None, remedy="re-run the indexer")
    assert pre_pin is not None and "no input pin" in pre_pin
    assert pre_pin.endswith("(re-run the indexer)")


def test_a_span_tie_goes_to_the_first_symbol_in_index_order(tmp_path: Path) -> None:
    """Two spans of equal width can hold one reference — an all-name chain
    (``ALIAS = DEFAULT = helper`` makes two one-line variables) or a
    one-line class. The tie goes to the FIRST symbol in the index's sorted
    ``(name, lineno)`` order, so attribution never depends on extraction
    order (K10)."""
    # Feature: FEAT-SCIP-001
    root = _repo(tmp_path)
    (root / "pkg" / "main.py").write_text(
        "from pkg.lib import helper\n\nALIAS = DEFAULT = helper\n", "utf-8"
    )
    helper = _PREFIX + "`pkg.lib`/helper()."
    raw = tmp_path / "tie.scip"
    raw.write_bytes(
        index([document("pkg/main.py", [occurrence(helper, range_=[2, 18, 24])])])
    )
    xrefs = build_xrefs(read_scip(raw), _code_index(root), generated_by="t")
    assert [e.source for e in xrefs.edges] == ["symbol pkg/main.py#ALIAS"]


# ----------------------------------------------- xref round 5 (review + gaps)


def test_the_exact_vouch_and_the_stale_warning_name_the_same_files(
    tmp_path: Path,
) -> None:
    """The exact vouch compares the WHOLE stored entry with a fresh build —
    every symbol field included, so an entry that differs only in a
    docstring digest over identical bytes and spans is not vouched for.
    `cdx scip` names :func:`unsynced_paths` in its STALE warning, so the
    pin must be exactly the joined files that warning does NOT name: never
    a file warned "left unpinned" that is pinned anyway, never a silent
    unpin."""
    # Feature: FEAT-SCIP-001
    from custodex.codeindex import unsynced_paths

    root = _repo(tmp_path)
    fresh = _code_index(root)
    raw = tmp_path / "index.scip"
    raw.write_bytes(_scip_bytes())
    scip = read_scip(raw)
    joined = {"pkg/__init__.py", "pkg/lib.py", "pkg/main.py"}
    assert set(build_xrefs(scip, fresh, generated_by="t").input_digests or {}) == (
        joined
    )

    def legacy(paths: set[str]):
        return fresh.model_copy(
            update={
                "files": tuple(
                    f.model_copy(
                        update={
                            "symbols": tuple(
                                s.model_copy(update={"doc_digest": "0" * 16})
                                for s in f.symbols
                            )
                        }
                    )
                    if f.path in paths
                    else f
                    for f in fresh.files
                )
            }
        )

    # every joined file with a symbol (the empty pkg/__init__.py has none)
    for paths in ({"pkg/main.py"}, {"pkg/lib.py", "pkg/main.py"}):
        stored = legacy(paths)
        xrefs = build_xrefs(scip, stored, generated_by="t", tree_index=fresh)
        assert set(unsynced_paths(stored, fresh)) == paths
        assert set(xrefs.input_digests or {}) == joined - paths
        # the vouch narrows the pin only: identical spans, identical edges
        assert xrefs.edges == build_xrefs(scip, fresh, generated_by="t").edges
