# RTE-02b — class + pydantic fields enter the surface AND the rendered table

**Epic:** RTE  ·  **Depends on:** RTE-02a  ·  **Constraints:** K1, K2, K6, K9, K10

## Goal (validable)

Make the 1,039 annotated class fields that currently extract as **nothing** part of
the documented surface. For a pydantic-heavy codebase these ARE the configurable
API — `MonitorConfig.apply_default` is the single most important fact an adopter
needs, and today it appears in no document and in no coverage denominator.

**Done when:**
- `_variable_symbols` gains `*, qualifier: str = ""`; a `ClassDef`'s
  `Assign`/`AnnAssign` children become `Class.field` symbols of kind `variable`,
  with the bare `field: type = default` signature. A private field stays private —
  though note `_is_public` already strips a dotted qualifier, so passing the bare
  name is a style choice, not the correctness guard an earlier draft claimed.
- Fields reach the rendered symbol table, not only the surface — pinned by a test,
  because decoupling them would INFLATE coverage (see the ⟨R⟩ in ARCHITECTURE:
  `documented` means "selected by a config glob", so a surface-only field counts
  as documented while appearing nowhere).
- Module-level variables keep their unqualified names (regression guard).
- All FOUR monitored configs rehealed (`config/cdmon`, `demo/config/cdmon`, both
  `examples/`), full gate green, trace + wikis + index fresh.

## Scope discipline (NOT in this slice)

Module docstring as a symbol, and promoting `property` into `SymbolKind` with its
`_symbols_for_ref` selector — RTE-02c. One attributable cause per reheal.
