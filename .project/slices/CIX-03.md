# CIX-03 — `cdx impact`: the diff→docs surgical join

**Epic:** CIX (the persisted code index, cross-references, and impact)
**Depends on:** CIX-01 (stored index + diff); CIX-02 optional at runtime
(callers enrichment when `.cdmon/xrefs.json` exists)
**Constraints:** K0, K1, K8, K9, K10

## Goal (validable)

Answer "I changed the tree — which docs are affected, and through which
symbols?" WITHOUT a full check: diff the stored code index against the
current tree, join changed symbols to covering docs (the `docmap.symbol_owners`
coverage join), and — when xrefs exist — extend the blast radius through
callers of the changed symbols. Read-only, always (K1).

**Done when:**
- `codeindex.impact_report(config, root, stored, current, xrefs)` matches the
  pinned signature: `ImpactReport{deltas, docs: tuple[DocImpact{doc_id,
  direct, via_callers}], callers_available}`; pure, sorted (K10); private
  symbols may appear in deltas but doc joins run over the public entity
  universe (the docmap contract).
- `cdx impact`: no stored index → one loud K8 error line naming the fix
  (`run cdx codeindex --write first`), exit 1; otherwise builds the current
  index in memory (writes NOTHING), prints per-doc impact grouped
  direct-then-callers, `--json` round-trippable; exit 0 always when the
  join runs (informational, `report` precedent).
- Governance: FEAT-CODEINDEX-002 appended to `feature-doc/catalog/
  codeindex.yaml`; DEMO-115; tagged tests; wiki regen.
- Full gate green (as CIX-01).

## Design

The join is deliberately docmap's, not a re-implementation: changed symbol →
entity id → `symbol_owners` doc set. `via_callers` = xref edges whose TARGET
changed → source symbol → its covering docs (one hop — transitive closure is
advisory-only territory, the `deps --transitive` precedent, deferred).

## Non-goals

- Multi-hop caller closure; gating flags; writing anything.
- Feeding impact into `monitor` verdicts (a later epic — this slice is the
  read-only projection).

## Test plan (TDD)

- **unit** `tests/unit/test_impact.py`: synthetic config + two indexes —
  signature change → direct doc hit; docstring-only change → delta present,
  eng-guide doc hit via digest bucket; xrefs present → via_callers populated,
  absent → `callers_available=False` and empty via_callers; removed file;
  determinism (two runs `==`).
- **system** `tests/system/test_impact_cli.py` (CliRunner): missing artifact
  → K8 line + exit 1; happy path over a tmp repo fixture; `--json` shape.

## Reheal order (DoD)

`cdx monitor --apply → cdx check → cdx wiki → cdx trace → ruff/mypy/pytest`.
