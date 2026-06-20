"""Typed pending config edits — the staged "mapping ticket" model (EDITOR E-03).

A web edit to the document↔code mapping is NOT applied to disk immediately: it is
staged as a row in the ``config_edits`` table (the "ticket"), then a later
"Generate / make live" action (E-06) applies the staged edits to the on-disk
``config/cdmon/*.yaml`` and heals the docs. This module defines the typed payload
of one such ticket — a :class:`ConfigEdit` discriminated union on ``action`` — plus
:class:`StoredConfigEdit`, the persisted envelope (edit + status + timestamps) the
store returns.

It lives in the server subpackage but imports nothing from ``fastapi`` / the store
itself (only pydantic + stdlib), so both the store (``db.py`` / ``store.py``) and the
later routes can import it with no cycle. Models are frozen + ``extra="forbid"`` so an
unknown ``action`` or a stray field is a loud validation error (K8); the discriminated
union keeps mypy honest about which payload fields each action carries.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "EditCodeRef",
    "EditContextRef",
    "EditDocStyle",
    "CreateDocEdit",
    "AddCodeRefEdit",
    "RemoveCodeRefEdit",
    "SetContextRefsEdit",
    "SetDocStyleEdit",
    "ReassignOwnerEdit",
    "ConfigEdit",
    "StoredConfigEdit",
]

# Frozen + extra="forbid": a staged edit is an audited artifact stored as the FULL
# JSON source of truth (K6); a stray/unknown field is a loud K8 error.
_EDIT_CONFIG = ConfigDict(extra="forbid", frozen=True)


class EditCodeRef(BaseModel):
    """A code_ref payload inside an edit — a subset of the on-disk ``CodeRef``.

    Minimal but sufficient for E-06 generation: a repo-relative ``path`` plus the
    optional ``symbols`` it owns there (empty = whole file) and an optional 1-based
    inclusive ``lines`` range string (e.g. ``"10-42"``). The richer extract/lang
    knobs of the full :class:`~code_doc_monitor.config.CodeRef` are not surfaced in
    the editor — generation maps these onto a whole-file/symbol/line code_ref.
    """

    model_config = _EDIT_CONFIG

    path: str
    symbols: tuple[str, ...] = ()
    lines: str | None = None


class EditContextRef(BaseModel):
    """A context_ref payload inside an edit — mirrors the on-disk ``ContextRef``.

    Generation context ("glance-through"), NEVER coverage (K6): a repo-relative
    ``path`` and an optional human ``note``.
    """

    model_config = _EDIT_CONFIG

    path: str
    note: str | None = None


class EditDocStyle(BaseModel):
    """A doc-style selection payload — the four category options, all optional.

    Mirrors the four ``doc-style.yaml`` category dimensions
    (``document_type``/``tone``/``writing_style``/``vocabulary``). Each is optional
    so an edit may set only the dimensions the author changed; generation resolves
    the rest from the document's existing/defaults selection.
    """

    model_config = _EDIT_CONFIG

    document_type: str | None = None
    tone: str | None = None
    writing_style: str | None = None
    vocabulary: str | None = None


class CreateDocEdit(BaseModel):
    """Create (or fully define) a document entry under a unit (``action='create_doc'``).

    Carries the new document's ``unit``/``doc_id``/``path``/``audience`` plus its
    optional initial ``code_refs`` (documented surface), ``context_refs`` (glance
    context, K6), and ``doc_style`` selection. E-06 upserts this into the unit yaml.
    """

    model_config = _EDIT_CONFIG

    action: Literal["create_doc"] = "create_doc"
    unit: str
    doc_id: str
    path: str
    audience: str
    code_refs: tuple[EditCodeRef, ...] = ()
    context_refs: tuple[EditContextRef, ...] = ()
    doc_style: EditDocStyle | None = None


class AddCodeRefEdit(BaseModel):
    """Add one code_ref to an existing document (``action='add_code_ref'``)."""

    model_config = _EDIT_CONFIG

    action: Literal["add_code_ref"] = "add_code_ref"
    unit: str
    doc_id: str
    ref: EditCodeRef


class RemoveCodeRefEdit(BaseModel):
    """Remove a code_ref by ``path`` from a document (``action='remove_code_ref'``)."""

    model_config = _EDIT_CONFIG

    action: Literal["remove_code_ref"] = "remove_code_ref"
    unit: str
    doc_id: str
    path: str


class SetContextRefsEdit(BaseModel):
    """Replace a document's ``context_refs`` wholesale (``action='set_context_refs'``).

    The K6 generation-context list; never coverage. An empty list clears them.
    """

    model_config = _EDIT_CONFIG

    action: Literal["set_context_refs"] = "set_context_refs"
    unit: str
    doc_id: str
    context_refs: tuple[EditContextRef, ...] = ()


class SetDocStyleEdit(BaseModel):
    """Set/override a document's doc-style selection (``action='set_doc_style'``).

    Scoped by ``doc_id`` alone (the doc-style map is unit-independent — it keys on
    document id), carrying the four-category :class:`EditDocStyle` selection.
    """

    model_config = _EDIT_CONFIG

    action: Literal["set_doc_style"] = "set_doc_style"
    doc_id: str
    doc_style: EditDocStyle


class ReassignOwnerEdit(BaseModel):
    """Reassign a document's owner/team/dri (``action='reassign_owner'``, EPIC OWN).

    The human fix for an orphan (config = truth): a provided value SETS that field,
    while ``None`` (the default / omitted) LEAVES the existing value — so a partial
    reassignment (e.g. just a new ``dri`` when the team stays) keeps owner/team.
    """

    model_config = _EDIT_CONFIG

    action: Literal["reassign_owner"] = "reassign_owner"
    unit: str
    doc_id: str
    owner: str | None = None
    team: str | None = None
    dri: str | None = None


# The tagged union the store persists + the routes accept. ``action`` is the
# discriminator: validation routes to the matching payload model and a missing/
# unknown ``action`` (or a payload field that does not belong) is a loud K8 error.
ConfigEdit = Annotated[
    CreateDocEdit
    | AddCodeRefEdit
    | RemoveCodeRefEdit
    | SetContextRefsEdit
    | SetDocStyleEdit
    | ReassignOwnerEdit,
    Field(discriminator="action"),
]


class StoredConfigEdit(BaseModel):
    """A persisted pending-edit envelope — the store's read shape (E-03).

    Wraps one typed :class:`ConfigEdit` with its lifecycle: an ``edit_id`` (the
    ticket handle the route returns), a ``status`` (``pending``/``applied``/
    ``discarded``), the injected ``created_at`` (deterministic, K10) and the
    nullable ``applied_at`` stamped when :meth:`Store.mark_config_edits` flips it.
    Frozen + ``extra="forbid"`` (K8). ``config_edits_for`` returns these in
    insertion order (K10).
    """

    model_config = _EDIT_CONFIG

    edit_id: str
    status: str
    created_at: str
    applied_at: str | None = None
    edit: ConfigEdit
