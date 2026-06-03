"""Tests for code_doc_monitor.manifest (CDM-03).

Covers front-matter parsing (with + without), managed-region parsing including
malformed regions raising DriftError (K8), set_region preserving bytes outside
the markers (K7), fingerprint round-trip, and re-rendering. TDD (K9).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_doc_monitor.errors import DriftError
from code_doc_monitor.manifest import (
    parse_doc,
    regions,
    render_doc,
    set_fingerprint,
    set_region,
    stored_fingerprint,
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
