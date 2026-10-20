# RTE-02c — an empty coverage universe must not pass a `--fail-under` gate

**Epic:** RTE  ·  **Depends on:** RTE-02b  ·  **Constraints:** K1, K6, K8, K9, K10

## Goal (validable)

Close a silent hole in the completeness metric the whole epic rests on:
`cdx coverage --fail-under 95` currently PASSES when the universe is empty, because
`percent_public_symbols` returns `100.0` for zero symbols. A mis-scoped include
glob therefore reports perfect coverage of nothing and exits 0.

**Done when:**
- `CoverageReport.public_universe` exposes the symbols the percentage is computed
  over, so a caller can distinguish "100% of many" from "100% of nothing".
- `cdx coverage --fail-under N` raises a typed, LOUD error on an empty universe
  (K8) rather than exiting 0; without `--fail-under` the command still reports
  100.0 unchanged (K9 — no behaviour change for the reporting path).
- `percent_public_symbols` arithmetic is UNCHANGED (⟨R⟩ in ARCHITECTURE: vacuous
  truth is right for a property, wrong for a gate; other callers want a number).
- Tests pin: empty universe + `--fail-under` → loud non-zero; empty universe
  WITHOUT `--fail-under` → still 100.0 and exit 0; a non-empty universe below the
  threshold still fails the ordinary way; a non-empty universe above it passes.
- Full gate green; all four configs still clean.
