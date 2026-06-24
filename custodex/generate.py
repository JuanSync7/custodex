"""The "Generate / make live" engine — staged edits → live on-disk config + docs.

EDITOR E-06, the INTEGRATION slice. :func:`apply_edits_to_disk` turns a list of
typed :class:`~custodex.server.edits.ConfigEdit` tickets into a real,
git-tracked change of a repo's working tree:

1. apply the edits to the on-disk ``config/cdmon/*.yaml`` unit files (and the
   ``doc-style.yaml`` map) via the EXISTING pure model editors
   (:func:`~custodex.config.upsert_document` /
   :func:`~custodex.config.add_code_ref` / … ) +
   :func:`~custodex.config.dump_unit_file`;
2. ``regenerate_index`` + ``write_index`` so the index lists every unit + a
   refreshed ``updated``;
3. materialize/heal each affected document — mechanically, NO LLM (the LLM path
   is E-07): scaffold a missing doc and ``regenerate_regions`` so its managed
   regions match the current code surface, preserving human-owned regions.

This is the engine the central server's ``POST /config/generate`` route calls; it
lives HERE (a core module, not the server) so it is unit-testable WITHOUT fastapi
and dogfood-coverable. It is OFFLINE + deterministic (K10) and IDEMPOTENT (K7):
running the same edits twice yields byte-identical on-disk bytes (the second run
is a no-op heal). The WRITE surface is SCOPED (K1 relaxation, EDITOR §0): only
``config/cdmon/*.yaml`` and the declared document ``.md`` files are ever written —
never an arbitrary path. Every failure is a loud, typed
:class:`~custodex.errors.CodeDocMonitorError` (K8); the clock is injected
via ``now`` (no wall-clock read).
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .config import (
    CodeRef,
    ContextRef,
    DocumentSpec,
    RegionMode,
    UnitFile,
    add_code_ref,
    dump_unit_file,
    load_bundle,
    load_unit_file,
    regenerate_index,
    remove_code_ref,
    resolve_repo_root,
    set_context_refs,
    set_document_owner,
    upsert_document,
    write_index,
)
from .docstyle import (
    STYLE_CATEGORIES,
    DocStyleMapping,
    DocStyleSelection,
    dump_doc_style,
    load_doc_style,
)
from .errors import CodeDocMonitorError
from .extract import build_document_surface
from .heal import apply_fix, regenerate_regions
from .layout import scaffold_doc
from .schema import Audience, ReviewRecord, Verdict
from .server.edits import (
    AddCodeRefEdit,
    ConfigEdit,
    CreateDocEdit,
    EditCodeRef,
    EditContextRef,
    EditDocStyle,
    ReassignOwnerEdit,
    RemoveCodeRefEdit,
    SetContextRefsEdit,
    SetDocStyleEdit,
)

__all__ = [
    "ApplyFixResult",
    "GenerateResult",
    "apply_edits_to_disk",
    "apply_record_fix",
]

# The verdicts whose record carries an applicable fix (EDITOR E-07). Only a FIX
# verdict proposes a remediation to apply; INVALIDATE/ESCALATE carry no fix.
_FIX_VERDICTS = frozenset({Verdict.FIX})

# Where a repo's dir-layout config lives, relative to the repo root (mirrors
# configsync._CONFIG_SUBDIR).
_CONFIG_SUBDIR = ("config", "cdmon")

# The index frontmatter ``updated:`` line (mirrors config._UPDATED_LINE_RE).
# ``regenerate_index`` stamps this with the WALL clock; generate re-stamps it with
# the injected ``now`` so the index is deterministic (K10) and a second identical
# run is byte-identical (K7).
_INDEX_UPDATED_RE = re.compile(r"^updated:[^\n]*$", re.MULTILINE)


def _stamp_index_updated(text: str, now: str) -> str:
    """Replace the index frontmatter ``updated:`` line with the injected ``now``.

    Scoped to the FRONTMATTER block (the text before the second ``---`` fence) so a
    body line that merely starts ``updated:`` is never touched. Idempotent (K7).
    """
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return text
    fm, body = parts
    new_fm = _INDEX_UPDATED_RE.sub(f'updated: "{now}"', fm, count=1)
    return new_fm + "\n---\n" + body


class GenerateResult(BaseModel):
    """The outcome of one :func:`apply_edits_to_disk` — what the route reports.

    Frozen + ``extra="forbid"`` (K8). ``applied_edit_ids`` is empty here (the
    engine operates on edit PAYLOADS, not the stored envelopes — the route owns
    the id↔payload mapping and marks them applied); it is carried for the route to
    fill. ``affected_units`` / ``affected_docs`` are the on-disk artifacts the run
    touched (repo-relative, sorted, deterministic K10). ``wrote_doc_style`` flags
    whether ``doc-style.yaml`` was rewritten. ``index_changed`` mirrors whether the
    index text moved.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    applied_edit_ids: tuple[str, ...] = ()
    affected_units: tuple[str, ...] = ()
    affected_docs: tuple[str, ...] = ()
    wrote_doc_style: bool = False
    index_changed: bool = False


class ApplyFixResult(BaseModel):
    """The outcome of one :func:`apply_record_fix` — what the apply-fix route reports.

    Frozen + ``extra="forbid"`` (K8). ``applied`` is ``True`` only when the doc
    file changed; an already-applied fix is a no-op (``applied=False`` + empty
    ``diff``, K7). ``doc_path`` is the repo-relative document path the fix targeted;
    ``diff`` is a stdlib :func:`difflib.unified_diff` of the doc text before→after
    (empty string when unchanged), so a human (or the UI) can see exactly what the
    LLM's fix changed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    applied: bool
    doc_path: str
    diff: str


def apply_record_fix(
    local_path: Path, record: ReviewRecord, *, now: str
) -> ApplyFixResult:
    """Apply a review record's proposed fix to its doc on disk (EDITOR E-07).

    The offline, deterministic (K10), SCOPED counterpart of ``cdx monitor
    --apply`` for ONE already-recorded drift: it writes ONLY the record's own
    document ``.md`` file (never an arbitrary path, EDITOR §0) and never touches
    code or other config. Steps, in order:

    1. loud K8 :class:`~custodex.errors.CodeDocMonitorError` if the record
       carries no applicable fix — ``record.fix is None`` or its ``verdict`` is not
       a FIX-shaped verdict (only an applicable fix can be applied);
    2. resolve ``config/cdmon`` under ``local_path``, :func:`load_bundle`, and
       :func:`resolve_repo_root` → the repo root; the doc path is ``repo_root /
       record.doc_path`` (loud K8 if the doc file is missing);
    3. find the matching :class:`DocumentSpec` (by ``doc_id``) to derive the
       human-owned ``preserve`` set + per-region ``modes`` EXACTLY as
       :meth:`custodex.monitor.Monitor.run` does for ``--apply`` (B-02/B-03
       — human regions are never authored; the guarantee is enforced at the heal
       write boundary);
    4. read the doc text BEFORE, call :func:`~custodex.heal.apply_fix`
       (the EXISTING healer), read AFTER;
    5. return an :class:`ApplyFixResult` whose ``diff`` is a unified diff of
       before→after (empty when unchanged). IDEMPOTENT (K7): re-applying an
       already-applied fix is a no-op (``applied=False``, empty ``diff``).

    The ``now`` clock is accepted for signature parity with the other engine
    entry points and a deterministic call surface; the underlying region heal is
    already clock-free (it stamps content hashes, not timestamps).
    """
    if record.fix is None or record.verdict not in _FIX_VERDICTS:
        raise CodeDocMonitorError(
            f"record {record.record_id!r} has no applicable fix "
            f"(verdict={record.verdict.value}, fix={'set' if record.fix else 'none'}); "
            "only a FIX-verdict record carrying a proposed fix can be applied"
        )

    config_dir = local_path.joinpath(*_CONFIG_SUBDIR)
    index_path = config_dir / "index.yaml"
    if not index_path.is_file():
        raise CodeDocMonitorError(
            f"cannot apply fix: no config/cdmon/index.yaml under {local_path} "
            "(is this a cdx repo with a dir-layout config?)"
        )
    bundle = load_bundle(config_dir)
    repo_root = resolve_repo_root(config_dir, bundle.index.root)

    spec = next((d for d in bundle.config.documents if d.id == record.doc_id), None)
    if spec is None:
        raise CodeDocMonitorError(
            f"cannot apply fix: no document {record.doc_id!r} in the config "
            f"under {config_dir}"
        )

    doc_path = repo_root / record.doc_path
    if not doc_path.is_file():
        raise CodeDocMonitorError(
            f"cannot apply fix: document file {doc_path} does not exist"
        )

    # Mirror Monitor.run's --apply preserve/modes derivation EXACTLY (B-02/B-03):
    # human-owned regions are never authored by the engine, and the full
    # region_modes map lets apply_fix derive the B-03 lock + per-region hash
    # stamping at the write boundary.
    preserve = frozenset(
        rid for rid in spec.region_keys if spec.mode_for(rid) is RegionMode.HUMAN
    )
    modes = {rid: spec.mode_for(rid) for rid in spec.region_keys}

    before = doc_path.read_text(encoding="utf-8")
    apply_fix(doc_path, record.fix, preserve=preserve, modes=modes)
    after = doc_path.read_text(encoding="utf-8")

    diff = ""
    if after != before:
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{record.doc_path}",
                tofile=f"b/{record.doc_path}",
            )
        )

    return ApplyFixResult(applied=after != before, doc_path=record.doc_path, diff=diff)


def _coerce_audience(value: str) -> Audience:
    """Parse an edit's free-string ``audience`` into the typed enum (loud K8)."""
    try:
        return Audience(value)
    except ValueError as exc:
        valid = ", ".join(a.value for a in Audience)
        raise CodeDocMonitorError(
            f"invalid audience {value!r}; expected one of: {valid}"
        ) from exc


def _code_ref_from_edit(ref: EditCodeRef) -> CodeRef:
    """Build an on-disk :class:`CodeRef` from an edit payload (whole-file/symbol/line).

    Maps the editor's minimal shape onto a code_ref: ``symbols`` select named
    surface (empty = whole file), and a ``"start-end"`` ``lines`` string parses to
    one 1-based inclusive range. A malformed ``lines`` is a loud K8 error.
    """
    lines: tuple[tuple[int, int], ...] = ()
    if ref.lines is not None:
        text = ref.lines.strip()
        try:
            start_s, end_s = text.split("-", 1)
            lines = ((int(start_s), int(end_s)),)
        except ValueError as exc:
            raise CodeDocMonitorError(
                f"invalid code_ref lines {ref.lines!r}: expected 'start-end' "
                "(1-based inclusive)"
            ) from exc
    return CodeRef(path=ref.path, symbols=tuple(ref.symbols), lines=lines)


def _context_refs_from_edit(
    refs: tuple[EditContextRef, ...],
) -> tuple[ContextRef, ...]:
    """Build the on-disk :class:`ContextRef` tuple from edit payloads.

    K6 generation context ("glance-through"), never coverage.
    """
    return tuple(ContextRef(path=r.path, note=r.note) for r in refs)


def _selection_with_overrides(
    base: DocStyleSelection, override: EditDocStyle
) -> DocStyleSelection:
    """Return ``base`` with each non-``None`` :class:`EditDocStyle` field replaced.

    An edit may set only the categories the author changed; the rest resolve from
    the document's existing selection (or the map ``defaults``). Built through the
    hyphenated aliases so it is sound regardless of the pydantic plugin (Z-03).
    """
    values: dict[str, str] = {}
    for attr, subdir in STYLE_CATEGORIES:
        chosen = getattr(override, attr)
        values[subdir] = chosen if chosen is not None else getattr(base, attr)
    return DocStyleSelection.model_validate(values)


def _apply_doc_style(
    config_dir: Path,
    repo_root: Path,
    doc_id: str,
    override: EditDocStyle,
    *,
    doc_style_pointer: str,
    now: str,
) -> None:
    """Add or replace ``doc_id``'s mapping in ``doc-style.yaml`` (EDITOR E-06).

    Loads the existing map (validating its templates exist), resolves the new
    selection (existing/defaults overlaid with the edit's set fields), upserts the
    per-doc mapping, and rewrites the file via :func:`dump_doc_style`. SCOPED write:
    only ``config/cdmon/<doc-style pointer>`` is touched. Loud K8 if no doc-style
    file exists (an edit cannot create the map from nothing here).
    """
    path = config_dir / doc_style_pointer
    if not path.is_file():
        raise CodeDocMonitorError(
            f"cannot set doc-style for {doc_id!r}: no doc-style file at {path}"
        )
    templates_root = repo_root / "templates" / "writing"
    current = load_doc_style(path, templates_root=templates_root)
    base = current.style_for(doc_id)
    selection = _selection_with_overrides(base, override)
    new_mapping = DocStyleMapping.model_validate(
        {
            "doc": doc_id,
            "document-type": selection.document_type,
            "tone": selection.tone,
            "writing-style": selection.writing_style,
            "vocabulary": selection.vocabulary,
        }
    )
    mappings = list(current.mappings)
    for i, m in enumerate(mappings):
        if m.doc == doc_id:
            mappings[i] = new_mapping
            break
    else:
        mappings.append(new_mapping)
    updated = current.model_copy(update={"mappings": tuple(mappings)})
    text = dump_doc_style(updated, now=now)
    path.write_text(text, encoding="utf-8")


def apply_edits_to_disk(
    local_path: Path,
    edits: list[ConfigEdit],
    *,
    now: str,
    backend: object | None = None,
) -> GenerateResult:
    """Apply staged config edits to ``local_path`` and make them live (EDITOR E-06).

    Deterministic + offline (K10): NO LLM (E-07 owns that). Steps, in order:

    1. resolve ``config/cdmon`` under ``local_path`` (loud K8 if absent);
    2. group the edits by target unit, apply each via the EXISTING pure model
       editors, and rewrite the unit yaml with :func:`dump_unit_file`;
       ``set_doc_style`` edits rewrite ``doc-style.yaml``;
    3. ``regenerate_index`` + ``write_index`` so the index lists every unit;
    4. reload the bundle and, for each affected document, scaffold a missing doc
       then ``regenerate_regions`` to bring its managed regions in sync — preserving
       human-owned regions (mirroring how ``cdx monitor``/``new-doc`` derive
       ``preserve``/``modes``).

    SCOPED writes ONLY (EDITOR §0): ``config/cdmon/*.yaml`` + the declared doc
    ``.md`` files. IDEMPOTENT (K7): a second identical run is a byte-identical
    no-op heal. ``backend`` is accepted (unused) to keep the signature stable for
    the E-07 LLM path. Every failure is a loud, typed
    :class:`~custodex.errors.CodeDocMonitorError` (K8).
    """
    config_dir = local_path.joinpath(*_CONFIG_SUBDIR)
    index_path = config_dir / "index.yaml"
    if not index_path.is_file():
        raise CodeDocMonitorError(
            f"cannot generate: no config/cdmon/index.yaml under {local_path} "
            "(is this a cdx repo with a dir-layout config?)"
        )

    # Resolve the repo root + the doc-style pointer up front (one load, K10).
    bundle = load_bundle(config_dir)
    repo_root = resolve_repo_root(config_dir, bundle.index.root)
    doc_style_pointer = bundle.index.doc_style

    # ---- 1/2. Group the unit-targeted edits and apply them per unit. ---------
    by_unit: dict[str, list[ConfigEdit]] = {}
    doc_style_edits: list[SetDocStyleEdit] = []
    affected_doc_ids: set[str] = set()
    for edit in edits:
        if isinstance(edit, SetDocStyleEdit):
            doc_style_edits.append(edit)
            affected_doc_ids.add(edit.doc_id)
            continue
        by_unit.setdefault(edit.unit, []).append(edit)
        affected_doc_ids.add(edit.doc_id)

    affected_units: list[str] = []
    for unit_name, unit_edits in by_unit.items():
        unit_path = config_dir / f"{unit_name}.yaml"
        if not unit_path.is_file():
            raise CodeDocMonitorError(
                f"cannot apply edits: unit file {unit_path} does not exist"
            )
        unit = load_unit_file(unit_path)
        for edit in unit_edits:
            unit = _apply_unit_edit(unit, edit)
        text = dump_unit_file(unit, now=now)
        unit_path.write_text(text, encoding="utf-8")
        affected_units.append(unit_name)

    # ---- set_doc_style edits rewrite doc-style.yaml. -------------------------
    wrote_doc_style = False
    for ds_edit in doc_style_edits:
        _apply_doc_style(
            config_dir,
            repo_root,
            ds_edit.doc_id,
            ds_edit.doc_style,
            doc_style_pointer=doc_style_pointer,
            now=now,
        )
        wrote_doc_style = True

    # ---- 3. Regenerate the index so it lists every unit + refreshes updated. -
    new_index = _stamp_index_updated(regenerate_index(config_dir), now)
    index_changed = new_index != index_path.read_text(encoding="utf-8")
    write_index(config_dir, new_index)

    # ---- 4. Materialize/heal each affected document (mechanical, no LLM). ----
    fresh = load_bundle(config_dir)
    fresh_root = resolve_repo_root(config_dir, fresh.index.root)
    affected_docs: list[str] = []
    for doc_id in sorted(affected_doc_ids):
        spec = next((d for d in fresh.config.documents if d.id == doc_id), None)
        if spec is None:
            # A set_doc_style edit may target a doc that no unit declares; nothing
            # on disk to heal for it (the style map change still landed).
            continue
        doc_path = fresh_root / spec.path
        surface = build_document_surface(spec, fresh_root)
        if not doc_path.exists():
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(
                scaffold_doc(
                    spec, surface, include_body=fresh.config.fingerprint_body_tier
                ),
                encoding="utf-8",
            )
        # Human-owned regions are never authored by the engine (B-02); the
        # guarantee is enforced at the heal write boundary. Mirrors the
        # monitor/new-doc preserve/modes derivation.
        preserve = frozenset(
            rid for rid in spec.region_keys if spec.mode_for(rid) is RegionMode.HUMAN
        )
        modes = {rid: spec.mode_for(rid) for rid in spec.region_keys}
        regenerate_regions(
            doc_path,
            surface,
            fresh.config.region_templates,
            preserve,
            modes,
            include_body=fresh.config.fingerprint_body_tier,
        )
        affected_docs.append(spec.path)

    return GenerateResult(
        affected_units=tuple(sorted(affected_units)),
        affected_docs=tuple(sorted(affected_docs)),
        wrote_doc_style=wrote_doc_style,
        index_changed=index_changed,
    )


def _apply_unit_edit(unit: UnitFile, edit: ConfigEdit) -> UnitFile:
    """Apply one unit-targeted edit to a :class:`UnitFile` via the model editors.

    Routes on the discriminated-union action to the matching EXISTING pure editor
    (:func:`upsert_document` / :func:`add_code_ref` / :func:`remove_code_ref` /
    :func:`set_context_refs`); returns a NEW frozen unit (no mutation). A
    :class:`SetDocStyleEdit` never reaches here (it has no ``unit`` and is handled
    against ``doc-style.yaml``).
    """
    if isinstance(edit, CreateDocEdit):
        doc = DocumentSpec(
            id=edit.doc_id,
            path=edit.path,
            audience=_coerce_audience(edit.audience),
            code_refs=tuple(_code_ref_from_edit(r) for r in edit.code_refs),
            context_refs=_context_refs_from_edit(edit.context_refs),
        )
        return upsert_document(unit, doc)
    if isinstance(edit, AddCodeRefEdit):
        ref = _code_ref_from_edit(edit.ref)
        # IDEMPOTENT (K7): adding a code_ref already present (same path/symbols/
        # lines) is a no-op, so a second identical generate run yields byte-identical
        # yaml rather than a duplicated entry. The pure ``add_code_ref`` editor
        # always appends; the de-dup belongs to the generate engine, where "make
        # live the staged edit" must converge.
        existing_doc = next((d for d in unit.documents if d.id == edit.doc_id), None)
        if existing_doc is not None and any(
            existing == ref for existing in existing_doc.code_refs
        ):
            return unit
        return add_code_ref(unit, edit.doc_id, ref)
    if isinstance(edit, RemoveCodeRefEdit):
        return remove_code_ref(unit, edit.doc_id, edit.path)
    if isinstance(edit, SetContextRefsEdit):
        return set_context_refs(
            unit, edit.doc_id, _context_refs_from_edit(edit.context_refs)
        )
    if isinstance(edit, ReassignOwnerEdit):
        return set_document_owner(
            unit, edit.doc_id, owner=edit.owner, team=edit.team, dri=edit.dri
        )
    raise CodeDocMonitorError(
        f"unexpected unit edit action {getattr(edit, 'action', '?')!r}"
    )
