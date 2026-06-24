# Slice OWN-05 — `ReassignOwnerEdit` (reassignment, config = truth)

The human-in-the-loop fix for an orphan: reassign a document's owner/team/dri,
rewritten to disk through the existing EDITOR generate-to-disk pipeline.

## Goal (validable)
1. A new `ConfigEdit` variant `ReassignOwnerEdit(action="reassign_owner", unit,
   doc_id, owner?, team?, dri?)` stages + persists like the other 5 edit types.
2. `config.set_document_owner(unit, doc_id, *, owner, team, dri) -> UnitFile`
   returns a NEW frozen `UnitFile` with that doc's ownership updated (None args
   leave the existing value; a sentinel/explicit clear is out of scope v1 —
   passing a value sets it).
3. `apply_edits_to_disk([ReassignOwnerEdit(...)])` rewrites
   `config/cdmon/<unit>.yaml` with the new owner (byte-stable, idempotent) and the
   `run_sync` re-mirror carries it into `ConfigDocument`.
4. Reassigning the orphan from OWN-04's cascade to an ACTIVE owner clears the
   orphan on the next `GET /ownership`.

## Design
- `server/edits.py`: define `ReassignOwnerEdit`, add to the `ConfigEdit` union +
  `__all__`.
- `config.py`: `set_document_owner` (pure editor, `model_copy` pattern — mirrors
  `upsert_document`/`add_code_ref`).
- `generate.py`: import + an `isinstance(edit, ReassignOwnerEdit)` branch in
  `_apply_unit_edit`. Route + store already generic (no change).

## Test plan (TDD red-first)
- `tests/unit/test_config.py`: `set_document_owner` sets each field; returns a new
  frozen model; unknown doc_id ⇒ loud.
- `tests/integration/test_generate.py`: a `reassign_owner` edit rewrites the unit
  yaml + the doc's owner round-trips; idempotent re-apply.
- `tests/integration/test_config_edits_routes.py`: add to the all-actions payload
  list (stage + list + generate).

## Dogfood
`config.py`, `generate.py`, `server/edits.py` tracked → reheal `docs/api/*`. Add
**FEAT-OWNERSHIP-008** (reassignment edit) to the catalog + DEMOS case + tagged
test; `cdx wiki`; `cdx trace --fail-on-gap` exit 0.

## Constraints
K5 (reassignment = the human fix; config = truth), K6 (additive edit type),
K7 (idempotent disk rewrite), K8 (loud on unknown doc/unit), K9, K10.
