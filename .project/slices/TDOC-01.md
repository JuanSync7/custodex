# Slice TDOC-01 — Test→test-doc mirror: config convention + dogfood proof

EPIC TDOC ("test docs"). Source code already syncs to documents under `docs/`
(via a unit's `code_refs`); this epic adds the **same mirror for tests**: test
files under `tests/**` sync to **test-docs** under a top-level `test-docs/`
directory, using the IDENTICAL machinery. TDOC-01 is the foundational slice: it
proves the existing engine needs **no change** (tests are just `.py` files — the
extractor/drift/heal/coverage are already generic), establishes the config
convention, and dogfoods it on cdmon's OWN `tests/smoke/` boundary.

## Why
The engine (`extract`/`drift`/`heal`/`coverage`/`inventory`) has zero
source-vs-test hard-coding, and `UnitFile`/`DocumentSpec`/`CodeRef` are
audience-agnostic. So "sync tests → test-docs" is a *config convention*, not new
code: a unit whose `code_refs` point at `tests/**` and whose docs live under
`test-docs/`. Dogfooding it on the small, stable `tests/smoke/` boundary makes it
real (and keeps the maintenance tax + coverage impact bounded).

## Goal (validable)
1. **Convention.** A new dogfood unit `config/cdmon/tests.yaml`
   (`dir-covered: [tests/smoke]`, `source-files-format: [".py"]`) declares one
   test-doc per smoke test file, each with a managed `symbols` region and
   `code_refs` pointing at the test file. Docs live under `test-docs/smoke/`.
2. **In sync.** After `cdmon new-doc` + reheal, `cdmon check` is clean and the
   test-doc's `symbols` region lists the file's test functions.
3. **Coverage stays green.** `cdmon coverage` (symbol floor 95%) and the dogfood
   self-coverage threshold test stay ≥ threshold (test functions are documented).
4. **Index in sync.** `cdmon index` lists `tests.yaml`; `index --check` is clean.
5. **Self-heal.** Inducing drift in a smoke test file (add/rename a `test_*`
   function) drifts its test-doc; `cdmon monitor --apply` heals it (idempotent).

## Design
- **No engine change.** Reuse `build_document_surface`, `drift.detect`,
  `heal.regenerate_regions`, `resolve_coverage` unchanged.
- **`config/cdmon/tests.yaml`** (new unit): `unit: tests`, `dir-covered:
  [tests/smoke]`, two `eng-guide` docs (`test-smoke-boundaries`,
  `test-smoke-smoke`) with `region_keys: [symbols]`.
- **`test-docs/smoke/*.md`** (new, generated): scaffolded via `cdmon new-doc`,
  human blockquote describing what the test module guards; region machine-filled.
- **`index.yaml`**: `cdmon index` adds `tests.yaml`; add a coverage waiver for
  `tests/smoke/__init__.py` IF it surfaces as a gap (empirically determined).
- **Copy-helper ripple.** Both `_copy_dogfood_tree` helpers (`test_dogfood.py`
  and `tests/regression/test_corpus_selfcoverage.py`) must also copy `test-docs/`
  and `tests/smoke/` so the self-heal-on-a-copy tests resolve the new code_refs.

## Test plan
- **system (`tests/system/test_testdoc_mirror.py`, new):** the `tests` unit loads;
  `test-smoke-boundaries` surface contains the boundary test functions;
  `Monitor(cfg).check().ok`; inducing drift on a copied smoke test then
  `monitor --apply` re-syncs (mirrors the source self-heal contract for tests).
- **dogfood (existing):** `test_dogfood_*` (check / lint / coverage / index)
  automatically validate the new unit + docs once rehealed.
- Full gate green (ruff/mypy/pytest); coverage ≥ floor; `cdmon trace`/`wiki`
  handled in TDOC-03.

## Out of scope
The demo 1:1 mirror (TDOC-02); the feature-catalog entry + trace + wiki (TDOC-03);
the frontend "Test docs" sections (TDOC-04). No new CLI command or engine code.

## Constraints
K0 (no engine knowledge of "test" vs "source"; the distinction is pure config +
path convention), K2 (the test file is the source of truth; the test-doc is graded
against it), K7 (idempotent reheal), K9 (test-first, gate green, no prior slice
broken), K10 (deterministic surfaces).
