# RTE-03b — the mechanical fold + the three-way routing tally

**Epic:** RTE (the apply-tier router)
**Depends on:** RTE-01 (`ApplyTier`, `auto_routable_docs`) — merged
**Constraints:** K1, K6, K9, K10, K11
**Status:** DONE

## Goal (validable)

RTE-01 answered *"could this drift close itself?"*. RTE-03 turns the same fold
into the set an **unattended write is allowed to touch**, and that is a strictly
narrower question: *"could the ENGINE close this DOCUMENT, with no model consulted
at all?"* Make that number readable off `cdx check` before anything writes.

```
routing: 2/6 document(s) mechanical, 1 delegated, 3 need human intent
```

**Done when:**
- `docs_closable_by(report, tiers, *, require_actionable=False)` generalises the
  per-document fold; `auto_routable_docs` is a one-line delegate with a
  byte-unchanged contract; `mechanical_docs` folds over `CODE_DERIVED` alone.
- `AUTO_TIERS` is DERIVED from `is_auto`, never a literal.
- `summary()`'s routing line is three-way and still ONE appended line (K9).
- Pure — no clock, no I/O, no backend (K1/K10). No config knob, no write.
- Full gate green; four configs clean; dogfood rehealed.

## Design

⟨R⟩ **`require_actionable` exists because the vacuous member is harmless for
ROUTING and dangerous for CLOSING.** The fold is "nothing blocks", so a document
whose only drift is a `SUSPECT_LINK` is a member by vacuous truth. RTE-01
documented that as harmless — nothing on such a doc reaches the apply gate. RTE-03d
turns the SAME set into the closure set, where it becomes a phantom
`ClosureRecord(verified=True)`: a GREEN line for a document whose doc↔doc edge is
still open and was just `ESCALATE`'d. So the closing fold requires ≥1 qualifying
actionable drift; the routing fold keeps its vacuous truth and its exact output.

⟨R⟩ **`mechanical_docs` is strictly NARROWER than `auto_routable_docs`.**
`DELEGATED` routes AUTO but is prose a MODEL authors — RTE-04, and it carries a K11
widening that needs explicit human ratification. RTE-03 writes only what the engine
projects itself.

⟨R⟩ **`AUTO_TIERS` is derived, not restated.** A hand-written literal would be a
SECOND encoding of the route, free to drift from `is_auto` — the property that
actually drives the fold. One fact, one definition (K10).

⟨R⟩ **The tally's denominator is the ACTIONABLE documents, not all of them.** The
three buckets partition the documents that have something to close. A
suspect-link-only doc is excluded entirely: counting it as `mechanical` is the
phantom closure, and counting it as `delegated`/`held` invents work that does not
exist.

## Tests (TDD, red first — via `ImportError: cannot import name 'AUTO_TIERS'`)

`AUTO_TIERS` derived · the generalised fold over three different tier sets ·
`auto_routable_docs` byte-unchanged **including its vacuous member** ·
`mechanical_docs` rejecting a suspect-link-only doc · `mechanical_docs` strictly
narrower · a suspect link still not vetoing a mechanically-closable doc · the tally
asserted VERBATIM · the tally partitioning the actionable documents.

## Mutation verification (ralph loop) — 9/9 killed, 0 survivors (after closing 1 gap)

| # | mutation | result |
|---|---|---|
| N1 | `require_actionable` ignored (phantom closure returns) | killed |
| N2 | `require_actionable` always on (`auto_routable_docs` loses its vacuous member) | killed |
| N3 | `mechanical_docs` widened to `AUTO_TIERS` | killed |
| N4 | `AUTO_TIERS` hand-written to include `NEEDS_INTENT` | killed |
| N5 | fold per-DRIFT (drop the blocking subtraction) | killed |
| N6 | `SUSPECT_LINK` vetoes its document again | killed |
| N7 | tally denominator is ALL docs | killed |
| N8 | tally swaps `mechanical` and `delegated` | **SURVIVED → gap closed** |
| N9 | tally swaps `delegated` and `need human intent` | killed |

⟨R-LEARNED⟩ **N8 survived because both fixtures had `mechanical == delegated == 1`,
so swapping the labels changed no byte.** This is the same gap that let "sort the
decorators" survive RTE-02a's first pass (every fixture symbol had exactly one
decorator). Closed by making all three counts DISTINCT (2/1/3). A tally test whose
buckets are equal cannot defend its own labels.

## EPIC-R

**FEAT-DRIFT-014** + **DEMO-122**; `cdx trace --fail-on-gap` 262/262.
