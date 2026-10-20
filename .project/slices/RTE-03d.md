# RTE-03d — zero backend calls on the mechanical path + the closure alarm

**Epic:** RTE (the apply-tier router)
**Depends on:** RTE-03a (index-aware heal), RTE-03b (`mechanical_docs`), RTE-03c
(the restraint) — all merged
**Constraints:** K2, K4, K5, K6, K7, K8, K10
**Status:** DONE

## Goal (validable)

**A mechanically-closable document costs zero tokens** — instrumented, not
asserted, with a backend that raises on any call. And an unattended close that did
not close must be LOUD.

End-to-end on a two-document repo with `apply_tiered: true`:

```
$ cdx check
routing: 1/2 document(s) mechanical, 1 delegated, 0 need human intent

$ cdx monitor --apply
guide: HASH -> FIX (applied)
prose-guide: HASH -> FIX
prose-guide: REGION -> FIX
closure: guide — HASH closed mechanically (no backend)
2 drift(s) remaining: prose-guide ...

$ grep "retry loop" prose.md
Why alpha matters to the caller: it is the identity used by the retry loop.
```

The human's authored WHY survives byte-for-byte and is still asked about next
cycle; the document the code can answer closed itself for free.

## Design

⟨R⟩ **The fix SHAPES must not widen.** Region-scoped for a `REGION`, whole-doc for
a `HASH` — exactly `MockBackend` rules 1 and 3. Collapsing them into one whole-doc
`render_corrected` per document would make a REGION close rewrite front-matter it
never touches today (`set_fingerprint_tiers`, `set_symbol_sigs`), which on a legacy
composite-only doc silently ADDS the digests `classify_change_severity` needs to
move a FUTURE HASH drift from `UNKNOWN` (NEEDS_INTENT) to `COSMETIC`
(CODE_DERIVED). **The unattended write would widen what it may next write
unattended.** It also keeps the ticket's `change_kind` honest and preserves the
`handled`/`records` lockstep `mcp/tools.py` zips `strict=True`.

⟨R⟩ **The engine uses the SAME region selector `detect` grades against**
(`_region_body`: `render_index` for a `source: index` template, else
`expected_region`). RTE-03a stopped heal CORRUPTING an index region; this stops the
engine WRITING one wrong. The two renderers must never diverge again.

⟨R⟩ **`preserve`/`modes` go to `apply_fix` only** (`_preserve_for`/`_modes_for`,
now shared by both paths) — proven a byte-level no-op in `render_corrected`, and one
enforcement point means a future B-02/B-03/RTE-04 guard is added once.

⟨R⟩ **D-06 keeps its precedence.** `rule_for` is evaluated BEFORE the engine
branch, so a verdict humans reached ≥K times is never overwritten by an engine
write. A rule match does NOT remove the document from `mechanical_docs`: with the
region-scoped shape a mechanical REGION close does not stamp `cdm.fingerprint`, so
it cannot bless anything the rule held.

⟨R⟩ **An unrenderable "mechanical" drift is a loud ESCALATE, never a silent FIX.**
Routing called it mechanical and the renderer could not produce it: that is a
contradiction a human must see (K8). A `FIX` carrying no fix would look handled in
the log while nothing was written.

⟨R⟩ **`ClosureRecord` lives in `monitor.py`, not `schema.py`** — an in-process
result detail, not a public artifact. `cdx schema` emits `ReviewRecord` alone, so
no `schema_version` bump is implied (K6). The durable trail is the `ReviewRecord`
it names.

⟨R⟩ **`record_id` is SINGULAR.** `new_record_id` hashes
`(doc_id, surface_hash, detected_at)` — no kind, no region — so N drifts closed on
one document in one run share ONE id. A tuple would be duplicates pretending to be
a set. Widening the id would change every existing record id and break the
doc-grain `cdx resolve` contract MCP-01 pinned.

⟨R⟩ **The alarm gates on `attempted`, never on `wrote`.** `apply_fix` returns
`False` for an ATTEMPTED write it DECLINED (a preserved id, a B-03 locked region),
which is precisely *"routing promised mechanical closure and the write boundary
silently refused"* — the case the alarm exists for. Gating on `wrote` would print
it as a dry-run preview and report success.

⟨R⟩ **No new exit code.** `verified` derives from the same recheck that already
drives the `remaining` gate, so an unverified closure always exits 1 there. The
deliverable is the MESSAGE naming the pathology, printed before the symptom — and
asserted verbatim, so it is killable.

⟨R⟩ **`verified` ignores `SUSPECT_LINK`.** A doc↔doc edge is handled by a pass that
never applies a fix, so it can legitimately stay open on a document whose code↔doc
drift closed cleanly. Counting it would fire the alarm on every healthy run with
docdeps on — and noise is how an alarm stops being read.

## Mutation verification (ralph loop) — 11/11 killed, 0 survivors (after closing 5 gaps)

First pass: **5 survivors.** Every one was a real test gap, closed with a test.

| # | mutation | first pass | after |
|---|---|---|---|
| Q1 | engine branch hoisted ABOVE `rule_for` | — | killed |
| Q2 | engine REGION fix widened to whole-doc | killed | killed |
| Q3 | `_region_body` drops the index branch | **SURVIVED** | killed |
| Q4 | unrenderable drift becomes a silent FIX-with-no-fix | **SURVIVED** | killed |
| Q5 | closure `attempted` derived from `wrote` | killed | killed |
| Q6 | `closures` unsorted | killed | killed |
| Q7 | `verified` counts `SUSPECT_LINK` | **SURVIVED** | killed |
| Q8a/b | `drift_kinds`/`evidence` in encounter order | **SURVIVED** | killed |
| Q9 | `engine_sourced` marker dropped | killed | killed |
| Q10 | CLI alarm gated on `wrote` | **SURVIVED** | killed |

⟨R-LEARNED⟩ **Q8 is the third appearance of one gap in this epic**: a fixture whose
facets are singletons (one drift kind, one evidence string) cannot defend
sortedness, exactly as one decorator per symbol could not defend source order
(RTE-02a) and equal bucket counts could not defend the tally labels (RTE-03b).
Closed by testing `Monitor._closures` directly with facts in REVERSE-sorted
encounter order, which kills the realistic refactor mutation
(`dict.fromkeys`, arrival order) **deterministically** — a plain `tuple(set)`
mutation is only killed probabilistically, since `str` hashing is randomized.

## EPIC-R

**FEAT-MONITOR-012**, **FEAT-RECORD-014** + **DEMO-126/127**;
`cdx trace --fail-on-gap` 268/268.

⟨R-CORRECTED⟩ **Three further rationales were refuted by the post-implementation
review, all verified first-hand before changing anything.**

1. **`--tiered` is not a subset of `--apply`** — it REPLACES the authority on the
   mechanical path. Reproduced: `--apply` with a declining backend writes nothing;
   `--apply --tiered` writes. Corrected in six places.
2. **A promoted D-06 rule needs the whole document withdrawn from the mechanical
   set.** The original ⟨R⟩ argued a region-scoped close cannot bless anything a rule
   held — true, and irrelevant: the HASH close is WHOLE-DOC and regenerates every
   known region, including the rule-held one. Reproduced (`rule-held region body
   survived? False`). The first design review recommended exactly this and was
   declined on that incomplete argument.
3. **`ClosureRecord.record_id` had to become `record_ids`.** The claim "N drifts on
   one document share ONE id" holds only under a FIXED injected clock; under
   `_default_now`'s microsecond precision the ids are DISTINCT and a singular field
   silently named the first of N.

Plus two defects that were not rationale errors:

4. **The fold must block by `doc_path`, not `doc_id`.** `MonitorConfig` accepts two
   documents on one file; closing the mechanical one rewrote the held one and
   stamped its fingerprint. Blocking by path SUBSUMES blocking by id (every drift
   carries its own document's path), so the separate id set was an equivalent
   mutant and was removed.
5. **`cdx sync-pr` / `open-docs-pr` must honour the operator's OWN `apply_tiered`.**
   Forcing `tiered=False` at every non-`cdx monitor` site left the docs-PR loop with
   no protection at all. The leak worth closing was config arriving BY OMISSION where
   the config is not the operator's — a remote agent's tool call, and the server's
   route over a CLONED repo. Those still force it off. **The distinction is whose
   config it is, not which function is called.**

⟨R-CORRECTED, second pass⟩ **The narrowing claim was pinned in TEN places, not six.**
The first correction pass missed four, including the two that matter most: the
scaffolded `config/cdmon/index.yaml` body in `templates_v2.py` — the ONLY
adopter-visible copy, and the comment someone reads before enabling the knob in CI —
and the `MonitorConfig.apply_tiered` field comment itself. Also corrected: the
`mcp/tools.py` parenthetical (its CONCLUSION survives — forcing tiered off keeps MCP
on the backend-authored path, which is never broader — only its premise was wrong)
and a test section header. The guard now covers BOTH declining verdicts, because
`INVALIDATE` ("does not affect this audience", K3) and `ESCALATE` ("a human must
decide") are different real cases and neither can hold the write once the engine
stops asking.

The adopter-facing text also said "NOTHING on it is written" for a held document,
which the suspect-link edge baseline contradicts. Corrected to name the exception and
why it is safe.

⟨REFUTED⟩ **"`cdx generate` now leaves a permanent `TODO: content for <id>` in an
index region."** Not permanent: `cdx monitor --apply` fills it correctly through the
index-aware path (verified — `TODO: content for 'idx'` → `| [Sib](sib.md) |`). Before
RTE-03a the scaffold path wrote a *wrong* table there instead; an honest TODO until
the first monitor run is strictly better than a silent lie that looks right.
