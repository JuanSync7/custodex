# CIX-01 — the persisted code index (`codeindex.py` + `cdx codeindex`)

**Epic:** CIX (the persisted code index, cross-references, and impact)
**Depends on:** — (first slice of the epic; extract/inventory/coverage as merged on `main`)
**Constraints:** K0, K1, K6, K7, K8, K9, K10

## Goal (validable)

Persist the extracted code surface as a versioned, diffable artifact
(`.cdmon/code-index.json`): every file in the coverage universe with a
content digest, every symbol with its span and per-tier digests
(signature/docstring/body), stamped with injected provenance
(`generated_by`, `source_sha`) that never enters a digest or a comparison.
This is the artifact everything later in the epic diffs against.

**Done when:**
- `custodex/codeindex.py` matches the pinned `ARCHITECTURE §EPIC CIX → CIX-01`
  signatures: `IndexedSymbol`/`IndexedFile`/`CodeIndex` (frozen, extra=forbid),
  `build_code_index` (pure fold over `discover_files(include=cfg.coverage.include,
  exclude=cfg.coverage.exclude)` + `discover_symbols` — the exact `cdx coverage`
  universe), `read_code_index` (missing → None; corrupt → `SchemaError`, K8),
  `write_code_index` (content-compare skip, stamp-blind — K7),
  `diff_code_index` → `CodeIndexDiff`/`FileDelta` (sorted, K10).
- `cdx codeindex`: read-only summary by default; `--write` is the one mutating
  mode (echoes `wrote`/`unchanged`); `--check` exits 1 on a stale artifact
  (stamp-blind compare); `--json`; `--ref` else `$CI_COMMIT_SHA` else None.
- No existing fingerprint moves: a regression test pins `surface_hash`/
  `fingerprint()` outputs on a fixture surface before/after this slice
  (golden literals captured from `main` FIRST — the P-01 lesson).
- Governance: `coverage.waive` entry for `custodex/codeindex.py`;
  `feature-doc/catalog/codeindex.yaml` (FEAT-CODEINDEX-001, modules
  `[codeindex, cli]`); DEMO-113 in `demo/DEMOS.md`; `Features:`-tagged tests;
  `cdx wiki` regenerated; cli-doc reheal (`cdx monitor --apply`).
- Full gate green: ruff format/check, mypy, pytest ≥90% branch;
  `cdx check` / `index --check` / `wiki --check` / `trace --fail-on-gap` green.

## Design

See `ARCHITECTURE §EPIC CIX` ⟨R⟩1 (projection, never truth) and ⟨R⟩2 (stamps
are provenance, never identity). The writer is the module's ONE impure
function, called only by `cdx codeindex --write` — never by check (K1).

## Non-goals (later slices)

- SCIP decode / xrefs (CIX-02); impact join (CIX-03); incremental check
  (CIX-04, deferred with rationale pinned in ARCHITECTURE).
- Shell/tcl symbol coverage beyond what `discover_symbols` extracts today
  (python-only symbol extraction; other languages index as symbol-less files
  with content digests — honest, additive later).

## Test plan (TDD)

- **unit** `tests/unit/test_codeindex.py`: model determinism (two builds over
  the same tree are `==` and dump byte-identically); digests match the
  extract.py conventions (`sig_digest` == the DIG-01 `cdm.symbol_sigs` value);
  read/write roundtrip; corrupt artifact → `SchemaError` with line context;
  write idempotency incl. the stamp-blind case (same files, new `source_sha`
  → no write, old stamp survives); `diff_code_index` buckets
  (added/removed/signature/docstring/body) each exercised; empty diff on
  identical indexes; no absolute path anywhere in the dump.
- **regression** `tests/regression/test_fingerprint_stability_codeindex.py`:
  golden `cdm.fingerprint`/`fingerprint_tiers`/`symbol_sigs` literals captured
  on `main` still produced after the slice (guards the K6 hash contract).
- **system** `tests/system/test_codeindex_cli.py` (CliRunner): summary default
  writes nothing; `--write` then `--write` → `wrote` then `unchanged`;
  `--check` clean → exit 0, after a source edit → exit 1; `--json` shape;
  missing config → clean K8 error line.

## Reheal order (DoD)

`(waiver) → cdx monitor --apply → cdx check → cdx wiki → cdx trace →
ruff/mypy/pytest`. Wiki LAST of the generators.
