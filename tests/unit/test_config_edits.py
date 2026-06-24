"""Validation suite for the typed pending-edit model (EDITOR E-03).

The :data:`ConfigEdit` discriminated union (tagged on ``action``) is the staged
"mapping ticket" payload the routes accept and the store persists. These tests pin
its validation contract: each action validates with its payload, an unknown/missing
``action`` is a loud error (K8), and ``extra="forbid"`` rejects stray fields. Pure
pydantic — no DB, no ``[server]`` extra needed.

Features: FEAT-SERVER-011
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from custodex.server.edits import (
    AddCodeRefEdit,
    ConfigEdit,
    CreateDocEdit,
    EditCodeRef,
    EditContextRef,
    EditDocStyle,
    RemoveCodeRefEdit,
    SetContextRefsEdit,
    SetDocStyleEdit,
    StoredConfigEdit,
)

_ADAPTER: TypeAdapter[ConfigEdit] = TypeAdapter(ConfigEdit)


def test_create_doc_validates_full_payload() -> None:
    edit = _ADAPTER.validate_python(
        {
            "action": "create_doc",
            "unit": "core",
            "doc_id": "guide",
            "path": "docs/guide.md",
            "audience": "user-guide",
            "code_refs": [{"path": "src/m.py", "symbols": ["Task"], "lines": "1-40"}],
            "context_refs": [{"path": "docs/ref.md", "note": "see also"}],
            "doc_style": {"tone": "friendly"},
        }
    )
    assert isinstance(edit, CreateDocEdit)
    assert edit.code_refs[0].symbols == ("Task",)
    assert edit.context_refs[0].note == "see also"
    assert edit.doc_style is not None and edit.doc_style.tone == "friendly"


def test_create_doc_minimal_payload_defaults() -> None:
    edit = _ADAPTER.validate_python(
        {
            "action": "create_doc",
            "unit": "core",
            "doc_id": "g",
            "path": "docs/g.md",
            "audience": "eng-guide",
        }
    )
    assert isinstance(edit, CreateDocEdit)
    assert edit.code_refs == ()
    assert edit.context_refs == ()
    assert edit.doc_style is None


def test_add_code_ref_validates() -> None:
    edit = _ADAPTER.validate_python(
        {
            "action": "add_code_ref",
            "unit": "core",
            "doc_id": "g",
            "ref": {"path": "src/x.py"},
        }
    )
    assert isinstance(edit, AddCodeRefEdit)
    assert edit.ref == EditCodeRef(path="src/x.py")


def test_remove_code_ref_validates() -> None:
    edit = _ADAPTER.validate_python(
        {"action": "remove_code_ref", "unit": "core", "doc_id": "g", "path": "src/x.py"}
    )
    assert isinstance(edit, RemoveCodeRefEdit)
    assert edit.path == "src/x.py"


def test_set_context_refs_validates() -> None:
    edit = _ADAPTER.validate_python(
        {
            "action": "set_context_refs",
            "unit": "core",
            "doc_id": "g",
            "context_refs": [{"path": "docs/a.md"}],
        }
    )
    assert isinstance(edit, SetContextRefsEdit)
    assert edit.context_refs == (EditContextRef(path="docs/a.md"),)


def test_set_doc_style_validates() -> None:
    edit = _ADAPTER.validate_python(
        {
            "action": "set_doc_style",
            "doc_id": "g",
            "doc_style": {"document_type": "tutorial", "vocabulary": "plain"},
        }
    )
    assert isinstance(edit, SetDocStyleEdit)
    assert edit.doc_style == EditDocStyle(document_type="tutorial", vocabulary="plain")


def test_unknown_action_is_loud() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python({"action": "frobnicate", "doc_id": "g"})


def test_missing_action_is_loud() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python({"unit": "core", "doc_id": "g"})


def test_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(
            {
                "action": "remove_code_ref",
                "unit": "core",
                "doc_id": "g",
                "path": "src/x.py",
                "rogue": "nope",
            }
        )


def test_wrong_payload_for_action_is_loud() -> None:
    # set_doc_style has no `unit` field — supplying one trips extra="forbid".
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(
            {"action": "set_doc_style", "doc_id": "g", "unit": "core", "doc_style": {}}
        )


def test_stored_config_edit_round_trips_through_json() -> None:
    edit = CreateDocEdit(
        unit="core", doc_id="g", path="docs/g.md", audience="user-guide"
    )
    stored = StoredConfigEdit(
        edit_id="e1", status="pending", created_at="2026-06-08T00:00:00Z", edit=edit
    )
    reparsed = StoredConfigEdit.model_validate(stored.model_dump(mode="json"))
    assert reparsed == stored
    assert isinstance(reparsed.edit, CreateDocEdit)
    assert reparsed.applied_at is None
