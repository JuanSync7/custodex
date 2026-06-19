# Slice OWN-01 — config ownership fields + `ownership.resolve_ownership`

Add the per-repo ownership-of-record (config = truth) and the pure resolver.

## Goal (validable)
1. `DocumentSpec` accepts optional `owner`/`team`/`dri` (str|None, default None);
   a config without them still loads (back-compat); a typo'd key still raises a
   loud `ConfigError` (extra='forbid' intact, K8).
2. `dump_unit_file(load_unit_file(text))` is **byte-identical** for a unit whose
   docs carry owner/team/dri (idempotent round-trip, K7) — fields emitted by
   `_document_to_yaml` after `nav_label`, before `region_keys`, defaults dropped.
3. New `code_doc_monitor/ownership.py`: `Identity`, `RosterSnapshot`,
   `EffectiveOwner`, and `resolve_ownership(config, *, unit_owner=None)` returns
   one `EffectiveOwner` per document, sorted by `doc_id` (K10), with
   `accountable = dri or owner or team or unit_owner[doc_id]` and
   `durable = team or owner`.

## Design
- `config.py`: add the three fields to `DocumentSpec` (after `nav_label`); extend
  `_document_to_yaml` to emit them (only when not None, in field order). No
  validator needed (free strings). Server mirror `ConfigDocument` gains the same
  three optional fields here too (so OWN-04 can persist them) — additive.
- `ownership.py` (NEW, top-level module → auto-registers in `_known_modules`):
  frozen pydantic, `extra='forbid'`, `__all__`, sorted/deterministic, no clock.
  `resolve_ownership` reads `config.documents`; `unit_owner` maps `doc_id` → the
  unit frontmatter owner (caller builds it from the bundle; None ⇒ no fallback).

## Test plan (TDD red-first)
- `tests/integration/test_config.py`: owner/team/dri load + round-trip idempotency
  + unknown-key still raises (extend existing forbid test).
- `tests/unit/test_ownership.py` (NEW): `resolve_ownership` — doc-level wins;
  fallback to `unit_owner`; `accountable`/`durable` precedence; empty config ⇒ ();
  sorted by doc_id. `Identity`/`RosterSnapshot.is_active` (None/unknown ⇒ False).

## Dogfood
`config.py` is tracked → its surface drifts `docs/api/*`. After green:
`cdmon monitor --apply --config config/cdmon` then `cdmon check` exit 0. New
`ownership.py` is NOT yet tracked (added to coverage waiver like other new modules,
or covered by a doc later). Add **FEAT-OWNERSHIP-001** (config fields) +
**FEAT-OWNERSHIP-002** (`resolve_ownership`) to `feature-doc/catalog/ownership.yaml`
(NEW), a `demo/DEMOS.md` case + tagged tests; run `cdmon wiki` so FEATURES.md /
TRACEABILITY.md update; `cdmon trace --fail-on-gap` exit 0.

## Constraints
K0 (no new dep), K1/K10 (resolver pure, sorted), K6 (additive fields), K7 (round-trip
idempotent), K8 (forbid intact), K9 (TDD, ≥90%).
