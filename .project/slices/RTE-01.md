# RTE-01 — classify + report the apply tier (change nothing)

**Epic:** RTE (the apply-tier router — "spend human attention only where the code
cannot answer the question")
**Depends on:** B-12 (`ChangeSeverity`) + DIG-01 (`sigs_changed`) — both merged
**Constraints:** K0, K1, K2, K3, K6, K9, K10, K11

## Goal (validable)

Make the routing decision **visible and auditable with zero behavioural risk**.
`detect` classifies every `Drift` with the authority that could close it —
`CODE_DERIVED` (an engine projection of the surface; no model consulted),
`DELEGATED` (model-authored into a region a human declared `mode: llm`), or
`NEEDS_INTENT` (closing it needs a WHY the code cannot supply) — and `cdx check`
reports the per-document routing tally. **Nothing is applied differently.** No
config flag, no `monitor.py` change, no schema bump, no backend call.

This slice is the executable proof of the epic's central claim: **a useful
confidence tier needs no model self-scoring.** It is independently valuable even if
RTE-02..05 never ship — it turns "which drifts could safely close themselves?" from
an argument into a number a human can read off `cdx check`.

**Done when:**
- `custodex/drift.py` gains `ApplyTier`, `classify_apply_tier`, and
  `auto_routable_docs` exactly as pinned in `ARCHITECTURE §EPIC RTE`. All three are
  PURE — no clock, no I/O, no backend, no network (K1/K10).
- `Drift` gains `apply_tier: ApplyTier = ApplyTier.NEEDS_INTENT` and
  `tier_evidence: tuple[str, ...] = ()`, appended LAST (the P2/P4/DIG-01/P5
  precedent). **The default is the DENY value** — a `Drift` built outside `detect`
  is never auto-applied, so a forgotten construction site fails safe.
- All SIX `detect` construction points set them (MISSING_DOC · HASH · REGION
  llm-prose · UNHEALABLE · REGION renderer-backed · SUSPECT_LINK).
- `DriftReport.summary()` gains ONE additive trailing routing line; every existing
  substring assertion still holds.
- The full 12-rule precedence truth table is pinned as a unit test (mirroring
  `test_drift.py::test_classify_change_severity_truth_table`), including the
  deny-by-default terminal and a defaults-only call.
- `auto_routable_docs` is proved PER-DOCUMENT: doc A `{HASH COSMETIC, REGION
  renderer-backed}` and doc B `{HASH COSMETIC, REGION authored-prose}` ⇒ `== {"A"}`.
- A doc carrying `{HASH COSMETIC, SUSPECT_LINK}` **is still auto-routable** (a
  suspect link must not veto its document).
- `classify_change_severity`'s pinned truth table is CONSUMED, never re-tuned (K9).
- `ruff format --check` · `ruff check` · `mypy custodex` · `pytest -q --cov=custodex
  --cov-branch` (≥90) all clean; `cdx check` / `index --check` / `wiki --check` /
  `trace --fail-on-gap` all green; **dogfood reheal committed** (`drift.py` is a
  tracked module — `config/cdmon/core.yaml`).

## Design

### Why provenance, not a score

K11 bans a bare float. More importantly a float is the wrong MODEL of the problem:
on the `CODE_DERIVED` path there is no model judgement to be confident *about* —
the bytes are the engine's own projection of the surface, produced by the same
functions `heal` calls. Confidence is a CLASSIFICATION over signals `detect`
already captures, not an ESTIMATION. See `ARCHITECTURE §EPIC RTE` for the full
decision table and the four ⟨R⟩ decisions (kind-rules-before-healable; LLM_SEEDED
denied wholesale because the classifier is not given the lock state; BREAKING
escalates while COSMETIC/ADDITIVE do not; no audience clause because K3 is already
enforced upstream in the fingerprint).

### The safety-critical part: per-DOCUMENT routing

One `NEEDS_INTENT` drift holds the WHOLE document. This is the correctness
condition, not a refinement — `heal._corrected` skips a no-renderer region but
still stamps the fingerprint, and that stamp is the ONLY staleness trigger such a
region has. Routing per-drift would let a doc's HASH fix bless its sibling prose
region into permanent staleness with `cdx check` green forever. Pinned by test.

### Scope discipline (what this slice deliberately does NOT do)

- No `apply_tiered` config knob — that is RTE-03.
- No `monitor.py` change; the apply gate is untouched, so day-one behaviour is
  byte-identical.
- No `ReviewRecord` field and no schema bump — RTE-03 carries 1.2.0 → 1.3.0.
- No extraction change — RTE-02 owns that, and it is a PREREQUISITE to ever
  recommending `apply_tiered: true`.
