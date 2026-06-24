# Regression corpus (H-03)

A curated, executable **index of the program's durable invariants** — one guard
per learned failure mode captured across EPIC-2 (`.project/LESSON_LEARNT.md` +
`.project/problems/*.md`). Each case names the lesson id it guards (`[B-02]`,
`[CDM-07]`, …) in its docstring, so a red points straight at the writeup that
explains *why* the invariant exists. A learned failure that has a corpus guard
**cannot silently come back**.

This is an INDEX, not a copy: where a lesson already had a guarding test the
corpus writes a thin re-assertion against the same engine seam; where a listed
invariant had no test, the corpus ADDS one (notably the
unlisted-engine-module-is-a-gap case).

## Running

- **Default suite** — the corpus is included automatically (it lives under
  `tests/`): `pytest`.
- **Corpus alone** — `pytest -m regression` (every case under
  `tests/regression/` is auto-tagged `regression` by `conftest.py`; the marker is
  registered in `pyproject.toml`).

## Case → lesson map

### `test_corpus_pipeline.py` — heal/drift pipeline invariants
| Case | Lesson | Invariant |
|------|--------|-----------|
| `test_audience_invalidation_docstring_only_drifts_eng_not_user` | **[CDM-07]** | a docstring/comment-only edit drifts eng, is a NON-event for user (extraction-level audience policy) |
| `test_audience_public_signature_drifts_both` | **[CDM-07]** | the audience filter is selective — a real surface move reaches both docs |
| `test_heal_is_idempotent_no_perpetual_region_drift` | **[CDM-03]** | regenerate → detect-clean → regenerate is False (no trailing newline ⇒ no perpetual REGION drift) |
| `test_human_region_never_auto_edited` | **[B-02]** | a `human` region survives `monitor --apply` byte-identical; fingerprint still refreshes (break-it documented) |
| `test_human_advisory_persists_until_human_edits` | **[B-03]** | the human advisory persists across a fingerprint heal and clears only when the body changes |
| `test_llm_seeded_fill_then_lock_three_phase` | **[B-03]** | FILL → LOCK → REPORT (the three-phase property; break-it documented) |
| `test_llm_seeded_unlocked_regenerates_on_code_move` | **[B-03]** | an UNLOCKED llm-seeded region still regenerates (the foil to the lock) |
| `test_both_drift_shapes_close_in_one_apply` | **[CDM-07]** | a realistic HASH+REGION change converges in one `--apply` (fixer ≡ checker) |
| `test_loop_safety_doc_only_commit_does_not_resync` | **[C-04]** | `should_sync` False for a doc-only commit; separator-normalized truth table (break-it documented) |
| `test_pure_llm_no_renderer_authored_reauthor_idempotent_human_untouched` | **[B-06]** | a `mode: llm` no-renderer region is AUTHORED prose end-to-end: a code move surfaces a healable REGION drift, `--apply` re-authors its prose from the current surface, a second `--apply` is a clean no-op, and an adjacent `human` region stays byte-identical (break-it documented) |

### `test_corpus_contracts.py` — schema / transport / learning contracts
| Case | Lesson | Invariant |
|------|--------|-----------|
| `test_pre_field_review_record_still_parses` | **[C-05]** | a pre-`source_sha` JSONL `ReviewRecord` still validates (additive back-compat; break-it documented) |
| `test_pre_field_resolution_record_still_parses` | **[D-01]** | a pre-`note` `ResolutionRecord` line still validates (same K6 pattern) |
| `test_emitted_schema_is_versioned_and_additive` | **[C-05/D-01]** | the emitted JSON Schema stays a versioned superset (carries `source_sha`) |
| `test_review_record_round_trips_with_set_field` | **[C-05]** | a SET additive field round-trips losslessly |
| `test_reporting_never_raises_when_transport_down` | **[E-01]** | a down central transport queues to the outbox, never throws into the heal loop (break-it documented) |
| `test_matched_rule_resolves_with_zero_backend_calls` | **[D-06]** | a matched promoted rule resolves a drift with ZERO backend calls (+ `resolved_by="rule"` audit marker) |
| `test_default_no_rules_is_additive_backend_for_everything` | **[D-06]** | default `rules=()` is additive — the backend still handles every drift |

### `test_corpus_selfcoverage.py` — self-coverage & dogfood
| Case | Lesson | Invariant |
|------|--------|-----------|
| `test_self_coverage_meets_committed_threshold` | **[H-02]** | engine public-symbol self-coverage stays ≥ the committed 95% floor |
| `test_every_coverage_waiver_carries_a_reason` | **[H-02/A-04]** | every coverage waiver justifies itself (losslessness explicit) |
| `test_unlisted_engine_module_is_detected_as_a_gap` | **[H-01/H-04]** | an UNLISTED `custodex/**` module's public symbol is detected as a gap and DROPS self-coverage |
| `test_dogfood_docs_are_in_sync` | **[CDM-07]** | the checked-in docs match the checked-in code (in-sync re-assertion) |
| `test_dogfood_docs_conform_to_layout_standard` | **[CDM-08]** | the checked-in docs satisfy the machine-checked Layout Standard |
| `test_dogfood_self_heals_on_a_copy` | **[CDM-07]** | the full self-heal LOOP works on the real project (on a temp copy) |

## "Break-it" provenance

For three top invariants, the author temporarily broke the fix, confirmed the
corpus reds, and reverted (the break is **not** committed). The exact break is
documented in each case's docstring:

- **[B-02]/[B-03]** human-region & llm-seeded lock — making `heal.locked_region_ids`
  return an empty set unlocks the protected body → `monitor --apply` re-authors it
  → both `test_human_region_never_auto_edited` and
  `test_llm_seeded_fill_then_lock_three_phase` red.
- **[E-01]** reporting-never-raises — removing/narrowing `HttpSink.emit`'s
  `except Exception` makes `emit` propagate the OSError →
  `test_reporting_never_raises_when_transport_down` reds.
- **[C-05]** schema back-compat — dropping the `= None` default on
  `ReviewRecord.source_sha` makes the legacy line a `ValidationError` →
  `test_pre_field_review_record_still_parses` reds.
- **[D-06]** zero-backend-calls — moving the rule check after `backend.propose`
  makes `spy.calls == 1` for a matched drift → the spy assertion reds.
- **[B-06]** pure-`llm` no-renderer authoring — reverting the `drift.py` B-06
  branch so a no-renderer `llm` region falls back to `UNHEALABLE` reds the
  re-author step of `test_pure_llm_no_renderer_authored_reauthor_idempotent_human_untouched`.

## Notes on stale / superseded lessons

None of the indexed invariants are stale. One refinement worth recording: the
B-02 human-region guarantee is enforced by **two** layers — a redundant `preserve`
set in `monitor.run` AND the modes-derived lock in `heal.locked_region_ids`. The
load-bearing one is the heal-layer lock (clearing only `monitor`'s `preserve`
does NOT red the guard); the corpus's break-it notes target the heal layer
accordingly.
