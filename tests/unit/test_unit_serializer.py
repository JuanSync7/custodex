"""EDITOR E-01: the unit-file serializer + pure model editors (config.py).

Pins the §2 contract: ``load_unit_file(write(dump_unit_file(u))) == u`` (true
round-trip across code_refs with symbols/lines, context_refs, multiple docs,
region fields), idempotent dump (byte-identical second pass, K7), and the four
pure model editors (upsert/add/remove/set) returning NEW frozen models that
survive a round-trip.

Features: FEAT-CONFIGV2-014
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_doc_monitor.config import (
    Audience,
    CodeRef,
    ContextRef,
    DocumentSpec,
    RegionMode,
    UnitFile,
    UnitFrontmatter,
    add_code_ref,
    dump_unit_file,
    load_unit_file,
    remove_code_ref,
    set_context_refs,
    set_document_owner,
    upsert_document,
)
from code_doc_monitor.errors import ConfigError

NOW = "2026-06-08"


def _unit() -> UnitFile:
    """A representative unit: code_refs WITH symbols+lines, context_refs, 2 docs."""
    fm = UnitFrontmatter(
        **{
            "cdmon-config-version": "2.0.0",
            "unit": "core",
            "title": "core engine",
            "owner": "cdmon-team",
            "created": "2026-06-07",
            "updated": NOW,
        }
    )
    foundation = DocumentSpec(
        id="foundation",
        path="docs/api/foundation.md",
        audience=Audience.ENG_GUIDE,
        region_keys=("symbols",),
        region_modes={"symbols": RegionMode.GENERATED},
        code_refs=(
            CodeRef(path="code_doc_monitor/config.py"),
            CodeRef(
                path="code_doc_monitor/schema.py", symbols=("Verdict", "ProposedFix")
            ),
            CodeRef(path="code_doc_monitor/blocks.py", lines=((1, 10), (20, 25))),
        ),
        context_refs=(
            ContextRef(path="docs/api/index.md", note="the landing page"),
            ContextRef(path="code_doc_monitor/errors.py"),
        ),
    )
    index_doc = DocumentSpec(
        id="api-index",
        path="docs/api/index.md",
        audience=Audience.USER_GUIDE,
        index=True,
        region_keys=("api-index",),
    )
    return UnitFile(
        **{
            "frontmatter": fm,
            "dir-covered": ("code_doc_monitor",),
            "source-files-format": (".py",),
            "documents": (foundation, index_doc),
        }
    )


def _roundtrip(unit: UnitFile, tmp_path: Path, now: str = NOW) -> UnitFile:
    p = tmp_path / "core.yaml"
    p.write_text(dump_unit_file(unit, now=now), encoding="utf-8")
    return load_unit_file(p)


def test_dump_round_trips_to_equal_model(tmp_path: Path) -> None:
    """load_unit_file(write(dump_unit_file(u))) == u (full fidelity)."""
    unit = _unit()
    assert _roundtrip(unit, tmp_path) == unit


def test_dump_is_idempotent(tmp_path: Path) -> None:
    """Dumping a loaded-then-dumped unit is byte-identical (K7)."""
    unit = _unit()
    text1 = dump_unit_file(unit, now=NOW)
    (tmp_path / "core.yaml").write_text(text1, encoding="utf-8")
    reloaded = load_unit_file(tmp_path / "core.yaml")
    text2 = dump_unit_file(reloaded, now=NOW)
    assert text1 == text2


def test_dump_refreshes_updated_field(tmp_path: Path) -> None:
    """``dump_unit_file`` writes ``now`` into the front-matter ``updated:`` field."""
    unit = _unit()
    out = _roundtrip(unit, tmp_path, now="2099-01-01")
    assert out.frontmatter.updated == "2099-01-01"
    # Every other front-matter field is carried through unchanged.
    assert out.frontmatter.created == "2026-06-07"
    assert out.frontmatter.unit == "core"
    assert out.frontmatter.title == "core engine"


def test_upsert_document_replaces_in_place_and_appends(tmp_path: Path) -> None:
    """upsert replaces an existing doc by id (keeping position) or appends a new one."""
    unit = _unit()
    # Replace foundation with a modified copy.
    new_foundation = unit.documents[0].model_copy(update={"path": "docs/changed.md"})
    replaced = upsert_document(unit, new_foundation)
    assert replaced is not unit  # new model
    assert replaced.documents[0].path == "docs/changed.md"
    assert len(replaced.documents) == len(unit.documents)
    # Append a brand-new doc.
    extra = DocumentSpec(id="ops", path="docs/ops.md", audience=Audience.ENG_GUIDE)
    appended = upsert_document(unit, extra)
    assert appended.documents[-1].id == "ops"
    assert len(appended.documents) == len(unit.documents) + 1
    # Survives a round-trip.
    assert _roundtrip(appended, tmp_path) == appended


def test_add_and_remove_code_ref(tmp_path: Path) -> None:
    """add_code_ref appends; remove_code_ref drops by path; both pure + round-trip."""
    unit = _unit()
    ref = CodeRef(path="code_doc_monitor/heal.py", symbols=("apply_fix",))
    added = add_code_ref(unit, "foundation", ref)
    assert ref in added.documents[0].code_refs
    assert unit.documents[0].code_refs != added.documents[0].code_refs  # no mutation
    removed = remove_code_ref(added, "foundation", "code_doc_monitor/heal.py")
    assert removed.documents[0].code_refs == unit.documents[0].code_refs
    assert _roundtrip(added, tmp_path) == added


def test_set_context_refs_replaces_wholesale(tmp_path: Path) -> None:
    """set_context_refs swaps the whole list and round-trips."""
    unit = _unit()
    refs = (ContextRef(path="docs/new.md", note="hi"),)
    out = set_context_refs(unit, "foundation", refs)
    assert out.documents[0].context_refs == refs
    assert _roundtrip(out, tmp_path) == out


def test_editors_loud_on_unknown_doc_id() -> None:
    """add/remove/set all raise a loud ConfigError for an unknown doc id (K8)."""
    unit = _unit()
    with pytest.raises(ConfigError):
        add_code_ref(unit, "nope", CodeRef(path="x.py"))
    with pytest.raises(ConfigError):
        remove_code_ref(unit, "nope", "x.py")
    with pytest.raises(ConfigError):
        set_context_refs(unit, "nope", ())


def test_remove_code_ref_loud_on_missing_path() -> None:
    """Removing a code_ref that is not present is a loud ConfigError (K8)."""
    unit = _unit()
    with pytest.raises(ConfigError):
        remove_code_ref(unit, "foundation", "code_doc_monitor/not-there.py")


def test_set_context_refs_rejects_duplicate_path() -> None:
    """A duplicate path in the replacement set is rejected loudly (K8)."""
    unit = _unit()
    dup = (ContextRef(path="docs/a.md"), ContextRef(path="docs/a.md"))
    with pytest.raises(ConfigError):
        set_context_refs(unit, "foundation", dup)


def test_set_document_owner_sets_partial_and_round_trips(tmp_path: Path) -> None:
    """set_document_owner reassigns owner/team/dri; None leaves a field; round-trips.

    Features: FEAT-OWNERSHIP-008
    """
    unit = _unit()  # the foundation doc starts unowned
    out = set_document_owner(unit, "foundation", owner="team-a", dri="alice")
    assert out is not unit  # NEW frozen model (no mutation, B-02)
    doc = out.documents[0]
    assert (doc.owner, doc.dri, doc.team) == ("team-a", "alice", None)
    # partial: setting only the dri keeps owner/team
    out2 = set_document_owner(out, "foundation", dri="bob")
    assert (out2.documents[0].owner, out2.documents[0].dri) == ("team-a", "bob")
    # the reassignment survives a dump→load round-trip (K7)
    assert _roundtrip(out2, tmp_path) == out2


def test_set_document_owner_loud_on_unknown_doc() -> None:
    """An unknown doc id is a loud ConfigError (K8).

    Features: FEAT-OWNERSHIP-008
    """
    with pytest.raises(ConfigError):
        set_document_owner(_unit(), "nope", owner="x")
