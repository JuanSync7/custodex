"""Tests for custodex.manifest (CDM-03).

Covers front-matter parsing (with + without), managed-region parsing including
malformed regions raising DriftError (K8), set_region preserving bytes outside
the markers (K7), fingerprint round-trip, and re-rendering. TDD (K9).

Features: FEAT-MANIFEST-001, FEAT-MANIFEST-002, FEAT-MANIFEST-003
Features: FEAT-MANIFEST-004, FEAT-MANIFEST-005, FEAT-MANIFEST-006
Features: FEAT-MANIFEST-007, FEAT-MANIFEST-008, FEAT-MANIFEST-009
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custodex.errors import DriftError
from custodex.extract import SurfaceFingerprint
from custodex.manifest import (
    Doc,
    drop_upstream_hash,
    parse_doc,
    parse_text,
    region_body_hash,
    region_is_locked,
    regions,
    render_doc,
    set_fingerprint,
    set_fingerprint_tiers,
    set_region,
    set_region_hash,
    set_upstream_hash,
    stored_fingerprint,
    stored_fingerprint_tiers,
    stored_region_hash,
    stored_upstream_hashes,
)

WITH_FM = """\
---
title: User Guide
cdm:
  fingerprint: abc123
---
# Heading

<!-- CDM:BEGIN symbols -->
old body
<!-- CDM:END symbols -->

Trailing prose.
"""

NO_FM = """\
# Heading

<!-- CDM:BEGIN symbols -->
body line
<!-- CDM:END symbols -->
"""


def _write(tmp_path: Path, text: str, name: str = "doc.md") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_parse_with_front_matter(tmp_path: Path) -> None:
    doc = parse_doc(_write(tmp_path, WITH_FM))
    assert doc.meta["title"] == "User Guide"
    assert doc.meta["cdm"]["fingerprint"] == "abc123"
    assert doc.body.startswith("# Heading")
    assert "title: User Guide" not in doc.body
    assert doc.raw == WITH_FM


def test_parse_without_front_matter(tmp_path: Path) -> None:
    doc = parse_doc(_write(tmp_path, NO_FM))
    assert doc.meta == {}
    assert doc.body == NO_FM
    assert doc.raw == NO_FM


def test_stored_fingerprint_present_and_absent(tmp_path: Path) -> None:
    assert stored_fingerprint(parse_doc(_write(tmp_path, WITH_FM))) == "abc123"
    assert stored_fingerprint(parse_doc(_write(tmp_path, NO_FM))) is None


def test_set_fingerprint_creates_and_updates() -> None:
    meta = set_fingerprint({}, "deadbeef")
    assert meta["cdm"]["fingerprint"] == "deadbeef"
    meta2 = set_fingerprint({"title": "X", "cdm": {"other": 1}}, "f00d")
    assert meta2["cdm"]["fingerprint"] == "f00d"
    assert meta2["cdm"]["other"] == 1
    assert meta2["title"] == "X"


def test_regions_maps_id_to_body(tmp_path: Path) -> None:
    doc = parse_doc(_write(tmp_path, WITH_FM))
    assert regions(doc) == {"symbols": "old body"}


def test_regions_unterminated_raises(tmp_path: Path) -> None:
    text = "<!-- CDM:BEGIN symbols -->\nbody\n"
    with pytest.raises(DriftError, match="unterminated"):
        regions(parse_doc(_write(tmp_path, text)))


def test_regions_duplicate_raises(tmp_path: Path) -> None:
    text = (
        "<!-- CDM:BEGIN s -->\na\n<!-- CDM:END s -->\n"
        "<!-- CDM:BEGIN s -->\nb\n<!-- CDM:END s -->\n"
    )
    with pytest.raises(DriftError, match="duplicate"):
        regions(parse_doc(_write(tmp_path, text)))


def test_regions_nested_raises(tmp_path: Path) -> None:
    text = (
        "<!-- CDM:BEGIN a -->\n<!-- CDM:BEGIN b -->\n"
        "<!-- CDM:END b -->\n<!-- CDM:END a -->\n"
    )
    with pytest.raises(DriftError, match="nest"):
        regions(parse_doc(_write(tmp_path, text)))


def test_regions_end_without_begin_raises(tmp_path: Path) -> None:
    with pytest.raises(DriftError, match="no open region"):
        regions(parse_doc(_write(tmp_path, "<!-- CDM:END s -->\n")))


def test_regions_mismatched_end_raises(tmp_path: Path) -> None:
    text = "<!-- CDM:BEGIN a -->\n<!-- CDM:END b -->\n"
    with pytest.raises(DriftError, match="does not match"):
        regions(parse_doc(_write(tmp_path, text)))


def test_set_region_replaces_and_reports_changed() -> None:
    body = "intro\n<!-- CDM:BEGIN s -->\nold\n<!-- CDM:END s -->\noutro\n"
    new, changed = set_region(body, "s", "new")
    assert changed is True
    assert "new" in new
    assert "old" not in new
    # Bytes outside the markers are byte-for-byte preserved (K7).
    assert new.startswith("intro\n")
    assert new.endswith("outro\n")
    assert "<!-- CDM:BEGIN s -->\n" in new
    assert "<!-- CDM:END s -->\n" in new


def test_set_region_idempotent_when_same() -> None:
    body = "<!-- CDM:BEGIN s -->\nsame\n<!-- CDM:END s -->\n"
    new, changed = set_region(body, "same not", "x")  # missing id -> no change
    assert changed is False
    assert new == body
    new2, changed2 = set_region(body, "s", "same")
    assert changed2 is False
    assert new2 == body


def test_set_region_unknown_id_no_change() -> None:
    body = "<!-- CDM:BEGIN s -->\nx\n<!-- CDM:END s -->\n"
    out, changed = set_region(body, "nope", "y")
    assert changed is False
    assert out == body


def test_render_doc_round_trips(tmp_path: Path) -> None:
    doc = parse_doc(_write(tmp_path, WITH_FM))
    text = render_doc(doc.meta, doc.body)
    # Re-parsing the rendered text yields the same meta and body.
    reparsed_path = _write(tmp_path, text, name="re.md")
    reparsed = parse_doc(reparsed_path)
    assert reparsed.meta == doc.meta
    assert reparsed.body == doc.body


def test_render_doc_no_meta_emits_body_only() -> None:
    assert render_doc({}, "just body\n") == "just body\n"


def test_parse_non_mapping_front_matter_raises(tmp_path: Path) -> None:
    text = "---\n- just\n- a list\n---\nbody\n"
    with pytest.raises(DriftError, match="must be a mapping"):
        parse_doc(_write(tmp_path, text))


def test_parse_malformed_yaml_front_matter_raises(tmp_path: Path) -> None:
    text = "---\nkey: : bad: :\n---\nbody\n"
    with pytest.raises(DriftError, match="Malformed YAML front matter"):
        parse_doc(_write(tmp_path, text))


def test_parse_empty_front_matter(tmp_path: Path) -> None:
    doc = parse_doc(_write(tmp_path, "---\n---\nbody\n"))
    assert doc.meta == {}
    assert doc.body == "body\n"


def test_set_region_unterminated_raises() -> None:
    with pytest.raises(DriftError, match="unterminated"):
        set_region("<!-- CDM:BEGIN s -->\nbody\n", "s", "x")


def test_set_region_nested_raises() -> None:
    body = "<!-- CDM:BEGIN a -->\n<!-- CDM:BEGIN b -->\n<!-- CDM:END b -->\n"
    with pytest.raises(DriftError, match="nest"):
        set_region(body, "a", "x")


def test_set_region_end_without_begin_raises() -> None:
    with pytest.raises(DriftError, match="no open region"):
        set_region("<!-- CDM:END s -->\n", "s", "x")


def test_set_region_mismatched_end_raises() -> None:
    with pytest.raises(DriftError, match="does not match"):
        set_region("<!-- CDM:BEGIN a -->\n<!-- CDM:END b -->\n", "a", "x")


# --- B-03: per-region content hash (the lock) -------------------------------


def test_region_body_hash_is_deterministic_and_short() -> None:
    h = region_body_hash("some body\nlines")
    assert h == region_body_hash("some body\nlines")
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_region_body_hash_normalizes_line_endings() -> None:
    """CRLF-normalized like layout.md_source_hash, for portability (K10)."""
    assert region_body_hash("a\r\nb") == region_body_hash("a\nb")
    assert region_body_hash("a\rb") == region_body_hash("a\nb")
    # different content -> different hash
    assert region_body_hash("a\nb") != region_body_hash("a\nc")


def test_region_body_hash_matches_layout_md_source_hash() -> None:
    """Mirrors the layout standard's md_source_hash algorithm exactly."""
    from custodex.layout import md_source_hash

    assert region_body_hash("x\r\ny\n") == md_source_hash("x\r\ny\n")


def test_set_and_stored_region_hash_round_trip(tmp_path: Path) -> None:
    meta = set_region_hash({}, "symbols", "deadbeef00112233")
    doc = parse_text(render_doc(meta, "# body\n"))
    assert stored_region_hash(doc, "symbols") == "deadbeef00112233"
    assert stored_region_hash(doc, "absent") is None


def test_stored_region_hash_absent_returns_none(tmp_path: Path) -> None:
    doc = parse_doc(_write(tmp_path, WITH_FM))
    assert stored_region_hash(doc, "symbols") is None


def test_set_region_hash_is_additive_under_cdm() -> None:
    """region_hashes lives under cdm and preserves siblings (fingerprint etc.)."""
    meta = set_fingerprint({"title": "X"}, "fp123")
    meta = set_region_hash(meta, "a", "h_a")
    meta = set_region_hash(meta, "b", "h_b")
    assert meta["cdm"]["fingerprint"] == "fp123"
    assert meta["title"] == "X"
    assert meta["cdm"]["region_hashes"] == {"a": "h_a", "b": "h_b"}


def test_set_fingerprint_preserves_region_hashes() -> None:
    """The whole cdm map (incl. region_hashes) survives a fingerprint heal."""
    meta = set_region_hash({}, "symbols", "hh")
    meta = set_fingerprint(meta, "newfp")
    assert meta["cdm"]["fingerprint"] == "newfp"
    assert meta["cdm"]["region_hashes"] == {"symbols": "hh"}


def test_region_is_locked_predicate() -> None:
    body = "the engine wrote this\n"
    meta = set_region_hash({}, "symbols", region_body_hash(body))
    doc = parse_text(render_doc(meta, "# x\n"))
    # body unchanged from the stamp -> NOT locked.
    assert region_is_locked(doc, "symbols", body) is False
    # body diverged (a human edited it) -> LOCKED.
    assert region_is_locked(doc, "symbols", "a human changed it\n") is True
    # no stored hash at all -> never locked.
    doc2 = parse_text("# x\n")
    assert region_is_locked(doc2, "symbols", body) is False


# --------------------------------------------------------------------------- #
# P-02: tiered fingerprint front-matter accessors (additive)                   #
# --------------------------------------------------------------------------- #
def _doc_with_meta(meta: dict) -> Doc:
    return Doc(path=Path("d.md"), meta=meta, body="", raw="")


def test_fingerprint_tiers_round_trip() -> None:
    fp = SurfaceFingerprint(
        signature="aaaaaaaaaaaaaaaa",
        docstring="bbbbbbbbbbbbbbbb",
        body="cccccccccccccccc",
        composite="dddddddddddddddd",
    )
    meta = set_fingerprint_tiers({}, fp)
    assert stored_fingerprint_tiers(_doc_with_meta(meta)) == fp


def test_fingerprint_tiers_absent_returns_none() -> None:
    assert stored_fingerprint_tiers(parse_text("# x\n")) is None
    # An old doc with a composite fingerprint but no tiers block -> None.
    assert (
        stored_fingerprint_tiers(_doc_with_meta({"cdm": {"fingerprint": "x"}})) is None
    )


def test_fingerprint_tiers_none_subtiers_round_trip() -> None:
    """A user-guide fingerprint (docstring/body None) round-trips faithfully."""
    fp = SurfaceFingerprint(
        signature="aaaaaaaaaaaaaaaa",
        docstring=None,
        body=None,
        composite="aaaaaaaaaaaaaaaa",
    )
    meta = set_fingerprint_tiers({}, fp)
    assert stored_fingerprint_tiers(_doc_with_meta(meta)) == fp


def test_set_fingerprint_tiers_is_additive() -> None:
    """Stamping tiers preserves the composite fingerprint and region hashes."""
    fp = SurfaceFingerprint(signature="s", docstring="d", body="b", composite="comp")
    meta = {"cdm": {"fingerprint": "comp", "region_hashes": {"symbols": "rh"}}}
    out = set_fingerprint_tiers(meta, fp)
    assert stored_fingerprint(_doc_with_meta(out)) == "comp"
    assert stored_region_hash(_doc_with_meta(out), "symbols") == "rh"
    assert stored_fingerprint_tiers(_doc_with_meta(out)) == fp
    assert meta["cdm"] == {"fingerprint": "comp", "region_hashes": {"symbols": "rh"}}


# --------------------------------------------------------------------------- #
# P-04: region anchors (stable symbol-identity set per region, additive)       #
# --------------------------------------------------------------------------- #
def test_region_anchors_round_trip() -> None:
    from custodex.manifest import set_region_anchors, stored_region_anchors

    meta = set_region_anchors({}, "symbols", ("bbbb", "aaaa"))
    # Stored sorted for diff-stable front matter (K10).
    assert stored_region_anchors(_doc_with_meta(meta), "symbols") == ("aaaa", "bbbb")


def test_region_anchors_absent_returns_none() -> None:
    from custodex.manifest import stored_region_anchors

    assert stored_region_anchors(parse_text("# x\n"), "symbols") is None
    assert (
        stored_region_anchors(_doc_with_meta({"cdm": {"fingerprint": "x"}}), "symbols")
        is None
    )


def test_set_region_anchors_is_additive() -> None:
    """Stamping anchors preserves the composite fingerprint, tiers, region hashes."""
    from custodex.manifest import (
        set_region_anchors,
        stored_region_anchors,
        stored_region_hash,
    )

    meta = {
        "cdm": {
            "fingerprint": "comp",
            "fingerprint_tiers": {"signature": "s", "composite": "comp"},
            "region_hashes": {"symbols": "rh"},
        }
    }
    out = set_region_anchors(meta, "symbols", ("a1", "a2"))
    d = _doc_with_meta(out)
    assert stored_fingerprint(d) == "comp"
    assert stored_region_hash(d, "symbols") == "rh"
    assert stored_fingerprint_tiers(d) is not None
    assert stored_region_anchors(d, "symbols") == ("a1", "a2")
    assert "region_anchors" not in meta["cdm"]  # original untouched


# --------------------------------------------------------------------------- #
# DIG-01: per-symbol signature digests under cdm.symbol_sigs
#
# Feature: FEAT-DRIFT-012
# --------------------------------------------------------------------------- #
def test_symbol_sigs_round_trip() -> None:
    from custodex.manifest import set_symbol_sigs, stored_symbol_sigs

    meta = set_symbol_sigs({}, {"b_anchor": "h2", "a_anchor": "h1"})
    doc = parse_text(render_doc(meta, "# body\n"))
    # Stored with sorted keys for diff-stable front matter (K10).
    assert stored_symbol_sigs(doc) == {"a_anchor": "h1", "b_anchor": "h2"}
    assert list(doc.meta["cdm"]["symbol_sigs"]) == ["a_anchor", "b_anchor"]


def test_symbol_sigs_absent_returns_none_but_empty_block_returns_empty() -> None:
    """None distinguishes a pre-DIG-01 doc from a stamped-but-symbol-less doc."""
    from custodex.manifest import stored_symbol_sigs

    assert stored_symbol_sigs(parse_text("# x\n")) is None
    assert stored_symbol_sigs(_doc_with_meta({"cdm": {"fingerprint": "x"}})) is None
    # present-but-empty ⇒ {}, NOT None (a doc that was stamped with no symbols).
    assert stored_symbol_sigs(_doc_with_meta({"cdm": {"symbol_sigs": {}}})) == {}


def test_set_symbol_sigs_is_additive() -> None:
    """Stamping symbol_sigs preserves the fingerprint, tiers, region anchors, edges."""
    from custodex.manifest import (
        set_symbol_sigs,
        stored_region_anchors,
        stored_symbol_sigs,
    )

    meta = {
        "cdm": {
            "fingerprint": "comp",
            "fingerprint_tiers": {"signature": "s", "composite": "comp"},
            "region_anchors": {"symbols": ["a1"]},
            "upstream_hashes": {"overview": "hh"},
        }
    }
    out = set_symbol_sigs(meta, {"a1": "sig1"})
    d = _doc_with_meta(out)
    assert stored_fingerprint(d) == "comp"
    assert stored_fingerprint_tiers(d) is not None
    assert stored_region_anchors(d, "symbols") == ("a1",)
    assert out["cdm"]["upstream_hashes"] == {"overview": "hh"}
    assert stored_symbol_sigs(d) == {"a1": "sig1"}
    assert "symbol_sigs" not in meta["cdm"]  # original untouched


def test_set_fingerprint_preserves_symbol_sigs() -> None:
    """The per-symbol digests survive a later fingerprint heal (zero blast radius)."""
    from custodex.manifest import set_symbol_sigs, stored_symbol_sigs

    meta = set_symbol_sigs({}, {"a1": "sig1"})
    meta = set_fingerprint(meta, "newfp")
    assert meta["cdm"]["fingerprint"] == "newfp"
    assert stored_symbol_sigs(_doc_with_meta(meta)) == {"a1": "sig1"}


# --------------------------------------------------------------------------- #
# EPIC B (B-02): per-edge upstream stamps under cdm.upstream_hashes
# --------------------------------------------------------------------------- #
def test_set_and_stored_upstream_hash_round_trip() -> None:
    """An upstream stamp round-trips through render + parse (K7)."""
    meta = set_upstream_hash({}, "overview", "deadbeef00112233")
    doc = parse_text(render_doc(meta, "# body\n"))
    assert stored_upstream_hashes(doc) == {"overview": "deadbeef00112233"}


def test_stored_upstream_hashes_absent_is_empty() -> None:
    """A doc with no edge stamps reports an empty mapping (not None)."""
    doc = parse_text("# body only\n")
    assert stored_upstream_hashes(doc) == {}


def test_set_upstream_hash_is_additive_under_cdm() -> None:
    """upstream_hashes lives under cdm and preserves siblings (fingerprint etc.)."""
    meta = set_fingerprint({"title": "X"}, "fp123")
    meta = set_upstream_hash(meta, "overview", "h_o")
    meta = set_upstream_hash(meta, "glossary", "h_g")
    assert meta["cdm"]["fingerprint"] == "fp123"
    assert meta["title"] == "X"
    assert meta["cdm"]["upstream_hashes"] == {"overview": "h_o", "glossary": "h_g"}


def test_set_fingerprint_preserves_upstream_hashes() -> None:
    """The edge stamps survive a later fingerprint heal (zero blast radius, B-03)."""
    meta = set_upstream_hash({}, "overview", "hh")
    meta = set_fingerprint(meta, "newfp")
    assert meta["cdm"]["fingerprint"] == "newfp"
    assert meta["cdm"]["upstream_hashes"] == {"overview": "hh"}


def test_drop_upstream_hash_removes_one_stamp() -> None:
    """Dropping one edge stamp leaves the siblings and the fingerprint intact."""
    meta = set_upstream_hash({}, "overview", "h_o")
    meta = set_upstream_hash(meta, "glossary", "h_g")
    meta = set_fingerprint(meta, "fp")
    meta = drop_upstream_hash(meta, "overview")
    assert meta["cdm"]["upstream_hashes"] == {"glossary": "h_g"}
    assert meta["cdm"]["fingerprint"] == "fp"


def test_drop_upstream_hash_absent_is_noop() -> None:
    """Dropping a stamp that does not exist is a harmless no-op (K7)."""
    meta = set_upstream_hash({}, "overview", "h_o")
    same = drop_upstream_hash(meta, "nonexistent")
    assert same["cdm"]["upstream_hashes"] == {"overview": "h_o"}
