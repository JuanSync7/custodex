# Slice TDOC-03 — Feature catalog + 1:1 traceability + wikis

EPIC TDOC. Registers the test→test-doc mirror as a golden feature
(`FEAT-CONFIGV2-017`), wires its 1:1 evidence (a demo case + a test), and
regenerates the EPIC-R wikis so `cdmon trace --fail-on-gap` and `cdmon wiki
--check` stay green.

## Why
Every cdmon feature must trace 1:1 to a demo AND a test (`cdmon trace`). The new
mirror feature needs a catalog entry plus evidence on both sides, and the wikis
(FEATURES.md, TEST_WIKI.md, TRACEABILITY.md) regenerated from those single sources.

## Goal (validable)
1. **Catalog.** `feature-doc/catalog/configv2.yaml` gains `FEAT-CONFIGV2-017`
   (test→test-doc mirror), modules naming real engine modules.
2. **Demo evidence.** `demo/DEMOS.md` DEMO-058 tags `Features: FEAT-CONFIGV2-017`
   (added in TDOC-02).
3. **Test evidence.** `tests/system/test_testdoc_mirror.py` module docstring tags
   `Features: FEAT-CONFIGV2-017`.
4. **Trace 1:1.** `cdmon trace --fail-on-gap` reports COMPLETE 199/199 (was 198):
   no feature missing a test/demo, no unknown refs.
5. **Wikis fresh.** `cdmon wiki` regenerates; `cdmon wiki --check` is clean.

## Design
- Add the feature entry (mirrors FEAT-CONFIGV2-016's shape; `modules:` are real
  modules the mirror exercises — `config`, `extract`, `heal`).
- Tag the test module docstring; DEMO-058 already carries the demo tag.
- `cdmon wiki` (regenerate all four wiki targets from their single sources).

## Test plan
- `cdmon trace --fail-on-gap` → COMPLETE 199/199.
- `tests/integration/test_demo_traceability.py` (every feature has a demo) and the
  test-evidence checks stay green.
- `cdmon wiki --check` clean; full offline pytest green.

## Out of scope
The frontend sections (TDOC-04, delivered); the engine (unchanged).

## Constraints
K0, K6 (catalog is additive), K8 (an unknown tagged id is a loud failure), K9,
K10 (byte-stable wiki regeneration). Tags are honest — the feature is exercised by
the tagged demo + test.
